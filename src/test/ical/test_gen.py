"""ical.gen 离线测试：VEVENT 展开、格式、转义、折行、UID 去重。"""

from __future__ import annotations

import dataclasses

import re
from datetime import date, datetime, time, timezone

import pytest

from westlake_survival.ical import courses_to_ical, save_ics
from westlake_survival.ical.gen import _escape_text, _fold
from westlake_survival.sis import ClassSession

DTSTAMP = datetime(2026, 9, 22, 0, 0, tzinfo=timezone.utc)


def _ical(sessions, **kw) -> str:
    return courses_to_ical(sessions, now=DTSTAMP, **kw)


# --------------------------------------------------------------------------- #
# 结构
# --------------------------------------------------------------------------- #
def test_calendar_wrapper(thursday_course):
    text = _ical([thursday_course])
    assert text.startswith("BEGIN:VCALENDAR\r\n")
    assert text.rstrip("\r\n").endswith("END:VCALENDAR")
    assert "VERSION:2.0" in text
    assert "PRODID:-//westlake_survival//CN" in text
    assert text.count("BEGIN:VEVENT") == text.count("END:VEVENT")


def test_calendar_name_override(thursday_course):
    text = _ical([thursday_course], cal_name="我的课表")
    assert "X-WR-CALNAME:我的课表" in text


# --------------------------------------------------------------------------- #
# 日期展开
# --------------------------------------------------------------------------- #
def test_event_count_matches_expanded_days(thursday_course, monday_course):
    text = _ical([thursday_course, monday_course])
    # 周四 2026-03-05~06-18 共 16 次；周一 03-09~06-15 共 15 次。
    assert text.count("BEGIN:VEVENT") == 16 + 15


def test_single_day_course_generates_one_event(single_day_course):
    text = _ical([single_day_course])
    assert text.count("BEGIN:VEVENT") == 1
    assert "DTSTART:20260410T183000" in text
    assert "DTEND:20260410T200500" in text


def test_dtstart_is_floating_local(single_day_course):
    text = _ical([single_day_course])
    dtstarts = re.findall(r"DTSTART:(\S+)", text)
    assert dtstarts
    for value in dtstarts:
        assert re.fullmatch(r"\d{8}T\d{6}", value), value
        assert not value.endswith("Z")


def test_dates_align_to_weekday(thursday_course):
    text = _ical([thursday_course])
    days = {m[:8] for m in re.findall(r"DTSTART:(\d{8})T", text)}
    # 首末均应为周四。
    assert min(days) == "20260305"
    assert max(days) == "20260618"
    for stamp in days:
        d = date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8]))
        assert d.isoweekday() == 4


def test_summary_location_description(thursday_course):
    text = _ical([thursday_course])
    assert "SUMMARY:计算机程序设计" in text
    assert "LOCATION:H6-303" in text
    assert "DESCRIPTION:张三 / CS101" in text


# --------------------------------------------------------------------------- #
# weeks 过滤
# --------------------------------------------------------------------------- #
def test_weeks_filter_limits_events():
    # 第 1 周周一为 2026-03-02；只上周次 1 和 3。
    session = ClassSession(
        title="限周课程",
        course_code="WK100",
        weekday=1,
        start_time=time(9, 0),
        end_time=time(10, 0),
        date_start=date(2026, 3, 2),
        date_end=date(2026, 3, 30),
        weeks=(1, 3),
    )
    text = _ical([session], week1_monday=date(2026, 3, 2))
    assert text.count("BEGIN:VEVENT") == 2
    assert "DTSTART:20260302T090000" in text  # 第 1 周
    assert "DTSTART:20260316T090000" in text  # 第 3 周
    assert "DTSTART:20260309T090000" not in text  # 第 2 周被过滤


def test_invalid_date_range_produces_no_event():
    session = ClassSession(
        title="无日期",
        course_code="X",
        weekday=1,
        start_time=time(9, 0),
        end_time=time(10, 0),
    )
    text = _ical([session])
    assert "BEGIN:VEVENT" not in text
    assert text.count("BEGIN:VCALENDAR") == 1


def test_week_anchor_uses_global_earliest_date_start():
    """锁定当前锚点语义：第 1 周 = 全局最早 date_start 所在周（不做学期对齐）。

    全局最早课 03-02（周一，即第 1 周周一）；另一课 03-16 起、标称
    ``weeks=(1,)``——按"全局第 1 周"语义，03-16 是第 3 周，不在 weeks 内，
    因此被过滤，不产出任何事件。这正是"最早课从第 2 周起则周号整体偏移"
    这一已知边界条件的直接体现（如需修正应以 SIS 课表页周次为准）。
    """
    earliest = ClassSession(
        title="最早课",
        course_code="EARLY",
        weekday=1,
        start_time=time(9, 0),
        end_time=time(10, 0),
        date_start=date(2026, 3, 2),
        date_end=date(2026, 3, 2),
    )
    later = ClassSession(
        title="较晚课",
        course_code="LATE",
        weekday=1,
        start_time=time(11, 0),
        end_time=time(12, 0),
        date_start=date(2026, 3, 16),
        date_end=date(2026, 3, 16),
        weeks=(1,),
    )
    text = _ical([earliest, later])
    # 最早课无条件产出 1 条；较晚课按全局第 1 周语义被过滤。
    assert text.count("BEGIN:VEVENT") == 1
    assert "DTSTART:20260302T090000" in text
    assert "DTSTART:20260316T110000" not in text


def test_week1_monday_helper_picks_earliest_week():
    """_week1_monday 取全局最早 date_start 所在周的周一。"""
    from westlake_survival.ical.gen import _week1_monday

    early = ClassSession(
        title="A", course_code="A", weekday=4,
        start_time=time(9, 0), end_time=time(10, 0),
        date_start=date(2026, 3, 5), date_end=date(2026, 3, 5),
    )
    later = ClassSession(
        title="B", course_code="B", weekday=1,
        start_time=time(9, 0), end_time=time(10, 0),
        date_start=date(2026, 3, 16), date_end=date(2026, 3, 16),
    )
    # 2026-03-05 是周四，所在周周一为 2026-03-02。
    assert _week1_monday([later, early]) == date(2026, 3, 2)
    assert _week1_monday([]) is None


# --------------------------------------------------------------------------- #
# UID
# --------------------------------------------------------------------------- #
def test_uid_format_and_uniqueness(thursday_course, monday_course):
    text = _ical([thursday_course, monday_course])
    uids = re.findall(r"UID:(\S+)", text)
    assert len(uids) == len(set(uids))
    pattern = re.compile(
        r"wl-sis-(CS101|PHY200)-[1-7]-\d{6}-.+-\d{8}@westlake_survival"
    )
    for uid in uids:
        assert pattern.fullmatch(uid), uid


def test_duplicate_sessions_deduped(thursday_course):
    text = _ical([thursday_course, thursday_course])
    uids = re.findall(r"UID:(\S+)", text)
    assert len(uids) == len(set(uids))
    assert text.count("BEGIN:VEVENT") == 16


# --------------------------------------------------------------------------- #
# 转义与折行
# --------------------------------------------------------------------------- #
def test_escape_text():
    assert _escape_text("a,b;c\\d") == "a\\,b\\;c\\\\d"
    assert _escape_text("line1\nline2") == "line1\\nline2"


def test_summary_escaped_in_output():
    session = ClassSession(
        title="数学,分析; 上",
        course_code="M1",
        weekday=1,
        start_time=time(9, 0),
        end_time=time(10, 0),
        date_start=date(2026, 3, 2),
        date_end=date(2026, 3, 2),
    )
    text = _ical([session])
    assert "SUMMARY:数学\\,分析\\; 上" in text


def test_fold_multibyte_safe():
    line = "SUMMARY:" + "课" * 100  # 每字 3 字节
    folded = _fold(line)
    for physical in folded.split("\r\n"):
        assert len(physical.encode("utf-8")) <= 75
    # 折行后可无损还原。
    assert folded.replace("\r\n ", "") == line


def test_no_physical_line_exceeds_75_bytes(thursday_course):
    text = _ical([thursday_course])
    for physical in text.split("\r\n"):
        assert len(physical.encode("utf-8")) <= 75


# --------------------------------------------------------------------------- #
# save_ics
# --------------------------------------------------------------------------- #
def test_save_ics_writes_file(tmp_path, thursday_course):
    path = save_ics([thursday_course], tmp_path / "sub" / "schedule.ics")
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "BEGIN:VCALENDAR" in content
    assert "BEGIN:VEVENT" in content


def test_save_ics_accepts_str_path(tmp_path, thursday_course):
    path = save_ics([thursday_course], str(tmp_path / "s.ics"))
    assert path.name == "s.ics"


def test_same_slot_different_rooms_not_deduped(thursday_course):
    """同课同日同时段、不同教室（小班）是两个事件，不得被 UID 去重丢弃。"""
    single = _ical([thursday_course])
    other_room = dataclasses.replace(thursday_course, room="H6-305")
    both = _ical([thursday_course, other_room])
    assert both.count("BEGIN:VEVENT") == single.count("BEGIN:VEVENT") * 2
    assert "H6-303" in both and "H6-305" in both
