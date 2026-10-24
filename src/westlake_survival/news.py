"""西湖新闻（Westlake News）客户端。

数据源是西湖大学官网「西湖新闻」列表页
``https://www.westlake.edu.cn/news_events/westlakenews/allnews/``（2026-09-22
实测，校外可直连）。该页同样是 Vue 单页应用，真正的数据不在 DOM 里，而是内嵌
在页面 ``<script>`` 的一段 ``new allNews("#app", { ... })`` 调用中：

* ``topicsList``：**全量**新闻数组（实测约 1631 条，前端分页只是展示层），
  每条形如::

      {
        imgUrl: "../people/202609/W020260922412722347323.jpg",
        title: "人物",                       # 注意！这是**分类**
        content: "本校“最大气”的两位老师！",   # 这才是**新闻标题**
        time: "2026-09-22 11:24:35",
        url: "https://.../t20260922_69940.html",
      }

* 页面里的 ``page`` / 分页逻辑只作用于前端展示，服务端返回的是全量数组，
  因此本模块的 :func:`latest` 一次请求即可拿到所有新闻，本地做分类过滤与截断。

字段名陷阱
==========
列表条目里的 ``title`` 是**分类**（人物|资讯|学术|校园|招生|媒体|影像），
``content`` 才是**新闻标题**；详情页则把标题放在 ``mainObj.mainTitle``。本模块
在 :class:`NewsItem` 层已把二者映射为语义正确的 ``title`` / ``category``。

详情页
======
``GET <url>`` 返回 ``new newsDetail("#app", { mainObj: { Data, mainTitle, Author,
Category, categoryUrl, type, detailContent, ... } })``（2026-09-22 实测键名），
其中 ``Data`` 是 ``"2026-09-22 11:24:35"`` 形式的日期时间，``detailContent``
是富文本 HTML。详情页不做本地缓存，每次调用都真发请求。

编码坑位
========
该站响应头是 ``Content-Type: text/html``（**无 charset**），``requests`` 会把
``response.encoding`` 当成 ISO-8859-1，直接读 ``response.text`` 会得到乱码；
本模块一律取 ``response.content`` 手动 UTF-8 解码。列表页复用
:func:`westlake_survival._cache.http_get_with_etag`（该站实测无 ETag 头，等价
于普通 GET），并用 :func:`_repair_mojibake` 兜底修复可能的乱码。

组件块里混有 ``turnToEn: function (str) { ... }`` 等回调，不能对整个块调用
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
    "NEWS_URL",
    "LIST_COMPONENT",
    "DETAIL_COMPONENT",
    "CACHE_NAME",
    "CATEGORIES",
    "NewsItem",
    "NewsDetail",
    "parse_datetime",
    "parse_news_list",
    "parse_news_detail",
    "latest",
    "fetch_detail",
    "cli_group",
]

logger = logging.getLogger(__name__)

#: 「西湖新闻」列表页（唯一可抓取的全量列表）。
NEWS_URL = "https://www.westlake.edu.cn/news_events/westlakenews/allnews/"

#: 列表页组件构造函数名。
LIST_COMPONENT = "allNews"

#: 详情页组件构造函数名。
DETAIL_COMPONENT = "newsDetail"

#: ETag 缓存文件名（相对缓存目录）。
CACHE_NAME = "news/allnews.html"

#: 双语源（2026-10-25 实测）：英文主站 en.westlake.edu.cn 同构、组件同名；
#: 英文全量列表在 ``all_news/``（中文是 allnews/，路径不同名；英文页组件带
#: ``mounted: function(){}`` 回调，解析前须本地剥除——共享解析器按仓库约定不扩）。
NEWS_URLS = {"zh": NEWS_URL, "en": "https://en.westlake.edu.cn/news_events/westlakenews/all_news/"}
CACHE_BY_LANG = {"zh": CACHE_NAME, "en": "news/allnews_en.html"}

#: 已知的分类（列表条目 ``title`` 字段的取值，实测于 2026-09-22）。
CATEGORIES = ("人物", "资讯", "学术", "校园", "招生", "媒体", "影像")

#: ``2026-09-22 11:24:35`` / ``2026-09-22`` / ``2026/09/22`` 日期时间字面量。
_DATETIME_RE = re.compile(
    r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})"
    r"(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?"
)


# --------------------------------------------------------------------------- #
# JS 提取工具
# --------------------------------------------------------------------------- #
def _repair_mojibake(text: str) -> str:
    """修复"UTF-8 被当成 ISO-8859-1 解码"造成的乱码。

    与 :func:`westlake_survival.calendar._repair_mojibake` 同款：该站响应无
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
def parse_datetime(value: str) -> datetime | None:
    """把 ``2026-09-22 11:24:35``（或 ``2026-09-22`` / ``2026/09/22``）解析成
    :class:`datetime.datetime`。

    空串或无法解析时返回 ``None``（历史条目偶有缺日期）。
    """
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


@dataclass
class NewsItem:
    """列表页的一条新闻。

    注意字段映射陷阱：原始条目的 ``title`` 是**分类**、``content`` 是**标题**，
    本类已把它们分别映射到语义正确的 :attr:`category` 与 :attr:`title`。
    """

    title: str
    category: str
    date: datetime | None = None
    url: str = ""
    img_url: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class NewsDetail:
    """详情页的一篇新闻。

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
def _parse_item(raw: dict) -> NewsItem:
    """把一个原始列表条目转成 :class:`NewsItem`（含 title↔category 映射）。"""
    return NewsItem(
        # content 才是新闻标题，title 是分类——切勿对调。
        title=str(raw.get("content") or ""),
        category=str(raw.get("title") or ""),
        date=parse_datetime(str(raw.get("time") or "")),
        url=str(raw.get("url") or ""),
        img_url=str(raw.get("imgUrl") or ""),
        raw=dict(raw),
    )


def parse_news_list(html: str) -> list[NewsItem]:
    """解析「西湖新闻」列表页 HTML，返回全部 :class:`NewsItem`。

    列表页组件块里混有 ``function () {}`` 回调，故先用
    :func:`~westlake_survival._trs.component_script` 截出块文本，再只对
    ``topicsList`` 数组调用 :func:`~westlake_survival._trs.js_literal`。

    Raises:
        ParseError: 页面里找不到 ``allNews`` 组件或 ``topicsList`` 数组。
    """
    text = _repair_mojibake(html)
    block = component_script(text, LIST_COMPONENT)
    if not block:
        raise ParseError(f"页面中找不到组件 {LIST_COMPONENT!r}，页面结构可能已变化")
    raw_items = array_of(block, "topicsList")
    return [_parse_item(item) for item in raw_items if isinstance(item, dict)]


def parse_news_detail(html: str, url: str = "") -> NewsDetail:
    """解析新闻详情页 HTML，返回 :class:`NewsDetail`。

    Raises:
        ParseError: 页面里找不到 ``newsDetail`` 组件或其 ``mainObj``。
    """
    text = _repair_mojibake(html)
    block = component_script(text, DETAIL_COMPONENT)
    if not block:
        raise ParseError(f"页面中找不到组件 {DETAIL_COMPONENT!r}，页面结构可能已变化")
    main = object_of(block, "mainObj")
    return NewsDetail(
        title=str(main.get("mainTitle") or ""),
        author=str(main.get("Author") or ""),
        category=str(main.get("Category") or main.get("type") or ""),
        date=parse_datetime(str(main.get("Data") or "")),
        content_html=str(main.get("detailContent") or ""),
        url=url,
        raw=dict(main),
    )


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
        raise OffCampusError("官网新闻详情页拒绝访问（403）")
    if status >= 400:
        raise ParseError(f"官网新闻详情页返回 HTTP {status}：{url}")


def _fetch_list_html(
    session: requests.Session | None = None,
    *,
    refresh: bool = False,
    timeout: float | None = None,
    lang: str = "zh",
) -> str:
    """抓取列表页 HTML（带 ETag 条件请求 + 本地缓存）。

    该站实测无 ETag 头，等价于普通 GET；复用
    :func:`~westlake_survival._cache.http_get_with_etag` 以获得与校历一致的
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
            NEWS_URLS.get(lang, NEWS_URL),
            cache_name=CACHE_BY_LANG.get(lang, CACHE_NAME),
            session=session,
            timeout=timeout if timeout is not None else DEFAULT_TIMEOUT,
        )
    except requests.HTTPError as exc:
        response = exc.response
        if response is not None and getattr(response, "status_code", 0) == 403:
            if is_offcampus(response):
                raise OffCampusError("官网新闻列表页拒绝访问（403）") from exc
        status = getattr(response, "status_code", "?")
        raise ParseError(f"官网新闻列表页返回 HTTP {status}：{NEWS_URLS.get(lang, NEWS_URL)}") from exc
    except requests.Timeout as exc:
        raise WestlakeError(
            f"官网新闻列表请求超时（{timeout if timeout is not None else DEFAULT_TIMEOUT}s）"
        ) from exc
    except requests.RequestException as exc:
        raise WestlakeError(f"官网新闻列表请求失败：{exc}") from exc
    return _repair_mojibake(body)


def _decode_detail(response: requests.Response) -> str:
    """取详情页响应体，手动 UTF-8 解码（禁止 ``response.text``）。"""
    raw = getattr(response, "content", None)
    if raw is None:  # 兜底：只有 text 的替身对象
        return _repair_mojibake(getattr(response, "text", "") or "")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ParseError("官网新闻详情页响应体不是合法 UTF-8") from exc


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
    lang: str = "zh",
) -> list[NewsItem]:
    """返回「西湖新闻」列表（默认按官网顺序，最新在前）。

    Args:
        category: 只看某分类；取值是列表条目原始的 ``title`` 字段值
            （见 :data:`CATEGORIES`，如 ``"人物"`` / ``"资讯"``）。
        limit: 最多返回条数；``None`` 表示不限。
        session: 可注入的 :class:`requests.Session`（测试用）；缺省用
            :func:`westlake_survival._net.http_session`。
        refresh: 为 ``True`` 时先清掉本地 ETag 缓存再请求。
        timeout: 请求超时（秒），缺省 :data:`~westlake_survival._net.DEFAULT_TIMEOUT`。

    Returns:
        :class:`NewsItem` 列表。

    Raises:
        WestlakeError: 网络层失败（超时/连接错误等）。
        ParseError: HTTP 4xx/5xx，或页面结构变化导致解析失败。
        OffCampusError: 被校外访问网关拦截（403 且命中阻断页特征）。
    """
    session = session if session is not None else http_session()
    items = parse_news_list(
        _fetch_list_html(session, refresh=refresh, timeout=timeout, lang=lang)
    )
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
) -> NewsDetail:
    """抓取并解析一篇新闻详情（不缓存）。

    Args:
        url: 详情页地址（列表条目 :attr:`NewsItem.url`）。
        session: 可注入的 :class:`requests.Session`（测试用）；缺省用
            :func:`westlake_survival._net.http_session`。
        timeout: 请求超时（秒），缺省 :data:`~westlake_survival._net.DEFAULT_TIMEOUT`。

    Returns:
        :class:`NewsDetail`。

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
        raise WestlakeError(f"官网新闻详情请求超时（{effective_timeout}s）") from exc
    except requests.RequestException as exc:
        raise WestlakeError(f"官网新闻详情请求失败：{exc}") from exc

    _check_response(response, url)
    return parse_news_detail(_decode_detail(response), url=url)


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
    name="news",
    help="西湖新闻：最新资讯与详情。",
    invoke_without_command=True,
)
@click.option(
    "--category",
    default=None,
    help="只看某分类（人物|资讯|学术|校园|招生|媒体|影像）。",
)
@click.option("--limit", type=int, default=10, show_default=True, help="最多显示条数。")
@click.option("--lang", type=click.Choice(["zh", "en"]), default="zh", show_default=True,
              help="语言：zh=中文主站 en=英文主站（英文分类值为英文，如 People/News）。")
@click.pass_context
def cli_group(ctx: click.Context, category: str | None, limit: int, lang: str) -> None:
    """``westlake news [--category X] [--limit N] [--lang en]`` / ``westlake news detail <url>``。"""
    if ctx.invoked_subcommand is not None:  # 交给 detail 子命令
        return
    _run_list(category=category, limit=limit, lang=lang)


@cli_group.command(name="detail")
@click.argument("url")
@_handle_errors
def news_detail_cmd(url: str) -> None:
    """显示一篇新闻详情（标题 / 分类 / 作者 / 日期 / 正文）。"""
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
def _run_list(category: str | None, limit: int, lang: str = "zh") -> None:
    """执行列表查询并打印表格（``_print_table`` 惰性导入以免循环依赖）。"""
    from westlake_survival.cli.main import _print_table

    items = latest(category=category, limit=limit, lang=lang)
    if not items:
        scope = f"分类 {category!r} 下" if category else ""
        click.echo(f"未找到{scope}新闻。")
        return
    rows = [
        (
            item.date.strftime("%Y-%m-%d %H:%M") if item.date else "—",
            item.category or "—",
            item.title or "—",
            item.url or "—",
        )
        for item in items
    ]
    _print_table(rows, ("时间", "分类", "标题", "链接"))


def _html_to_text(html: str) -> str:
    """把详情页富文本 HTML 粗略转成纯文本（去标签、压缩空白）。

    仅用于 CLI 展示；完整 HTML 仍保留在 :attr:`NewsDetail.content_html`。
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