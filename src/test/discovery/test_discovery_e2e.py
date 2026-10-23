"""服务发现与办事大厅的端到端测试（真网络、真目录、真进程）。

运行：``pytest src/test/discovery/test_discovery_e2e.py -q -m live``
（子域普查走直连；目录接口免登录）
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

from westlake_survival.discovery import app_directory, subdomain_census

pytestmark = pytest.mark.live


def test_live_app_directory_returns_census() -> None:
    """免登录目录返回大量应用，且可按关键词过滤。"""
    apps = app_directory()
    assert len(apps) >= 150  # 2026-10-24 实测 176；下限防接口退化
    assert any("预约" in a.name for a in apps)
    hits = app_directory("预约")
    assert 3 <= len(hits) <= 20
    assert all("预约" in a.name or "预约" in a.department for a in hits)


def test_live_subdomain_census_direct_connection() -> None:
    """直连普查：已知活服务命中，通配 502 与不可达被正确标记为非活。"""
    results = subdomain_census(hosts=["www", "hpc", "mirrors", "one", "mydisk"])
    by_host = {r.host: r for r in results}

    assert by_host["www"].alive and "西湖大学" in by_host["www"].title
    assert by_host["hpc"].alive and "高性能计算中心" in by_host["hpc"].title
    assert by_host["mirrors"].alive
    assert by_host["one"].alive
    assert not by_host["mydisk"].alive  # 真内网（2026-10-24 实测直连也不可达）


def test_live_probe_scan_cli() -> None:
    """`westlake probe scan` 真进程跑通：普查表 + 目录计数。"""
    result = subprocess.run(
        [sys.executable, "-m", "westlake_survival", "probe", "scan",
         "--hosts", "www,hpc,mirrors,mydisk", "--timeout", "4"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
        stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "子域普查" in result.stdout
    assert "hpc.westlake.edu.cn" in result.stdout
    assert "www.westlake.edu.cn" in result.stdout
    assert "办事大厅目录" in result.stdout


def test_webui_affairs_page_lists_apps() -> None:
    """WebUI /affairs 渲染目录与入口表。"""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen(
        [sys.executable, "-m", "westlake_survival", "webui", "serve", "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 40
        html = ""
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(base + "/affairs", timeout=20) as response:
                    if response.status == 200:
                        html = response.read().decode("utf-8")
                        break
            except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
                time.sleep(0.8)
        assert "网上办事大厅" in html
        assert "资源预约" in html or "场馆预约" in html
        assert "HPC 门户" in html and "预约中心" in html
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
