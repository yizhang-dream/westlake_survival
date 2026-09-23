"""iCalendar 下载与 JSON API：Content-Type / 503 / JSON 可序列化。"""

from __future__ import annotations

import json

import pytest

from westlake_survival.exceptions import AuthError
from westlake_survival.webui import app as webui_app
from westlake_survival.webui import create_app


def _make_app(monkeypatch, **seams):
    defaults = {
        "_context_data": lambda level="normal": None,
        "_transit_data": lambda: None,
        "_calendar_data": lambda: None,
        "_schedule_sessions": lambda: None,
        "_shuttle_ical": lambda: None,
        "_schedule_ical": lambda sessions: None,
    }
    defaults.update(seams)
    for name, value in defaults.items():
        monkeypatch.setattr(webui_app, name, value)
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


# ── /ical/shuttle ─────────────────────────────────────────────────────────

def test_ical_shuttle_headers(monkeypatch):
    """/ical/shuttle 返回 text/calendar 且正文含 BEGIN:VCALENDAR。"""
    ics = "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "BEGIN:VEVENT",
            "SUMMARY:校巴 云谷始发 07:30",
            "END:VEVENT",
            "END:VCALENDAR",
        ]
    ) + "\r\n"
    client = _make_app(monkeypatch, _shuttle_ical=lambda: ics)
    resp = client.get("/ical/shuttle")
    assert resp.status_code == 200
    assert resp.headers["Content-Type"].startswith("text/calendar")
    assert "charset=utf-8" in resp.headers["Content-Type"].lower()
    assert "attachment" in resp.headers["Content-Disposition"]
    assert ".ics" in resp.headers["Content-Disposition"]
    body = resp.get_data(as_text=True)
    assert "BEGIN:VCALENDAR" in body
    assert "END:VCALENDAR" in body
    assert "BEGIN:VEVENT" in body


def test_ical_shuttle_503_when_module_missing(monkeypatch):
    """transit 模块不可用时 503 + 提示页。"""
    client = _make_app(monkeypatch)
    resp = client.get("/ical/shuttle")
    assert resp.status_code == 503
    assert "不可用" in resp.get_data(as_text=True)


# ── /ical/schedule ────────────────────────────────────────────────────────

def test_ical_schedule_503_without_credentials(monkeypatch):
    """无凭据（get_schedule 抛 AuthError）时 503 + 中文提示。"""
    def auth_fail():
        raise AuthError("未登录")

    client = _make_app(monkeypatch, _schedule_sessions=auth_fail)
    resp = client.get("/ical/schedule")
    assert resp.status_code == 503
    body = resp.get_data(as_text=True)
    assert "凭据" in body


def test_ical_schedule_ok_with_sessions(monkeypatch):
    """有 sessions 时返回 text/calendar 下载。"""
    from datetime import date, time

    from westlake_survival.ical import courses_to_ical
    from westlake_survival.sis import ClassSession

    session = ClassSession(
        title="机器学习",
        course_code="CS301",
        room="A101",
        weekday=1,
        start_time=time(8, 0),
        end_time=time(9, 30),
        date_start=date(2026, 9, 1),
        date_end=date(2026, 12, 31),
        weeks=(1, 2, 3),
    )
    client = _make_app(
        monkeypatch,
        _schedule_sessions=lambda: [session],
        _schedule_ical=courses_to_ical,
    )
    resp = client.get("/ical/schedule")
    assert resp.status_code == 200
    assert resp.headers["Content-Type"].startswith("text/calendar")
    assert "BEGIN:VCALENDAR" in resp.get_data(as_text=True)


# ── JSON API ──────────────────────────────────────────────────────────────

def test_api_context_json_dumpable(monkeypatch, fixed_context):
    client = _make_app(monkeypatch, _context_data=lambda level="normal": dict(fixed_context))
    resp = client.get("/api/context")
    assert resp.status_code == 200
    assert resp.headers["Content-Type"].startswith("application/json")
    # 能被 json.dumps 且内容非空。
    payload = resp.get_json()
    assert payload["week_number"] == 12
    assert json.dumps(payload, ensure_ascii=False)


def test_api_context_handles_none(monkeypatch):
    client = _make_app(monkeypatch)
    resp = client.get("/api/context")
    assert resp.status_code == 200
    assert resp.get_json() is None


def test_api_shuttle_503_without_data(monkeypatch):
    client = _make_app(monkeypatch)
    resp = client.get("/api/shuttle")
    assert resp.status_code == 503
    assert "error" in resp.get_json()
