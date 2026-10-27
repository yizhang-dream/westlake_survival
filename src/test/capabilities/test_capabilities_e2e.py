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
    """学业页核心分组全渲染（空数据块显示空态而非消失）。"""
    status, html = _get(server + "/sis")
    assert status == 200
    for section in ("本学期课表", "成绩（", "考试安排", "待评教",
                    "学籍档案", "校园记录", "社团与资助",
                    "住宿", "荣誉", "志愿服务"):
        assert section in html, section


def test_canvas_and_affairs_blocks_thick(server: str) -> None:
    """Canvas 考试/测验/成绩/公告区与办事页待办/进行中区（空态也渲染）。"""
    _, canvas_html = _get(server + "/canvas")
    for marker in ("考试", "测验", "课程成绩", "最新公告", "未发布"):
        assert marker in canvas_html, marker
    assert "全局自动目录" in canvas_html  # 目录改为 base.html JS 全局自动生成（curl 可见脚本特征）
    _, affairs_html = _get(server + "/affairs")
    # 待办为 0 是真实态：空态文案也算渲染到位
    assert ("我的待办" in affairs_html) or ("没有待办任务" in affairs_html)
    assert "我发起的流程" in affairs_html


def test_sis_grades_full_history_rendered(server: str) -> None:
    """成绩历史全量渲染：≥30 门课、跨 ≥3 学期、总学分卡片有数值。"""
    _, html = _get(server + "/sis")
    import re as _re

    total = _re.search(r"总课程</div><div class=\"value\"[^>]*>(\d+)", html)
    assert total and int(total.group(1)) >= 30, total.group(0) if total else "no card"
    credits = _re.search(r"总学分</div><div class=\"value\"[^>]*>([\d.]+)", html)
    assert credits and float(credits.group(1)) > 50
    terms = set(_re.findall(
        r"(202\d-20\d\d [春夏秋冬]季学期|20\d\d-20\d\d (?:Fall|Spring|Winter|Summer) Term)",
        html,
    ))
    assert len(terms) >= 3, terms


def test_sis_profile_blocks_full_render(server: str) -> None:
    """个人信息 11 项 / 学籍 20 项 / 扩展 16 项全渲染（SIS 三页全量）。"""
    _, html = _get(server + "/sis")
    for label, count in (("个人信息", "11 项"), ("学籍信息", "20 项"), ("扩展信息", "16 项")):
        assert label in html, label
        assert count in html, count
    # 学籍关键字段上页面（导师/预计毕业/书院）；界面语言切中文后表头也是中文
    assert "导师" in html and ("预计毕业" in html or "Expected Graduation" in html)


def test_sis_all_blocks_render(server: str) -> None:
    """24 块全接线：注册/志愿/预约/离校/社团/资助/第二课堂/导师/其他申请都上页面。"""
    _, html = _get(server + "/sis")
    for marker in (
        "第二课堂",           # second_classroom（首页瓦片入口）
        "学业导师",           # advising（分配结果 + 两轮名单）
        "学籍异动",           # other_applications（异动流程 tab）
        "学期注册缴费",       # registration（含缴费提示句）
        "生源信息确认",       # source_info_status
        "志愿服务",           # volunteer_history（总时长 + 明细）
        "心理预约",           # appointments（周历）
        "离校检查",           # leaving_check
        "我的社团",           # my_clubs
        "社团目录",           # student_orgs 目录
        "39 个",              # 目录计数徽标
        "社团简介",           # clubwiki 离线简介（改写自 WikiLake，无凭据也渲染）
        "贷款 / 勤工助学 / 海外交流",  # aid 汇总块
        "anchor-nav",         # 吸顶锚点导航
        "grade-filter",       # 成绩表筛选器
    ):
        assert marker in html, marker
    # 志愿总时长实数值（24 拆为值 + 单位两段；单位随界面语言是 HOUR / 小时）
    assert "<span data-count=\"24\">24</span>" in html
    assert "HOUR" in html or "小时" in html
    assert "currently not open" in html or "缴费" in html
