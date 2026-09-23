"""班车页：200、含全部校区名与时刻、高亮下一班。"""

from __future__ import annotations

import pytest

from westlake_survival.transit import Campus, DayKind, ShuttleTable, TransitData
from westlake_survival.webui import app as webui_app
from westlake_survival.webui import create_app


@pytest.fixture
def client(monkeypatch, fixed_transit):
    monkeypatch.setattr(webui_app, "_transit_data", lambda: fixed_transit)
    monkeypatch.setattr(webui_app, "_context_data", lambda level="normal": None)
    monkeypatch.setattr(webui_app, "_calendar_data", lambda: None)
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_shuttle_ok_contains_campuses(client):
    resp = client.get("/shuttle")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # 每个校区名都出现。
    for campus in (Campus.YUNGU, Campus.YUNQI, Campus.TONGJIANHU):
        assert campus.value in body
    # 时刻与日别分组。
    assert "07:30" in body
    assert "工作日" in body and "周末" in body
    # 高亮集合中的时刻带 chip 样式（说明命中 next_departures）。
    assert "chip" in body


def test_shuttle_departed_times_marked(client):
    """「现在出发」区块至少有一个时刻渲染。"""
    body = client.get("/shuttle").get_data(as_text=True)
    assert "现在出发" in body


def test_shuttle_200_when_data_missing(monkeypatch):
    monkeypatch.setattr(webui_app, "_transit_data", lambda: None)
    app = create_app()
    app.config.update(TESTING=True)
    resp = app.test_client().get("/shuttle")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "暂无班车数据" in body


def test_shuttle_handles_empty_table(monkeypatch):
    """某校区只有空表时该区块显示占位而非报错。"""
    data = TransitData(
        tables=[
            ShuttleTable(campus=Campus.YUNGU, day_kind=DayKind.WEEKDAY),
        ]
    )
    monkeypatch.setattr(webui_app, "_transit_data", lambda: data)
    app = create_app()
    app.config.update(TESTING=True)
    resp = app.test_client().get("/shuttle")
    assert resp.status_code == 200
    assert "无时刻表数据" in resp.get_data(as_text=True)


def test_api_shuttle_json(monkeypatch, fixed_transit):
    monkeypatch.setattr(webui_app, "_transit_data", lambda: fixed_transit)
    app = create_app()
    app.config.update(TESTING=True)
    resp = app.test_client().get("/api/shuttle")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert isinstance(payload, list)
    assert payload[0]["campus"] == "云谷"
    assert payload[0]["morning"] == ["07:30", "08:30"]
