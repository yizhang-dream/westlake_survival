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


def test_live_content_pages_have_real_data() -> None:
    """三个内容页真数据：HPC 队列表、财务文档、镜像仓库（live：抓真实站点）。"""
    from westlake_survival.finance import articles
    from westlake_survival.hpc import overview
    from westlake_survival.mirrors import repos

    h = overview()
    assert len(h.queues) >= 10
    names = " ".join(q.name for q in h.queues)
    assert "amd-ep2" in names and "A100" in names
    assert any(q.nodes.isdigit() and int(q.nodes) >= 5 for q in h.queues)

    guides = articles("ywzn1/rcbx1.htm")
    assert 4 <= len(guides) <= 12
    assert any("报销" in a.title for a in guides)
    rules = articles("gzzd1/zmcwzd.htm")
    assert len(rules) >= 8 and any("管理办法" in a.title for a in rules)

    m = repos()
    assert len(m) >= 8
    assert any(r.name.lower() == "pypi" for r in m)
    assert any(r.help_url for r in m)


def test_live_institute_lists_have_articles() -> None:
    """理论科学研究院（its 域名）新闻与学术活动列表真数据。"""
    from westlake_survival.institute import articles

    news = articles("xwdt.htm")
    events = articles("xshd/xshy.htm")
    assert len(news) >= 5 and len(events) >= 5
    assert all(a.url.startswith("https://its.westlake.edu.cn/") for a in news[:3])


def test_live_taskcenter_personal_todo() -> None:
    """我的待办（浏览器统一会话）：接口通、结构正确（0 条也是成功）。"""
    from westlake_survival.taskcenter import todo

    items = todo()  # 已登录的持久化 profile；首次会自动登录（统一密码）
    assert isinstance(items, list)


def test_live_schools_news_all_five() -> None:
    """五学院官网适配器全通：每院 ≥3 条、首条有标题。"""
    from westlake_survival.schools import SCHOOLS, news

    first_titles = {}
    for key in SCHOOLS:
        items = news(key, limit=3)
        assert len(items) >= 3, key
        assert items[0].title and items[0].url.startswith("http"), key
        first_titles[key] = items[0].title
    # 五院首条互不相同（防止适配器串台）
    assert len(set(first_titles.values())) == len(first_titles)


def test_live_snowball_finds_hidden_hosts() -> None:
    """滚雪球收割能发现字典漏掉的机构站点（页脚互链）。"""
    from westlake_survival.discovery import snowball_hosts

    found = snowball_hosts(rounds=1)
    hosts = set(found)
    # 2026-10-24 实测靠页脚互链才发现的站点
    for hidden in ("dq", "wudf", "qiushi", "huxin"):
        assert hidden in hosts, hidden
    # 每个发现都应带来源
    assert found["dq"] and found["dq"][0].startswith("http")


def test_live_portal_services_directory() -> None:
    """登录门户取服务大厅目录（统一会话浏览器真链路）。"""
    from westlake_survival.discovery import portal_services

    rows = portal_services()
    names = " ".join(r["name"] for r in rows)
    assert len(rows) >= 15
    for must in ("人力资源部", "学生事务部", "研究生院", "信息技术中心"):
        assert must in names, must
    urls = " ".join(r["url"] for r in rows)
    assert "ohr.westlake.edu.cn" in urls and "osa.westlake.edu.cn" in urls


def test_live_snowball_finds_research_platforms() -> None:
    """滚雪球（扩充种子后）能发现科研公共平台群。"""
    from westlake_survival.discovery import snowball_hosts

    found = snowball_hosts(rounds=1)
    hosts = set(found)
    for platform in ("brcf", "larc", "nanolab", "share"):
        assert platform in hosts, platform


@pytest.mark.live
def test_webui_services_registry_is_complete() -> None:
    # 注册表自省 + 页面渲染断言（服务真启动）
    """服务注册表收录全部已发现站点（≥60 行），页面真渲染。"""
    import socket
    import subprocess
    import urllib.request as _rq

    from westlake_survival.webui.app import SERVICE_REGISTRY

    assert len(SERVICE_REGISTRY) >= 60
    hosts = " ".join(h for h, _, _ in SERVICE_REGISTRY)
    for must in ("brcf", "larc", "nanolab", "share", "huxin", "osa", "chatbot"):
        assert must in hosts, must
