"""SIS 考试安排页读取：把 fluid 网格 ``WL_EXAM_STU_VW`` 解析为 :class:`ExamSlot`。

数据源（2026-09-23 实测）：组件页
``WL_CUSTOMIZE_MENU.WL_EXAM_STU_COM_FL.GBL?Page=WL_EXAM_STU_FL``，fluid 网格
``WL_EXAM_STU_VW``，列 ``Course Code / Course Title / Date / Time / Type /
Method / Venue / Seat Nbr``（2026-10-27 实测：界面语言切中文后表头为
``考试科目 / 课程名称 / 考试日期 / 考试时间 / 课程考试类型 / 考试方式 /
考试地点 / 座位号``，列名映射双语化），**页头固定当前学期**（实测
2026-2027 Fall Term，10 门课）；考试尚未排定时 ``Date`` 及之后各列为空
（真实数据即如此，本模块忠实返回空串而非臆造）。

解析委托给 :mod:`westlake_survival.sis.pages`（登录态抓页 + fluid 网格解析），
本模块只负责列名归一与数据模型映射。
"""

from __future__ import annotations

from dataclasses import dataclass

from westlake_survival.sis import pages

__all__ = [
    "EXAMS_COMPONENT",
    "EXAMS_QUERY",
    "EXAMS_GRID_ID",
    "ExamSlot",
    "exam_schedule",
]

#: 考试页组件。
EXAMS_COMPONENT = "WL_CUSTOMIZE_MENU.WL_EXAM_STU_COM_FL.GBL"

#: 考试页查询串（``Page`` 参数指向考试 fluid 页）。
EXAMS_QUERY = "Page=WL_EXAM_STU_FL"

#: 考试 fluid 网格 id。
EXAMS_GRID_ID = "WL_EXAM_STU_VW"


@dataclass
class ExamSlot:
    """一门课程的考试安排（尚未排定时除课程信息外均为空串）。

    Attributes:
        course_code: 课程代码（如 ``PHY 1004``）。
        course_title: 课程名称（ENG locale）。
        date: 考试日期文本（未排定为空串）。
        time: 考试时间文本（未排定为空串）。
        exam_type: 考试类型（如 Final / Midterm 等）。
        method: 考试方式（如 Closed Book / Online）。
        venue: 考场。
        seat: 座位号。
    """

    course_code: str = ""
    course_title: str = ""
    date: str = ""
    time: str = ""
    exam_type: str = ""
    method: str = ""
    venue: str = ""
    seat: str = ""

    def to_dict(self) -> dict:
        """转为可序列化字典。"""
        return {
            "course_code": self.course_code,
            "course_title": self.course_title,
            "date": self.date,
            "time": self.time,
            "exam_type": self.exam_type,
            "method": self.method,
            "venue": self.venue,
            "seat": self.seat,
        }

    #: 表头双语文备（2026-10-27 实测：登录语言为中文时网格表头是中文列名
    #: ``考试科目/课程名称/考试日期/考试时间/课程考试类型/考试方式/考试地点/
    #: 座位号``，旧实现只匹配英文表头导致 10 行全部被当空行跳过——
    #: exam_schedule() 静默返回空）。写法沿用 :mod:`...sis.grades` 的
    #: ``_COLUMNS`` 双语映射。
    _COLUMNS = {
        "course_code": ("Course Code", "考试科目"),
        "course_title": ("Course Title", "课程名称"),
        "date": ("Date", "考试日期"),
        "time": ("Time", "考试时间"),
        "exam_type": ("Type", "课程考试类型"),
        "method": ("Method", "考试方式"),
        "venue": ("Venue", "考试地点"),
        "seat": ("Seat Nbr", "座位号"),
    }

    @classmethod
    def from_row(cls, row: dict) -> "ExamSlot":
        """从 :func:`~westlake_survival.sis.pages.parse_fluid_grid` 的行字典构造。

        网格表头语言随账号登录语言（实测有英文与中文两套列名），逐列取
        第一个命中的语言键。
        """
        def pick(*names: str) -> str:
            for name in names:
                value = row.get(name)
                if value:
                    return str(value).strip()
            return ""

        return cls(
            course_code=pick(*cls._COLUMNS["course_code"]),
            course_title=pick(*cls._COLUMNS["course_title"]),
            date=pick(*cls._COLUMNS["date"]),
            time=pick(*cls._COLUMNS["time"]),
            exam_type=pick(*cls._COLUMNS["exam_type"]),
            method=pick(*cls._COLUMNS["method"]),
            venue=pick(*cls._COLUMNS["venue"]),
            seat=pick(*cls._COLUMNS["seat"]),
        )


def exam_schedule() -> list[ExamSlot]:
    """取当前学期考试安排（页头学期由 SIS 决定，本模块不传学期参数）。

    Returns:
        :class:`ExamSlot` 列表；页面无数据行时为空列表。缺课程信息的空行被跳过。

    Raises:
        AuthError: 会话失效。
        OffCampusError: 校外访问被拒。
        ActionError: 考试组件未授权。
        ParseError: 页面结构变化导致网格解析失败；或页面有数据行但所有
            具名字段均为空（表头可能又一次变化，见
            :func:`~westlake_survival.sis.pages.assert_named_fields`）。
    """
    html = pages.fetch_page(EXAMS_COMPONENT, query=EXAMS_QUERY)
    rows = pages.parse_fluid_grid(html, EXAMS_GRID_ID)
    result: list[ExamSlot] = []
    for row in rows:
        slot = ExamSlot.from_row(row)
        if not (slot.course_code or slot.course_title):
            continue  # 站点残留的空行
        result.append(slot)
    pages.assert_named_fields(rows, result, page="考试安排")
    return result
