"""真实网络测试：需要校园网（默认被 ``-m 'not live'`` 排除）。

运行：``pytest src/test/calendar -q -m live``
"""

from __future__ import annotations

import pytest

from westlake_survival.calendar import AcademicCalendar


@pytest.mark.live
def test_live_load_real_page() -> None:
    cal = AcademicCalendar.load(refresh=True)
    assert len(cal.semesters) >= 2

    fall = next((s for s in cal.semesters if "秋季" in s.name), None)
    assert fall is not None, f"未找到秋季学期：{[s.name for s in cal.semesters]}"
    assert len(fall.events) >= 15
    assert fall.start <= fall.end