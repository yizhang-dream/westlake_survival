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

更正（2026-10-23 二次侦察）：本模块首版误判「公开网没有分专业培养方案」。
培养方案确实公开——在主站专业详情页，见下文「真正的培养方案」一节。
招生网那三页只是培养理念、通识课程体系与专业简介，不含学分要求。

编码坑位：与官网主站同款——响应头 ``Content-Type`` 无 charset，禁止直接读
``response.text``；一律取 ``response.content`` 手动 UTF-8 解码，并复用
:func:`_repair_mojibake` 兜底。列表类页面复用
:func:`~westlake_survival._cache.http_get_with_etag` 做本地缓存。

组件块里混有 ``mounted: function () {}`` 等回调，不能整块
:func:`~westlake_survival._trs.js_literal`；统一先用
:func:`~westlake_survival._trs.component_script` 截块，再按目标键
:func:`~westlake_survival._trs.object_of` 单独解析。

真正的**培养方案（学分要求 + 课程表）在主站**，不在招生网
==========================================================
主站 ``https://www.westlake.edu.cn/academics/undergraduate_studies/<专业>/``
（组件 ``undergraduateStudiesDetails``，2026-10-23 实测）才是培养方案本体：
组件里的 ``navList`` 是**全部 8 个专业**的数组，每项含
``{text, imgUrl, briefIntroduction, requirements, warnText}``：

* ``briefIntroduction``：``[{subTitle, content}]``，通常是「<专业名>」总述 +
  「专业核心课程」两句；
* ``requirements``：按学分块列出，``{title, content, url, tab, credits,
  headerInfo, tableData}``——四个通识块给 ``credits``（如 ``34`` / ``20-28``）
  并指向通识课程页；专业块给 ``tableData`` 课程表；
* ``tableData`` 有两种形态：扁平 ``{name, value(学分), detailInfo}`` 与分组
  ``{field(方向名), course:[...]}``；``detailInfo`` 是 ``[{label, val}]`` 或
  ``[{label, vals:[]}]``，承载「先修课程 / 授课教师 / 课程简介」。

**要点**：任一专业页都含全部 8 个专业的数据，因此一次抓取即可覆盖全体；
但为语义忠实，取某专业时仍抓该专业自己的 URL。**临床医学的专业课程表
是空的**（只有四个通识学分块有数据），这是官网现状，不是解析失败——模块
用 ``has_courses`` 如实暴露。英文主站该路径 500（2026-10-23 实测），
培养方案只有中文版。
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
from westlake_survival._trs import balanced, component_script, js_literal, object_of
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
    "MAIN_SITE",
    "MAJOR_PLAN_PATH",
    "MAJOR_PLAN_COMPONENT",
    "MAJOR_SLUGS",
    "CourseEntry",
    "CommonCourse",
    "CourseTeacher",
    "COMMON_COURSES_PATH",
    "COMMON_COURSE_KEYS",
    "parse_common_courses",
    "common_courses",
    "course_search",
    "CreditRequirement",
    "MajorPlan",
    "PlansCatalog",
    "parse_major_plans",
    "parse_overview",
    "parse_curriculum",
    "parse_majors",
    "overview",
    "curriculum",
    "majors",
    "major_plans",
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

#: 主站（培养方案本体所在，仅中文站）。
MAIN_SITE = "https://www.westlake.edu.cn"

#: 专业培养方案页路径模板（``{slug}`` 由 :data:`MAJOR_SLUGS` 给出）。
MAJOR_PLAN_PATH = "/academics/undergraduate_studies/{slug}/"

#: 专业培养方案页组件名。
MAJOR_PLAN_COMPONENT = "undergraduateStudiesDetails"

#: 通识课程目录页（主站，含全部通识课程与授课教师链接）。
COMMON_COURSES_PATH = "/academics/undergraduate_studies/common_courses/"

#: 通识课程页组件名。
COMMON_COURSES_COMPONENT = "commonSources"

#: 通识课程页的三个课程块键 → 官方类别名（思政类该页不发布）。
COMMON_COURSE_KEYS = {
    "STEMCoursesObj": "理工基础类",
    "HASSCoursesObj": "人文社科艺术类",
    "PECoursesObj": "基础素质类",
}

#: 8 个本科专业的中文名 → 官网 URL slug（2026-10-23 实测，与招生网专业设置页同集合）。
MAJOR_SLUGS = {
    "数学与应用数学": "mathematics_and_applied_mathematics",
    "物理学": "physics",
    "化学": "chemistry",
    "材料科学与工程": "materials_science_and_engineering",
    "电子信息工程": "electronic_and_information_engineering",
    "人工智能": "artificial_intelligence",
    "生物科学": "biological_sciences",
    "临床医学": "clinical_medicine",
}


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


@dataclass
class CourseEntry:
    """培养方案课程表里的一门课。

    :attr:`credits` 是官网 ``value`` 字段（可能是 ``3`` 或 ``31.5``）；
    :attr:`group` 来自分组形态的 ``field``（方向名，如「物理进阶」）。
    """

    name: str
    credits: float | None = None
    group: str = ""
    prerequisite: str = ""
    description_html: str = ""
    teachers: list[str] = field(default_factory=list)

    @property
    def description_text(self) -> str:
        """课程简介纯文本。"""
        return _html_to_text(self.description_html)


@dataclass
class CreditRequirement:
    """一个学分块（如「专业必修课程 24 学分」）。

    ``credits`` 保留官网原样字符串（``"24"`` / ``"20-28"`` / ``"31.5"``），
    因为通识块是区间而非单值，强行转数字会丢信息。
    """

    title: str
    credits: str = ""
    note: str = ""
    url: str = ""
    courses: list[CourseEntry] = field(default_factory=list)

    @property
    def has_courses(self) -> bool:
        """该块是否带课程表（通识块与临床医学专业块为空）。"""
        return bool(self.courses)


@dataclass
class MajorPlan:
    """一个本科专业的培养方案。"""

    name: str
    image_url: str = ""
    intro: list[ProgramSection] = field(default_factory=list)
    requirements: list[CreditRequirement] = field(default_factory=list)
    warn_text: str = ""
    url: str = ""

    @property
    def total_credits(self) -> float | None:
        """学分合计；含区间（如 ``20-28``）或非常规值时返回 ``None``。"""
        total = 0.0
        for requirement in self.requirements:
            raw = (requirement.credits or "").strip()
            if not raw:
                continue
            try:
                total += float(raw)
            except ValueError:
                return None
        return total if self.requirements else None

    @property
    def course_count(self) -> int:
        """全部课程表条目数（不区分必修/选修）。"""
        return sum(len(requirement.courses) for requirement in self.requirements)


@dataclass
class PlansCatalog:
    """培养方案集合（任一专业页都含全部 8 个专业）。"""

    majors: list[MajorPlan] = field(default_factory=list)
    url: str = ""

    def find(self, name: str) -> MajorPlan | None:
        """按中文名精确查找；找不到返回 ``None``。"""
        for major in self.majors:
            if major.name == name:
                return major
        return None

    def match(self, keyword: str) -> list[MajorPlan]:
        """按子串匹配（用于 CLI 模糊查询）。"""
        return [major for major in self.majors if keyword in major.name]


@dataclass
class CourseTeacher:
    """通识课程条目里的授课教师（官网带个人主页链接，可能为空）。"""

    name: str
    url: str = ""


@dataclass
class CommonCourse:
    """通识课程目录里的一门课。

    :attr:`category` 是三大类之一（见 :data:`COMMON_COURSE_KEYS`），
    :attr:`subject` 是学科（数学/物理/体育/艺术……）。学分与开课学期保留
    官网原文字符串（如 ``"7"`` / ``"春、秋季"``），不做数值化。
    """

    title: str
    category: str = ""
    subject: str = ""
    credits: str = ""
    semester: str = ""
    prerequisite: str = ""
    teachers: list[CourseTeacher] = field(default_factory=list)
    description_html: str = ""

    @property
    def description_text(self) -> str:
        """课程简介纯文本。"""
        return _html_to_text(self.description_html)


@dataclass
class CommonCourses:
    """通识课程目录（三类合计，2026-10-23 实测 99 门）。"""

    courses: list[CommonCourse] = field(default_factory=list)
    notices: dict[str, str] = field(default_factory=dict)
    url: str = ""

    def categories(self) -> list[str]:
        """出现过的类别（保持官网顺序）。"""
        seen: list[str] = []
        for course in self.courses:
            if course.category and course.category not in seen:
                seen.append(course.category)
        return seen


@dataclass
class CourseHit:
    """跨源课程搜索的一条结果。

    :attr:`source` 形如 ``通识·数学`` 或 ``人工智能·专业必修课程``，
    用来区分同一门课在不同处的归属。
    """

    title: str
    credits: str = ""
    source: str = ""
    prerequisite: str = ""
    description_html: str = ""

    @property
    def description_text(self) -> str:
        """课程简介纯文本。"""
        return _html_to_text(self.description_html)


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


def _credits_value(raw: object) -> float | None:
    """把课程 ``value`` 转学分；非数字（如分组占位）返回 ``None``。"""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _parse_course(raw: dict, group: str = "") -> CourseEntry:
    """解析课程表的一行（扁平或分组内条目）。"""
    prerequisite = ""
    description = ""
    teachers: list[str] = []
    for detail in raw.get("detailInfo") or []:
        if not isinstance(detail, dict):
            continue
        label = str(detail.get("label") or "")
        if label == "先修课程":
            prerequisite = str(detail.get("val") or "").strip()
        elif label == "课程简介":
            description = str(detail.get("val") or "")
        elif label == "授课教师":
            values = detail.get("vals")
            if isinstance(values, list):
                teachers = [str(value) for value in values if str(value).strip()]
    return CourseEntry(
        name=str(raw.get("name") or ""),
        credits=_credits_value(raw.get("value")),
        group=group,
        prerequisite=prerequisite,
        description_html=description,
        teachers=teachers,
    )


def _parse_requirement(raw: dict) -> CreditRequirement:
    """解析一个学分块，兼容扁平与分组两种课程表形态。"""
    courses: list[CourseEntry] = []
    for item in raw.get("tableData") or []:
        if not isinstance(item, dict):
            continue
        nested = item.get("course")
        if isinstance(nested, list):  # 分组形态 {field, course:[...]}
            group = str(item.get("field") or "")
            for child in nested:
                if isinstance(child, dict):
                    courses.append(_parse_course(child, group=group))
        elif item.get("name"):
            courses.append(_parse_course(item))
    return CreditRequirement(
        title=str(raw.get("title") or "专业课程"),
        credits=str(raw.get("credits") if raw.get("credits") is not None else ""),
        note=str(raw.get("content") or ""),
        url=str(raw.get("url") or ""),
        courses=courses,
    )


def _parse_major_plan(raw: dict, url: str = "") -> MajorPlan:
    """解析 ``navList`` 的一项（一个专业）。"""
    intro = [
        ProgramSection(key="", title=str(entry.get("subTitle") or ""), content_html=str(entry.get("content") or ""))
        for entry in raw.get("briefIntroduction") or []
        if isinstance(entry, dict)
    ]
    requirements = [
        _parse_requirement(entry) for entry in raw.get("requirements") or [] if isinstance(entry, dict)
    ]
    return MajorPlan(
        name=str(raw.get("text") or ""),
        image_url=str(raw.get("imgUrl") or ""),
        intro=intro,
        requirements=requirements,
        warn_text=str(raw.get("warnText") or ""),
        url=url,
    )


def parse_major_plans(html: str, *, url: str = "") -> PlansCatalog:
    """解析主站专业培养方案页 HTML。

    ``navList`` 是全部 8 个专业的数组（任一专业页都有全量数据）。

    Raises:
        ParseError: 找不到组件或 ``navList`` 数组。
    """
    block = _require_component(html, MAJOR_PLAN_COMPONENT, url)
    match = re.search(r"\bnavList\s*:\s*\[", block)
    if not match:
        raise ParseError(f"培养方案页缺少 navList 数组：{url}")
    raw_list = js_literal(balanced(block, match.end() - 1))
    if not isinstance(raw_list, list):
        raise ParseError(f"培养方案页 navList 不是数组：{url}")
    majors = [_parse_major_plan(item, url=url) for item in raw_list if isinstance(item, dict) and item.get("text")]
    if not majors:
        raise ParseError(f"培养方案页未解析出任何专业：{url}")
    return PlansCatalog(majors=majors, url=url)


def _parse_teachers(raw: object) -> list[CourseTeacher]:
    """解析 ``detailInfo`` 里的 ``授课教师`` 值（``[{val, url}]``）。"""
    teachers: list[CourseTeacher] = []
    for entry in raw or []:
        if isinstance(entry, dict):
            name = str(entry.get("val") or "").strip()
            if name:
                teachers.append(CourseTeacher(name=name, url=str(entry.get("url") or "")))
        elif isinstance(entry, str) and entry.strip():
            teachers.append(CourseTeacher(name=entry.strip()))
    return teachers


def parse_common_courses(html: str, *, url: str = "") -> CommonCourses:
    """解析通识课程目录页 HTML。

    Raises:
        ParseError: 找不到组件，或三个课程块一个都不在。
    """
    block = _require_component(html, COMMON_COURSES_COMPONENT, url)
    courses: list[CommonCourse] = []
    notices: dict[str, str] = {}
    found = False
    for key, category in COMMON_COURSE_KEYS.items():
        match = re.search(r"\b" + key + r"\s*:\s*\{", block)
        if not match:
            continue
        raw = js_literal(balanced(block, match.end() - 1))
        if not isinstance(raw, dict):
            continue
        found = True
        official = str(raw.get("title") or category)
        notice = str(raw.get("notice") or "").strip()
        if notice:
            notices[official] = notice
        tables = raw.get("tableDatas") or {}
        groups = tables.get("lists") if isinstance(tables, dict) else None
        for group in groups or []:
            if not isinstance(group, dict):
                continue
            subject = str(group.get("subject") or "")
            for item in group.get("items") or []:
                if not isinstance(item, dict):
                    continue
                prerequisite = ""
                teachers: list[CourseTeacher] = []
                description = ""
                for detail in item.get("detailInfo") or []:
                    if not isinstance(detail, dict):
                        continue
                    label = str(detail.get("label") or "")
                    if label == "先修课程":
                        raw_pre = str(detail.get("val") or "").strip()
                        prerequisite = "" if raw_pre == "/" else raw_pre
                    elif label == "授课教师":
                        teachers = _parse_teachers(detail.get("vals"))
                    elif label == "课程简介":
                        description = str(detail.get("val") or "")
                courses.append(
                    CommonCourse(
                        title=str(item.get("courseTitle") or ""),
                        category=official,
                        subject=subject,
                        credits=str(item.get("credit") or ""),
                        semester=str(item.get("recommendedSemester") or ""),
                        prerequisite=prerequisite,
                        teachers=teachers,
                        description_html=description,
                    )
                )
    if not found or not courses:
        raise ParseError(f"通识课程页未解析出任何课程：{url}")
    return CommonCourses(courses=courses, notices=notices, url=url)


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


def major_plans(
    major: str | None = None,
    *,
    session: requests.Session | None = None,
    refresh: bool = False,
    timeout: float | None = None,
) -> PlansCatalog:
    """抓取并解析主站专业培养方案（学分要求 + 课程表 + 先修课程 + 课程简介）。

    任一专业页都含全部 8 个专业的数据；指定 ``major`` 时抓该专业自己的 URL
    （语义忠实），未知名称回退到 ``人工智能`` 页并给出全量结果。

    Args:
        major: 专业中文名（见 :data:`MAJOR_SLUGS`）；``None`` 表示不指定。
        session: 可注入的 :class:`requests.Session`（测试用）。
        refresh: 为 ``True`` 时先清掉本地缓存再请求。
        timeout: 请求超时（秒），缺省 :data:`~westlake_survival._net.DEFAULT_TIMEOUT`。

    Returns:
        :class:`PlansCatalog`（``majors`` 含全部 8 个专业）。

    Raises:
        WestlakeError: 网络层失败。
        ParseError: HTTP 4xx/5xx，或页面结构变化导致解析失败。
        OffCampusError: 被校外访问网关拦截。
    """
    slug = MAJOR_SLUGS.get(major or "", MAJOR_SLUGS["人工智能"])
    url = MAIN_SITE + MAJOR_PLAN_PATH.format(slug=slug)
    cache_name = f"program/plan_{slug}.html"
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
            raise OffCampusError(f"主站培养方案页拒绝访问（403）：{url}") from exc
        status = getattr(response, "status_code", "?")
        raise ParseError(f"主站培养方案页返回 HTTP {status}：{url}") from exc
    except requests.Timeout as exc:
        raise WestlakeError(
            f"主站培养方案页请求超时（{timeout if timeout is not None else DEFAULT_TIMEOUT}s）：{url}"
        ) from exc
    except requests.RequestException as exc:
        raise WestlakeError(f"主站培养方案页请求失败：{exc}") from exc
    return parse_major_plans(_repair_mojibake(body), url=url)


def common_courses(
    category: str | None = None,
    keyword: str | None = None,
    *,
    session: requests.Session | None = None,
    refresh: bool = False,
    timeout: float | None = None,
) -> CommonCourses:
    """抓取并解析通识课程目录（三类合计，含学分、开课学期、先修、教师、简介）。

    Args:
        category: 类别名或其中任意片段（如 ``"理工"`` / ``"人文"`` / ``"素质"``）。
        keyword: 课程名/学科/简介里的子串过滤（大小写不敏感）。
        session: 可注入的 :class:`requests.Session`（测试用）。
        refresh: 为 ``True`` 时先清掉本地缓存再请求。
        timeout: 请求超时（秒）。

    Raises:
        WestlakeError: 网络层失败。
        ParseError: HTTP 4xx/5xx，或页面结构变化导致解析失败。
        OffCampusError: 被校外访问网关拦截。
    """
    url = MAIN_SITE + COMMON_COURSES_PATH
    cache_name = "program/common_courses.html"
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
            raise OffCampusError(f"通识课程页拒绝访问（403）：{url}") from exc
        status = getattr(response, "status_code", "?")
        raise ParseError(f"通识课程页返回 HTTP {status}：{url}") from exc
    except requests.Timeout as exc:
        raise WestlakeError(
            f"通识课程页请求超时（{timeout if timeout is not None else DEFAULT_TIMEOUT}s）：{url}"
        ) from exc
    except requests.RequestException as exc:
        raise WestlakeError(f"通识课程页请求失败：{exc}") from exc
    catalog = parse_common_courses(_repair_mojibake(body), url=url)
    courses = catalog.courses
    if category:
        courses = [course for course in courses if category in course.category]
    if keyword:
        needle = keyword.casefold()
        courses = [
            course
            for course in courses
            if needle in course.title.casefold()
            or needle in course.subject.casefold()
            or needle in course.description_text.casefold()
        ]
    return CommonCourses(courses=courses, notices=catalog.notices, url=catalog.url)


def course_search(
    keyword: str,
    *,
    include_major_plans: bool = True,
    session: requests.Session | None = None,
    refresh: bool = False,
) -> list[CourseHit]:
    """跨源课程搜索：通识目录 + 8 个专业的培养方案课程表。

    通识课与专业课重名（如「机器学习」只在专业必修里）时两条都会命中，
    :attr:`CourseHit.source` 说明归属。网络异常按源降级：任一源失败不影响
    另一源的结果。

    Args:
        keyword: 课程名子串（大小写不敏感）。
        include_major_plans: 是否并入专业培养方案的课程表。
        session: 可注入的 :class:`requests.Session`（测试用）。
        refresh: 为 ``True`` 时先清掉本地缓存。

    Raises:
        ValueError: ``keyword`` 为空。
        WestlakeError: 两个源都失败时抛最后一个异常。
    """
    needle = (keyword or "").strip().casefold()
    if not needle:
        raise ValueError("keyword 不能为空")
    hits: list[CourseHit] = []
    errors: list[Exception] = []
    try:
        catalog = common_courses(session=session, refresh=refresh)
    except WestlakeError as exc:
        errors.append(exc)
    else:
        for course in catalog.courses:
            if needle in course.title.casefold():
                hits.append(
                    CourseHit(
                        title=course.title,
                        credits=course.credits,
                        source=f"通识·{course.subject or course.category}",
                        prerequisite=course.prerequisite,
                        description_html=course.description_html,
                    )
                )
    if include_major_plans:
        try:
            plans = major_plans(session=session, refresh=refresh)
        except WestlakeError as exc:
            errors.append(exc)
        else:
            for plan in plans.majors:
                for requirement in plan.requirements:
                    for course in requirement.courses:
                        if needle in course.name.casefold():
                            hits.append(
                                CourseHit(
                                    title=course.name,
                                    credits=_fmt_credits(course.credits),
                                    source=f"{plan.name}·{requirement.title}",
                                    prerequisite=course.prerequisite,
                                    description_html=course.description_html,
                                )
                            )
    if not hits and errors:
        raise errors[-1]
    hits.sort(key=lambda hit: (hit.title, hit.source))
    return hits


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


def _fmt_credits(value: float | None) -> str:
    """学分展示：整数值去掉 ``.0``，缺失显示 ``—``。"""
    if value is None:
        return "—"
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


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


@cli_group.command(name="plan")
@click.argument("name", required=False)
@_refresh_option
@click.option("--detail", is_flag=True, help="同时打印每门课的课程简介。")
@_handle_errors
@click.pass_context
def plan_cmd(ctx: click.Context, name: str | None, refresh: bool, detail: bool) -> None:
    """专业培养方案：学分要求 + 课程表（含先修课程）；NAME 按专业名子串过滤。

    数据源是主站专业详情页（每个专业页都含全部 8 个专业的培养方案）；只有
    中文版。临床医学的专业课程表官网为空，此时只列通识学分块。
    """
    _, effective_refresh = _effective(ctx, None, refresh)
    catalog = major_plans(name, refresh=effective_refresh)
    targets = catalog.match(name) if name else catalog.majors
    if not targets:
        available = "、".join(major.name for major in catalog.majors)
        click.secho(f"未找到名称含 {name!r} 的专业。可选：{available}", fg="yellow", err=True)
        raise SystemExit(1)
    for index, plan in enumerate(targets):
        if index:
            click.echo("")
        total = plan.total_credits
        head = f"== {plan.name} 培养方案 =="
        summary = []
        if total is not None:
            summary.append(f"学分合计 {_fmt_credits(total)}")
        else:
            summary.append("学分合计见分项（含区间）")
        summary.append(f"课程 {plan.course_count} 门")
        click.echo(head + "  " + "　".join(summary))
        for section in plan.intro:
            text = section.content_text
            if text:
                click.echo(f"[{section.title or '介绍'}] {text}")
        click.echo("")
        for requirement in plan.requirements:
            count = f"，{len(requirement.courses)} 门" if requirement.courses else ""
            click.echo(f"-- {requirement.title}：{requirement.credits or '—'} 学分{count}")
            if requirement.note and not requirement.courses:
                click.echo(f"   {requirement.note}")
            for course in requirement.courses:
                group = f"[{course.group}] " if course.group else ""
                line = f"   {group}{course.name}  {_fmt_credits(course.credits)} 学分"
                if course.prerequisite:
                    line += f"　先修：{course.prerequisite}"
                click.echo(line)
                if detail and course.description_text:
                    click.echo(f"      {course.description_text}")
        if plan.warn_text:
            click.echo(f"\n{plan.warn_text}")
    click.echo(f"\n来源：{catalog.url}（主站公开页，中文）")


@cli_group.command(name="courses")
@click.option("--category", default=None, help="类别片段：理工 / 人文 / 素质。")
@click.option("-k", "--keyword", default=None, help="课程名、学科或简介里的关键词。")
@click.option("--detail", is_flag=True, help="打印课程简介与授课教师。")
@_refresh_option
@_handle_errors
@click.pass_context
def courses_cmd(ctx: click.Context, category: str | None, keyword: str | None, detail: bool, refresh: bool) -> None:
    """通识课程目录：三类通识课的名称、学分、开课学期、先修与教师。"""
    _, effective_refresh = _effective(ctx, None, refresh)
    catalog = common_courses(category=category, keyword=keyword, refresh=effective_refresh)
    if not catalog.courses:
        click.echo("未找到符合条件的通识课程。")
        return
    grouped: dict[str, list[CommonCourse]] = {}
    for course in catalog.courses:
        grouped.setdefault(course.category, []).append(course)
    for name, rows in grouped.items():
        click.echo(f"== {name}（{len(rows)} 门）==")
        for course in rows:
            line = f"  [{course.subject or '—'}] {course.title}　{course.credits or '—'} 学分　{course.semester or '—'}"
            if course.prerequisite:
                line += f"　先修：{course.prerequisite}"
            click.echo(line)
            if detail:
                if course.teachers:
                    click.echo("      教师：" + "、".join(teacher.name for teacher in course.teachers))
                text = course.description_text
                if text:
                    click.echo(f"      {text}")
        notice = catalog.notices.get(name)
        if notice:
            click.echo(f"  注：{notice}")
        click.echo("")
    click.echo(f"合计 {len(catalog.courses)} 门；来源：{catalog.url}")


@cli_group.command(name="course")
@click.argument("keyword")
@click.option("--no-plans", is_flag=True, help="只搜通识目录，不并入专业培养方案课程表。")
@_refresh_option
@_handle_errors
@click.pass_context
def course_cmd(ctx: click.Context, keyword: str, no_plans: bool, refresh: bool) -> None:
    """跨源课程搜索：同一门课在通识目录与各专业培养方案里的归属。"""
    _, effective_refresh = _effective(ctx, None, refresh)
    hits = course_search(keyword, include_major_plans=not no_plans, refresh=effective_refresh)
    if not hits:
        click.echo(f"未找到名称含 {keyword!r} 的课程。")
        return
    click.echo(f"命中 {len(hits)} 条（{keyword}）：")
    for hit in hits:
        line = f"  {hit.title}　{hit.credits or '—'} 学分　[{hit.source}]"
        if hit.prerequisite:
            line += f"　先修：{hit.prerequisite}"
        click.echo(line)


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
