"""西湖大学本科培养方案（官网公开版）客户端。

数据源是**本科招生网**（中文 ``zh-ugadmissions.westlake.edu.cn`` / 英文
``ugadmissions.westlake.edu.cn``，2026-10-23 实测校外可直连）的三张 TRS CMS
组件页，数据都以 ``new 组件名("#app", { ...JS 对象字面量... })`` 内嵌：

* 培养理念 ``/Academics/WestlakeEducation/``（组件 ``AcademicEducation``）：
  ``prepareFuture.content`` 是培养目标；``breadthAndFocus`` / ``challenge`` /
  ``leaders`` / ``individualization`` / ``leadersC`` / ``individualizationC`` /
  ``leadersSeven`` / ``individualizationCEight`` 八个键是培养特色。
  **陷阱**：这些特色条目的正文字段名是 ``contnet``——官网源码拼写错误，
  不是 ``content``，本模块两者都兜。
* 课程安排 ``/Academics/Curriculum/``（组件 ``AcademicCurriculum``）：
  ``prepare``（核心课程）、``SECore``（通识教育课程，带课程简表）、
  ``HASSCore``（通识教育核心课程，带课程列表）、``majors``（**科研训练课程**）、
  ``studyAbroad``（**专业课程**，正文含各专业选定时间规则）、
  ``research``（**海外学习**）。键名与语义大面积错位（``majors`` 键装的是
  科研训练），展示时以页面自带的 ``title`` 字段为准，勿按键名望文生义。
* 专业设置 ``/Academics/Majors/``（组件 ``AcademicMajors``）：
  ``majors.content`` 是纯文本的本科专业总览（8 个专业 + 选定时间规则）；
  ``courseArrangement.left.items`` 是 ``[{name: 理学|工学|医学, children:
  [{name: 专业名, value: 标识, content: [{title: '介绍', content: html}]}]}]``，
  每个专业带富文本介绍。该子树无 ``function`` 回调，可整块解析。

局限（如实声明）：公开网**没有**分专业的官方培养方案文档（修读学分、课程
清单等逐项要求），SIS 学生端 2026-09-23 全量摸底也未见该页；本模块交付的
是公开可得的培养理念、课程体系与专业介绍，逐门修读要求仍以教务发布为准。

编码坑位：与官网主站同款——响应头 ``Content-Type`` 无 charset，禁止直接读
``response.text``；一律取 ``response.content`` 手动 UTF-8 解码，并复用
:func:`_repair_mojibake` 兜底。列表类页面复用
:func:`~westlake_survival._cache.http_get_with_etag` 做本地缓存。

组件块里混有 ``mounted: function () {}`` 等回调，不能整块
:func:`~westlake_survival._trs.js_literal`；统一先用
:func:`~westlake_survival._trs.component_script` 截块，再按目标键
:func:`~westlake_survival._trs.object_of` 单独解析。
"""

from __future__ import annotations

import functools
import logging
import re
from dataclasses import dataclass, field

import click
import requests

from westlake_survival._cache import http_get_with_etag
from westlake_survival._net import DEFAULT_TIMEOUT, http_session
from westlake_survival._trs import component_script, object_of
from westlake_survival.exceptions import OffCampusError, ParseError, WestlakeError, is_offcampus

__all__ = [
    "SITES",
    "PAGE_PATHS",
    "EDUCATION_COMPONENT",
    "CURRICULUM_COMPONENT",
    "MAJORS_COMPONENT",
    "EDUCATION_FEATURE_KEYS",
    "CURRICULUM_SECTION_KEYS",
    "ProgramSection",
    "CurriculumTable",
    "CurriculumTableRow",
    "Curriculum",
    "Major",
    "MajorsCatalog",
    "ProgramOverview",
    "parse_overview",
    "parse_curriculum",
    "parse_majors",
    "overview",
    "curriculum",
    "majors",
    "cli_group",
]

logger = logging.getLogger(__name__)

#: 招生网各语言站点根地址（2026-10-23 实测两站同构、组件名一致）。
SITES = {
    "zh": "https://zh-ugadmissions.westlake.edu.cn",
    "en": "https://ugadmissions.westlake.edu.cn",
}

#: 三张源页路径（两语言一致；培养理念页中文落地是
#: ``/Academics/`` 302 到的 ``/Academics/WestlakeEducation/``）。
PAGE_PATHS = {
    "education": "/Academics/WestlakeEducation/",
    "curriculum": "/Academics/Curriculum/",
    "majors": "/Academics/Majors/",
}

#: 培养理念页组件名。
EDUCATION_COMPONENT = "AcademicEducation"

#: 课程安排页组件名。
CURRICULUM_COMPONENT = "AcademicCurriculum"

#: 专业设置页组件名。
MAJORS_COMPONENT = "AcademicMajors"

#: 培养理念页的特色条目键（官网展示顺序；正文字段名是拼错的 ``contnet``）。
EDUCATION_FEATURE_KEYS = (
    "breadthAndFocus",          # 一人一策培养
    "challenge",                # 国际一流师资
    "leaders",                  # 专业自主选择
    "individualization",        # 本博连读机会
    "leadersC",                 # 全员海外交流
    "individualizationC",       # 一流科研训练
    "leadersSeven",             # 一人多导支持
    "individualizationCEight",  # 书院文化浸润
)

#: 课程安排页的栏目键（官方展示顺序；键名与语义错位，见模块 docstring）。
CURRICULUM_SECTION_KEYS = (
    "prepare",      # 我们的核心课程
    "SECore",       # 通识教育课程（含课程简表）
    "HASSCore",     # 通识教育核心课程（含课程列表）
    "majors",       # 科研训练课程
    "studyAbroad",  # 专业课程（含专业选定时间规则）
    "research",     # 海外学习
)


# --------------------------------------------------------------------------- #
# 编码修复
# --------------------------------------------------------------------------- #
def _repair_mojibake(text: str) -> str:
    """修复"UTF-8 被当成 ISO-8859-1 解码"造成的乱码。

    与 :func:`westlake_survival.news._repair_mojibake` 同款：文本已是正确
    UTF-8 时 ``encode("latin-1")`` 会抛 :class:`UnicodeEncodeError`，原样返回，
    因此是安全的幂等修复。
    """
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def _html_to_text(html: str) -> str:
    """富文本 HTML 粗转纯文本（去标签、解实体、压缩空白），用于展示层。"""
    if not html:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
    text = text.replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'")
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


# --------------------------------------------------------------------------- #
# 数据模型
# --------------------------------------------------------------------------- #
@dataclass
class ProgramSection:
    """培养页里的一个栏目。

    :attr:`key` 是组件数据里的原始键名（如 ``studyAbroad``——实际语义是
    「专业课程」，键名与语义错位，见模块 docstring）；:attr:`title` 是页面
    自带的官方标题，展示一律用它。
    """

    key: str
    title: str
    content_html: str = ""
    table: "CurriculumTable | None" = None

    @property
    def content_text(self) -> str:
        """正文纯文本（HTML 去标签）。"""
        return _html_to_text(self.content_html)


@dataclass
class CurriculumTableRow:
    """课程简表的一行：分类名 + 课程名列表。"""

    name: str
    items: list[str] = field(default_factory=list)


@dataclass
class CurriculumTable:
    """栏目自带的结构化表格（通识课程简表等）。"""

    name: str = ""
    headers: list[str] = field(default_factory=list)
    rows: list[CurriculumTableRow] = field(default_factory=list)


@dataclass
class Curriculum:
    """课程安排页解析结果：课程体系各栏目（官方展示顺序）。"""

    sections: list[ProgramSection] = field(default_factory=list)
    url: str = ""
    lang: str = "zh"


@dataclass
class ProgramOverview:
    """培养理念页解析结果。

    :attr:`goal` 是培养目标（原始键 ``prepareFuture``），与特色条目同为
    :class:`ProgramSection`，展示统一走 ``content_text``。
    """

    goal: ProgramSection = field(
        default_factory=lambda: ProgramSection(key="prepareFuture", title="培养目标")
    )
    features: list[ProgramSection] = field(default_factory=list)
    url: str = ""
    lang: str = "zh"


@dataclass
class Major:
    """专业设置页里的一个本科专业。"""

    name: str
    group: str = ""
    value: int | None = None
    sections: list[ProgramSection] = field(default_factory=list)

    @property
    def intro_text(self) -> str:
        """介绍栏目纯文本（无栏目时为空串）。"""
        return self.sections[0].content_text if self.sections else ""


@dataclass
class MajorsCatalog:
    """专业设置页解析结果。"""

    summary: str = ""
    majors: list[Major] = field(default_factory=list)
    url: str = ""
    lang: str = "zh"


# --------------------------------------------------------------------------- #
# 解析
# --------------------------------------------------------------------------- #
def _extract_table(raw: dict) -> CurriculumTable | None:
    """从栏目数据里取 ``table`` 子对象；无表格返回 ``None``。"""
    table = raw.get("table")
    if not isinstance(table, dict):
        return None
    rows = []
    for entry in table.get("td") or []:
        if isinstance(entry, dict):
            rows.append(
                CurriculumTableRow(
                    name=str(entry.get("name") or ""),
                    items=[str(item) for item in entry.get("list") or []],
                )
            )
    return CurriculumTable(
        name=str(table.get("name") or ""),
        headers=[str(header) for header in table.get("th") or []],
        rows=rows,
    )


def _section_text(raw: dict) -> str:
    """取栏目正文，兼容官网把 ``content`` 拼成 ``contnet`` 的键。"""
    return str(raw.get("content") or raw.get("contnet") or "")


#: 简单模板字符串（不含 ``${}`` 插值）。英文招生网把 ``title`` 写成
#: ``title: \`Undergraduate Majors\``，而共享解析器 :func:`_trs.js_literal`
#: 按仓库既有约定不支持模板串（见 ``src/test/test_trs.py``），故在本模块
#: 就地把无插值的模板串转成普通单引号字符串再解析。
_TEMPLATE_LITERAL = re.compile(r"`([^`]*)`")


def _unwrap_template_literals(block: str) -> str:
    """把组件块里**无插值**的模板串就地转成单引号字符串字面量。

    含 ``${}`` 插值的模板串不在替换之列（留给解析器按既有行为报错，
    不静默吞掉插值语义）。
    """
    def _sub(match: re.Match[str]) -> str:
        inner = match.group(1)
        if "${" in inner:
            return match.group(0)
        if "'" in inner:
            return '"' + inner.replace('"', '\\"') + '"'
        return "'" + inner + "'"

    return _TEMPLATE_LITERAL.sub(_sub, block)


def _require_component(html: str, name: str, url: str) -> str:
    """截组件块；缺失即 :class:`ParseError`（页面结构可能已变化）。"""
    block = component_script(html, name)
    if not block:
        raise ParseError(f"页面中找不到组件 {name!r}，页面结构可能已变化：{url}")
    return _unwrap_template_literals(block)


def parse_overview(html: str, *, url: str = "", lang: str = "zh") -> ProgramOverview:
    """解析培养理念页 HTML。

    Raises:
        ParseError: 找不到 ``AcademicEducation`` 组件或培养目标键。
    """
    block = _require_component(html, EDUCATION_COMPONENT, url)
    goal_raw = object_of(block, "prepareFuture")
    goal = _section_text(goal_raw)
    if not goal:
        raise ParseError(f"培养理念页组件缺少培养目标正文（prepareFuture）：{url}")
    goal_section = ProgramSection(
        key="prepareFuture",
        title=str(goal_raw.get("title") or "培养目标"),
        content_html=goal,
    )
    features: list[ProgramSection] = []
    for key in EDUCATION_FEATURE_KEYS:
        try:
            raw = object_of(block, key)
        except ParseError:
            continue  # 官网增删特色条目时少一栏不应致命
        text = _section_text(raw)
        if not text:
            continue
        features.append(ProgramSection(key=key, title=str(raw.get("title") or key), content_html=text))
    return ProgramOverview(goal=goal_section, features=features, url=url, lang=lang)


def parse_curriculum(html: str, *, url: str = "", lang: str = "zh") -> Curriculum:
    """解析课程安排页 HTML。

    Raises:
        ParseError: 找不到 ``AcademicCurriculum`` 组件，或六个栏目一个都不在。
    """
    block = _require_component(html, CURRICULUM_COMPONENT, url)
    sections: list[ProgramSection] = []
    for key in CURRICULUM_SECTION_KEYS:
        try:
            raw = object_of(block, key)
        except ParseError:
            continue
        sections.append(
            ProgramSection(
                key=key,
                title=str(raw.get("title") or key),
                content_html=_section_text(raw),
                table=_extract_table(raw),
            )
        )
    if not sections:
        raise ParseError(f"课程安排页组件不含任何已知栏目键 {CURRICULUM_SECTION_KEYS}：{url}")
    return Curriculum(sections=sections, url=url, lang=lang)


def parse_majors(html: str, *, url: str = "", lang: str = "zh") -> MajorsCatalog:
    """解析专业设置页 HTML。

    Raises:
        ParseError: 找不到 ``AcademicMajors`` 组件或 ``courseArrangement`` 子树。
    """
    block = _require_component(html, MAJORS_COMPONENT, url)
    summary_raw = object_of(block, "majors")
    arrangement = object_of(block, "courseArrangement")
    left = arrangement.get("left")
    items = left.get("items") if isinstance(left, dict) else None
    if not isinstance(items, list):
        raise ParseError(f"专业设置页组件缺少 courseArrangement.left.items 数组：{url}")
    majors: list[Major] = []
    for group in items:
        if not isinstance(group, dict):
            continue
        group_name = str(group.get("name") or "")
        for child in group.get("children") or []:
            if not isinstance(child, dict):
                continue
            sections = [
                ProgramSection(key="", title=str(entry.get("title") or ""), content_html=str(entry.get("content") or ""))
                for entry in child.get("content") or []
                if isinstance(entry, dict)
            ]
            value = child.get("value")
            majors.append(
                Major(
                    name=str(child.get("name") or ""),
                    group=group_name,
                    value=value if isinstance(value, int) else None,
                    sections=sections,
                )
            )
    if not majors:
        raise ParseError(f"专业设置页组件未解析出任何专业条目：{url}")
    return MajorsCatalog(summary=_section_text(summary_raw), majors=majors, url=url, lang=lang)


# --------------------------------------------------------------------------- #
# 网络层
# --------------------------------------------------------------------------- #
def _page_url(page: str, lang: str) -> str:
    """拼源页地址，校验 ``lang`` 取值。"""
    if lang not in SITES:
        raise ValueError(f"lang 只支持 {tuple(SITES)}，收到 {lang!r}")
    if page not in PAGE_PATHS:
        raise ValueError(f"page 只支持 {tuple(PAGE_PATHS)}，收到 {page!r}")
    return SITES[lang] + PAGE_PATHS[page]


def _drop_etag_cache(cache_name: str) -> None:
    """删除本地 ETag 缓存条目，令下一次请求变为无条件 GET。"""
    try:
        from westlake_survival import _cache

        path = _cache.cache_path(cache_name)
        if path.exists():
            path.unlink()
    except OSError:  # 缓存删不掉不应阻断加载
        logger.debug("删除 ETag 缓存失败", exc_info=True)


def _fetch_page(
    page: str,
    *,
    lang: str = "zh",
    refresh: bool = False,
    timeout: float | None = None,
    session: requests.Session | None = None,
) -> str:
    """抓取一张源页 HTML（ETag 条件请求 + 本地缓存 + 乱码修复）。"""
    url = _page_url(page, lang)
    cache_name = f"program/{page}_{lang}.html"
    if refresh:
        _drop_etag_cache(cache_name)
    session = session if session is not None else http_session()
    try:
        body, _etag = http_get_with_etag(
            url,
            cache_name=cache_name,
            session=session,
            timeout=timeout if timeout is not None else DEFAULT_TIMEOUT,
        )
    except requests.HTTPError as exc:
        response = exc.response
        if response is not None and getattr(response, "status_code", 0) == 403 and is_offcampus(response):
            raise OffCampusError(f"招生网页面拒绝访问（403）：{url}") from exc
        status = getattr(response, "status_code", "?")
        raise ParseError(f"招生网页面返回 HTTP {status}：{url}") from exc
    except requests.Timeout as exc:
        raise WestlakeError(
            f"招生网页面请求超时（{timeout if timeout is not None else DEFAULT_TIMEOUT}s）：{url}"
        ) from exc
    except requests.RequestException as exc:
        raise WestlakeError(f"招生网页面请求失败：{exc}") from exc
    # http_get_with_etag 已做无 charset 场景的编码探测，这里再做一次乱码兜底。
    return _repair_mojibake(body)


# --------------------------------------------------------------------------- #
# 公开 API
# --------------------------------------------------------------------------- #
def overview(
    lang: str = "zh",
    *,
    session: requests.Session | None = None,
    refresh: bool = False,
    timeout: float | None = None,
) -> ProgramOverview:
    """抓取并解析培养理念页（培养目标 + 培养特色）。

    Args:
        lang: ``"zh"`` / ``"en"``，对应两个招生网站点。
        session: 可注入的 :class:`requests.Session`（测试用）。
        refresh: 为 ``True`` 时先清掉本地缓存再请求。
        timeout: 请求超时（秒），缺省 :data:`~westlake_survival._net.DEFAULT_TIMEOUT`。

    Raises:
        ValueError: ``lang`` 非法。
        WestlakeError: 网络层失败。
        ParseError: HTTP 4xx/5xx，或页面结构变化导致解析失败。
        OffCampusError: 被校外访问网关拦截。
    """
    url = _page_url("education", lang)
    return parse_overview(
        _fetch_page("education", lang=lang, refresh=refresh, timeout=timeout, session=session),
        url=url,
        lang=lang,
    )


def curriculum(
    lang: str = "zh",
    *,
    session: requests.Session | None = None,
    refresh: bool = False,
    timeout: float | None = None,
) -> Curriculum:
    """抓取并解析课程安排页（核心课程 / 通识课程表 / 专业课程等六栏目）。

    参数与异常同 :func:`overview`。
    """
    url = _page_url("curriculum", lang)
    return parse_curriculum(
        _fetch_page("curriculum", lang=lang, refresh=refresh, timeout=timeout, session=session),
        url=url,
        lang=lang,
    )


def majors(
    lang: str = "zh",
    *,
    session: requests.Session | None = None,
    refresh: bool = False,
    timeout: float | None = None,
) -> MajorsCatalog:
    """抓取并解析专业设置页（8 个本科专业总览 + 分专业介绍）。

    参数与异常同 :func:`overview`。
    """
    url = _page_url("majors", lang)
    return parse_majors(
        _fetch_page("majors", lang=lang, refresh=refresh, timeout=timeout, session=session),
        url=url,
        lang=lang,
    )


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


def _lang_option(default: str | None = "zh"):
    """``--lang zh|en`` 选项；组级默认 ``zh``，子命令级默认 ``None`` 以便回退。"""

    def _apply(func):
        return click.option(
            "--lang",
            default=default,
            show_default=default is not None,
            type=click.Choice(tuple(SITES)),
            help="站点语言。",
        )(func)

    return _apply


def _refresh_option(func):
    """``--refresh`` 选项：跳过本地缓存强制重抓。"""
    return click.option("--refresh", is_flag=True, help="忽略本地缓存，强制重新抓取。")(func)


@click.group(
    name="program",
    help="本科培养方案（官网公开版）：培养理念 / 课程体系 / 专业设置。",
)
@_lang_option("zh")
@_refresh_option
@click.pass_context
def cli_group(ctx: click.Context, lang: str, refresh: bool) -> None:
    """``westlake program [--lang zh|en] [--refresh] [overview|curriculum|majors]``。

    ``--lang`` / ``--refresh`` 放在子命令前作用于整组，放在子命令后只作用于
    该条命令；两级都定义是为了 ``westlake program overview --refresh`` 这类
    自然写法。
    """
    ctx.ensure_object(dict)
    ctx.obj["lang"] = lang
    ctx.obj["refresh"] = refresh


def _effective(ctx: click.Context, lang: str | None, refresh: bool) -> tuple[str, bool]:
    """合并组级与子命令级的 ``--lang`` / ``--refresh``（子命令优先）。"""
    return lang or ctx.obj["lang"], refresh or ctx.obj["refresh"]


@cli_group.command(name="overview")
@_lang_option(None)
@_refresh_option
@_handle_errors
@click.pass_context
def overview_cmd(ctx: click.Context, lang: str | None, refresh: bool) -> None:
    """培养理念：培养目标与八项培养特色。"""
    effective_lang, effective_refresh = _effective(ctx, lang, refresh)
    data = overview(effective_lang, refresh=effective_refresh)
    click.echo(f"培养目标：{data.goal.content_text or '—'}")
    if not data.features:
        click.echo("培养特色：—")
        return
    click.echo("培养特色：")
    for index, feature in enumerate(data.features, 1):
        click.echo(f"  {index}. 【{feature.title}】{feature.content_text}")


@cli_group.command(name="curriculum")
@_lang_option(None)
@_refresh_option
@_handle_errors
@click.pass_context
def curriculum_cmd(ctx: click.Context, lang: str | None, refresh: bool) -> None:
    """课程体系：核心课程 / 通识课程表 / 专业课程等六栏目。"""
    effective_lang, effective_refresh = _effective(ctx, lang, refresh)
    data = curriculum(effective_lang, refresh=effective_refresh)
    for index, section in enumerate(data.sections):
        if index:
            click.echo("")
        click.echo(f"== {section.title} ==")
        text = section.content_text
        if text:
            click.echo(text)
        if section.table is not None:
            if section.table.name:
                click.echo(f"[{section.table.name}]")
            for row in section.table.rows:
                click.echo(f"  {row.name}：{'；'.join(row.items)}")


@cli_group.command(name="majors")
@click.argument("name", required=False)
@_lang_option(None)
@_refresh_option
@_handle_errors
@click.pass_context
def majors_cmd(ctx: click.Context, name: str | None, lang: str | None, refresh: bool) -> None:
    """专业设置：本科专业总览与分专业介绍；NAME 按专业名子串过滤。"""
    effective_lang, effective_refresh = _effective(ctx, lang, refresh)
    data = majors(effective_lang, refresh=effective_refresh)
    if data.summary:
        click.echo(f"总览：{data.summary}")
        click.echo("")
    found = [m for m in data.majors if not name or name in m.name]
    if name and not found:
        click.secho(f"未找到名称含 {name!r} 的专业。可选：{'、'.join(m.name for m in data.majors)}", fg="yellow", err=True)
        raise SystemExit(1)
    for index, major in enumerate(found):
        if index:
            click.echo("")
        group = f"（{major.group}）" if major.group else ""
        click.echo(f"== {major.name}{group} ==")
        for section in major.sections:
            title = section.title or "介绍"
            text = section.content_text
            if text:
                click.echo(f"[{title}] {text}")
            else:
                click.echo(f"[{title}] —")
