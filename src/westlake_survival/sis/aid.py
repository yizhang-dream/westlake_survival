"""SIS 学生资助 / 海外交流 / 社团活动读取层。

数据源（2026-09-23 登录态实测）都是 PeopleSoft fluid 组件页，经共享读取层
:mod:`westlake_survival.sis.pages` 抓页 + 解析。**关键坑位**：这些组件的
**裸组件名**（如 ``WL_LOAN_LIST_COM.GBL``、``WL_SAA_OTB_LIST_FL.GBL``）
直接访问会被 PeopleSoft 判为「You are not authorized to access this
component. (40,20)」；必须带菜单前缀
``WL_CUSTOMIZE_MENU.``（如 ``WL_CUSTOMIZE_MENU.WL_LOAN_LIST_COM.GBL``）
才返回真实页面。本模块的组件常量一律带前缀。

各页实测结构（2026-09-23，学生角色；「空」= 该账号无记录）
============================================================

- **贷款列表** ``WL_CUSTOMIZE_MENU.WL_LOAN_LIST_COM.GBL?NavColl=true``
  （页标题「Loan Assistance Records」）：**空**，正文 HTML 区
  ``chnNoDataFound`` 文案「You currently do not have a loan application.」，
  整页无任何 ``ps_grid`` 网格（空页不渲染表头）。
- **个人贷款** ``WL_CUSTOMIZE_MENU.WL_LOAN_OWN_COM.GBL``
  （「Loan Application」）：**空**，同款 no-data 文案。
- **还款** ``WL_CUSTOMIZE_MENU.WL_LOAN_REPAYM_FL.GBL``
  （「Loan Repayment」）：**空**，文案「The current query has no data.」。
- **海外交流 Outbound** ``WL_CUSTOMIZE_MENU.WL_SAA_OTB_LIST_FL.GBL``
  （「My Outbound Application」）：**空**，文案「You have not applied yet.」。
- **Exchange 申请** ``WL_CUSTOMIZE_MENU.WL_EXC_APPL_LIST.GBL``
  （「Exchange Apply」）：**空**，同款「You have not applied yet.」。
- **Exchange 院校** ``WL_CUSTOMIZE_MENU.WL_EXC_SCHOOL_COM.GBL``
  （「University List」）：**空**，文案「There is no data for the current
  query.」。
- **社团活动** ``WL_CUSTOMIZE_MENU.WL_STU_ACT_LIST_FL.GBL``（「社团活动」）：
  **空**，文案「There are currently no activity registrations.」。
- **我的社团** ``WL_CUSTOMIZE_MENU.WL_STU_ORG_LIST_FL.GBL``（「我的社团列表
  / My Clubs」）：**有数据**。fluid 网格 ``WL_STU_ORG_TBL``（实测 2 行），
  表头 ``Academic Year / Club Name / Founder / Initiation Deadline /
  Current Initiators Number``。
- **学生组织与社团目录** ``WL_CUSTOMIZE_MENU.WL_STU_ORG_SUM_FL.GBL``
  （「学生组织与社团 / Orginazation List」）：**有数据**。这不是标准
  ``<table>`` fluid 网格，而是 **div 网格**（``ps_grid-row`` 在 ``<div>``
  里），故 :func:`~westlake_survival.sis.pages.parse_fluid_grid` 不适用，
  本模块用 :func:`_org_directory_rows` 按分组盒（``ps_header-group``）逐个
  抽社团名。实测 39 行，分 ``STUDENT ORGANIZATION / POLITICAL AND
  IDEOLOGICAL / ACADEMIC AND TECHNOLOGICAL / INNOVATION AND
  ENTREPRENEURSHIP / CULTURE AND SPORTS / VOLUNTARY AND PUBLIC WELFARE /
  SELF-DISCIPLINE AND MUTUAL ASSISTANCE / OTHER`` 8 类（空类不产出行）。
- **勤工助学** ``CHN_PACKAGE_CS.CHN_WORK_MD01.GBL?page=CHN_WORK_MD01``
  （「Study Jobs Self Sevice」）：导航网格 ``CHN_MD_NAV`` 是 **4 个 tab**
  （Positions Available For Application / My Work-Study Positions / Hours
  Declaration / My Salary），每行 ``ps-text`` 为标签、``onclick`` 里的
  ``LaunchURL`` 为目标 URL。各 tab 指向的子页（``CHN_STUAPL_LIST_FL`` /
  ``WL_STUWORK_LIST_FL`` / ``WL_STUSAL_LIST_FL``）实测均返回「No Data
  Found!」，无网格数据。

列名兜底
========
贷款 / 交流 / 活动这几页对当前账号均为空页，**表格列名无法实测**；相应模型
（:class:`LoanRecord` 等）给出少量按 PeopleSoft 命名习惯推断的具名字段，并在
:attr:`~LoanRecord.raw` 保留原始行字典（``{表头文本: 单元格文本}``）——列名
一旦漂移或补测出真实列名，具名字段取不到值时 :attr:`raw` 仍完整透传，不丢数据
（`dict` 兜底）。:class:`OrgRecord` 的社团目录部分则按实测列建。

解析风格沿用 :mod:`westlake_survival.sis.grades`：本模块只做「抓页 → 找网格
→ 列名归一 → 数据模型映射」，网络与通用网格解析委托 :mod:`...sis.pages`。
"""

from __future__ import annotations

import functools
import html as _html
import re
from dataclasses import dataclass, field

import click

from westlake_survival.exceptions import OffCampusError, ParseError, WestlakeError
from westlake_survival.sis import pages

__all__ = [
    # 贷款
    "LOAN_LIST_COMPONENT",
    "LOAN_LIST_QUERY",
    "LOAN_LIST_GRID_ID",
    "LOAN_OWN_COMPONENT",
    "LOAN_OWN_GRID_ID",
    "LOAN_REPAYMENT_COMPONENT",
    "LOAN_REPAYMENT_GRID_ID",
    "LoanRecord",
    "LoanRepayment",
    "loans",
    "loan_application",
    "loan_repayments",
    # 勤工助学
    "WORK_MENU_COMPONENT",
    "WORK_MENU_QUERY",
    "WORK_NAV_GRID_ID",
    "WORK_POSITIONS_COMPONENT",
    "WORK_POSITIONS_QUERY",
    "WORK_POSITIONS_GRID_ID",
    "StudyJob",
    "WorkStudyTab",
    "study_jobs",
    "work_study_tabs",
    "CLAIM_COMPONENT",
    "job_claim",
    # 海外交流
    "OUTBOUND_COMPONENT",
    "OUTBOUND_GRID_ID",
    "EXCHANGE_APPL_COMPONENT",
    "EXCHANGE_APPL_GRID_ID",
    "EXCHANGE_SCHOOL_COMPONENT",
    "EXCHANGE_SCHOOL_GRID_ID",
    "OutboundRecord",
    "ExchangeRecord",
    "ExchangeSchool",
    "outbound_programs",
    "exchange_applications",
    "exchange_schools",
    # 学生组织 / 活动
    "ORG_SUM_COMPONENT",
    "ORG_SUM_GRID_ID",
    "ORG_LIST_COMPONENT",
    "ORG_LIST_GRID_ID",
    "ACTIVITY_COMPONENT",
    "ACTIVITY_GRID_ID",
    "OrgRecord",
    "ActivityRecord",
    "student_orgs",
    "my_clubs",
    "student_activities",
    # CLI
    "cli_group",
]

# --------------------------------------------------------------------------- #
# 组件与网格常量（一律带 ``WL_CUSTOMIZE_MENU.`` 菜单前缀，见模块 docstring）
# --------------------------------------------------------------------------- #

#: 贷款列表页组件；查询串 ``NavColl=true``（实测可直达列表 fluid 页）。
LOAN_LIST_COMPONENT = "WL_CUSTOMIZE_MENU.WL_LOAN_LIST_COM.GBL"
LOAN_LIST_QUERY = "NavColl=true"
#: 贷款列表 fluid 网格 id（空页不渲染，取页内记录名 ``WL_LOAN_LIST_FL``）。
LOAN_LIST_GRID_ID = "WL_LOAN_LIST_FL"

#: 个人贷款页组件 / 网格 id。
LOAN_OWN_COMPONENT = "WL_CUSTOMIZE_MENU.WL_LOAN_OWN_COM.GBL"
LOAN_OWN_GRID_ID = "WL_LOAN_OWN_FL"

#: 还款页组件 / 网格 id。
LOAN_REPAYMENT_COMPONENT = "WL_CUSTOMIZE_MENU.WL_LOAN_REPAYM_FL.GBL"
LOAN_REPAYMENT_GRID_ID = "WL_LOAN_REPAYM_FL"

#: 勤工助学导航页组件与查询串（``page`` 为小写，实测有效）。
WORK_MENU_COMPONENT = "CHN_PACKAGE_CS.CHN_WORK_MD01.GBL"
WORK_MENU_QUERY = "page=CHN_WORK_MD01"
#: 勤工助学导航网格 id（4 个 tab，行内 ``ps-text`` 为标签）。
WORK_NAV_GRID_ID = "CHN_MD_NAV"

#: 勤工助学「My Work-Study Positions」子页组件 / 查询串 / 网格 id。
WORK_POSITIONS_COMPONENT = "CHN_PACKAGE_CS.CHN_STUAPL_LIST_FL.GBL"
WORK_POSITIONS_QUERY = "Page=CHN_STUAPL_LIST_FL&Action=U"
WORK_POSITIONS_GRID_ID = "CHN_STUAPL_LIST_FL"

#: 海外交流 Outbound 申请页组件 / 网格 id。
OUTBOUND_COMPONENT = "WL_CUSTOMIZE_MENU.WL_SAA_OTB_LIST_FL.GBL"
OUTBOUND_GRID_ID = "WL_SAA_OTB_LIST_FL"

#: Exchange 申请页组件 / 网格 id。
EXCHANGE_APPL_COMPONENT = "WL_CUSTOMIZE_MENU.WL_EXC_APPL_LIST.GBL"
EXCHANGE_APPL_GRID_ID = "WL_EXC_APPL_LIST_FL"

#: Exchange 院校列表页组件 / 网格 id。
EXCHANGE_SCHOOL_COMPONENT = "WL_CUSTOMIZE_MENU.WL_EXC_SCHOOL_COM.GBL"
EXCHANGE_SCHOOL_GRID_ID = "WL_EXC_SCHOOL_COM_FL"

#: 学生组织与社团目录页组件 / div 网格 id（实测 39 行，8 个分组）。
ORG_SUM_COMPONENT = "WL_CUSTOMIZE_MENU.WL_STU_ORG_SUM_FL.GBL"
ORG_SUM_GRID_ID = "WL_HR_DUMMY_REC"

#: 我的社团页组件 / fluid 网格 id（实测 2 行，表头 5 列）。
ORG_LIST_COMPONENT = "WL_CUSTOMIZE_MENU.WL_STU_ORG_LIST_FL.GBL"
ORG_LIST_GRID_ID = "WL_STU_ORG_TBL"

#: 社团活动页组件 / 网格 id。
ACTIVITY_COMPONENT = "WL_CUSTOMIZE_MENU.WL_STU_ACT_LIST_FL.GBL"
ACTIVITY_GRID_ID = "WL_STU_ACT_LIST_FL"

# --------------------------------------------------------------------------- #
# 空页识别与网格抽取
# --------------------------------------------------------------------------- #

#: 空记录页正文特征（小写子串匹配）。空页不渲染网格，需据此与「结构漂移」区分。
#: 2026-10-27 起界面语言为中文，补中文空页文案（实测逐句登录态核对）：
#: 贷款「您当前没有助贷申请。」、勤工助学「未查询到相应数据！」、
#: 海外交流 / Exchange「您(你)当前还没有申请…」、社团活动「当前没有活动报名…」
#: 「你还没有参与活动的记录…」。
_NO_DATA_MARKERS = (
    "you currently do not have a loan application",
    "you have not applied yet",
    "there is no data for the current query",
    "the current query has no data",
    "no data found",
    "there are currently no activity registrations",
    "you don't have a club yet",
    "您当前没有助贷申请",
    "未查询到相应数据",
    "当前还没有申请",
    "当前没有活动报名",
    "你还没有参与活动的记录",
    # 2026-10-27 实测：还款页空态文案（「没有结果」而不是「没有数据」）
    "当前查询没有结果",
)

#: PeopleSoft 网格数据行 id：``{grid_id}${group}_row_{row}``。
_ROW_ID_RE = re.compile(r"id=['\"]([A-Za-z0-9_]+)\$(\d+)_row_(\d+)['\"]")
#: ``ps-text`` 文本（导航 tab 标签、分组盒标题等）。
_PS_TEXT_RE = re.compile(r"<span class='ps-text'[^>]*>(.*?)</span>", re.S)
#: 锚文本（div 网格行里的社团名）。
_ANCHOR_RE = re.compile(r"<a\b[^>]*>(.*?)</a>", re.S)
#: ``LaunchURL`` 目标 URL（导航行点击跳转目标）。
_URL_RE = re.compile(r"LaunchURL\(\s*null\s*,\s*'([^']+)'")
#: 社团目录分组盒标题：``WL_STU_ORGM_WRK_GROUPBOX1$N`` → 标题文本。
_ORG_GROUPBOX_RE = re.compile(
    r"id='win3divWL_STU_ORGM_WRK_GROUPBOX1\$(\d+)'.*?"
    r"ps_header-group[^>]*>\s*<span class='ps-text'[^>]*>(.*?)</span>",
    re.S,
)
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(text: str) -> str:
    """去 HTML 标签并反转义实体，压缩首尾空白。"""
    return _html.unescape(_TAG_RE.sub("", text or "")).strip()


def _has_no_data_marker(html: str) -> bool:
    """正文是否含空记录页特征文案。"""
    low = (html or "").lower()
    return any(marker in low for marker in _NO_DATA_MARKERS)


def _data_grid_ids(html: str) -> list[str]:
    """按出现顺序返回页面里**有数据行**的网格 id（去重）。"""
    ids: list[str] = []
    for match in _ROW_ID_RE.finditer(html or ""):
        grid_id = match.group(1)
        if grid_id not in ids:
            ids.append(grid_id)
    return ids


def _grid_rows(html: str, grid_id: str) -> list[dict]:
    """解析 fluid 网格为行字典列表；空记录页优雅返回 ``[]``。

    先按 *grid_id* 解析；若页内该网格不存在但有*其它*数据行网格（列/网格漂移），
    退回第一个有数据的网格。两者都解析不到时：含空记录特征文案 → ``[]``；
    否则原样抛 :class:`~westlake_survival.exceptions.ParseError`（视为结构漂移，
    不静默吞掉）。
    """
    ids = _data_grid_ids(html)
    target = grid_id if grid_id in ids else (ids[0] if ids else grid_id)
    try:
        return pages.parse_fluid_grid(html, target)
    except ParseError:
        if _has_no_data_marker(html):
            return []
        raise


def _row_segments(html: str, grid_id: str) -> list[str]:
    """切出 *grid_id* 各数据行在 HTML 里的切片（供非表头网格逐行取值）。"""
    matches = list(_ROW_ID_RE.finditer(html or ""))
    segments: list[str] = []
    for index, match in enumerate(matches):
        if match.group(1) != grid_id:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(html)
        segments.append(html[match.start() : end])
    return segments


def _org_directory_rows(html: str) -> list[dict]:
    """解析「学生组织与社团」**div 网格**（``WL_HR_DUMMY_REC``）。

    PeopleSoft 该页把每个分组渲染成一个 ``ps_header-group`` 标题 + 一个
    ``ps_grid-row`` div 网格；分组盒与网格共用同一数字后缀
    （``...GROUPBOX1$N`` 对 ``WL_HR_DUMMY_REC$N``）。逐行取行内首个锚文本为
    社团名，按后缀映射到分组标题作为类别。无数据时返回 ``[]``。
    """
    titles = {num: _strip_tags(text) for num, text in _ORG_GROUPBOX_RE.findall(html or "")}
    rows: list[dict] = []
    for segment in _row_segments(html, ORG_SUM_GRID_ID):
        # 从行 id 里取分组后缀：``WL_HR_DUMMY_REC$N_row_M`` 的 N。
        suffix_match = re.search(
            rf"id=['\"]{re.escape(ORG_SUM_GRID_ID)}\$(\d+)_row_\d+['\"]", segment
        )
        anchor = _ANCHOR_RE.search(segment)
        name = _strip_tags(anchor.group(1)) if anchor else ""
        if not name:
            continue
        suffix = suffix_match.group(1) if suffix_match else ""
        rows.append({"category": titles.get(suffix, ""), "name": name})
    return rows


def _nav_tab_rows(html: str, grid_id: str) -> list[dict]:
    """解析「标签 + 跳转链接」型导航网格（无 ``<th>`` 表头）。

    用于勤工助学主页的 ``CHN_MD_NAV``：逐行取 ``ps-text`` 为标签、
    ``LaunchURL`` 首个字符串参数为目标 URL。无行时返回 ``[]``。
    """
    rows: list[dict] = []
    for segment in _row_segments(html, grid_id):
        text = _PS_TEXT_RE.search(segment)
        url = _URL_RE.search(segment)
        rows.append(
            {
                "name": _strip_tags(text.group(1)) if text else "",
                "url": url.group(1) if url else "",
            }
        )
    return rows


def _pick(row: dict, *keys: str) -> str:
    """按候选表头名依次取值，取到首个非空即返回（列名漂移兜底）。"""
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _models(rows: list[dict], build, page: str) -> list:
    """行字典 → 模型列表；「页面有数据行但具名字段全空」时抛 ParseError。

    2026-10-27 中文表头事故教训：表头语言切换后具名字段全部取空，
    ``raw`` 兜底虽有数据但 CLI 只显示「—」——静默空返回比报错更危险，
    故统一走 :func:`westlake_survival.sis.pages.assert_named_fields` 守卫。
    """
    models = [build(row) for row in rows]
    pages.assert_named_fields(
        rows, models, page=page, is_empty=pages.named_fields_empty
    )
    return models


# --------------------------------------------------------------------------- #
# 数据模型
# --------------------------------------------------------------------------- #
@dataclass
class LoanRecord:
    """一条贷款记录（列表页/申请页）。

    贷款页对当前账号为空页，**列名未实测**；具名字段按 PeopleSoft 命名习惯
    给出候选别名，取不到值时为空串，完整行字典保留在 :attr:`raw`。

    Attributes:
        loan_type: 贷款类型 / 名称。
        amount: 金额（文本，保留原样，不折算）。
        status: 状态 / 审批状态。
        apply_date: 申请日期。
        raw: 原始行字典 ``{表头文本: 单元格文本}``（列漂移兜底）。
    """

    loan_type: str = ""
    amount: str = ""
    status: str = ""
    apply_date: str = ""
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_row(cls, row: dict) -> "LoanRecord":
        """从 :func:`~westlake_survival.sis.pages.parse_fluid_grid` 的行字典构造。"""
        return cls(
            loan_type=_pick(row, "Loan Type", "Loan Name", "Type"),
            amount=_pick(row, "Loan Amount", "Amount", "Approved Amount"),
            status=_pick(row, "Application Status", "Status", "Approval Status"),
            apply_date=_pick(row, "Application Date", "Apply Date", "Date"),
            raw=dict(row),
        )

    def to_dict(self) -> dict:
        """转为可序列化字典（含 :attr:`raw`）。"""
        return {
            "loan_type": self.loan_type,
            "amount": self.amount,
            "status": self.status,
            "apply_date": self.apply_date,
            "raw": dict(self.raw),
        }


@dataclass
class LoanRepayment:
    """一条还款记录（还款页；列名未实测，同 :class:`LoanRecord` 兜底口径）。

    Attributes:
        period: 还款期次 / 学期。
        amount_due: 应还金额文本。
        amount_paid: 已还金额文本。
        due_date: 到期日 / 还款日。
        status: 还款状态。
        raw: 原始行字典（列漂移兜底）。
    """

    period: str = ""
    amount_due: str = ""
    amount_paid: str = ""
    due_date: str = ""
    status: str = ""
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_row(cls, row: dict) -> "LoanRepayment":
        """从行字典构造。"""
        return cls(
            period=_pick(row, "Period", "Term", "Installment", "Seq Nbr"),
            amount_due=_pick(row, "Amount Due", "Due Amount", "Repayment Amount"),
            amount_paid=_pick(row, "Amount Paid", "Paid Amount", "Repaid Amount"),
            due_date=_pick(row, "Due Date", "Repayment Date", "Date"),
            status=_pick(row, "Status", "Repayment Status"),
            raw=dict(row),
        )

    def to_dict(self) -> dict:
        """转为可序列化字典（含 :attr:`raw`）。"""
        return {
            "period": self.period,
            "amount_due": self.amount_due,
            "amount_paid": self.amount_paid,
            "due_date": self.due_date,
            "status": self.status,
            "raw": dict(self.raw),
        }


@dataclass
class StudyJob:
    """一条勤工助学岗位/工时/工资记录（子页对当前账号为空，列名未实测）。

    Attributes:
        position: 岗位名称。
        department: 用工部门 / 单位。
        hours: 工时文本。
        salary: 工资文本。
        status: 状态（如申请中 / 已录用）。
        raw: 原始行字典（列漂移兜底）。
    """

    position: str = ""
    department: str = ""
    hours: str = ""
    salary: str = ""
    status: str = ""
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_row(cls, row: dict) -> "StudyJob":
        """从行字典构造。"""
        return cls(
            position=_pick(row, "Position", "Position Name", "Job Title", "Job Name"),
            department=_pick(row, "Department", "Unit", "Employer", "Dept"),
            hours=_pick(row, "Hours", "Total Hours", "Work Hours"),
            salary=_pick(row, "Salary", "Wage", "Amount", "Pay"),
            status=_pick(row, "Status", "Application Status"),
            raw=dict(row),
        )

    def to_dict(self) -> dict:
        """转为可序列化字典（含 :attr:`raw`）。"""
        return {
            "position": self.position,
            "department": self.department,
            "hours": self.hours,
            "salary": self.salary,
            "status": self.status,
            "raw": dict(self.raw),
        }


@dataclass
class WorkStudyTab:
    """勤工助学主页的一个导航 tab（实测 4 个）。

    Attributes:
        name: tab 标签文本（如 ``My Work-Study Positions``）。
        url: tab 点击跳转的目标 URL。
    """

    name: str = ""
    url: str = ""

    @classmethod
    def from_row(cls, row: dict) -> "WorkStudyTab":
        """从 :func:`_nav_tab_rows` 的行字典构造。"""
        return cls(name=(row.get("name") or "").strip(), url=(row.get("url") or "").strip())

    def to_dict(self) -> dict:
        """转为可序列化字典。"""
        return {"name": self.name, "url": self.url}


@dataclass
class OutboundRecord:
    """一条 Outbound（海外交流派出）申请记录（空页，列名未实测）。

    Attributes:
        program: 项目 / 申请名称。
        country: 国家 / 地区。
        university: 接收院校。
        term: 交流学期。
        status: 申请状态。
        raw: 原始行字典（列漂移兜底）。
    """

    program: str = ""
    country: str = ""
    university: str = ""
    term: str = ""
    status: str = ""
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_row(cls, row: dict) -> "OutboundRecord":
        """从行字典构造。"""
        return cls(
            program=_pick(row, "Program", "Program Name", "Project", "Application"),
            country=_pick(row, "Country", "Country/Region", "Region"),
            university=_pick(row, "University", "Institution", "Host University"),
            term=_pick(row, "Term", "Academic Term", "Exchange Term"),
            status=_pick(row, "Status", "Application Status"),
            raw=dict(row),
        )

    def to_dict(self) -> dict:
        """转为可序列化字典（含 :attr:`raw`）。"""
        return {
            "program": self.program,
            "country": self.country,
            "university": self.university,
            "term": self.term,
            "status": self.status,
            "raw": dict(self.raw),
        }


@dataclass
class ExchangeRecord:
    """一条 Exchange（交换生）申请记录（空页，列名未实测）。

    Attributes:
        program: 项目名称。
        university: 申请院校。
        major: 专业方向。
        term: 交流学期。
        status: 申请状态。
        raw: 原始行字典（列漂移兜底）。
    """

    program: str = ""
    university: str = ""
    major: str = ""
    term: str = ""
    status: str = ""
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_row(cls, row: dict) -> "ExchangeRecord":
        """从行字典构造。"""
        return cls(
            program=_pick(row, "Program", "Program Name", "Application"),
            university=_pick(row, "University", "Institution", "Host University"),
            major=_pick(row, "Major", "UGRD Major", "Field of Study"),
            term=_pick(row, "Term", "Academic Term", "Exchange Term"),
            status=_pick(row, "Status", "Application Status"),
            raw=dict(row),
        )

    def to_dict(self) -> dict:
        """转为可序列化字典（含 :attr:`raw`）。"""
        return {
            "program": self.program,
            "university": self.university,
            "major": self.major,
            "term": self.term,
            "status": self.status,
            "raw": dict(self.raw),
        }


@dataclass
class ExchangeSchool:
    """Exchange 可选院校（院校列表页，实测空，列名未实测）。

    Attributes:
        university: 院校名称。
        country: 国家 / 地区。
        program: 关联项目（如有）。
        raw: 原始行字典（列漂移兜底）。
    """

    university: str = ""
    country: str = ""
    program: str = ""
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_row(cls, row: dict) -> "ExchangeSchool":
        """从行字典构造。"""
        return cls(
            university=_pick(row, "University", "Institution", "University Name"),
            country=_pick(row, "Country", "Country/Region", "Country Name"),
            program=_pick(row, "Program", "Program Name"),
            raw=dict(row),
        )

    def to_dict(self) -> dict:
        """转为可序列化字典（含 :attr:`raw`）。"""
        return {
            "university": self.university,
            "country": self.country,
            "program": self.program,
            "raw": dict(self.raw),
        }


@dataclass
class OrgRecord:
    """一条学生组织 / 社团记录，覆盖两个来源。

    - 组织目录（:func:`student_orgs`）：按实测列填 :attr:`category` + :attr:`name`；
    - 我的社团（:func:`my_clubs`）：按实测列填 :attr:`academic_year` /
      :attr:`club_name` / :attr:`founder` / :attr:`initiation_deadline` /
      :attr:`initiators`。

    Attributes:
        category: 目录分组类别（如 ``CULTURE AND SPORTS``）；来自「我的社团」时为空。
        name: 社团名称（目录来源）。
        academic_year: 学年；来自目录时为空。
        club_name: 社团名称（「我的社团」来源）。
        founder: 发起人。
        initiation_deadline: 发起截止日。
        initiators: 当前发起人数。
        raw: 原始行字典（列漂移兜底）。
    """

    category: str = ""
    name: str = ""
    academic_year: str = ""
    club_name: str = ""
    founder: str = ""
    initiation_deadline: str = ""
    initiators: str = ""
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_row(cls, row: dict) -> "OrgRecord":
        """从 :func:`~westlake_survival.sis.pages.parse_fluid_grid` 的行字典构造。

        表头随界面语言切换（2026-10-27 实测中文：学年 / 社团名称 / 负责人 /
        发起截止时间 / 当前发起人总数），两种写法都认。
        """
        return cls(
            academic_year=_pick(row, "Academic Year", "学年"),
            club_name=_pick(row, "Club Name", "社团名称"),
            founder=_pick(row, "Founder", "负责人"),
            initiation_deadline=_pick(row, "Initiation Deadline", "发起截止时间"),
            initiators=_pick(row, "Current Initiators Number", "当前发起人总数"),
            raw=dict(row),
        )

    @classmethod
    def from_directory_row(cls, row: dict) -> "OrgRecord":
        """从 :func:`_org_directory_rows` 的行字典构造（类别 + 名称）。"""
        return cls(
            category=(row.get("category") or "").strip(),
            name=(row.get("name") or "").strip(),
            raw=dict(row),
        )

    def to_dict(self) -> dict:
        """转为可序列化字典（含 :attr:`raw`）。"""
        return {
            "category": self.category,
            "name": self.name,
            "academic_year": self.academic_year,
            "club_name": self.club_name,
            "founder": self.founder,
            "initiation_deadline": self.initiation_deadline,
            "initiators": self.initiators,
            "raw": dict(self.raw),
        }


@dataclass
class ActivityRecord:
    """一条社团活动登记记录（空页，列名未实测）。

    Attributes:
        name: 活动名称。
        date: 活动日期 / 时间。
        location: 活动地点。
        status: 登记状态。
        raw: 原始行字典（列漂移兜底）。
    """

    name: str = ""
    date: str = ""
    location: str = ""
    status: str = ""
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_row(cls, row: dict) -> "ActivityRecord":
        """从行字典构造。"""
        return cls(
            name=_pick(row, "Activity", "Activity Name", "Name", "Club"),
            date=_pick(row, "Date", "Activity Date", "Time"),
            location=_pick(row, "Location", "Venue", "Place"),
            status=_pick(row, "Status", "Registration Status"),
            raw=dict(row),
        )

    def to_dict(self) -> dict:
        """转为可序列化字典（含 :attr:`raw`）。"""
        return {
            "name": self.name,
            "date": self.date,
            "location": self.location,
            "status": self.status,
            "raw": dict(self.raw),
        }


# --------------------------------------------------------------------------- #
# 查询函数
# --------------------------------------------------------------------------- #
def loans() -> list[LoanRecord]:
    """取贷款记录列表（列表页）。

    Returns:
        :class:`LoanRecord` 列表；空记录页返回空列表。

    Raises:
        AuthError: 会话失效。
        OffCampusError: 校外访问被拒。
        ActionError: 组件未授权。
        ParseError: 页面结构变化导致网格解析失败（非空页）。
    """
    html = pages.fetch_page(LOAN_LIST_COMPONENT, query=LOAN_LIST_QUERY)
    return _models(
        _grid_rows(html, LOAN_LIST_GRID_ID), LoanRecord.from_row, "贷款记录"
    )


def loan_application() -> list[LoanRecord]:
    """取个人贷款申请记录（申请页）。

    Returns:
        :class:`LoanRecord` 列表；空记录页返回空列表。
    """
    html = pages.fetch_page(LOAN_OWN_COMPONENT)
    return _models(
        _grid_rows(html, LOAN_OWN_GRID_ID), LoanRecord.from_row, "贷款申请"
    )


def loan_repayments() -> list[LoanRepayment]:
    """取还款记录（还款页）。

    Returns:
        :class:`LoanRepayment` 列表；空记录页返回空列表。
    """
    html = pages.fetch_page(LOAN_REPAYMENT_COMPONENT)
    return _models(
        _grid_rows(html, LOAN_REPAYMENT_GRID_ID),
        LoanRepayment.from_row,
        "还款记录",
    )


def work_study_tabs() -> list[WorkStudyTab]:
    """取勤工助学主页的导航 tab（实测 4 个：岗位/工时/工资等入口）。

    Returns:
        :class:`WorkStudyTab` 列表；无导航行时为空列表。
    """
    html = pages.fetch_page(WORK_MENU_COMPONENT, query=WORK_MENU_QUERY)
    return [WorkStudyTab.from_row(row) for row in _nav_tab_rows(html, WORK_NAV_GRID_ID)]


def study_jobs() -> list[StudyJob]:
    """取勤工助学岗位/工时/工资记录（「My Work-Study Positions」子页）。

    Returns:
        :class:`StudyJob` 列表；空记录页（实测当前账号如此）返回空列表。
    """
    html = pages.fetch_page(WORK_POSITIONS_COMPONENT, query=WORK_POSITIONS_QUERY)
    return _models(
        _grid_rows(html, WORK_POSITIONS_GRID_ID), StudyJob.from_row, "勤工助学"
    )


#: 工时申报页组件（``CHN_PACKAGE`` 菜单，2026-10-24 实测）。
CLAIM_COMPONENT = "CHN_PACKAGE_CS.CHN_SW_CLAIM_LIST.GBL"

#: 工时申报页空态提示（无岗位时整页仅此一句，无网格；在去标签前匹配，
#: 以 ``<`` / 句终符截断避免吃到后续脚本/页脚文本）。2026-10-27 实测中文
#: 空页文案：「你还没有勤工俭学被录用的岗位信息！」。
_CLAIM_EMPTY_RE = re.compile(
    r"(You haven't got a job yet\.|No Data[^<]{0,60}|你还没有勤工俭学[^<。！]{0,40}[。！])"
)


def job_claim() -> dict:
    """取工时申报状态（有无勤工助学岗位）。

    Returns:
        ``{"notice": 提示句}``；2026-10-24 实测当前账号无岗位，提示
        ``You haven't got a job yet.``（页面另有学号/性别/学院等基本信息头，
        与 SIS 个人信息重复，不重复抽取）。有岗位时应为申报网格，届时按需
        扩展。

    Raises:
        AuthError: 会话失效。
        OffCampusError: 校外访问被拒。
        ActionError: 工时组件未授权。
    """
    html = pages.fetch_page(CLAIM_COMPONENT)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    match = _CLAIM_EMPTY_RE.search(text)
    return {"notice": match.group(1).strip() if match else ""}


def outbound_programs() -> list[OutboundRecord]:
    """取 Outbound（海外交流派出）申请记录。

    Returns:
        :class:`OutboundRecord` 列表；空记录页返回空列表。
    """
    html = pages.fetch_page(OUTBOUND_COMPONENT)
    return _models(
        _grid_rows(html, OUTBOUND_GRID_ID), OutboundRecord.from_row, "Outbound 申请"
    )


def exchange_applications() -> list[ExchangeRecord]:
    """取 Exchange（交换生）申请记录。

    Returns:
        :class:`ExchangeRecord` 列表；空记录页返回空列表。
    """
    html = pages.fetch_page(EXCHANGE_APPL_COMPONENT)
    return _models(
        _grid_rows(html, EXCHANGE_APPL_GRID_ID), ExchangeRecord.from_row, "Exchange 申请"
    )


def exchange_schools() -> list[ExchangeSchool]:
    """取 Exchange 可选院校列表。

    Returns:
        :class:`ExchangeSchool` 列表；空记录页返回空列表。
    """
    html = pages.fetch_page(EXCHANGE_SCHOOL_COMPONENT)
    return _models(
        _grid_rows(html, EXCHANGE_SCHOOL_GRID_ID),
        ExchangeSchool.from_row,
        "Exchange 院校",
    )


def student_orgs() -> list[OrgRecord]:
    """取学生组织与社团**目录**（按分组类别，实测 39 行 / 8 类）。

    Returns:
        :class:`OrgRecord` 列表（填 ``category`` + ``name``）；无数据时为空列表。
    """
    html = pages.fetch_page(ORG_SUM_COMPONENT)
    return [OrgRecord.from_directory_row(row) for row in _org_directory_rows(html)]


def my_clubs() -> list[OrgRecord]:
    """取「我的社团」列表（fluid 网格 ``WL_STU_ORG_TBL``，实测 2 行 / 5 列）。

    Returns:
        :class:`OrgRecord` 列表（填 ``academic_year`` 等具名实测列）；空记录页为空列表。
    """
    html = pages.fetch_page(ORG_LIST_COMPONENT)
    return _models(_grid_rows(html, ORG_LIST_GRID_ID), OrgRecord.from_row, "我的社团")


def student_activities() -> list[ActivityRecord]:
    """取社团活动登记记录。

    Returns:
        :class:`ActivityRecord` 列表；空记录页返回空列表。
    """
    html = pages.fetch_page(ACTIVITY_COMPONENT)
    return _models(
        _grid_rows(html, ACTIVITY_GRID_ID), ActivityRecord.from_row, "社团活动"
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


@click.group(
    name="aid",
    help="学生资助 / 海外交流 / 社团：贷款、勤工助学、交流申请、社团组织与活动。",
)
def cli_group() -> None:
    """``westlake aid`` 命令组（注册见后续 cli.main 改动）。"""


def _table(rows: list[tuple], headers: tuple, empty: str) -> None:
    """打印对齐表格（``_print_table`` 惰性导入以免循环依赖）；无行时提示 *empty*。"""
    from westlake_survival.cli.main import _print_table

    if not rows:
        click.echo(empty)
        return
    _print_table(rows, headers)


@cli_group.command(name="loans")
@_handle_errors
def aid_loans() -> None:
    """列出贷款记录。"""
    items = loans()
    _table(
        [
            (r.loan_type or "—", r.amount or "—", r.status or "—", r.apply_date or "—")
            for r in items
        ],
        ("类型", "金额", "状态", "申请日期"),
        "没有贷款记录。",
    )


@cli_group.command(name="jobs")
@_handle_errors
def aid_jobs() -> None:
    """列出勤工助学岗位/工时/工资记录。"""
    items = study_jobs()
    _table(
        [
            (
                r.position or "—",
                r.department or "—",
                r.hours or "—",
                r.salary or "—",
                r.status or "—",
            )
            for r in items
        ],
        ("岗位", "部门", "工时", "工资", "状态"),
        "没有勤工助学记录。",
    )


@cli_group.command(name="claim")
@_handle_errors
def aid_claim() -> None:
    """显示工时申报状态（有无岗位）。"""
    click.echo(job_claim()["notice"] or "未获取到提示")


@cli_group.command(name="outbound")
@_handle_errors
def aid_outbound() -> None:
    """列出 Outbound（海外交流派出）申请记录。"""
    items = outbound_programs()
    _table(
        [
            (
                r.program or "—",
                r.country or "—",
                r.university or "—",
                r.term or "—",
                r.status or "—",
            )
            for r in items
        ],
        ("项目", "国家/地区", "院校", "学期", "状态"),
        "没有 Outbound 申请记录。",
    )


@cli_group.command(name="exchange")
@_handle_errors
def aid_exchange() -> None:
    """列出 Exchange（交换生）申请记录。"""
    items = exchange_applications()
    _table(
        [
            (
                r.program or "—",
                r.university or "—",
                r.major or "—",
                r.term or "—",
                r.status or "—",
            )
            for r in items
        ],
        ("项目", "院校", "专业", "学期", "状态"),
        "没有 Exchange 申请记录。",
    )


@cli_group.command(name="orgs")
@click.option("--wiki", "with_wiki", is_flag=True, help="附 WikiLake 社区简介（学生自建百科，摘要）。")
@_handle_errors
def aid_orgs(with_wiki: bool = False) -> None:
    """列出学生组织与社团目录（按分组类别）。"""
    items = student_orgs()
    _table(
        [(r.category or "—", r.name or "—") for r in items],
        ("类别", "社团/组织"),
        "没有学生组织数据。",
    )
    from westlake_survival import clubwiki

    matched = [row for row in clubwiki.annotate(items) if row.get("wiki_summary")]
    if not matched:
        return
    if not with_wiki:
        click.echo(f"提示：{len(matched)} 个社团有 WikiLake 社区简介，加 --wiki 查看。")
        return
    meta = clubwiki.catalog()["meta"]
    click.echo(f"\nWikiLake 社区简介（{meta.get('source', '')}，摘要改写，版权归其贡献者）：")
    for row in matched:
        name = row.get("name") or row.get("club_name") or "—"
        click.echo(f"- {name}：{row['wiki_summary']}")
        click.echo(f"  原文：{row['wiki_url']}")


@cli_group.command(name="activities")
@_handle_errors
def aid_activities() -> None:
    """列出社团活动登记记录。"""
    items = student_activities()
    _table(
        [
            (r.name or "—", r.date or "—", r.location or "—", r.status or "—")
            for r in items
        ],
        ("活动", "日期", "地点", "状态"),
        "没有社团活动记录。",
    )
