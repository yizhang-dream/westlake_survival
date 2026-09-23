"""真实网络测试：需要能访问官网（默认被 ``-m 'not live'`` 排除）。

运行：``pytest src/test/news -q -m live``
"""

from __future__ import annotations

from datetime import datetime

import pytest

from westlake_survival.news import fetch_detail, latest


@pytest.mark.live
def test_live_list_has_many_items() -> None:
    """真抓列表页：前端分页只是展示层，服务端返回全量数组（实测 > 500 条）。"""
    items = latest()

    assert len(items) >= 500
    first = items[0]
    assert first.title
    assert first.category
    assert first.url.startswith("http")
    assert isinstance(first.date, datetime)
    assert first.title != first.category


@pytest.mark.live
def test_live_category_filter_and_limit() -> None:
    people = latest(category="人物", limit=3)

    assert len(people) <= 3
    assert all(item.category == "人物" for item in people)


@pytest.mark.live
def test_live_detail() -> None:
    """真抓一篇详情：标题、日期、正文非空。"""
    first = latest(limit=1)[0]
    detail = fetch_detail(first.url)

    assert detail.title
    assert detail.url == first.url
    assert isinstance(detail.date, datetime)
    assert detail.content_html