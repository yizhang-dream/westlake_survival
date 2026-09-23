"""iCalendar (``.ics``) 导出子模块。

把 SIS 课表节次转成主流日历可导入的 ``.ics``::

    from westlake_survival.sis import get_schedule
    from westlake_survival.ical import courses_to_ical, save_ics

    sessions = get_schedule()
    text = courses_to_ical(sessions)          # 直接拿字符串
    save_ics(sessions, "schedule.ics")        # 或写文件

实现为纯字符串变换（无网络、无副作用），细节见
:mod:`westlake_survival.ical.gen`。
"""

from __future__ import annotations

from westlake_survival.ical.gen import (
    CALENDAR_NAME,
    PRODID,
    UID_SUFFIX,
    courses_to_ical,
    save_ics,
)

__all__ = [
    "courses_to_ical",
    "save_ics",
    "PRODID",
    "CALENDAR_NAME",
    "UID_SUFFIX",
]