"""CLI 基础：--version、命令树、编码兜底。"""

from __future__ import annotations

import importlib

from westlake_survival._version import __version__


def test_version(runner, cli_group) -> None:
    result = runner.invoke(cli_group, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_help_lists_all_subcommands(runner, cli_group) -> None:
    result = runner.invoke(cli_group, ["--help"])
    assert result.exit_code == 0
    for name in (
        "sso",
        "calendar",
        "transit",
        "canvas",
        "sis",
        "lib",
        "pms",
        "context",
        "webui",
    ):
        assert name in result.output


def test_cli_export_is_callable_group(cli_group) -> None:
    import click

    assert isinstance(cli_group, click.Group)


def test_windows_stream_reconfigure_is_silent_on_failure(monkeypatch) -> None:
    """reconfigure 抛异常时应静默（不影响导入）。"""
    import sys

    cli_pkg = importlib.import_module("westlake_survival.cli")

    class _BadStream:
        def reconfigure(self, **kwargs):
            raise OSError("stream closed")

    monkeypatch.setattr(sys, "platform", "win32", raising=False)
    monkeypatch.setattr(sys, "stdout", _BadStream())
    monkeypatch.setattr(sys, "stderr", _BadStream())
    # 不应抛异常。
    cli_pkg._configure_windows_streams()


def test_main_module_entrypoint_help(capsys) -> None:
    """python -m westlake_survival 的入口 help 可正常输出。"""
    from click.testing import CliRunner

    from westlake_survival.cli import cli

    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Commands" in result.output
