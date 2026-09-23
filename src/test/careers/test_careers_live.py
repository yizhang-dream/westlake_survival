"""真实网络测试：需要能访问官网（默认被 ``-m 'not live'`` 排除）。

运行：``pytest src/test/careers -q -m live``
"""

from __future__ import annotations

import pytest

from westlake_survival.careers import fetch_detail, positions


@pytest.mark.live
def test_live_positions_returns_full_list() -> None:
    """真抓招聘主页：全量岗位应达数百条，字段齐全。"""
    items = positions(refresh=True)

    assert len(items) >= 400, f"仅取到 {len(items)} 条岗位"
    assert all(p.title for p in items)
    assert all(p.url.startswith("http") for p in items)
    assert all(p.category for p in items)

    # 类别去重后应覆盖多个类别
    categories = {p.category for p in items}
    assert len(categories) >= 3

    # 过滤接口与全量一致
    postdoc = positions(category="博士后")
    assert postdoc
    assert {p.category for p in postdoc} == {"博士后"}
    assert len(positions(limit=5)) == 5


@pytest.mark.live
def test_live_detail_page() -> None:
    """真抓一条官网详情：标题/正文非空。"""
    first = positions(limit=1)[0]
    detail = fetch_detail(first.url)

    assert detail.title
    assert detail.content_html
    assert detail.url == first.url