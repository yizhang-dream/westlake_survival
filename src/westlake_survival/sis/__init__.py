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

from westlake_survival.sis.client import (
    SCHEDULE_CACHE_NAME,
    SIS_URLS,
    SISClient,
    export_schedule_xls,
    fetch_schedule_html,
    get_schedule,
    reset_sis,
)
from westlake_survival.sis.aid import (
    ActivityRecord,
    ExchangeRecord,
    ExchangeSchool,
    LoanRecord,
    LoanRepayment,
    OrgRecord,
    OutboundRecord,
    StudyJob,
    WorkStudyTab,
    exchange_applications,
    exchange_schools,
    loan_application,
    loan_repayments,
    loans,
    my_clubs,
    outbound_programs,
    student_activities,
    student_orgs,
    study_jobs,
    work_study_tabs,
)
from westlake_survival.sis.evals import (
    EvalTask,
    evaluations,
    pending_evaluations,
)
from westlake_survival.sis.exams import ExamSlot, exam_schedule
from westlake_survival.sis.grades import Grade, grades
from westlake_survival.sis.pages import (
    fetch_page,
    parse_fluid_grid,
    parse_label_values,
)
from westlake_survival.sis.parser import (
    ClassSession,
    parse_date_range,
    parse_ps_xls,
    parse_schedule_html,
    parse_time_slot,
    parse_weeks,
)
from westlake_survival.sis.profile import (
    academic_record,
    extended_info,
    personal_info,
)
from westlake_survival.sis.records import (
    DisciplineRecord,
    DormApplication,
    DormRecord,
    HonorRecord,
    LeaveRequest,
    PracticeRecord,
    VolunteerRecord,
    discipline_records,
    dormitory,
    honors,
    leave_requests,
    social_practice,
    volunteer_records,
)

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
]
