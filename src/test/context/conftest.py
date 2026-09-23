"""context 模块测试共享 fixture。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from westlake_survival import calendar as calendar_module
from westlake_survival import transit as transit_module
from westlake_survival.calendar import AcademicCalendar
from westlake_survival.transit.schedule import FALLBACK_TABLES, TransitData

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def offline_defaults(monkeypatch):
    """默认切断真实网络：校历走 fallback、班车走内置表。

    需要联网行为的测试可自行覆盖这些 patch。
    """
    monkeypatch.setattr(
        calendar_module.AcademicCalendar,
        "load",
        classmethod(lambda cls, refresh=False: cls.from_fallback()),
    )
    monkeypatch.setattr(
        transit_module,
        "transit",
        lambda refresh=False: TransitData(tables=list(FALLBACK_TABLES)),
    )


@pytest.fixture
def weather_payload() -> dict:
    """实测 Open-Meteo 天气响应（2026-09-22）。"""
    return json.loads((FIXTURES / "weather.json").read_text(encoding="utf-8"))


@pytest.fixture
def aqi_payload() -> dict:
    """实测 Open-Meteo 空气质量响应（2026-09-22）。"""
    return json.loads((FIXTURES / "aqi.json").read_text(encoding="utf-8"))