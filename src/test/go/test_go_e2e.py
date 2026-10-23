"""`westlake go` 的端到端测试：真进程启动、真 HTTP 就绪、浏览器可关。

运行：``pytest src/test/go/test_go_e2e.py -q``
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_go_starts_webui_without_browser(tmp_path) -> None:
    """`westlake go --no-browser` 真启动：服务可访问，help 语义不变。"""
    port = _free_port()
    env = dict(os.environ)
    env["WESTLAKE_HOME"] = str(tmp_path)
    env["WESTLAKE_NO_KEYRING"] = "1"
    process = subprocess.Popen(
        [sys.executable, "-m", "westlake_survival", "go", "--port", str(port), "--no-browser"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        env=env,
    )
    url = f"http://127.0.0.1:{port}/"
    # 仪表盘首访要拉校历/班车/天气，实测可到 10 秒级：单次等待放宽，总限 60 秒。
    deadline = time.time() + 60
    ok = False
    try:
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=15) as response:
                    if response.status == 200:
                        ok = True
                        break
            except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
                time.sleep(1)
        assert ok, "go 启动的 WebUI 应可访问"
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def test_go_in_help() -> None:
    """`westlake --help` 与能力清单都能看到 go（用户第一入口）。"""
    result = subprocess.run(
        [sys.executable, "-m", "westlake_survival", "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert result.returncode == 0
    assert "go" in result.stdout

    from westlake_survival.capabilities import as_dict

    names = [row["name"] for row in as_dict()["items"]]
    assert "westlake go" in names
