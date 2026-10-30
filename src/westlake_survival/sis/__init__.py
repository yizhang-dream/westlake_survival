"""SIS（教务，Oracle PeopleSoft Campus Solutions）子模块。

公开 API（webui/cli 依赖，视为冻结）::

    from westlake_survival.sis import (
        get_schedule,            # 取课表节次（带缓存）
        fetch_schedule_html,     # 抓课表页 HTML
        export_schedule_xls,     # 尝试导出 ps.xls
        parse_schedule_html,     # 解析课表页 HTML
        parse_ps_xls,            # 解析导出的 HTML-in-xls（容错缺 </tr>）
        ClassSession,            # 节次数据模型
        SIS_URLS,                # URL 常量
        grades,                  # 取全部学期成绩
        Grade,                   # 成绩数据模型
        exam_schedule,           # 取当前学期考试安排
        ExamSlot,                # 考试数据模型
        shopping_cart,           # 取选课车内容（只读）
        CartCourse,              # 选课车课程数据模型
    )

    sessions = get_schedule()                 # 首次抓取 + 写缓存
    sessions = get_schedule(refresh=True)     # 强制刷新
    sessions = get_schedule(source="xls")     # 走导出路线
    grade_list = grades()                     # 成绩（含历史学期）
    exams = exam_schedule()                   # 考试安排（当前学期）

登录复用 :class:`westlake_survival.sso.SISAuth`（PeopleSoft 本地登录）。
课表页未登录 GET 会 302 到 ``?cmd=login``，本模块据此抛 ``AuthError``。

成绩 / 考试等其余组件页经共享读取层 :mod:`westlake_survival.sis.pages`
（登录态抓页 + fluid 网格解析；门户索引 ``CSPRD_x`` 动态解析，见其 docstring）。

解析与 URL 的实测说明（2026-08-30 导出格式、2026-09-23 登录链路全链路
实测确认）见 :mod:`westlake_survival.sis.parser` 与
:mod:`westlake_survival.sis.client` 的模块 docstring。
"""

from __future__ import annotations

from __future__ import annotations

import importlib

#: 惰性导出映射：符号名 → 子模块路径。按需动态加载，避免引入 sis 包时级联
#: 静态导入全部 12 个子模块与全部数据模型。
_LAZY_EXPORTS: dict[str, str] = {
    "ActivityRecord": "westlake_survival.sis.aid",
    "Advisor": "westlake_survival.sis.advisor",
    "AdvisorInfo": "westlake_survival.sis.advisor",
    "AdvisorRotation": "westlake_survival.sis.advisor",
    "ApplicationStatus": "westlake_survival.sis.applications",
    "CartCourse": "westlake_survival.sis.cart",
    "ClassSession": "westlake_survival.sis.parser",
    "DisciplineRecord": "westlake_survival.sis.records",
    "DormApplication": "westlake_survival.sis.records",
    "DormRecord": "westlake_survival.sis.records",
    "EvalTask": "westlake_survival.sis.evals",
    "ExamSlot": "westlake_survival.sis.exams",
    "ExchangeRecord": "westlake_survival.sis.aid",
    "ExchangeSchool": "westlake_survival.sis.aid",
    "Grade": "westlake_survival.sis.grades",
    "HonorRecord": "westlake_survival.sis.records",
    "LeaveRequest": "westlake_survival.sis.records",
    "LoanRecord": "westlake_survival.sis.aid",
    "LoanRepayment": "westlake_survival.sis.aid",
    "OrgRecord": "westlake_survival.sis.aid",
    "OtherApplications": "westlake_survival.sis.applications",
    "OutboundRecord": "westlake_survival.sis.aid",
    "PracticeRecord": "westlake_survival.sis.records",
    "SCHEDULE_CACHE_NAME": "westlake_survival.sis.client",
    "SISClient": "westlake_survival.sis.client",
    "SIS_URLS": "westlake_survival.sis.client",
    "SecondClassCategory": "westlake_survival.sis.second_class",
    "SecondClassNode": "westlake_survival.sis.second_class",
    "SecondClassReport": "westlake_survival.sis.second_class",
    "SecondClassRow": "westlake_survival.sis.second_class",
    "StudyJob": "westlake_survival.sis.aid",
    "VolunteerRecord": "westlake_survival.sis.records",
    "WorkStudyTab": "westlake_survival.sis.aid",
    "academic_record": "westlake_survival.sis.profile",
    "advising": "westlake_survival.sis.advisor",
    "discipline_records": "westlake_survival.sis.records",
    "dormitory": "westlake_survival.sis.records",
    "evaluations": "westlake_survival.sis.evals",
    "exam_schedule": "westlake_survival.sis.exams",
    "exchange_applications": "westlake_survival.sis.aid",
    "exchange_schools": "westlake_survival.sis.aid",
    "export_schedule_xls": "westlake_survival.sis.client",
    "extended_info": "westlake_survival.sis.profile",
    "fetch_page": "westlake_survival.sis.pages",
    "fetch_schedule_html": "westlake_survival.sis.client",
    "get_schedule": "westlake_survival.sis.client",
    "grades": "westlake_survival.sis.grades",
    "honors": "westlake_survival.sis.records",
    "leave_requests": "westlake_survival.sis.records",
    "loan_application": "westlake_survival.sis.aid",
    "loan_repayments": "westlake_survival.sis.aid",
    "loans": "westlake_survival.sis.aid",
    "my_clubs": "westlake_survival.sis.aid",
    "other_applications": "westlake_survival.sis.applications",
    "outbound_programs": "westlake_survival.sis.aid",
    "parse_date_range": "westlake_survival.sis.parser",
    "parse_fluid_grid": "westlake_survival.sis.pages",
    "parse_label_values": "westlake_survival.sis.pages",
    "parse_ps_xls": "westlake_survival.sis.parser",
    "parse_schedule_html": "westlake_survival.sis.parser",
    "parse_time_slot": "westlake_survival.sis.parser",
    "parse_weeks": "westlake_survival.sis.parser",
    "pending_evaluations": "westlake_survival.sis.evals",
    "personal_info": "westlake_survival.sis.profile",
    "reset_sis": "westlake_survival.sis.client",
    "second_classroom": "westlake_survival.sis.second_class",
    "shopping_cart": "westlake_survival.sis.cart",
    "social_practice": "westlake_survival.sis.records",
    "student_activities": "westlake_survival.sis.aid",
    "student_orgs": "westlake_survival.sis.aid",
    "study_jobs": "westlake_survival.sis.aid",
    "volunteer_records": "westlake_survival.sis.records",
    "work_study_tabs": "westlake_survival.sis.aid",
}


def __getattr__(name: str) -> object:
    if name in _LAZY_EXPORTS:
        mod = importlib.import_module(_LAZY_EXPORTS[name])
        val = getattr(mod, name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    # 客户端
    "SISClient",
    "SIS_URLS",
    "SCHEDULE_CACHE_NAME",
    "get_schedule",
    "fetch_schedule_html",
    "export_schedule_xls",
    "reset_sis",
    # 解析
    "ClassSession",
    "parse_schedule_html",
    "parse_ps_xls",
    "parse_date_range",
    "parse_time_slot",
    "parse_weeks",
    # 通用页面读取层
    "fetch_page",
    "parse_fluid_grid",
    "parse_label_values",
    # 成绩
    "Grade",
    "grades",
    # 考试
    "ExamSlot",
    "exam_schedule",
    # 选课车（只读）
    "CartCourse",
    "shopping_cart",
    # 评教
    "EvalTask",
    "evaluations",
    "pending_evaluations",
    # 个人信息 / 学籍 / 扩展信息
    "personal_info",
    "academic_record",
    "extended_info",
    # 学生事务记录
    "DormApplication",
    "DormRecord",
    "dormitory",
    "LeaveRequest",
    "leave_requests",
    "HonorRecord",
    "honors",
    "VolunteerRecord",
    "volunteer_records",
    "PracticeRecord",
    "social_practice",
    "DisciplineRecord",
    "discipline_records",
    # 资助 / 交流 / 社团
    "LoanRecord",
    "LoanRepayment",
    "loans",
    "loan_application",
    "loan_repayments",
    "StudyJob",
    "WorkStudyTab",
    "study_jobs",
    "work_study_tabs",
    "OutboundRecord",
    "outbound_programs",
    "ExchangeRecord",
    "ExchangeSchool",
    "exchange_applications",
    "exchange_schools",
    "OrgRecord",
    "student_orgs",
    "my_clubs",
    "ActivityRecord",
    "student_activities",
    # 第二课堂
    "SecondClassReport",
    "SecondClassCategory",
    "SecondClassNode",
    "SecondClassRow",
    "second_classroom",
    # 学业导师
    "Advisor",
    "AdvisorRotation",
    "AdvisorInfo",
    "advising",
    # 其他申请（学籍异动 / 困难认定 / 本博衔接 / 就业）
    "ApplicationStatus",
    "OtherApplications",
    "other_applications",
]
