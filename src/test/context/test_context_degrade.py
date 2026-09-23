"""优雅降级：各 fetch 抛异常时字段为 None，to_dict / to_str 不抛。"""

from __future__ import annotations

import importlib
import json
import logging
from datetime import datetime

import pytest

from westlake_survival import calendar as calendar_module
from westlake_survival.context import CHINA_TZ, Level, snapshot

#: 显式取子模块（``from westlake_survival.context import snapshot`` 拿到的是函数）。
snapshot_module = importlib.import_module("westlake_survival.context.snapshot")


@pytest.fixture
def all_io_broken(monkeypatch):
    """让所有外部依赖都抛异常。"""
    def boom(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(
        calendar_module.AcademicCalendar,
        "load",
        classmethod(lambda cls, refresh=False: boom()),
    )
    monkeypatch.setattr(snapshot_module, "fetch_weather", boom)
    monkeypatch.setattr(snapshot_module, "fetch_aqi", boom)

    from westlake_survival import canvas, transit

    monkeypatch.setattr(transit, "transit", boom)
    monkeypatch.setattr(canvas, "upcoming_deadlines", boom)


def test_verbose_fields_degrade_to_none(all_io_broken, caplog) -> None:
    now = datetime(2026, 9, 22, 8, 30, tzinfo=CHINA_TZ)
    with caplog.at_level(logging.WARNING):
        ctx = snapshot(Level.VERBOSE, now=now)

    assert ctx.semester_name is None
    assert ctx.week_number is None
    assert ctx.next_event is None
    assert ctx.next_shuttles is None
    assert ctx.weather is None
    assert ctx.aqi is None
    assert ctx.next_deadlines is None
    # 纯本地字段仍可用。
    assert ctx.date.isoformat() == "2026-09-22"
    assert ctx.weekday_cn == "周二"


def test_to_dict_never_raises_when_broken(all_io_broken) -> None:
    ctx = snapshot(Level.VERBOSE, now=datetime(2026, 9, 22, 8, 30, tzinfo=CHINA_TZ))
    data = ctx.to_dict()  # 不应抛
    json.dumps(data, ensure_ascii=False)  # 必须可序列化
    assert data["weather"] is None
    assert data["aqi"] is None
    assert data["next_deadlines"] is None
    assert data["next_event"] is None
    assert data["next_shuttles"] is None


def test_to_str_shows_placeholder_when_broken(all_io_broken) -> None:
    ctx = snapshot(Level.VERBOSE, now=datetime(2026, 9, 22, 8, 30, tzinfo=CHINA_TZ))
    text = ctx.to_str()
    assert "（暂无）" in text
    assert "## 🌤️ 天气" in text
    assert "## 📌 最近截止" in text


def test_warning_logged_on_failure(all_io_broken, caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="westlake_survival.context"):
        ctx = snapshot(Level.VERBOSE, now=datetime(2026, 9, 22, 8, 30, tzinfo=CHINA_TZ))
        ctx.weather
        ctx.aqi
    # fetch 被直接替换成抛异常，故 warning 来自 _get 兜底（含字段名）。
    assert any("weather" in r.message or "天气" in r.message for r in caplog.records)
    assert any("aqi" in r.message or "空气" in r.message for r in caplog.records)


def test_canvas_auth_error_degrades(monkeypatch) -> None:
    """无 token（AuthError）时 next_deadlines 为 None，不抛。"""
    from westlake_survival import canvas
    from westlake_survival.exceptions import AuthError

    def no_token(limit=10):
        raise AuthError("no token")

    monkeypatch.setattr(canvas, "upcoming_deadlines", no_token)
    monkeypatch.setattr(snapshot_module, "fetch_weather", lambda *a, **k: None)
    monkeypatch.setattr(snapshot_module, "fetch_aqi", lambda *a, **k: None)

    ctx = snapshot(Level.VERBOSE, now=datetime(2026, 9, 22, 8, 30, tzinfo=CHINA_TZ))
    assert ctx.next_deadlines is None
    assert ctx.to_dict()["next_deadlines"] is None


# --------------------------------------------------------------------------- #
# 结构违约：下游返回契约外结构时 to_dict / to_str 仍不抛
# --------------------------------------------------------------------------- #
def _patch_transit(monkeypatch, fake_next):
    """把 transit().next_departures 替换为返回 *fake_next* 的假实现。"""

    class _FakeTransit:
        def next_departures(self, now=None, limit=3):
            return fake_next

    from westlake_survival import transit

    monkeypatch.setattr(transit, "transit", lambda *a, **k: _FakeTransit())
    # 校历固定到内置 fallback，避免网络。
    monkeypatch.setattr(
        calendar_module.AcademicCalendar,
        "load",
        classmethod(lambda cls, refresh=False: cls.from_fallback()),
    )
    monkeypatch.setattr(snapshot_module, "fetch_weather", lambda *a, **k: None)
    monkeypatch.setattr(snapshot_module, "fetch_aqi", lambda *a, **k: None)


def test_to_dict_survives_malformed_shuttle_triple(monkeypatch) -> None:
    """next_departures 返回三元组（契约外）→ to_dict 不抛，违约项降级。"""
    _patch_transit(monkeypatch, [("a", "b", "c")])
    ctx = snapshot(Level.NORMAL, now=datetime(2026, 9, 22, 8, 30, tzinfo=CHINA_TZ))
    data = ctx.to_dict()  # 不应抛
    json.dumps(data, ensure_ascii=False)
    assert data["next_shuttles"] == []
    # to_str 同样不抛，且显示占位。
    assert "（暂无）" in ctx.to_str()


def test_to_dict_survives_malformed_shuttle_none_element(monkeypatch) -> None:
    """列表含 None 元素 → 违约项跳过，其余正常项保留。"""
    from westlake_survival.transit import Campus, DayKind, ShuttleTable

    good_table = ShuttleTable(campus=Campus.YUNGU, day_kind=DayKind.WEEKDAY)
    _patch_transit(monkeypatch, [None, (good_table, "08:00")])
    ctx = snapshot(Level.NORMAL, now=datetime(2026, 9, 22, 8, 30, tzinfo=CHINA_TZ))
    data = ctx.to_dict()  # 不应抛
    json.dumps(data, ensure_ascii=False)
    assert data["next_shuttles"] == [
        {"time": "08:00", "campus": Campus.YUNGU.value, "day_kind": DayKind.WEEKDAY.value}
    ]
    assert "08:00" in ctx.to_str()


def test_to_dict_survives_non_iterable_shuttles(monkeypatch) -> None:
    """next_departures 返回不可迭代对象 → shuttles 字段整体降级为 None。"""
    _patch_transit(monkeypatch, 42)
    ctx = snapshot(Level.NORMAL, now=datetime(2026, 9, 22, 8, 30, tzinfo=CHINA_TZ))
    data = ctx.to_dict()  # 不应抛
    json.dumps(data, ensure_ascii=False)
    assert data["next_shuttles"] is None
    assert "（暂无）" in ctx.to_str()