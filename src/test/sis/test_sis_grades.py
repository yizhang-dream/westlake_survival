"""``westlake_survival.sis.grades`` 离线测试（网络层打桩）。

注意：``sis/__init__`` 把函数 ``grades`` 重导出到包命名空间，``sis.grades``
属性是**函数**而非子模块；故这里用 :func:`importlib.import_module` 取模块。
"""

from __future__ import annotations

import importlib

import pytest

from westlake_survival.exceptions import OffCampusError
from westlake_survival.sis.grades import (
    GRADES_COMPONENT,
    GRADES_GRID_ID,
    Grade,
    grades,
)

grades_mod = importlib.import_module("westlake_survival.sis.grades")


def _patch_page(monkeypatch, html: str, captured: list | None = None):
    """打桩 ``pages.fetch_page``，返回固定 HTML 并记录组件名。"""

    def fake(component: str, *, query: str = "") -> str:
        if captured is not None:
            captured.append((component, query))
        return html

    monkeypatch.setattr(grades_mod.pages, "fetch_page", fake)


def test_grades_component_and_grid_constants():
    assert GRADES_COMPONENT == "WL_CUSTOMIZE_MENU.WL_STU_GRADE_COM.GBL"
    assert GRADES_GRID_ID == "WL_STU_ENRL_V2"


def test_grades_parses_current_and_history_terms(monkeypatch, grades_real_html):
    """真实脱敏页面：7 行成绩，覆盖当前学期与历史学期。"""
    captured: list = []
    _patch_page(monkeypatch, grades_real_html, captured)

    items = grades()

    assert captured == [(GRADES_COMPONENT, "")]
    assert len(items) == 7
    assert items[0].course_code == "CST 2000"
    assert items[0].term == "2026-2027 Fall Term"
    assert items[0].grade == ""  # 未出分保持空串，不臆造
    terms = {g.term for g in items}
    assert "2025-2026 Fall Term" in terms
    assert "2025-2026 夏季学期" in terms


def test_grades_keeps_pass_grades(monkeypatch, grades_real_html):
    """等级制 ``P`` 忠实保留（不试图折算 GPA）。"""
    _patch_page(monkeypatch, grades_real_html)
    items = grades()
    assert any(g.grade == "P" for g in items)
    p = next(g for g in items if g.grade == "P")
    assert p.course_code == "CPE 1000"
    assert p.credits == "1.0"


def test_grade_from_row_maps_columns():
    row = {
        "Course Code": " CST 2000 ",
        "Course Title": "Discrete Mathematics",
        "Term": "2026-2027 Fall Term",
        "Grade": "A",
        "Credits": "2.0",
    }
    grade = Grade.from_row(row)
    assert grade == Grade("CST 2000", "Discrete Mathematics", "2026-2027 Fall Term", "A", "2.0")
    assert grade.to_dict()["course_code"] == "CST 2000"


def test_grade_from_row_missing_columns_default_empty():
    grade = Grade.from_row({})
    assert grade == Grade()


def test_grades_skips_rows_without_course(monkeypatch):
    html = (
        "<table id='WL_STU_ENRL_V2'><thead><tr>"
        "<th>Course Code</th><th>Term</th><th>Grade</th></tr></thead><tbody>"
        "<tr><td>A</td><td>T</td><td>B</td></tr>"
        "<tr><td></td><td></td><td></td></tr>"
        "</tbody></table>"
    )
    _patch_page(monkeypatch, html)
    items = grades()
    assert len(items) == 1
    assert items[0].course_code == "A"


def test_grades_empty_grid_returns_empty(monkeypatch):
    html = (
        "<table id='WL_STU_ENRL_V2'><thead><tr><th>Course Code</th></tr></thead>"
        "<tbody class='ps_grid-body'></tbody></table>"
    )
    _patch_page(monkeypatch, html)
    assert grades() == []


def test_grades_propagates_offcampus(monkeypatch):
    def boom(component, *, query=""):
        raise OffCampusError("校外")

    monkeypatch.setattr(grades_mod.pages, "fetch_page", boom)
    with pytest.raises(OffCampusError):
        grades()


def test_grades_exposed_on_package(monkeypatch, grades_real_html):
    """``westlake_survival.sis`` 顶层导出 grades / Grade。"""
    from westlake_survival import sis

    assert sis.grades is grades
    assert sis.Grade is Grade
