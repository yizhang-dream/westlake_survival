"""真实网络探测：成绩 / 考试页（``@pytest.mark.live``，默认被 ``-m 'not live'`` 排除）。

需要校园网 / VPN 与有效凭据（登录复用 :class:`SISAuth` 单例，登录 POST ≤3 次）。
只读：GET 组件页并断言解析结果条数，不改动任何远端状态。

运行：``pytest src/test/sis -q -m live``
"""

from __future__ import annotations

import pytest

from westlake_survival.sis.exams import exam_schedule
from westlake_survival.sis.grades import grades

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def _probe():
    """预热一次：确认 SIS 可达且有凭据；不可达则整体 skip。"""
    try:
        from westlake_survival.sso import SISAuth

        SISAuth().ensure()
    except Exception as exc:  # noqa: BLE001 - 需要校园网/凭据，任何失败都 skip
        pytest.skip(f"无法登录 SIS（需校园网/VPN 与有效凭据）：{exc}")
    return True


def test_live_grades_at_least_30_rows(_probe):
    """真页成绩 ≥30 行（实测 38 行），首行含课程代码与学期。"""
    items = grades()
    assert len(items) >= 30, len(items)
    assert items[0].course_code
    assert items[0].term
    assert any(g.grade for g in items)  # 至少一条已出分


def test_live_exam_schedule_parsable(_probe):
    """真页考试安排可解析（当前学期 N 门课；排期列可能为空）。"""
    items = exam_schedule()
    assert items, "考试页解析为空，页面结构可能已变化"
    for slot in items:
        assert slot.course_code or slot.course_title
