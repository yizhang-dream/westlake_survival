"""首页（仪表盘）：200、渲染 context 快照、无数据时仍 200。"""

from __future__ import annotations

import pytest

from westlake_survival.webui import app as webui_app
from westlake_survival.webui import create_app


@pytest.fixture
def app_client(monkeypatch, fixed_context, fixed_transit):
    monkeypatch.setattr(webui_app, "_context_data", lambda level="normal": dict(fixed_context))
    monkeypatch.setattr(webui_app, "_transit_data", lambda: fixed_transit)
    monkeypatch.setattr(webui_app, "_calendar_data", lambda: None)
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_index_ok_with_context(app_client):
    resp = app_client.get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # 周次文本（验收标准点名要含周次）。
    assert "第 12 周" in body
    assert "教学周" in body
    # 日期与学期。
    assert "2026-11-16" in body
    assert "2026年秋季" in body
    # 最近事件与下班车。
    assert "期中考试周" in body
    assert "09:45" in body
    # verbose 卡片（有就渲染）。
    assert "多云" in body
    assert "优" in body


def test_index_200_when_context_missing(monkeypatch):
    """context 模块不可用（接缝返回 None）时首页仍 200 且提示降级。"""
    monkeypatch.setattr(webui_app, "_context_data", lambda level="normal": None)
    monkeypatch.setattr(webui_app, "_transit_data", lambda: None)
    monkeypatch.setattr(webui_app, "_calendar_data", lambda: None)
    app = create_app()
    app.config.update(TESTING=True)
    resp = app.test_client().get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "暂不可用" in body  # 降级提示
    assert "—" in body  # 占位破折号


def test_index_graceful_on_context_exception(monkeypatch):
    """接缝抛异常时外围兜底成 500 错误页（而非裸栈）。"""
    def boom(level="normal"):
        raise RuntimeError("boom")

    monkeypatch.setattr(webui_app, "_context_data", boom)
    app = create_app()
    app.config.update(TESTING=True)
    resp = app.test_client().get("/")
    assert resp.status_code == 500
    body = resp.get_data(as_text=True)
    assert "出错" in body


def test_index_renders_verbose_cards_as_dash_when_absent(monkeypatch, fixed_context):
    """verbose 字段缺失时对应卡片显示「—」，不报错。"""
    ctx = dict(fixed_context)
    ctx["weather"] = None
    ctx["aqi"] = None
    ctx["next_deadlines"] = None
    monkeypatch.setattr(webui_app, "_context_data", lambda level="normal": ctx)
    monkeypatch.setattr(webui_app, "_transit_data", lambda: None)
    monkeypatch.setattr(webui_app, "_calendar_data", lambda: None)
    app = create_app()
    app.config.update(TESTING=True)
    resp = app.test_client().get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "天气" in body and "—" in body
