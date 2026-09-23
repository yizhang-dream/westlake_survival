"""错误页与模板过滤器。"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from westlake_survival.webui import app as webui_app
from westlake_survival.webui import create_app
from westlake_survival.webui.app import days_until, fmt_date, weekday_cn


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(webui_app, "_context_data", lambda level="normal": None)
    monkeypatch.setattr(webui_app, "_transit_data", lambda: None)
    monkeypatch.setattr(webui_app, "_calendar_data", lambda: None)
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_404_uses_error_template(client):
    resp = client.get("/definitely-not-here")
    assert resp.status_code == 404
    body = resp.get_data(as_text=True)
    assert "404" in body
    assert "页面不存在" in body
    assert "返回仪表盘" in body


# ── 模板过滤器 ────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "value,expected",
    [
        (date(2026, 11, 16), "周一"),
        (date(2026, 11, 22), "周日"),
        (datetime(2026, 11, 16, 9, 30), "周一"),
        ("2026-11-16", "周一"),
        (0, "周一"),
        (6, "周日"),
    ],
)
def test_weekday_cn(value, expected):
    assert weekday_cn(value) == expected


def test_weekday_cn_none_and_unknown():
    assert weekday_cn(None) == ""
    assert weekday_cn("不是日期") == "不是日期"


@pytest.mark.parametrize(
    "value,expected",
    [
        (date(2026, 11, 16), "2026-11-16"),
        (datetime(2026, 11, 16, 9, 30), "2026-11-16"),
        ("2026/11/16", "2026-11-16"),
        ("2026-11-16", "2026-11-16"),
    ],
)
def test_fmt_date(value, expected):
    assert fmt_date(value) == expected


def test_fmt_date_none_and_garbage():
    assert fmt_date(None) == "—"
    assert fmt_date("无法解析") == "无法解析"


def test_days_until():
    base = date(2026, 11, 16)
    assert days_until(date(2026, 11, 20), today=base) == 4
    assert days_until(date(2026, 11, 16), today=base) == 0
    assert days_until(date(2026, 11, 10), today=base) == -6
    assert days_until("garbage", today=base) is None
    assert days_until(None, today=base) is None
