"""webui 测试共享 fixture。

约定：
* 全部测试走 Flask ``test_client``，不依赖真实网络——render 层的取数接缝
  （``webui.app._context_data`` / ``_transit_data`` / ``_calendar_data`` /
  ``_schedule_sessions``）在用例里 monkeypatch 成固定数据。
* 因此本目录的测试在离线、无凭据时也能全绿。
"""

from __future__ import annotations

from datetime import date, datetime, time

import pytest

from westlake_survival.transit import Campus, DayKind, ShuttleTable, TransitData
from westlake_survival.webui import create_app, app as webui_app


# --------------------------------------------------------------------------- #
# 固定数据
# --------------------------------------------------------------------------- #
@pytest.fixture
def fixed_context() -> dict:
    """一份固定的 ``Context.to_dict()`` 形状快照（2026 秋，第 12 周）。"""
    return {
        "level": "verbose",
        "now": "2026-11-16T09:30:00+08:00",
        "date": "2026-11-16",
        "weekday_cn": "周一",
        "semester_name": "2026年秋季",
        "week_number": 12,
        "next_event": {
            "title": "期中考试周",
            "start": "2026-11-20",
            "end": "2026-11-24",
        },
        "next_shuttles": [
            {"time": "09:45", "campus": "云谷", "day_kind": "工作日"},
            {"time": "10:15", "campus": "云栖", "day_kind": "工作日"},
        ],
        "weather": {"temperature": 18.5, "text": "多云", "humidity": 60},
        "aqi": {"us_aqi": 42, "grade": "优"},
        "next_deadlines": [
            {"name": "Lab 4 报告", "due_at": "2026-11-18T23:59:00+08:00"},
        ],
    }


@pytest.fixture
def fixed_transit() -> TransitData:
    """一张极小的班车数据：云谷 / 云栖 各一张工作日表。"""
    return TransitData(
        tables=[
            ShuttleTable(
                campus=Campus.YUNGU,
                day_kind=DayKind.WEEKDAY,
                direction_note="始发云谷，往返 云谷 ↔ 云栖",
                morning=("07:30", "08:30"),
                noon=("12:30",),
                night=("21:00",),
            ),
            ShuttleTable(
                campus=Campus.YUNQI,
                day_kind=DayKind.WEEKDAY,
                direction_note="始发云栖，往返 云谷 ↔ 云栖",
                morning=("07:45",),
            ),
        ]
    )


@pytest.fixture
def fixed_calendar():
    """离线校历（内置兜底数据，不触发网络）。"""
    from westlake_survival.calendar import AcademicCalendar

    return AcademicCalendar.from_fallback()


@pytest.fixture
def client(monkeypatch):
    """test_client，默认把校历 / 班车接缝指向离线固定数据，context 指向空。"""
    monkeypatch.setattr(webui_app, "_context_data", lambda level="normal": None)
    monkeypatch.setattr(webui_app, "_calendar_data", lambda: None)
    monkeypatch.setattr(webui_app, "_transit_data", lambda: None)
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()
