"""官网「导师团队 / 教师」模块：教师名录与教师主页详情。

本模块**聚合四个公开数据源**，得到尽量完整的教师全集（2026-09-24 实测约
335 人）。注意官网 ``/about/faculty/`` 的 ``memberList`` 只是「导师团队」名录
（约 302 人），**并非全校教师全集**：理学院、生命科学学院各自的站点与通识课
授课教师页另有收录。:func:`members` 默认聚合全部四源并按 ``url`` 去重（主站
优先保留），任一子源失败只降级跳过、不影响其余源。

数据源
======
1. 主站「导师团队」名录（``source="main"``，约 302 人）::

       GET https://www.westlake.edu.cn/about/faculty/

   注意：``https://www.westlake.edu.cn/about/`` 这个目录本身返回 403，必须带上
   完整子路径 ``/about/faculty/`` 才正常。

   该页是 Vue 单页应用，真实数据内嵌在 ``<script>`` 里的
   ``new faculty("#app", { ... })`` 调用中（2026-09-22 实测）：

   * ``memberList``：教师数组（约 302 人），每个条目形如::

         {imgUrl: "./science/202606/W020260611362809332339.jpg",
          name: "李奕璠博士", nameEn: "Yifan Li, Ph.D.",
          school: "理学院",
          subject: "物理学</br>冷原子量子调控实验室",
          url: "https://www.westlake.edu.cn/faculty/yifan-li.html",
          target: "_blank", show: true}

     ``subject`` 用 ``</br>`` / ``<br>`` 把「首学科」与「实验室/方向」拼在一起，
     拆开分别落到 :attr:`FacultyMember.subject` 与 :attr:`FacultyMember.lab`；
     条目里偶见首段为空（``"</br>早期宇宙实验室"``，即只写了实验室）。
   * ``schoolOPtions`` / ``subjectOptions``：筛选枚举值，供 :func:`school_options`
     与 :func:`subject_options` 读出校验。
   * ``storyList``：人才引进新闻（本模块不处理）。

2. 理学院教师列表（``source="science"``，125 条，按 url 去重后净增约 10 人）::

       POST https://science.westlake.edu.cn/chemistry_api/biz/modularity/project247/outLxyTutorList

   JSON 请求体**必须精确**为
   ``{"language": "Chinese", "pageNo": 1, "pageSize": 500, "kexi": null,
   "workType": null}``：``kexi`` / ``workType`` 传空串会报「科系参数不合法」，
   缺 ``pageNo`` 会报「pageNo 不能为null」。响应 ``data.outputData`` 为数组，
   条目字段实测（2026-09-24）：

   * ``fullName``：姓名（无「博士」后缀，如 ``"曹趣"``）；
   * ``chinesePinyin``：拼音（**不是**英文名，故不填 ``name_en``）；
   * ``kexi``：科系代码，映射见 :data:`SCIENCE_KEXI`
     （``"1"`` 化学系 / ``"2"`` 物理系 / ``"3"`` 天文系 / ``"4"`` 数学系 /
     ``"5"`` 交叉学科），落到 ``subject``；
   * ``remark``：实验室 / 方向，落到 ``lab``；
   * ``workType``：聘用类型，映射见 :data:`SCIENCE_WORK_TYPES`
     （``"1"`` 主聘 / ``"2"`` 兼聘 / ``"3"`` 教学 / ``"4"`` 访问），落到
     ``work_type``（其余源为 ``None``）；
   * ``linkUrl``：教师主页（少数指向通识课授课教师详情页）；
   * ``photograph``：头像（``/file/download?fileKey=...``，本站相对路径）。

   该接口 ``school`` 恒为「理学院」。

3. 生命科学学院教师列表（``source="sls"``，118 条，净增约 2 人）::

       GET https://sls.westlake.edu.cn/Our_Faculty/json_401.json

   响应 ``data.ldata`` 为数组，条目字段实测（2026-09-24）：

   * ``doctitle``：姓名（带「博士」后缀，如 ``"方睿博士"``）；
   * ``en_name``：英文名，落到 ``name_en``；
   * ``school``：学院（含兼聘写法，如 ``"生命科学学院与理学院（兼聘）"``）；
   * ``subject``：学科，落到 ``subject``；
   * ``Subject2`` / ``Subject3``：实验室 / 方向，非空时用 ``、`` 拼接到 ``lab``；
   * ``recurl``：教师主页；``docphoto``：头像。

4. 通识课授课教师（``source="teaching"``，28 人，净增约 22 人）::

       GET https://www.westlake.edu.cn/academics/undergraduate_studies/common_courses/TeachingFaculty/

   静态 TRS HTML 表格（**不是** Vue 组件），每行形如::

       <TD width="70%" align="left">
         <a href=".../TeachingFaculty/xxx.html">王燕博士</a>
       </TD>

   实测（2026-09-24）：页面**没有分组字段**，只有姓名与发布日期两列；
   ``href`` 可能是绝对地址（``https://www.westlake.edu.cn/faculty/binhe.html``）、
   本目录绝对地址或相对地址（``./202605/t20260507_66379.html``），统一相对
   :data:`TEACHING_LIST_URL` 绝对化。其中多数（28 人里 26 人）**没有 ``/faculty/``
   独立主页**，详情页就落在 ``TeachingFaculty/`` 目录下；本模块把 ``school``
   固定记为「通识课程」，``subject`` 留空（页面未提供）。

详情页 ``GET https://www.westlake.edu.cn + <url>``::

    new facultyDetail("#app", {personObj: {name, post, subject, lab, email,
        bottomLabel, bottomUrl, msg}, biographyStr, historyStr, researchStr,
        representativeList, ...})

``post`` 是职称/院系（如 ``"理学院"``），``biographyStr`` / ``historyStr`` /
``researchStr`` 是含 HTML 的富文本字符串。

``representativeList`` 是「代表作 / 代表性成果」区块数组（2026-09-23 实测：
**全部 296 个教师主页都有该键，且每条都是 2 项**），条目只含两个字段::

    {
      title: "代表论文",          // 区块标题，另一行为「联系我们」
      content: "<div class=\"view TRS_UEDITOR trs_paper_default trs_word\">"
               "<p>[1] ***, ***, and ***, 论文题名, <strong>期刊名</strong> "
               "卷, 页 (年).</p><p>[2] ...</p></div>",
    }

即**没有独立的题名 / 类型 / 链接 / 年份字段**——题名、期刊、年份都写在
``content`` 的富文本里（论文按 ``[n]`` 编号，逐条一个 ``<p>``；「联系我们」
那条 ``content`` 多为空串或邮箱/招生信息）。本模块把 ``content`` 原样保留为
HTML（与 ``biography_html`` 同口径，清洗由调用方按需处理）。

实现要点与坑
============
- 组件对象里混着 ``mounted: function () {}`` 之类的回调，**不能整块
  :func:`~westlake_survival._trs.js_literal`**；先 :func:`component_script`
  取到配平块，再按键用 :func:`~westlake_survival._trs.array_of` / :func:`~westlake_survival._trs.object_of` /
  :func:`_extract_string` 单独截取目标片段后才解析。
- 响应头是 ``Content-Type: text/html``（**无 charset**），``requests`` 会把
  ``encoding`` 当成 ISO-8859-1，``response.text`` 得到乱码；本模块一律取
  ``response.content`` 手动 UTF-8 解码，**不使用 ``response.text``**。
- 主站列表页与通识课授课教师页复用 :mod:`westlake_survival._cache` 的 ETag
  条件 GET（与 :mod:`westlake_survival.calendar` 同口径），详情页每次直连
  不缓存。理学院接口实测**不返回 ETag**，改为 JSON 缓存（缓存体即解析前的
  原始 JSON 文本）；生科院接口支持 ETag（实测命中返回 304），同样走条件 GET。
- **官网漏录已知问题**：主站 ``memberList`` 遗漏了若干在职教师（如理学院
  曹趣、王子桐、王盼，生科院方睿、肖宇晨，以及大部分通识课授课教师），
  本模块靠多源聚合补齐；若某源挂掉，:func:`members` 只降级跳过该源并在
  日志记 warning，其余源照常返回。
- **英文源（``lang="en"``，2026-10-24 实测）**：只用主列表源（英文主站
  en.westlake.edu.cn 的 ``/about/faculty/``，同组件 ``faculty`` / 同键
  ``memberList``）；science / sls / teaching 三源是中文 API / 中文页面，en
  模式不聚合（``source`` 只能为 ``None`` / ``"main"``）。英文条目的姓名/学院/
  学科为英文，相对 url / 图片地址按英文站根（:data:`BASE_URLS`）绝对化，
  详情页 ``facultyDetail`` 组件与中文站同构。
"""

from __future__ import annotations

import functools
import json
import logging
import re
from dataclasses import dataclass, field
from html import unescape
from urllib.parse import urljoin

import click
import requests

from westlake_survival import _cache
from westlake_survival._net import DEFAULT_TIMEOUT, http_session
from westlake_survival._trs import array_of, component_script, js_literal, object_of
from westlake_survival.exceptions import (
    NotFound,
    OffCampusError,
    ParseError,
    WestlakeError,
    is_offcampus,
)

__all__ = [
    "LIST_URL",
    "BASE_URL",
    "CACHE_NAME",
    "SCHOOL_NAMES",
    "SOURCES",
    "SCIENCE_API_URL",
    "SCIENCE_CACHE_NAME",
    "SCIENCE_WORK_TYPES",
    "SCIENCE_KEXI",
    "SLS_LIST_URL",
    "SLS_CACHE_NAME",
    "TEACHING_LIST_URL",
    "TEACHING_CACHE_NAME",
    "TEACHING_SCHOOL",
    "FacultyMember",
    "FacultyDetail",
    "FacultyRepresentative",
    "parse_members",
    "parse_science_members",
    "parse_sls_members",
    "parse_teaching_members",
    "parse_detail",
    "members",
    "fetch_detail",
    "school_options",
    "subject_options",
    "cli_group",
]

logger = logging.getLogger(__name__)

#: 教师名录列表页（主站「导师团队」，``source="main"``）。
LIST_URL = "https://www.westlake.edu.cn/about/faculty/"

#: 站点根，用于把相对 url / 图片地址绝对化。
BASE_URL = "https://www.westlake.edu.cn/"

#: 主站列表页 ETag 缓存文件名（相对缓存目录）。
CACHE_NAME = "faculty/faculty_list.html"

#: 双语源（2026-10-24 实测）：英文主站 en.westlake.edu.cn 同路径同组件名，
#: ``memberList`` 条目的姓名/学院/学科为英文，详情 URL 指向 en 域（也有相对
#: 路径，须按英文站根绝对化）。**``lang="en"`` 只用主列表源**——science /
#: sls / teaching 三源是中文 API / 中文页面，英文模式下不聚合。
LIST_URLS = {
    "zh": LIST_URL,
    "en": "https://en.westlake.edu.cn/about/faculty/",
}

#: 站点根（按语言）：相对 url / 图片地址绝对化时按 lang 切换。
BASE_URLS = {"zh": BASE_URL, "en": "https://en.westlake.edu.cn/"}

#: 主站列表页 ETag 缓存文件名（按语言；zh 缓存名逐字保留，en 另存一份）。
CACHE_BY_LANG = {"zh": CACHE_NAME, "en": "faculty/faculty_list_en.html"}

#: 列表页组件构造函数名（2026-09-22 实测）。
LIST_COMPONENT = "faculty"

#: 详情页组件构造函数名（2026-09-22 实测）。
DETAIL_COMPONENT = "facultyDetail"

#: 官方筛选用的学院枚举（与 ``schoolOPtions`` 一致，供 CLI ``--school`` 使用）。
SCHOOL_NAMES = ("理学院", "生命科学学院", "工学院", "医学院")

#: 全部数据源标识（:func:`members` 的 ``source`` 取值，``None`` 表示全聚合）。
SOURCES = ("main", "science", "sls", "teaching")

#: 理学院教师列表接口（POST JSON，2026-09-24 实测）。
SCIENCE_API_URL = (
    "https://science.westlake.edu.cn/chemistry_api/biz/modularity/project247/outLxyTutorList"
)

#: 理学院接口请求体（字段与取值必须精确，否则报参数错误）。
SCIENCE_API_BODY = {
    "language": "Chinese",
    "pageNo": 1,
    "pageSize": 500,
    "kexi": None,
    "workType": None,
}

#: 理学院接口的 JSON 缓存文件名（该接口无 ETag，只能整份缓存）。
SCIENCE_CACHE_NAME = "faculty/science_tutors.json"

#: 理学院 ``workType`` 聘用类型映射（2026-09-24 实测）。
SCIENCE_WORK_TYPES = {
    "1": "主聘",
    "2": "兼聘",
    "3": "教学",
    "4": "访问",
}

#: 理学院 ``kexi`` 科系代码映射（取自同站 ``outLxyKexiIntroduceList``，2026-09-24 实测）。
SCIENCE_KEXI = {
    "1": "化学系",
    "2": "物理系",
    "3": "天文系",
    "4": "数学系",
    "5": "交叉学科",
}

#: 理学院源的 ``school`` 常量（接口不返回学院字段）。
SCIENCE_SCHOOL = "理学院"

#: 生命科学学院教师列表（GET JSON，支持 ETag，2026-09-24 实测）。
SLS_LIST_URL = "https://sls.westlake.edu.cn/Our_Faculty/json_401.json"

#: 生科院列表 ETag 缓存文件名。
SLS_CACHE_NAME = "faculty/sls_faculty.json"

#: 通识课授课教师页（静态 TRS HTML 表格，2026-09-24 实测）。
TEACHING_LIST_URL = (
    "https://www.westlake.edu.cn/academics/undergraduate_studies/common_courses/TeachingFaculty/"
)

#: 通识课授课教师页 ETag 缓存文件名。
TEACHING_CACHE_NAME = "faculty/teaching_faculty.html"

#: 通识课授课教师的 ``school`` 常量（页面未提供学院/分组字段）。
TEACHING_SCHOOL = "通识课程"

#: ``</br>`` / ``<br>`` / ``<br/>`` 等换行标签（不区分大小写）。
_BR_RE = re.compile(r"</?br\s*/?>", re.IGNORECASE)

#: 详情页富文本里的段落边界（``</p><p ...>``）与换行标签，用于拆出纯文本行。
_RICH_BREAK_RE = re.compile(
    r"<\s*/?\s*br\s*/?\s*>|<\s*/\s*p\s*>\s*<\s*p[^>]*>",
    re.IGNORECASE,
)

#: 任意 HTML 标签（用于把富文本剥成纯文本）。
_TAG_RE = re.compile(r"<[^>]*>")

#: 用于清理详情页 ``subject`` 尾部的分隔符（实测为 ``"物理学,"``）。
_TRAILING_PUNCT = "，,、;；"

#: CLI ``faculty detail`` 每个代表作区块最多列出的纯文本行数：超出只报总数，
#: 避免一份长论文列表（实测 6 条/人，未来可能更长）刷屏。
_REP_PREVIEW_LINES = 5


# --------------------------------------------------------------------------- #
# 数据模型
# --------------------------------------------------------------------------- #
@dataclass
class FacultyMember:
    """教师名录里的一位教师。

    ``subject`` 是拆分后的「首学科」（原始 ``subject`` 中换行标签之前的部分，
    可能为空字符串——实测有 14 人只写了实验室）；``lab`` 是「实验室/方向」
    部分，原始数据里没有第二段时为 ``None``。

    ``source`` 标识该条目来自哪个数据源（:data:`SOURCES` 之一：``"main"``
    主站导师团队 / ``"science"`` 理学院 / ``"sls"`` 生科院 / ``"teaching"``
    通识课授课教师）；``work_type`` 只在理学院源有值（主聘/兼聘/教学/访问，
    见 :data:`SCIENCE_WORK_TYPES`），其余源为 ``None``。
    """

    name: str
    name_en: str = ""
    school: str = ""
    subject: str = ""
    lab: str | None = None
    url: str = ""
    img_url: str = ""
    visible: bool = True
    source: str = "main"
    work_type: str | None = None

    def matches(self, keyword: str) -> bool:
        """``keyword``（不区分大小写）是否命中 name / name_en / subject / lab。"""
        needle = keyword.casefold()
        if not needle:
            return True
        fields = (self.name, self.name_en, self.subject, self.lab or "")
        return any(needle in field.casefold() for field in fields)


@dataclass
class FacultyRepresentative:
    """详情页「代表作 / 代表性成果」区块里的一项（``representativeList`` 条目）。

    实测（2026-09-23，全部 296 个教师主页）条目只有两个字段：

    - ``title``：区块标题，如 ``"代表论文"``；另一项固定是 ``"联系我们"``。
    - ``content_html``：含 HTML 的富文本（页面原文，**未清洗**）。论文那项里
      按 ``[n]`` 编号、逐条一个 ``<p>``，题名/期刊/年份都写在文本里，没有
      独立的结构化字段；「联系我们」多为空串或邮箱/招生信息。

    需要纯文本时用 :meth:`lines`（按 ``<p>``/``<br>`` 拆行并剥标签），
    ``content_html`` 原样保留供调用方自行清洗。
    """

    title: str = ""
    content_html: str = ""

    def lines(self) -> list[str]:
        """把 ``content_html`` 拆成纯文本行（按段落/换行标记，已剥 HTML 标签）。"""
        return _split_rich_lines(self.content_html)


@dataclass
class FacultyDetail:
    """教师主页详情。

    ``biography_html`` / ``history_html`` / ``research_html`` 是原始富文本
    （含 HTML 标签），展示时按需自行清洗。

    ``representatives`` 是「代表作 / 代表性成果」区块（页面
    ``representativeList``）：每个条目为一个 :class:`FacultyRepresentative`，
    保持页面原始顺序。字段缺失或结构变化时退化为空列表（不影响其余字段）。
    """

    name: str
    title: str = ""
    subject: str = ""
    lab: str = ""
    email: str = ""
    biography_html: str = ""
    history_html: str = ""
    research_html: str = ""
    url: str = ""
    representatives: list[FacultyRepresentative] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# JS 片段提取（先取配平块，再按键单独截取，避开组件里的 function 回调）
# --------------------------------------------------------------------------- #
def _extract_string(block: str, key: str) -> str:
    """取出组件块里 ``key: "..."`` 的字符串值（支持 ``\\u`` / ``\\/`` 等转义）。

    富文本字段（``biographyStr`` 等）内部含大量转义引号，直接正则取不到，
    这里按引号扫描到配对的收尾引号后交给 :func:`js_literal` 解析。
    """
    m = re.search(r"\b" + re.escape(key) + r"\s*:\s*([\"'])", block)
    if not m:
        raise ParseError(f"组件数据中找不到字符串键 {key!r}")
    start = m.start(1)
    quote = block[start]
    i = start + 1
    n = len(block)
    while i < n:
        ch = block[i]
        if ch == "\\":
            i += 2
            continue
        if ch == quote:
            return js_literal(block[start : i + 1])
        i += 1
    raise ParseError(f"键 {key!r} 的字符串未闭合")


# --------------------------------------------------------------------------- #
# 解析
# --------------------------------------------------------------------------- #
def _split_subject(raw: str) -> tuple[str, str | None]:
    """把 ``"物理学</br>冷原子量子调控实验室"`` 拆成 ``("物理学", "冷原子量子调控实验室")``。

    - 首段是学科，其余段用 ``、`` 连接作为实验室/方向；
    - 首段为空（``"</br>早期宇宙实验室"``）时学科为空字符串；
    - 只有一段（无换行标签）时实验室为 ``None``。
    """
    segments = [part.strip() for part in _BR_RE.split(raw or "")]
    subject = segments[0] if segments else ""
    rest = [part for part in segments[1:] if part]
    return subject, ("、".join(rest) if rest else None)


def _absolute(url: str, base: str = LIST_URL) -> str:
    """把相对地址（``./x``、``/y``）绝对化；空串原样返回。"""
    if not url:
        return ""
    return urljoin(base, url)


def _build_member(raw: dict, base: str = LIST_URL) -> FacultyMember:
    """把 ``memberList`` 的一个原始条目转成 :class:`FacultyMember`（主站源）。

    ``base`` 是相对 url / 图片地址的绝对化基准（zh 用中文站列表页、en 用
    英文站列表页，见 :data:`LIST_URLS`）。
    """
    subject, lab = _split_subject(str(raw.get("subject") or ""))
    return FacultyMember(
        name=str(raw.get("name") or ""),
        name_en=str(raw.get("nameEn") or ""),
        school=str(raw.get("school") or ""),
        subject=subject,
        lab=lab,
        url=_absolute(str(raw.get("url") or ""), base),
        img_url=_absolute(str(raw.get("imgUrl") or ""), base),
        visible=bool(raw.get("show", True)),
        source="main",
    )


def parse_members(html: str, lang: str = "zh") -> list[FacultyMember]:
    """解析教师名录列表页 HTML，返回全部教师（含隐藏项，过滤由调用方负责）。

    ``lang`` 只影响相对 url / 图片地址的绝对化基准（zh 按中文站、en 按英文站
    :data:`LIST_URLS`）；英文页条目的 url 多为 en 域绝对地址。

    官网 ``memberList`` 实测会重复收录同一教师（2026-09-24：曾文锋出现两次，
    两条完全相同），这里按 ``url`` 去重、保留首次出现的顺序，避免同一人在列表
    里重复出现。``url`` 为空的条目无法判定同一人，一律保留。

    Raises:
        ParseError: 页面里找不到 ``faculty`` 组件或 ``memberList`` 键。
    """
    base = LIST_URLS.get(lang, LIST_URL)
    block = component_script(html, LIST_COMPONENT)
    if not block:
        raise ParseError(f"页面中找不到组件 {LIST_COMPONENT!r}，结构可能已变化")
    raw_list = array_of(block, "memberList")
    if not raw_list:
        raise ParseError("memberList 为空，页面结构可能已变化")
    members: list[FacultyMember] = []
    seen_urls: set[str] = set()
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        member = _build_member(item, base=base)
        if member.url:
            if member.url in seen_urls:
                continue
            seen_urls.add(member.url)
        members.append(member)
    return members


def _clean_subject(value: str) -> str:
    """清理详情页 ``subject`` 尾部的分隔符（实测 ``"物理学,"`` → ``"物理学"``）。"""
    return (value or "").strip().rstrip(_TRAILING_PUNCT).strip()


# --------------------------------------------------------------------------- #
# 子源解析（理学院 / 生科院 / 通识课授课教师）
# --------------------------------------------------------------------------- #
def _parse_json(text: str) -> dict:
    """解析 JSON 响应体；结构不合法时抛 :class:`ParseError`。"""
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ParseError(f"接口返回不是合法 JSON：{text[:120]!r}") from exc
    if not isinstance(data, dict):
        raise ParseError(f"接口返回顶层不是对象：{text[:120]!r}")
    return data


def parse_science_members(text: str) -> list[FacultyMember]:
    """解析理学院教师列表接口（``outLxyTutorList``）返回的 JSON 文本。

    响应形如 ``{"msg": "请求成功", "data": {"outputData": [ {...}, ... ]}}``；
    条目字段映射见模块 docstring（``fullName`` → name、``kexi`` → subject、
    ``remark`` → lab、``workType`` → work_type、``linkUrl`` → url、
    ``photograph`` → img_url）。``school`` 恒为 :data:`SCIENCE_SCHOOL`，
    ``name_en`` 留空（``chinesePinyin`` 是拼音而非英文名）。

    同一 ``linkUrl`` 重复出现时按首次保留（实测 125 条里有 1 条重复）。

    Raises:
        ParseError: JSON 不合法，或 ``data.outputData`` 缺失/非数组。
    """
    payload = _parse_json(text)
    data = payload.get("data")
    rows = data.get("outputData") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ParseError(f"理学院接口缺少 data.outputData 数组：{text[:120]!r}")
    members: list[FacultyMember] = []
    seen_urls: set[str] = set()
    for item in rows:
        if not isinstance(item, dict):
            continue
        url = _absolute(str(item.get("linkUrl") or ""), SCIENCE_API_URL)
        if url:
            if url in seen_urls:
                continue
            seen_urls.add(url)
        kexi = str(item.get("kexi") or "")
        work_type = SCIENCE_WORK_TYPES.get(str(item.get("workType") or ""))
        members.append(
            FacultyMember(
                name=str(item.get("fullName") or "").strip(),
                school=SCIENCE_SCHOOL,
                subject=SCIENCE_KEXI.get(kexi, ""),
                lab=(str(item.get("remark") or "").strip() or None),
                url=url,
                img_url=_absolute(str(item.get("photograph") or ""), SCIENCE_API_URL),
                visible=True,
                source="science",
                work_type=work_type,
            )
        )
    return members


def parse_sls_members(text: str) -> list[FacultyMember]:
    """解析生命科学学院教师列表（``json_401.json``）返回的 JSON 文本。

    响应形如 ``{"data": {"ldata": [ {...}, ... ]}}``；条目字段映射见模块
    docstring（``doctitle`` → name、``en_name`` → name_en、``school`` → school、
    ``subject`` → subject、``Subject2`` / ``Subject3`` → lab、
    ``recurl`` → url、``docphoto`` → img_url）。

    Raises:
        ParseError: JSON 不合法，或 ``data.ldata`` 缺失/非数组。
    """
    payload = _parse_json(text)
    data = payload.get("data")
    rows = data.get("ldata") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ParseError(f"生科院接口缺少 data.ldata 数组：{text[:120]!r}")
    members: list[FacultyMember] = []
    seen_urls: set[str] = set()
    for item in rows:
        if not isinstance(item, dict):
            continue
        url = _absolute(str(item.get("recurl") or ""), BASE_URL)
        if url:
            if url in seen_urls:
                continue
            seen_urls.add(url)
        subject, lab = _split_subject(str(item.get("subject") or ""))
        extra = [
            str(item.get(key) or "").strip()
            for key in ("Subject2", "Subject3")
        ]
        extra = [part for part in extra if part]
        lab = "、".join(extra) if extra else lab
        members.append(
            FacultyMember(
                name=str(item.get("doctitle") or "").strip(),
                name_en=str(item.get("en_name") or "").strip(),
                school=str(item.get("school") or "").strip(),
                subject=subject,
                lab=lab,
                url=url,
                img_url=_absolute(str(item.get("docphoto") or ""), BASE_URL),
                visible=True,
                source="sls",
            )
        )
    return members


#: 通识课授课教师页表格行的 ``<a href>`` 与姓名（``<TD width="70%">`` 单元格内）。
_TEACHING_ROW_RE = re.compile(
    r'<TD[^>]*width="70%"[^>]*>\s*<a\s+href="([^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)


def parse_teaching_members(html: str) -> list[FacultyMember]:
    """解析通识课授课教师页的静态 HTML 表格。

    页面每行形如 ``<TD width="70%" align="left"><a href="...">王燕博士</a></TD>``；
    ``href`` 可能是绝对地址、本目录绝对地址或相对地址（``./202605/...``），统一
    相对 :data:`TEACHING_LIST_URL` 绝对化。页面没有分组/学科字段，``school``
    固定记为 :data:`TEACHING_SCHOOL`，``subject`` 留空。

    同一 ``href`` 重复出现时按首次保留；``href`` 为空的条目跳过。

    Raises:
        ParseError: 页面里一条授课教师行都找不到（结构可能已变化）。
    """
    members: list[FacultyMember] = []
    seen_urls: set[str] = set()
    for raw_href, raw_name in _TEACHING_ROW_RE.findall(html or ""):
        url = _absolute(unescape(raw_href).strip(), TEACHING_LIST_URL)
        if not url or url in seen_urls:
            continue
        name = unescape(_TAG_RE.sub("", raw_name)).strip()
        if not name:
            continue
        seen_urls.add(url)
        members.append(
            FacultyMember(
                name=name,
                school=TEACHING_SCHOOL,
                url=url,
                visible=True,
                source="teaching",
            )
        )
    if not members:
        raise ParseError("通识课授课教师页里找不到任何教师行，结构可能已变化")
    return members


def _split_rich_lines(html_text: str) -> list[str]:
    """把一段含 HTML 的富文本拆成纯文本行。

    先按 ``<br>`` 系列与 ``</p><p>`` 换成换行，再剥掉其余标签并还原实体
    （``&nbsp;`` 等），最后逐行去空白、丢弃空行。空输入返回空列表。

    论文列表 ``content`` 里逐条一个 ``<p>``（``[1] ...``、``[2] ...``），
    因此每行即一条成果。
    """
    if not html_text:
        return []
    text = _RICH_BREAK_RE.sub("\n", html_text)
    text = unescape(_TAG_RE.sub("", text))
    return [line.strip() for line in text.split("\n") if line.strip()]


def _build_representative(raw: dict) -> FacultyRepresentative:
    """把 ``representativeList`` 的一个原始条目转成 :class:`FacultyRepresentative`。"""
    return FacultyRepresentative(
        title=str(raw.get("title") or ""),
        content_html=str(raw.get("content") or ""),
    )


def _parse_representatives(block: str) -> list[FacultyRepresentative]:
    """解析 ``representativeList``；键缺失或结构变化时返回空列表。

    该键实测恒存在（全部 296 个主页），但属可选展示字段：缺失时静默降级为
    空列表，不让整页解析失败（与 :func:`westlake_survival.events.parse_detail`
    处理可选 ``right`` 键同口径）。
    """
    try:
        raw_list = array_of(block, "representativeList")
    except ParseError:
        return []
    return [
        _build_representative(item)
        for item in raw_list
        if isinstance(item, dict)
        and str(item.get("title") or "").strip() not in ("联系我们", "Contact Us", "Contact")
    ]


def parse_detail(html: str, url: str = "") -> FacultyDetail:
    """解析教师详情页 HTML，返回 :class:`FacultyDetail`。

    Raises:
        ParseError: 页面里找不到 ``facultyDetail`` 组件或 ``personObj`` 键。
    """
    block = component_script(html, DETAIL_COMPONENT)
    if not block:
        raise ParseError(f"页面中找不到组件 {DETAIL_COMPONENT!r}，结构可能已变化")
    person = object_of(block, "personObj")
    return FacultyDetail(
        name=str(person.get("name") or ""),
        title=str(person.get("post") or ""),
        subject=_clean_subject(str(person.get("subject") or "")),
        lab=str(person.get("lab") or ""),
        email=str(person.get("email") or ""),
        biography_html=_extract_string(block, "biographyStr"),
        history_html=_extract_string(block, "historyStr"),
        research_html=_extract_string(block, "researchStr"),
        url=url,
        representatives=_parse_representatives(block),
    )


def _options(block: str, key: str) -> list[str]:
    """从 ``key: [{value, label}, ...]`` 里取出 ``value`` 列表。"""
    return [
        str(item.get("value"))
        for item in array_of(block, key)
        if isinstance(item, dict) and item.get("value")
    ]


def school_options(html: str) -> list[str]:
    """读出列表页 ``schoolOPtions`` 的学院枚举值（供校验/展示）。"""
    block = component_script(html, LIST_COMPONENT)
    if not block:
        raise ParseError(f"页面中找不到组件 {LIST_COMPONENT!r}")
    return _options(block, "schoolOPtions")


def subject_options(html: str) -> list[str]:
    """读出列表页 ``subjectOptions`` 的学科枚举值（供校验/展示）。"""
    block = component_script(html, LIST_COMPONENT)
    if not block:
        raise ParseError(f"页面中找不到组件 {LIST_COMPONENT!r}")
    return _options(block, "subjectOptions")


# --------------------------------------------------------------------------- #
# 网络层
# --------------------------------------------------------------------------- #
def _decode(response: requests.Response) -> str:
    """手动 UTF-8 解码响应体（响应无 charset 头，不能用 ``response.text``）。"""
    raw = getattr(response, "content", None)
    if raw is None:  # 兜底：只有 text 的替身对象
        return getattr(response, "text", "") or ""
    return raw.decode("utf-8", errors="replace")


def _check_response(response: requests.Response, url: str) -> None:
    """把 HTTP 层失败翻译成库内异常。"""
    status = getattr(response, "status_code", 200)
    if status == 403 and is_offcampus(response):
        raise OffCampusError(f"官网导师页面拒绝访问（403）：{url}")
    if status == 404:
        raise NotFound(f"页面不存在（404）：{url}")
    if status >= 400:
        raise ParseError(f"官网导师页面返回 HTTP {status}：{url}")


def _fetch_html(
    session: requests.Session,
    url: str,
    *,
    cache_name: str | None = None,
    timeout: float | None = None,
) -> str:
    """GET 一个页面并按 UTF-8 解码；``cache_name`` 非空时启用 ETag 条件 GET。

    条件 GET 复用 :mod:`westlake_survival._cache` 的 ``load_json`` / ``save_json``
    （与 :mod:`westlake_survival.calendar` 同口径），但响应体一律用
    ``response.content.decode("utf-8")``，不依赖 ``response.text``。
    """
    timeout = DEFAULT_TIMEOUT if timeout is None else timeout
    cached: dict = {}
    headers: dict[str, str] = {}
    if cache_name:
        cached = _cache.load_json(cache_name, default=None) or {}
        if cached.get("etag"):
            headers["If-None-Match"] = cached["etag"]

    try:
        response = session.get(url, headers=headers, timeout=timeout)
    except requests.Timeout as exc:
        raise WestlakeError(f"官网导师页面请求超时（{timeout}s）：{url}") from exc
    except requests.RequestException as exc:
        raise WestlakeError(f"官网导师页面请求失败：{exc}") from exc

    if cache_name and getattr(response, "status_code", 200) == 304 and cached.get("body"):
        return cached["body"]

    _check_response(response, url)
    text = _decode(response)
    if cache_name:
        etag = response.headers.get("ETag") or cached.get("etag")
        if etag:
            _cache.save_json(cache_name, {"etag": etag, "body": text})
    return text


def _fetch_source_text(
    session: requests.Session,
    url: str,
    *,
    cache_name: str,
    timeout: float | None = None,
    method: str = "GET",
    json_body: dict | None = None,
) -> str:
    """抓取子源响应文本，复用 :mod:`westlake_survival._cache` 做条件 GET / JSON 缓存。

    - ``GET`` 且服务器支持 ETag 时走条件请求（命中 304 用缓存体），与
      :func:`_fetch_html` 同口径；
    - 理学院接口是 ``POST`` 且**不返回 ETag**，此时只把响应体整份存入缓存，
      并在请求失败（网络错误 / HTTP 4xx-5xx）时**回退到缓存体**，避免接口抖动
      直接打断聚合。
    """
    timeout = DEFAULT_TIMEOUT if timeout is None else timeout
    cached = _cache.load_json(cache_name, default=None) or {}
    headers: dict[str, str] = {}
    if cached.get("etag"):
        headers["If-None-Match"] = cached["etag"]

    try:
        if method == "POST":
            response = session.post(url, json=json_body, headers=headers, timeout=timeout)
        else:
            response = session.get(url, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        if cached.get("body"):
            logger.warning("子源请求失败，改用缓存体：%s（%s）", url, exc)
            return cached["body"]
        raise WestlakeError(f"教师子源请求失败：{exc}（{url}）") from exc

    if getattr(response, "status_code", 200) == 304 and cached.get("body"):
        return cached["body"]

    try:
        _check_response(response, url)
    except WestlakeError as exc:
        if cached.get("body"):
            logger.warning("子源返回错误，改用缓存体：%s（%s）", url, exc)
            return cached["body"]
        raise

    text = _decode(response)
    etag = response.headers.get("ETag") or cached.get("etag")
    _cache.save_json(cache_name, {"etag": etag, "body": text})
    return text


def _fetch_main_members(
    session: requests.Session, timeout: float | None, lang: str = "zh"
) -> list[FacultyMember]:
    """抓取并解析主站「导师团队」名录（``lang`` 切换中/英文主站与缓存）。"""
    html = _fetch_html(
        session,
        LIST_URLS.get(lang, LIST_URL),
        cache_name=CACHE_BY_LANG.get(lang, CACHE_NAME),
        timeout=timeout,
    )
    return parse_members(html, lang=lang)


def _fetch_science_members(
    session: requests.Session, timeout: float | None
) -> list[FacultyMember]:
    """抓取并解析理学院教师列表（POST JSON 接口）。"""
    text = _fetch_source_text(
        session,
        SCIENCE_API_URL,
        cache_name=SCIENCE_CACHE_NAME,
        timeout=timeout,
        method="POST",
        json_body=SCIENCE_API_BODY,
    )
    return parse_science_members(text)


def _fetch_sls_members(
    session: requests.Session, timeout: float | None
) -> list[FacultyMember]:
    """抓取并解析生命科学学院教师列表（GET JSON，支持 ETag）。"""
    text = _fetch_source_text(
        session,
        SLS_LIST_URL,
        cache_name=SLS_CACHE_NAME,
        timeout=timeout,
    )
    return parse_sls_members(text)


def _fetch_teaching_members(
    session: requests.Session, timeout: float | None
) -> list[FacultyMember]:
    """抓取并解析通识课授课教师页（静态 TRS HTML 表格）。"""
    text = _fetch_source_text(
        session,
        TEACHING_LIST_URL,
        cache_name=TEACHING_CACHE_NAME,
        timeout=timeout,
    )
    return parse_teaching_members(text)


#: 各子源（``source`` → 抓取函数）。``main`` 源带 ``lang`` 参数、按语言切换
#: URL / 缓存，在 :func:`members` 里单独派发，不放这张表。
_SOURCE_FETCHERS = {
    "main": _fetch_main_members,
    "science": _fetch_science_members,
    "sls": _fetch_sls_members,
    "teaching": _fetch_teaching_members,
}


# --------------------------------------------------------------------------- #
# 公开 API
# --------------------------------------------------------------------------- #
def members(
    school: str | None = None,
    keyword: str | None = None,
    include_hidden: bool = False,
    limit: int | None = None,
    *,
    source: str | None = None,
    session: requests.Session | None = None,
    timeout: float | None = None,
    lang: str = "zh",
) -> list[FacultyMember]:
    """抓取并过滤教师名录（默认聚合主站 + 理学院 + 生科院 + 通识课四源）。

    聚合顺序为 ``main`` → ``science`` → ``sls`` → ``teaching``，按 ``url`` 去重、
    **保留先出现的条目**（主站优先），因此同一教师在主站与子源都收录时只保留
    主站条目（``source="main"``）。三个子源任一失败只降级跳过并记 warning，
    其余源照常返回；主站失败仍按既有口径抛异常（不降级）。

    Args:
        school: 学院名（``理学院`` / ``生命科学学院`` / ``工学院`` / ``医学院``）；
            按 ``FacultyMember.school`` 的**子串**匹配，因此兼聘教师（如
            ``"工学院与理学院（兼聘）"``）在两个学院下都会出现。通识课授课
            教师的 ``school`` 为 ``"通识课程"``。``lang="en"`` 时该字段是英文
            原始值（如 ``"School of Science"``），中文枚举匹配不到任何条目。
        keyword: 关键词，不区分大小写地匹配 name / name_en / subject / lab。
        include_hidden: 为 ``False``（默认）时过滤掉主站 ``show`` 为假的条目。
        limit: 最多返回条数；``None`` 表示不限。
        source: 只取单一数据源（``main`` / ``science`` / ``sls`` / ``teaching``）；
            ``None``（默认）聚合全部四源。``lang="en"`` 时只允许 ``None`` 或
            ``"main"``——science / sls / teaching 三源是中文 API / 中文页面。
        session: 可注入的 :class:`requests.Session`（测试用）。
        timeout: 请求超时（秒），缺省 :data:`~westlake_survival._net.DEFAULT_TIMEOUT`。
        lang: ``"zh"``（默认）中文主站并聚合四源；``"en"`` **只用主列表源**
            （英文主站 en.westlake.edu.cn 的 ``/about/faculty/``，相对 url /
            图片地址按英文站根绝对化），姓名/学院/学科为英文（未知值回退 zh）。

    Returns:
        过滤后的 :class:`FacultyMember` 列表，保持各源原始顺序。

    Raises:
        ValueError: ``source`` 不是 :data:`SOURCES` 中的取值，或 ``lang="en"``
            时指定了主站以外的 ``source``。
        WestlakeError: 主站网络层失败（超时/连接错误等）。
        ParseError: 主站 HTTP 4xx/5xx，或页面结构变化导致解析失败。
        OffCampusError: 主站被校外访问网关拦截。
        NotFound: 主站列表页返回 404。
    """
    if source is not None and source not in SOURCES:
        raise ValueError(f"未知的教师数据源：{source!r}（可选 {SOURCES}）")
    if lang != "zh" and source not in (None, "main"):
        raise ValueError(
            f"lang={lang!r} 只支持主列表源（source=None 或 'main'），得到 {source!r}"
        )
    session = session if session is not None else http_session()
    wanted = ("main",) if lang != "zh" else ((source,) if source is not None else SOURCES)

    result: list[FacultyMember] = []
    seen_urls: set[str] = set()
    for name in wanted:
        try:
            if name == "main":
                fetched = _fetch_main_members(session, timeout, lang=lang)
            else:
                fetched = _SOURCE_FETCHERS[name](session, timeout)
        except WestlakeError as exc:
            if name == "main":
                raise  # 主站不降级：维持既有异常口径
            logger.warning("教师数据源 %s 抓取失败，已跳过：%s", name, exc)
            continue
        for member in fetched:
            if member.url:
                if member.url in seen_urls:
                    continue
                seen_urls.add(member.url)
            result.append(member)

    if school:
        result = [m for m in result if school in m.school]
    if keyword:
        result = [m for m in result if m.matches(keyword)]
    if not include_hidden:
        result = [m for m in result if m.visible]
    if limit is not None:
        result = result[: max(0, limit)]
    return result


def _is_faculty_home(url: str) -> bool:
    """``url`` 是否为 ``/faculty/`` 下的独立教师主页（本模块唯一支持的详情形态）。"""
    return "/faculty/" in url


def fetch_detail(
    url: str,
    *,
    session: requests.Session | None = None,
    timeout: float | None = None,
    lang: str = "zh",
) -> FacultyDetail:
    """抓取并解析一位教师的详情页。

    只支持 ``/faculty/`` 下的独立教师主页。授课教师 / 无独立主页的条目
    （url 落在 ``.../TeachingFaculty/`` 等目录下）没有 ``facultyDetail`` 组件，
    这里直接抛 :class:`ParseError` 并在消息里说明「该教师无独立主页」，不发起
    请求。

    Args:
        url: 教师主页地址，绝对（``https://www.westlake.edu.cn/faculty/x.html``）
            或相对（``/faculty/x.html``）均可；相对路径按 ``lang`` 对应的站点
            根（:data:`BASE_URLS`）绝对化。
        session: 可注入的 :class:`requests.Session`（测试用）。
        timeout: 请求超时（秒）。
        lang: ``"zh"``（默认）按中文站根绝对化；``"en"`` 按英文站根绝对化
            （英文列表条目的 url 多为 en 域绝对地址，不受影响）。

    Raises:
        WestlakeError: 网络层失败。
        ParseError: 非 ``/faculty/`` 主页（该教师无独立主页），或 HTTP 4xx/5xx
            （404 除外），或页面结构变化。
        NotFound: 详情页返回 404。
        OffCampusError: 被校外访问网关拦截。
    """
    absolute = _absolute(url, base=BASE_URLS.get(lang, BASE_URL))
    if not _is_faculty_home(absolute):
        raise ParseError(f"该教师无独立主页：{absolute}")
    session = session if session is not None else http_session()
    html = _fetch_html(session, absolute, timeout=timeout)
    return parse_detail(html, url=absolute)


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
    name="faculty",
    help="导师团队：查询西湖大学教师名录与教师主页。",
    invoke_without_command=True,
)
@click.option(
    "--school",
    type=click.Choice(SCHOOL_NAMES),
    default=None,
    help="按学院筛选（兼聘教师会在其各学院下出现）。",
)
@click.option("--keyword", default=None, help="关键词，匹配姓名/英文名/学科/实验室。")
@click.option(
    "--source",
    type=click.Choice(("all", *SOURCES)),
    default="all",
    show_default=True,
    help="数据源：all 聚合四源（主站/理学院/生科院/通识课），或单选某源。",
)
@click.option("--limit", type=int, default=20, show_default=True, help="最多显示条数。")
@click.option("--all", "include_hidden", is_flag=True, help="包含官网隐藏的成员。")
@click.option(
    "--lang",
    type=click.Choice(["zh", "en"]),
    default="zh",
    show_default=True,
    help="语言：zh=中文主站 en=英文主站（en 只用主列表源，school 用英文原始值）。",
)
@click.pass_context
def cli_group(
    ctx: click.Context,
    school: str | None,
    keyword: str | None,
    source: str,
    limit: int,
    include_hidden: bool,
    lang: str,
) -> None:
    """``westlake faculty [--school ...] [--keyword ...] [--source ...] [--limit N] [--all] [--lang en]``。"""
    if ctx.invoked_subcommand is not None:  # detail 子命令
        return
    _run_list(
        school=school,
        keyword=keyword,
        source=None if source == "all" else source,
        limit=limit,
        include_hidden=include_hidden,
        lang=lang,
    )


@cli_group.command(name="detail", help="查看一位教师的详情页。")
@click.argument("url")
@_handle_errors
def faculty_detail_cmd(url: str) -> None:
    """``westlake faculty detail <url>``：打印教师主页的要点信息。

    末尾追加「代表作 / 代表性成果」：先报区块条数，再逐个区块列出标题与其
    纯文本内容的前 :data:`_REP_PREVIEW_LINES` 行（超出部分只报总数）。
    """
    detail = fetch_detail(url)
    click.echo(f"姓名：{detail.name or '—'}")
    click.echo(f"职称/院系：{detail.title or '—'}")
    click.echo(f"学科：{detail.subject or '—'}")
    click.echo(f"实验室/方向：{detail.lab or '—'}")
    click.echo(f"邮箱：{detail.email or '—'}")
    click.echo(f"链接：{detail.url or url}")
    click.echo(f"代表作：{len(detail.representatives)} 项")
    for rep in detail.representatives:
        click.echo(f"  {rep.title or '（无标题）'}：")
        lines = rep.lines()
        if not lines:
            click.echo("    —")
            continue
        for line in lines[:_REP_PREVIEW_LINES]:
            click.echo(f"    {line}")
        if len(lines) > _REP_PREVIEW_LINES:
            click.echo(f"    …（共 {len(lines)} 条）")


@_handle_errors
def _run_list(
    *,
    school: str | None,
    keyword: str | None,
    source: str | None,
    limit: int,
    include_hidden: bool,
    lang: str = "zh",
) -> None:
    """抓取名录并打印表格（``_print_table`` 惰性导入以免循环依赖）。

    先按筛选条件取全量（``limit=None``），再在展示层截断：这样既能打印
    「共 N 条，已显示 M 条」的被截断提示，又不会让 ``--limit`` 的默认值
    （20）被误读成名录总量。
    """
    from westlake_survival.cli.main import _print_table

    people = members(
        school=school,
        keyword=keyword,
        include_hidden=include_hidden,
        source=source,
        limit=None,
        lang=lang,
    )
    if not people:
        click.echo("未找到匹配的教师。")
        return
    total = len(people)
    shown = people[: max(0, limit)] if limit is not None else people
    filters = []
    if school:
        filters.append(f"学院：{school}")
    if keyword:
        filters.append(f"关键词：{keyword}")
    if source:
        filters.append(f"数据源：{source}")
    scope = "　".join(filters)
    click.echo(f"{scope}　共 {total} 人" if scope else f"共 {total} 人")
    rows = [
        (m.name, m.school, m.subject, m.lab or "—", m.url)
        for m in shown
    ]
    _print_table(rows, ("姓名", "学院", "学科", "实验室/方向", "链接"))
    if len(shown) < total:
        click.echo(
            f"共 {total} 条，已显示 {len(shown)} 条（如需更多请调大 --limit）。"
        )