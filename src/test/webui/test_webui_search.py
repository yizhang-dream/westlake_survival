"""全站搜索页（/search）：200、渲染命中、异常降级、未搜索与空结果态。"""

from __future__ import annotations

from datetime import date

import pytest

from westlake_survival.search import SearchHit, SearchResult
from westlake_survival.webui import app as webui_app
from westlake_survival.webui import create_app


def _client(monkeypatch, seam):
    monkeypatch.setattr(webui_app, "_search_data", seam)
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


@pytest.fixture
def app_client(monkeypatch):
    monkeypatch.setattr(
        webui_app,
        "_search_data",
        lambda keyword: SearchResult(
            hits=[
                SearchHit(
                    title="<font color=>西湖</font>理学讲坛",
                    url="https://www.westlake.edu.cn/s.html",
                    date=date(2026, 9, 23),
                    desc="<font color=>量子</font>主题讲座",
                )
            ],
            page=1,
            page_count=1,
            total=42,
        ),
    )
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_search_page_ok(app_client):
    resp = app_client.get("/search?q=量子")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "全站搜索" in body
    # 命中的 <font> 高亮标签应被剥离后再渲染。
    assert "西湖理学讲坛" in body
    assert "<font" not in body
    assert "2026-09-23" in body
    assert "https://www.westlake.edu.cn/s.html" in body
    assert "42" in body


def test_search_page_200_when_source_fails(monkeypatch):
    def boom(keyword):
        raise RuntimeError("boom")

    client = _client(monkeypatch, boom)
    resp = client.get("/search?q=量子")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "搜索暂时不可用" in body
    assert "搜索暂不可用" in body


def test_search_page_200_when_empty(monkeypatch):
    client = _client(monkeypatch, lambda keyword: SearchResult(hits=[], total=0))
    resp = client.get("/search?q=不存在的东西")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "没有找到" in body


def test_search_page_without_keyword_does_not_call_source(monkeypatch):
    """空关键词时不发起请求，给出引导文案。"""

    def seam(keyword):  # pragma: no cover - 不应被调用
        raise AssertionError("空关键词不应触发搜索")

    client = _client(monkeypatch, seam)
    resp = client.get("/search")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "输入关键词" in body


def test_search_page_200_on_plain_hit_list(monkeypatch):
    """接缝返回裸命中列表（无信封对象）时也照常渲染。"""
    client = _client(
        monkeypatch,
        lambda keyword: [SearchHit(title="标题", url="https://x/y.html", desc="摘要")],
    )
    resp = client.get("/search?q=x")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "标题" in body
    assert "摘要" in body
