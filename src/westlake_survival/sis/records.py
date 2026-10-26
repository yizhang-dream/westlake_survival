"""SIS 学生事务记录页读取：住宿 / 请假 / 荣誉 / 志愿服务 / 社会实践 / 违纪。

本模块把六类「学生自助」组件页解析为数据模型，全部走共享读取层
:mod:`westlake_survival.sis.pages`（登录态抓页 + fluid 网格解析）。只做只读
``GET``；住宿页上的 *Apply for Dormitory Transfer* / *Leaving Dormitory* 等
**动作按钮绝不点击**。

实测结构（2026-09-23 登录态逐页确认）
=====================================
.. list-table::
   :header-rows: 1

   * - 函数 / 页面
     - 组件（``WL_CUSTOMIZE_MENU.`` 前缀）
     - 网格 id / 列
     - 实况
   * - :func:`dormitory`
     - ``WL_SA3_DORM_SELF.GBL?page=WL_SA3_DORM_SELF``
     - ``WL_SA3_DORM_VW``：Application No. / Application Type / Apply Reason /
       Date/Time / Status / View Detail
     - 3 行申请记录；另有宿舍信息区（label-value，键 ``On Campus Dormitory``）
   * - :func:`leave_requests`
     - ``WL_LEV_REQ_LIST_FL.GBL``
     - 未渲染（用户 0 条记录）
     - **空数据**；页内字段 ``Term`` / ``Accumulated leave days``
   * - :func:`honors`
     - ``WL_STUHON_HP_COM.GBL?page=WL_STUHON_HP_COM``
     - 未渲染（无数据；页内出现字段线索 ``WL_HON_PRJ_VW_WL_SA_HONOR_NAME``）
     - **空数据**；显示 *I haven't received any honors yet...*
   * - :func:`volunteer_records`
     - ``WL_VOL_MYSELF_COM.GBL?page=WL_VOL_MYSELF_COM``
     - ``WL_VOL_COM_VW``：Selected / Year / Voluntary Service NBR /
       Service Name / Status / Activity Time / Maximum Number Of  Hour
     - 4 行；页内 ``Total Duration``（label-value）与学年控件
       ``WL_VOL_WRK_WL_ACAD_YEAR``
   * - :func:`social_practice`
     - ``WL_SA_SCPRA_SELF.GBL?page=WL_SA_SCPRA_SELF``
     - 未渲染（页面提示「社会实践尚未开放」）
     - **空数据**
   * - :func:`discipline_records`
     - ``WL_DSC_STU_LIST_FL.GBL?page=WL_DSC_STU_LIST_FL``
     - 未渲染（无数据）
     - **空数据**；显示 *You currently have no disciplinary information.*

关键坑位
========
- **组件名必须带 ``WL_CUSTOMIZE_MENU.`` 前缀**：实测直接用裸组件名
  （如 ``WL_VOL_MYSELF_COM.GBL``）会被 SIS 判为 *not authorized*，加上
  ``WL_CUSTOMIZE_MENU.`` 前缀后才可访问（对照成绩页
  ``WL_CUSTOMIZE_MENU.WL_STU_GRADE_COM.GBL`` 同款）。
- **空数据页不渲染网格**：用户暂无记录时，PeopleSoft 根本不输出 ``$grid$``
  容器（不是输出空表），故「找不到网格」= 无记录，返回空列表而非报错。
  仅当**已知网格 id 出现在页面里**却解析失败（缺表头等）才视为结构变化并抛
  :class:`~westlake_survival.exceptions.ParseError`。
- **列名可漂移的页用 ``raw`` dict 兜底**：请假 / 荣誉 / 社会实践 / 违纪四页
  当前无数据、真实列名未实测，数据模型保留 ``raw``（原始「表头→值」字典），
  并对常见列名做候选匹配；将来站点改列名时 ``raw`` 仍可拿到全量字段。
- 网格容器 id 形如 ``win3div{GRID}$grid$N``；对无实测网格 id 的页面，
  :func:`_grid_rows` 会扫描页面内任意以 ``_VW`` 结尾的 fluid 网格容器。
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field

import click

from westlake_survival.exceptions import OffCampusError, WestlakeError
from westlake_survival.sis import pages

__all__ = [
    # 住宿
    "DORM_COMPONENT",
    "DORM_QUERY",
    "DORM_GRID_ID",
    "DormApplication",
    "DormRecord",
    "dormitory",
    # 请假
    "LEAVE_COMPONENT",
    "LeaveRequest",
    "leave_requests",
    # 荣誉
    "HONORS_COMPONENT",
    "HONORS_QUERY",
    "HONORS_GRID_ID",
    "HonorRecord",
    "honors",
    # 志愿服务
    "VOLUNTEER_COMPONENT",
    "VOLUNTEER_QUERY",
    "VOLUNTEER_GRID_ID",
    "VolunteerRecord",
    "volunteer_records",
    # 社会实践
    "PRACTICE_COMPONENT",
    "PRACTICE_QUERY",
    "PracticeRecord",
    "social_practice",
    # 违纪
    "DISCIPLINE_COMPONENT",
    "DISCIPLINE_QUERY",
    "DisciplineRecord",
    "discipline_records",
    # 志愿服务历史
    "VOL_HISTORY_COMPONENT",
    "VOL_HISTORY_GRID_ID",
    "VolunteerHistoryEntry",
    "VolunteerHistory",
    "volunteer_history",
    # 学期注册缴费
    "REGISTRATION_COMPONENT",
    "RegistrationStatus",
    "registration",
    # 心理健康预约
    "APPOINTMENT_COMPONENT",
    "AppointmentSlot",
    "Appointments",
    "appointments",
    # 离校 / 生源状态
    "LEAVING_CHECK_COMPONENT",
    "SOURCE_INFO_COMPONENT",
    "leaving_check",
    "source_info_status",
    # CLI
    "cli_group",
]

# --------------------------------------------------------------------------- #
# 组件 / 网格常量（实测）
# --------------------------------------------------------------------------- #
#: 住宿页组件（含 ``WL_CUSTOMIZE_MENU.`` 前缀，下同）。
DORM_COMPONENT = "WL_CUSTOMIZE_MENU.WL_SA3_DORM_SELF.GBL"
#: 住宿页查询串。
DORM_QUERY = "page=WL_SA3_DORM_SELF"
#: 住宿申请记录网格 id。
DORM_GRID_ID = "WL_SA3_DORM_VW"

#: 请假申请列表组件（实测无查询串）。
LEAVE_COMPONENT = "WL_CUSTOMIZE_MENU.WL_LEV_REQ_LIST_FL.GBL"

#: 荣誉主页组件。
HONORS_COMPONENT = "WL_CUSTOMIZE_MENU.WL_STUHON_HP_COM.GBL"
#: 荣誉页查询串。
HONORS_QUERY = "page=WL_STUHON_HP_COM"
#: 荣誉网格 id（无数据未实测，取自页内字段线索 ``WL_HON_PRJ_VW_...``）。
HONORS_GRID_ID = "WL_HON_PRJ_VW"

#: 志愿服务页组件。
VOLUNTEER_COMPONENT = "WL_CUSTOMIZE_MENU.WL_VOL_MYSELF_COM.GBL"
#: 志愿服务页查询串。
VOLUNTEER_QUERY = "page=WL_VOL_MYSELF_COM"
#: 志愿服务网格 id。
VOLUNTEER_GRID_ID = "WL_VOL_COM_VW"

#: 社会实践页组件。
PRACTICE_COMPONENT = "WL_CUSTOMIZE_MENU.WL_SA_SCPRA_SELF.GBL"
#: 社会实践页查询串。
PRACTICE_QUERY = "page=WL_SA_SCPRA_SELF"

#: 违纪信息页组件。
DISCIPLINE_COMPONENT = "WL_CUSTOMIZE_MENU.WL_DSC_STU_LIST_FL.GBL"
#: 违纪信息页查询串。
DISCIPLINE_QUERY = "page=WL_DSC_STU_LIST_FL"

#: fluid 网格容器 id 特征：``{前缀}{GRID}$grid${N}``。
_GRID_CONTAINER_RE = re.compile(r"id=['\"]([A-Za-z0-9_]+)\$grid\$\d+['\"]")

#: 网格容器 id 前缀（PeopleSoft 渲染时加在组件 id 前）。
_GRID_CONTAINER_PREFIX = "win3div"


# --------------------------------------------------------------------------- #
# 解析辅助
# --------------------------------------------------------------------------- #
def _grid_container_id(raw_id: str) -> str:
    """从元素 id 还原网格 id：去掉 PeopleSoft 的 ``win3div`` 前缀。"""
    if raw_id.startswith(_GRID_CONTAINER_PREFIX):
        return raw_id[len(_GRID_CONTAINER_PREFIX) :]
    return raw_id


def _first_fluid_grid_id(html: str) -> str | None:
    """扫描页面内第一个 fluid 网格 id（``_VW`` 结尾）。

    用于列/网格 id 未实测的页面（请假 / 荣誉 / 社会实践 / 违纪）：这些页在
    有记录时才会渲染网格。识别两类形态：

    1. 容器 ``win3div{GRID}$grid$N``（PeopleSoft fluid 网格容器）；
    2. 元素 id 恰为 ``{GRID}`` 且以 ``_VW`` 结尾（简化页 / 测试构造）。

    字段 id（如 ``WL_HON_PRJ_VW_WL_SA_HONOR_NAME``）不以 ``_VW`` 结尾，不会
    误判。找不到返回 ``None``（即无记录）。
    """
    for match in _GRID_CONTAINER_RE.finditer(html or ""):
        grid_id = _grid_container_id(match.group(1))
        if grid_id.endswith("_VW"):
            return grid_id
    for match in re.finditer(r"id=['\"]([A-Za-z0-9_]+)['\"]", html or ""):
        grid_id = _grid_container_id(match.group(1))
        if grid_id.endswith("_VW"):
            return grid_id
    return None


def _is_rendered_grid(html: str, grid_id: str) -> bool:
    """页面是否真的渲染了网格 *grid_id* 的 fluid 容器。

    仅凭 ``grid_id in html`` 不可靠：字段 id（如 ``WL_HON_PRJ_VW_...``）会以
    子串形式命中。故要求出现真正的网格容器 ``{前缀}{grid_id}$grid$N``、数据行
    id ``{grid_id}$N_row_M``，或元素 id 恰等于 *grid_id*。
    """
    if not grid_id:
        return False
    if re.search(
        rf"id=['\"][A-Za-z0-9_]*{re.escape(grid_id)}\$grid\$\d+['\"]", html
    ):
        return True
    if re.search(rf"id=['\"]{re.escape(grid_id)}\$\d+_row_\d+['\"]", html):
        return True
    return bool(re.search(rf"id=['\"]{re.escape(grid_id)}['\"]", html))


def _grid_rows(html: str, *candidates: str) -> list[dict]:
    """取页面的数据行：优先按候选网格 id，退回扫描任一 ``_VW`` 网格容器。

    - 候选网格 id 已渲染（:func:`_is_rendered_grid`）：按它解析（缺表头等
      结构问题会抛 ``ParseError``）；
    - 否则扫描页面内任意 ``_VW`` fluid 网格容器并解析；
    - 都没有：返回 ``[]``（**无记录页不渲染网格**，属正常空数据）。
    """
    for grid_id in candidates:
        if _is_rendered_grid(html, grid_id):
            return pages.parse_fluid_grid(html, grid_id)
    scanned = _first_fluid_grid_id(html)
    if scanned:
        return pages.parse_fluid_grid(html, scanned)
    return []


def _pick(row: dict, *keys: str) -> str:
    """按候选列名依次取值（去空白）；全部缺失/为空返回空串。"""
    for key in keys:
        value = row.get(key)
        if value:
            return value.strip()
    return ""


def _row_non_empty(row: dict) -> bool:
    """行是否含任一非空单元格（过滤站点残留空行）。"""
    return any((value or "").strip() for value in row.values())


def _rows_to_models(rows, build, *, page: str) -> list:
    """把行字典列表经 ``build`` 映射为模型，跳过全空行。

    「页面有数据行但所有模型具名字段全空」时抛 ``ParseError``（表头可能
    又变了）——2026-10-27 中文表头事故的教训：只匹配英文表头时真实数据行
    全被当空行，命令静默输出「—」，比报错更危险。守卫统一走
    :func:`westlake_survival.sis.pages.assert_named_fields`。
    """
    result = []
    for row in rows:
        if not _row_non_empty(row):
            continue
        result.append(build(row))
    pages.assert_named_fields(
        rows, result, page=page, is_empty=pages.named_fields_empty
    )
    return result


# --------------------------------------------------------------------------- #
# 住宿
# --------------------------------------------------------------------------- #
@dataclass
class DormApplication:
    """一条住宿申请记录（实测网格 ``WL_SA3_DORM_VW``）。

    Attributes:
        application_no: 申请号（如 ``000002422``）。
        application_type: 申请类型（如 ``Vacation Stay Application``）。
        reason: 申请理由（实测为中文自由文本）。
        date_time: 提交时间文本（如 ``2026/07/05 21:41:19``）。
        status: 审批状态（如 ``Passed``）。
        raw: 原始「表头 → 值」字典，列名漂移时的兜底。
    """

    application_no: str = ""
    application_type: str = ""
    reason: str = ""
    date_time: str = ""
    status: str = ""
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """转为可序列化字典。"""
        return {
            "application_no": self.application_no,
            "application_type": self.application_type,
            "reason": self.reason,
            "date_time": self.date_time,
            "status": self.status,
            "raw": dict(self.raw),
        }

    @classmethod
    def from_row(cls, row: dict) -> "DormApplication":
        """从行字典构造（表头双语：2026-10-27 实测中文表头为
        ``申请号 / 申请类型 / 申请原因 / 申请提交时间 / 状态``）。"""
        return cls(
            application_no=_pick(
                row, "Application No.", "Application Nbr", "申请号"
            ),
            application_type=_pick(
                row, "Application Type", "Type", "申请类型"
            ),
            reason=_pick(row, "Apply Reason", "Reason", "申请原因"),
            date_time=_pick(
                row, "Date/Time", "Date Time", "Date", "申请提交时间"
            ),
            status=_pick(row, "Status", "状态"),
            raw=dict(row),
        )


@dataclass
class DormRecord:
    """住宿页整体信息：申请记录列表 + 宿舍信息字典。

    Attributes:
        applications: 住宿申请记录（无记录时为空列表）。
        info: 宿舍信息「标签 → 值」字典（实测键 ``On Campus Dormitory``，
            值形如 ``<校区>-<书院>-<楼>-<房>``（示例已脱敏））。键集合由站点
            决定、可能漂移，故用 dict 承载而非固定字段。
    """

    applications: list = field(default_factory=list)
    info: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """转为可序列化字典。"""
        return {
            "applications": [a.to_dict() for a in self.applications],
            "info": dict(self.info),
        }


def dormitory() -> DormRecord:
    """取住宿信息（申请记录列表 + 宿舍信息字典）。

    只读 ``GET``；住宿页上的 *Apply for Dormitory Transfer* /
    *Leaving Dormitory* 等动作按钮**不会被触发**。

    Returns:
        :class:`DormRecord`；无申请记录时 ``applications`` 为空列表，
        宿舍信息区为空时 ``info`` 为空字典。

    Raises:
        AuthError: 会话失效。
        OffCampusError: 校外访问被拒。
        ActionError: 住宿组件未授权。
        ParseError: 已渲染的申请网格结构变化（缺表头等）。
    """
    html = pages.fetch_page(DORM_COMPONENT, query=DORM_QUERY)
    rows = _grid_rows(html, DORM_GRID_ID)
    applications = _rows_to_models(rows, DormApplication.from_row, page="住宿申请")
    info = pages.parse_label_values(html)
    return DormRecord(applications=applications, info=info)


# --------------------------------------------------------------------------- #
# 请假
# --------------------------------------------------------------------------- #
@dataclass
class LeaveRequest:
    """一条请假申请（实测用户无记录，真实列名未确认）。

    Attributes:
        application_no: 申请单号。
        leave_type: 请假类型。
        start: 开始时间文本。
        end: 结束时间文本。
        reason: 请假事由。
        status: 审批状态。
        raw: 原始「表头 → 值」字典；列名漂移时据此兜底（**列名未实测**，
            字段匹配按常见候选键进行，取不到即空串，不影响 ``raw`` 完整性）。
    """

    application_no: str = ""
    leave_type: str = ""
    start: str = ""
    end: str = ""
    reason: str = ""
    status: str = ""
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """转为可序列化字典。"""
        return {
            "application_no": self.application_no,
            "leave_type": self.leave_type,
            "start": self.start,
            "end": self.end,
            "reason": self.reason,
            "status": self.status,
            "raw": dict(self.raw),
        }

    @classmethod
    def from_row(cls, row: dict) -> "LeaveRequest":
        """从行字典构造（列名未实测，用候选键匹配 + ``raw`` 兜底）。"""
        return cls(
            application_no=_pick(
                row, "Application No.", "Leave Nbr", "Request Nbr", "Application Nbr"
            ),
            leave_type=_pick(row, "Leave Type", "Type", "Apply Type"),
            start=_pick(row, "Start Date", "From Date", "Begin Date", "Start Time"),
            end=_pick(row, "End Date", "To Date", "End Time"),
            reason=_pick(row, "Reason", "Apply Reason", "Leave Reason"),
            status=_pick(row, "Status", "Approval Status"),
            raw=dict(row),
        )


def leave_requests() -> list[LeaveRequest]:
    """取请假申请列表。

    Returns:
        :class:`LeaveRequest` 列表；用户无请假记录时为空列表（实测页面
        不渲染网格，属正常空数据）。

    Raises:
        AuthError: 会话失效。
        OffCampusError: 校外访问被拒。
        ActionError: 请假组件未授权。
        ParseError: 已渲染的申请网格结构变化（缺表头等）。
    """
    html = pages.fetch_page(LEAVE_COMPONENT)
    return _rows_to_models(_grid_rows(html), LeaveRequest.from_row, page="请假申请")


# --------------------------------------------------------------------------- #
# 荣誉
# --------------------------------------------------------------------------- #
@dataclass
class HonorRecord:
    """一条荣誉记录（实测用户暂无荣誉，真实列名未确认）。

    Attributes:
        name: 荣誉名称。
        level: 荣誉级别（校级 / 院级等）。
        date: 获得日期文本。
        status: 状态。
        raw: 原始「表头 → 值」字典；列名漂移时兜底。
    """

    name: str = ""
    level: str = ""
    date: str = ""
    status: str = ""
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """转为可序列化字典。"""
        return {
            "name": self.name,
            "level": self.level,
            "date": self.date,
            "status": self.status,
            "raw": dict(self.raw),
        }

    @classmethod
    def from_row(cls, row: dict) -> "HonorRecord":
        """从行字典构造（列名未实测，用候选键匹配 + ``raw`` 兜底）。"""
        return cls(
            name=_pick(row, "Honor Name", "Honorary Title", "Name", "WL_SA_HONOR_NAME"),
            level=_pick(row, "Honor Level", "Level", "Honor Type"),
            date=_pick(row, "Award Date", "Date", "Get Date"),
            status=_pick(row, "Status"),
            raw=dict(row),
        )


def honors() -> list[HonorRecord]:
    """取荣誉记录列表。

    Returns:
        :class:`HonorRecord` 列表；暂无荣誉时为空列表（实测页面显示
        *I haven't received any honors yet...* 且不渲染网格）。

    Raises:
        AuthError: 会话失效。
        OffCampusError: 校外访问被拒。
        ActionError: 荣誉组件未授权。
        ParseError: 已渲染的荣誉网格结构变化（缺表头等）。
    """
    html = pages.fetch_page(HONORS_COMPONENT, query=HONORS_QUERY)
    return _rows_to_models(
        _grid_rows(html, HONORS_GRID_ID), HonorRecord.from_row, page="荣誉记录"
    )


# --------------------------------------------------------------------------- #
# 志愿服务
# --------------------------------------------------------------------------- #
@dataclass
class VolunteerRecord:
    """一条志愿服务记录（实测网格 ``WL_VOL_COM_VW``）。

    Attributes:
        selected: 勾选列文本（通常为空）。
        year: 学年（如 ``2025``）。
        number: 志愿服务编号（如 ``000000660``）。
        name: 服务名称（可能为字面量 ``NULL``，站点原样给出，本模块不改写）。
        status: 状态（如 ``Have Finished``）。
        activity_time: 活动时间文本（如 ``2026-06-12 13.00to2026-06-14 19.00``）。
        hours: 时长文本（列名实测为 ``Maximum Number Of  Hour``，注意双空格）。
        raw: 原始「表头 → 值」字典，列名漂移时的兜底。
    """

    selected: str = ""
    year: str = ""
    number: str = ""
    name: str = ""
    status: str = ""
    activity_time: str = ""
    hours: str = ""
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """转为可序列化字典。"""
        return {
            "selected": self.selected,
            "year": self.year,
            "number": self.number,
            "name": self.name,
            "status": self.status,
            "activity_time": self.activity_time,
            "hours": self.hours,
            "raw": dict(self.raw),
        }

    @classmethod
    def from_row(cls, row: dict) -> "VolunteerRecord":
        """从行字典构造（表头双语：2026-10-27 实测中文表头为
        ``已选择 / 学年 / 志愿服务编号 / 志愿服务名称 / 当前状态 /
        志愿服务日期 / 志愿服务时数``）。"""
        return cls(
            selected=_pick(row, "Selected", "已选择"),
            year=_pick(row, "Year", "Academic Year", "学年"),
            number=_pick(
                row, "Voluntary Service NBR", "Service Nbr", "志愿服务编号"
            ),
            name=_pick(
                row, "Service Name", "Volunteer Service Name", "志愿服务名称"
            ),
            status=_pick(row, "Status", "当前状态"),
            activity_time=_pick(row, "Activity Time", "志愿服务日期"),
            hours=_pick(
                row,
                "Maximum Number Of  Hour",
                "Maximum Number Of Hour",
                "Hours",
                "志愿服务时数",
            ),
            raw=dict(row),
        )


def volunteer_records() -> list[VolunteerRecord]:
    """取志愿服务记录列表。

    Returns:
        :class:`VolunteerRecord` 列表；无记录时为空列表。

    Raises:
        AuthError: 会话失效。
        OffCampusError: 校外访问被拒。
        ActionError: 志愿服务组件未授权。
        ParseError: 已渲染的网格结构变化（缺表头等）。
    """
    html = pages.fetch_page(VOLUNTEER_COMPONENT, query=VOLUNTEER_QUERY)
    return _rows_to_models(
        _grid_rows(html, VOLUNTEER_GRID_ID), VolunteerRecord.from_row, page="志愿服务"
    )


# --------------------------------------------------------------------------- #
# 社会实践
# --------------------------------------------------------------------------- #
@dataclass
class PracticeRecord:
    """一条社会实践记录（实测页面提示「社会实践尚未开放」，真实列名未确认）。

    Attributes:
        title: 实践项目名称。
        organization: 组织 / 单位。
        start: 开始时间文本。
        end: 结束时间文本。
        hours: 时长文本。
        status: 状态。
        raw: 原始「表头 → 值」字典；列名漂移时兜底。
    """

    title: str = ""
    organization: str = ""
    start: str = ""
    end: str = ""
    hours: str = ""
    status: str = ""
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """转为可序列化字典。"""
        return {
            "title": self.title,
            "organization": self.organization,
            "start": self.start,
            "end": self.end,
            "hours": self.hours,
            "status": self.status,
            "raw": dict(self.raw),
        }

    @classmethod
    def from_row(cls, row: dict) -> "PracticeRecord":
        """从行字典构造（列名未实测，用候选键匹配 + ``raw`` 兜底）。"""
        return cls(
            title=_pick(row, "Practice Name", "Project Name", "Title", "Name"),
            organization=_pick(row, "Organization", "Org", "Company", "Unit"),
            start=_pick(row, "Start Date", "Begin Date"),
            end=_pick(row, "End Date"),
            hours=_pick(row, "Hours", "Duration"),
            status=_pick(row, "Status"),
            raw=dict(row),
        )


def social_practice() -> list[PracticeRecord]:
    """取社会实践记录列表。

    Returns:
        :class:`PracticeRecord` 列表；未开放 / 无记录时为空列表（实测页面
        提示「社会实践尚未开放，敬请关注相关通知。」）。

    Raises:
        AuthError: 会话失效。
        OffCampusError: 校外访问被拒。
        ActionError: 社会实践组件未授权。
        ParseError: 已渲染的网格结构变化（缺表头等）。
    """
    html = pages.fetch_page(PRACTICE_COMPONENT, query=PRACTICE_QUERY)
    return _rows_to_models(_grid_rows(html), PracticeRecord.from_row, page="社会实践")


# --------------------------------------------------------------------------- #
# 违纪
# --------------------------------------------------------------------------- #
@dataclass
class DisciplineRecord:
    """一条违纪记录（实测用户暂无违纪信息，真实列名未确认）。

    Attributes:
        date: 记录日期文本。
        category: 违纪类别。
        description: 详情 / 描述。
        status: 处理状态。
        raw: 原始「表头 → 值」字典；列名漂移时兜底。
    """

    date: str = ""
    category: str = ""
    description: str = ""
    status: str = ""
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """转为可序列化字典。"""
        return {
            "date": self.date,
            "category": self.category,
            "description": self.description,
            "status": self.status,
            "raw": dict(self.raw),
        }

    @classmethod
    def from_row(cls, row: dict) -> "DisciplineRecord":
        """从行字典构造（列名未实测，用候选键匹配 + ``raw`` 兜底）。"""
        return cls(
            date=_pick(row, "Date", "Record Date", "Date/Time"),
            category=_pick(row, "Category", "Type", "Discipline Type"),
            description=_pick(row, "Description", "Detail", "Reason"),
            status=_pick(row, "Status"),
            raw=dict(row),
        )


def discipline_records() -> list[DisciplineRecord]:
    """取违纪信息列表。

    Returns:
        :class:`DisciplineRecord` 列表；无违纪信息时为空列表（实测页面显示
        *You currently have no disciplinary information.* 且不渲染网格）。

    Raises:
        AuthError: 会话失效。
        OffCampusError: 校外访问被拒。
        ActionError: 违纪组件未授权。
        ParseError: 已渲染的网格结构变化（缺表头等）。
    """
    html = pages.fetch_page(DISCIPLINE_COMPONENT, query=DISCIPLINE_QUERY)
    return _rows_to_models(
        _grid_rows(html), DisciplineRecord.from_row, page="违纪信息"
    )


# --------------------------------------------------------------------------- #
# 志愿服务历史（官方 + 自主提交，含总时长）
# --------------------------------------------------------------------------- #
#: 志愿服务历史页组件（``WL_VOLUN`` 菜单，学生端可见）。
VOL_HISTORY_COMPONENT = "WL_CUSTOMIZE_MENU.WL_VOL_HIS_COM.GBL"

#: 志愿服务历史网格 id（2026-10-24 实测）。
VOL_HISTORY_GRID_ID = "WL_VOL_HISTORY"

#: 总时长 label 值里的单位粘连形态（如 ``24HOUR``）拆成 ``24 HOUR``。
_TOTAL_TIME_RESUB = re.compile(r"^(\d+(?:\.\d+)?)(HOUR|MINUTE|小时)$")


@dataclass
class VolunteerHistoryEntry:
    """一条志愿服务历史记录（实测网格 ``WL_VOL_HISTORY``）。

    Attributes:
        year: 学年（如 ``2025``）。
        source: 来源（``Official Entry`` 官方录入 / ``Self Submitted`` 自主提交）。
        name: 服务名称（中文自由文本）。
        time_text: 服务时间段（如 ``2025/11/18 18:30 — 2025/11/19 16:30``）。
        hours: 时长文本（如 ``2.0``）。
        raw: 原始「表头 → 值」字典，列名漂移时兜底。
    """

    year: str = ""
    source: str = ""
    name: str = ""
    time_text: str = ""
    hours: str = ""
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """转为可序列化字典。"""
        return {
            "year": self.year,
            "source": self.source,
            "name": self.name,
            "time_text": self.time_text,
            "hours": self.hours,
            "raw": dict(self.raw),
        }

    @classmethod
    def from_row(cls, row: dict) -> "VolunteerHistoryEntry":
        """从行字典构造（表头双语：2026-10-27 实测中文表头为
        ``学年 / 官方录入/自主提交 / 志愿服务名称 / 志愿服务时间 /
        服务时长（小时）``，注意末列是全角括号）。"""
        return cls(
            year=_pick(row, "Academic Year", "Year", "学年"),
            source=_pick(
                row, "Official Entry / Self Submitted", "Source", "官方录入/自主提交"
            ),
            name=_pick(
                row,
                "Volunteer Service Name",
                "Service Name",
                "Name",
                "志愿服务名称",
            ),
            time_text=_pick(
                row, "Volunteer Time", "Activity Time", "Time", "志愿服务时间"
            ),
            hours=_pick(
                row,
                "Service Duration (Hours)",
                "Duration",
                "Hours",
                "服务时长（小时）",
            ),
            raw=dict(row),
        )


@dataclass
class VolunteerHistory:
    """志愿服务历史页整体：总时长 + 明细列表。

    Attributes:
        total_time: 总时长文本（label 双语：英文 ``Total Time Of Volunteer
            Service`` / 中文 ``志愿服务累计时长``；值 ``24HOUR`` / ``24小时``
            规范化为 ``24 HOUR`` / ``24 小时``）。
        entries: 志愿服务历史明细（无记录时为空列表）。
    """

    total_time: str = ""
    entries: list = field(default_factory=list)

    def to_dict(self) -> dict:
        """转为可序列化字典。"""
        return {
            "total_time": self.total_time,
            "entries": [e.to_dict() for e in self.entries],
        }


def volunteer_history() -> VolunteerHistory:
    """取志愿服务历史（官方录入 + 自主提交，含总时长）。

    与 :func:`volunteer_records`（「我的志愿服务」``WL_VOL_MYSELF_COM``）为
    不同组件：历史页按学年汇总全部记录并给出总时长（2026-10-24 实测 4 行、
    总时长 24 HOUR）。

    Returns:
        :class:`VolunteerHistory`。

    Raises:
        AuthError: 会话失效。
        OffCampusError: 校外访问被拒。
        ActionError: 历史组件未授权。
        ParseError: 已渲染网格结构变化（缺表头等）。
    """
    html = pages.fetch_page(VOL_HISTORY_COMPONENT)
    rows = _grid_rows(html, VOL_HISTORY_GRID_ID)
    entries = _rows_to_models(
        rows, VolunteerHistoryEntry.from_row, page="志愿服务历史"
    )
    # 总时长 label 双语：英文 ``Total Time Of Volunteer Service`` / 中文
    # ``志愿服务累计时长``（2026-10-27 实测界面语言为中文时取后者）。
    labels = pages.parse_label_values(html)
    total = (
        labels.get("Total Time Of Volunteer Service")
        or labels.get("志愿服务累计时长")
        or ""
    )
    match = _TOTAL_TIME_RESUB.match(total.replace(" ", ""))
    if match:
        total = f"{match.group(1)} {match.group(2)}"
    return VolunteerHistory(total_time=total, entries=entries)


# --------------------------------------------------------------------------- #
# 学期注册缴费状态
# --------------------------------------------------------------------------- #
#: 学期注册缴费组件（``WL_XG_MENU`` 菜单，学生端「Semester Enrollment」）。
REGISTRATION_COMPONENT = "WL_XG_MENU.WL_STU_REG_PAY_COM.GBL"

#: 注册缴费页提示句特征（中英双语兜底）。
_REG_NOTICE_RE = re.compile(
    r"(The payment of fees[^<.!！]*[.!！]|缴费[^<.!！]{0,120}[.!！]|"
    r"registration[^<.!！]{0,120}[.!！]|注册[^<.!！]{0,120}[.!！])",
    re.IGNORECASE,
)


@dataclass
class RegistrationStatus:
    """学期注册缴费状态。

    Attributes:
        fields: 个人信息「标签 → 值」字典（实测键 ``Student ID`` / ``Name`` /
            ``Grade`` / ``Academic Career`` / ``Academic Group`` / ``College`` /
            ``Payment Academic Year``）。
        notice: 注册缴费提示句（2026-10-24 实测「The payment of fees for
            the 2026-2027 academic year is currently not open!」）。
    """

    fields: dict = field(default_factory=dict)
    notice: str = ""

    def to_dict(self) -> dict:
        """转为可序列化字典。"""
        return {"fields": dict(self.fields), "notice": self.notice}


def registration() -> RegistrationStatus:
    """取学期注册缴费状态。

    Returns:
        :class:`RegistrationStatus`；页面未开放缴费时 ``notice`` 携带站点
        提示句，``fields`` 为个人信息区键值对。

    Raises:
        AuthError: 会话失效。
        OffCampusError: 校外访问被拒。
        ActionError: 注册组件未授权。
    """
    html = pages.fetch_page(REGISTRATION_COMPONENT)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    match = _REG_NOTICE_RE.search(text)
    return RegistrationStatus(
        fields=pages.parse_label_values(html),
        notice=match.group(1).strip() if match else "",
    )


# --------------------------------------------------------------------------- #
# 心理健康预约（周历）
# --------------------------------------------------------------------------- #
#: 「我的预约」组件（``WL_SA_MENU``，心理健康在线预约）。
APPOINTMENT_COMPONENT = "WL_SA_MENU.WL_MTL_MY_APPNT2.GBL"

#: 周历表头里的星期词（用于列 → 星期映射）。
_WEEKDAY_WORDS = ("Monday", "Tuesday", "Wednesday", "Thursday",
                  "Friday", "Saturday", "Sunday")

#: 空闲占位符（周历空单元格渲染为连续箭头）。
_EMPTY_CELL = "-->"


@dataclass
class AppointmentSlot:
    """周历上的一个已占用时段。

    Attributes:
        day: 星期（如 ``Monday``）。
        date: 日期文本（如 ``2026-10-19``，页面有则带）。
        time: 起始时间（如 ``14:00``）。
        text: 单元格内容（预约标题 / 状态等）。
    """

    day: str = ""
    date: str = ""
    time: str = ""
    text: str = ""

    def to_dict(self) -> dict:
        """转为可序列化字典。"""
        return {"day": self.day, "date": self.date, "time": self.time, "text": self.text}


@dataclass
class Appointments:
    """「我的预约」周历视图。

    Attributes:
        week: 周范围文本（如 ``2026/10/19~2026/10/25``）。
        entries: 已占用时段列表（周历全空时为空列表——2026-10-24 实测本周
            无预约，全部单元格为 ``-->`` 占位）。
    """

    week: str = ""
    entries: list = field(default_factory=list)

    def to_dict(self) -> dict:
        """转为可序列化字典。"""
        return {"week": self.week, "entries": [e.to_dict() for e in self.entries]}


def _parse_week_calendar(html: str) -> Appointments:
    """解析周历表：定位含 ``Monday`` 表头的表格，抽出非空闲单元格。

    表结构（实测）：首列 ``Time`` 为整点（06:00–22:00），后 7 列为
    Monday–Sunday；表头单元格文本形如 ``Monday2026-10-19``（星期与日期连写）。
    空单元格渲染为 ``-->``。
    """
    from westlake_survival.sis.parser import _parse_tables

    week_match = re.search(r"\d{4}/\d{2}/\d{2}~\d{4}/\d{2}/\d{2}", html)
    result = Appointments(week=week_match.group(0) if week_match else "")
    for match in re.finditer(r"<table\b", html):
        end = html.find("</table>", match.start())
        if end == -1:
            continue
        segment = html[match.start(): end + 8]
        if "Monday" not in segment:
            continue
        header, rows = _parse_tables(segment)
        days: list[tuple[str, str]] = []
        header_cells = next((r for r in rows if r and r[:1] == ["Time"]), None)
        if header_cells:
            for cell in header_cells[1:]:
                day = next((w for w in _WEEKDAY_WORDS if cell.startswith(w)), "")
                date = cell[len(day):].strip() if day else ""
                days.append((day, date))
        for cells in rows:
            if not cells or not cells[0].strip() or cells[0].strip() == "Time":
                continue
            slot_time = cells[0].strip()
            for index, value in enumerate(cells[1:]):
                text = value.replace(_EMPTY_CELL, "").strip()
                if not text or index >= len(days):
                    continue
                day, date = days[index]
                result.entries.append(
                    AppointmentSlot(day=day, date=date, time=slot_time, text=text)
                )
        break
    return result


def appointments() -> Appointments:
    """取「我的预约」周历（心理健康在线预约）。

    Returns:
        :class:`Appointments`；当前周无预约时 ``entries`` 为空列表。

    Raises:
        AuthError: 会话失效。
        OffCampusError: 校外访问被拒。
        ActionError: 预约组件未授权。
    """
    html = pages.fetch_page(APPOINTMENT_COMPONENT)
    return _parse_week_calendar(html)


# --------------------------------------------------------------------------- #
# 离校检查 / 生源信息状态
# --------------------------------------------------------------------------- #
#: 离校自查清单组件。
LEAVING_CHECK_COMPONENT = "WL_CUSTOMIZE_MENU.WL_STU_LAV_CHECK.GBL"

#: 生源信息确认组件。
SOURCE_INFO_COMPONENT = "WL_SA_MENU.WL_SA_SOURCE_INFO.GBL"

#: 状态页正文抽取范围：登录问候语（中英）之后到补充面板（中英）之前。
#: 问候语里含学生姓名、正文前部含 ``ptnbsid`` 会话参数与导航噪音，均不应
#: 回显（2026-10-27 之前的实现整页倾倒，含姓名/参数/导航噪音）。
_STATUS_REGION_RE = re.compile(
    r"(?:welcome to SIS|您好，欢迎登录SIS系统)(.*?)(?:Supplementary Panel|辅助面板)",
    re.S,
)

#: 导航 / 框架噪音词（按空白切词后整词剔除，避免误删句中子串）。
_STATUS_NOISE_TOKENS = frozenset({
    "Back", "test", "后退", "种类", "*种类", "全部", "导航器", "关键字", "操作",
    "新窗口", "主页", "搜索", "添加至主页", "添加至导航栏", "添加至收藏夹",
    "帮助", "登出", "个性化页面", "跳至主内容", "相关信息", "问卷调查",
})

#: 关键状态句：以中英句终符收尾的短句。
_STATUS_SENTENCE_RE = re.compile(r"[^。！？!?]+[。！？!?]")


def _status_messages(html: str, *, title: str = "", page: str = "状态页") -> list[str]:
    """抽状态页关键提示句（一行一句，不含问候语 / 会话参数 / 导航噪音）。

    步骤：去 script/style → 锚定问候语到补充面板之间的正文 → 去标签 →
    剔除 ``ptnbsid`` 会话参数与导航噪音词（整词匹配）→ 按句终符切句。
    页面标题等无句终符的碎片自然被丢弃。抽不到任何句子时抛
    :class:`~westlake_survival.exceptions.ParseError`（结构变化不静默）。
    """
    from westlake_survival.exceptions import ParseError

    body = re.sub(r"<script.*?</script>", " ", html or "", flags=re.S)
    body = re.sub(r"<style.*?</style>", " ", body, flags=re.S)
    match = _STATUS_REGION_RE.search(body)
    segment = match.group(1) if match else body
    text = re.sub(r"<[^>]+>", " ", segment)
    text = text.replace("&nbsp;", " ")
    text = re.sub(r"(?i)ptnbsid[^\s'\"<>]*", " ", text)  # 不回显会话参数
    tokens = [
        token
        for token in text.split()
        if token not in _STATUS_NOISE_TOKENS and token != title
    ]
    text = " ".join(tokens)
    sentences = [
        sentence.strip() for sentence in _STATUS_SENTENCE_RE.findall(text)
        if len(sentence.strip()) > 1
    ]
    if not sentences:
        raise ParseError(f"{page}未找到关键提示句，页面结构可能已变化。")
    return sentences


def leaving_check() -> dict:
    """取离校自查清单状态。

    Returns:
        ``{"messages": [提示句, …]}``（一行一句）；2026-10-27 中文页实测为
        ``["您当前暂无离校任务！"]``，2026-10-24 英文页为
        ``["You currently have no task to leave school!"]``。有任务时应为
        清单网格，届时按需扩展。

    Raises:
        AuthError: 会话失效。
        OffCampusError: 校外访问被拒。
        ActionError: 离校组件未授权。
        ParseError: 状态页未找到关键提示句（结构可能已变化）。
    """
    html = pages.fetch_page(LEAVING_CHECK_COMPONENT)
    return {
        "messages": _status_messages(
            html, title="学生离校自查清单", page="离校自查"
        )
    }


def source_info_status() -> dict:
    """取生源信息确认状态。

    Returns:
        ``{"messages": [提示句, …]}``；2026-10-27 中文页实测为
        ``["未开放，还不能确认生源信息。"]``，2026-10-24 英文页为
        ``["Not yet open, unable to confirm student source information."]``。

    Raises:
        AuthError: 会话失效。
        OffCampusError: 校外访问被拒。
        ActionError: 生源组件未授权。
        ParseError: 状态页未找到关键提示句（结构可能已变化）。
    """
    html = pages.fetch_page(SOURCE_INFO_COMPONENT)
    return {
        "messages": _status_messages(
            html, title="学生确认生源信息", page="生源信息"
        )
    }


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


def _print_table(rows, headers) -> None:
    """打印对齐文本表格（委托 ``cli.main._print_table``，避免重复实现）。"""
    from westlake_survival.cli.main import _print_table as _impl

    _impl(rows, headers)


@click.group(name="records", help="学生事务记录：住宿 / 请假 / 荣誉 / 志愿 / 实践 / 违纪 / 第二课堂 / 学业导师 / 异动 / 注册 / 预约等。")
def cli_group() -> None:
    """``westlake records`` 命令组（注册由 ``cli.main`` 后续完成）。"""


@cli_group.command(name="dorm")
@_handle_errors
def records_dorm() -> None:
    """显示住宿申请记录与宿舍信息。"""
    record = dormitory()
    if record.info:
        for key, value in record.info.items():
            click.echo(f"{key}: {value}")
    if not record.applications:
        click.echo("暂无记录")
        return
    rows = [
        (a.application_no or "—", a.application_type or "—", a.reason or "—",
         a.date_time or "—", a.status or "—")
        for a in record.applications
    ]
    _print_table(rows, ("申请号", "类型", "理由", "时间", "状态"))


@cli_group.command(name="leave")
@_handle_errors
def records_leave() -> None:
    """显示请假申请列表。"""
    items = leave_requests()
    if not items:
        click.echo("暂无记录")
        return
    rows = [
        (i.application_no or "—", i.leave_type or "—", i.start or "—",
         i.end or "—", i.status or "—")
        for i in items
    ]
    _print_table(rows, ("申请号", "类型", "开始", "结束", "状态"))


@cli_group.command(name="honors")
@_handle_errors
def records_honors() -> None:
    """显示荣誉记录。"""
    items = honors()
    if not items:
        click.echo("暂无记录")
        return
    rows = [(h.name or "—", h.level or "—", h.date or "—", h.status or "—") for h in items]
    _print_table(rows, ("荣誉", "级别", "日期", "状态"))


@cli_group.command(name="volunteer")
@_handle_errors
def records_volunteer() -> None:
    """显示志愿服务记录。"""
    items = volunteer_records()
    if not items:
        click.echo("暂无记录")
        return
    rows = [
        (v.year or "—", v.number or "—", v.name or "—", v.status or "—",
         v.activity_time or "—", v.hours or "—")
        for v in items
    ]
    _print_table(rows, ("学年", "编号", "服务名称", "状态", "活动时间", "时长"))


@cli_group.command(name="practice")
@_handle_errors
def records_practice() -> None:
    """显示社会实践记录。"""
    items = social_practice()
    if not items:
        click.echo("暂无记录")
        return
    rows = [
        (p.title or "—", p.organization or "—", p.start or "—", p.end or "—",
         p.hours or "—", p.status or "—")
        for p in items
    ]
    _print_table(rows, ("项目", "组织", "开始", "结束", "时长", "状态"))


@cli_group.command(name="discipline")
@_handle_errors
def records_discipline() -> None:
    """显示违纪信息。"""
    items = discipline_records()
    if not items:
        click.echo("暂无记录")
        return
    rows = [
        (d.date or "—", d.category or "—", d.description or "—", d.status or "—")
        for d in items
    ]
    _print_table(rows, ("日期", "类别", "描述", "状态"))


@cli_group.command(name="vol-history")
@_handle_errors
def records_vol_history() -> None:
    """显示志愿服务历史（含总时长）。"""
    record = volunteer_history()
    click.echo(f"总时长：{record.total_time or '—'}")
    if not record.entries:
        click.echo("暂无记录")
        return
    rows = [
        (e.year or "—", e.source or "—", e.name or "—", e.time_text or "—",
         e.hours or "—")
        for e in record.entries
    ]
    _print_table(rows, ("学年", "来源", "服务名称", "时间", "时长(h)"))


@cli_group.command(name="registration")
@_handle_errors
def records_registration() -> None:
    """显示学期注册缴费状态。"""
    record = registration()
    for key, value in record.fields.items():
        click.echo(f"{key}: {value}")
    if record.notice:
        click.echo(f"提示：{record.notice}")


@cli_group.command(name="appointments")
@_handle_errors
def records_appointments() -> None:
    """显示本周预约（心理健康）。"""
    record = appointments()
    click.echo(f"周范围：{record.week or '—'}")
    if not record.entries:
        click.echo("本周无预约")
        return
    rows = [
        (e.date or e.day, e.time or "—", e.text or "—") for e in record.entries
    ]
    _print_table(rows, ("日期", "时间", "内容"))


@cli_group.command(name="leaving-check")
@_handle_errors
def records_leaving_check() -> None:
    """显示离校自查清单状态（关键提示句，一行一条）。"""
    for line in leaving_check()["messages"]:
        click.echo(line)


@cli_group.command(name="source-info")
@_handle_errors
def records_source_info() -> None:
    """显示生源信息确认状态（关键提示句，一行一条）。"""
    for line in source_info_status()["messages"]:
        click.echo(line)


@cli_group.command(name="advisor")
@click.option("--rotation", default=None, help="只看某轮（如 1 / 2 或 Rotation 标签关键词）")
@click.option("--limit", default=20, show_default=True, help="每轮最多列出多少位导师")
@_handle_errors
def records_advisor(rotation: str | None, limit: int) -> None:
    """显示学业导师分配结果与各轮名单。"""
    from westlake_survival.sis.advisor import advising

    info = advising()
    if info.announcement:
        click.echo(info.announcement)
    for item in info.rotations:
        if rotation and rotation not in item.label and rotation != item.code:
            continue
        click.secho(f"{item.label or '导师名单'}：{len(item.advisors)} 位", bold=True)
        ranked = sorted(
            item.advisors,
            key=lambda a: _to_int(a.choices.get("1st Choice")),
            reverse=True,
        )
        for advisor in ranked[: max(0, limit)]:
            click.echo(
                f"  {advisor.name}｜{advisor.school}｜配额 {advisor.quota or '—'}"
                f"｜余量 {advisor.remaining or '—'}｜1志愿 {advisor.choices.get('1st Choice') or '—'}"
            )
        if len(ranked) > limit:
            click.echo(f"  …另有 {len(ranked) - limit} 位（--limit 调整）")


def _to_int(value: str | None) -> int:
    """把页面上的计数文本转 int（非数字按 0）。"""
    text = str(value or "").strip()
    return int(text) if text.isdigit() else 0


@cli_group.command(name="other-apps")
@_handle_errors
def records_other_apps() -> None:
    """显示学籍异动 / 困难认定 / 本博衔接 / 就业四类申请状态。"""
    from westlake_survival.sis.applications import other_applications

    data = other_applications()
    tabs = data.status_change.tabs
    click.secho(f"学籍异动可办理流程（{len(tabs)}）", bold=True)
    click.echo("  " + " · ".join(tabs) if tabs else "  （未取到流程列表）")
    for label, item in (
        ("困难认定", data.difficulty),
        ("本博衔接", data.phd),
        ("就业服务", data.employment),
        ("学术进度", data.academic_progress),
    ):
        click.echo(f"{label}：{item.count} 条" + (f"｜{item.message}" if item.message else ""))


@cli_group.command(name="second-class")
@_handle_errors
def records_second_class() -> None:
    """显示第二课堂成绩单（5 个维度 + 每项要求进度）。"""
    from westlake_survival.sis.second_class import second_classroom

    report = second_classroom()
    if not report.categories:
        click.echo("暂无第二课堂记录")
        return
    for category in report.categories:
        percent = f"{category.percent}%" if category.percent is not None else "—"
        click.secho(f"{category.name}（{percent}）", bold=True)
        for node in category.nodes:
            show_node = bool(node.name) and node.name != category.name
            if show_node:
                label = node.name
                if node.percent is not None:
                    label = f"{label}（{node.percent}%）"
                click.echo(f"  {label}")
            indent = "    " if show_node else "  "
            for row in node.rows:
                click.echo(f"{indent}{row.requirement}：{row.progress or '—'}")
            for child in node.children:
                child_label = child.name
                if child.percent is not None:
                    child_label = f"{child_label}（{child.percent}%）"
                click.echo(f"    {child_label}")
                for row in child.rows:
                    click.echo(f"      {row.requirement}：{row.progress or '—'}")
    click.echo(f"未完成要求：{report.pending} 条")