"""正元智慧场馆预约系统（``sportvenue.westlake.edu.cn``）——游泳/球场只读接入。

为什么是独立模块
================
预约中心（``booking``）只覆盖自习室/研讨室/琴房等 17 类场地；**体育场馆与游泳
不在这里**（``booking types`` 看不到「体育场馆」，接口对无权限分类只返回空）。
2026-10-27 实测，真实入口是正元智慧的多租户场馆系统 ``sportvenue``。
完整侦查记录见 ``docs/sportvenue_notes.md``。

登录（四步，全部 requests 可自动化）
====================================
1. ``GET /site/cas/address``（带签名参数）→ 返回 ``/authcenter/toLoginPage``；
2. 跟到 ``iam.westlake.edu.cn/ac/#/index?lck=…&entityId=tycgyy``，用
   :func:`westlake_survival.iam.authenticate` 走完统一认证，拿回跳地址
   ``/authcenter/doOauth2?code=…``；
3. 跟这个地址的第 301+302 两跳，**302 的 Location 里带 ``uniToken``**
   （片段前的 query，可直接正则取）；
4. ``POST /site/cas/token`` 换业务 token，之后每个请求带 ``token`` 头。

签名
====
每个请求的 query 都要拼 ``appId`` / ``nonce``（32 位随机）/ ``timeStamp``
（毫秒）/ ``sign = md5("appId=…&nonce=…&timeStamp=…&key=…")``。``key`` 是从
前端混淆函数里还原的定值（见 :data:`SIGN_KEY`），不是账号凭据。

数据面（2026-10-27 实测）
========================
* :func:`scenes` —— ``GET /site/api/site/scene/list``，15 个场景（球场、次卡）。
* :func:`sites` —— ``POST /site/api/reserve/current/page``，某场景某日的场地
  列表，含 ``reserveStatus``（Y/N + 原因 + 错误码）。
* :func:`days` —— ``POST /site/api/reserve/cross/detail``，某场地逐日可约状态；
  目前每天都是 N，原因「表单规则未找到！！！」（40100082）。
* :func:`my_reservations` —— ``POST /site/api/reserve/reserveRecord``（进行中）
  与 ``historyRecord``（历史）。

坑
==
* 同一场地在两条接口上的不可约原因文案不同：``current/page`` 回
  「申请表单信息缺失」（401000316），``cross/detail`` 回「表单规则未找到！！！」
  （40100082）。两者都表示**服务端没有配好预约表单**，不是我们这边的问题。
* 场景里既有场地型（序号场地）也有**次卡型**（游泳次卡/健身次卡），后者的
  「场地」是场次（``siteName=游泳场次``），下单走次卡支付而不是按时段。
* ``/site/api/reserve/current/page`` 的 ``data`` 是**列表**、总数在 ``count``，
  不是常见分页信封。
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from datetime import date as _date
from datetime import datetime, timedelta
from html import unescape
from typing import Any
from urllib.parse import urljoin

import requests

from westlake_survival._net import DEFAULT_TIMEOUT
from westlake_survival.discovery import direct_session
from westlake_survival.exceptions import AuthError, WestlakeError

__all__ = [
    "SPORT_BASE",
    "DayStatus",
    "Scene",
    "Site",
    "cli_group",
    "days",
    "find_scene",
    "find_site",
    "my_reservations",
    "scenes",
    "sites",
]

SPORT_BASE = "https://sportvenue.westlake.edu.cn"
SPORT_HOME = f"{SPORT_BASE}/"

#: 前端签名用的公开 appId（正元多租户固定值，非账号凭据）。
APP_ID = "1497016617475903488"
#: ``getKeys()`` 混淆还原出来的签名 key（所有客户共用，非账号凭据）。
SIGN_KEY = "57325972627c40bd8c7729693d293705"
#: nonce 字符表（与前端一致，去掉了易混淆的 I/L/O/U/V）。
_NONCE_CHARS = "ABCDEFGHJKMNPQRSTWXYZabcdefhijkmnprstwxyz0123456789"

_SESSION: requests.Session | None = None
_TOKEN: str = ""


@dataclass
class Scene:
    """一个场馆场景（如「C16羽毛球场」「游泳次卡」）。"""

    uuid: str
    name: str
    related_type: str = ""
    description: str = ""

    def __str__(self) -> str:  # noqa: D105 - 便于 CLI 直接打印
        return f"{self.name}（{self.uuid}）"


@dataclass
class Site:
    """场景下的一个场地/场次。"""

    uuid: str
    name: str
    site_type: str = "DEV"
    location: str = ""
    open_state: int | None = None
    bookable: bool = False
    reason: str = ""
    code: int | None = None

    def __str__(self) -> str:  # noqa: D105
        tail = "可约" if self.bookable else f"不可约（{self.reason or '原因未知'}）"
        return f"{self.name}｜{self.location}｜{tail}"


@dataclass
class DayStatus:
    """某场地某一天的可约状态。"""

    day: str
    bookable: bool
    reason: str = ""
    code: int | None = None
    ranges: list[Any] = field(default_factory=list)


def _sign() -> dict[str, str]:
    """生成一次请求的签名参数（每次请求都重新生成）。"""
    nonce = "".join(random.choice(_NONCE_CHARS) for _ in range(32))
    stamp = str(int(datetime.now().timestamp() * 1000))
    raw = f"appId={APP_ID}&nonce={nonce}&timeStamp={stamp}&key={SIGN_KEY}"
    return {
        "appId": APP_ID,
        "nonce": nonce,
        "timeStamp": stamp,
        "sign": hashlib.md5(raw.encode()).hexdigest(),
    }


def _extract_uni_token(session: requests.Session, start_url: str) -> str:
    """跟随 doOauth2 的重定向链，从 302 的 Location 里取 ``uniToken``。

    实测链路是 301（http→https）再 302（``/?uniToken=…``）；片段不会被自动
    跟随，所以必须逐跳 ``allow_redirects=False`` 手工走。
    """
    url = start_url
    for _ in range(6):
        response = session.get(url, timeout=DEFAULT_TIMEOUT, allow_redirects=False)
        location = response.headers.get("Location", "")
        if "uniToken=" in location:
            token = location.split("uniToken=", 1)[1].split("&", 1)[0].split("#", 1)[0]
            return token
        if not location:
            break
        url = location if location.startswith("http") else urljoin(url, location)
    raise WestlakeError(
        "场馆系统未下发 uniToken——统一认证可能已成功但回跳被改；"
        f"最后一跳 {url[:80]}"
    )


def _login() -> tuple[requests.Session, str]:
    """统一密码 → IAM CAS → 场馆系统业务 token。"""
    from westlake_survival import iam
    from westlake_survival.sso import read_credentials

    try:
        user, password = read_credentials()
    except Exception as exc:  # noqa: BLE001 - 缺凭据统一转成 AuthError
        raise AuthError("未配置统一凭据；先在网页「设置」页或 westlake setup 配置") from exc

    session = direct_session()
    session.headers["User-Agent"] = "Mozilla/5.0 (westlake-survival sportvenue)"

    entry = session.get(
        f"{SPORT_BASE}/site/cas/address",
        params={
            **_sign(),
            "redirectUrl": SPORT_HOME,
            "queryParam": _b64(SPORT_HOME),
        },
        timeout=DEFAULT_TIMEOUT,
        verify=False,
    )
    try:
        login_page = str(entry.json().get("data") or "")
    except ValueError as exc:
        raise WestlakeError(f"场馆系统 CAS 入口返回非 JSON：{entry.text[:120]}") from exc
    if not login_page:
        raise WestlakeError("场馆系统未给出 CAS 登录地址")

    session, location = iam.authenticate(login_page, user, password, session=session)
    if not location:
        raise AuthError("场馆系统统一认证未给出回跳地址（可能已处于登录态）")

    uni_token = _extract_uni_token(session, unescape(location))
    response = session.post(
        f"{SPORT_BASE}/site/cas/token",
        params=_sign(),
        json={"platForm": "CAS", "client": "PC", "token": uni_token},
        timeout=DEFAULT_TIMEOUT,
        verify=False,
    )
    try:
        payload = response.json()
    except ValueError as exc:
        raise WestlakeError(f"场馆系统 token 接口返回非 JSON：{response.text[:120]}") from exc
    data = payload.get("data") or {}
    token = str(data.get("token") or "")
    if not token:
        raise AuthError(f"场馆系统未下发 token：{payload.get('message') or response.text[:80]}")
    return session, token


def _b64(text: str) -> str:
    import base64

    return base64.b64encode(text.encode()).decode()


def _client() -> tuple[requests.Session, str]:
    """惰性登录并缓存（进程内复用，换进程重登）。"""
    global _SESSION, _TOKEN
    if _SESSION is None or not _TOKEN:
        _SESSION, _TOKEN = _login()
    return _SESSION, _TOKEN


def _call(method: str, path: str, *, params: dict | None = None, body: dict | None = None) -> Any:
    """带签名与 token 的请求；登录过期时重登一次。"""
    global _SESSION, _TOKEN
    for attempt in (0, 1):
        session, token = _client()
        url = f"{SPORT_BASE}{path}"
        kwargs: dict[str, Any] = {"timeout": DEFAULT_TIMEOUT, "verify": False}
        if body is not None:
            kwargs["json"] = body
        response = session.request(
            method,
            url,
            params={**_sign(), **(params or {})},
            headers={"token": token},
            **kwargs,
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise WestlakeError(f"场馆系统 {path} 返回非 JSON：{response.text[:120]}") from exc
        code = payload.get("code")
        if code == 0:
            return payload.get("data")
        message = str(payload.get("message") or "")
        if "登录过期" in message or payload.get("errorCode") == 1130002:
            if attempt == 0:
                _SESSION, _TOKEN = None, ""
                continue
            raise AuthError("场馆系统会话失效，重登后仍被拒绝")
        raise WestlakeError(f"场馆系统 {path} 失败（{code}）：{message or '未知错误'}")
    raise AuthError("场馆系统会话失效")


def scenes() -> list[Scene]:
    """全部场景（实测 15 个：球场若干 + 会员卡服务 + 游泳次卡/健身次卡）。"""
    rows = _call("GET", "/site/api/site/scene/list") or []
    return [
        Scene(
            uuid=str(row.get("uuid") or ""),
            name=str(row.get("sceneName") or ""),
            related_type=str(row.get("relatedType") or ""),
            description=str(row.get("description") or ""),
        )
        for row in rows
        if isinstance(row, dict)
    ]


def find_scene(selector: str) -> Scene:
    """按 uuid 或名称子串唯一定位场景（零命中/多命中都报候选）。"""
    all_scenes = scenes()
    hits = [s for s in all_scenes if selector == s.uuid] or [
        s for s in all_scenes if selector in s.name
    ]
    if not hits:
        names = "、".join(s.name for s in all_scenes)
        raise WestlakeError(f"没找到场景「{selector}」；可选：{names}")
    if len(hits) > 1:
        names = "、".join(s.name for s in hits)
        raise WestlakeError(f"「{selector}」命中多个场景：{names}，请写全名或给 uuid")
    return hits[0]


def _site_from_row(row: dict) -> Site:
    status = row.get("reserveStatus") or {}
    location = row.get("siteLocation") or {}
    return Site(
        uuid=str(row.get("uuid") or ""),
        name=str(row.get("siteName") or ""),
        site_type=str(row.get("siteType") or "DEV"),
        location=str(location.get("location") or location.get("roomName") or ""),
        open_state=row.get("openState"),
        bookable=str(status.get("reserveStatus") or "").upper() == "Y",
        reason=str(status.get("reserveStatusReason") or ""),
        code=status.get("code"),
    )


def sites(scene: str | Scene, day: _date | str | None = None) -> list[Site]:
    """某场景某日的场地列表（含每条自身能否预约）。

    ``day`` 缺省为明天——今天多半已经排满或已过开放时段，看明天更有信息量。
    """
    scene_uuid = scene.uuid if isinstance(scene, Scene) else find_scene(scene).uuid
    when = _as_day(day or (_date.today() + timedelta(days=1)))
    rows = _call(
        "POST",
        "/site/api/reserve/current/page",
        body={
            "sceneUuid": scene_uuid,
            "reserveDate": when.isoformat(),
            "pageNum": 1,
            "pageSize": 100,
            "resvKind": "CURRENT_RESERVE",
        },
    )
    return [_site_from_row(row) for row in (rows or []) if isinstance(row, dict)]


def find_site(scene: str | Scene, selector: str, day: _date | str | None = None) -> Site:
    """在场景内按 uuid 或名称子串唯一定位场地。"""
    rows = sites(scene, day)
    hits = [s for s in rows if selector == s.uuid] or [s for s in rows if selector in s.name]
    if not hits:
        names = "、".join(s.name for s in rows) or "（当日无场地）"
        raise WestlakeError(f"场景内没找到场地「{selector}」；当日可选：{names}")
    if len(hits) > 1:
        names = "、".join(s.name for s in hits)
        raise WestlakeError(f"「{selector}」命中多个场地：{names}，请写全名或给 uuid")
    return hits[0]


def days(
    site: Site | str,
    *,
    start: _date | str | None = None,
    end: _date | str | None = None,
    site_type: str = "DEV",
) -> list[DayStatus]:
    """逐日可约状态。

    ``site`` 传 :class:`Site` 或 uuid；只给 uuid 时默认 ``siteType="DEV"``。
    返回每天一条：``bookable`` 为 False 时 ``reason`` 是系统原话（当前普遍是
    「表单规则未找到！！！」）。
    """
    site_uuid = site.uuid if isinstance(site, Site) else str(site)
    site_type = site.site_type if isinstance(site, Site) else site_type
    first = _as_day(start or _date.today())
    last = _as_day(end or (first + timedelta(days=13)))
    if last < first:
        raise WestlakeError("结束日期早于开始日期")
    data = _call(
        "POST",
        "/site/api/reserve/cross/detail",
        body={
            "siteUuid": site_uuid,
            "siteType": site_type,
            "reserveStartDate": first.isoformat(),
            "reserveEndDate": last.isoformat(),
        },
    )
    rows = (data or {}).get("groupReserveVos") or []
    out: list[DayStatus] = []
    for row in rows:
        status = row.get("reserveStatus") or {}
        out.append(
            DayStatus(
                day=str(row.get("currentDate") or ""),
                bookable=str(status.get("reserveStatus") or "").upper() == "Y",
                reason=str(status.get("reserveStatusReason") or ""),
                code=status.get("code"),
                ranges=status.get("availableRange") or [],
            )
        )
    return out


def my_reservations(*, history: bool = False, limit: int = 20) -> list[dict]:
    """我的预约（``history=True`` 取历史记录）。字段原样返回，时间已由服务端给。"""
    path = "/site/api/reserve/historyRecord" if history else "/site/api/reserve/reserveRecord"
    rows = _call("POST", path, body={"pageNum": 1, "pageSize": max(1, limit)})
    return [row for row in (rows or []) if isinstance(row, dict)]


def _as_day(value: _date | str) -> _date:
    if isinstance(value, _date):
        return value
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError as exc:
        raise WestlakeError(f"日期要写成 YYYY-MM-DD，收到 {value!r}") from exc


def _cli():
    import functools

    import click

    from westlake_survival.exceptions import WestlakeError

    def handle(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except WestlakeError as exc:
                click.secho(f"错误：{exc}", fg="red", err=True)
                raise SystemExit(1) from exc

        return wrapper

    @click.group(
        name="sport",
        help="体育场馆/游泳预约系统（正元 sportvenue）——场景、场地、逐日可约、我的预约。",
    )
    def group() -> None:
        """游泳与球场不在预约中心，入口是独立的正元场馆系统。"""

    @group.command(name="scenes")
    @handle
    def scenes_cmd() -> None:
        """全部场景（球场 / 会员卡 / 游泳次卡）。"""
        for scene in scenes():
            click.echo(f"{scene.name}\t{scene.uuid}")

    @group.command(name="sites")
    @click.argument("scene")
    @click.option("--date", "day", default=None, help="日期 YYYY-MM-DD（缺省明天）")
    @handle
    def sites_cmd(scene: str, day: str | None) -> None:
        """某场景某日的场地与可约状态。"""
        rows = sites(scene, day)
        if not rows:
            click.echo("该场景当日没有场地数据。")
            return
        for site in rows:
            state = "可约" if site.bookable else f"不可约：{site.reason or '原因未知'}"
            click.echo(f"{site.name}\t{site.location}\t{state}\t{site.uuid}")

    @group.command(name="days")
    @click.argument("scene")
    @click.argument("site")
    @click.option("--start", "start_day", default=None, help="起始日期 YYYY-MM-DD（缺省今天）")
    @click.option("--end", "end_day", default=None, help="结束日期 YYYY-MM-DD（缺省起始+13 天）")
    @handle
    def days_cmd(scene: str, site: str, start_day: str | None, end_day: str | None) -> None:
        """某场地逐日可约状态与不可约原因。"""
        target = find_site(scene, site)
        rows = days(target, start=start_day, end=end_day)
        if not rows:
            click.echo("没有返回逐日状态。")
            return
        for item in rows:
            state = "可约" if item.bookable else f"不可约：{item.reason or '原因未知'}"
            click.echo(f"{item.day}\t{state}")
        if all(not item.bookable for item in rows):
            click.echo("", err=True)
            click.echo(
                "提示：全部不可约且原因一致时，多半是服务端没有配置预约表单，"
                "与本机环境无关（见 docs/sportvenue_notes.md）。",
                err=True,
            )

    @group.command(name="mine")
    @click.option("--history", is_flag=True, help="看历史记录而不是进行中")
    @click.option("--limit", type=int, default=20, show_default=True)
    @handle
    def mine_cmd(history: bool, limit: int) -> None:
        """我的场馆预约。"""
        rows = my_reservations(history=history, limit=limit)
        if not rows:
            click.echo("没有记录。")
            return
        for row in rows:
            click.echo(
                "{date}\t{scene}/{site}\t{state}".format(
                    date=row.get("reserveDate") or row.get("createTime") or "",
                    scene=row.get("sceneName") or "",
                    site=row.get("siteName") or "",
                    state=row.get("reserveState") or row.get("state") or "",
                )
            )

    return group


cli_group = _cli()
