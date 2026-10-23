"""首次配置向导的端到端测试：真进程、真文件、真退出码。

运行：``pytest src/test/setup/test_setup_e2e.py -q``（默认非 live，不需外网）

隔离方式：``WESTLAKE_HOME`` 指向临时目录；保存路径强制 ``--no-keyring``，
确保绝不碰真实的系统钥匙串。
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest
from pathlib import Path


def _run(args: list[str], home: Path, *, timeout: float = 45.0) -> subprocess.CompletedProcess:
    """以临时 home 启动真实 CLI 进程（stdin 关闭，模拟非交互环境）。"""
    env = dict(os.environ)
    env["WESTLAKE_HOME"] = str(home)
    env["WESTLAKE_NO_KEYRING"] = "1"  # 读也不读钥匙串，保证用例彼此隔离
    env.pop("WESTLAKE_CREDENTIALS", None)
    return subprocess.run(
        [sys.executable, "-m", "westlake_survival", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        stdin=subprocess.DEVNULL,
        env=env,
    )


def test_setup_writes_credentials_without_keyring(tmp_path) -> None:
    """向导在隔离目录里写凭据文件，并打印逐项结果。"""
    result = _run(
        ["setup", "--sid", "20259999", "--password", "dummy-pass",
         "--no-verify", "--force-save", "--no-keyring"],
        tmp_path,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    cred = tmp_path / "credentials.txt"
    assert cred.exists(), "凭据文件应写入 WESTLAKE_HOME"
    assert cred.read_text(encoding="utf-8").startswith("20259999:")
    for marker in ("首次配置", "教务 SIS", "Canvas", "公开功能", "已保存到"):
        assert marker in result.stdout, marker


def test_bare_invocation_without_credentials_does_not_hang(tmp_path) -> None:
    """非交互终端下不带子命令：快速打印帮助，不进入向导、不阻塞。"""
    result = _run([], tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Commands:" in result.stdout
    assert "西湖生存手册 · 首次配置" not in result.stdout  # 没进向导
    assert "提示：还没有配置教务账号" in result.stdout


def test_bare_invocation_with_credentials_skips_wizard(tmp_path) -> None:
    """已有凭据时同样只打印帮助。"""
    (tmp_path / "credentials.txt").write_text("20259999:whatever\n", encoding="utf-8")

    result = _run([], tmp_path)

    assert result.returncode == 0
    assert "Commands:" in result.stdout
    assert "检测到还没有配置" not in result.stdout
    assert "提示：还没有配置教务账号" not in result.stdout


def test_setup_appears_in_help(tmp_path) -> None:
    """`westlake --help` 里能直接看到 setup 入口。"""
    result = _run(["--help"], tmp_path)

    assert result.returncode == 0
    assert "setup" in result.stdout


def test_cli_creds_show_reveals_stored_password(tmp_path) -> None:
    """`westlake sso creds show` 能找回本机存的教务密码（忘记密码场景）。"""
    (tmp_path / "credentials.txt").write_text("20259999:dummy-pass" + chr(10), encoding="utf-8")
    result = _run(["sso", "creds", "show"], tmp_path)
    assert result.returncode == 0
    assert "20259999" in result.stdout
    assert "dummy-pass" in result.stdout


@pytest.mark.live
def test_live_sis_auth_accepts_stored_credentials() -> None:
    """live：用本机已存凭据真登一次 SIS（IAM 主路径 + PS 回落，两条都算通过）。"""
    from westlake_survival.sso import SISAuth

    auth = SISAuth()
    auth.refresh()
    assert auth.session.cookies.get("PS_TOKEN")


@pytest.mark.live
def test_live_canvas_usable_without_token() -> None:
    """live：无 token 时 CanvasClient 回退统一认证会话，真实拉到课程。"""
    from westlake_survival.canvas import client as canvas_client

    original = canvas_client.resolve_token
    canvas_client.resolve_token = lambda token=None: None
    try:
        client = canvas_client.CanvasClient()
        me = client.me()
        courses = client.list_courses()
        assert me.name
        assert isinstance(courses, list) and courses
    finally:
        canvas_client.resolve_token = original
