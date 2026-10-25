"""全量子站挖掘的解析层端到端测试（离线 HTML 片段）。

覆盖：栏目筛选（同域/跳过登录检索）、条目抽取（站点列表抽取器）、
编码识别（requests 把无 charset 页面猜成 ISO-8859-1 时的纠正）。

运行：``pytest src/test/hosts/test_hosts_e2e.py -q``
"""

from __future__ import annotations

from westlake_survival import hosts


class _Response:
    def __init__(self, raw: bytes, encoding: str = "ISO-8859-1") -> None:
        self.content = raw
        self.encoding = encoding


def test_decode_prefers_utf8_over_latin1_guess() -> None:
    raw = "<title>西湖大学理学院</title>".encode("utf-8")
    text = hosts._decode(_Response(raw, "ISO-8859-1"))
    assert "西湖大学理学院" in text


def test_nav_columns_filters_same_host_and_noise() -> None:
    base = "https://career.westlake.edu.cn/"
    html = """
    <a href="/news/">新闻动态</a>
    <a href="/jobs/list.htm">招聘信息</a>
    <a href="/login">登录</a>
    <a href="https://other.example.com/x">外部</a>
    <a href="/news/">新闻动态</a>
    <a href="javascript:void(0)">菜单</a>
    """
    columns = hosts._nav_columns(html, base, limit=8)
    paths = [url for _, url in columns]
    assert len(paths) == len(set(paths)), "同路径应去重"
    assert any("/news" in url for url in paths)
    assert any("jobs" in url for url in paths)
    assert not any("login" in url for url in paths)
    assert not any("other.example.com" in url for url in paths)


def test_items_extracts_list_titles() -> None:
    base = "https://its.westlake.edu.cn/news/"
    html = """
    <ul>
      <li><a href="t20261020_1.html">西湖大学理论科学研究院举办秋季论坛</a><span>2026-10-20</span></li>
      <li><a href="t20261018_2.html">理论院两位学者获青年科学基金资助</a><span>2026-10-18</span></li>
    </ul>
    """
    items = hosts._items(html, base, limit=5)
    titles = [item["title"] for item in items]
    assert any("秋季论坛" in title for title in titles)
    assert any("青年科学基金" in title for title in titles)
