"""``westlake_survival.sis.aid`` 离线测试（网络层打桩）。

fixture 两种来源：

- **真实结构裁剪 + 脱敏**：``aid_*_sanitized.html`` / ``aid_*_empty.html``
  （2026-09-23 登录态实测页面裁剪，社团发起人姓名替换为 ``***``，无其它 PII）；
- **合成**：考试/贷款/交流等空页无法实测列名，故用与真实 fluid 网格同构的
  合成表格覆盖列名映射与 ``raw`` 兜底。

网络层一律打桩 ``aid.pages.fetch_page``，不发真实请求。
live 用例见 :mod:`test_sis_aid_live`。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from westlake_survival.exceptions import ActionError, OffCampusError, ParseError
from westlake_survival.sis import aid
from westlake_survival.sis.aid import (
    ACTIVITY_COMPONENT,
    EXCHANGE_APPL_COMPONENT,
    EXCHANGE_SCHOOL_COMPONENT,
    LOAN_LIST_COMPONENT,
    LOAN_LIST_QUERY,
    LOAN_OWN_COMPONENT,
    LOAN_REPAYMENT_COMPONENT,
    ORG_LIST_COMPONENT,
    ORG_SUM_COMPONENT,
    OUTBOUND_COMPONENT,
    WORK_MENU_COMPONENT,
    WORK_MENU_QUERY,
    WORK_POSITIONS_COMPONENT,
    ActivityRecord,
    ExchangeRecord,
    ExchangeSchool,
    LoanRecord,
    LoanRepayment,
    OrgRecord,
    OutboundRecord,
    StudyJob,
    WorkStudyTab,
    cli_group,
    exchange_applications,
    exchange_schools,
    loan_application,
    loan_repayments,
    loans,
    my_clubs,
    outbound_programs,
    student_activities,
    student_orgs,
    study_jobs,
    work_study_tabs,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _patch(monkeypatch, html: str, captured: list | None = None):
    """打桩 ``aid.pages.fetch_page``，记录 (component, query)。"""

    def fake(component: str, *, query: str = "") -> str:
        if captured is not None:
            captured.append((component, query))
        return html

    monkeypatch.setattr(aid.pages, "fetch_page", fake)


def _grid_html(grid_id: str, headers: list[str], rows: list[list[str]]) -> str:
    """构造与真实 fluid 网格同构的合成表格。"""
    head = "".join(f"<th scope='col'>{h}</th>" for h in headers)
    body = "".join(
        f"<tr class='ps_grid-row' id='{grid_id}$0_row_{i}'>"
        + "".join(f"<td>{c}</td>" for c in row)
        + "</tr>"
        for i, row in enumerate(rows)
    )
    return (
        f"<table class='ps_grid-flex'><thead class='ps_grid-head'><tr>{head}</tr></thead>"
        f"<tbody class='ps_grid-body'>{body}</tbody></table>"
    )


# --------------------------------------------------------------------------- #
# 常量：组件一律带菜单前缀，否则 PeopleSoft 判未授权（实测）
# --------------------------------------------------------------------------- #
def test_components_use_menu_prefix():
    for component in (
        LOAN_LIST_COMPONENT,
        LOAN_OWN_COMPONENT,
        LOAN_REPAYMENT_COMPONENT,
        OUTBOUND_COMPONENT,
        EXCHANGE_APPL_COMPONENT,
        EXCHANGE_SCHOOL_COMPONENT,
        ORG_SUM_COMPONENT,
        ORG_LIST_COMPONENT,
        ACTIVITY_COMPONENT,
    ):
        assert component.startswith("WL_CUSTOMIZE_MENU."), component
    assert LOAN_LIST_QUERY == "NavColl=true"
    assert WORK_MENU_COMPONENT == "CHN_PACKAGE_CS.CHN_WORK_MD01.GBL"
    assert WORK_MENU_QUERY == "page=CHN_WORK_MD01"
    assert WORK_POSITIONS_COMPONENT == "CHN_PACKAGE_CS.CHN_STUAPL_LIST_FL.GBL"


# --------------------------------------------------------------------------- #
# 空记录页：优雅返回空列表（8 个真实空页场景）
# --------------------------------------------------------------------------- #
def test_loans_empty_page_returns_empty(monkeypatch):
    captured: list = []
    _patch(monkeypatch, _fixture("aid_loan_empty.html"), captured)
    assert loans() == []
    assert captured == [(LOAN_LIST_COMPONENT, LOAN_LIST_QUERY)]


def test_loan_application_empty_page_returns_empty(monkeypatch):
    captured: list = []
    _patch(monkeypatch, _fixture("aid_loan_empty.html"), captured)
    assert loan_application() == []
    assert captured == [(LOAN_OWN_COMPONENT, "")]


def test_loan_repayments_empty_page_returns_empty(monkeypatch):
    _patch(monkeypatch, _fixture("aid_loan_repayment_empty.html"))
    assert loan_repayments() == []


def test_study_jobs_empty_page_returns_empty(monkeypatch):
    captured: list = []
    _patch(monkeypatch, _fixture("aid_study_jobs_empty.html"), captured)
    assert study_jobs() == []
    assert captured == [(WORK_POSITIONS_COMPONENT, "Page=CHN_STUAPL_LIST_FL&Action=U")]


def test_outbound_empty_page_returns_empty(monkeypatch):
    _patch(monkeypatch, _fixture("aid_outbound_empty.html"))
    assert outbound_programs() == []


def test_exchange_applications_empty_page_returns_empty(monkeypatch):
    _patch(monkeypatch, _fixture("aid_exchange_application_empty.html"))
    assert exchange_applications() == []


def test_exchange_schools_empty_page_returns_empty(monkeypatch):
    _patch(monkeypatch, _fixture("aid_exchange_schools_empty.html"))
    assert exchange_schools() == []


def test_student_activities_empty_page_returns_empty(monkeypatch):
    captured: list = []
    _patch(monkeypatch, _fixture("aid_activities_empty.html"), captured)
    assert student_activities() == []
    assert captured == [(ACTIVITY_COMPONENT, "")]


# --------------------------------------------------------------------------- #
# 有数据页：真实结构裁剪 + 脱敏
# --------------------------------------------------------------------------- #
def test_work_study_tabs_real_nav(monkeypatch):
    """勤工助学主页导航网格实测 4 个 tab（岗位/申请/工时/工资）。"""
    captured: list = []
    _patch(monkeypatch, _fixture("aid_work_nav_sanitized.html"), captured)
    tabs = work_study_tabs()
    assert captured == [(WORK_MENU_COMPONENT, WORK_MENU_QUERY)]
    assert [t.name for t in tabs] == [
        "Positions Available For Application",
        "My Work-Study Positions",
        "Hours Declaration",
        "My Salary",
    ]
    assert tabs[0].url.endswith("CHN_STUWRK_LIST_FL.GBL?Page=CHN_STUWRK_LIST_FL&Action=U")
    assert all(t.name and t.url for t in tabs)


def test_my_clubs_real_grid(monkeypatch):
    """「我的社团」fluid 网格 ``WL_STU_ORG_TBL`` 实测 2 行 / 5 列，创始人已脱敏。"""
    _patch(monkeypatch, _fixture("aid_my_clubs_sanitized.html"))
    clubs = my_clubs()
    assert len(clubs) == 2
    first = clubs[0]
    assert first.academic_year == "2026"
    assert first.club_name == "Philosophy and Humanities/Social Sciences Club"
    assert first.founder == "***"  # 脱敏占位
    assert first.initiation_deadline == "09/07/2026"
    assert first.initiators == "76"
    # raw 保留原始表头行
    assert first.raw["Club Name"] == first.club_name
    assert first.to_dict()["initiators"] == "76"


def test_student_orgs_real_div_grid(monkeypatch):
    """社团目录是 div 网格（非标准 table），按分组盒抽类别 + 名称。"""
    captured: list = []
    _patch(monkeypatch, _fixture("aid_org_directory_sanitized.html"), captured)
    orgs = student_orgs()
    assert captured == [(ORG_SUM_COMPONENT, "")]
    assert len(orgs) == 4
    cats = {o.category for o in orgs}
    assert cats == {"ACADEMIC AND TECHNOLOGICAL", "CULTURE AND SPORTS"}
    first = orgs[0]
    assert first.category == "ACADEMIC AND TECHNOLOGICAL"
    assert first.name == "Natural Exploration Club（Outstanding Club）"
    assert first.academic_year == ""  # 目录来源不填「我的社团」列


# --------------------------------------------------------------------------- #
# 合成网格：列名映射 + raw 兜底（空页列名未实测）
# --------------------------------------------------------------------------- #
def test_loans_parse_synthetic_and_keep_raw(monkeypatch):
    html = _grid_html(
        aid.LOAN_LIST_GRID_ID,
        ["Loan Type", "Loan Amount", "Application Status", "Application Date"],
        [["国家助学贷款", "1000", "Approved", "09/01/2026"]],
    )
    _patch(monkeypatch, html)
    items = loans()
    assert len(items) == 1
    assert items[0].loan_type == "国家助学贷款"
    assert items[0].amount == "1000"
    assert items[0].status == "Approved"
    assert items[0].apply_date == "09/01/2026"
    assert items[0].raw["Loan Amount"] == "1000"


def test_loan_record_raw_fallback_on_column_drift():
    """列名漂移（未知表头）时具名字段留空，raw 仍完整透传。"""
    record = LoanRecord.from_row({"Mystery Column": "x", "Amount": " 1000 "})
    assert record.loan_type == ""
    assert record.amount == "1000"  # 别名命中
    assert record.raw == {"Mystery Column": "x", "Amount": " 1000 "}
    assert record.to_dict()["raw"]["Mystery Column"] == "x"


def test_loan_repayments_parse_synthetic(monkeypatch):
    html = _grid_html(
        aid.LOAN_REPAYMENT_GRID_ID,
        ["Period", "Amount Due", "Amount Paid", "Due Date", "Status"],
        [["2026-1", "500", "500", "09/30/2026", "Paid"]],
    )
    _patch(monkeypatch, html)
    items = loan_repayments()
    assert len(items) == 1
    rep = items[0]
    assert (rep.period, rep.amount_due, rep.amount_paid, rep.due_date, rep.status) == (
        "2026-1", "500", "500", "09/30/2026", "Paid",
    )
    assert LoanRepayment.from_row({}) == LoanRepayment()


def test_study_jobs_parse_synthetic(monkeypatch):
    html = _grid_html(
        aid.WORK_POSITIONS_GRID_ID,
        ["Position Name", "Department", "Total Hours", "Salary", "Status"],
        [["Library Assistant", "图书馆", "40", "1000", "Hired"]],
    )
    _patch(monkeypatch, html)
    items = study_jobs()
    assert len(items) == 1
    assert items[0].position == "Library Assistant"
    assert items[0].department == "图书馆"
    assert items[0].hours == "40"
    assert items[0].salary == "1000"
    assert items[0].status == "Hired"


def test_outbound_parse_synthetic(monkeypatch):
    html = _grid_html(
        aid.OUTBOUND_GRID_ID,
        ["Program", "Country", "University", "Term", "Status"],
        [["Exchange Program", "Singapore", "NUS", "2026-2027 Fall", "Submitted"]],
    )
    _patch(monkeypatch, html)
    items = outbound_programs()
    assert len(items) == 1
    rec = items[0]
    assert (rec.program, rec.country, rec.university, rec.term, rec.status) == (
        "Exchange Program", "Singapore", "NUS", "2026-2027 Fall", "Submitted",
    )
    assert OutboundRecord.from_row({}) == OutboundRecord()


def test_exchange_applications_parse_synthetic(monkeypatch):
    html = _grid_html(
        aid.EXCHANGE_APPL_GRID_ID,
        ["Program", "Institution", "Major", "Academic Term", "Status"],
        [["UGRD Exchange", "ETH Zürich", "Computer Science", "Spring 2027", "Under Review"]],
    )
    _patch(monkeypatch, html)
    items = exchange_applications()
    assert len(items) == 1
    rec = items[0]
    assert rec.university == "ETH Zürich"
    assert rec.major == "Computer Science"
    assert rec.term == "Spring 2027"
    assert ExchangeRecord.from_row({}) == ExchangeRecord()


def test_exchange_schools_parse_synthetic(monkeypatch):
    html = _grid_html(
        aid.EXCHANGE_SCHOOL_GRID_ID,
        ["University Name", "Country", "Program"],
        [["UC Berkeley", "USA", "UGRD Exchange"], ["Kyoto University", "Japan", "UGRD Exchange"]],
    )
    _patch(monkeypatch, html)
    items = exchange_schools()
    assert len(items) == 2
    assert items[0].university == "UC Berkeley"
    assert items[0].country == "USA"
    assert items[1].university == "Kyoto University"
    assert ExchangeSchool.from_row({}) == ExchangeSchool()


def test_student_activities_parse_synthetic(monkeypatch):
    html = _grid_html(
        aid.ACTIVITY_GRID_ID,
        ["Activity Name", "Date", "Location", "Status"],
        [["摄影展", "10/01/2026", "E13-201", "Registered"]],
    )
    _patch(monkeypatch, html)
    items = student_activities()
    assert len(items) == 1
    rec = items[0]
    assert (rec.name, rec.date, rec.location, rec.status) == (
        "摄影展", "10/01/2026", "E13-201", "Registered",
    )
    assert ActivityRecord.from_row({}) == ActivityRecord()


def test_org_record_from_row_maps_real_columns():
    row = {
        "Academic Year": "2026",
        "Club Name": "Test Club",
        "Founder": "***",
        "Initiation Deadline": "09/07/2026",
        "Current Initiators Number": "10",
    }
    org = OrgRecord.from_row(row)
    assert org.club_name == "Test Club"
    assert org.founder == "***"
    assert org.initiators == "10"
    assert org.to_dict()["academic_year"] == "2026"


def test_work_study_tab_from_row():
    tab = WorkStudyTab.from_row({"name": " My Salary ", "url": " https://x/y "})
    assert tab.name == "My Salary"
    assert tab.url == "https://x/y"
    assert tab.to_dict() == {"name": "My Salary", "url": "https://x/y"}


# --------------------------------------------------------------------------- #
# 网格漂移兜底与异常传播
# --------------------------------------------------------------------------- #
def test_grid_drift_falls_back_to_other_data_grid(monkeypatch):
    """目标网格 id 漂移但页内有其它数据行网格时，退回该网格解析（不丢数据）。"""
    html = _grid_html("RENAMED_GRID", ["Loan Type"], [["测试贷款"]])
    _patch(monkeypatch, html)
    items = loans()
    assert len(items) == 1
    assert items[0].loan_type == "测试贷款"


def test_missing_grid_without_nodata_marker_raises(monkeypatch):
    """既无目标网格也无空记录特征：视为结构漂移，抛 ParseError 而非静默空。"""
    _patch(monkeypatch, "<html><body>no grids here</body></html>")
    with pytest.raises(ParseError):
        loans()


def test_loans_propagates_unauthorized(monkeypatch):
    def boom(component, *, query=""):
        raise ActionError("not authorized")

    monkeypatch.setattr(aid.pages, "fetch_page", boom)
    with pytest.raises(ActionError):
        loans()


def test_student_orgs_propagates_offcampus(monkeypatch):
    def boom(component, *, query=""):
        raise OffCampusError("校外")

    monkeypatch.setattr(aid.pages, "fetch_page", boom)
    with pytest.raises(OffCampusError):
        student_orgs()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def test_cli_group_commands():
    assert cli_group.name == "aid"
    assert set(cli_group.commands) == {
        "loans", "jobs", "outbound", "exchange", "orgs", "activities",
    }


def test_cli_loans_prints_rows(monkeypatch):
    html = _grid_html(
        aid.LOAN_LIST_GRID_ID,
        ["Loan Type", "Loan Amount", "Application Status", "Application Date"],
        [["国家助学贷款", "1000", "Approved", "09/01/2026"]],
    )
    _patch(monkeypatch, html)
    result = CliRunner().invoke(cli_group, ["loans"])
    assert result.exit_code == 0, result.output
    assert "国家助学贷款" in result.output
    assert "1000" in result.output


def test_cli_orgs_prints_rows(monkeypatch):
    _patch(monkeypatch, _fixture("aid_org_directory_sanitized.html"))
    result = CliRunner().invoke(cli_group, ["orgs"])
    assert result.exit_code == 0, result.output
    assert "Natural Exploration Club" in result.output
    assert "ACADEMIC AND TECHNOLOGICAL" in result.output


def test_cli_empty_page_prints_hint(monkeypatch):
    _patch(monkeypatch, _fixture("aid_loan_empty.html"))
    result = CliRunner().invoke(cli_group, ["loans"])
    assert result.exit_code == 0
    assert "没有贷款记录。" in result.output


def test_cli_handles_error_exit_code(monkeypatch):
    def boom(component, *, query=""):
        raise OffCampusError("校外")

    monkeypatch.setattr(aid.pages, "fetch_page", boom)
    result = CliRunner().invoke(cli_group, ["loans"])
    assert result.exit_code == 1
    assert "VPN" in result.output or "VPN" in (result.stderr or "")


# --------------------------------------------------------------------------- #
# live：真实网络探测（``@pytest.mark.live``，默认被 ``-m 'not live'`` 排除）
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def _probe():
    """确认 SIS 可达且有凭据；不可达则整体 skip（需校园网/VPN）。"""
    try:
        from westlake_survival.sso import SISAuth

        SISAuth().ensure()
    except Exception as exc:  # noqa: BLE001 - 任何失败都 skip
        pytest.skip(f"无法登录 SIS（需校园网/VPN 与有效凭据）：{exc}")
    return True


@pytest.mark.live
def test_live_six_aid_pages_reachable_and_parsable(_probe):
    """六类页（贷款/勤工助学/交流申请/院校/组织/活动）可达且可解析。

    空数据也算通过：只要不抛异常并返回对应模型列表。
    """
    checks = [
        (loans, LoanRecord),
        (study_jobs, StudyJob),
        (outbound_programs, OutboundRecord),
        (exchange_applications, ExchangeRecord),
        (student_orgs, OrgRecord),
        (student_activities, ActivityRecord),
    ]
    for func, model in checks:
        items = func()
        assert isinstance(items, list), func.__name__
        assert all(isinstance(item, model) for item in items), func.__name__


@pytest.mark.live
def test_live_auxiliary_aid_pages_reachable(_probe):
    """贷款还款 / 个人贷款 / 院校列表 / 勤工助学 tab / 我的社团 均可达可解析。"""
    assert isinstance(loan_repayments(), list)
    assert isinstance(loan_application(), list)
    assert isinstance(exchange_schools(), list)
    assert isinstance(my_clubs(), list)
    tabs = work_study_tabs()
    assert isinstance(tabs, list)
    assert all(isinstance(t, WorkStudyTab) for t in tabs)

