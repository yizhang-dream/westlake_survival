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
