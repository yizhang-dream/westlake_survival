"""真实网络测试：需要能访问官网（默认被 ``-m 'not live'`` 排除）。

运行：``pytest src/test/search -q -m live``
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from westlake_survival.search import search


@pytest.mark.live
def test_live_search_xihu() -> None:
    """真搜「西湖」：应命中大量结果，且高亮标签被剥掉。"""
    result = search("西湖")

    assert result.total > 0
    assert result.page == 1
    assert result.page_count >= 1
    assert len(result.hits) > 0

    first = result.hits[0]
    assert first.clean_title
    assert "<font" not in first.clean_title
    assert first.url.startswith("http")
    assert first.date is not None
    # 官网会预告未来日程，日期允许略晚于今天。
    assert first.date <= date.today() + timedelta(days=30)

    # 翻到第 2 页，内容应与第 1 页不同。
    page2 = search("西湖", page=2)
    assert page2.page == 2
    assert page2.hits[0].url != first.url