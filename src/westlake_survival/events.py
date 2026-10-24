"""官网「活动预告」（讲座/学术会议/演出等）解析与查询。

数据源是西湖大学官网活动预告列表页
``https://www.westlake.edu.cn/news_events/EventCalendars/``（2026-09-22 实测，
校外可直连）。该页是 Vue 单页应用，真正的数据内嵌在页面内联 ``<script>``
里的 ``new events("#app", { ... })`` 调用中，其中 ``eventList`` 是**全量**
数组（实测约 1813 条，含历史活动），每条形如::

    {
      date: "2026-09-23 14:00:00",       # 开始时间
      title: "西湖理学讲坛| 程金光：...",   # 标题
      range: "2026-09-23 14:00 - 2026-09-23 15:30",  # 时间段文本
      address: "云谷校区E10-211",          # 地点
      school: "理学院",                    # 主办单位
      url: "https://.../t20260916_69819.html",
      target: "_self",
      type: "名家讲座",                    # 活动类型
      brand: "",                          # 品牌（西湖名师论坛/湖心讲堂/We剧场/WeMeet/其他）
    }

列表页组件对象里混有 ``function () {}`` 回调（``mounted`` 等），**不能**把
整个组件块直接交给 :func:`~westlake_survival._trs.js_literal`；本模块先用
:func:`~westlake_survival._trs.component_script` 取到配平的 ``{...}`` 文本，
再按键单独提取数组/对象后解析（见 :func:`~westlake_survival._trs.array_of` / :func:`~westlake_survival._trs.object_of`）。

详情页 ``GET <url>`` 同样是 Vue 页面，内嵌 ``new eventsDetail("#app", {...})``。
2026-09-22 实测该 payload 的键为：

* 顶层：``navList``（面包屑数组）、``left``（信息块对象）、``right``（标题 +
  正文对象）、``downloadLists``（附件数组，通常为空）、``mounted``（函数回调）；
* ``left``：``Data``（开始时间）、``Time``（时间段）、``Venue``（地点）、
  ``Host``（主持人）、``Audience``（受众）、``Category``（类型）；
* ``right``：``title``（标题）、``detailContent``（正文 HTML 字符串）。

实测坑位
========
- 响应头 ``Content-Type`` 不带 charset，``requests`` 会把 ``encoding`` 当成
  ISO-8859-1，``response.text`` 得到乱码；本模块一律取 ``response.content``
  手动 UTF-8 解码，禁止读 ``.text``。
- 列表页组件块内含 ``function`` 回调，必须按键提取数组，不能整块解析。
- 列表页支持 ETag 条件 GET：复用 :mod:`westlake_survival._cache` 的
  ``load_json`` / ``save_json`` / ``cache_path`` 做本地缓存。
- 该接口公开可达（校外可直连），连接失败统一映射为 :class:`WestlakeError`。
"""

from __future__ import annotations

import functools
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import click
import requests

from westlake_survival import _cache
from westlake_survival._net import DEFAULT_TIMEOUT, http_session
from westlake_survival._trs import array_of, component_script, object_of
from westlake_survival.exceptions import (
    OffCampusError,
    ParseError,
    WestlakeError,
    is_offcampus,
)

__all__ = [
    "EVENTS_URL",
    "CACHE_NAME",
    "EventItem",
    "EventDetail",
    "parse_events",
    "parse_detail",
    "parse_datetime",
    "load_events",
    "upcoming",
    "fetch_detail",
    "cli_group",
]

logger = logging.getLogger(__name__)

#: 活动预告列表页（唯一可抓取的列表页）。
EVENTS_URL = "https://www.westlake.edu.cn/news_events/EventCalendars/"

#: 列表页 ETag 缓存文件名（相对缓存目录）。
CACHE_NAME = "events/event_calendars.html"

#: 双语源（2026-10-24 实测）：英文主站 en.westlake.edu.cn 同路径同组件名；
#: 英文页组件块同样混有 ``mounted: function () {}`` 回调，解析路径与中文一致
#: （:func:`~westlake_survival._trs.array_of` 按键截取目标数组，不受回调影响）。
#: 英文条目的 ``type`` / ``school`` / ``address`` 为英文（如 ``"Seminar"`` /
#: ``"School of Science"``），按这些字段过滤时须用英文原始值。
EVENTS_URLS = {
    "zh": EVENTS_URL,
    "en": "https://en.westlake.edu.cn/news_events/EventCalendars/",
}

#: ETag 缓存文件名（按语言；zh 缓存名逐字保留，en 另存一份避免互相覆盖）。
CACHE_BY_LANG = {"zh": CACHE_NAME, "en": "events/event_calendars_en.html"}

#: 列表页组件构造函数名。
_LIST_COMPONENT = "events"

#: 详情页组件构造函数名。
_DETAIL_COMPONENT = "eventsDetail"

#: ``2026-09-23 14:00:00`` / ``2026-09-23 14:00`` / ``2026-09-23`` 日期时间字面量。
_DATETIME_RE = re.compile(
    r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?"
)

#: ``<title>...</title>``，用于详情页标题兜底。
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)


# --------------------------------------------------------------------------- #
# 数据模型
# --------------------------------------------------------------------------- #
@dataclass
class EventItem:
    """活动预告列表里的一条活动。

    ``date`` 是开始时间（含时分），``time_range`` 是原始时间段文本
    （可能只有 ``"10:00-11:30"`` 而不含日期）。``raw`` 保留原始条目字典，
    便于排查。
    """

    title: str
    date: datetime
    time_range: str = ""
    venue: str = ""
    organizer: str = ""
    event_type: str = ""
    brand: str = ""
    url: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def date_only(self) -> date:
        """活动的日历日期（丢弃时分）。"""
        return self.date.date()


@dataclass
class EventDetail:
    """活动详情页解析结果。

    字段来自详情组件 ``left`` / ``right`` 两块：``date_text`` 是原始开始时间
    字符串（``Data``），``time_text`` 是时间段（``Time``），``host`` 是主持人
    （``Host``），``audience`` 是受众（``Audience``），``category`` 是类型
    （``Category``），``content_html`` 是正文 HTML（``detailContent``）。
    """

    title: str
    date_text: str = ""
    time_text: str = ""
    venue: str = ""
    host: str = ""
    audience: str = ""
    category: str = ""
    content_html: str = ""
    url: str = ""
    raw: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# 文本解析
# --------------------------------------------------------------------------- #
def parse_datetime(value: str) -> datetime | None:
    """把 ``2026-09-23 14:00:00``（或 ``14:00`` / ``YYYY/MM/DD``）解析成 datetime。

    缺时间部分时按 ``00:00`` 处理；空串或无法解析时返回 ``None``。
    """
    match = _DATETIME_RE.search(value or "")
    if not match:
        return None
    year, month, day = (int(match.group(i)) for i in (1, 2, 3))
    hour = int(match.group(4)) if match.group(4) else 0
    minute = int(match.group(5)) if match.group(5) else 0
    second = int(match.group(6)) if match.group(6) else 0
    try:
        return datetime(year, month, day, hour, minute, second)
    except ValueError:
        return None


def _text(raw: dict, key: str) -> str:
    """取字典中 ``key`` 的字符串值（缺省或 ``None`` 时返回空串）。"""
    value = raw.get(key)
    return str(value).strip() if value is not None else ""


def _parse_item(raw: dict) -> EventItem | None:
    """把一个原始条目字典转成 :class:`EventItem`；无法解析时返回 ``None``。"""
    title = _text(raw, "title")
    when = parse_datetime(_text(raw, "date"))
    if not title or when is None:
        logger.debug("跳过无法解析的活动条目：%r", raw)
        return None
    return EventItem(
        title=title,
        date=when,
        time_range=_text(raw, "range"),
        venue=_text(raw, "address"),
        organizer=_text(raw, "school"),
        event_type=_text(raw, "type"),
        brand=_text(raw, "brand"),
        url=_text(raw, "url"),
        raw=dict(raw),
    )


def parse_events(html: str) -> list[EventItem]:
    """解析活动预告列表页 HTML，返回全部 :class:`EventItem`（含历史）。

    Args:
        html: 列表页整页 HTML（须为正确 UTF-8 文本，不能是 latin-1 乱码）。

    Returns:
        按页面原顺序（大致为开始时间降序）排列的活动列表。

    Raises:
        ParseError: 页面中找不到 ``events`` 组件、缺少 ``eventList`` 键，或
            全部条目都无法解析。
    """
    block = component_script(html, _LIST_COMPONENT)
    if not block:
        raise ParseError("活动预告列表页找不到 events 组件")
    raw_items = array_of(block, "eventList")
    parsed = (_parse_item(raw) for raw in raw_items if isinstance(raw, dict))
    items = [item for item in parsed if item is not None]
    if not items:
        raise ParseError("活动预告 eventList 为空或全部条目无法解析，页面结构可能已变化")
    return items


def _detail_title(block: str, html: str) -> str:
    """取详情标题：优先 ``right.title``，缺省回退到 ``<title>`` 标签。"""
    try:
        right = object_of(block, "right")
    except ParseError:
        right = {}
    title = _text(right, "title")
    if title:
        return title
    match = _TITLE_RE.search(html)
    if not match:
        return ""
    # 官网详情页 <title> 形如 "标题&nbsp;-&nbsp;西湖大学"，剥掉站点后缀。
    text = re.sub(r"&nbsp;|\s", " ", match.group(1)).strip()
    return re.split(r"\s*-\s*西湖大学\s*$", text)[0].strip()


def parse_detail(html: str, url: str = "") -> EventDetail:
    """解析活动详情页 HTML，返回 :class:`EventDetail`。

    详情组件 ``left`` 提供时间/地点/主持人/受众/类型，``right`` 提供标题与
    正文 HTML。

    Args:
        html: 详情页整页 HTML。
        url: 详情页地址，原样存入结果的 ``url`` 字段。

    Raises:
        ParseError: 页面中找不到 ``eventsDetail`` 组件，或 ``left`` 键缺失。
    """
    block = component_script(html, _DETAIL_COMPONENT)
    if not block:
        raise ParseError("活动详情页找不到 eventsDetail 组件")
    left = object_of(block, "left")
    try:
        right = object_of(block, "right")
    except ParseError:
        right = {}
    return EventDetail(
        title=_detail_title(block, html),
        date_text=_text(left, "Data"),
        time_text=_text(left, "Time"),
        venue=_text(left, "Venue"),
        host=_text(left, "Host"),
        audience=_text(left, "Audience"),
        category=_text(left, "Category"),
        content_html=str(right.get("detailContent") or ""),
        url=url,
        raw={"left": left, "right": right},
    )


# --------------------------------------------------------------------------- #
# 网络层
# --------------------------------------------------------------------------- #
def _check_response(response: requests.Response, what: str) -> None:
    """把 HTTP 层失败翻译成库内异常。"""
    status = getattr(response, "status_code", 200)
    url = getattr(response, "url", "") or EVENTS_URL
    if status == 403 and is_offcampus(response):
        raise OffCampusError(f"官网{what}拒绝访问（403）")
    if status >= 400:
        raise ParseError(f"官网{what}返回 HTTP {status}：{url}")


def _request(
    session: requests.Session,
    url: str,
    *,
    headers: dict | None,
    timeout: float | None,
    what: str,
) -> requests.Response:
    """发 GET 请求并把网络异常映射为 :class:`WestlakeError`。"""
    try:
        return session.get(
            url,
            headers=headers or {},
            timeout=timeout if timeout is not None else DEFAULT_TIMEOUT,
        )
    except requests.Timeout as exc:
        raise WestlakeError(
            f"官网{what}请求超时（{timeout if timeout is not None else DEFAULT_TIMEOUT}s）"
        ) from exc
    except requests.RequestException as exc:
        raise WestlakeError(f"官网{what}请求失败：{exc}") from exc


def _drop_cache(lang: str = "zh") -> None:
    """删除列表页本地 ETag 缓存，令下一次请求变为无条件 GET。"""
    try:
        _cache.cache_path(CACHE_BY_LANG.get(lang, CACHE_NAME)).unlink(missing_ok=True)
    except OSError:  # 缓存删不掉不应阻断加载
        logger.debug("删除活动预告 ETag 缓存失败", exc_info=True)


def _fetch_list_html(
    *,
    session: requests.Session | None = None,
    timeout: float | None = None,
    refresh: bool = False,
    lang: str = "zh",
) -> str:
    """抓取活动预告列表页 HTML（带 ETag 条件 GET + 本地缓存）。

    ``lang`` 选择中/英文主站与对应缓存（未知值回退 zh）；``304 Not Modified``
    时返回缓存正文；否则按 ``response.content`` 手动 UTF-8 解码（响应无
    charset 头，读 ``.text`` 会乱码）。
    """
    session = session if session is not None else http_session()
    if refresh:
        _drop_cache(lang)
    cache_name = CACHE_BY_LANG.get(lang, CACHE_NAME)
    cached = _cache.load_json(cache_name, default=None) or {}
    headers = {"If-None-Match": cached["etag"]} if cached.get("etag") else {}

    response = _request(
        session,
        EVENTS_URLS.get(lang, EVENTS_URL),
        headers=headers,
        timeout=timeout,
        what="活动预告列表页",
    )
    if response.status_code == 304 and cached.get("body"):
        return cached["body"]
    _check_response(response, "活动预告列表页")
    body = response.content.decode("utf-8")
    etag = response.headers.get("ETag")
    if etag:
        _cache.save_json(cache_name, {"etag": etag, "body": body})
    return body


def fetch_detail(
    url: str,
    *,
    session: requests.Session | None = None,
    timeout: float | None = None,
) -> EventDetail:
    """抓取并解析一个活动详情页。

    Args:
        url: 详情页地址（列表条目里的 ``url`` 字段）。
        session: 可注入的 :class:`requests.Session`（测试用）。
        timeout: 请求超时（秒），缺省 :data:`~westlake_survival._net.DEFAULT_TIMEOUT`。

    Raises:
        ValueError: ``url`` 为空。
        WestlakeError: 网络层失败（超时/连接错误等）。
        ParseError: HTTP 4xx/5xx，或页面结构与预期不符。
        OffCampusError: 被校外访问网关拦截（403 且命中阻断页特征）。
    """
    if not url:
        raise ValueError("url 不能为空")
    session = session if session is not None else http_session()
    response = _request(session, url, headers=None, timeout=timeout, what="活动详情页")
    _check_response(response, "活动详情页")
    return parse_detail(response.content.decode("utf-8"), url=url)


# --------------------------------------------------------------------------- #
# 公开 API
# --------------------------------------------------------------------------- #
def load_events(
    event_type: str | None = None,
    since: date | None = None,
    until: date | None = None,
    limit: int | None = None,
    *,
    session: requests.Session | None = None,
    timeout: float | None = None,
    refresh: bool = False,
    lang: str = "zh",
) -> list[EventItem]:
    """抓取并过滤活动预告列表。

    列表页的 ``eventList`` 是全量数组（含历史），因此 ``since`` / ``until``
    是常用的收窄手段。

    Args:
        event_type: 只保留该活动类型（与 ``type`` 字段**精确匹配**，如
            ``"名家讲座"``）；``None`` 表示不过滤。``lang="en"`` 时该字段是
            英文原始值（如 ``"Seminar"``）。
        since: 只保留开始日期 ``>= since`` 的活动。
        until: 只保留开始日期 ``<= until`` 的活动。
        limit: 最多返回条数（在过滤后按页面原顺序截断）；``None`` 表示不限。
        session: 可注入的 :class:`requests.Session`（测试用）。
        timeout: 请求超时（秒）。
        refresh: 为 ``True`` 时先清掉本地 ETag 缓存再请求。
        lang: ``"zh"``（默认）抓中文主站；``"en"`` 抓英文主站
            en.westlake.edu.cn，条目的类型/地点/主办为英文原始值（未知值
            回退 zh）。

    Returns:
        过滤后的活动列表，保持页面原顺序（大致为开始时间降序）。

    Raises:
        WestlakeError: 网络层失败。
        ParseError: HTTP 4xx/5xx，或页面结构与预期不符。
        OffCampusError: 被校外访问网关拦截。
    """
    html = _fetch_list_html(session=session, timeout=timeout, refresh=refresh, lang=lang)
    items = parse_events(html)
    if event_type is not None:
        items = [item for item in items if item.event_type == event_type]
    if since is not None:
        items = [item for item in items if item.date_only >= since]
    if until is not None:
        items = [item for item in items if item.date_only <= until]
    if limit is not None:
        items = items[: max(0, limit)]
    return items


def upcoming(
    days: int = 14,
    *,
    session: requests.Session | None = None,
    timeout: float | None = None,
    refresh: bool = False,
    today: date | None = None,
    lang: str = "zh",
) -> list[EventItem]:
    """返回从今天起 ``days`` 天内（含首尾）的活动，按开始时间升序。

    Args:
        days: 未来天数窗口，``0`` 表示只看今天；必须 ``>= 0``。
        session: 可注入的 :class:`requests.Session`（测试用）。
        timeout: 请求超时（秒）。
        refresh: 为 ``True`` 时先清掉本地 ETag 缓存再请求。
        today: 窗口起点，缺省为今天（测试用）。
        lang: 同 :func:`load_events`（``"zh"`` 中文主站 / ``"en"`` 英文主站）。

    Raises:
        ValueError: ``days`` 小于 0。
        WestlakeError / ParseError / OffCampusError: 同 :func:`load_events`。
    """
    if days < 0:
        raise ValueError(f"days 必须 >= 0，得到 {days!r}")
    start = today or date.today()
    items = load_events(
        since=start,
        until=start + timedelta(days=days),
        session=session,
        timeout=timeout,
        refresh=refresh,
        lang=lang,
    )
    return sorted(items, key=lambda item: item.date)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _handle_errors(func):
    """装饰器：把 :class:`WestlakeError` 转成中文提示 + 退出码 1。

    与 :func:`westlake_survival.cli.main._handle_errors` 同款；此处自带一份
    以免与 ``cli.main`` 形成循环导入。
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
    name="events",
    help="活动预告：讲座 / 学术会议 / 演出等。",
    invoke_without_command=True,
)
@click.option("--type", "event_type", default=None, help="只看某类型活动（如「名家讲座」；en 模式用英文原始值）。")
@click.option("--days", type=int, default=14, show_default=True, help="只看未来 N 天（含今天）。")
@click.option("--limit", type=int, default=20, show_default=True, help="最多显示条数。")
@click.option(
    "--lang",
    type=click.Choice(["zh", "en"]),
    default="zh",
    show_default=True,
    help="语言：zh=中文主站 en=英文主站。",
)
@click.pass_context
def cli_group(
    ctx: click.Context, event_type: str | None, days: int, limit: int, lang: str
) -> None:
    """``westlake events [--type T] [--days N] [--limit N] [--lang en]``。

    不带子命令时展示未来 ``--days`` 天的活动预告；``westlake events detail
    <url>`` 查看单条活动详情。
    """
    if ctx.invoked_subcommand is not None:  # 交给 detail 子命令
        return
    if days < 0:
        raise click.UsageError(f"--days 必须 >= 0，得到 {days}")
    _run_list(event_type=event_type, days=days, limit=limit, lang=lang)


@cli_group.command(name="detail")
@click.argument("url")
@_handle_errors
def events_detail(url: str) -> None:
    """查看单条活动详情（参数为列表里的详情页 URL）。"""
    detail = fetch_detail(url)
    if detail.title:
        click.secho(detail.title, bold=True)
    rows = [
        ("时间", detail.date_text or "—"),
        ("时段", detail.time_text or "—"),
        ("地点", detail.venue or "—"),
        ("主办", detail.host or "—"),
        ("受众", detail.audience or "—"),
        ("类型", detail.category or "—"),
        ("链接", detail.url or "—"),
    ]
    from westlake_survival.cli.main import _print_table

    _print_table(rows, ("字段", "内容"))
    if detail.content_html:
        click.echo()
        click.echo("正文（HTML 原文）：")
        click.echo(detail.content_html)


@_handle_errors
def _run_list(*, event_type: str | None, days: int, limit: int, lang: str = "zh") -> None:
    """展示未来 ``days`` 天的活动预告表格（表格工具惰性导入）。"""
    from westlake_survival.cli.main import _print_table

    items = upcoming(days, lang=lang)
    if event_type is not None:
        items = [item for item in items if item.event_type == event_type]
    if not items:
        suffix = f"（类型：{event_type}）" if event_type else ""
        click.echo(f"未来 {days} 天内暂无活动预告{suffix}。")
        return
    rows = [
        (
            item.date.strftime("%Y-%m-%d %H:%M"),
            item.event_type or "—",
            item.title or "—",
            item.venue or "—",
            item.organizer or "—",
        )
        for item in items[: max(0, limit)]
    ]
    _print_table(rows, ("时间", "类型", "标题", "地点", "主办"))