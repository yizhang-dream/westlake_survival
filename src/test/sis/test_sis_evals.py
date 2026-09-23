"""``westlake_survival.sis.evals`` 离线测试（网络层打桩）。

fixture ``evals_grid_sanitized.html`` 自真页裁剪脱敏（2026-09-23 登录态抓取
``WL_CUSTOMIZE_MENU.WL_STU_EVAL_CEN.GBL?page=WL_STU_EVAL_CEN``）：保留网格
``WL_EVAL_WRK`` 的吸顶表头表 + 数据表两张表，抽取 7 行（覆盖两个评估时间
区间：2026 Spring 与 2025 Fall）。脱敏：只保留网格 ``<table>`` 本身（页头
问候语含学生姓名，已整体剔除）；会话令牌已随页头剔除；课程代码 / 课程名称 /
学期 / 班级 / 类别 / 时间 / 状态与 DOM 结构保持原样。无个人 PII。

注意：``sis/__init__`` 未重导出 ``evals``（本模块只新增、未改包导出），故直接
从 ``westlake_survival.sis.evals`` 导入。
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from westlake_survival.exceptions import ActionError, OffCampusError
from westlake_survival.sis.evals import (
    COMPLETED_STATUSES,
    EVALS_COMPONENT,
    EVALS_GRID_ID,
    EVALS_QUERY,
    EvalTask,
    evaluations,
    pending_evaluations,
)

evals_mod = importlib.import_module("westlake_survival.sis.evals")

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def evals_real_html() -> str:
    """真页裁剪脱敏 fixture（7 行，两个时间区间）。"""
    return (FIXTURES / "evals_grid_sanitized.html").read_text(encoding="utf-8")


def _patch_page(monkeypatch, html: str, captured: list | None = None):
    """打桩 ``pages.fetch_page``，返回固定 HTML 并记录 (component, query)。"""

    def fake(component: str, *, query: str = "") -> str:
        if captured is not None:
            captured.append((component, query))
        return html

    monkeypatch.setattr(evals_mod.pages, "fetch_page", fake)


def _grid(rows: str, headers: str = "") -> str:
    """拼一张最小可解析的 ``WL_EVAL_WRK`` 网格（表头 + 数据行）。"""
    if not headers:
        headers = (
            "<th>Term</th><th>Course Code</th><th>Course Title</th>"
            "<th>Class</th><th>Evaluate Category</th><th>Date/Time</th>"
            "<th>Evaluation Status</th>"
        )
    return (
        "<html><body><DIV class='ps_box-grid' id='win3divWL_EVAL_WRK$grid$0'>"
        "<table class='ps_grid-flex'><thead><tr>"
        + headers
        + "</tr></thead><tbody class='ps_grid-body'>"
        + rows
        + "</tbody></table></DIV></body></html>"
    )


# --------------------------------------------------------------------------- #
# 常量与数据模型
# --------------------------------------------------------------------------- #
def test_evals_constants():
    assert EVALS_COMPONENT == "WL_CUSTOMIZE_MENU.WL_STU_EVAL_CEN.GBL"
    assert EVALS_QUERY == "page=WL_STU_EVAL_CEN"
    assert EVALS_GRID_ID == "WL_EVAL_WRK"


def test_completed_statuses_is_frozenset_and_excludes_submit():
    assert isinstance(COMPLETED_STATUSES, frozenset)
    assert "Submit" not in COMPLETED_STATUSES


def test_evaltask_from_row_maps_all_columns():
    row = {
        "Term": " 2026-2027 Fall Term ",
        "Course Code": " ENG1003 ",
        "Course Title": "English Communication Ⅱ",
        "Class": "1010",
        "Evaluate Category": "End",
        "Date/Time": "2026/06/02 10:00 - 2026/06/26 23:59",
        "Evaluation Status": "Submit",
    }
    task = EvalTask.from_row(row)
    assert task == EvalTask(
        term="2026-2027 Fall Term",
        course_code="ENG1003",
        course_title="English Communication Ⅱ",
        class_nbr="1010",
        category="End",
        period_start="2026/06/02 10:00",
        period_end="2026/06/26 23:59",
        period_raw="2026/06/02 10:00 - 2026/06/26 23:59",
        status="Submit",
        detail_url="",
    )
    assert task.to_dict()["period_end"] == "2026/06/26 23:59"


def test_evaltask_from_row_missing_columns_default_empty():
    assert EvalTask.from_row({}) == EvalTask()


def test_evaltask_from_row_column_aliases():
    """常见列名变体（Class Nbr / Category / Status / Date-Time）兜底。"""
    row = {
        "Term": "T",
        "Course Code": "C",
        "Class Nbr": "2020",
        "Category": "Mid",
        "Status": "Submit",
        "Date-Time": "2026/01/01 00:00 - 2026/01/02 00:00",
    }
    task = EvalTask.from_row(row)
    assert task.class_nbr == "2020"
    assert task.category == "Mid"
    assert task.status == "Submit"
    assert task.period_start == "2026/01/01 00:00"
    assert task.period_end == "2026/01/02 00:00"


# --------------------------------------------------------------------------- #
# 时间区间边界
# --------------------------------------------------------------------------- #
def test_period_split_normal_range():
    task = EvalTask.from_row({"Date/Time": "2025/12/02 15:20 - 2025/12/26 23:59"})
    assert task.period_start == "2025/12/02 15:20"
    assert task.period_end == "2025/12/26 23:59"
    assert task.period_raw == "2025/12/02 15:20 - 2025/12/26 23:59"


def test_period_no_separator_keeps_whole_in_start():
    task = EvalTask.from_row({"Date/Time": "2026/06/02 10:00"})
    assert task.period_start == "2026/06/02 10:00"
    assert task.period_end == ""
    assert task.period_raw == "2026/06/02 10:00"


def test_period_empty_stays_empty():
    task = EvalTask.from_row({"Date/Time": ""})
    assert task.period_start == ""
    assert task.period_end == ""
    assert task.period_raw == ""


def test_period_multiple_separators_split_on_first():
    task = EvalTask.from_row({"Date/Time": "A - B - C"})
    assert task.period_start == "A"
    assert task.period_end == "B - C"


# --------------------------------------------------------------------------- #
# 真页 fixture 解析
# --------------------------------------------------------------------------- #
def test_evaluations_parses_real_page(monkeypatch, evals_real_html):
    """真页裁剪 fixture：7 行，用 query 请求 page=WL_STU_EVAL_CEN。"""
    captured: list = []
    _patch_page(monkeypatch, evals_real_html, captured)

    items = evaluations()

    assert captured == [(EVALS_COMPONENT, EVALS_QUERY)]
    assert len(items) == 7
    assert items[0].course_code == "ENG1003"
    assert items[0].term == "2025-2026 Spring Term"
    assert items[0].class_nbr == "1010"
    assert items[0].category == "End"
    assert items[0].status == "Submit"
    assert items[0].period_start == "2026/06/02 10:00"
    assert items[0].period_end == "2026/06/26 23:59"
    assert items[0].detail_url == ""  # 真页 Detail 为 JS 按钮，无 URL


def test_evaluations_covers_two_periods(monkeypatch, evals_real_html):
    """fixture 覆盖两个评估时间区间（2026 Spring / 2025 Fall）。"""
    _patch_page(monkeypatch, evals_real_html)
    items = evaluations()
    periods = {t.period_raw for t in items}
    assert "2026/06/02 10:00 - 2026/06/26 23:59" in periods
    assert "2025/12/02 15:20 - 2025/12/26 23:59" in periods
    terms = {t.term for t in items}
    assert terms == {"2025-2026 Spring Term", "2025-2026 Fall Term"}


def test_evaluations_real_status_set_is_submit_only(monkeypatch, evals_real_html):
    """真页裁剪 fixture 状态取值集合实测为 {'Submit'}。"""
    _patch_page(monkeypatch, evals_real_html)
    assert {t.status for t in evaluations()} == {"Submit"}


# --------------------------------------------------------------------------- #
# pending 口径
# --------------------------------------------------------------------------- #
def test_pending_returns_all_when_none_completed(monkeypatch, evals_real_html):
    """真页全部 Submit（不在 COMPLETED_STATUSES）→ pending 等于全部。"""
    _patch_page(monkeypatch, evals_real_html)
    assert len(pending_evaluations()) == len(evaluations()) == 7


def test_pending_filters_completed_status(monkeypatch):
    html = _grid(
        "<tr><td>T</td><td>A</td><td>a</td><td>1</td><td>End</td>"
        "<td>2026/01/01 00:00 - 2026/01/02 00:00</td><td>Submit</td></tr>"
        "<tr><td>T</td><td>B</td><td>b</td><td>2</td><td>End</td>"
        "<td>2026/01/01 00:00 - 2026/01/02 00:00</td><td>Submitted</td></tr>"
    )
    _patch_page(monkeypatch, html)
    assert [t.course_code for t in pending_evaluations()] == ["A"]


def test_pending_excludes_empty_status(monkeypatch):
    """状态为空串（无法判定）不计入 pending。"""
    html = _grid(
        "<tr><td>T</td><td>A</td><td>a</td><td>1</td><td>End</td>"
        "<td>2026/01/01 00:00 - 2026/01/02 00:00</td><td></td></tr>"
    )
    _patch_page(monkeypatch, html)
    assert pending_evaluations() == []


# --------------------------------------------------------------------------- #
# 边界：空表 / 缺列 / 异常传播
# --------------------------------------------------------------------------- #
def test_evaluations_empty_grid_returns_empty(monkeypatch):
    html = (
        "<table id='WL_EVAL_WRK'><thead><tr><th>Course Code</th></tr></thead>"
        "<tbody class='ps_grid-body'></tbody></table>"
    )
    _patch_page(monkeypatch, html)
    assert evaluations() == []


def test_evaluations_skips_rows_without_course(monkeypatch):
    html = _grid(
        "<tr><td>T</td><td>A</td><td>a</td><td>1</td><td>End</td>"
        "<td>2026/01/01 00:00 - 2026/01/02 00:00</td><td>Submit</td></tr>"
        "<tr><td></td><td></td><td></td><td></td><td></td><td></td><td></td></tr>"
    )
    _patch_page(monkeypatch, html)
    items = evaluations()
    assert len(items) == 1
    assert items[0].course_code == "A"


def test_evaluations_missing_columns_yield_empty_fields(monkeypatch):
    """缺列时对应字段为空串，不臆造（仅 Course Code 一列）。"""
    html = _grid(
        "<tr><td>ENG1003</td></tr>",
        headers="<th>Course Code</th>",
    )
    _patch_page(monkeypatch, html)
    task = evaluations()[0]
    assert task.course_code == "ENG1003"
    assert task.term == ""
    assert task.status == ""
    assert task.period_raw == ""


def test_evaluations_propagates_offcampus(monkeypatch):
    def boom(component, *, query=""):
        raise OffCampusError("校外")

    monkeypatch.setattr(evals_mod.pages, "fetch_page", boom)
    with pytest.raises(OffCampusError):
        evaluations()


def test_evaluations_propagates_unauthorized(monkeypatch):
    def boom(component, *, query=""):
        raise ActionError("not authorized")

    monkeypatch.setattr(evals_mod.pages, "fetch_page", boom)
    with pytest.raises(ActionError):
        evaluations()


def test_cli_group_registered_commands():
    """``cli_group`` 是 click group，且已挂 ``list`` 子命令。"""
    import click

    assert isinstance(evals_mod.cli_group, click.Group)
    assert "list" in evals_mod.cli_group.commands


# --------------------------------------------------------------------------- #
# live（默认被 -m 'not live' 排除）
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def _probe():
    """预热一次：确认 SIS 可达且有凭据；不可达则整体 skip。

    module 作用域：须在 autouse 的 ``_clean_state``（会把 ``WESTLAKE_HOME``
    重定向到 tmp、切断真实凭据）之前完成登录，故与现有 live 测试同款。
    """
    try:
        from westlake_survival.sso import SISAuth

        SISAuth().ensure()
    except Exception as exc:  # noqa: BLE001 - 需要校园网/凭据，任何失败都 skip
        pytest.skip(f"无法登录 SIS（需校园网/VPN 与有效凭据）：{exc}")
    return True


@pytest.mark.live
def test_live_evaluations_parse(_probe):
    """真页：≥10 行，且 course_code / term / status / period_raw 非空率 >80%。"""
    items = evaluations()
    assert len(items) >= 10, len(items)
    for field in ("course_code", "term", "status", "period_raw"):
        filled = sum(1 for t in items if getattr(t, field))
        assert filled / len(items) > 0.8, (field, filled, len(items))
    assert items[0].course_code