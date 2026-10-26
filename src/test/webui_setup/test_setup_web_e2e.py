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
    """设置页有表单、密码框、令牌框、保存接口与状态表。"""
    base, _ = server
    status, html = _get(base + "/setup")
    assert status == 200
    for marker in ("setupForm", 'type="password"', "/setup/api/save", "账号配置",
                   'name="canvas_token"', "clearCanvasBtn", "/setup/api/canvas/clear"):
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


# --------------------------------------------------------------------------- #
# Canvas 令牌（2026-10-26 A）：网页可存、可查有无、可清除。
# 校验走本地假 Canvas（``WESTLAKE_CANVAS_BASE``)，不碰真实服务与真实账号。
# --------------------------------------------------------------------------- #
import http.server
import threading


def _serve_fake_canvas(status: int):
    """起一个只返回固定状态码的假 Canvas API，返回 (httpd, base_url)。"""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler 约定
            body = json.dumps({"id": 1, "name": "stub"}).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # 静默，避免污染测试输出
            pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}/api/v1"


@pytest.fixture
def webui_factory(tmp_path):
    """按需起 webui 进程（可带额外环境变量），用完整轮关停。"""
    processes = []

    def start(**extra_env):
        home = tmp_path / f"wlhome{len(processes)}"
        home.mkdir()
        port = _free_port()
        env = dict(os.environ)
        env["WESTLAKE_HOME"] = str(home)
        env["WESTLAKE_NO_KEYRING"] = "1"
        env.pop("WESTLAKE_CREDENTIALS", None)
        env.pop("WESTLAKE_CANVAS_TOKEN", None)
        env.update(extra_env)
        process = subprocess.Popen(
            [sys.executable, "-m", "westlake_survival", "webui", "serve", "--port", str(port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        processes.append(process)
        base = f"http://127.0.0.1:{port}"
        deadline = time.time() + 40
        while time.time() < deadline:
            try:
                if _get(base + "/setup", timeout=2)[0] == 200:
                    return base, home
            except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
                time.sleep(0.6)
        raise RuntimeError("webui 未能在 40 秒内启动")

    yield start
    for process in processes:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover
            process.kill()


def test_canvas_token_rejected_is_not_saved(webui_factory) -> None:
    """被 Canvas 明确拒绝（401）的令牌不落盘——它落盘会抢在统一密码前面把 Canvas 锁死。"""
    httpd, canvas_base = _serve_fake_canvas(401)
    try:
        base, home = webui_factory(WESTLAKE_CANVAS_BASE=canvas_base)
        status, payload = _post(
            base + "/setup/api/save", {"canvas_token": "bad-token", "verify": True}
        )
    finally:
        httpd.shutdown()

    assert status == 200, payload
    assert payload["canvas"]["saved"] is False
    assert "被拒" in payload["canvas"]["note"]
    assert not (home / "canvas_token.txt").exists()


def test_canvas_token_only_saved_stored_and_cleared(webui_factory) -> None:
    """令牌可脱离学号密码单独提交；/stored 只报有无不回显；清除后文件消失。"""
    httpd, canvas_base = _serve_fake_canvas(200)
    try:
        base, home = webui_factory(WESTLAKE_CANVAS_BASE=canvas_base)
        status, payload = _post(
            base + "/setup/api/save", {"canvas_token": "good-token-xyz", "verify": True}
        )
        assert status == 200, payload
        assert payload["canvas"]["saved"] is True
        token_file = home / "canvas_token.txt"
        assert token_file.read_text(encoding="utf-8").strip() == "good-token-xyz"
        assert not (home / "credentials.txt").exists(), "只存令牌不应写教务凭据"

        with urllib.request.urlopen(base + "/setup/api/stored", timeout=10) as response:
            stored = json.loads(response.read().decode("utf-8"))
        assert stored["canvas"]["configured"] is True
        assert stored["canvas"]["source"] == "本地文件"
        assert "good-token-xyz" not in json.dumps(stored, ensure_ascii=False)

        request = urllib.request.Request(base + "/setup/api/canvas/clear", data=b"{}", method="POST")
        with urllib.request.urlopen(request, timeout=10) as response:
            cleared = json.loads(response.read().decode("utf-8"))
        assert cleared["cleared"] is True
        assert cleared["canvas"]["configured"] is False
        assert not token_file.exists()
    finally:
        httpd.shutdown()
