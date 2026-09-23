"""西湖大学「科研进展」（Research at Westlake）客户端。

数据源是官网科研进展板块列表页
``https://www.westlake.edu.cn/research/research_at_westlake/``（2026-09-23
实测，校外可直连）。该页同样是 TRS CMS + Vue 单页应用，真正的数据不在 DOM
里，而是内嵌在页面内联 ``<script>`` 的一段
``new researchWestlake("#app", { ... })`` 调用中：

* ``mainObj`` 是板块主体，含 ``brief``（数据说明）、``topCountList``
  （独立实验室/国家级平台等计数）与 ``researchList``（按研究方向分组的条目）；
* ``researchList`` 是**分组数组**，每个分组形如::

      {
        title: "生命健康 / Good Health & Wellbeing",   # 研究方向（分组名）
        iconUrl: "./good_health_wellbeing/images/x.png",
        mainBg: "./good_health_wellbeing/images/y.png",
        moreObj: { type: "research", moreText: "查看更多", url: "...", target: "_blank" },
        list: [
          {
            url: "https://.../good_health_wellbeing/202510/t20251016_60343.html",
            imgUrl: "./good_health_wellbeing/202510/W020251016821762002388.jpg",
            abs: "西湖大学卢培龙研究团队及其合作者从头设计新型电压门控阴离子通道",
          },
          ...
        ],
      }

  即：条目文本只有 ``abs`` 一个字段（既作标题也作摘要），``title`` 是**分组名**
  （研究方向）而非条目标题；本模块在 :class:`ResearchItem` 层把 ``abs`` 映射为
  :attr:`title` / :attr:`summary`，把分组 ``title`` 映射为 :attr:`category`。

日期缺失的坑
============
``researchList`` 条目里**没有**日期字段；唯一可靠的发布时间编码在 URL 的
``tYYYYMMDD_`` 片段中（如 ``t20251016_60343.html``）。本模块用
:func:`parse_url_date` 从中还原 ``datetime``，URL 不含该片段时 :attr:`date`
为 ``None``（不臆造）。

详情页
======
列表条目的 ``url`` 指向的详情页与「西湖新闻」同构，用的是 **同一个**
``new newsDetail("#app", { mainObj: { Data, mainTitle, Author, Category,
detailContent, ... } })`` 组件（2026-09-23 实测）；本模块单独实现
:func:`parse_research_detail` / :func:`fetch_detail`。详情页不做本地缓存，
每次调用都真发请求。

编码坑位
========
该站响应头是 ``Content-Type: text/html``（**无 charset**），``requests`` 会把
``response.encoding`` 当成 ISO-8859-1，直接读 ``response.text`` 会得到乱码；
本模块一律取 ``response.content`` 手动 UTF-8 解码。列表页复用
:func:`westlake_survival._cache.http_get_with_etag`（该站实测无 ETag 头，等价
于普通 GET），并用 :func:`_repair_mojibake` 兜底修复可能的乱码。

组件块里混有 ``mounted: function () { }`` 等回调，不能对整个块调用
:func:`~westlake_survival._trs.js_literal`；本模块先用
:func:`~westlake_survival._trs.component_script` 拿到块文本，再按键提取数组/
对象后只解析那一段。
"""

from __future__ import annotations

import functools
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

import click
import requests

from westlake_survival._cache import http_get_with_etag
from westlake_survival._net import DEFAULT_TIMEOUT, http_session
from westlake_survival._trs import array_of, component_script, object_of
from westlake_survival.exceptions import OffCampusError, ParseError, WestlakeError, is_offcampus

__all__ = [
    "RESEARCH_URL",
    "LIST_COMPONENT",
    "DETAIL_COMPONENT",
    "CACHE_NAME",
    "CATEGORIES",
    "ResearchItem",
    "ResearchDetail",
    "parse_url_date",
    "parse_research_list",
    "parse_research_detail",
    "latest",
    "fetch_detail",
    "cli_group",
]

logger = logging.getLogger(__name__)

#: 「科研进展」列表页。
RESEARCH_URL = "https://www.westlake.edu.cn/research/research_at_westlake/"

#: 列表页组件构造函数名。
LIST_COMPONENT = "researchWestlake"

#: 详情页组件构造函数名（与「西湖新闻」详情页同构）。
DETAIL_COMPONENT = "newsDetail"

#: ETag 缓存文件名（相对缓存目录）。
CACHE_NAME = "research/research_at_westlake.html"

#: 已知的研究方向分组名（``researchList[].title``，实测于 2026-09-23）。
CATEGORIES = (
    "生命健康 / Good Health & Wellbeing",
    "医学创新 / Treatment & Cures for Diseases",
    "能源与可持续环境 / Energy & Sustainable Environment",
    "材料科学 / Innovative Materials Research",
    "先进智造 / Advanced Manufacturing",
    "AI+跨学科研究与应用 / AI for Science",
    "理学前沿 / Frontiers of Sciences",
)

#: URL 里的发布日期片段 ``tYYYYMMDD_``（如 ``t20251016_60343.html``）。
_URL_DATE_RE = re.compile(r"t(\d{4})(\d{2})(\d{2})_")


# --------------------------------------------------------------------------- #
# JS 提取 / 文本工具
# --------------------------------------------------------------------------- #
def _repair_mojibake(text: str) -> str:
    """修复"UTF-8 被当成 ISO-8859-1 解码"造成的乱码。

    与 :func:`westlake_survival.news._repair_mojibake` 同款：该站响应无
    charset 头，``requests`` 可能按 latin-1 解码出乱码。把乱码按 latin-1 还原
    成字节、再按 UTF-8 解码即可恢复；文本已是正确 UTF-8 时 ``encode("latin-1")``
    会抛 :class:`UnicodeEncodeError`（中文超出 latin-1 范围），此时原样返回——
    因此该函数是安全的幂等修复。
    """
    try:
        repaired = text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    return repaired


# --------------------------------------------------------------------------- #
# 数据模型
# --------------------------------------------------------------------------- #
def parse_url_date(url: str) -> datetime | None:
    """从详情页 URL 的 ``tYYYYMMDD_`` 片段还原发布日期（当日 0 点）。

    ``researchList`` 条目本身没有日期字段，发布时间只编码在 URL 里；URL 不含
    该片段（或日期非法）时返回 ``None``，不臆造时间。
    """
    match = _URL_DATE_RE.search(url or "")
    if not match:
        return None
    try:
        return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


@dataclass
class ResearchItem:
    """「科研进展」列表页的一条研究报道。

    官网 payload 里每个条目只有 ``abs`` 一个文本字段（既作标题又作摘要），
    故 :attr:`title` 与 :attr:`summary` 同源；``category`` 来自所属分组的
    ``title``（研究方向），``date`` 由 URL 的 ``tYYYYMMDD_`` 片段推断。
    """

    title: str
    category: str
    summary: str = ""
    date: datetime | None = None
    url: str = ""
    img_url: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class ResearchDetail:
    """一篇科研进展详情页。

    ``content_html`` 是 ``detailContent`` 原文（富文本 HTML，未做清洗）。
    """

    title: str
    author: str = ""
    category: str = ""
    date: datetime | None = None
    content_html: str = ""
    url: str = ""
    raw: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# 解析
# --------------------------------------------------------------------------- #
def _parse_item(raw: dict, category: str) -> ResearchItem:
    """把一个原始条目转成 :class:`ResearchItem`（``abs`` → title/summary）。"""
    title = str(raw.get("abs") or "")
    url = str(raw.get("url") or "")
    return ResearchItem(
        title=title,
        category=category,
        summary=title,
        date=parse_url_date(url),
        url=url,
        img_url=str(raw.get("imgUrl") or ""),
        raw=dict(raw),
    )


def parse_research_list(html: str) -> list[ResearchItem]:
    """解析「科研进展」列表页 HTML，返回全部 :class:`ResearchItem`（按官网分组顺序展平）。

    组件块里混有 ``mounted: function () { }`` 回调，故先用
    :func:`~westlake_survival._trs.component_script` 截出块文本，再按键取出
    ``researchList`` 分组数组，逐个分组展平其 ``list``。

    Raises:
        ParseError: 页面里找不到 ``researchWestlake`` 组件或 ``researchList`` 数组。
    """
    text = _repair_mojibake(html)
    block = component_script(text, LIST_COMPONENT)
    if not block:
        raise ParseError(f"页面中找不到组件 {LIST_COMPONENT!r}，页面结构可能已变化")
    groups = array_of(block, "researchList")
    items: list[ResearchItem] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        category = str(group.get("title") or "")
        entries = group.get("list")
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict):
                items.append(_parse_item(entry, category))
    return items


def parse_research_detail(html: str, url: str = "") -> ResearchDetail:
    """解析科研进展详情页 HTML，返回 :class:`ResearchDetail`。

    Raises:
        ParseError: 页面里找不到 ``newsDetail`` 组件或其 ``mainObj``。
    """
    text = _repair_mojibake(html)
    block = component_script(text, DETAIL_COMPONENT)
    if not block:
        raise ParseError(f"页面中找不到组件 {DETAIL_COMPONENT!r}，页面结构可能已变化")
    main = object_of(block, "mainObj")
    return ResearchDetail(
        title=str(main.get("mainTitle") or ""),
        author=str(main.get("Author") or ""),
        category=str(main.get("Category") or main.get("type") or ""),
        date=_parse_datetime(str(main.get("Data") or "")) or parse_url_date(url),
        content_html=str(main.get("detailContent") or ""),
        url=url,
        raw=dict(main),
    )


#: ``2026-09-22 11:24:35`` / ``2026-09-22`` / ``2026/09/22`` 日期时间字面量。
_DATETIME_RE = re.compile(
    r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})"
    r"(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?"
)


def _parse_datetime(value: str) -> datetime | None:
    """把详情页 ``Data`` 字段（``2026-09-22 11:24:35`` 等）解析成 ``datetime``。"""
    match = _DATETIME_RE.search(value or "")
    if not match:
        return None
    year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
    hour = int(match.group(4) or 0)
    minute = int(match.group(5) or 0)
    second = int(match.group(6) or 0)
    try:
        return datetime(year, month, day, hour, minute, second)
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# 网络层
# --------------------------------------------------------------------------- #
def _drop_etag_cache() -> None:
    """删除本地 ETag 缓存条目，令下一次请求变为无条件 GET。"""
    try:
        from westlake_survival import _cache

        path = _cache.cache_path(CACHE_NAME)
        if path.exists():
            path.unlink()
    except OSError:  # 缓存删不掉不应阻断加载
        logger.debug("删除 ETag 缓存失败", exc_info=True)


def _check_response(response: requests.Response, url: str) -> None:
    """把详情页 HTTP 层失败翻译成库内异常。"""
    status = getattr(response, "status_code", 200)
    if status == 403 and is_offcampus(response):
        raise OffCampusError("官网科研进展详情页拒绝访问（403）")
    if status >= 400:
        raise ParseError(f"官网科研进展详情页返回 HTTP {status}：{url}")


def _fetch_list_html(
    session: requests.Session | None = None,
    *,
    refresh: bool = False,
    timeout: float | None = None,
) -> str:
    """抓取列表页 HTML（带 ETag 条件请求 + 本地缓存）。

    该站实测无 ETag 头，等价于普通 GET；复用
    :func:`~westlake_survival._cache.http_get_with_etag` 以获得与校历/新闻一致的
    缓存行为，再对返回文本做一次乱码修复。

    Raises:
        WestlakeError: 网络层失败（超时/连接错误等）。
        ParseError: HTTP 4xx/5xx。
        OffCampusError: 403 且命中校外阻断特征。
    """
    if refresh:
        _drop_etag_cache()
    try:
        body, _etag = http_get_with_etag(
            RESEARCH_URL,
            cache_name=CACHE_NAME,
            session=session,
            timeout=timeout if timeout is not None else DEFAULT_TIMEOUT,
        )
    except requests.HTTPError as exc:
        response = exc.response
        if response is not None and getattr(response, "status_code", 0) == 403:
            if is_offcampus(response):
                raise OffCampusError("官网科研进展列表页拒绝访问（403）") from exc
        status = getattr(response, "status_code", "?")
        raise ParseError(f"官网科研进展列表页返回 HTTP {status}：{RESEARCH_URL}") from exc
    except requests.Timeout as exc:
        raise WestlakeError(
            f"官网科研进展列表请求超时（{timeout if timeout is not None else DEFAULT_TIMEOUT}s）"
        ) from exc
    except requests.RequestException as exc:
        raise WestlakeError(f"官网科研进展列表请求失败：{exc}") from exc
    return _repair_mojibake(body)


def _decode_detail(response: requests.Response) -> str:
    """取详情页响应体，手动 UTF-8 解码（禁止 ``response.text``）。"""
    raw = getattr(response, "content", None)
    if raw is None:  # 兜底：只有 text 的替身对象
        return _repair_mojibake(getattr(response, "text", "") or "")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ParseError("官网科研进展详情页响应体不是合法 UTF-8") from exc


# --------------------------------------------------------------------------- #
# 公开 API
# --------------------------------------------------------------------------- #
def latest(
    category: str | None = None,
    limit: int | None = None,
    *,
    session: requests.Session | None = None,
    refresh: bool = False,
    timeout: float | None = None,
) -> list[ResearchItem]:
    """返回「科研进展」列表（按官网分组顺序展平，各组内保持官网顺序）。

    Args:
        category: 只看某研究方向；取值是分组 ``title``（见 :data:`CATEGORIES`，
            如 ``"生命健康 / Good Health & Wellbeing"``）。
        limit: 最多返回条数；``None`` 表示不限。
        session: 可注入的 :class:`requests.Session`（测试用）；缺省用
            :func:`westlake_survival._net.http_session`。
        refresh: 为 ``True`` 时先清掉本地 ETag 缓存再请求。
        timeout: 请求超时（秒），缺省 :data:`~westlake_survival._net.DEFAULT_TIMEOUT`。

    Returns:
        :class:`ResearchItem` 列表。

    Raises:
        WestlakeError: 网络层失败（超时/连接错误等）。
        ParseError: HTTP 4xx/5xx，或页面结构变化导致解析失败。
        OffCampusError: 被校外访问网关拦截（403 且命中阻断页特征）。
    """
    session = session if session is not None else http_session()
    items = parse_research_list(_fetch_list_html(session, refresh=refresh, timeout=timeout))
    if category is not None:
        items = [item for item in items if item.category == category]
    if limit is not None:
        items = items[: max(0, limit)]
    return items


def fetch_detail(
    url: str,
    *,
    session: requests.Session | None = None,
    timeout: float | None = None,
) -> ResearchDetail:
    """抓取并解析一篇科研进展详情（不缓存）。

    Args:
        url: 详情页地址（列表条目 :attr:`ResearchItem.url`）。
        session: 可注入的 :class:`requests.Session`（测试用）；缺省用
            :func:`westlake_survival._net.http_session`。
        timeout: 请求超时（秒），缺省 :data:`~westlake_survival._net.DEFAULT_TIMEOUT`。

    Returns:
        :class:`ResearchDetail`。

    Raises:
        ValueError: ``url`` 为空。
        WestlakeError: 网络层失败（超时/连接错误等）。
        ParseError: HTTP 4xx/5xx，或页面结构变化导致解析失败。
        OffCampusError: 被校外访问网关拦截（403 且命中阻断页特征）。
    """
    if not url:
        raise ValueError("url 不能为空")

    session = session if session is not None else http_session()
    effective_timeout = timeout if timeout is not None else DEFAULT_TIMEOUT
    try:
        response = session.get(url, timeout=effective_timeout)
    except requests.Timeout as exc:
        raise WestlakeError(f"官网科研进展详情请求超时（{effective_timeout}s）") from exc
    except requests.RequestException as exc:
        raise WestlakeError(f"官网科研进展详情请求失败：{exc}") from exc

    _check_response(response, url)
    return parse_research_detail(_decode_detail(response), url=url)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _handle_errors(func):
    """装饰器：把 :class:`WestlakeError` 转成中文提示 + 退出码 1。

    与 :func:`westlake_survival.news._handle_errors` 同款；此处自带一份以免与
    ``cli.main`` 形成循环导入。
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
    name="research",
    help="科研进展：官网 Research at Westlake 板块的研究报道与详情。",
    invoke_without_command=True,
)
@click.option(
    "--category",
    default=None,
    help="只看某研究方向（分组名，如「生命健康 / Good Health & Wellbeing」）。",
)
@click.option("--limit", type=int, default=10, show_default=True, help="最多显示条数。")
@click.pass_context
def cli_group(ctx: click.Context, category: str | None, limit: int) -> None:
    """``westlake research [--category X] [--limit N]`` / ``westlake research detail <url>``。"""
    if ctx.invoked_subcommand is not None:  # 交给 detail 子命令
        return
    _run_list(category=category, limit=limit)


@cli_group.command(name="detail")
@click.argument("url")
@_handle_errors
def research_detail_cmd(url: str) -> None:
    """显示一篇科研进展详情（标题 / 分类 / 作者 / 日期 / 正文）。"""
    from westlake_survival.cli.main import _print_table

    detail = fetch_detail(url)
    click.echo(f"标题：{detail.title or '—'}")
    click.echo(f"分类：{detail.category or '—'}　作者：{detail.author or '—'}")
    click.echo(f"日期：{detail.date.isoformat(sep=' ') if detail.date else '—'}")
    click.echo(f"链接：{detail.url or url}")
    body = _html_to_text(detail.content_html)
    if body:
        click.echo("正文：")
        click.echo(body)
    else:
        _print_table([("正文", "—")], ("项目", "内容"))


@_handle_errors
def _run_list(category: str | None, limit: int) -> None:
    """执行列表查询并打印表格（``_print_table`` 惰性导入以免循环依赖）。"""
    from westlake_survival.cli.main import _print_table

    items = latest(category=category, limit=limit)
    if not items:
        scope = f"方向 {category!r} 下" if category else ""
        click.echo(f"未找到{scope}科研进展。")
        return
    rows = [
        (
            item.date.strftime("%Y-%m-%d") if item.date else "—",
            item.category or "—",
            item.title or "—",
            item.url or "—",
        )
        for item in items
    ]
    _print_table(rows, ("日期", "方向", "标题", "链接"))


def _html_to_text(html: str) -> str:
    """把详情页富文本 HTML 粗略转成纯文本（去标签、压缩空白）。

    仅用于 CLI 展示；完整 HTML 仍保留在 :attr:`ResearchDetail.content_html`。
    """
    if not html:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
    text = text.replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'")
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)
