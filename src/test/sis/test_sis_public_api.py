"""sis / ical 公开 API 冻结测试：webui/cli 依赖这些名字。"""

from __future__ import annotations


def test_sis_public_api():
    from westlake_survival.sis import (
        SIS_URLS,
        ClassSession,
        SISClient,
        export_schedule_xls,
        fetch_schedule_html,
        get_schedule,
        parse_ps_xls,
        parse_schedule_html,
    )

    assert callable(get_schedule)
    assert callable(fetch_schedule_html)
    assert callable(export_schedule_xls)
    assert callable(parse_schedule_html)
    assert callable(parse_ps_xls)
    assert isinstance(SIS_URLS, dict)
    assert "schedule_page" in SIS_URLS
    assert ClassSession is not None
    assert SISClient is not None


def test_ical_public_api():
    from westlake_survival.ical import courses_to_ical, save_ics

    assert callable(courses_to_ical)
    assert callable(save_ics)


def test_classsession_fields():
    import dataclasses
    from datetime import date, time

    from westlake_survival.sis import ClassSession

    fields = {f.name for f in dataclasses.fields(ClassSession)}
    assert {
        "title",
        "course_code",
        "teacher",
        "room",
        "weekday",
        "start_time",
        "end_time",
        "date_start",
        "date_end",
        "weeks",
        "raw",
    } <= fields
    assert ClassSession().start_time == time(0, 0)
    assert ClassSession().date_start == date(1970, 1, 1)