"""src/test/cli 公共夹具。

所有测试**离线**：各命令通过 ``monkeypatch`` 打桩依赖模块的公开函数，
不发起真实网络请求。
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from westlake_survival.canvas import reset_canvas
from westlake_survival.cli import cli
from westlake_survival.pms import reset_pms
from westlake_survival.sso import cred_clear


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def isolated_home(monkeypatch, tmp_path):
    """把配置根目录重定位到临时目录，并清掉凭据/token 相关环境变量。

    ``WESTLAKE_NO_KEYRING`` 一起钉住：本机真装着 keyring 时，用例若走到缺省
    分支会把假账号写进**真实系统钥匙串**，之后真实登录先读到假凭据、长期报
    「密码错误」（2026-10-28 踩过）。隔离后读写都不碰钥匙串；需要观察 keyring
    分支的用例在自己那里显式放开（见 ``test_cli_creds_keyring`` 的打桩）。
    """
    monkeypatch.setenv("WESTLAKE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("WESTLAKE_NO_KEYRING", "1")
    monkeypatch.delenv("WESTLAKE_CREDENTIALS", raising=False)
    monkeypatch.delenv("WESTLAKE_CANVAS_TOKEN", raising=False)
    cred_clear()
    reset_canvas()
    reset_pms()
    yield tmp_path / "home"
    cred_clear()
    reset_canvas()
    reset_pms()


@pytest.fixture
def cli_group():
    """顶层 click group（供需要直接 invoke 的测试使用）。"""
    return cli
