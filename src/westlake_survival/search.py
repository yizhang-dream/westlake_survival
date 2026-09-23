"""官网全站搜索（Site Search）客户端。

数据源是西湖大学官网的 TRS WAS5 全站搜索 JSON 接口（2026-09-22 实测可用）::

    GET https://www.westlake.edu.cn/was5/web/search
        ?channelid=276758&searchword=<关键词>&page=<n>

返回 JSON 信封::

    {
      "searchTime": 0.018, "page": 1, "pageCount": 392, "perpage": 10, "count": 3916,
      "data": [
        {"docchannel": 4721, "title": "...", "time": "2026-09-23", "docid": 69819,
         "content": "", "desc": "...", "url": "https://...", "author": "",
         "subdoctitle": "", "doclink": "", "target": "_self"}
      ]
    }

``page`` 从 1 起，``count`` 是命中总数，``pageCount`` 是可翻页数。

实测坑位
========
- 响应头是 ``Content-Type: text/html;charset=UTF-8``，``requests`` 会把
  ``response.encoding`` 当成 ISO-8859-1，``response.text`` 因此得到乱码；
  本模块一律取 ``response.content`` 手动 UTF-8 解码。
- 正文前有若干 ``\\r\\n`` 空行，``json.loads`` 之前必须先 ``strip()``。
- ``title`` / ``desc`` 里命中关键词被 ``<font color=>…</font>`` 包裹，
  :attr:`SearchHit.clean_title` 给出剥掉标签后的纯文本。
- ``author`` 在招聘类条目里是 ``"全职"`` 之类的分类词而非人名，原样保留。
- 该接口公开可达（校外可直连），故连接失败不按 :class:`OffCampusError`
  处理，统一映射为 :class:`WestlakeError`。

查询类接口不做本地缓存，每次调用都真发请求。
"""

from __future__ import annotations

import functools
import json
import re
from dataclasses import dataclass, field
from datetime import date

import click
import requests

from westlake_survival._net import DEFAULT_TIMEOUT, http_session
from westlake_survival.exceptions import OffCampusError, ParseError, WestlakeError, is_offcampus

__all__ = [
    "SEARCH_URL",
    "CHANNEL_ID",
    "PER_PAGE",
    "SearchHit",
    "SearchResult",
    "search",
    "parse_search",
    "parse_date",
    "strip_font_tags",
    "cli_group",
]

#: 全站搜索接口地址（GET）。
SEARCH_URL = "https://www.westlake.edu.cn/was5/web/search"

#: 官网「全站搜索」频道号（2026-09-22 实测；改版后可能变化）。
CHANNEL_ID = "276758"

#: 服务端默认每页条数（响应里的 ``perpage``）。
PER_PAGE = 10

#: ``<font color=>…</font>`` 命中高亮标签。
_FONT_TAG_RE = re.compile(r"</?font\b[^>]*>", re.IGNORECASE)

#: ``YYYY-MM-DD`` / ``YYYY/MM/DD`` 日期字面量。
_DATE_RE = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})")


# --------------------------------------------------------------------------- #
# 数据模型
# --------------------------------------------------------------------------- #
def strip_font_tags(text: str) -> str:
    """剥掉命中高亮用的 ``<font>`` 标签并去掉首尾空白。

    例：``"<font color=>西湖</font>理学讲坛"`` → ``"西湖理学讲坛"``。
    """
    return _FONT_TAG_RE.sub("", text or "").strip()


def parse_date(value: str) -> date | None:
    """把 ``2026-09-23``（或 ``2026/09/23``）解析成 :class:`datetime.date`。

    空串或无法解析时返回 ``None``（搜索接口偶有条目缺日期）。
    """
    match = _DATE_RE.search(value or "")
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


@dataclass
class SearchHit:
    """一条全站搜索命中。

    ``title`` 是原文（含 ``<font>`` 高亮标签），:attr:`clean_title` 是剥掉
    标签后的纯文本，展示时应用后者。
    """

    title: str
    url: str
    date: date | None = None
    desc: str = ""
    author: str = ""
    docchannel: int | None = None
    raw: dict = field(default_factory=dict)

    @property
    def clean_title(self) -> str:
        """去掉 ``<font>`` 高亮标签后的标题。"""
        return strip_font_tags(self.title)

    @property
    def clean_desc(self) -> str:
        """去掉 ``<font>`` 高亮标签后的摘要。"""
        return strip_font_tags(self.desc)


@dataclass
class SearchResult:
    """一页搜索结果。

    ``total`` 是命中总数（信封 ``count``），``page_count`` 是可翻页数
    （信封 ``pageCount``），``page`` 是当前页码（从 1 起）。
    """

    hits: list[SearchHit] = field(default_factory=list)
    page: int = 1
    page_count: int = 0
    total: int = 0

    def __len__(self) -> int:
        return len(self.hits)

    def __iter__(self):
        return iter(self.hits)

    @property
    def has_next(self) -> bool:
        """是否还有下一页。"""
        return self.page < self.page_count


# --------------------------------------------------------------------------- #
# 网络层
# --------------------------------------------------------------------------- #
def _check_response(response: requests.Response) -> None:
    """把 HTTP 层失败翻译成库内异常。"""
    status = getattr(response, "status_code", 200)
    url = getattr(response, "url", "") or SEARCH_URL
    if status == 403 and is_offcampus(response):
        raise OffCampusError("官网搜索接口拒绝访问（403）")
    if status >= 400:
        raise ParseError(f"官网搜索接口返回 HTTP {status}：{url}")


def _decode_payload(response: requests.Response) -> dict:
    """把响应体手动 UTF-8 解码后解析成 JSON 对象。

    ``Content-Type`` 是 ``text/html``，不能用 ``response.text``（latin-1 乱码），
    因此取 ``content`` 原始字节解码，再 strip 掉正文前导空行。
    """
    raw = getattr(response, "content", None)
    if raw is None:  # 兜底：只有 text 的替身对象
        text = getattr(response, "text", "") or ""
    else:
        text = raw.decode("utf-8", errors="replace")
    text = text.strip()
    if not text:
        raise ParseError("官网搜索接口返回空响应体")
    try:
        payload = json.loads(text)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ParseError("官网搜索接口未返回合法 JSON（响应体可能被截断）") from exc
    if not isinstance(payload, dict):
        raise ParseError("官网搜索接口返回的 JSON 顶层不是对象")
    return payload


def _parse_hit(raw: dict) -> SearchHit:
    """把一个原始条目字典转成 :class:`SearchHit`。"""
    docchannel = raw.get("docchannel")
    if isinstance(docchannel, str) and docchannel.isdigit():
        docchannel = int(docchannel)
    elif not isinstance(docchannel, int):
        docchannel = None
    return SearchHit(
        title=str(raw.get("title") or ""),
        url=str(raw.get("url") or ""),
        date=parse_date(str(raw.get("time") or "")),
        desc=str(raw.get("desc") or ""),
        author=str(raw.get("author") or ""),
        docchannel=docchannel,
        raw=dict(raw),
    )


def parse_search(payload: dict, *, page: int = 1) -> SearchResult:
    """解析搜索接口的 JSON 信封，返回 :class:`SearchResult`。

    信封里缺 ``data`` 列表（或类型不对）时抛 :class:`ParseError`。
    """
    raw_hits = payload.get("data")
    if raw_hits is None:
        raw_hits = []
    if not isinstance(raw_hits, list):
        raise ParseError("官网搜索接口的 data 字段不是数组")

    hits = [_parse_hit(item) for item in raw_hits if isinstance(item, dict)]

    def _int(value, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    return SearchResult(
        hits=hits,
        page=_int(payload.get("page"), page),
        page_count=_int(payload.get("pageCount"), 0),
        total=_int(payload.get("count"), len(hits)),
    )


def search(
    keyword: str,
    page: int = 1,
    *,
    session: requests.Session | None = None,
    timeout: float | None = None,
) -> SearchResult:
    """在官网全站搜索 ``keyword``，返回第 ``page`` 页结果。

    Args:
        keyword: 检索词（原样交给服务端做 URL 编码）。
        page: 页码，从 1 起。
        session: 可注入的 :class:`requests.Session`（测试用）；缺省用
            :func:`westlake_survival._net.http_session`。
        timeout: 请求超时（秒），缺省 :data:`~westlake_survival._net.DEFAULT_TIMEOUT`。

    Returns:
        :class:`SearchResult`；无命中时 ``hits`` 为空列表。

    Raises:
        ValueError: ``page`` 小于 1。
        WestlakeError: 网络层失败（超时/连接错误等）。
        ParseError: HTTP 4xx/5xx，或响应体不是合法 JSON 信封。
        OffCampusError: 被校外访问网关拦截（403 且命中阻断页特征）。
    """
    if page < 1:
        raise ValueError(f"page 必须 >= 1，得到 {page!r}")

    session = session if session is not None else http_session()
    params = {"channelid": CHANNEL_ID, "searchword": keyword, "page": page}
    try:
        response = session.get(
            SEARCH_URL,
            params=params,
            timeout=timeout if timeout is not None else DEFAULT_TIMEOUT,
        )
    except requests.Timeout as exc:
        raise WestlakeError(
            f"官网搜索请求超时（{timeout if timeout is not None else DEFAULT_TIMEOUT}s）"
        ) from exc
    except requests.RequestException as exc:
        raise WestlakeError(f"官网搜索请求失败：{exc}") from exc

    _check_response(response)
    return parse_search(_decode_payload(response), page=page)


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
    name="search",
    help="官网全站搜索：检索西湖大学官网内容。",
    invoke_without_command=True,
    # 组默认不解析位置参数之后的选项；本组的关键词是位置参数，
    # 需要允许 `westlake search 西湖 --page 2` 这种写法。
    context_settings={"allow_interspersed_args": True},
)
@click.argument("keyword", required=False)
@click.option("--page", type=int, default=1, show_default=True, help="页码（从 1 开始）。")
@click.option("--limit", type=int, default=10, show_default=True, help="最多显示条数。")
@click.pass_context
def cli_group(ctx: click.Context, keyword: str | None, page: int, limit: int) -> None:
    """``westlake search <关键词> [--page N] [--limit N]``。"""
    if ctx.invoked_subcommand is not None:  # 预留给未来的子命令
        return
    if not keyword:
        raise click.UsageError("缺少参数：关键词")
    if page < 1:
        raise click.UsageError(f"--page 必须 >= 1，得到 {page}")
    _run_search(keyword, page=page, limit=limit)


@_handle_errors
def _run_search(keyword: str, *, page: int, limit: int) -> None:
    """执行检索并打印表格（``_print_table`` 惰性导入以免循环依赖）。"""
    from westlake_survival.cli.main import _print_table

    result = search(keyword, page=page)
    if not result.hits:
        click.echo("未找到匹配的内容。")
        return
    click.echo(
        f"关键词：{keyword}　共 {result.total} 条，第 {result.page}/{result.page_count} 页"
    )
    rows = [
        (
            hit.date.isoformat() if hit.date else "—",
            hit.clean_title or "—",
            hit.author or "—",
            hit.url or "—",
        )
        for hit in result.hits[: max(0, limit)]
    ]
    _print_table(rows, ("日期", "标题", "作者", "链接"))