"""真实 ps.xls（脱敏）离线测试：校准编码、列映射、多 meeting pattern、节次换算。

fixture ``ps_real_sanitized.xls`` 是 2026-08-30 从 SIS 手动导出的真实
``ps.xls``（2026 秋学期）的**脱敏**副本：仅教师姓名替换为「教师A」..「教师I」，
课程代码 / 课程名称 / 日期 / 星期和时间 / 教室 / 状态 与字节结构保持原样。

本文件锁定真实样本证实的格式事实；与合成 fixture（``ps.xls``）的行为差异在
各测试注释与 :func:`test_synthetic_vs_real_differences` 中说明。
"""

from __future__ import annotations

import re
from datetime import date, time

import pytest

from westlake_survival.ical import courses_to_ical
from westlake_survival.sis import parser as parser_mod
from westlake_survival.sis.parser import (
    PERIOD_SCHEDULE,
    parse_ps_xls,
    slot_to_periods,
)


# --------------------------------------------------------------------------- #
# 编码 / HTML 伪装 / 缺 </tr>
# --------------------------------------------------------------------------- #
def test_real_encoding_is_utf8(ps_real_bytes: bytes):
    """真实导出为 UTF-8（无 BOM），首选解码分支即命中。"""
    assert not ps_real_bytes.startswith(b"\xef\xbb\xbf")  # 无 BOM
    text = ps_real_bytes.decode("utf-8")  # 不抛即通过
    assert 'charset=utf-8' in text
    # GBK 解码会失败，证明首选分支确有必要。
    with pytest.raises(UnicodeDecodeError):
        ps_real_bytes.decode("gbk")


def test_real_html_disguised_as_xls(ps_real_text: str):
    """文件是 HTML 伪装的 .xls：DOCTYPE + PeopleSoft 版权注释 + <table>。"""
    assert ps_real_text.lstrip().startswith("<!DOCTYPE html>")
    assert "Oracle and/or its affiliates" in ps_real_text
    assert "<table" in ps_real_text.lower()


def test_real_missing_closing_tr(ps_real_bytes: bytes):
    """真实导出缺 ``</tr>``：11 个 <tr，仅 1 个 </tr>（表头行闭合）。"""
    assert ps_real_bytes.count(b"<tr") == 11
    assert ps_real_bytes.count(b"</tr>") == 1


def test_real_multi_value_uses_br(ps_real_bytes: bytes):
    """多 meeting pattern 以 ``<br />`` 分隔（共 107 个）。"""
    assert ps_real_bytes.count(b"<br />") == 107


# --------------------------------------------------------------------------- #
# 表头列映射：10 列（8 有值 + 2 空）
# --------------------------------------------------------------------------- #
def test_real_header_maps_all_valued_columns(ps_real_text: str):
    header, rows = parser_mod._parse_tables(ps_real_text)
    assert header is not None
    assert len(header) == 10
    # 末两列为空表头（&nbsp;），不参与映射。
    assert header[8] == "" and header[9] == ""
    mapping = parser_mod._map_columns(header)
    assert mapping == {
        0: "class_section",
        1: "course_code",
        2: "title",
        3: "date_range",
        4: "time_slot",
        5: "room",
        6: "teacher",
        7: "status",
    }
    assert len(rows) == 10  # 10 门课各一行


def test_real_header_row_not_treated_as_data(ps_real_text: str):
    """表头行由 <th> 承载，且数据行都不会被误判成表头。"""
    header, rows = parser_mod._parse_tables(ps_real_text)
    assert parser_mod._looks_like_header(header) is True
    for row in rows:
        assert parser_mod._looks_like_header(row) is False


# --------------------------------------------------------------------------- #
# 解析结果：门课数 / 各列字段
# --------------------------------------------------------------------------- #
EXPECTED_CODES = {
    "CST2000",
    "CST4801",
    "CST4806",
    "HUM1024",
    "HUM1029",
    "MATH1009",
    "PHY1004",
    "PHY1009",
    "POL1003",
    "POL1012",
}


def test_real_parses_all_courses(ps_real_bytes: bytes):
    """10 门课展开为 13 条节次（PHY1004 ×2、PHY1009 ×3，其余各 1）。"""
    sessions = parse_ps_xls(ps_real_bytes)
    assert len(sessions) == 13
    assert {s.course_code for s in sessions} == EXPECTED_CODES


def test_real_column_fields(ps_real_bytes: bytes):
    """逐列核对 CST2000 的字段（课程名/教室/教师占位符/状态/日期）。"""
    sessions = parse_ps_xls(ps_real_bytes)
    cst2000 = [s for s in sessions if s.course_code == "CST2000"]
    assert len(cst2000) == 1
    session = cst2000[0]
    assert session.title == "离散数学"
    assert session.room == "云谷校区E13-509"
    assert session.teacher == "教师A"
    assert session.weekday == 4
    assert session.start_time == time(13, 30)
    assert session.end_time == time(15, 5)
    assert session.date_start == date(2026, 9, 3)
    assert session.date_end == date(2026, 12, 24)
    # 班级列（class_section）与状态列保留在 raw 中。
    assert session.raw["class_section"] == "1203"
    assert session.raw["status"] == "已注册"
    # 时间列是「文字星期 + 真实时刻」，非节次编号。
    assert session.raw["time_slot"] == "星期四 13:30 到 15:05"


def test_real_status_column_is_yizhuce(ps_real_bytes: bytes):
    """真实状态列值为「已注册」（合成 fixture 用「已选」）。"""
    sessions = parse_ps_xls(ps_real_bytes)
    assert {s.raw["status"] for s in sessions} == {"已注册"}


def test_real_teacher_placeholders_deduped(ps_real_bytes: bytes):
    """教师列重复出现同一批姓名，去重后以「、」连接。"""
    sessions = parse_ps_xls(ps_real_bytes)
    teachers = {s.teacher for s in sessions}
    assert "教师G、教师H" in teachers  # PHY1004 / PHY1009 两位教师去重
    assert "待定" in teachers  # POL1003 教师未定
    # 脱敏后不应残留任何真实姓名拼音。
    for s in sessions:
        assert not re.search(r"[A-Za-z]{4,}", s.teacher)


# --------------------------------------------------------------------------- #
# 日期 / 时间解析
# --------------------------------------------------------------------------- #
def test_real_date_and_time_parsing(ps_real_bytes: bytes):
    """日期为 ``YYYY/MM/DD - YYYY/MM/DD``；时间为「星期X HH:MM 到 HH:MM」。"""
    sessions = parse_ps_xls(ps_real_bytes)
    by_code = {s.course_code: s for s in sessions if s.course_code != "PHY1009"}
    math = by_code["MATH1009"]
    assert (math.date_start, math.date_end) == (date(2026, 8, 31), date(2026, 12, 21))
    assert math.weekday == 1 and math.start_time == time(8, 0)
    # 单次课：形势与政策 Ⅲ 只有 2 周范围（2026/11/11 - 2026/11/25）。
    pol = by_code["POL1003"]
    assert (pol.date_start, pol.date_end) == (date(2026, 11, 11), date(2026, 11, 25))
    assert pol.weekday == 3


# --------------------------------------------------------------------------- #
# 多 meeting pattern
# --------------------------------------------------------------------------- #
def test_real_multi_pattern_expansion(ps_real_bytes: bytes):
    """PHY1009 一行 3 个 pattern（2 个周一不同教室 + 1 个周四）。"""
    sessions = parse_ps_xls(ps_real_bytes)
    phy1009 = [s for s in sessions if s.course_code == "PHY1009"]
    assert len(phy1009) == 3
    monday = sorted((s for s in phy1009 if s.weekday == 1), key=lambda s: s.room)
    assert [s.room for s in monday] == ["云谷校区E13-209", "云谷校区H6-201"]
    assert {s.start_time for s in monday} == {time(13, 30)}
    thursday = next(s for s in phy1009 if s.weekday == 4)
    assert thursday.room == "云谷校区E13-209"
    assert thursday.start_time == time(16, 10)
    # 教室与 pattern 一一对应（未错配）。
    assert thursday.date_start == date(2026, 9, 3)


def test_real_multi_pattern_pairing_phy1004(ps_real_bytes: bytes):
    """PHY1004 一行 2 个 pattern，日期/时间相同、教室不同。"""
    sessions = parse_ps_xls(ps_real_bytes)
    phy1004 = [s for s in sessions if s.course_code == "PHY1004"]
    assert len(phy1004) == 2
    assert {s.room for s in phy1004} == {"云谷校区E13-209", "云谷校区H6-201"}
    assert {s.start_time for s in phy1004} == {time(15, 10)}
    assert {s.weekday for s in phy1004} == {1}


# --------------------------------------------------------------------------- #
# 节次时间表：真实时刻全部落在官方 13 节边界上
# --------------------------------------------------------------------------- #
def test_period_schedule_has_13_periods():
    assert len(PERIOD_SCHEDULE) == 13
    # 首末节与官方对照表一致。
    assert PERIOD_SCHEDULE[0] == (8, 0, 8, 45)
    assert PERIOD_SCHEDULE[-1] == (20, 10, 20, 55)


def test_real_sessions_map_to_official_periods(ps_real_bytes: bytes):
    """真实样本 13 条节次的起止时刻全部命中官方节次边界。"""
    sessions = parse_ps_xls(ps_real_bytes)
    for session in sessions:
        assert session.periods is not None, (session.course_code, session.start_time)


def test_slot_to_periods_rejects_off_grid():
    assert slot_to_periods(time(13, 30), time(15, 5)) == (6, 7)
    assert slot_to_periods(time(8, 0), time(10, 35)) == (1, 3)
    # 不在节次边界上 → None（不猜测）。
    assert slot_to_periods(time(12, 0), time(13, 0)) is None
    # 结束早于开始 → None。
    assert slot_to_periods(time(15, 5), time(13, 30)) is None


# --------------------------------------------------------------------------- #
# 与 schedule.ics（westlake-ics 用同一样本生成）对照
# --------------------------------------------------------------------------- #
def test_real_ical_first_occurrences_match_reference(ps_real_bytes: bytes):
    """3 门课的首次上课日期/时刻与参照 schedule.ics 一致。

    参照文件由 westlake-ics 的 ``ps2ics.py`` 用同一份 ``ps.xls`` 生成
    （Asia/Shanghai、RRULE 周循环）。这里校验本模块的逐日展开首日与之对齐。
    """
    reference = {
        # (课程代码, 星期, 起, 止) -> 首次上课日
        ("CST2000", 4, "1330", "1505"): "20260903",
        ("CST4801", 2, "1610", "1745"): "20260901",
        ("POL1003", 3, "1330", "1555"): "20261111",
    }
    sessions = parse_ps_xls(ps_real_bytes)
    ical = courses_to_ical(sessions)
    first_days: dict[tuple, str] = {}
    for block in ical.split("BEGIN:VEVENT")[1:]:
        block = block.split("END:VEVENT")[0]
        code_match = re.search(r"UID:wl-sis-([A-Z]+\d+)-(\d)-", block)
        if not code_match:
            continue
        code, weekday = code_match.group(1), int(code_match.group(2))
        start = re.search(r"DTSTART:\d{8}T(\d{4})", block).group(1)
        end = re.search(r"DTEND:\d{8}T(\d{4})", block).group(1)
        day = re.search(r"DTSTART:(\d{8})T", block).group(1)
        key = (code, weekday, start, end)
        if key in reference and (key not in first_days or day < first_days[key]):
            first_days[key] = day
    # 三个被抽查的 key 都应出现，且首日与参照一致。
    assert set(reference) <= set(first_days)
    for key, expected_day in reference.items():
        assert first_days[key] == expected_day, (key, first_days[key])


# --------------------------------------------------------------------------- #
# 合成 fixture vs 真实样本的行为差异
# --------------------------------------------------------------------------- #
def test_synthetic_vs_real_differences(ps_xls_bytes: bytes, ps_real_bytes: bytes):
    """合成 fixture 与真实样本的差异（说明为何需要真实样本校准）。

    - 合成表头用「日期 / 时间」，真实用「开始/结束日期 / 星期和时间」；
      真实表头 10 列（末两列空），合成为 8 列。
    - 合成状态值为「已选」，真实为「已注册」。
    - 合成教师为纯中文名，真实为「中文名 (Pinyin)」且跨 pattern 重复。
    - 真实样本多 pattern 用 ``<br />`` + CRLF，合成用 ``<br>``。
    两者经同一解析器均能正确解析（列语义一致），故 parser 无需为真实样本
    特化；差异仅体现在原始文本形态。
    """
    synthetic = parse_ps_xls(ps_xls_bytes)
    real = parse_ps_xls(ps_real_bytes)
    assert {s.raw["status"] for s in synthetic} == {"已选"}
    assert {s.raw["status"] for s in real} == {"已注册"}
    # 真实表头关键字与合成不同（真实 10 列、末两列空），但都命中同一组规范列名。
    syn_header, _ = parser_mod._parse_tables(ps_xls_bytes.decode("utf-8"))
    real_header, _ = parser_mod._parse_tables(ps_real_bytes.decode("utf-8"))
    assert syn_header != real_header
    assert len(real_header) == 10 and len(syn_header) == 8
    assert parser_mod._map_columns(syn_header) == parser_mod._map_columns(real_header)