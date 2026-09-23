"""联网测试（默认排除，需外网）。运行：``pytest -m live src/test/context``。"""

from __future__ import annotations

import pytest

from westlake_survival.context import fetch_aqi, fetch_weather


@pytest.mark.live
def test_live_weather() -> None:
    weather = fetch_weather()
    assert weather is not None, "天气接口不可达"
    assert weather["temperature"] is not None
    assert weather["text"] not in (None, "未知")
    assert len(weather["daily"]) >= 1
    assert weather["daily"][0]["tmax"] is not None


@pytest.mark.live
def test_live_aqi() -> None:
    aqi = fetch_aqi()
    assert aqi is not None, "空气质量接口不可达"
    assert aqi["us_aqi"] is not None
    assert aqi["grade"] != "未知"
    assert aqi["pm2_5"] is not None