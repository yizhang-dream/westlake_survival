"""能力总览的端到端测试：真启动 webui 进程，真 HTTP 请求，核对页面与 API。

运行：``pytest src/test/capabilities/test_capabilities_e2e.py -q``
（不依赖外网；三个数据源都是库内自省）。
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

from westlake_survival.capabilities import collect


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _get(url: str, timeout: float = 60.0) -> tuple[int, str]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.status, response.read().decode("utf-8")


@pytest.fixture(scope="module")
def server():
    """真启一个 webui 进程，返回基地址。"""
    port = _free_port()
    process = subprocess.Popen(
        [sys.executable, "-m", "westlake_survival", "webui", "serve", "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 40
    while time.time() < deadline:
        try:
            status, _ = _get(base + "/capabilities", timeout=2)
            if status == 200:
                break
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
            time.sleep(0.6)
    else:  # pragma: no cover
        process.terminate()
        raise RuntimeError("webui 未能在 40 秒内启动")
    try:
        yield base
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover
            process.kill()


def test_api_counts_match_introspection(server: str) -> None:
    """API 返回的计数与库内自省一致（CLI 26 / MCP 25 / Web 12 是当时的实际值）。"""
    status, body = _get(server + "/api/capabilities")
    payload = json.loads(body)
    expected = collect()
    counts = payload["counts"]

    assert status == 200
    assert counts["total"] == len(expected)
    assert counts["cli"] == sum(1 for item in expected if item.kind == "cli")
    assert counts["mcp"] == sum(1 for item in expected if item.kind == "mcp")
    assert counts["web"] == sum(1 for item in expected if item.kind == "web")
    # 规模下限：防止自省静默退化成空表
    assert counts["cli"] >= 20 and counts["mcp"] >= 20 and counts["web"] >= 10


def test_page_lists_every_cli_group_and_mcp_tool(server: str) -> None:
    """页面里逐项出现每个 CLI 组与每个 MCP 工具名。"""
    status, html = _get(server + "/capabilities")
    assert status == 200

    items = collect()
    missing = [
        item.name
        for item in items
        if item.kind in ("cli", "mcp") and item.name not in html
    ]
    assert not missing, f"页面缺少这些能力条目：{missing[:5]}"


def test_auth_classification_is_sane(server: str) -> None:
    """教务/Canvas 类标为需凭据，公开数据类标为公开。"""
    _, body = _get(server + "/api/capabilities")
    rows = {row["name"]: row for row in json.loads(body)["items"]}

    assert rows["westlake sis"]["needs_auth"] is True
    assert rows["westlake canvas"]["needs_auth"] is True
    assert rows["mcp:sis_grades"]["needs_auth"] is True
    assert rows["mcp:canvas_submit"]["needs_auth"] is True
    assert rows["westlake calendar"]["needs_auth"] is False
    assert rows["mcp:program_plan"]["needs_auth"] is False
    assert rows["westlake map"]["needs_auth"] is False


def test_cli_subcommands_exposed(server: str) -> None:
    """CLI 组的子命令名也出现在页面上（便于直接照抄命令）。"""
    _, html = _get(server + "/capabilities")
    _, body = _get(server + "/api/capabilities")
    rows = {row["name"]: row for row in json.loads(body)["items"]}

    program = rows["westlake program"]
    names = [sub["name"] for sub in program["commands"]]
    assert {"overview", "curriculum", "majors", "plan", "courses", "course"} <= set(names)
    for name in names:
        assert f">{name}<" in html or f"<code>{name}</code>" in html


def test_all_pages_share_the_new_shell(server: str) -> None:
    """所有主要页面共用新外壳：暖纸底令牌、主题切换、内容卡片。

    真 HTTP 逐页取，核对的是最终产物（渲染后的 HTML），不是模板源码。
    """
    pages = ["/", "/program", "/capabilities", "/map", "/courses", "/news", "/faculty", "/sis", "/canvas", "/careers", "/affairs"]
    for path in pages:
        status, html = _get(server + path)
        assert status == 200, path
        assert 'id="themeToggle"' in html, path
        assert 'data-theme="light"' in html, path
        assert "wrap sheet" in html, path
        assert "--bg: #f7f6f3" in html, path  # 西湖品牌配色版


def test_capabilities_page_documents_http_endpoints(server: str) -> None:
    """HTTP 接口说明并入能力页（瘦身裁定），覆盖全部接口；导航不再有 API 项。"""
    status, html = _get(server + "/capabilities")
    assert status == 200
    assert "HTTP 接口" in html
    for path in ("/api/context", "/api/capabilities", "/api/shuttle", "/ical/shuttle", "/ical/schedule"):
        assert path in html, path
    assert 'href="/api"' not in html.split("</header>")[0]  # 导航无 API 项


def test_calendar_page_offers_ics_subscription(server: str) -> None:
    """校历页承载 ICS 订阅入口（瘦身后 API 页的唯一用户价值搬到这里）。"""
    status, html = _get(server + "/calendar")
    assert status == 200
    assert "订阅到日历" in html
    assert "/ical/shuttle" in html and "/ical/schedule" in html


def test_json_endpoints_still_valid(server: str) -> None:
    """说明页旁边，原始 JSON 接口仍返回可解析内容。"""
    for path in ("/api/context", "/api/capabilities"):
        status, body = _get(server + path)
        assert status == 200, path
        payload = json.loads(body)
        assert isinstance(payload, dict), path


def test_all_frontend_pages_render(server: str) -> None:
    """前端覆盖扩展后：学业/Canvas/招聘页真渲染（SIS/Canvas 需凭据，允许降级提示）。"""
    for path, markers in (
        ("/sis", ("学业（SIS）", "本学期课表")),
        ("/canvas", ("Canvas",)),
        ("/careers", ("招聘岗位",)),
        ("/affairs", ("网上办事大厅",)),
    ):
        status, html = _get(server + path)
        assert status == 200, path
        for marker in markers:
            assert marker in html, (path, marker)


def test_services_scan_api(server: str) -> None:
    """/api/services/scan 按钮后端：小集合直连普查返回活服务。"""
    status, body = _get(server + "/api/services/scan?hosts=www,mydisk")
    payload = json.loads(body)
    assert status == 200
    assert payload["total"] == 2
    hosts = [r["host"] for r in payload["alive"]]
    assert "www" in hosts and "mydisk" not in hosts


def test_sis_page_has_nine_blocks(server: str) -> None:
    """学业页九块信息全渲染（空数据块显示空态而非消失）。"""
    status, html = _get(server + "/sis")
    assert status == 200
    for section in ("本学期课表", "成绩与 GPA", "考试安排", "待评教", "个人信息", "学籍信息", "住宿", "荣誉记录", "志愿服务"):
        assert section in html, section
