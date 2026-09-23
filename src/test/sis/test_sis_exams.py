"""``westlake_survival.sis.exams`` 离线测试（网络层打桩）。"""

from __future__ import annotations

import importlib

import pytest

from westlake_survival.exceptions import ActionError
from westlake_survival.sis.exams import (
    EXAMS_COMPONENT,
    EXAMS_GRID_ID,
    EXAMS_QUERY,
    ExamSlot,
    exam_schedule,
)

exams_mod = importlib.import_module("westlake_survival.sis.exams")


def _patch_page(monkeypatch, html: str, captured: list | None = None):
    def fake(component: str, *, query: str = "") -> str:
        if captured is not None:
            captured.append((component, query))
        return html

    monkeypatch.setattr(exams_mod.pages, "fetch_page", fake)


def test_exams_constants():
    assert EXAMS_COMPONENT == "WL_CUSTOMIZE_MENU.WL_EXAM_STU_COM_FL.GBL"
    assert EXAMS_QUERY == "Page=WL_EXAM_STU_FL"
    assert EXAMS_GRID_ID == "WL_EXAM_STU_VW"


def test_exam_schedule_parses_real_page(monkeypatch, exams_real_html):
    """真实脱敏页面：4 门课，用 query 请求 Page=WL_EXAM_STU_FL。"""
    captured: list = []
    _patch_page(monkeypatch, exams_real_html, captured)

    items = exam_schedule()

    assert captured == [(EXAMS_COMPONENT, EXAMS_QUERY)]
    assert len(items) == 4
    assert items[0].course_code == "PHY 1004"
    assert items[0].course_title == "General Physics Laboratory Ⅱ"
    # 考试未排期：日期及之后各列为空串（忠实反映真实数据）。
    assert items[0].date == ""
    assert items[0].time == ""
    assert items[0].venue == ""
    assert items[0].seat == ""


def test_exam_schedule_parses_populated_slot(monkeypatch):
    """已排期行正确映射各列。"""
    html = (
        "<table id='WL_EXAM_STU_VW'><thead><tr>"
        "<th>Course Code</th><th>Course Title</th><th>Date</th><th>Time</th>"
        "<th>Type</th><th>Method</th><th>Venue</th><th>Seat Nbr</th></tr></thead><tbody>"
        "<tr><td>PHY 1004</td><td>General Physics Laboratory Ⅱ</td><td>2027/01/05</td>"
        "<td>09:00 - 11:00</td><td>Final</td><td>Closed Book</td><td>H6-201</td>"
        "<td>42</td></tr>"
        "</tbody></table>"
    )
    _patch_page(monkeypatch, html)
    slot = exam_schedule()[0]
    assert slot.date == "2027/01/05"
    assert slot.time == "09:00 - 11:00"
    assert slot.exam_type == "Final"
    assert slot.method == "Closed Book"
    assert slot.venue == "H6-201"
    assert slot.seat == "42"


def test_examslot_from_row_and_to_dict():
    row = {
        "Course Code": "CST 2000",
        "Course Title": "Discrete Mathematics",
        "Date": "2027/01/06",
        "Time": "13:30 - 15:30",
        "Type": "Final",
        "Method": "Open Book",
        "Venue": "E13-509",
        "Seat Nbr": "7",
    }
    slot = ExamSlot.from_row(row)
    assert slot.to_dict() == {
        "course_code": "CST 2000",
        "course_title": "Discrete Mathematics",
        "date": "2027/01/06",
        "time": "13:30 - 15:30",
        "exam_type": "Final",
        "method": "Open Book",
        "venue": "E13-509",
        "seat": "7",
    }
    assert ExamSlot.from_row({}) == ExamSlot()


def test_exam_schedule_skips_rows_without_course(monkeypatch):
    html = (
        "<table id='WL_EXAM_STU_VW'><thead><tr><th>Course Code</th></tr></thead><tbody>"
        "<tr><td>PHY 1004</td></tr><tr><td></td></tr></tbody></table>"
    )
    _patch_page(monkeypatch, html)
    items = exam_schedule()
    assert len(items) == 1


def test_exam_schedule_empty_grid_returns_empty(monkeypatch):
    html = (
        "<table id='WL_EXAM_STU_VW'><thead><tr><th>Course Code</th></tr></thead>"
        "<tbody class='ps_grid-body'></tbody></table>"
    )
    _patch_page(monkeypatch, html)
    assert exam_schedule() == []


def test_exam_schedule_propagates_unauthorized(monkeypatch):
    def boom(component, *, query=""):
        raise ActionError("not authorized")

    monkeypatch.setattr(exams_mod.pages, "fetch_page", boom)
    with pytest.raises(ActionError):
        exam_schedule()


def test_exams_exposed_on_package():
    from westlake_survival import sis

    assert sis.exam_schedule is exam_schedule
    assert sis.ExamSlot is ExamSlot
