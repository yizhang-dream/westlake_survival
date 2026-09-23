"""人才招聘（Open Positions）解析与查询。

数据源是学校招聘主页
``https://www.westlake.edu.cn/careers/OpenPositions/``。该页是 Vue 单页应用，
真正可用的数据内嵌在 HTML 的 ``<script>`` 里的一段 ``new career("#app", { ... })``
调用中（2026-09-22 实测）：

* ``roleList``：全量岗位数组（约 628 条），每条形如::

      {
        category: "博士后",                       // 类别
        dept: "西湖大学…课题组博士后招聘启事",      // 注意：这是**岗位标题**
        type: "全职, 生命科学学院, 中国杭州，云谷校区",  // 性质 / 部门 / 地点
        url: "https://www.westlake.edu.cn/careers/OpenPositions/…/t…html",  // 官网详情
        url2: "",                                  // 外部招聘平台链接（优先展示）
        target: "_self",
        date: "2026-09-20",
      }

详情页 ``GET <url>`` 内嵌 ``new careerDetail("#app", {topObj: {…}, mainStr: "…"})``，
``topObj`` 给标题/类别/部门/地点/岗位性质，``mainStr`` 是正文 HTML。

实测坑位
========
- 组件对象里混有 ``mounted: function () { }`` 之类回调，**不能**整块交给
  :func:`~westlake_survival._trs.js_literal`；先按键定位、再对目标片段单独解析。
- 响应头是 ``Content-Type: text/html``（无 charset），``requests`` 会把
  ``encoding`` 当成 ISO-8859-1，``response.text`` 因此乱码；本模块一律取
  ``response.content`` 手动 UTF-8 解码。
- ``type`` 字段用逗号分隔三段，中英文逗号混用（第 2、3 段之间是中文逗号），
  且地点本身含中文逗号（``中国杭州，云谷校区``），因此按逗号**最多切两刀**。
- ``url2`` 实测当前全为空串；非空时多为 ``app.mokahr.com`` 外部招聘平台，
  这类岗位不做详情解析，:func:`fetch_detail` 直接原样返回外链。
- 列表页返回头不带 ``ETag``（实测），条件 GET 命中不了 304；仍照
  :mod:`westlake_survival.calendar` 的用法走 :mod:`westlake_survival._cache`
  读写缓存，服务器日后补上 ``ETag`` 即自动生效。
- 该页公开可达（校外可直连），连接失败统一映射为
  :class:`~westlake_survival.exceptions.WestlakeError`，不按
  :class:`~westlake_survival.exceptions.OffCampusError` 处理（403 命中阻断页
  特征时仍按后者）。
"""

from __future__ import annotations

import functools
import logging
import re
from dataclasses import dataclass, field
from datetime import date

import click
import requests

from westlake_survival import _cache
from westlake_survival._net import DEFAULT_TIMEOUT, http_session
from westlake_survival._trs import array_of, component_script, js_literal, object_of
from westlake_survival.exceptions import OffCampusError, ParseError, WestlakeError, is_offcampus

__all__ = [
    "POSITIONS_URL",
    "CACHE_NAME",
    "COMPONENT_NAME",
    "DETAIL_COMPONENT_NAME",
    "Position",
    "PositionDetail",
    "split_type",
    "parse_date",
    "parse_position",
    "parse_positions",
    "parse_detail",
    "positions",
    "fetch_detail",
    "cli_group",
]

logger = logging.getLogger(__name__)

#: 招聘主页（列表页，唯一可抓取的岗位清单页面）。
POSITIONS_URL = "https://www.westlake.edu.cn/careers/OpenPositions/"

#: ETag 缓存文件名（相对缓存目录）。
CACHE_NAME = "careers/positions.html"

#: 列表页组件构造函数名。
COMPONENT_NAME = "career"

#: 详情页组件构造函数名。
DETAIL_COMPONENT_NAME = "careerDetail"

#: ``type`` 字段的分隔符：半角/全角逗号。
_TYPE_SEP = re.compile(r"[,\uff0c]")

#: ``YYYY-MM-DD`` / ``YYYY/MM/DD`` 日期字面量。
_DATE_RE = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})")

#: 外部招聘平台域名特征：命中则不做详情解析，直接返回外链。
_EXTERNAL_HOSTS = ("app.mokahr.com",)


# --------------------------------------------------------------------------- #
# 数据模型
# --------------------------------------------------------------------------- #
@dataclass
class Position:
    """一条岗位。

    ``title`` 取自原始数据的 ``dept`` 字段（官网把**岗位标题**放在 ``dept`` 里，
    ``department`` 才是部门，取自 ``type`` 的第二段）。``external_url`` 是外部
    招聘平台链接（原始 ``url2``），:attr:`apply_url` 优先给出它，没有时退回官网
    详情 ``url``。
    """

    title: str
    category: str = ""
    job_type: str = ""
    department: str = ""
    location: str = ""
    date: date | None = None
    url: str = ""
    external_url: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def apply_url(self) -> str:
        """申请链接：外部平台 ``url2`` 优先，缺省退回官网详情 ``url``。"""
        return self.external_url or self.url

    @property
    def is_external(self) -> bool:
        """申请入口是否指向外部招聘平台。"""
        return bool(self.external_url)


@dataclass
class PositionDetail:
    """一个岗位的详情页内容。

    ``content_html`` 是正文 HTML（原始 ``mainStr``）；对跳到外部招聘平台的
    岗位，:func:`fetch_detail` 不做解析，返回的实例 ``content_html`` 为空串、
    ``url`` 为外部链接本身。
    """

    title: str
    category: str = ""
    department: str = ""
    address: str = ""
    job_type: str = ""
    content_html: str = ""
    url: str = ""
    raw: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# 文本与字段解析
# --------------------------------------------------------------------------- #
def split_type(value: str) -> tuple[str, str, str]:
    """拆分 ``type`` 字段为 ``(岗位性质, 部门, 地点)``。

    原始格式是逗号分隔的三段（``"全职, 医学院, 中国杭州，云谷校区"``），中英文
    逗号混用；地点段自身含中文逗号，故按逗号**最多切两刀**，保证地点不被切碎。
    段数不足时缺失项为空串。
    """
    parts = [p.strip() for p in _TYPE_SEP.split(value or "", maxsplit=2)]
    while len(parts) < 3:
        parts.append("")
    return parts[0], parts[1], parts[2]


def parse_date(value: str) -> date | None:
    """把 ``2026-09-20``（或 ``2026/09/20``）解析成 :class:`datetime.date`。

    空串或无法解析时返回 ``None``。
    """
    match = _DATE_RE.search(value or "")
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _extract_string(block: str, key: str) -> str:
    """取出组件块里 ``key: "..."`` 的字符串字面量并解出转义后的文本。"""
    m = re.search(r"\b" + re.escape(key) + r"\s*:\s*(\"(?:[^\"\\]|\\.)*\")", block)
    if not m:
        raise ParseError(f"组件数据中找不到键 {key!r}")
    return js_literal(m.group(1))


def parse_position(raw: dict) -> Position:
    """把一个原始岗位字典转成 :class:`Position`。"""
    job_type, department, location = split_type(str(raw.get("type") or ""))
    return Position(
        title=str(raw.get("dept") or "").strip(),
        category=str(raw.get("category") or "").strip(),
        job_type=job_type,
        department=department,
        location=location,
        date=parse_date(str(raw.get("date") or "")),
        url=str(raw.get("url") or "").strip(),
        external_url=str(raw.get("url2") or "").strip(),
        raw=dict(raw),
    )


def parse_positions(html: str) -> list[Position]:
    """解析招聘主页 HTML，返回全部岗位。

    Raises:
        ParseError: 页面里找不到 ``career`` 组件或 ``roleList`` 键。
    """
    block = component_script(html, COMPONENT_NAME)
    if not block:
        raise ParseError(f"页面中找不到组件 {COMPONENT_NAME!r}，页面结构可能已变化")
    raw_list = array_of(block, "roleList")
    return [parse_position(item) for item in raw_list if isinstance(item, dict)]


def parse_detail(html: str, url: str = "") -> PositionDetail:
    """解析岗位详情页 HTML，返回 :class:`PositionDetail`。

    Raises:
        ParseError: 页面里找不到 ``careerDetail`` 组件或 ``topObj`` / ``mainStr``。
    """
    block = component_script(html, DETAIL_COMPONENT_NAME)
    if not block:
        raise ParseError(f"页面中找不到组件 {DETAIL_COMPONENT_NAME!r}，页面结构可能已变化")
    top = object_of(block, "topObj")
    content = _extract_string(block, "mainStr")
    return PositionDetail(
        title=str(top.get("title") or "").strip(),
        category=str(top.get("category") or "").strip(),
        department=str(top.get("department") or "").strip(),
        address=str(top.get("address") or "").strip(),
        job_type=str(top.get("jobType") or "").strip(),
        content_html=content,
        url=url,
        raw=top,
    )


# --------------------------------------------------------------------------- #
# 网络层
# --------------------------------------------------------------------------- #
def is_external_url(url: str) -> bool:
    """``url`` 是否指向外部招聘平台（``url2`` 常见形态）。"""
    lowered = (url or "").lower()
    return any(host in lowered for host in _EXTERNAL_HOSTS)


def _check_response(response: requests.Response) -> None:
    """把 HTTP 层失败翻译成库内异常。"""
    status = getattr(response, "status_code", 200)
    url = getattr(response, "url", "") or POSITIONS_URL
    if status == 403 and is_offcampus(response):
        raise OffCampusError("招聘页面拒绝访问（403）")
    if status >= 400:
        raise ParseError(f"招聘页面返回 HTTP {status}：{url}")


def _drop_cache() -> None:
    """删除本地 ETag 缓存条目，令下一次请求变为无条件 GET。"""
    try:
        path = _cache.cache_path(CACHE_NAME)
        if path.exists():
            path.unlink()
    except OSError:  # 缓存删不掉不应阻断加载
        logger.debug("删除招聘页 ETag 缓存失败", exc_info=True)


def _fetch_list_html(
    *,
    session: requests.Session | None = None,
    timeout: float | None = None,
    refresh: bool = False,
) -> str:
    """抓取招聘主页 HTML（照 calendar 用法走 ``_cache`` 的 ETag 条件 GET）。

    响应无 charset 头，故一律取 ``response.content`` 手动 UTF-8 解码，绝不使用
    ``response.text``。缓存只存公开页面内容，不涉凭据。
    """
    session = session if session is not None else http_session()
    if refresh:
        _drop_cache()
    cached = _cache.load_json(CACHE_NAME, default=None) or {}
    headers = {"If-None-Match": cached["etag"]} if cached.get("etag") else {}
    try:
        response = session.get(
            POSITIONS_URL,
            headers=headers,
            timeout=timeout if timeout is not None else DEFAULT_TIMEOUT,
        )
    except requests.Timeout as exc:
        raise WestlakeError(
            f"招聘页面请求超时（{timeout if timeout is not None else DEFAULT_TIMEOUT}s）"
        ) from exc
    except requests.RequestException as exc:
        raise WestlakeError(f"招聘页面请求失败：{exc}") from exc

    if response.status_code == 304 and cached.get("body"):
        return cached["body"]
    _check_response(response)

    raw = getattr(response, "content", None)
    if raw is None:  # 兜底：只有 text 的替身对象
        text = getattr(response, "text", "") or ""
    else:
        text = raw.decode("utf-8", errors="replace")
    etag = response.headers.get("ETag")
    if etag:
        _cache.save_json(CACHE_NAME, {"etag": etag, "body": text})
    return text


# --------------------------------------------------------------------------- #
# 公开 API
# --------------------------------------------------------------------------- #
def positions(
    category: str | None = None,
    keyword: str | None = None,
    limit: int | None = None,
    *,
    session: requests.Session | None = None,
    timeout: float | None = None,
    refresh: bool = False,
) -> list[Position]:
    """抓取并返回岗位列表，可按类别/关键词过滤。

    Args:
        category: 岗位类别，精确匹配（如 ``"博士后"``、``"科研团队"``）；
            缺省不过滤。
        keyword: 关键词，对岗位标题（``title``）做**大小写不敏感**的模糊匹配；
            缺省不过滤。
        limit: 最多返回条数；``None`` 表示不限。
        session: 可注入的 :class:`requests.Session`（测试用）。
        timeout: 请求超时（秒），缺省 :data:`~westlake_survival._net.DEFAULT_TIMEOUT`。
        refresh: 为 ``True`` 时先清本地 ETag 缓存再请求，强制拿最新内容。

    Returns:
        :class:`Position` 列表；无匹配时为空列表。

    Raises:
        ValueError: ``limit`` 为负数。
        WestlakeError: 网络层失败（超时/连接错误等）。
        ParseError: HTTP 4xx/5xx，或页面结构变化导致解析失败。
        OffCampusError: 被校外访问网关拦截（403 且命中阻断页特征）。
    """
    if limit is not None and limit < 0:
        raise ValueError(f"limit 必须 >= 0，得到 {limit!r}")

    items = parse_positions(
        _fetch_list_html(session=session, timeout=timeout, refresh=refresh)
    )
    if category:
        wanted = category.strip()
        items = [p for p in items if p.category == wanted]
    if keyword:
        needle = keyword.strip().lower()
        items = [p for p in items if needle in p.title.lower()]
    if limit is not None:
        items = items[:limit]
    return items


def fetch_detail(
    url: str,
    *,
    session: requests.Session | None = None,
    timeout: float | None = None,
) -> PositionDetail:
    """抓取并解析一个岗位详情页。

    若 ``url`` 指向外部招聘平台（如 ``app.mokahr.com``），不做任何请求与解析，
    直接返回一个 ``content_html`` 为空、``url`` 为该外链的 :class:`PositionDetail`，
    由调用方按"打开外链"处理。

    Args:
        url: 详情页地址（官网 ``url`` 或外部平台 ``url2``）。
        session: 可注入的 :class:`requests.Session`（测试用）。
        timeout: 请求超时（秒），缺省 :data:`~westlake_survival._net.DEFAULT_TIMEOUT`。

    Returns:
        :class:`PositionDetail`。

    Raises:
        ValueError: ``url`` 为空。
        WestlakeError: 网络层失败（超时/连接错误等）。
        ParseError: HTTP 4xx/5xx，或页面结构变化导致解析失败。
        OffCampusError: 被校外访问网关拦截（403 且命中阻断页特征）。
    """
    if not url or not url.strip():
        raise ValueError("url 不能为空")
    url = url.strip()
    if is_external_url(url):
        logger.debug("岗位详情指向外部招聘平台，直接返回外链：%s", url)
        return PositionDetail(title="", url=url)

    session = session if session is not None else http_session()
    try:
        response = session.get(
            url, timeout=timeout if timeout is not None else DEFAULT_TIMEOUT
        )
    except requests.Timeout as exc:
        raise WestlakeError(
            f"岗位详情请求超时（{timeout if timeout is not None else DEFAULT_TIMEOUT}s）"
        ) from exc
    except requests.RequestException as exc:
        raise WestlakeError(f"岗位详情请求失败：{exc}") from exc

    _check_response(response)
    raw = getattr(response, "content", None)
    if raw is None:  # 兜底：只有 text 的替身对象
        text = getattr(response, "text", "") or ""
    else:
        text = raw.decode("utf-8", errors="replace")
    return parse_detail(text, url)


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
    name="careers",
    help="人才招聘：岗位列表与详情。",
    invoke_without_command=True,
)
@click.option("--category", default=None, help="按岗位类别过滤（如 博士后 / 科研团队）。")
@click.option("--keyword", default=None, help="按岗位标题模糊匹配（大小写不敏感）。")
@click.option("--limit", type=int, default=20, show_default=True, help="最多显示条数。")
@click.pass_context
def cli_group(
    ctx: click.Context, category: str | None, keyword: str | None, limit: int
) -> None:
    """``westlake careers [--category C] [--keyword K] [--limit N]``。"""
    if ctx.invoked_subcommand is not None:  # 交给子命令（detail）
        return
    if limit < 0:
        raise click.UsageError(f"--limit 必须 >= 0，得到 {limit}")
    _run_positions(category=category, keyword=keyword, limit=limit)


@cli_group.command(name="detail")
@click.argument("url")
@_handle_errors
def careers_detail(url: str) -> None:
    """显示一个岗位详情页的标题、类别、部门、地点与正文纯文本。"""
    detail = fetch_detail(url)
    if detail.content_html:
        click.echo(f"标题：{detail.title or '—'}")
        click.echo(f"类别：{detail.category or '—'}")
        click.echo(f"部门：{detail.department or '—'}")
        click.echo(f"地点：{detail.address or '—'}")
        click.echo(f"性质：{detail.job_type or '—'}")
        click.echo("")
        text = _html_to_text(detail.content_html).strip()
        click.echo(text or "（正文为空）")
        return
    # 外部招聘平台：不做解析，直接给出外链
    click.echo(f"该岗位投递入口在外部招聘平台：{detail.url}")


@_handle_errors
def _run_positions(*, category: str | None, keyword: str | None, limit: int) -> None:
    """抓取岗位列表并打印表格（``_print_table`` 惰性导入以免循环依赖）。"""
    from westlake_survival.cli.main import _print_table

    items = positions(category=category, keyword=keyword, limit=limit)
    if not items:
        click.echo("未找到匹配的岗位。")
        return
    filters = []
    if category:
        filters.append(f"类别={category}")
    if keyword:
        filters.append(f"关键词={keyword}")
    prefix = "　".join(filters)
    click.echo(f"{prefix + '　' if prefix else ''}共 {len(items)} 条")
    rows = [
        (
            p.title or "—",
            p.category or "—",
            p.department or "—",
            p.location or "—",
            p.date.isoformat() if p.date else "—",
            p.apply_url or "—",
        )
        for p in items
    ]
    _print_table(rows, ("岗位", "类别", "部门", "地点", "日期", "投递链接"))


def _html_to_text(html: str) -> str:
    """把详情页富文本 HTML 粗略转成纯文本（去标签、压缩空白）。

    仅用于 CLI 展示；完整 HTML 仍保留在 :attr:`PositionDetail.content_html`。
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