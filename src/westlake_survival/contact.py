"""官网「联系我们」：三校区地址、交通方式、常用电话邮箱与校区地图。

数据源
======
页面 ``https://www.westlake.edu.cn/about/contact_us/``（2026-09-22 实测，校外可
直连）。注意 ``https://www.westlake.edu.cn/about/`` 目录本身返回 403，必须带完
整子路径。该页与校历一样是 TRS CMS + Vue SPA，数据内嵌在一段
``new contactUs("#app", {...})`` 内联脚本里，结构为::

    new contactUs("#app", {
      transportObj: {
        addressArr: [
          {campus: "云谷校区", address: "浙江省杭州市西湖区墩余路600号</br>邮编：310030"},
          {campus: "云栖校区", address: "浙江省杭州市西湖区石龙山街18号<br>邮编：310024"},
          {campus: "云栖校区（铜鉴湖园区）", address: "...石龙山工业区块25号<br>邮编：310024"},
        ],
        trafficList: [
          {index: 0,
           chinese: "1、...<br/>2、...",              # 自驾路线，``<br/>`` 分隔多条
           metro: "4号线池华街站",
           metroOperatingHours: [{bound: "池华街方向", time: "首班车06:00，末班车22:40"}, ...],
           bus: "西湖大学云谷校区，349路",
           busOperatingHours: [{bound: "三墩地铁站方向", time: "..."}, ...],
           mapImgUrl: "./address/yungu/202309/W020241028583941229157.png"},
          ...
        ],
      },
      mapList: [{text: "云谷", imgUrl: "./address/yungu/..."},
                {text: "云栖", imgUrl: "./address/yunqi/..."}],
      contactList: [
        {title: "想咨询招生政策",
         content: "<div ...>本科生招生 电话：0571-88996767 邮箱：ugadmissions@westlake.edu.cn"
                  "博士生招生 电话：0571-86886872 邮箱：admissions@westlake.edu.cn</div>"},
        {title: "想参加校园活动", content: "<div ...>关注官方微信公众号…</div>"},
        {title: "想捐赠支持西湖", content: "<div ...>联系电话 13071113309…</div>"},
      ],
      mounted: function () { },   # 组件里混有函数回调
    });

要点：

* ``addressArr`` 与 ``trafficList`` 按下标一一对应（``trafficList`` 带 ``index``
  字段，``addressArr`` 不带），三个校区依次为云谷、云栖、铜鉴湖（原页面写作
  ``"云栖校区（铜鉴湖园区）"``，本模块归一化为 :data:`CAMPUS_NAMES`）。
* ``mapList`` 只有云谷、云栖两张图，铜鉴湖园区没有地图，对应
  :attr:`CampusInfo.map_url` 为 ``None``。
* 组件对象里混有 ``mounted: function () {}`` 这类回调，**不能**对整块做
  :func:`~westlake_survival._trs.js_literal`；先按 ``{...}`` 配平取块，再按键单
  独抽取目标数组/对象后解析（见 :func:`~westlake_survival._trs.balanced` /
  :func:`~westlake_survival._trs.array_of` / :func:`~westlake_survival._trs.object_of`）。
* 页面响应无 ``charset`` 头，必须 ``response.content.decode("utf-8")``，禁止
  ``response.text``（会得到 ISO-8859-1 乱码）。

页脚全局信息（首页实测 2026-09-22）不在 contactUs 组件里，作为
:data:`GENERAL_CONTACTS` 常量硬编码：公共事务部 0571-86886861、
media@westlake.edu.cn、传真 0571-88111699。
"""

from __future__ import annotations

import functools
import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

import click
import requests

from westlake_survival._cache import load_json, save_json
from westlake_survival._net import DEFAULT_TIMEOUT, http_session
from westlake_survival._trs import array_of, component_script, object_of
from westlake_survival.exceptions import (
    OffCampusError,
    ParseError,
    WestlakeError,
    is_offcampus,
)

__all__ = [
    "CONTACT_URL",
    "CACHE_NAME",
    "CAMPUS_NAMES",
    "CampusInfo",
    "ContactEntry",
    "ContactPage",
    "GENERAL_CONTACTS",
    "campuses",
    "contacts",
    "parse",
    "parse_campuses",
    "parse_contacts",
    "cli_group",
]

logger = logging.getLogger(__name__)

#: 「联系我们」页面地址（2026-09-22 实测；校外可直连）。
CONTACT_URL = "https://www.westlake.edu.cn/about/contact_us/"

#: ETag 缓存文件名（相对缓存目录）。
CACHE_NAME = "contact/contact_us.html"

#: 组件构造函数名。
_COMPONENT = "contactUs"

#: 归一化后的校区名（与 :attr:`CampusInfo.name` 一致）。
CAMPUS_NAMES = ("云谷", "云栖", "铜鉴湖")

#: 原始校区名 → 归一化名。``铜鉴湖`` 必须先匹配，否则会被 ``云栖`` 提前命中。
_CAMPUS_ALIASES = (("铜鉴湖", "铜鉴湖"), ("云谷", "云谷"), ("云栖", "云栖"))

#: ``<br>`` / ``<br/>`` / ``</br>`` 换行标记（js_literal 已把 ``<\/br>`` 还原）。
_BR_RE = re.compile(r"</?br\s*/?>", re.IGNORECASE)

#: 地址串里的邮编段：``邮编：310030``。
_POSTCODE_RE = re.compile(r"邮编[:：]\s*(\d{6})")

#: 电话号码：杭州固话 ``0571-88996767`` 或 11 位手机号（限定 ASCII 数字，避免
#: ``\d`` 吃到全角数字）。
_PHONE_RE = re.compile(r"(?:0571[-\s]?[0-9]{8}|1[3-9][0-9]{9})")

#: 电子邮箱；**必须限定 ASCII**——标签直接删去后正文里中文会紧贴邮箱，
#: ``\w`` 会含 CJK 而把 ``…@westlake.edu.cn博士生招生`` 整段吃进去。
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")

#: HTML 标签（提取 contactList 正文纯文本用）。
_TAG_RE = re.compile(r"<[^>]+>")


# --------------------------------------------------------------------------- #
# 数据模型
# --------------------------------------------------------------------------- #
@dataclass
class CampusInfo:
    """一个校区的地址、交通与地图。

    Attributes:
        name: 归一化校区名，取值见 :data:`CAMPUS_NAMES`。
        address: 详细地址（已去掉 ``<br>`` 与邮编段）。
        postcode: 邮政编码；地址里没有则空串。
        traffic: 逐条交通说明文本，形如 ``"自驾：1、…"`` /
            ``"地铁：4号线池华街站（池华街方向 首班车06:00，末班车22:40）"`` /
            ``"公交：西湖大学云谷校区，349路（…）"``。
        map_url: 校区地图图片的绝对 URL；该校区没有地图时为 ``None``。
    """

    name: str
    address: str = ""
    postcode: str = ""
    traffic: list[str] = field(default_factory=list)
    map_url: str | None = None


@dataclass
class ContactEntry:
    """一条「联系我们」条目。

    来源结构是 ``contactList`` 里的 ``{title, content}``：``title`` 是问题式标题
    （如 ``"想咨询招生政策"``），``content`` 是一段富文本 HTML，电话/邮箱夹杂在
    正文里（且会被 ``<span>`` 切开，如 ``"电话：0</span>571-88996767"``）。本类
    在剥掉标签的纯文本上用正则抽出电话与邮箱。

    Attributes:
        label: 条目标题（``title``）。
        phones: 正文里出现的电话号码，按出现顺序去重。
        emails: 正文里出现的邮箱，按出现顺序去重。
        text: 剥掉 HTML 标签并压缩空白后的正文纯文本。
        fax: 传真号；只有 :data:`GENERAL_CONTACTS` 会用到（官网 contactList 里没有）。
    """

    label: str
    phones: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    text: str = ""
    fax: str = ""


@dataclass
class ContactPage:
    """整页「联系我们」数据：三校区信息 + 常用联系条目。"""

    campuses: list[CampusInfo] = field(default_factory=list)
    contacts: list[ContactEntry] = field(default_factory=list)


#: 页脚全局信息（首页 ``maskObj`` 实测于 2026-09-22）：公共事务部总机、媒体邮箱
#: 与传真。不属于 contactUs 组件，故硬编码为常量；页面改版时应核对更新。
GENERAL_CONTACTS = ContactEntry(
    label="公共事务部（学校总机 / 媒体联络）",
    phones=["0571-86886861"],
    emails=["media@westlake.edu.cn"],
    fax="0571-88111699",
)


# --------------------------------------------------------------------------- #
# 解析
# --------------------------------------------------------------------------- #
def _campus_name(raw: str) -> str:
    """把原始校区名归一化成 :data:`CAMPUS_NAMES` 中的一个。

    ``"云栖校区（铜鉴湖园区）"`` → ``"铜鉴湖"``（``铜鉴湖`` 优先匹配，避免被
    ``云栖`` 抢占）；未识别的名字去掉 ``"校区"`` 后原样返回。
    """
    for keyword, name in _CAMPUS_ALIASES:
        if keyword in raw:
            return name
    return raw.replace("校区", "").strip()


def _split_address(raw: str) -> tuple[str, str]:
    """把 ``"...600号</br>邮编：310030"`` 拆成 ``(地址, 邮编)``。"""
    text = _BR_RE.sub("\n", raw or "")
    match = _POSTCODE_RE.search(text)
    postcode = match.group(1) if match else ""
    address = _POSTCODE_RE.sub("", text)
    return " ".join(address.split()), postcode


def _format_hours(items: object) -> str:
    """把 ``[{bound, time}, ...]`` 拼成 ``"池华街方向 首班车06:00，末班车22:40；…"``。"""
    if not isinstance(items, list):
        return ""
    parts: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        bound = str(item.get("bound") or "").strip()
        time = str(item.get("time") or "").strip()
        if bound and time:
            parts.append(f"{bound} {time}")
        elif time:
            parts.append(time)
    return "；".join(parts)


def _traffic_entries(raw: dict) -> list[str]:
    """把一个 ``trafficList`` 条目转成逐条交通文本。

    自驾的 ``chinese`` 字段用 ``<br/>`` 分隔多条路线，每条单独作为一项并加
    ``"自驾："`` 前缀；地铁与公交各拼成一项，附首末班时间。
    """
    entries: list[str] = []
    routes = _BR_RE.sub("\n", str(raw.get("chinese") or ""))
    for line in routes.split("\n"):
        line = line.strip().rstrip("；;")
        if line:
            entries.append(f"自驾：{line}")

    metro = str(raw.get("metro") or "").strip()
    if metro:
        hours = _format_hours(raw.get("metroOperatingHours"))
        entries.append(f"地铁：{metro}（{hours}）" if hours else f"地铁：{metro}")

    bus = str(raw.get("bus") or "").strip()
    if bus:
        hours = _format_hours(raw.get("busOperatingHours"))
        entries.append(f"公交：{bus}（{hours}）" if hours else f"公交：{bus}")
    return entries


def _map_index(map_list: list) -> dict[str, str]:
    """``mapList`` → ``{归一化校区名: 图片 URL}``。"""
    index: dict[str, str] = {}
    for item in map_list:
        if not isinstance(item, dict):
            continue
        img = str(item.get("imgUrl") or "").strip()
        if not img:
            continue
        index[_campus_name(str(item.get("text") or ""))] = img
    return index


def _strip_tags(fragment: str) -> str:
    """剥掉 HTML 标签并压缩空白（标签直接删去，避免 ``0</span>571-…`` 被拆开）。"""
    return " ".join(_TAG_RE.sub("", fragment or "").split())


def _dedup(values: list[str]) -> list[str]:
    """按出现顺序去重。"""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _parse_contact_entry(raw: dict) -> ContactEntry:
    """把一个 ``contactList`` 条目转成 :class:`ContactEntry`。"""
    text = _strip_tags(str(raw.get("content") or ""))
    return ContactEntry(
        label=str(raw.get("title") or "").strip(),
        phones=_dedup(_PHONE_RE.findall(text)),
        emails=_dedup(_EMAIL_RE.findall(text)),
        text=text,
    )


def parse(page_text: str) -> ContactPage:
    """解析「联系我们」页面文本，返回 :class:`ContactPage`。

    Args:
        page_text: 整页 HTML（已按 UTF-8 解码）。

    Returns:
        三校区信息与 contactList 条目。

    Raises:
        ParseError: 页面找不到 contactUs 组件，或组件里缺少目标键。
    """
    block = component_script(page_text, _COMPONENT)
    if not block:
        raise ParseError(
            f"页面中找不到组件 {_COMPONENT!r}；页面片段：{page_text[:200]!r}"
        )

    # transportObj 内部只有数据，可以整块解析（实测无 function）；mapList /
    # contactList 与 mounted 回调同级，必须按键单独抽取后只解析目标部分。
    transport = object_of(block, "transportObj")
    addresses = transport.get("addressArr") or []
    traffic_list = transport.get("trafficList") or []
    if not isinstance(addresses, list) or not isinstance(traffic_list, list):
        raise ParseError("transportObj 的 addressArr / trafficList 不是数组")
    map_index = _map_index(array_of(block, "mapList"))

    campuses_info: list[CampusInfo] = []
    for position, raw_address in enumerate(addresses):
        if not isinstance(raw_address, dict):
            continue
        name = _campus_name(str(raw_address.get("campus") or ""))
        address, postcode = _split_address(str(raw_address.get("address") or ""))

        raw_traffic = traffic_list[position] if position < len(traffic_list) else {}
        if not isinstance(raw_traffic, dict):
            raw_traffic = {}
        map_url = map_index.get(name) or str(raw_traffic.get("mapImgUrl") or "").strip() or None

        campuses_info.append(
            CampusInfo(
                name=name,
                address=address,
                postcode=postcode,
                traffic=_traffic_entries(raw_traffic),
                map_url=urljoin(CONTACT_URL, map_url) if map_url else None,
            )
        )

    contact_entries = [
        _parse_contact_entry(item)
        for item in array_of(block, "contactList")
        if isinstance(item, dict)
    ]
    return ContactPage(campuses=campuses_info, contacts=contact_entries)


def parse_campuses(page_text: str) -> list[CampusInfo]:
    """只解析三校区信息（:func:`parse` 的便捷包装）。"""
    return parse(page_text).campuses


def parse_contacts(page_text: str) -> list[ContactEntry]:
    """只解析 contactList 条目（:func:`parse` 的便捷包装）。"""
    return parse(page_text).contacts


# --------------------------------------------------------------------------- #
# 网络层
# --------------------------------------------------------------------------- #
def _check_response(response: requests.Response) -> None:
    """把 HTTP 层失败翻译成库内异常（口径与 :mod:`westlake_survival.search` 一致）。"""
    status = getattr(response, "status_code", 200)
    if status == 403 and is_offcampus(response):
        raise OffCampusError("「联系我们」页面拒绝访问（403）")
    if status >= 400:
        raise ParseError(f"「联系我们」页面返回 HTTP {status}")


def _drop_cache() -> None:
    """删除本地 ETag 缓存条目，令下一次请求变为无条件 GET。"""
    try:
        from westlake_survival import _cache

        path = _cache.cache_path(CACHE_NAME)
        if path.exists():
            path.unlink()
    except OSError:  # 缓存删不掉不应阻断加载
        logger.debug("删除 ETag 缓存失败", exc_info=True)


def _fetch(
    *,
    refresh: bool = False,
    session: requests.Session | None = None,
    timeout: float | None = None,
) -> str:
    """抓取页面并按 UTF-8 手动解码；带 ETag 条件请求。

    响应无 ``charset`` 头，``requests`` 会把 ``response.encoding`` 当成
    ISO-8859-1，``response.text`` 因此得到乱码，故一律取 ``response.content``
    手动解码。

    Args:
        refresh: 为 ``True`` 时先清掉本地 ETag 缓存再请求。
        session: 可注入的 :class:`requests.Session`（测试用）。
        timeout: 请求超时（秒），缺省 ``DEFAULT_TIMEOUT``。

    Raises:
        WestlakeError: 超时或连接层错误。
        OffCampusError: 被校外访问网关拦截（403 且命中阻断页特征）。
        ParseError: HTTP 4xx/5xx、响应体为空或不是合法 UTF-8。
    """
    session = session if session is not None else http_session()
    if refresh:
        _drop_cache()

    cached = load_json(CACHE_NAME, default=None) or {}
    headers = {"If-None-Match": cached["etag"]} if cached.get("etag") else {}
    try:
        response = session.get(
            CONTACT_URL,
            headers=headers,
            timeout=timeout if timeout is not None else DEFAULT_TIMEOUT,
        )
    except requests.Timeout as exc:
        raise WestlakeError("「联系我们」页面请求超时") from exc
    except requests.RequestException as exc:
        raise WestlakeError(f"「联系我们」页面请求失败：{exc}") from exc

    if getattr(response, "status_code", 200) == 304 and cached.get("body"):
        return cached["body"]

    _check_response(response)

    raw = getattr(response, "content", None)
    if raw is None:
        raise ParseError("「联系我们」页面响应缺少 content（禁止使用 response.text）")
    try:
        body = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ParseError("「联系我们」页面响应不是合法 UTF-8") from exc
    if not body.strip():
        raise ParseError("「联系我们」页面返回空响应体")

    etag = response.headers.get("ETag") or cached.get("etag")
    if etag:
        try:
            save_json(CACHE_NAME, {"etag": etag, "body": body})
        except OSError:  # 缓存写不进去不影响本次结果
            logger.debug("写入 ETag 缓存失败", exc_info=True)
    return body


def _load(refresh: bool = False, **kwargs) -> ContactPage:
    """抓取并解析页面；``campuses`` / ``contacts`` 共用。"""
    return parse(_fetch(refresh=refresh, **kwargs))


def campuses(refresh: bool = False, **kwargs) -> list[CampusInfo]:
    """返回三校区地址与交通信息。

    Args:
        refresh: 为 ``True`` 时跳过本地 ETag 缓存，强制拉取最新页面。
        **kwargs: 透传给 :func:`_fetch`（``session`` / ``timeout``，测试用）。

    Raises:
        WestlakeError: 网络层失败。
        ParseError: 页面结构变化或非法响应。
    """
    return _load(refresh, **kwargs).campuses


def contacts(refresh: bool = False, **kwargs) -> list[ContactEntry]:
    """返回官网 ``contactList`` 的常用联系条目（招生电话/邮箱等）。"""
    return _load(refresh, **kwargs).contacts


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _handle_errors(func):
    """装饰器：把 :class:`WestlakeError` 转成中文提示 + 退出码 1。

    与 :func:`westlake_survival.cli.main._handle_errors` 同款；此处自带一份以免
    与 ``cli.main`` 形成循环导入。
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except WestlakeError as exc:
            click.secho(f"错误：{exc}", fg="red", err=True)
            if isinstance(exc, OffCampusError):
                click.secho(
                    "提示：该服务仅校园网/VPN 内可达，请先连接西湖大学 VPN："
                    "https://vpn.westlake.edu.cn/",
                    err=True,
                )
            raise SystemExit(1) from exc

    return wrapper


@click.group(
    name="contact",
    help="联系我们：三校区地址/交通/地图，以及常用电话邮箱。",
    invoke_without_command=True,
)
@click.option(
    "--campus",
    type=click.Choice(list(CAMPUS_NAMES)),
    default=None,
    help="只看某校区（云谷 / 云栖 / 铜鉴湖）；缺省列出全部三校区。",
)
@click.pass_context
def cli_group(ctx: click.Context, campus: str | None) -> None:
    """``westlake contact [--campus 云谷|云栖|铜鉴湖]`` 与 ``westlake contact phones``。"""
    if ctx.invoked_subcommand is not None:
        return
    _run_contact(campus)


@cli_group.command(name="phones")
@_handle_errors
def contact_phones() -> None:
    """列出常用电话与邮箱（官网 contactList + 页脚公共事务部）。"""
    _run_phones()


@_handle_errors
def _run_contact(campus: str | None) -> None:
    """打印三校区（或指定校区）的地址、邮编、地图与交通。"""
    from westlake_survival.cli.main import _print_table

    infos = campuses()
    if campus:
        infos = [info for info in infos if info.name == campus]
    if not infos:
        click.echo("未找到匹配的校区信息。")
        return

    for info in infos:
        click.echo(f"【{info.name}校区】")
        rows = [(info.address or "—", info.postcode or "—", info.map_url or "—")]
        _print_table(rows, ("地址", "邮编", "校区地图"))
        for line in info.traffic:
            click.echo(f"  - {line}")


@_handle_errors
def _run_phones() -> None:
    """打印常用电话邮箱表格。"""
    from westlake_survival.cli.main import _print_table

    entries = [*contacts(), GENERAL_CONTACTS]
    rows = [
        (
            entry.label or "—",
            "、".join(entry.phones) or "—",
            "、".join(entry.emails) or "—",
            entry.fax or "—",
        )
        for entry in entries
    ]
    _print_table(rows, ("事项", "电话", "邮箱", "传真"))
