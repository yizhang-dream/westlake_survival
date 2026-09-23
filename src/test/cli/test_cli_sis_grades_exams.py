"""``westlake sis grades`` / ``sis exams`` 命令与 ``research`` 注册测试（离线打桩）。"""

from __future__ import annotations

from westlake_survival.sis import ExamSlot, Grade


# --------------------------------------------------------------------------- #
# sis grades
# --------------------------------------------------------------------------- #
def test_sis_grades_renders(runner, cli_group, monkeypatch) -> None:
    import westlake_survival.sis as sis_pkg

    items = [
        Grade("CST 2000", "Discrete Mathematics", "2026-2027 Fall Term", "", "2.0"),
        Grade("MATH 1004", "Single Variable Calculus Track A", "2025-2026 Fall Term", "A+", "5.0"),
    ]
    monkeypatch.setattr(sis_pkg, "grades", lambda: items)
    result = runner.invoke(cli_group, ["sis", "grades"])

    assert result.exit_code == 0, result.output
    assert "Discrete Mathematics" in result.output
    assert "2026-2027 Fall Term" in result.output
    assert "A+" in result.output
    # 表头存在。
    assert "学期" in result.output and "课程代码" in result.output


def test_sis_grades_empty(runner, cli_group, monkeypatch) -> None:
    import westlake_survival.sis as sis_pkg

    monkeypatch.setattr(sis_pkg, "grades", lambda: [])
    result = runner.invoke(cli_group, ["sis", "grades"])
    assert result.exit_code == 0
    assert "成绩为空" in result.output


def test_sis_grades_blank_grade_shows_dash(runner, cli_group, monkeypatch) -> None:
    """未出分（空等级）显示为 ``—``，不出现空列。"""
    import westlake_survival.sis as sis_pkg

    monkeypatch.setattr(
        sis_pkg, "grades", lambda: [Grade("CST 2000", "Discrete Mathematics", "T", "", "")]
    )
    result = runner.invoke(cli_group, ["sis", "grades"])
    assert result.exit_code == 0
    assert "—" in result.output


def test_sis_grades_error_exit_code(runner, cli_group, monkeypatch) -> None:
    import westlake_survival.sis as sis_pkg
    from westlake_survival.exceptions import AuthError

    def boom():
        raise AuthError("会话未认证")

    monkeypatch.setattr(sis_pkg, "grades", boom)
    result = runner.invoke(cli_group, ["sis", "grades"])
    assert result.exit_code == 1
    assert "错误" in result.stderr


# --------------------------------------------------------------------------- #
# sis exams
# --------------------------------------------------------------------------- #
def test_sis_exams_renders(runner, cli_group, monkeypatch) -> None:
    import westlake_survival.sis as sis_pkg

    items = [
        ExamSlot("PHY 1004", "General Physics Laboratory Ⅱ", "", "", "", "", "", ""),
        ExamSlot(
            "CST 2000",
            "Discrete Mathematics",
            "2027/01/06",
            "13:30 - 15:30",
            "Final",
            "Open Book",
            "E13-509",
            "7",
        ),
    ]
    monkeypatch.setattr(sis_pkg, "exam_schedule", lambda: items)
    result = runner.invoke(cli_group, ["sis", "exams"])

    assert result.exit_code == 0, result.output
    assert "General Physics Laboratory Ⅱ" in result.output
    assert "2027/01/06" in result.output
    assert "Final" in result.output
    assert "课程代码" in result.output


def test_sis_exams_empty(runner, cli_group, monkeypatch) -> None:
    import westlake_survival.sis as sis_pkg

    monkeypatch.setattr(sis_pkg, "exam_schedule", lambda: [])
    result = runner.invoke(cli_group, ["sis", "exams"])
    assert result.exit_code == 0
    assert "考试安排为空" in result.output


def test_sis_exams_error_exit_code(runner, cli_group, monkeypatch) -> None:
    import westlake_survival.sis as sis_pkg
    from westlake_survival.exceptions import ActionError

    def boom():
        raise ActionError("组件未授权")

    monkeypatch.setattr(sis_pkg, "exam_schedule", boom)
    result = runner.invoke(cli_group, ["sis", "exams"])
    assert result.exit_code == 1
    assert "错误" in result.stderr


# --------------------------------------------------------------------------- #
# sis 子命令树
# --------------------------------------------------------------------------- #
def test_sis_help_lists_grades_and_exams(runner, cli_group) -> None:
    result = runner.invoke(cli_group, ["sis", "--help"])
    assert result.exit_code == 0, result.output
    assert "grades" in result.output
    assert "exams" in result.output


# --------------------------------------------------------------------------- #
# research 注册到顶层命令树
# --------------------------------------------------------------------------- #
def test_research_registered_on_cli(cli_group) -> None:
    assert "research" in cli_group.commands
    assert cli_group.commands["research"].name == "research"


def test_top_level_help_lists_research(runner, cli_group) -> None:
    result = runner.invoke(cli_group, ["--help"])
    assert result.exit_code == 0, result.output
    assert "research" in result.output


def test_research_runs_through_top_level_tree(runner, cli_group, monkeypatch) -> None:
    """``westlake research --limit 2`` 走顶层树，调用 research.latest。"""
    from datetime import datetime

    from westlake_survival.research import ResearchItem

    calls: list[tuple] = []

    def fake(category=None, limit=None, **kwargs):
        calls.append((category, limit))
        return [
            ResearchItem(
                title="测试条目",
                category="生命健康 / Good Health & Wellbeing",
                summary="测试条目",
                date=datetime(2025, 10, 16),
                url="https://x/t20251016_1.html",
            )
        ]

    monkeypatch.setattr("westlake_survival.research.latest", fake)
    result = runner.invoke(cli_group, ["research", "--limit", "2"])

    assert result.exit_code == 0, result.output
    assert "测试条目" in result.output
    assert calls == [(None, 2)]
