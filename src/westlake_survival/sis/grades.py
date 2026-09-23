"""SIS 成绩页读取：把 fluid 网格 ``WL_STU_ENRL_V2`` 解析为 :class:`Grade` 列表。

数据源（2026-09-23 实测）：组件页
``WL_CUSTOMIZE_MENU.WL_STU_GRADE_COM.GBL``（页面标题「My Grades」），fluid
网格 ``WL_STU_ENRL_V2``，列 ``Course Code / Course Title / Term / Grade /
Credits``，一次返回全部历史学期（实测 38 行）。

**不计算 GPA**：网格里既有字母等级（``A+``/``B``/``P``…）也有未出分
（``Grade`` 为空）与仅记 ``P`` 的记录，学分字段亦含 0.5 的整半值；缺少
官方换算口径时任何加权平均都是臆造，故本模块只忠实返回逐条成绩。

解析委托给 :mod:`westlake_survival.sis.pages`（登录态抓页 + fluid 网格解析），
本模块只负责列名归一与数据模型映射。
"""

from __future__ import annotations

from dataclasses import dataclass

from westlake_survival.sis import pages

__all__ = [
    "GRADES_COMPONENT",
    "GRADES_GRID_ID",
    "Grade",
    "grades",
]

#: 成绩页组件（无查询串）。
GRADES_COMPONENT = "WL_CUSTOMIZE_MENU.WL_STU_GRADE_COM.GBL"

#: 成绩 fluid 网格 id。
GRADES_GRID_ID = "WL_STU_ENRL_V2"


@dataclass
class Grade:
    """一条课程成绩。

    Attributes:
        course_code: 课程代码（如 ``CST 2000``）。
        course_title: 课程名称（ENG locale）。
        term: 学期描述（如 ``2026-2027 Fall Term``）。
        grade: 等级；未出分时为空串。
        credits: 学分文本（如 ``2.0``）；缺失时为空串。
    """

    course_code: str = ""
    course_title: str = ""
    term: str = ""
    grade: str = ""
    credits: str = ""

    def to_dict(self) -> dict:
        """转为可序列化字典。"""
        return {
            "course_code": self.course_code,
            "course_title": self.course_title,
            "term": self.term,
            "grade": self.grade,
            "credits": self.credits,
        }

    @classmethod
    def from_row(cls, row: dict) -> "Grade":
        """从 :func:`~westlake_survival.sis.pages.parse_fluid_grid` 的行字典构造。"""
        return cls(
            course_code=(row.get("Course Code") or "").strip(),
            course_title=(row.get("Course Title") or "").strip(),
            term=(row.get("Term") or "").strip(),
            grade=(row.get("Grade") or "").strip(),
            credits=(row.get("Credits") or "").strip(),
        )


def grades() -> list[Grade]:
    """取全部学期成绩（按页面顺序，最近学期在前）。

    Returns:
        :class:`Grade` 列表；页面无数据行时为空列表。缺课程代码的空行被跳过。

    Raises:
        AuthError: 会话失效。
        OffCampusError: 校外访问被拒。
        ActionError: 成绩组件未授权。
        ParseError: 页面结构变化导致网格解析失败。
    """
    html = pages.fetch_page(GRADES_COMPONENT)
    result: list[Grade] = []
    for row in pages.parse_fluid_grid(html, GRADES_GRID_ID):
        grade = Grade.from_row(row)
        if not (grade.course_code or grade.course_title):
            continue  # 站点残留的空行 / 汇总行
        result.append(grade)
    return result
