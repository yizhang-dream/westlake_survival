"""真实网络测试：需要能访问官网（默认被 ``-m 'not live'`` 排除）。

运行：``pytest src/test/campus -q -m live``
"""

from __future__ import annotations

import pytest

from westlake_survival.campus import SHUTTLE_LIVE_URL, dining, housing, load


@pytest.mark.live
def test_live_campus_page() -> None:
    """真抓「餐饮住宿」页面：食堂 ≥5 家、住宿 ≥1 条，且班车外链可见。"""
    data = load(refresh=True)

    assert len(data.dining["食堂"]) >= 5, f"食堂过少：{[s.name for s in data.dining['食堂']]}"
    assert len(data.dining["咖啡轻食"]) >= 1
    assert len(data.housing) >= 1

    # 第一条食堂的营业时间已按 <br/> 拆成多行
    first = data.dining["食堂"][0]
    assert first.name
    assert first.hours
    assert all("<" not in line for line in first.hours)

    # 住宿带服务信息
    assert data.housing[0].services

    # notice 里的实时班车外链
    assert SHUTTLE_LIVE_URL in data.shuttle_notice()

    # 查询 API 走单例，返回同样规模的数据
    assert len(dining()) == len(data.dining["食堂"]) + len(data.dining["咖啡轻食"])
    assert len(housing()) == len(data.housing)