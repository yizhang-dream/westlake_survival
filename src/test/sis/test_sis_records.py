"""``westlake_survival.sis.records`` 离线测试（网络层打桩）。

六页各测「有数据」与「空数据」两条路径；fixture 分两类：

- **真实结构裁剪 + 脱敏**（``records_*_sanitized.html``）：2026-09-23 登录态
  抓取，只保留网格 ``<table>`` 与宿舍信息区，姓名替换为 ``***``；
- **合成**：覆盖无记录页（不渲染网格）与列名漂移时的 ``raw`` 兜底。

注意：``sis/__init__`` 未重导出本模块函数，``sis.records`` 属性即子模块，
但为与 grades 测试一致仍用 :func:`importlib.import_module` 取模块对象。
"""

from __future__ import annotations

import importlib

import pytest

from westlake_survival.exceptions import OffCampusError, ParseError
from westlake_survival.sis.records import (
    DORM_COMPONENT,
    DORM_GRID_ID,
    DORM_QUERY,
    LEAVE_COMPONENT,
    VOLUNTEER_GRID_ID,
    DormApplication,
    DormRecord,
    DisciplineRecord,
    HonorRecord,
    LeaveRequest,
    PracticeRecord,
    VolunteerRecord,
    discipline_records,
    dormitory,
    honors,
    leave_requests,
    social_practice,
    volunteer_records,
)

records_mod = importlib.import_module("westlake_survival.sis.records")


def _patch_page(monkeypatch, html: str, captured: list | None = None):
    """打桩 ``pages.fetch_page``，返回固定 HTML 并记录 (component, query)。"""

    def fake(component: str, *, query: str = "") -> str:
        if captured is not None:
            captured.append((component, query))
        return html

    monkeypatch.setattr(records_mod.pages, "fetch_page", fake)


def _load(name: str) -> str:
    from pathlib import Path

    path = Path(__file__).parent / "fixtures" / name
    return path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #
def test_component_constants_include_customize_prefix():
    """组件名必须带 ``WL_CUSTOMIZE_MENU.`` 前缀（裸名会被判 not authorized）。"""
    assert DORM_COMPONENT == "WL_CUSTOMIZE_MENU.WL_SA3_DORM_SELF.GBL"
    assert DORM_QUERY == "page=WL_SA3_DORM_SELF"
    assert DORM_GRID_ID == "WL_SA3_DORM_VW"
    assert LEAVE_COMPONENT == "WL_CUSTOMIZE_MENU.WL_LEV_REQ_LIST_FL.GBL"
    assert VOLUNTEER_GRID_ID == "WL_VOL_COM_VW"
    assert records_mod.VOLUNTEER_COMPONENT.startswith("WL_CUSTOMIZE_MENU.")
    assert records_mod.HONORS_COMPONENT.startswith("WL_CUSTOMIZE_MENU.")
    assert records_mod.PRACTICE_COMPONENT.startswith("WL_CUSTOMIZE_MENU.")
    assert records_mod.DISCIPLINE_COMPONENT.startswith("WL_CUSTOMIZE_MENU.")


# --------------------------------------------------------------------------- #
# 住宿
# --------------------------------------------------------------------------- #
def test_dormitory_real_fixture(monkeypatch):
    """真实脱敏页：3 条申请记录 + 宿舍信息字典。"""
    captured: list = []
    _patch_page(monkeypatch, _load("records_dorm_sanitized.html"), captured)

    record = dormitory()

    assert captured == [(DORM_COMPONENT, DORM_QUERY)]
    assert isinstance(record, DormRecord)
    assert len(record.applications) == 3
    first = record.applications[0]
    assert first.application_no == "000002422"
    assert first.application_type == "Vacation Stay Application"
    assert first.reason == "学习"
    assert first.date_time == "2026/07/05 21:41:19"
    assert first.status == "Passed"
    assert record.info["On Campus Dormitory"].startswith("Yungu Campus")


def test_dormitory_info_is_dict_and_raw_kept(monkeypatch):
    """宿舍信息用 dict 承载（键集合可漂移）；行保留原始列。"""
    _patch_page(monkeypatch, _load("records_dorm_sanitized.html"))
    record = dormitory()
    assert isinstance(record.info, dict)
    assert all(isinstance(a.raw, dict) for a in record.applications)
    assert record.applications[0].raw["View Detail"] == "View Detail"


def test_dormitory_empty_page(monkeypatch):
    """无申请记录页（不渲染网格）：applications 为空列表，不抛异常。"""
    html = (
        "<div class='ps_box-edit'><DIV class='ps_box-label'>"
        "<span class='ps-label'>On Campus Dormitory</span></DIV>"
        "<span class='ps_box-value'>Yungu Campus-本科生书院-H3-2-221-A</span></div>"
    )
    _patch_page(monkeypatch, html)
    record = dormitory()
    assert record.applications == []
    assert record.info["On Campus Dormitory"] == "Yungu Campus-本科生书院-H3-2-221-A"


def test_dorm_application_from_row_and_to_dict():
    row = {
        "Application No.": " 0001 ",
        "Application Type": "Type A",
        "Apply Reason": "R",
        "Date/Time": "D",
        "Status": "Passed",
    }
    app = DormApplication.from_row(row)
    assert app.application_no == "0001"
    assert app.to_dict()["status"] == "Passed"
    assert app.to_dict()["raw"]["Application No."] == " 0001 "


# --------------------------------------------------------------------------- #
# 请假
# --------------------------------------------------------------------------- #
def test_leave_requests_empty_real_fixture(monkeypatch):
    """真实脱敏页：用户无记录、页面不渲染网格 → 空列表。"""
    captured: list = []
    _patch_page(monkeypatch, _load("records_leave_sanitized.html"), captured)
    assert leave_requests() == []
    assert captured == [(LEAVE_COMPONENT, "")]


def test_leave_requests_with_synthetic_grid(monkeypatch):
    """合成网格（列名未实测，用候选键匹配）：解析出请假记录。"""
    html = (
        "<table id='WL_LEV_REQ_LIST_VW'><thead><tr>"
        "<th>Application No.</th><th>Leave Type</th><th>Start Date</th>"
        "<th>End Date</th><th>Status</th></tr></thead><tbody>"
        "<tr><td>L001</td><td>Sick</td><td>2026-09-01</td>"
        "<td>2026-09-02</td><td>Approved</td></tr>"
        "</tbody></table>"
    )
    _patch_page(monkeypatch, html)
    items = leave_requests()
    assert len(items) == 1
    assert isinstance(items[0], LeaveRequest)
    assert items[0].application_no == "L001"
    assert items[0].leave_type == "Sick"
    assert items[0].status == "Approved"
    assert items[0].raw["Start Date"] == "2026-09-01"


def test_leave_request_from_row_unknown_columns_kept_in_raw():
    """列名漂移时字段为空串，但 ``raw`` 完整保留。"""
    item = LeaveRequest.from_row({"Weird Col": "x"})
    assert item.application_no == ""
    assert item.raw == {"Weird Col": "x"}


# --------------------------------------------------------------------------- #
# 荣誉
# --------------------------------------------------------------------------- #
def test_honors_empty_real_fixture(monkeypatch):
    """真实脱敏页：暂无荣誉、无网格 → 空列表（页内字段线索不误判为网格）。"""
    _patch_page(monkeypatch, _load("records_honors_sanitized.html"))
    assert honors() == []


def test_honors_synthetic_grid(monkeypatch):
    html = (
        "<table id='WL_HON_PRJ_VW'><thead><tr>"
        "<th>Honor Name</th><th>Level</th><th>Date</th><th>Status</th>"
        "</tr></thead><tbody>"
        "<tr><td>优秀学生</td><td>校级</td><td>2026-06-01</td><td>已授予</td></tr>"
        "<tr><td>竞赛一等奖</td><td>省级</td><td>2026-05-01</td><td>已授予</td></tr>"
        "</tbody></table>"
    )
    _patch_page(monkeypatch, html)
    items = honors()
    assert len(items) == 2
    assert items[0].name == "优秀学生"
    assert items[0].level == "校级"
    assert isinstance(items[0], HonorRecord)


# --------------------------------------------------------------------------- #
# 志愿服务
# --------------------------------------------------------------------------- #
def test_volunteer_real_fixture(monkeypatch):
    """真实脱敏页：4 条志愿服务记录，含双空格列名 ``Maximum Number Of  Hour``。"""
    captured: list = []
    _patch_page(monkeypatch, _load("records_volunteer_sanitized.html"), captured)

    items = volunteer_records()

    assert captured == [(records_mod.VOLUNTEER_COMPONENT, records_mod.VOLUNTEER_QUERY)]
    assert len(items) == 4
    first = items[0]
    assert isinstance(first, VolunteerRecord)
    assert first.year == "2025"
    assert first.number == "000000660"
    assert first.status == "Have Finished"
    assert first.hours == "9.0"
    assert first.activity_time.startswith("2026-06-12")


def test_volunteer_keeps_literal_null_name(monkeypatch):
    """站点把空服务名渲染为字面量 ``NULL``，本模块忠实保留（不改写为空格）。"""
    _patch_page(monkeypatch, _load("records_volunteer_sanitized.html"))
    items = volunteer_records()
    assert any(v.name == "NULL" for v in items)


def test_volunteer_empty_page(monkeypatch):
    _patch_page(monkeypatch, "<div id='win3divX'></div>")
    assert volunteer_records() == []


# --------------------------------------------------------------------------- #
# 社会实践
# --------------------------------------------------------------------------- #
def test_social_practice_empty_real_fixture(monkeypatch):
    """真实脱敏页：社会实践尚未开放、无网格 → 空列表。"""
    captured: list = []
    _patch_page(monkeypatch, _load("records_practice_sanitized.html"), captured)
    assert social_practice() == []
    assert captured == [
        (records_mod.PRACTICE_COMPONENT, records_mod.PRACTICE_QUERY)
    ]


def test_social_practice_synthetic_grid(monkeypatch):
    html = (
        "<table id='WL_SA_SCPRA_VW'><thead><tr>"
        "<th>Practice Name</th><th>Organization</th><th>Start Date</th>"
        "<th>End Date</th><th>Hours</th></tr></thead><tbody>"
        "<tr><td>乡村振兴调研</td><td>校团委</td><td>2026-07-01</td>"
        "<td>2026-07-10</td><td>40</td></tr>"
        "</tbody></table>"
    )
    _patch_page(monkeypatch, html)
    items = social_practice()
    assert len(items) == 1
    assert items[0].title == "乡村振兴调研"
    assert items[0].organization == "校团委"
    assert isinstance(items[0], PracticeRecord)


# --------------------------------------------------------------------------- #
# 违纪
# --------------------------------------------------------------------------- #
def test_discipline_empty_real_fixture(monkeypatch):
    """真实脱敏页：暂无违纪信息、无网格 → 空列表。"""
    captured: list = []
    _patch_page(monkeypatch, _load("records_discipline_sanitized.html"), captured)
    assert discipline_records() == []
    assert captured == [
        (records_mod.DISCIPLINE_COMPONENT, records_mod.DISCIPLINE_QUERY)
    ]


def test_discipline_synthetic_grid(monkeypatch):
    html = (
        "<table id='WL_DSC_STU_LIST_VW'><thead><tr>"
        "<th>Date</th><th>Category</th><th>Description</th><th>Status</th>"
        "</tr></thead><tbody>"
        "<tr><td>2026-03-01</td><td>迟到</td><td>无故迟到</td><td>已处理</td></tr>"
        "</tbody></table>"
    )
    _patch_page(monkeypatch, html)
    items = discipline_records()
    assert len(items) == 1
    assert isinstance(items[0], DisciplineRecord)
    assert items[0].category == "迟到"


# --------------------------------------------------------------------------- #
# 通用行为：空行过滤 / 异常传播 / 结构变化
# --------------------------------------------------------------------------- #
def test_blank_rows_skipped(monkeypatch):
    html = (
        "<table id='WL_VOL_COM_VW'><thead><tr>"
        "<th>Year</th><th>Service Name</th></tr></thead><tbody>"
        "<tr><td>2025</td><td>A</td></tr>"
        "<tr><td></td><td></td></tr>"
        "</tbody></table>"
    )
    _patch_page(monkeypatch, html)
    items = volunteer_records()
    assert len(items) == 1
    assert items[0].name == "A"


def test_rendered_grid_without_header_raises(monkeypatch):
    """已渲染的网格缺表头 → ParseError（真结构变化，不能当空数据吞掉）。"""
    html = "<table id='WL_VOL_COM_VW'><tbody class='ps_grid-body'></tbody></table>"
    _patch_page(monkeypatch, html)
    with pytest.raises(ParseError):
        volunteer_records()


def test_offcampus_propagates(monkeypatch):
    def boom(component, *, query=""):
        raise OffCampusError("校外")

    monkeypatch.setattr(records_mod.pages, "fetch_page", boom)
    with pytest.raises(OffCampusError):
        dormitory()


def test_to_dict_roundtrip_shapes(monkeypatch):
    """``to_dict`` 产出可 JSON 序列化的普通 dict（raw 为浅拷贝）。"""
    _patch_page(monkeypatch, _load("records_dorm_sanitized.html"))
    record = dormitory()
    data = record.to_dict()
    assert set(data) == {"applications", "info"}
    assert data["applications"][0]["application_no"] == "000002422"
    assert data["applications"][0]["raw"]["Status"] == "Passed"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def test_cli_empty_shows_placeholder(monkeypatch):
    """空数据显示「暂无记录」。"""
    from click.testing import CliRunner

    _patch_page(monkeypatch, _load("records_discipline_sanitized.html"))
    result = CliRunner().invoke(records_mod.cli_group, ["discipline"])
    assert result.exit_code == 0
    assert "暂无记录" in result.output


def test_cli_dorm_prints_info_and_rows(monkeypatch):
    from click.testing import CliRunner

    _patch_page(monkeypatch, _load("records_dorm_sanitized.html"))
    result = CliRunner().invoke(records_mod.cli_group, ["dorm"])
    assert result.exit_code == 0
    assert "On Campus Dormitory" in result.output
    assert "申请号" in result.output
    assert "暂无记录" not in result.output


def test_cli_volunteer_rows(monkeypatch):
    from click.testing import CliRunner

    _patch_page(monkeypatch, _load("records_volunteer_sanitized.html"))
    result = CliRunner().invoke(records_mod.cli_group, ["volunteer"])
    assert result.exit_code == 0
    assert "服务名称" in result.output
    assert "000000660" in result.output


def test_cli_offcampus_exit_code(monkeypatch):
    from click.testing import CliRunner

    def boom(component, *, query=""):
        raise OffCampusError("校外")

    monkeypatch.setattr(records_mod.pages, "fetch_page", boom)
    result = CliRunner().invoke(records_mod.cli_group, ["honors"])
    assert result.exit_code == 1
    assert "VPN" in result.output or "VPN" in (result.stderr or "")


# --------------------------------------------------------------------------- #
# 真实网络探测（``@pytest.mark.live``，默认被 ``-m 'not live'`` 排除）
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def _live_probe():
    """预热一次：确认 SIS 可达且有凭据；不可达则整体 skip。"""
    try:
        from westlake_survival.sso import SISAuth

        SISAuth().ensure()
    except Exception as exc:  # noqa: BLE001 - 需要校园网/凭据，任何失败都 skip
        pytest.skip(f"无法登录 SIS（需校园网/VPN 与有效凭据）：{exc}")
    return True


@pytest.mark.live
def test_live_six_pages_parse_without_error(_live_probe):
    """六页全部 HTTP 可解析且不抛异常；空数据页返回空列表也算通过。

    只读 GET，不点击任何动作按钮（住宿页的 Transfer / Leaving 按钮绝不触发）。
    """
    record = dormitory()
    assert isinstance(record, DormRecord)
    for func in (
        leave_requests,
        honors,
        volunteer_records,
        social_practice,
        discipline_records,
    ):
        assert isinstance(func(), list)


@pytest.mark.live
def test_live_dorm_and_volunteer_shapes(_live_probe):
    """真页住宿申请与志愿服务记录逐条字段可解析（有记录时字段非空）。"""
    record = dormitory()
    for app in record.applications:
        assert app.application_no or app.application_type
    for item in volunteer_records():
        assert item.number or item.name