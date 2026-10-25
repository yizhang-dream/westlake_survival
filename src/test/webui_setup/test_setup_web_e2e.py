"""网页端账号配置的端到端测试：真服务、真表单接口、真文件。

运行：``pytest src/test/webui_setup/test_setup_web_e2e.py -q``
（不打外网：``verify=false`` 路径；隔离：``WESTLAKE_HOME`` + ``WESTLAKE_NO_KEYRING``）
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _get(url: str, timeout: float = 5.0) -> tuple[int, str]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.status, response.read().decode("utf-8")


#: 首页在已存凭据时会真去拉门户卡片/作业，单个请求可能跑到 20 秒档位；
#: 5 秒只适合静态页（/setup），首页用这个宽限值。
HOME_TIMEOUT = 60.0


def _post(url: str, payload: dict, timeout: float = 10.0) -> tuple[int, dict]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8") or "{}")


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    """真启 webui 进程：临时 home、禁用 keyring，绝不碰真实凭据。"""
    home = tmp_path_factory.mktemp("wlhome")
    port = _free_port()
    env = dict(os.environ)
    env["WESTLAKE_HOME"] = str(home)
    env["WESTLAKE_NO_KEYRING"] = "1"
    env.pop("WESTLAKE_CREDENTIALS", None)
    process = subprocess.Popen(
        [sys.executable, "-m", "westlake_survival", "webui", "serve", "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 40
    while time.time() < deadline:
        try:
            if _get(base + "/setup", timeout=2)[0] == 200:
                break
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
            time.sleep(0.6)
    else:  # pragma: no cover
        process.terminate()
        raise RuntimeError("webui 未能在 40 秒内启动")
    try:
        yield base, home
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover
            process.kill()


def test_setup_page_has_form_and_status(server) -> None:
    """设置页有表单、密码框、保存接口与状态表。"""
    base, _ = server
    status, html = _get(base + "/setup")
    assert status == 200
    for marker in ("setupForm", 'type="password"', "/setup/api/save", "账号配置"):
        assert marker in html, marker


def test_home_shows_banner_until_configured_then_clears(server) -> None:
    """未配置时首页有引导横幅；保存后横幅消失（同一会话内状态翻转）。"""
    base, home = server
    _, before = _get(base + "/", timeout=HOME_TIMEOUT)
    assert "还没有配置教务账号" in before
    assert 'href="/setup"' in before

    status, payload = _post(
        base + "/setup/api/save",
        {"sid": "20259999", "password": "dummy", "verify": False},
    )
    assert status == 200
    assert payload["sis"]["saved"] is True
    assert (home / "credentials.txt").exists()

    _, after = _get(base + "/", timeout=HOME_TIMEOUT)
    assert "还没有配置教务账号" not in after


def test_save_reports_per_service_without_echoing_password(server) -> None:
    """返回逐项结果；任何字段都不回显密码。"""
    base, _ = server
    status, payload = _post(
        base + "/setup/api/save",
        {"sid": "20259999", "password": "dummy-secret-value", "verify": False},
    )
    assert status == 200
    rendered = json.dumps(payload, ensure_ascii=False)
    assert "dummy-secret-value" not in rendered
    assert "sis" in payload and "sid" in payload and "canvas" not in payload


def test_empty_submission_rejected(server) -> None:
    """空学号/密码给 400，不落盘。"""
    base, home = server
    before = (home / "credentials.txt").read_text(encoding="utf-8") if (home / "credentials.txt").exists() else ""
    status, payload = _post(base + "/setup/api/save", {"sid": "", "password": ""})
    assert status == 400
    assert "error" in payload
    after = (home / "credentials.txt").read_text(encoding="utf-8") if (home / "credentials.txt").exists() else ""
    assert before == after


def test_stored_endpoint_returns_saved_credentials(server) -> None:
    """「查看密码」接口：保存后能取回学号与密码（本机密码管理器语义）。"""
    base, _ = server
    status, payload = _post(
        base + "/setup/api/save",
        {"sid": "20259999", "password": "dummy-pass", "verify": False},
    )
    assert status == 200
    with urllib.request.urlopen(base + "/setup/api/stored", timeout=10) as response:
        stored = json.loads(response.read().decode("utf-8"))
    assert stored["configured"] is True
    assert stored["sid"] == "20259999"
    assert stored["password"] == "dummy-pass"
