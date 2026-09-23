"""离线解析与查询测试（使用真实页面片段 fixture）。"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from westlake_survival.calendar import (
    AcademicCalendar,
    CalendarEvent,
    Semester,
    parse_calendar,
)
from westlake_survival.exceptions import ParseError


# --------------------------------------------------------------------------- #
# 解析
# --------------------------------------------------------------------------- #
def test_parse_two_semesters(calendar: AcademicCalendar) -> None:
    assert [s.name for s in calendar.semesters] == ["2026年春季", "2026年秋季"]


def test_semester_bounds_from_event_titles(calendar: AcademicCalendar) -> None:
    spring, fall = calendar.semesters
    assert (spring.start, spring.end) == (date(2026, 3, 2), date(2026, 6, 24))
    assert (fall.start, fall.end) == (date(2026, 8, 31), date(2026, 12, 25))


def test_event_counts(calendar: AcademicCalendar) -> None:
    spring, fall = calendar.semesters
    assert len(spring.events) == 16
    assert len(fall.events) == 19


def test_event_end_none_means_single_day(calendar: AcademicCalendar) -> None:
    fall = calendar.semesters[1]
    kickoff = next(e for e in fall.events if e.title == "秋季学期课程开始")
    assert kickoff.start == date(2026, 8, 31)
    assert kickoff.end is None
    assert kickoff.is_single_day
    assert kickoff.last_day == date(2026, 8, 31)

    midautumn = next(e for e in fall.events if "中秋节放假" in e.title)
    assert midautumn.start == date(2026, 9, 25)
    assert midautumn.end == date(2026, 9, 27)
    assert not midautumn.is_single_day


def test_raw_dict_preserved(calendar: AcademicCalendar) -> None:
    event = next(e for s in calendar.semesters for e in s.events if "元旦放假" in e.title)
    assert event.raw == {"title": "元旦放假", "time": "2027-01-01", "endtime": ""}


def test_holiday_and_exam_filters(calendar: AcademicCalendar) -> None:
    fall = calendar.semesters[1]
    assert [e.title for e in fall.holiday_events()] == [
        "中秋节放假(9月20日补上9月25日的课）",
        "国庆节放假(10月1-2日及5-7日的课顺延一周补齐）",
        "元旦放假",
    ]
    assert [e.title for e in fall.exams()] == ["期末考试周"]


def test_parse_mojibake_is_repaired(fixture_mojibake: str) -> None:
    # 模拟 http_get_with_etag 返回的 ISO-8859-1 乱码文本，解析后标题应正常。
    assert "课程" not in fixture_mojibake  # 确认输入确实是乱码
    calendar = parse_calendar(fixture_mojibake)
    titles = [e.title for s in calendar.semesters for e in s.events]
    assert "秋季学期课程开始" in titles


def test_parse_error_when_course_start_missing() -> None:
    html = (
        "<script>new calendar('#app', {"
        'seasonList: ["2026年秋季"],'
        'contentList: [[{title: "秋季学期课程结束", time: "2026-12-25", endtime: ""}]],'
        "});</script>"
    )
    with pytest.raises(ParseError, match="课程开始"):
        parse_calendar(html)


def test_parse_error_when_season_list_missing() -> None:
    with pytest.raises(ParseError):
        parse_calendar("<html>no calendar here</html>")


# --------------------------------------------------------------------------- #
# 周次换算
# --------------------------------------------------------------------------- #
def test_week_of_first_and_last_week(calendar: AcademicCalendar) -> None:
    fall = calendar.semesters[1]
    assert fall.week_of(date(2026, 8, 31)) == 1  # 课程开始日所在周
    assert fall.week_of(date(2026, 9, 6)) == 1  # 同一周的周日
    assert fall.week_of(date(2026, 9, 7)) == 2  # 次周周一
    assert fall.week_of(date(2026, 12, 25)) == fall.teaching_weeks()


def test_week_of_out_of_range_is_none(calendar: AcademicCalendar) -> None:
    fall = calendar.semesters[1]
    assert fall.week_of(date(2026, 8, 30)) is None  # 开学前一天
    # 学期末边界（last_day 含考试周等课程结束后的事件）之外为 None。
    assert fall.week_of(fall.last_day + timedelta(days=1)) is None


def test_exam_week_belongs_to_semester(calendar: AcademicCalendar) -> None:
    """考试周在课程结束之后，但仍属该学期并延续教学周次（P1 回归）。"""
    fall = calendar.semesters[1]
    assert fall.last_day >= date(2027, 1, 8)  # 覆盖期末考试周结束日
    week = fall.week_of(date(2026, 12, 28))
    assert week is not None and week >= 17
    assert fall.week_of(date(2027, 1, 1)) is not None

    # 自洽性：date_of(18, 1) 构造出的日期必须能反查回第 18 周。
    d = fall.date_of(18, 1)
    assert d == date(2026, 12, 28)
    assert fall.week_of(d) == 18
    assert calendar.semester_for(d) is fall
    assert calendar.current(date(2027, 1, 1)) is fall
    assert calendar.week_of(date(2026, 12, 28)) == (fall, 18)


def test_week_of_date_of_roundtrip(calendar: AcademicCalendar) -> None:
    for semester in calendar.semesters:
        for week in range(1, semester.teaching_weeks() + 1):
            for weekday in range(1, 8):
                d = semester.date_of(week, weekday)
                if semester.start <= d <= semester.last_day:
                    assert semester.week_of(d) == week, (semester.name, d)


def test_date_of_monday_is_week_start(calendar: AcademicCalendar) -> None:
    for semester in calendar.semesters:
        assert semester.date_of(1, 1) == semester.start  # 两学期都从周一开始
        assert semester.date_of(1, 7) - semester.date_of(1, 1) == timedelta(days=6)


def test_date_of_rejects_bad_arguments(calendar: AcademicCalendar) -> None:
    semester = calendar.semesters[0]
    with pytest.raises(ValueError):
        semester.date_of(0, 1)
    with pytest.raises(ValueError):
        semester.date_of(1, 0)
    with pytest.raises(ValueError):
        semester.date_of(1, 8)


def test_teaching_weeks(calendar: AcademicCalendar) -> None:
    assert calendar.semesters[0].teaching_weeks() == 17
    assert calendar.semesters[1].teaching_weeks() == 17


# --------------------------------------------------------------------------- #
# 假日 / 教学日
# --------------------------------------------------------------------------- #
def test_is_holiday_midautumn_range(calendar: AcademicCalendar) -> None:
    fall = calendar.semesters[1]
    for d in (date(2026, 9, 25), date(2026, 9, 26), date(2026, 9, 27)):
        assert fall.is_holiday(d) is True
    assert fall.is_holiday(date(2026, 9, 24)) is False


def test_makeup_day_is_not_holiday(calendar: AcademicCalendar) -> None:
    fall = calendar.semesters[1]
    # 9/20（周日）是"补上 9/25 的课"的调休补班日。
    assert date(2026, 9, 20) in fall.makeup_days()
    assert fall.is_holiday(date(2026, 9, 20)) is False


def test_national_day_and_new_year_holidays(calendar: AcademicCalendar) -> None:
    fall = calendar.semesters[1]
    assert fall.is_holiday(date(2026, 10, 3)) is True
    assert fall.is_holiday(date(2027, 1, 1)) is True
    assert fall.is_holiday(date(2026, 10, 8)) is False


def test_is_teaching_day(calendar: AcademicCalendar) -> None:
    fall = calendar.semesters[1]
    assert fall.is_teaching_day(date(2026, 9, 22)) is True  # 周二，正常上课
    assert fall.is_teaching_day(date(2026, 9, 25)) is False  # 中秋假日
    assert fall.is_teaching_day(date(2026, 9, 26)) is False  # 周六 + 假日
    assert fall.is_teaching_day(date(2026, 9, 12)) is False  # 普通周六
    assert fall.is_teaching_day(date(2026, 8, 30)) is False  # 教学范围外
    assert fall.is_teaching_day(date(2026, 12, 26)) is False


def test_makeup_day_counts_as_teaching_day(calendar: AcademicCalendar) -> None:
    fall = calendar.semesters[1]
    # 调休补班日即使是周日也算上课。
    assert fall.is_teaching_day(date(2026, 9, 20)) is True


def test_spring_makeup_days(calendar: AcademicCalendar) -> None:
    spring = calendar.semesters[0]
    assert {date(2026, 3, 28), date(2026, 5, 9)} <= spring.makeup_days()
    assert spring.is_teaching_day(date(2026, 4, 5)) is False  # 清明假期内的周日
    assert spring.is_holiday(date(2026, 4, 4)) is True


# --------------------------------------------------------------------------- #
# AcademicCalendar 查询
# --------------------------------------------------------------------------- #
def test_current_and_semester_for(calendar: AcademicCalendar) -> None:
    assert calendar.current(date(2026, 9, 22)) is calendar.semesters[1]
    assert calendar.current(date(2026, 4, 1)) is calendar.semesters[0]
    assert calendar.current(date(2026, 1, 15)) is None  # 寒暑假之间


def test_week_of_returns_semester_and_week(calendar: AcademicCalendar) -> None:
    result = calendar.week_of(date(2026, 9, 22))
    assert result is not None
    semester, week = result
    assert semester.name == "2026年秋季"
    assert week == 4
    assert calendar.week_of(date(2026, 1, 15)) is None


def test_next_event(calendar: AcademicCalendar) -> None:
    event = calendar.next_event(date(2026, 9, 22))
    assert event is not None
    assert "中秋节放假" in event.title
    assert event.start == date(2026, 9, 25)

    # 进行中的事件优先于更晚的事件（国庆 10/1-10/7）。
    ongoing = calendar.next_event(date(2026, 10, 3))
    assert ongoing is not None and "国庆节放假" in ongoing.title

    # 所有事件结束后返回 None。
    assert calendar.next_event(date(2030, 1, 1)) is None


def test_dataclasses_are_constructible() -> None:
    event = CalendarEvent(title="x", start=date(2026, 1, 1))
    assert event.end is None
    semester = Semester(name="s", start=date(2026, 1, 1), end=date(2026, 2, 1))
    assert semester.events == []
    assert AcademicCalendar().semesters == []