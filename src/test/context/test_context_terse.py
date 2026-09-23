"""TERSE 档：纯本地快算（日期 / 星期 / 学期 / 周次），不触发任何 I/O。"""

from __future__ import annotations

import importlib
from datetime import datetime

import pytest

from westlake_survival import calendar as calendar_module
from westlake_survival.calendar import AcademicCalendar
from westlake_survival.context import CHINA_TZ, Context, Level, snapshot


@pytest.fixture
def offline_calendar(monkeypatch):
    """把校历加载固定到内置 fallback，杜绝网络依赖。"""
    monkeypatch.setattr(
        calendar_module.AcademicCalendar,
        "load",
        classmethod(lambda cls, refresh=False: cls.from_fallback()),
    )
    return AcademicCalendar.from_fallback()


def test_terse_fields(offline_calendar) -> None:
    now = datetime(2026, 9, 22, 8, 30, tzinfo=CHINA_TZ)
    ctx = Context(level=Level.TERSE, now=now)

    assert ctx.date.isoformat() == "2026-09-22"
    assert ctx.weekday_cn == "周二"
    assert ctx.semester_name == "2026年秋季"
    assert ctx.week_number == 4


def test_terse_skips_io(offline_calendar, monkeypatch) -> None:
    """TERSE 档不触碰 transit / canvas / 天气 / AQI。"""
    def boom(*args, **kwargs):  # pragma: no cover - 不应被调用
        raise AssertionError("TERSE 档不应触发 I/O")

    from westlake_survival import canvas, transit

    snapshot_module = importlib.import_module("westlake_survival.context.snapshot")
    monkeypatch.setattr(transit, "transit", boom)
    monkeypatch.setattr(canvas, "upcoming_deadlines", boom)
    monkeypatch.setattr(snapshot_module, "fetch_weather", boom)
    monkeypatch.setattr(snapshot_module, "fetch_aqi", boom)

    ctx = snapshot(Level.TERSE, now=datetime(2026, 9, 22, 8, 30, tzinfo=CHINA_TZ))
    assert ctx.next_event is None
    assert ctx.next_shuttles is None
    assert ctx.weather is None
    assert ctx.aqi is None
    assert ctx.next_deadlines is None


def test_terse_header_in_str(offline_calendar) -> None:
    ctx = snapshot(Level.TERSE, now=datetime(2026, 9, 22, 8, 30, tzinfo=CHINA_TZ))
    text = ctx.to_str()
    assert "2026-09-22" in text
    assert "周二" in text
    assert "2026年秋季" in text
    assert "第4周" in text
    # TERSE 档无网络数据，各节显示"（暂无）"。
    assert text.count("（暂无）") >= 4


def test_out_of_semester_is_none(offline_calendar) -> None:
    """假期（无学期覆盖）时学期与周次为 None，但不抛异常。"""
    ctx = snapshot(Level.TERSE, now=datetime(2026, 7, 30, 12, 0, tzinfo=CHINA_TZ))
    assert ctx.semester_name is None
    assert ctx.week_number is None
    assert ctx.to_str().startswith("# 西湖大学")


def test_now_defaults_to_china_tz() -> None:
    ctx = Context(level=Level.TERSE)
    assert ctx.now.tzinfo is not None
    assert isinstance(ctx.now, datetime)


def test_naive_now_is_localized(offline_calendar) -> None:
    ctx = Context(level=Level.TERSE, now=datetime(2026, 9, 22, 8, 30))
    assert ctx.now.tzinfo is not None
    assert ctx.week_number == 4