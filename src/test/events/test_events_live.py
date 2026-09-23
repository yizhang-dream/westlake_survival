"""真实网络测试：需要能访问官网（默认被 ``-m 'not live'`` 排除）。

运行：``pytest src/test/events -q -m live``
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from westlake_survival.events import EventDetail, fetch_detail, load_events, upcoming


@pytest.mark.live
def test_live_list_has_full_history_and_upcoming() -> None:
    """真列表页应返回 ≥1000 条（含历史），且未来 14 天窗口非空。"""
    items = load_events()
    assert len(items) >= 1000
    assert all(item.title for item in items)

    soon = upcoming(14)
    assert soon, "未来 14 天应有活动预告"
    today = date.today()
    for item in soon:
        assert today <= item.date.date() <= today + timedelta(days=14)
    dates = [item.date for item in soon]
    assert dates == sorted(dates)


@pytest.mark.live
def test_live_detail_parses() -> None:
    """取一条真实详情页，应能解析出标题与正文。"""
    soon = upcoming(14)
    if not soon:
        pytest.skip("未来 14 天无活动，跳过详情页测试")
    detail = fetch_detail(soon[0].url)
    assert isinstance(detail, EventDetail)
    assert detail.title
    assert detail.url == soon[0].url