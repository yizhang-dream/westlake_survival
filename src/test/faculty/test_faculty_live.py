"""真实网络测试：需要校外可直连（默认被 ``-m 'not live'`` 排除）。

运行：``pytest src/test/faculty -q -m live``
"""

from __future__ import annotations

import pytest

from westlake_survival.faculty import fetch_detail, members


@pytest.mark.live
def test_live_members_has_full_roster() -> None:
    people = members(limit=None)
    assert len(people) >= 250, f"名录只有 {len(people)} 人，页面结构可能已变化"
    first = people[0]
    assert first.name
    assert first.school
    assert first.url.startswith("https://www.westlake.edu.cn/")
    # 至少有一位能拆出实验室/方向
    assert any(m.lab for m in people)


@pytest.mark.live
def test_live_members_aggregates_all_sources() -> None:
    """多源聚合后总数应 >= 330，且四个源都有贡献。"""
    people = members(limit=None)
    assert len(people) >= 330, f"聚合名录只有 {len(people)} 人，可能某源已失效"
    sources = {m.source for m in people}
    assert sources == {"main", "science", "sls", "teaching"}
    # 理学院源本身条目数（含与主站重叠者）应 >= 120
    science = members(source="science", limit=None)
    assert len(science) >= 120, f"理学院源只有 {len(science)} 人"
    assert any(m.work_type for m in science)


@pytest.mark.live
def test_live_detail_of_first_member() -> None:
    people = members(limit=1)
    assert people, "名录为空"
    detail = fetch_detail(people[0].url)
    assert detail.name
    assert detail.biography_html or detail.research_html