"""西湖新闻页（/news）：200、渲染列表与分类、异常降级、空态。"""

from __future__ import annotations

from datetime import datetime

import pytest

from westlake_survival.news import NewsItem
from westlake_survival.webui import app as webui_app
from westlake_survival.webui import create_app


def _client(monkeypatch, seam):
    monkeypatch.setattr(webui_app, "_news_list", seam)
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


@pytest.fixture
def app_client(monkeypatch):
    monkeypatch.setattr(
        webui_app,
        "_news_list",
        lambda limit=30, category=None: [
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


def test_news_page_ok(app_client):
    resp = app_client.get("/news?category=人物")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "西湖新闻" in body
    assert "本校“最大气”的两位老师！" in body
    assert "2026-09-22" in body
    assert "人物" in body
    assert "https://www.westlake.edu.cn/n.html" in body


def test_news_page_200_when_source_fails(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    client = _client(monkeypatch, boom)
    resp = client.get("/news")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "西湖新闻暂时不可用" in body
    assert "西湖新闻暂不可用" in body


def test_news_page_200_when_empty(monkeypatch):
    client = _client(monkeypatch, lambda limit=30, category=None: [])
    resp = client.get("/news")
    assert resp.status_code == 200
    assert "暂无新闻" in resp.get_data(as_text=True)


def test_news_page_passes_category_filter(monkeypatch):
    """分类参数透传到取数接缝。"""
    seen: dict = {}

    def seam(limit=30, category=None):
        seen["limit"] = limit
        seen["category"] = category
        return []

    client = _client(monkeypatch, seam)
    resp = client.get("/news?category=学术")
    assert resp.status_code == 200
    assert seen == {"limit": 30, "category": "学术"}
