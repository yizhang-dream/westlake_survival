"""预约中心（``booking.westlake.edu.cn/yy-sys``）——场馆 / 教室 / 研讨室预约。

登录
====
预约中心是 Infoplus 的预约平台（SPA + GraphQL），OIDC 客户端由平台自己实现：
``https://booking.westlake.edu.cn/sso/oauth2/authorize``（client_id
``VF1QlnZhbjLnSM33THW6``，隐式流 ``response_type=id_token token``）。流程：

1. :func:`westlake_survival.iam.login_for` 用统一密码走完 IAM CAS，会话落到
   ``requests.Session``（预约中心的 ``JSESSIONID`` / ``usk`` 等 cookie）；
2. 带着会话再请求 authorize，303 的 ``Location`` 片段里带 ``access_token``
   （32 位）；片段不会被跟随，所以必须 ``allow_redirects=False`` 手动取；
3. 之后所有 ``/bus/graphql/me`` 请求加 ``Authorization: Bearer <token>``。

数据面（2026-10-26 实测）
========================
* :func:`visible_types` —— ``findResourcesTypeAllByAccountForDisplay``，即首页
  「我能预约的分类」；账号没有权限的分类不会出现（例如本账号看不到
  「体育场馆」，见 :func:`diagnose_sports`）。
* :func:`resources` —— ``findResourcesAllByAccount``（可带 ``bookDate``）。
* :func:`free_slots` —— 空闲时段。服务端**没有**可用的「按日期列占用」查询：
  ``findAppointmentInformationAllForSeparation`` 的 ``appointmentDate`` 参数
  实测被忽略（永远返回全量历史），``filter`` 参数会抛空指针。所以空闲网格
  改为逐格调 ``checkResourceBookDateAndBookTime``（实测一次调用 ~20ms，
  单房间单日 28 格约 0.2 秒），以服务端判定为准。
* :func:`check` —— ``checkResourceBookDateAndBookTime``，提交前校验，
  ``errcode == "0"`` 表示这一段可约。
* :func:`available_days` —— ``findResourcesListBookingDetails``，按天的
  「可预约 / 已满」状态（快，用来挑日期）。
* :func:`book` —— ``saveAppointmentInformation``（**写操作**，会真实占场地）。
* :func:`cancel` —— ``updateAppointmentInformationState``（写操作）。
* :func:`my_bookings` —— ``findAppointmentInformationAllForSelf``。

坑
==
* GraphQL ``Date`` 标量只吃 epoch 毫秒（int），字符串会 coercion 失败；
  行内字面量更是要求 ``IntValue``，所以日期一律走变量。
* ``findResourcesAllByAccount`` 的 ``typeId`` 过滤不稳，按分类筛资源请用
  ``findResourcesAllNoPagination`` 或本地按 ``resources_type_name`` 过滤。
* 我账号没有权限时接口不报错，只是返回空列表——「查不到」和「没权限」要
  分开验证：先看 :func:`visible_types`，再看 :func:`resources`。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date as _date
from datetime import datetime
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from westlake_survival._net import DEFAULT_TIMEOUT
from westlake_survival.discovery import direct_session
from westlake_survival.exceptions import AuthError, WestlakeError

__all__ = [
    "BOOKING_BASE",
    "BOOKING_HOME",
    "Booking",
    "Resource",
    "ResourceType",
    "Slot",
    "available_days",
    "book",
    "cancel",
    "check",
    "cli_group",
    "diagnose_sports",
    "find",
    "free_slots",
    "my_bookings",
    "resources",
    "visible_types",
]

BOOKING_BASE = "https://booking.westlake.edu.cn"
BOOKING_HOME = f"{BOOKING_BASE}/yy-sys/"
BOOKING_CLIENT_ID = "VF1QlnZhbjLnSM33THW6"
BOOKING_REDIRECT_URI = f"{BOOKING_BASE}/yy-sys/oidc-callback"
BOOKING_SCOPE = "data openid process task app submit process_edit start profile privilege"
GRAPHQL_ME = f"{BOOKING_BASE}/bus/graphql/me"

#: 预约开放时间（分类级规则，取不到时兜底）。
DEFAULT_OPEN = "08:00"
DEFAULT_CLOSE = "22:00"
DEFAULT_STEP = 30

_SESSION: requests.Session | None = None
_TOKEN: str = ""


def _auth_url(state: str = "westlake-survival", nonce: str = "westlake-survival") -> str:
    """预约中心的 OIDC 授权地址（隐式流，令牌在 303 的片段里）。"""
    return f"{BOOKING_BASE}/sso/oauth2/authorize?" + urlencode(
        {
            "client_id": BOOKING_CLIENT_ID,
            "redirect_uri": BOOKING_REDIRECT_URI,
            "response_type": "id_token token",
            "scope": BOOKING_SCOPE,
            "state": state,
            "nonce": nonce,
        }
    )


def _login(user: str, password: str) -> tuple[requests.Session, str]:
    """统一密码 → IAM CAS → 预约中心 OIDC access_token。"""
    from westlake_survival import iam

    session = direct_session()
    iam.login_for(_auth_url(), user, password, session=session)
    response = session.get(_auth_url(), timeout=DEFAULT_TIMEOUT, allow_redirects=False)
    location = response.headers.get("Location", "")
    fragment = parse_qs(urlparse(location).fragment)
    token = (fragment.get("access_token") or [""])[0]
    if not token:
        raise AuthError(
            "预约中心未下发 access_token（最终跳转 "
            f"{urlparse(location).path or location[:80]}），登录态可能未建立。"
        )
    return session, token


def _session() -> tuple[requests.Session, str]:
    """惰性登录并缓存会话（进程内复用，换进程重登）。"""
    global _SESSION, _TOKEN
    if _SESSION is None or not _TOKEN:
        from westlake_survival.sso import creds

        user, password = creds.read_credentials()
        _SESSION, _TOKEN = _login(user, password)
    return _SESSION, _TOKEN


def reset() -> None:
    """丢掉缓存会话（换账号或令牌过期后调用）。"""
    global _SESSION, _TOKEN
    _SESSION = None
    _TOKEN = ""


def _gql(query: str, variables: dict | None = None) -> dict:
    """打 ``/bus/graphql/me``，返回 ``data``；``errors`` 转成异常。"""
    session, token = _session()
    response = session.post(
        GRAPHQL_ME,
        json={"query": query, "variables": variables or {}},
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=DEFAULT_TIMEOUT,
    )
    try:
        payload = response.json()
    except ValueError as exc:  # pragma: no cover - 网关返回非 JSON
        raise WestlakeError(f"预约中心返回非 JSON（HTTP {response.status_code}）") from exc
    errors = payload.get("errors") or []
    if errors:
        first = errors[0] or {}
        extensions = first.get("extensions") or {}
        detail = extensions.get("detail") or first.get("message") or str(first)
        raise WestlakeError(f"预约中心接口报错：{detail}")
    data = payload.get("data")
    if data is None:
        raise WestlakeError("预约中心接口返回空数据")
    return data


def _date_ms(day: str | _date) -> int:
    """``YYYY-MM-DD`` → 本地零点 epoch 毫秒（GraphQL Date 标量只吃毫秒）。"""
    if isinstance(day, _date):
        day = day.isoformat()
    local = datetime.now().astimezone().tzinfo
    parsed = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=local)
    return int(parsed.timestamp() * 1000)


def _minutes(text: str) -> int:
    """``HH:MM`` → 当日分钟数。"""
    hour, minute = text.strip().split(":")[:2]
    return int(hour) * 60 + int(minute)


def _hhmm(total: int) -> str:
    """当日分钟数 → ``HH:MM``。"""
    return f"{total // 60:02d}:{total % 60:02d}"


@dataclass
class ResourceType:
    """一个预约分类（首页卡片）。"""

    id: str
    name: str
    state: int = 0
    open_time: str = DEFAULT_OPEN
    close_time: str = DEFAULT_CLOSE
    step: int = DEFAULT_STEP

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "state": self.state,
            "open_time": self.open_time,
            "close_time": self.close_time,
            "step": self.step,
        }


@dataclass
class Resource:
    """一个可预约资源（房间 / 场地 / 座位区）。"""

    id: str
    name: str
    type_name: str = ""
    type_id: str = ""
    building: str = ""
    floor: str = ""
    campus: str = ""
    capacity: str = ""
    number: str = ""
    state: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "type_name": self.type_name,
            "building": self.building,
            "floor": self.floor,
            "campus": self.campus,
            "capacity": self.capacity,
            "state": self.state,
        }


@dataclass
class Slot:
    """一段可预约时间。"""

    start: str
    end: str
    resource_id: str = ""
    resource_name: str = ""

    def to_dict(self) -> dict:
        return {"start": self.start, "end": self.end, "resource": self.resource_name}


@dataclass
class Booking:
    """一条我的预约。"""

    id: str
    resource_name: str = ""
    day: str = ""
    start: str = ""
    end: str = ""
    state: str = ""
    appointment_state: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "resource": self.resource_name,
            "date": self.day,
            "start": self.start,
            "end": self.end,
            "state": self.state,
            "appointment_state": self.appointment_state,
        }


def visible_types() -> list[ResourceType]:
    """我能预约的分类（首页可见卡片）。"""
    data = _gql(
        "{ findResourcesTypeAllByAccountForDisplay"
        " { id resources_name state start_time end_time time_interval } }"
    )
    rows = data.get("findResourcesTypeAllByAccountForDisplay") or []
    items = []
    for row in rows:
        items.append(
            ResourceType(
                id=str(row.get("id") or ""),
                name=str(row.get("resources_name") or ""),
                state=int(row.get("state") or 0),
                open_time=str(row.get("start_time") or DEFAULT_OPEN),
                close_time=str(row.get("end_time") or DEFAULT_CLOSE),
                step=int(str(row.get("time_interval") or DEFAULT_STEP).strip() or DEFAULT_STEP),
            )
        )
    return items


def _all_resources() -> list[Resource]:
    """全校资源（不分权限，含停用项；用于按分类取名与排查）。"""
    data = _gql(
        "{ findResourcesAllNoPagination"
        " { id resources_name resources_type_id resources_type_name"
        "   campus_name building_name floor_name capacity resources_number state } }"
    )
    rows = data.get("findResourcesAllNoPagination") or []
    out = []
    for row in rows:
        out.append(
            Resource(
                id=str(row.get("id") or ""),
                name=str(row.get("resources_name") or ""),
                type_name=str(row.get("resources_type_name") or ""),
                type_id=str(row.get("resources_type_id") or ""),
                building=str(row.get("building_name") or ""),
                floor=str(row.get("floor_name") or ""),
                campus=str(row.get("campus_name") or ""),
                capacity=str(row.get("capacity") or ""),
                number=str(row.get("resources_number") or ""),
                state=int(row.get("state") or 0),
            )
        )
    return out


def resources(type_name: str | None = None, keyword: str | None = None) -> list[Resource]:
    """我能预约的资源；``type_name`` 按分类名精确匹配，``keyword`` 模糊匹配名称。

    只返回 :func:`visible_types` 里的分类（即真有权限的分类），避免把
    「全校有但你没权限」的场地误当成可约。
    """
    allowed = {t.name for t in visible_types()}
    items = _all_resources()
    if type_name:
        if type_name not in allowed:
            raise WestlakeError(
                f"账号没有「{type_name}」的预约权限；当前可约分类："
                + "、".join(sorted(allowed))
            )
        items = [i for i in items if i.type_name == type_name]
    else:
        items = [i for i in items if i.type_name in allowed]
    if keyword:
        items = [i for i in items if keyword in i.name or keyword in i.building]
    return [i for i in items if i.state == 0]


def find(resource_id: str) -> Resource | None:
    """按 id 取一个资源。"""
    for item in _all_resources():
        if item.id == resource_id:
            return item
    return None


def _match(selector: str) -> Resource:
    """把「房间名 / id 前缀 / 关键词」解析成唯一资源。"""
    if not selector:
        raise WestlakeError("缺少资源（房间名或 id）。")
    items = resources()
    exact = [i for i in items if i.id == selector]
    if exact:
        return exact[0]
    prefix = [i for i in items if i.id.startswith(selector)]
    if len(prefix) == 1:
        return prefix[0]
    hits = [i for i in items if selector in i.name]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise WestlakeError(f"没有匹配「{selector}」的可预约资源。")
    names = "、".join(f"{i.name}({i.id[:8]})" for i in hits[:8])
    raise WestlakeError(f"「{selector}」匹配到 {len(hits)} 个资源，请写全名或 id：{names}")


def available_days(resource_id: str, start: str, end: str) -> list[dict]:
    """某资源在 ``start..end``（含端）内每一天的可约状态。

    返回 ``[{"date": "2026-10-27", "code": "0", "name": "可预约"}, …]``；
    这是服务端按天算好的状态，比逐格问快得多，用来挑日期。
    """
    query = (
        "query($ids:[ID]!,$sd:String!,$ed:String!){"
        " findResourcesListBookingDetails(resourceIdList:$ids, startDate:$sd, endDate:$ed){"
        " id resourceDateStatusList { resource_date status_code status_name_cn } } }"
    )
    data = _gql(query, {"ids": [resource_id], "sd": start, "ed": end})
    rows = data.get("findResourcesListBookingDetails") or []
    out = []
    for row in rows:
        for item in row.get("resourceDateStatusList") or []:
            out.append(
                {
                    "date": str(item.get("resource_date") or ""),
                    "code": str(item.get("status_code") or ""),
                    "name": str(item.get("status_name_cn") or ""),
                }
            )
    return out


def free_slots(
    resource_id: str,
    day: str,
    *,
    start: str | None = None,
    end: str | None = None,
    step: int | None = None,
    duration: int | None = None,
) -> list[Slot]:
    """某资源某天的空闲时段（逐格问服务端，``errcode == 0`` 才算空闲）。

    服务端没有「按日期列占用」的查询，所以这里按分类的开放时间切格，
    逐格调 :func:`check`——实测每格约 20ms，单房间单日 28 格约 0.2 秒。

    ``duration`` 给定分钟数时只返回「连续空闲够长」的窗口（首尾相接）。
    """
    resource = find(resource_id)
    type_name = resource.type_name if resource else ""
    open_time, close_time, default_step = DEFAULT_OPEN, DEFAULT_CLOSE, DEFAULT_STEP
    for item in visible_types():
        if item.name == type_name:
            open_time, close_time, default_step = item.open_time, item.close_time, item.step
            break
    open_min = _minutes(start or open_time)
    close_min = _minutes(end or close_time)
    step = step or default_step or DEFAULT_STEP
    name = resource.name if resource else ""

    slots: list[Slot] = []
    cursor = open_min
    while cursor + step <= close_min:
        lo, hi = _hhmm(cursor), _hhmm(cursor + step)
        verdict = check(resource_id, day, lo, hi)
        if str(verdict.get("errcode")) == "0":
            slots.append(Slot(start=lo, end=hi, resource_id=resource_id, resource_name=name))
        cursor += step
    if not duration:
        return slots

    need = max(1, duration // step)
    windows: list[Slot] = []
    for index in range(len(slots) - need + 1):
        window = slots[index:index + need]
        if all(window[i].end == window[i + 1].start for i in range(len(window) - 1)):
            windows.append(
                Slot(start=window[0].start, end=window[-1].end,
                     resource_id=resource_id, resource_name=name)
            )
    return windows


def check(resource_id: str, day: str, start: str, end: str) -> dict:
    """提交前校验一段预约（返回 ``errcode`` / ``msg``）。"""
    query = (
        "query($r:String,$bd:String,$bs:String,$be:String,$src:String){"
        " checkResourceBookDateAndBookTime(resourceId:$r, bookDate:$bd,"
        " bookStartTime:$bs, bookEndTime:$be, checkSource:$src){"
        " errcode msg msg_en appointmentId } }"
    )
    data = _gql(
        query,
        {"r": resource_id, "bd": day, "bs": start, "be": end, "src": "pc"},
    )
    return data.get("checkResourceBookDateAndBookTime") or {}


def book(
    selector: str,
    day: str,
    start: str,
    end: str,
    *,
    theme: str = "",
    remark: str = "",
    people: int | None = None,
    dry_run: bool = False,
) -> dict:
    """创建一条预约（**写操作**）。

    ``selector`` 可以是房间全名、名称关键词或 id。``dry_run=True`` 只做
    :func:`check` 不提交。
    """
    resource = _match(selector)
    verdict = check(resource.id, day, start, end)
    if str(verdict.get("errcode")) != "0":
        raise WestlakeError(f"该时段不可约：{verdict.get('msg') or verdict}")
    if dry_run:
        return {"dry_run": True, "resource": resource.to_dict(), "date": day,
                "start": start, "end": end, "check": verdict}
    model = {
        "resources_id": resource.id,
        "appointment_date": day,
        "start_time": start,
        "end_time": end,
        "theme": theme or f"{resource.name} 预约",
        "remark": remark,
        "appointment_source": "pc",
    }
    if people:
        model["person_times"] = str(people)
    query = (
        "mutation($m:InputAppointmentInformation!){"
        " saveAppointmentInformation(model:$m){"
        " errcode msg msg_en ids appointmentId processURL auditStatus } }"
    )
    data = _gql(query, {"m": model})
    result = data.get("saveAppointmentInformation") or {}
    if str(result.get("errcode")) != "0":
        raise WestlakeError(f"预约失败：{result.get('msg') or result}")
    return result


def cancel(appointment_id: str, *, reason: str = "") -> dict:
    """取消一条预约（**写操作**）。

    取消就是把 ``state`` 置成 ``"3"``（实测：取消后 ``state=3``，
    ``appointment_state`` 保留原值 2）。
    """
    query = (
        "mutation($id:ID!,$state:String!,$reason:String){"
        " updateAppointmentInformationState(id:$id,state:$state,reason:$reason){"
        " errcode msg msg_en } }"
    )
    data = _gql(query, {"id": appointment_id, "state": "3", "reason": reason})
    return data.get("updateAppointmentInformationState") or {}


def my_bookings() -> list[Booking]:
    """我的预约。

    用 ``findAppointmentInformationAllForAccount``：``ForSelf`` 同名查询在本
    账号下恒返回空列表（实测创建成功仍查不到），ForAccount 才列出本人记录。
    """
    query = (
        "{ findAppointmentInformationAllForAccount(first:100, offset:0){"
        " edges { node { id appointment_date start_time end_time state"
        " appointment_state resources_name } } } }"
    )
    data = _gql(query)
    rows = ((data.get("findAppointmentInformationAllForAccount") or {}).get("edges")) or []
    out = []
    for edge in rows:
        node = edge.get("node") or {}
        out.append(
            Booking(
                id=str(node.get("id") or ""),
                resource_name=str(node.get("resources_name") or ""),
                day=str(node.get("appointment_date") or ""),
                start=str(node.get("start_time") or ""),
                end=str(node.get("end_time") or ""),
                state=str(node.get("state") or ""),
                appointment_state=str(node.get("appointment_state") or ""),
            )
        )
    return out


def diagnose_sports() -> dict:
    """体育场馆（含游泳）为什么约不了——把可见分类、类型状态、资源数摆出来。"""
    visible = {t.name for t in visible_types()}
    all_types = _gql(
        "{ findResourcesTypeAll { id resources_name state } }"
    ).get("findResourcesTypeAll") or []
    sports = [
        {"name": str(t.get("resources_name") or ""), "state": int(t.get("state") or 0)}
        for t in all_types
        if any(k in str(t.get("resources_name") or "") for k in ("体育", "球场", "球馆", "泳"))
    ]
    counts: dict[str, int] = {}
    enabled: dict[str, int] = {}
    for item in _all_resources():
        if item.type_name in {s["name"] for s in sports}:
            counts[item.type_name] = counts.get(item.type_name, 0) + 1
            if item.state == 0:
                enabled[item.type_name] = enabled.get(item.type_name, 0) + 1
    return {
        "visible_types": sorted(visible),
        "sports_types": sports,
        "sports_in_my_list": sorted(n for n in counts if n in visible),
        "sports_resources": {n: {"total": counts[n], "enabled": enabled.get(n, 0)} for n in counts},
    }


# --------------------------------------------------------------------- CLI


def _merge(slots: list[Slot]) -> list[tuple[str, str]]:
    """把首尾相接的空闲格子合并成区间。"""
    spans: list[tuple[str, str]] = []
    for slot in slots:
        if spans and spans[-1][1] == slot.start:
            spans[-1] = (spans[-1][0], slot.end)
        else:
            spans.append((slot.start, slot.end))
    return spans


def _state_label(state: str) -> str:
    return {"3": "已取消", "0": "已取消"}.get(state, "有效")


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

    @click.group(name="booking", help="预约中心：分类 / 资源 / 空闲时段 / 我的预约 / 预约与取消。")
    def group() -> None:
        """``westlake booking types|list|slots|mine|book|cancel|sports``（首次运行自动登录）。"""

    @group.command(name="types")
    @handle
    def types_cmd() -> None:
        """我能预约的分类（首页卡片）。"""
        items = visible_types()
        if not items:
            click.echo("没有可预约的分类。")
            return
        for t in items:
            click.echo(f"  {t.name}　{t.open_time}-{t.close_time} / {t.step}分钟")

    @group.command(name="list")
    @click.option("--type", "type_name", default=None, help="分类名（如 图书馆）")
    @click.option("--keyword", "keyword", default=None, help="名称关键词")
    @handle
    def list_cmd(type_name, keyword) -> None:
        """可预约资源列表。"""
        items = resources(type_name=type_name, keyword=keyword)
        if not items:
            click.echo("没有匹配的资源。")
            return
        for i in items:
            where = "".join(x for x in (i.campus, i.building, i.floor) if x)
            click.echo(f"  {i.name}　[{i.type_name}] {where} 容量{i.capacity}　{i.id}")

    @group.command(name="days")
    @click.argument("selector")
    @click.option("--start", "start_day", required=True, help="起始日期 YYYY-MM-DD")
    @click.option("--end", "end_day", required=True, help="结束日期 YYYY-MM-DD")
    @handle
    def days_cmd(selector, start_day, end_day) -> None:
        """某资源逐天的可约状态（挑日期用）。"""
        resource = _match(selector)
        rows = available_days(resource.id, start_day, end_day)
        free = [r["date"] for r in rows if r["code"] == "0"]
        click.echo(f"{resource.name}：可约 {len(free)}/{len(rows)} 天")
        click.echo("  " + "  ".join(free))

    @group.command(name="slots")
    @click.argument("selector")
    @click.option("--date", "day", required=True, help="YYYY-MM-DD")
    @click.option("--duration", default=None, type=int, help="只要连续空闲≥N分钟")
    @handle
    def slots_cmd(selector, day, duration) -> None:
        """某资源的空闲时段（名字或 id）。"""
        resource = _match(selector)
        slots = free_slots(resource.id, day, duration=duration)
        if not slots:
            click.echo(f"{resource.name} {day} 没有空闲时段。")
            return
        if duration:
            spans = [f"{s.start}-{s.end}" for s in slots]
        else:
            spans = [f"{lo}-{hi}" for lo, hi in _merge(slots)]
        click.echo(f"{resource.name} {day} 空闲（{duration or '整段'}）：")
        click.echo("  " + "  ".join(spans))

    @group.command(name="mine")
    @handle
    def mine_cmd() -> None:
        """我的预约。"""
        items = my_bookings()
        if not items:
            click.echo("没有预约记录。")
            return
        for b in items:
            click.echo(f"  {b.day} {b.start}-{b.end} {b.resource_name}"
                       f" [{_state_label(b.state)}] {b.id}")

    @group.command(name="book")
    @click.argument("selector")
    @click.option("--date", "day", required=True, help="YYYY-MM-DD")
    @click.option("--start", required=True, help="开始 HH:MM")
    @click.option("--end", required=True, help="结束 HH:MM")
    @click.option("--theme", default="", help="主题")
    @click.option("--remark", default="", help="备注")
    @click.option("--dry-run", is_flag=True, help="只校验不提交")
    @handle
    def book_cmd(selector, day, start, end, theme, remark, dry_run) -> None:
        """预约一段（写操作；--dry-run 先看能不能约）。"""
        result = book(selector, day, start, end, theme=theme, remark=remark, dry_run=dry_run)
        click.echo("校验通过（未提交）：" + json.dumps(result, ensure_ascii=False)
                   if dry_run else "预约成功：" + json.dumps(result, ensure_ascii=False))

    @group.command(name="cancel")
    @click.argument("appointment_id")
    @click.option("--reason", default="")
    @handle
    def cancel_cmd(appointment_id, reason) -> None:
        """取消预约（写操作）。"""
        click.echo(json.dumps(cancel(appointment_id, reason=reason), ensure_ascii=False))

    @group.command(name="sports")
    @handle
    def sports_cmd() -> None:
        """体育场馆（含游泳）权限体检。"""
        click.echo(json.dumps(diagnose_sports(), ensure_ascii=False, indent=2))
        click.echo(
            "提示：游泳/球场的真实入口是独立的正元场馆系统——"
            "用 westlake sport scenes 查（见 docs/sportvenue_notes.md）。",
            err=True,
        )

    return group


cli_group = _cli()
