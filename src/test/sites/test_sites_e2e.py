"""sites 模块端到端测试（live：直连各站，慢但真实）。

覆盖三类抓取路（博达 / 静态 / 官网款 TRS）+ 索引 + WebUI /sites 页。
"""

from __future__ import annotations

import importlib

import pytest

pytestmark = pytest.mark.live


def _mod():
    return importlib.import_module("westlake_survival.sites")


def test_sites_index_no_network() -> None:
    """索引不触发网络：30 站、分组齐全、字段完整。"""
    mod = _mod()
    rows = mod.sites_index()
    assert len(rows) >= 30
    groups = {r["group"] for r in rows}
    assert {"科研平台", "部门机构", "招生与基金", "课题组"} <= groups
    for row in rows:
        assert row["key"] and row["name"] and row["url"].startswith("https://")


def test_brcf_notices_have_titles_and_dates() -> None:
    """博达站代表（生物医学中心）：通知公告有条目、标题非空、URL 绝对。"""
    mod = _mod()
    content = mod.site_content("brcf", limit=4)
    section = next(s for s in content.sections if s.label == "通知公告")
    assert section.items, "通知公告应有条目"
    for item in section.items:
        assert item.title.strip()
        assert item.url.startswith("https://brcf.westlake.edu.cn/")
    assert any(item.date for item in section.items)


def test_graduateschool_defense_announcements() -> None:
    """官网款 TRS（研究生院）：答辩公告含姓名与论文题目。"""
    mod = _mod()
    content = mod.site_content("graduateschool", limit=3)
    section = next(s for s in content.sections if s.label == "答辩公告")
    assert section.items
    first = section.items[0].title
    assert len(first) > 6  # 「姓名 论文题目」拼接


def test_intro_site_falls_back_to_intro() -> None:
    """特例站（astro）：不抓内容，返回简介。"""
    mod = _mod()
    content = mod.site_content("astro")
    assert content.intro
    assert not content.sections


def test_unknown_key_raises() -> None:
    """未知 key 报 KeyError 并提示可用列表。"""
    mod = _mod()
    with pytest.raises(KeyError):
        mod.site_content("no-such-site")


def test_hpc_manuals_full_nav() -> None:
    """HPC：四套手册目录全量（科学 16 章 + GPU + 冷冻电镜 + WRAP）+ PDF。"""
    mod = _mod()
    content = mod.site_content("hpc", limit=6)
    labels = {s.label for s in content.sections}
    assert {"科学工程计算集群手册", "GPU 集群用户手册", "冷冻电镜集群使用指南",
            "WRAP（RNA-Seq 平台）文档", "资料下载"} <= labels
    science = next(s for s in content.sections if s.label == "科学工程计算集群手册")
    assert len(science.items) >= 12, "科学工程手册应≥12章"
    for item in science.items:
        assert item.url.startswith("https://hpc.westlake.edu.cn/document/science/")
    cryo = next(s for s in content.sections if s.label == "冷冻电镜集群使用指南")
    assert len(cryo.items) >= 5
    # 成果库 API（校内网）不通时优雅降级：手册仍在、intro 提示原因
    if "学术论文" not in labels:
        assert "校内网" in (content.intro or "")


def test_baida_discovery_expands_columns() -> None:
    """栏目发现器：学生事务部从手工 2 栏扩到≥8 栏（奖学金/社团等同构栏目）。"""
    mod = _mod()
    content = mod.site_content("osa", limit=4)
    labels = [s.label for s in content.sections]
    assert len([l for l in labels if l not in ("通知公告", "学生活动")]) >= 6
    assert all(s.items for s in content.sections), "发现器只收录有条目的栏目"
    assert len(content.sections) <= 12, "单站栏目上限 12"


def test_ore_discovery_from_empty_cols() -> None:
    """科技合作部（原无手工栏目）：纯靠首页发现器也要出内容栏目。"""
    mod = _mod()
    content = mod.site_content("ore", limit=4)
    assert content.sections, "发现器应给 ore 补出栏目"
    assert sum(len(s.items) for s in content.sections) >= 10


def test_item_urls_absolute_no_double_slash() -> None:
    """条目 URL 必须是可用绝对地址（回归 2026-10-25 双斜杠坏链）。"""
    mod = _mod()
    content = mod.site_content("brcf", limit=4)
    urls = [i.url for s in content.sections for i in s.items]
    assert urls, "应有条目"
    for u in urls:
        assert u.startswith("https://"), u
        assert "//westlake.edu.cn/" not in u, f"双斜杠坏链: {u}"
        assert "404" not in u


def test_site_detail_extractor() -> None:
    """详情深挖：真实条目页 -> 标题/摘要/附件；白名单拒绝外域。"""
    mod = _mod()
    content = mod.site_content("osa", limit=4)
    item = next(i for s in content.sections for i in s.items)
    d = mod.site_detail(item.url)
    assert "404" not in d["title"], f"详情页应可访问: {item.url}"
    assert len(d["excerpt"]) >= 30, "应有正文摘要"
    assert isinstance(d["attachments"], list)
    # HPC 手册章节（mkdocs）也走同一提取器
    hpc = mod.site_detail("https://hpc.westlake.edu.cn/document/science/login/login.html")
    assert hpc["title"] and len(hpc["excerpt"]) >= 30
    with pytest.raises(Exception):
        mod.site_detail("https://example.com/not-allowed.htm")


def test_vpn_status_shape() -> None:
    """VPN 会话层：未登录时 status 返回 20026 语义（不触登录流程）。"""
    vpn = importlib.import_module("westlake_survival.vpn")
    st = vpn.status()
    assert set(st) >= {"logged_in", "code", "message"}
    assert st["logged_in"] is False


def test_webui_sites_page() -> None:
    """/sites 页四件套齐：stats、锚点、折叠块、至少 40 条条目上页面。

    复用常驻 webui（127.0.0.1:2018；开发服务器的直连验证路径）。
    """
    import urllib.request

    try:
        html = urllib.request.urlopen("http://127.0.0.1:2018/sites", timeout=120).read().decode("utf-8")
    except Exception:
        pytest.skip("本地 webui 未运行（先 westlake webui serve --port 2018）")
    for marker in ("全校站点", "已接入站点", "anchor-nav", "details class=\"fold\"",
                   "生物医学实验技术中心", "答辩公告"):
        assert marker in html, marker
    assert html.count("<tr>") >= 40, "条目行数应≥40"
