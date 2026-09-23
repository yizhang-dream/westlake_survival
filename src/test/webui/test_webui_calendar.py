"""校历页：200、当前学期事件、周次进度条；无学期时优雅降级。"""

from __future__ import annotations

import pytest

from westlake_survival.webui import app as webui_app
from westlake_survival.webui import create_app


@pytest.fixture
def client(monkeypatch, fixed_calendar):
    monkeypatch.setattr(webui_app, "_calendar_data", lambda: fixed_calendar)
    monkeypatch.setattr(webui_app, "_context_data", lambda level="normal": None)
    monkeypatch.setattr(webui_app, "_transit_data", lambda: None)
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_calendar_ok(client):
    resp = client.get("/calendar")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "本学期校历" in body
    assert "校历事件" in body


def test_calendar_has_semester_and_events(client, fixed_calendar):
    """固定校历里至少有一个学期，页面展示学期名与至少一条事件。"""
    assert fixed_calendar.semesters, "内置兜底校历应含学期"
    semester = fixed_calendar.semesters[0]
    body = client.get("/calendar").get_data(as_text=True)
    if fixed_calendar.current() is not None:
        assert fixed_calendar.current().name in body
    # 内置数据里必有事件条目。
    assert semester.events
    assert semester.events[0].title in body


def test_calendar_200_when_missing(monkeypatch):
    monkeypatch.setattr(webui_app, "_calendar_data", lambda: None)
    app = create_app()
    app.config.update(TESTING=True)
    resp = app.test_client().get("/calendar")
    assert resp.status_code == 200
    assert "没有正在进行的学期" in resp.get_data(as_text=True)


def test_calendar_progress_bar_when_in_semester(monkeypatch):
    """用一份人为构造的「当前学期」验证进度条渲染。"""
    from datetime import date, timedelta

    from westlake_survival.calendar import AcademicCalendar, CalendarEvent, Semester

    today = date.today()
    semester = Semester(
        name="测试学期",
        start=today - timedelta(weeks=4),
        end=today + timedelta(weeks=12),
        events=[
            CalendarEvent(title="测试假期", start=today + timedelta(days=3)),
        ],
    )
    cal = AcademicCalendar(semesters=[semester])
    monkeypatch.setattr(webui_app, "_calendar_data", lambda: cal)
    app = create_app()
    app.config.update(TESTING=True)
    body = app.test_client().get("/calendar").get_data(as_text=True)
    assert "测试学期" in body
    assert "progress" in body  # 进度条元素
    assert "测试假期" in body
    assert "天后" in body  # 倒计时
