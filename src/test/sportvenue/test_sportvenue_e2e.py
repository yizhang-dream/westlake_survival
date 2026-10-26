"""端到端探测：场馆系统（正元 sportvenue）登录链路与只读接口。

需校园网/VPN 与已配置的统一凭据；默认被 pyproject 的 ``-m 'not live'`` 排除。
2026-10-27 实测：签名、四步登录、场景/场地/逐日/我的预约四类接口全部可用；
游泳与球场每天仍是「表单规则未找到」（服务端未配表单，不是本机问题）。
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from westlake_survival import sportvenue

pytestmark = pytest.mark.live


def test_scenes_e2e() -> None:
    """真实登录后拿到场景清单，且含游泳。"""
    rows = sportvenue.scenes()
    assert len(rows) >= 10
    assert any("游泳" in item.name for item in rows)


def test_sites_and_days_e2e() -> None:
    """游泳场景的场地与逐日状态能查；不可约时必须给出服务端原因。"""
    scene = sportvenue.find_scene("游泳")
    rows = sportvenue.sites(scene)
    assert rows, "游泳场景当日应有场地（场次）"
    target = rows[0]
    statuses = sportvenue.days(
        target,
        start=date.today() + timedelta(days=1),
        end=date.today() + timedelta(days=3),
    )
    assert len(statuses) == 3
    for item in statuses:
        assert item.day
        if not item.bookable:
            assert item.reason, "不可约却没给原因，说明接口语义变了"


def test_my_reservations_e2e() -> None:
    """我的预约接口可读（空列表是合法结果）。"""
    assert isinstance(sportvenue.my_reservations(limit=5), list)


def test_unknown_scene_e2e() -> None:
    """未知场景给可读候选，而不是抛原始异常。"""
    with pytest.raises(Exception) as excinfo:
        sportvenue.find_scene("不存在的场景xyz")
    assert "没找到场景" in str(excinfo.value)
