"""端到端：临时配置目录（``WESTLAKE_HOME``）必须是沙箱，绝不碰本机真实钥匙串。

背景（2026-10-28）：仓库测试里有一条 ``sso creds set`` 用例只重定位了
``WESTLAKE_HOME``，没关钥匙串；在本机装了 keyring 的机器上，它把假账号
``20210000`` 写进了真实的 Windows 凭据管理器（``service=westlake_survival``）。
之后真实登录先读到假凭据，长期报「密码错误」，状态页还显示「钥匙串有凭据」。

这条用例走**真实链路**：真实子进程 + 真实 CLI + 本机真实 keyring 后端，
核对三件事：
1. 临时目录写入落在临时 ``credentials.txt``；
2. 真实钥匙串里没有多出假账号条目，指针项前后一致；
3. 临时目录里的读取只看到临时凭据（读路径同样隔离）。

本机没装 keyring / 后端不可用时跳过——没有钥匙串就没有这条风险。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

KEYRING_SERVICE = "westlake_survival"
KEYRING_SID_KEY = "__westlake__"
FAKE_SID = "20210000"  # 占位假号，不是任何人的真实学号
FAKE_PASSWORD = "not-a-real-password"

SRC_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = SRC_ROOT.parent


def _keyring():
    """返回可用的真实 keyring 模块；不可用返回 ``None``。"""
    try:
        import keyring
    except Exception:  # noqa: BLE001 - 未安装即跳过
        return None
    try:
        keyring.get_password(KEYRING_SERVICE, KEYRING_SID_KEY)
    except Exception:  # noqa: BLE001 - 后端初始化失败
        return None
    return keyring


def _run(args: list[str], home: Path) -> subprocess.CompletedProcess:
    """在临时配置目录里跑真实 CLI 子进程（**不设** WESTLAKE_NO_KEYRING）。"""
    env = dict(os.environ)
    env["WESTLAKE_HOME"] = str(home)
    env.pop("WESTLAKE_NO_KEYRING", None)
    env.pop("WESTLAKE_CREDENTIALS", None)
    env["PYTHONPATH"] = str(SRC_ROOT) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    return subprocess.run(
        [sys.executable, "-m", "westlake_survival", *args],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )


def test_temp_home_never_writes_real_keyring(tmp_path) -> None:
    """临时目录里 ``creds set`` 只写文件；真实钥匙串前后不变。"""
    keyring = _keyring()
    if keyring is None:
        pytest.skip("本机没有可用的 keyring 后端，跳过")

    pointer_before = keyring.get_password(KEYRING_SERVICE, KEYRING_SID_KEY)
    had_fake = keyring.get_password(KEYRING_SERVICE, FAKE_SID) is not None

    home = tmp_path / "home"
    result = _run(["sso", "creds", "set", "--sid", FAKE_SID, "--password", FAKE_PASSWORD], home)
    assert result.returncode == 0, result.stdout + result.stderr

    # 1) 写进了临时目录，并明确说明没碰钥匙串。
    stored = home / "credentials.txt"
    assert stored.exists(), result.stdout
    assert stored.read_text(encoding="utf-8") == f"{FAKE_SID}:{FAKE_PASSWORD}"
    assert "沙箱" in result.stdout or "WESTLAKE_HOME" in result.stdout

    # 2) 真实钥匙串没有新增假账号，指针项也没被改。
    pointer_after = keyring.get_password(KEYRING_SERVICE, KEYRING_SID_KEY)
    assert had_fake or keyring.get_password(KEYRING_SERVICE, FAKE_SID) is None, (
        "假账号被写进了真实钥匙串"
    )
    assert (pointer_before or "") == (pointer_after or ""), "真实钥匙串的指针项被沙箱写入改动"


def test_temp_home_reads_stay_inside_sandbox(tmp_path) -> None:
    """临时目录里的读取只看临时凭据，不会被本机钥匙串里的真实账号顶替。"""
    keyring = _keyring()
    if keyring is None:
        pytest.skip("本机没有可用的 keyring 后端，跳过")
    if keyring.get_password(KEYRING_SERVICE, KEYRING_SID_KEY) is None:
        pytest.skip("本机钥匙串没有真实凭据，这条用例没有区分度")

    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    (home / "credentials.txt").write_text(
        f"{FAKE_SID}:{FAKE_PASSWORD}", encoding="utf-8"
    )

    result = _run(["sso", "creds", "status"], home)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "配置文件" in result.stdout
    assert "keyring" in result.stdout
    assert "已忽略" in result.stdout
