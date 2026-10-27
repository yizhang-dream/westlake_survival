"""westlake_survival — 在 API 层面调用西湖大学各服务系统。

子模块按需惰性导入::

    import westlake_survival
    westlake_survival.sis        # 教务 SIS (PeopleSoft)
    westlake_survival.canvas     # Canvas LMS
    westlake_survival.lib        # 图书馆 OPAC
    westlake_survival.sso        # 统一身份认证 (CAS)
    westlake_survival.mcp_server # MCP 服务器（stdio，供 AI 客户端接入）

SIS 常用数据模型与工厂也做惰性重导出，便于 ``westlake_survival.Grade`` 这样
的顶层取用（首次访问时才导入 :mod:`westlake_survival.sis`，维持惰性）::

    from westlake_survival import Grade, grades, ExamSlot, exam_schedule

成绩 / 考试之外的 SIS 组件页（评教、个人信息、学生事务记录、资助与机会）
同样重导出其主要模型与取数函数::

    from westlake_survival import EvalTask, pending_evaluations
    from westlake_survival import personal_info, dormitory, loans
"""

from __future__ import annotations

import importlib

from westlake_survival._version import __version__

#: 惰性重导出的 SIS 名字（模型 + 取数函数，口径与
#: :data:`westlake_survival.sis.__all__` 一致）。
_SIS_REEXPORTS = (
    # 成绩 / 考试
    "Grade",
    "grades",
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
    # 资助 / 勤工 / 交流 / 社团
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
)

__all__ = ["__version__", *_SIS_REEXPORTS]

_SUBMODULES = (
    "sso",
    "sis",
    "canvas",
    "lib",
    "pms",
    "transit",
    "calendar",
    "ical",
    "context",
    "search",
    "news",
    "research",
    "events",
    "careers",
    "faculty",
    "campus",
    "contact",
    "clubwiki",
    "webui",
    "mcp_server",
    "cli",
)

#: 惰性重导出的顶层名字 → 所属子模块。
_LAZY_REEXPORTS = {name: "sis" for name in _SIS_REEXPORTS}


def __getattr__(name: str):
    if name in _SUBMODULES:
        return importlib.import_module(f"westlake_survival.{name}")
    if name in _LAZY_REEXPORTS:
        return getattr(importlib.import_module(f"westlake_survival.{_LAZY_REEXPORTS[name]}"), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(__all__) | set(_SUBMODULES))