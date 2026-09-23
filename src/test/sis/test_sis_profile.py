"""``westlake_survival.sis.profile`` 离线测试（网络层打桩）。

fixture **全合成**：按 PeopleSoft 真实结构手造（``ps_box-label`` +
``ps_box-value``、多张 fluid 网格、空网格、缺表头网格），姓名 / 证件号 / 学号 /
银行 / 住址等一律为假造占位符，不含任何真实个人信息。

``sis/__init__`` 未重导出 ``profile``，但仍用 :func:`importlib.import_module`
取模块，避免将来重导出时与同名函数冲突（与 ``test_sis_grades`` 同风格）。
"""

from __future__ import annotations

import importlib

import pytest
from click.testing import CliRunner

from westlake_survival.exceptions import AuthError, OffCampusError
from westlake_survival.sis.profile import (
    ACADEMIC_RECORD_COMPONENT,
    ACADEMIC_RECORD_QUERY,
    EXTENDED_INFO_COMPONENT,
    EXTENDED_INFO_GRID_IDS,
    EXTENDED_INFO_QUERY,
    PERSONAL_INFO_COMPONENT,
    PERSONAL_INFO_QUERY,
    academic_record,
    cli_group,
    extended_info,
    personal_info,
)

profile_mod = importlib.import_module("westlake_survival.sis.profile")


# --------------------------------------------------------------------------- #
# 合成 fixture（结构真实、值全部假造）
# --------------------------------------------------------------------------- #
def _pair(label: str, value: str) -> str:
    """一段 PeopleSoft ``ps_box-label`` + ``ps_box-value`` 结构。"""
    return (
        "<DIV class='ps_box-edit'><DIV class='ps_box-label'>"
        f"<span class='ps-label'>{label}</span></DIV>"
        f"<span class='ps_box-value'>{value}</span></DIV>"
    )


#: 合成个人信息页：假造的证件号 / 姓名 / 出生日期。
SYNTH_INFO_HTML = (
    "<html><body>"
    + _pair("Campus ID", "SYNTH0001")
    + _pair("Name", "示例同学")
    + _pair("Gender", "Female")
    + _pair("BirthDate", "2000-01-01")
    + _pair("Country", "China")
    + _pair("Certificate Type", "ID Card")
    + _pair("Certificate No.", "000000000000000000")
    + _pair("Admission Category", "Regular")
    + _pair("Ethnic Group", "&nbsp;")  # 空值标签不产出
    + "</body></html>"
)

#: 合成学籍页：假造的入学日期 / 学院 / 专业。
SYNTH_ACADEMIC_HTML = (
    "<html><body>"
    + _pair("Program Level", "Undergraduate")
    + _pair("Grade", "Year 1")
    + _pair("Date of Enrollment", "2026-08-31")
    + _pair("College", "合成学院")
    + _pair("Major", "合成专业")
    + _pair("School", "合成学院")
    + _pair("Degree Type", "Bachelor")
    + _pair("Supervisor", "示例导师")
    + _pair("Student Status", "Enrolled")
    + _pair("Expected Graduation Date", "2030-06-30")
    + "</body></html>"
)


def _grid(grid_id: str, headers: list[str], rows: list[list[str]]) -> str:
    """一张 fluid 网格（吸顶表头表 + 数据表，结构与真实页一致）。"""
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join(
        f"<tr id='{grid_id}${i}_row_1'>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>"
        for i, row in enumerate(rows, start=1)
    )
    return (
        f"<div id='{grid_id}$grid$0'>"
        f"<table><thead><tr>{head}</tr></thead>"
        f"<tbody class='ps_grid-body'>{body}</tbody></table></div>"
    )


#: 合成扩展页：label-value + 四张网格（含空网格与缺表头网格）。
SYNTH_EXTENDED_HTML = (
    "<html><body>"
    + _pair("Conselor Name", "示例辅导员")
    + _pair("Native Place", "合成省合成市")
    + _pair("Hukou Type", "Urban")
    + _pair("E-mail Address", "synth@example.invalid")
    + _pair("Dormitory Information", "合成宿舍楼 101")
    + _pair("Home Address", "合成省合成市合成路 1 号")
    + _pair("Bank Of Deposit", "合成银行合成支行")
    + _pair("Personal Email", "synth2@example.invalid")
    + _pair("Phone Number", "000-0000-0000")
    + _pair("Phone Of Conselor", "000-0000-0001")
    + _pair("Place Of Origin", "合成省")
    + _pair("Politics", "Synth")
    + _pair("Registered Residence", "合成省合成市")
    + _pair("Religious Belief", "None")
    + _pair("Marital Status", "Single")
    + _pair("Campus Accommodation (Yes/No)", "Y")
    + _grid(
        "EXT_ORG_TBL",
        ["Contact Name", "Relationship", "Telephone", "Employer(Institute or Company)"],
        [["示例联系人", "Parent", "000-0000-0002", "合成单位"]],
    )
    + _grid(
        "WL_EDUEXPMDY_VW",
        ["Graduation School", "Graduation Time", "Career", "专业"],
        [["合成中学", "2026-06", "Student", "合成专业"]],
    )
    + _grid("WL_INSURMDY_VW", ["Insurance Name", "Insurance Number"], [])  # 空网格
    + "<div id='WL_NOHEADER$grid$0'><table><tbody class='ps_grid-body'>"
    + "<tr><td>x</td></tr></tbody></table></div>"  # 缺表头：解析失败应被跳过
    + "</body></html>"
)


def _patch_page(monkeypatch, html: str, captured: list | None = None):
    """打桩 ``pages.fetch_page``，返回固定 HTML 并记录组件名与查询串。"""

    def fake(component: str, *, query: str = "") -> str:
        if captured is not None:
            captured.append((component, query))
        return html

    monkeypatch.setattr(profile_mod.pages, "fetch_page", fake)


def _boom(exc):
    def fake(component, *, query=""):
        raise exc

    return fake


# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #
def test_component_and_query_constants():
    assert PERSONAL_INFO_COMPONENT == "WL_CUSTOMIZE_MENU.WL_PERS_DATA_FL.GBL"
    assert PERSONAL_INFO_QUERY == "page=WL_PERS_DATA_FL&NavColl=true"
    assert ACADEMIC_RECORD_COMPONENT == "WL_CUSTOMIZE_MENU.WL_ACADPRG_DATA_FL.GBL"
    assert ACADEMIC_RECORD_QUERY == "page=WL_ACADPRG_DATA_FL"
    assert EXTENDED_INFO_COMPONENT == "WL_CUSTOMIZE_MENU.WL_EXTINFO_DATA_FL.GBL"
    assert EXTENDED_INFO_QUERY == "page=WL_EXTINFO_DATA_FL"
    assert EXTENDED_INFO_GRID_IDS == (
        "EXT_ORG_TBL",
        "WL_EDUEXPMDY_VW",
        "WL_INSURMDY_VW",
        "WL_REWPUNMDY_VW",
    )


# --------------------------------------------------------------------------- #
# personal_info
# --------------------------------------------------------------------------- #
def test_personal_info_parses_label_values(monkeypatch):
    captured: list = []
    _patch_page(monkeypatch, SYNTH_INFO_HTML, captured)

    data = personal_info()

    assert captured == [(PERSONAL_INFO_COMPONENT, PERSONAL_INFO_QUERY)]
    assert data["Name"] == "示例同学"
    assert data["Campus ID"] == "SYNTH0001"
    assert data["Certificate Type"] == "ID Card"
    assert data["BirthDate"] == "2000-01-01"
    assert len(data) == 8  # 空值标签 Ethnic Group 不产出


def test_personal_info_empty_page_returns_empty_dict(monkeypatch):
    _patch_page(monkeypatch, "<html><body></body></html>")
    assert personal_info() == {}


def test_personal_info_missing_key_is_absent_not_defaulted(monkeypatch):
    """缺键即缺字段：不做臆造默认值。"""
    _patch_page(monkeypatch, _pair("Name", "示例同学"))
    data = personal_info()
    assert "Name" in data
    assert "Certificate No." not in data
    assert data.get("Certificate No.") is None


def test_personal_info_duplicate_label_last_wins(monkeypatch):
    _patch_page(monkeypatch, _pair("Name", "前") + _pair("Name", "后"))
    assert personal_info()["Name"] == "后"


def test_personal_info_propagates_offcampus(monkeypatch):
    monkeypatch.setattr(
        profile_mod.pages, "fetch_page", _boom(OffCampusError("校外"))
    )
    with pytest.raises(OffCampusError):
        personal_info()


# --------------------------------------------------------------------------- #
# academic_record
# --------------------------------------------------------------------------- #
def test_academic_record_shape_and_fields(monkeypatch):
    captured: list = []
    _patch_page(monkeypatch, SYNTH_ACADEMIC_HTML, captured)

    data = academic_record()

    assert captured == [(ACADEMIC_RECORD_COMPONENT, ACADEMIC_RECORD_QUERY)]
    assert set(data) == {"fields", "grids"}
    assert data["grids"] == {}  # 该页实测无网格
    assert data["fields"]["Program Level"] == "Undergraduate"
    assert data["fields"]["College"] == "合成学院"
    assert data["fields"]["Expected Graduation Date"] == "2030-06-30"
    assert len(data["fields"]) == 10


def test_academic_record_merges_grid_when_present(monkeypatch):
    """页面若出现网格则并入嵌套结构（配置漂移应对）。"""
    html = _pair("Major", "合成专业") + _grid(
        "WL_ACADPRG_TERM_VW", ["Term", "Status"], [["2026 Fall", "Active"]]
    )
    _patch_page(monkeypatch, html)
    data = profile_mod._fields_and_grids(
        ACADEMIC_RECORD_COMPONENT, ACADEMIC_RECORD_QUERY, ("WL_ACADPRG_TERM_VW",)
    )
    assert data["fields"]["Major"] == "合成专业"
    assert data["grids"]["WL_ACADPRG_TERM_VW"] == [{"Term": "2026 Fall", "Status": "Active"}]


def test_academic_record_empty_page(monkeypatch):
    _patch_page(monkeypatch, "")
    assert academic_record() == {"fields": {}, "grids": {}}


def test_academic_record_propagates_auth_error(monkeypatch):
    monkeypatch.setattr(profile_mod.pages, "fetch_page", _boom(AuthError("会话失效")))
    with pytest.raises(AuthError):
        academic_record()


# --------------------------------------------------------------------------- #
# extended_info
# --------------------------------------------------------------------------- #
def test_extended_info_fields(monkeypatch):
    captured: list = []
    _patch_page(monkeypatch, SYNTH_EXTENDED_HTML, captured)

    data = extended_info()

    assert captured == [(EXTENDED_INFO_COMPONENT, EXTENDED_INFO_QUERY)]
    assert len(data["fields"]) == 16
    assert data["fields"]["Conselor Name"] == "示例辅导员"
    assert data["fields"]["Home Address"] == "合成省合成市合成路 1 号"
    assert data["fields"]["Bank Of Deposit"] == "合成银行合成支行"


def test_extended_info_parses_multiple_grids(monkeypatch):
    _patch_page(monkeypatch, SYNTH_EXTENDED_HTML)
    grids = extended_info()["grids"]

    assert set(grids) == {"EXT_ORG_TBL", "WL_EDUEXPMDY_VW", "WL_INSURMDY_VW"}
    assert grids["EXT_ORG_TBL"][0]["Relationship"] == "Parent"
    assert grids["WL_EDUEXPMDY_VW"][0]["专业"] == "合成专业"


def test_extended_info_empty_grid_is_empty_list(monkeypatch):
    _patch_page(monkeypatch, SYNTH_EXTENDED_HTML)
    assert extended_info()["grids"]["WL_INSURMDY_VW"] == []


def test_extended_info_skips_missing_and_headerless_grids(monkeypatch):
    """页面缺网格 / 网格缺表头都不阻断整页（``WL_REWPUNMDY_VW`` 未出现）。"""
    _patch_page(monkeypatch, SYNTH_EXTENDED_HTML)
    grids = extended_info()["grids"]
    assert "WL_REWPUNMDY_VW" not in grids  # 页面上不存在
    assert grids  # 其余网格照常返回

    # 缺表头的网格（``WL_NOHEADER``）显式请求时被跳过，且不影响其他网格。
    data = profile_mod._fields_and_grids(
        EXTENDED_INFO_COMPONENT,
        EXTENDED_INFO_QUERY,
        ("WL_NOHEADER", "WL_EDUEXPMDY_VW"),
    )
    assert "WL_NOHEADER" not in data["grids"]
    assert data["grids"]["WL_EDUEXPMDY_VW"][0]["Graduation School"] == "合成中学"


def test_extended_info_propagates_offcampus(monkeypatch):
    monkeypatch.setattr(
        profile_mod.pages, "fetch_page", _boom(OffCampusError("校外"))
    )
    with pytest.raises(OffCampusError):
        extended_info()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def test_cli_group_registered():
    assert cli_group.name == "profile"
    assert set(cli_group.commands) == {"info", "academic", "extended"}


def test_cli_info_prints_table(monkeypatch):
    _patch_page(monkeypatch, SYNTH_INFO_HTML)
    result = CliRunner().invoke(cli_group, ["info"])
    assert result.exit_code == 0
    assert "Name" in result.output
    assert "示例同学" in result.output


def test_cli_academic_prints_fields_and_grid_placeholder(monkeypatch):
    _patch_page(monkeypatch, SYNTH_ACADEMIC_HTML)
    result = CliRunner().invoke(cli_group, ["academic"])
    assert result.exit_code == 0
    assert "Program Level" in result.output
    assert "（无网格数据）" in result.output


def test_cli_extended_prints_grid_headers(monkeypatch):
    _patch_page(monkeypatch, SYNTH_EXTENDED_HTML)
    result = CliRunner().invoke(cli_group, ["extended"])
    assert result.exit_code == 0
    assert "【EXT_ORG_TBL】" in result.output
    assert "Relationship" in result.output
    assert "（空）" in result.output  # WL_INSURMDY_VW 空网格


def test_cli_error_exit_code(monkeypatch):
    monkeypatch.setattr(
        profile_mod.pages, "fetch_page", _boom(OffCampusError("校外"))
    )
    result = CliRunner().invoke(cli_group, ["info"])
    assert result.exit_code == 1
    assert "错误" in result.output


# --------------------------------------------------------------------------- #
# live（默认被 -m 'not live' 排除；只断言键数，不打印任何值）
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def _probe():
    """预热一次：确认 SIS 可达且有凭据；不可达则整体 skip。

    必须是 **module 作用域**：函数作用域的 autouse ``_clean_state`` 会把
    ``WESTLAKE_HOME`` 重定位到 tmp，凭据就找不到了（与
    ``test_sis_grades_exams_live`` 同因同解）。
    """
    try:
        from westlake_survival.sso import SISAuth

        SISAuth().ensure()
    except Exception as exc:  # noqa: BLE001 - 需要校园网/凭据，任何失败都 skip
        pytest.skip(f"无法登录 SIS（需校园网/VPN 与有效凭据）：{exc}")
    return True


@pytest.mark.live
def test_live_personal_info_keys(_probe):
    """真页个人信息：键数 ≥10 且含 ``Name`` 键（只报数量，不打印值）。

    派发指令给的判据是「键数 ≥15」，但 2026-09-23 登录态实测该页只有 **11**
    个非空 ``label-value`` 对（键名见 :func:`personal_info` docstring），≥15
    会必然失败；此处取实测下界 10 作为回归线，页面增删字段时仍能报警。
    """
    data = personal_info()
    assert len(data) >= 10, len(data)
    assert "Name" in data