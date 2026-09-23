"""``westlake context`` 命令测试。"""

from __future__ import annotations

import pytest

from westlake_survival.exceptions import AuthError


def test_context_prints_snapshot(runner, cli_group, monkeypatch) -> None:
    """打桩 snapshot().to_str() 返回固定串。"""
    import westlake_survival.context as context_pkg

    fixed = "# 固定快照\n第 4 周 测试内容"

    class FakeContext:
        def to_str(self) -> str:
            return fixed

    captured = {}

    def fake_snapshot(level=context_pkg.Level.NORMAL, now=None):
        captured["level"] = level
        return FakeContext()

    monkeypatch.setattr(context_pkg, "snapshot", fake_snapshot)
    result = runner.invoke(cli_group, ["context"])
    assert result.exit_code == 0
    assert fixed in result.output
    assert captured["level"] == context_pkg.Level.NORMAL


def test_context_level_option_passed_through(runner, cli_group, monkeypatch) -> None:
    import westlake_survival.context as context_pkg

    captured = {}

    class FakeContext:
        def to_str(self) -> str:
            return "x"

    def fake_snapshot(level=context_pkg.Level.NORMAL, now=None):
        captured["level"] = level
        return FakeContext()

    monkeypatch.setattr(context_pkg, "snapshot", fake_snapshot)
    result = runner.invoke(cli_group, ["context", "--level", "verbose"])
    assert result.exit_code == 0
    assert captured["level"] == context_pkg.Level.VERBOSE


def test_context_invalid_level_rejected(runner, cli_group) -> None:
    result = runner.invoke(cli_group, ["context", "--level", "bogus"])
    assert result.exit_code != 0
