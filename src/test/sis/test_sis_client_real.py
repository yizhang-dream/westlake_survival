"""真实登录链路（2026-09-23 实测）产物驱动：课表页 DOM、精确 ICAction、
学期参数构造、两段式导出请求形态。

本文件取代「待有账号校准」的历史 TODO；上一轮仅 ``ps.xls`` 导出文件格式
是实测的，本文件把**登录链路三项**（课表页真实路径/DOM、导出按钮
``ICAction``、学期参数名）也固化为离线回归：

- 课表页真实路径是 ``SSR_STUDENT_FL.SSR_COMPONENT_FL.GBL?Page=SSR_VW_CLASS_FL``
  （fluid 网格 ``WL_STDNT_ENR_VW``）；原假设 ``SSR_MD_SP_FL.GBL`` 对学生
  未授权（实测 "not authorized"）。
- 页面**没有学期选择控件**，``STRM`` 参数名假设不成立；``term`` 参数不
  产生任何查询参数。
- 导出是两段式：``POST ICAction=WL_STDNT_ENR_VW$hexcel$0`` → 响应页含
  ``window.open('...ps.xls')`` → ``GET`` 该链接拿文件。

数据样本：2026-09-23 当日登录态抓取的页面与当场导出的 ``ps.xls``
（教师名等已脱敏，见 ``conftest.py``）。注意：当日真实课表为 **10 门课 /
15 条节次**（2026-08-30 旧样本为 13 条；差异源于选课变动），「页面解析 =
当场导出解析」的一致性是本文件与真实 E2E 共同锁定的事实。
"""

from __future__ import annotations

from datetime import date, time

import pytest

from westlake_survival.exceptions import ActionError
from westlake_survival.sis.client import (
    SIS_URLS,
    SISClient,
    _find_export_action,
    _find_export_url,
    _find_form_action,
)
from westlake_survival.sis.parser import parse_ps_xls, parse_schedule_html

from sis_fakes import FakeResponse, FakeSession

# 实测当日（2026-09-23）真实课表：10 门课 / 15 条节次（PHY1004 ×3、
# PHY1009 ×4，其余各 1）。旧样本（2026-08-30）为 13 条，选课变动所致。
EXPECTED_COURSES = 10
EXPECTED_SESSIONS = 15


# --------------------------------------------------------------------------- #
# 真实 fluid DOM 解析
# --------------------------------------------------------------------------- #
def test_real_grid_parses_courses_and_sessions(schedule_real_html: str):
    """真实页面网格解析：10 门课 / 15 条节次（ENG locale）。"""
    sessions = parse_schedule_html(schedule_real_html)
    assert len(sessions) == EXPECTED_SESSIONS
    assert len({s.course_code for s in sessions}) == EXPECTED_COURSES


def test_real_grid_english_headers_mapped(schedule_real_html: str):
    """ENG 表头（Course Title 等）全部映射到规范列名。"""
    from westlake_survival.sis import parser as parser_mod

    header, rows = parser_mod._parse_tables(schedule_real_html)
    assert header is not None
    assert header[:8] == [
        "Class",
        "Course Code",
        "Course Title",
        "Start/End Dates",
        "Time",
        "Room",
        "Instructor",
        "Status",
    ]
    assert parser_mod._map_columns(header) == {
        0: "class_section",
        1: "course_code",
        2: "title",
        3: "date_range",
        4: "time_slot",
        5: "room",
        6: "teacher",
        7: "status",
    }
    # 10 门课各一行（10 单元格）；页面另有一行站点残留的单单元格杂项行，
    # 不含课程信息，会在展开时被丢弃。
    course_rows = [row for row in rows if len(row) == 10]
    assert len(course_rows) == EXPECTED_COURSES


def test_real_grid_english_time_slots_parsed(schedule_real_html: str):
    """ENG 时间「Thurs 13:30 To 15:05」解析为周四 + 真实时刻（非 00:00）。"""
    sessions = parse_schedule_html(schedule_real_html)
    assert all(s.start_time != time(0, 0) for s in sessions)
    cst2000 = next(s for s in sessions if s.course_code == "CST2000")
    assert (cst2000.weekday, cst2000.start_time, cst2000.end_time) == (
        4,
        time(13, 30),
        time(15, 5),
    )
    assert (cst2000.date_start, cst2000.date_end) == (date(2026, 9, 3), date(2026, 12, 24))
    assert cst2000.raw["time_slot"] == "Thurs 13:30 To 15:05"
    assert cst2000.raw["status"] == "Enrolled"


def test_real_grid_multi_pattern_expansion(schedule_real_html: str):
    """同一行多个 meeting pattern（``<br /> <br />`` 分隔）展开为多条节次。"""
    sessions = parse_schedule_html(schedule_real_html)
    phy1004 = [s for s in sessions if s.course_code == "PHY1004"]
    phy1009 = [s for s in sessions if s.course_code == "PHY1009"]
    assert len(phy1004) == 3 and len(phy1009) == 4
    # 教室按出现顺序与 pattern 一一配对，不回落错配。
    assert [s.room for s in phy1004] == [
        "E13-209,Yungu",
        "H6-201,Yungu Campus",
        "H6-203,Yungu Campus",
    ]
    assert {s.weekday for s in phy1009} == {1, 4}


def test_real_grid_teachers_are_placeholders(schedule_real_html: str):
    """脱敏 fixture 的教师字段只含占位符（真名不得回流）。"""
    import re

    sessions = parse_schedule_html(schedule_real_html)
    assert "教师G、教师H" in {s.teacher for s in sessions}  # 跨 pattern 去重
    for s in sessions:
        assert not re.search(r"[A-Za-z]{4,}", s.teacher), s.teacher


def test_real_grid_sessions_map_to_official_periods(schedule_real_html: str):
    """实测 15 条节次的起止时刻全部落在官方 13 节边界上。"""
    sessions = parse_schedule_html(schedule_real_html)
    for s in sessions:
        assert s.periods is not None, (s.course_code, s.start_time)


# --------------------------------------------------------------------------- #
# 精确 ICAction 匹配
# --------------------------------------------------------------------------- #
def test_find_export_action_precise_hexcel_from_real_page(schedule_real_html: str):
    """真实页面上精确命中网格导出按钮 ``WL_STDNT_ENR_VW$hexcel$0``。"""
    action = _find_export_action(schedule_real_html)
    assert action == {"ICAction": "WL_STDNT_ENR_VW$hexcel$0"}


def test_find_export_action_precise_takes_priority_over_heuristics():
    """页面同时含 ICAction= 与 hexcel 按钮时，精确匹配优先。"""
    html = (
        '<a href="javascript:submitAction_win0(document.win0,\'OTHER$1\')" '
        'ICAction=OTHER$1>x</a>'
        "<a href=\"javascript:pAction_win17(document.win17,'WL_STDNT_ENR_VW$hexcel$0');\">"
        "dl</a>"
    )
    assert _find_export_action(html) == {"ICAction": "WL_STDNT_ENR_VW$hexcel$0"}


# --------------------------------------------------------------------------- #
# 学期参数构造：真实页面无学期控件，STRM 假设不成立
# --------------------------------------------------------------------------- #
def test_fetch_schedule_html_real_path_and_no_term_param(schedule_real_html):
    """请求打到真实组件页；传 term 也不附加任何学期查询参数。"""
    session = FakeSession(
        lambda m, u, k: FakeResponse(200, text=schedule_real_html, url=u)
    )
    client = SISClient(session=session)
    client.fetch_schedule_html(term="2265")
    method, url, kw = session.calls[0]
    assert method == "GET"
    assert url == SIS_URLS["schedule_page"]
    assert "SSR_STUDENT_FL.SSR_COMPONENT_FL.GBL" in url
    assert "Page=SSR_VW_CLASS_FL" in url
    assert "STRM" not in url and "STRM" not in str(kw.get("params"))


def test_schedule_page_menu_is_real_nav_collection():
    """菜单入口常量指向实测的 CS_SSR_MANAGE_CLASSES_NAV 导航集合。"""
    assert "PT_AGSTARTPAGE_NUI.GBL" in SIS_URLS["schedule_page_menu"]
    assert "scname=CS_SSR_MANAGE_CLASSES_NAV" in SIS_URLS["schedule_page_menu"]


# --------------------------------------------------------------------------- #
# 导出请求形态：两段式（POST ICAction → window.open ps.xls → GET）
# --------------------------------------------------------------------------- #
_EXPORT_RESPONSE_PAGE = (
    "<html><head><script>"
    "window.open('https://sis.westlake.edu.cn/psc/CSPRD_3/view/"
    "%7BV2%7dtoken/ps.xls','','');"
    "</script></head><body>ok</body></html>"
)


def _two_phase_session(schedule_real_html: str, xls_bytes: bytes) -> FakeSession:
    """GET 页面 → POST 重渲染页（含下载链接）→ GET 下载文件。"""

    def handler(method, url, kw):
        if method == "GET" and "ps.xls" in url:
            return FakeResponse(
                200,
                text="",
                url=url,
                headers={"Content-Type": "application/vnd.ms-excel"},
                content=xls_bytes,
            )
        if method == "POST":
            assert kw["data"]["ICAction"] == "WL_STDNT_ENR_VW$hexcel$0"
            return FakeResponse(200, text=_EXPORT_RESPONSE_PAGE, url=url)
        return FakeResponse(200, text=schedule_real_html, url=url)

    return FakeSession(handler)


def test_export_two_phase_request_shape(schedule_real_html: str, ps_export_real_bytes: bytes):
    """完整两段式导出：POST 打到页面表单 action，最后 GET 拿 ps.xls。"""
    session = _two_phase_session(schedule_real_html, ps_export_real_bytes)
    client = SISClient(session=session)
    content = client.export_schedule_xls()
    assert content == ps_export_real_bytes
    methods = [c[0] for c in session.calls]
    assert methods == ["GET", "POST", "GET"]
    # POST 携带页面全部隐藏域（页面状态）+ 精确动作 id。
    post_data = session.calls[1][2]["data"]
    assert post_data["ICAction"] == "WL_STDNT_ENR_VW$hexcel$0"
    assert post_data["ICSID"] == "ICSID_SANITIZED"  # 页面隐藏域原样转发
    assert "ICStateNum" in post_data
    # POST 打到课表页主表单的 action（裸 GBL，不带页面查询参数）。
    post_url = session.calls[1][1]
    assert "SSR_STUDENT_FL.SSR_COMPONENT_FL.GBL" in post_url
    assert "Page=SSR_VW_CLASS_FL" not in post_url
    # 第二段 GET 打到 window.open 给出的 ps.xls 链接。
    download_url = session.calls[2][1]
    assert "/view/" in download_url and download_url.endswith("ps.xls")


def test_export_form_action_extracted_from_real_page(schedule_real_html: str):
    """从真实页面提取主表单 action（导出 POST 的真实目标）。"""
    action_url = _find_form_action(schedule_real_html)
    assert action_url is not None
    assert "SSR_STUDENT_FL.SSR_COMPONENT_FL.GBL" in action_url
    assert "&amp;" not in action_url


def test_find_export_url_from_response_page():
    assert (
        _find_export_url(_EXPORT_RESPONSE_PAGE)
        == "https://sis.westlake.edu.cn/psc/CSPRD_3/view/%7BV2%7dtoken/ps.xls"
    )
    assert _find_export_url("<html>no token</html>") is None
    assert _find_export_url("") is None


def test_export_direct_file_response_fallback(ps_export_real_bytes: bytes):
    """兜底：POST 响应直接就是导出文件（老式行为）时原样返回。"""
    page = (
        "<a href=\"javascript:pAction_win17(document.win17,"
        "'WL_STDNT_ENR_VW$hexcel$0');\">dl</a>"
    )

    def handler(method, url, kw):
        if method == "POST":
            return FakeResponse(
                200,
                text="",
                url=url,
                headers={"Content-Type": "application/vnd.ms-excel"},
                content=ps_export_real_bytes,
            )
        return FakeResponse(200, text=page, url=url)

    session = FakeSession(handler)
    client = SISClient(session=session)
    assert client.export_schedule_xls() == ps_export_real_bytes


def test_export_missing_download_url_raises(schedule_real_html: str):
    """POST 响应既不是文件也没有下载链接 → ActionError。"""

    def handler(method, url, kw):
        if method == "POST":
            return FakeResponse(200, text=schedule_real_html, url=url)
        return FakeResponse(200, text=schedule_real_html, url=url)

    session = FakeSession(handler)
    client = SISClient(session=session)
    with pytest.raises(ActionError) as excinfo:
        client.export_schedule_xls()
    assert "未找到 ps.xls 下载链接" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# 页面解析 = 当场导出解析（2026-09-23 实测一致性的离线回归）
# --------------------------------------------------------------------------- #
def test_page_parse_equals_same_day_export_parse(
    schedule_real_html: str, ps_export_real_bytes: bytes
):
    """同一天抓取的页面与导出文件，逐字段一致（真实 E2E 的离线固化）。"""
    page_sessions = parse_schedule_html(schedule_real_html)
    xls_sessions = parse_ps_xls(ps_export_real_bytes)
    assert len(xls_sessions) == len(page_sessions) == EXPECTED_SESSIONS

    def key(s):
        return (
            s.course_code,
            s.title,
            s.weekday,
            str(s.start_time),
            str(s.end_time),
            str(s.date_start),
            str(s.date_end),
            s.room,
            s.teacher,
        )

    assert sorted(map(key, page_sessions)) == sorted(map(key, xls_sessions))


def test_ical_from_real_page_fixture(schedule_real_html: str):
    """真实页面解析结果可直接生成 ics（逐周展开，VEVENT 数 >= 节次数）。"""
    from westlake_survival.ical import courses_to_ical

    sessions = parse_schedule_html(schedule_real_html)
    ical = courses_to_ical(sessions)
    # ics 按日期范围逐周展开，VEVENT 数必然不少于节次数。
    assert ical.count("BEGIN:VEVENT") >= EXPECTED_SESSIONS
    for s in sessions:
        assert f"UID:wl-sis-{s.course_code}-" in ical
