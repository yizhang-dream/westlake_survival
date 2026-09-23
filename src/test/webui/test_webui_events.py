"""讲座活动页（/events）：200、渲染活动与新闻、数据源失败时降级。"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from westlake_survival.events import EventItem
from westlake_survival.news import NewsItem
from westlake_survival.webui import app as webui_app
from westlake_survival.webui import create_app


@pytest.fixture
def app_client(monkeypatch):
    monkeypatch.setattr(
        webui_app,
        "_events_data",
        lambda days=30, limit=8: [
            EventItem(
                title="西湖理学讲坛| 程金光",
                date=datetime(2026, 9, 23, 14, 0),
                event_type="名家讲座",
                venue="云谷校区E10-211",
                url="https://www.westlake.edu.cn/a.html",
            )
        ],
    )
    monkeypatch.setattr(
        webui_app,
        "_news_data",
        lambda limit=6: [
            NewsItem(
                title="本校“最大气”的两位老师！",
                category="人物",
                date=datetime(2026, 9, 22, 11, 24),
                url="https://www.westlake.edu.cn/n.html",
            )
        ],
    )
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_events_page_ok(app_client):
    resp = app_client.get("/events")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "讲座活动" in body
    assert "西湖理学讲坛| 程金光" in body
    assert "云谷校区E10-211" in body
    assert "2026-09-23 14:00" in body
    assert "本校“最大气”的两位老师！" in body
    assert "2026-09-22" in body


def test_events_page_200_when_sources_fail(monkeypatch):
    """两个数据源都抛异常时页面仍 200，区块隐藏并提示降级。"""
    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(webui_app, "_events_data", boom)
    monkeypatch.setattr(webui_app, "_news_data", boom)
    app = create_app()
    app.config.update(TESTING=True)
    resp = app.test_client().get("/events")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "活动预告暂不可用" in body
    assert "西湖新闻暂不可用" in body


def test_events_page_200_when_sources_empty(monkeypatch):
    """数据源返回空列表时显示空态而非报错。"""
    monkeypatch.setattr(webui_app, "_events_data", lambda days=30, limit=8: [])
    monkeypatch.setattr(webui_app, "_news_data", lambda limit=6: [])
    app = create_app()
    app.config.update(TESTING=True)
    resp = app.test_client().get("/events")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "暂无活动预告" in body
    assert "暂无新闻" in body