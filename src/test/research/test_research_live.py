"""真实网络测试：需要能访问官网（默认被 ``-m 'not live'`` 排除）。

运行：``pytest src/test/research -q -m live``
"""

from __future__ import annotations

from datetime import datetime

import pytest

from westlake_survival.research import fetch_detail, latest


@pytest.mark.live
def test_live_list_has_many_items() -> None:
    """真抓列表页：researchList 各分组条目展平后实测 ≥ 20 条。"""
    items = latest()

    assert len(items) >= 20
    first = items[0]
    assert first.title
    assert first.category
    assert first.url.startswith("http")
    assert first.summary == first.title
    assert first.title != first.category


@pytest.mark.live
def test_live_category_filter_and_limit() -> None:
    health = latest(category="生命健康 / Good Health & Wellbeing", limit=3)

    assert len(health) <= 3
    assert all(item.category == "生命健康 / Good Health & Wellbeing" for item in health)


@pytest.mark.live
def test_live_detail() -> None:
    """真抓一篇详情：标题、日期、正文非空。"""
    target = next(item for item in latest() if item.url.endswith(".html"))
    detail = fetch_detail(target.url)

    assert detail.title
    assert detail.url == target.url
    assert isinstance(detail.date, datetime)
    assert detail.content_html
