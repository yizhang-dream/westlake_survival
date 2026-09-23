"""transit 联网测试（默认排除，需校园网）。"""

from __future__ import annotations

import pytest

from westlake_survival.transit import transit


@pytest.mark.live
def test_live_load() -> None:
    data = transit(refresh=True)
    assert len(data.tables) >= 6