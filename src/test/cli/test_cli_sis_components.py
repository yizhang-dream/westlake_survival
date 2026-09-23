"""SIS 新增四个组件命令组接入顶层命令树的集成测试（离线，取数函数打桩）。

覆盖：``sis-evals`` / ``profile`` / ``records`` / ``aid`` 四个组挂在 ``westlake``
顶层；抽 2 个新命令（``sis-evals list --pending`` / ``aid loans``）走顶层命令树
用 ``CliRunner`` 跑通（monkeypatch 取数函数，不发起网络）。
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from westlake_survival.sis.aid import LoanRecord
from westlake_survival.sis.evals import EvalTask

#: 本次接入的四个 SIS 组件命令组（组名以各模块 ``cli_group`` 定义为准）。
_SIS_COMPONENT_COMMANDS = ("sis-evals", "profile", "records", "aid")


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# --------------------------------------------------------------------------- #
# 注册到顶层命令树
# --------------------------------------------------------------------------- #
def test_top_level_help_lists_sis_component_commands(
    runner: CliRunner, cli_group
) -> None:
    """``westlake --help`` 能看到四个新命令组。"""
    result = runner.invoke(cli_group, ["--help"])
    assert result.exit_code == 0, result.output
    for name in _SIS_COMPONENT_COMMANDS:
        assert name in result.output


def test_sis_component_commands_registered_on_cli(cli_group) -> None:
    """四个新命令组都真实注册在顶层 group 上（而非仅出现在 help 文本）。"""
    for name in _SIS_COMPONENT_COMMANDS:
        assert name in cli_group.commands
        assert cli_group.commands[name].name == name


def test_sis_component_command_subcommands(cli_group) -> None:
    """各组的子命令集合与模块定义一致（防止挂错 group）。"""
    expected = {
        "sis-evals": {"list"},
        "profile": {"info", "academic", "extended"},
        "records": {"dorm", "leave", "honors", "volunteer", "practice", "discipline"},
        "aid": {"loans", "jobs", "outbound", "exchange", "orgs", "activities"},
    }
    for name, subcommands in expected.items():
        assert set(cli_group.commands[name].commands) == subcommands


# --------------------------------------------------------------------------- #
# 抽 2 个新命令走顶层命令树（离线打桩）
# --------------------------------------------------------------------------- #
def test_top_level_sis_evals_pending(
    runner: CliRunner, cli_group, monkeypatch
) -> None:
    """``westlake sis-evals list --pending`` 走顶层树，只调 pending_evaluations。"""
    calls: list[str] = []
    pending = [
        EvalTask(
            term="2026-2027 Fall Term",
            course_code="ENG1003",
            course_title="Academic English",
            class_nbr="1010",
            category="End",
            period_raw="2026/06/02 10:00 - 2026/06/26 23:59",
            status="Submit",
        )
    ]

    def fake_pending():
        calls.append("pending")
        return pending

    def fake_all():  # pragma: no cover - 不应被调用
        raise AssertionError("--pending 不应调用 evaluations()")

    monkeypatch.setattr("westlake_survival.sis.evals.pending_evaluations", fake_pending)
    monkeypatch.setattr("westlake_survival.sis.evals.evaluations", fake_all)

    result = runner.invoke(cli_group, ["sis-evals", "list", "--pending"])
    assert result.exit_code == 0, result.output
    assert calls == ["pending"]
    assert "Academic English" in result.output
    assert "Submit" in result.output
    assert "课程代码" in result.output


def test_top_level_sis_evals_list_all(
    runner: CliRunner, cli_group, monkeypatch
) -> None:
    """``westlake sis-evals list``（不带 --pending）调用 evaluations()。"""
    monkeypatch.setattr(
        "westlake_survival.sis.evals.evaluations",
        lambda: [EvalTask(course_code="CST2000", course_title="Discrete Mathematics")],
    )
    result = runner.invoke(cli_group, ["sis-evals", "list"])
    assert result.exit_code == 0, result.output
    assert "Discrete Mathematics" in result.output


def test_top_level_aid_loans(runner: CliRunner, cli_group, monkeypatch) -> None:
    """``westlake aid loans`` 走顶层命令树并打印贷款表格。"""
    calls: list[int] = []

    def fake_loans():
        calls.append(1)
        return [
            LoanRecord(loan_type="国家助学贷款", amount="6000", status="已放款", apply_date="2026/09/01")
        ]

    monkeypatch.setattr("westlake_survival.sis.aid.loans", fake_loans)
    result = runner.invoke(cli_group, ["aid", "loans"])
    assert result.exit_code == 0, result.output
    assert calls == [1]
    assert "国家助学贷款" in result.output
    assert "6000" in result.output
    assert "金额" in result.output


def test_top_level_aid_loans_empty(runner: CliRunner, cli_group, monkeypatch) -> None:
    """空数据页如实提示「没有…记录」，不报错。"""
    monkeypatch.setattr("westlake_survival.sis.aid.loans", lambda: [])
    result = runner.invoke(cli_group, ["aid", "loans"])
    assert result.exit_code == 0, result.output
    assert "没有贷款记录" in result.output


def test_top_level_records_leave_empty(
    runner: CliRunner, cli_group, monkeypatch
) -> None:
    """``westlake records leave`` 空数据页打印「暂无记录」。"""
    monkeypatch.setattr("westlake_survival.sis.records.leave_requests", lambda: [])
    result = runner.invoke(cli_group, ["records", "leave"])
    assert result.exit_code == 0, result.output
    assert "暂无记录" in result.output


def test_top_level_profile_info(runner: CliRunner, cli_group, monkeypatch) -> None:
    """``westlake profile info`` 走顶层树并打印字段表。"""
    monkeypatch.setattr(
        "westlake_survival.sis.profile.personal_info",
        lambda: {"Name": "张三", "Student ID": "2026001"},
    )
    result = runner.invoke(cli_group, ["profile", "info"])
    assert result.exit_code == 0, result.output
    assert "张三" in result.output
    assert "字段" in result.output