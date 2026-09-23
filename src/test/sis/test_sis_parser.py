"""sis.parser 离线测试：ps.xls（缺 </tr>）与 HTML 网格解析。"""

from __future__ import annotations

from datetime import date, time

import pytest

from westlake_survival.exceptions import ParseError
from westlake_survival.sis.parser import (
    ClassSession,
    _expand_fields,
    parse_date_range,
    parse_ps_xls,
    parse_schedule_html,
    parse_time_slot,
    parse_weeks,
)


# --------------------------------------------------------------------------- #
# 字段解析
# --------------------------------------------------------------------------- #
def test_parse_date_range_slash_dash():
    assert parse_date_range("2026/03/05 - 2026/06/18") == (
        date(2026, 3, 5),
        date(2026, 6, 18),
    )


@pytest.mark.parametrize("sep", ["–", "—", "~", "～", "到", "至"])
def test_parse_date_range_alternate_separators(sep):
    text = f"2026/03/05 {sep} 2026/06/18"
    assert parse_date_range(text) == (date(2026, 3, 5), date(2026, 6, 18))


def test_parse_date_range_single_date_is_self_range():
    assert parse_date_range("2026/04/10") == (date(2026, 4, 10), date(2026, 4, 10))


def test_parse_date_range_unparseable_returns_none():
    assert parse_date_range("待定") is None
    assert parse_date_range("") is None


def test_parse_time_slot_chinese_weekday():
    assert parse_time_slot("星期四 13:30 到 15:55") == (
        4,
        time(13, 30),
        time(15, 55),
    )


def test_parse_time_slot_short_weekday_and_dash():
    assert parse_time_slot("周五 08:00-09:35") == (5, time(8, 0), time(9, 35))


def test_parse_time_slot_without_weekday_defaults_monday():
    assert parse_time_slot("10:40 到 12:15") == (1, time(10, 40), time(12, 15))


def test_parse_time_slot_unparseable_returns_none():
    assert parse_time_slot("时间待定") is None


def test_parse_weeks_range_and_list():
    assert parse_weeks("1-8,10-16周") == tuple([*range(1, 9), *range(10, 17)])
    assert parse_weeks("1,3,5") == (1, 3, 5)
    assert parse_weeks("第2-4周") == (2, 3, 4)


def test_parse_weeks_unparseable_returns_none():
    assert parse_weeks("") is None
    assert parse_weeks("全周") is None


# --------------------------------------------------------------------------- #
# ClassSession.from_row 容错
# --------------------------------------------------------------------------- #
def test_from_row_tolerates_missing_fields():
    session = ClassSession.from_row({})
    assert session.title == ""
    assert session.course_code == ""
    assert session.weekday == 1
    assert session.start_time == time(0, 0)
    assert session.end_time == time(0, 0)
    assert session.date_start.year == 1970
    assert session.weeks is None


def test_from_row_accepts_chinese_aliases():
    session = ClassSession.from_row(
        {
            "课程代码": "CS101",
            "课程名称": "计算机程序设计",
            "日期": "2026/03/05 - 2026/06/18",
            "时间": "星期四 13:30 到 15:55",
            "教室": "H6-303",
            "教师": "张三",
        }
    )
    assert session.course_code == "CS101"
    assert session.title == "计算机程序设计"
    assert session.weekday == 4
    assert session.start_time == time(13, 30)
    assert session.room == "H6-303"
    assert session.teacher == "张三"


def test_from_row_cleans_and_dedupes_teacher():
    session = ClassSession.from_row({"教师": "张三\n李四, 张三"})
    assert session.teacher == "张三、李四"


# --------------------------------------------------------------------------- #
# ps.xls（关键：行末缺 </tr>）
# --------------------------------------------------------------------------- #
def test_ps_xls_parses_all_courses(ps_xls_bytes):
    sessions = parse_ps_xls(ps_xls_bytes)
    codes = {s.course_code for s in sessions}
    assert codes == {"CS101", "PHY200", "EST2005", "SEM101", "PE100"}


def test_ps_xls_missing_tr_does_not_merge_rows(ps_xls_bytes):
    """核心回归：缺 </tr> 时不能把多行并成一行。"""
    sessions = parse_ps_xls(ps_xls_bytes)
    cs101 = [s for s in sessions if s.course_code == "CS101"]
    # CS101 有两个 meeting pattern（周四 + 周五）。
    assert len(cs101) == 2
    assert {s.weekday for s in cs101} == {4, 5}
    # 若行被错误合并，CS101 的教室会串到别的课程上。
    phy = next(s for s in sessions if s.course_code == "PHY200")
    assert phy.room == "A-101"
    assert phy.teacher == "王五"


def test_ps_xls_multi_pattern_pairing(ps_xls_bytes):
    sessions = parse_ps_xls(ps_xls_bytes)
    cs101 = sorted(
        (s for s in sessions if s.course_code == "CS101"), key=lambda s: s.weekday
    )
    thursday, friday = cs101
    assert thursday.room == "H6-303"
    assert thursday.start_time == time(13, 30)
    assert thursday.end_time == time(15, 55)
    assert friday.room == "H6-305"
    assert friday.start_time == time(8, 0)
    assert friday.end_time == time(9, 35)


def test_ps_xls_single_date_session(ps_xls_bytes):
    sessions = parse_ps_xls(ps_xls_bytes)
    seminar = next(s for s in sessions if s.course_code == "SEM101")
    assert seminar.date_start == date(2026, 4, 10)
    assert seminar.date_end == date(2026, 4, 10)
    assert seminar.weekday == 5


def test_ps_xls_duplicate_room_pattern_kept_as_two(ps_xls_bytes):
    """EST2005 两个 pattern 日期相同、教室不同，应展开成 2 条。"""
    sessions = parse_ps_xls(ps_xls_bytes)
    est = [s for s in sessions if s.course_code == "EST2005"]
    assert len(est) == 2
    assert {s.room for s in est} == {"H6-303", "H6-305"}
    assert {s.start_time for s in est} == {time(13, 30), time(15, 10)}


def test_ps_xls_bytes_and_text_equivalent(ps_xls_bytes, ps_xls_text):
    assert parse_ps_xls(ps_xls_bytes) == parse_ps_xls(ps_xls_text)


def test_ps_xls_non_table_raises():
    with pytest.raises(ParseError):
        parse_ps_xls(b"this is not a table at all")


# --------------------------------------------------------------------------- #
# HTML 网格
# --------------------------------------------------------------------------- #
def test_parse_schedule_html_grid(schedule_grid_html):
    sessions = parse_schedule_html(schedule_grid_html)
    codes = {s.course_code for s in sessions}
    assert codes == {"CS101", "PHY200"}
    cs = next(s for s in sessions if s.course_code == "CS101")
    assert cs.title == "计算机程序设计"
    assert cs.weekday == 4
    assert cs.room == "H6-303"
    assert cs.teacher == "张三"


def test_parse_schedule_html_empty_raises():
    with pytest.raises(ParseError):
        parse_schedule_html("")


def test_parse_schedule_html_unparseable_raises():
    with pytest.raises(ParseError):
        parse_schedule_html("<html><body><p>没有课程</p></body></html>")


def test_parse_schedule_html_text_fallback():
    """无表格时，纯文本兜底仍能抓出日期范围 + 时间段。"""
    html = (
        "<html><body><div>"
        "计算机程序设计 CS101 2026/03/05 - 2026/06/18 星期四 13:30 到 15:55"
        "</div></body></html>"
    )
    sessions = parse_schedule_html(html)
    assert len(sessions) == 1
    assert sessions[0].weekday == 4
    assert sessions[0].date_start == date(2026, 3, 5)


def test_parse_schedule_html_td_header_row():
    """PeopleSoft fluid 网格有时用 <td> 承载列头，而非 <th>。"""
    html = (
        "<table>"
        "<tr><td>课程代码</td><td>课程名称</td><td>日期</td><td>时间</td>"
        "<td>教室</td><td>教师</td></tr>"
        "<tr><td>CS101</td><td>计算机程序设计</td>"
        "<td>2026/03/05 - 2026/06/18</td><td>星期四 13:30 到 15:55</td>"
        "<td>H6-303</td><td>张三</td></tr>"
        "</table>"
    )
    sessions = parse_schedule_html(html)
    assert len(sessions) == 1
    assert sessions[0].course_code == "CS101"
    assert sessions[0].weekday == 4


def test_parse_schedule_html_course_name_with_time_word_not_header():
    """课程名含「时间」二字不应导致数据行被误判成表头。"""
    html = (
        "<table>"
        "<tr><td>课程代码</td><td>课程名称</td><td>日期</td><td>时间</td></tr>"
        "<tr><td>STA100</td><td>时间序列分析</td>"
        "<td>2026/03/05 - 2026/06/18</td><td>星期四 13:30 到 15:55</td></tr>"
        "</table>"
    )
    sessions = parse_schedule_html(html)
    assert len(sessions) == 1
    assert sessions[0].title == "时间序列分析"


def test_parse_ps_xls_course_name_with_time_word_not_header(ps_xls_bytes):
    """ps.xls 里混入含「时间」的课程名不应被当作表头剔除。"""
    sessions = parse_ps_xls(ps_xls_bytes)
    assert any(s.course_code == "SEM101" for s in sessions)


# --------------------------------------------------------------------------- #
# 缓存往返
# --------------------------------------------------------------------------- #
def test_session_dict_roundtrip(ps_xls_bytes):
    sessions = parse_ps_xls(ps_xls_bytes)
    restored = [ClassSession.from_dict(s.to_dict()) for s in sessions]
    assert restored == sessions


# --------------------------------------------------------------------------- #
# _expand_fields：多 pattern 与教室配对
# --------------------------------------------------------------------------- #
def test_expand_fields_pairs_rooms_in_order():
    """2 pattern + 2 教室：按出现顺序一一配对（既有行为）。"""
    sessions = _expand_fields(
        {
            "title": "计算机程序设计",
            "course_code": "CS101",
            "date_range": "2026/03/05 - 2026/06/18\n\n2026/03/06 - 2026/06/19",
            "time_slot": "星期四 13:30 到 15:55\n\n星期五 08:00 到 09:35",
            "room": "H6-303\n\nH6-305",
        }
    )
    assert len(sessions) == 2
    assert [s.room for s in sessions] == ["H6-303", "H6-305"]


def test_expand_fields_fewer_rooms_than_patterns_blanks_extra():
    """2 pattern + 1 教室：第二行 room 为空，不得回落到第一个教室。"""
    sessions = _expand_fields(
        {
            "title": "计算机程序设计",
            "course_code": "CS101",
            "date_range": "2026/03/05 - 2026/06/18\n\n2026/03/06 - 2026/06/19",
            "time_slot": "星期四 13:30 到 15:55\n\n星期五 08:00 到 09:35",
            "room": "H6-303",
        }
    )
    assert len(sessions) == 2
    assert sessions[0].room == "H6-303"
    assert sessions[1].room == ""
    # 两个 pattern 的日期/时间仍正确配对，未被教室影响。
    assert sessions[1].weekday == 5
    assert sessions[1].date_start == date(2026, 3, 6)