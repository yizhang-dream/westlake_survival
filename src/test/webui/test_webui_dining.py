"""餐饮页（/dining）：200、按校区分组、异常降级、空态。"""

from __future__ import annotations

import pytest

from westlake_survival.campus import DiningSpot
from westlake_survival.webui import app as webui_app
from westlake_survival.webui import create_app


def _client(monkeypatch, seam):
    monkeypatch.setattr(webui_app, "_campus_dining", seam)
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


@pytest.fixture
def app_client(monkeypatch):
    monkeypatch.setattr(
        webui_app,
        "_campus_dining",
        lambda: [
            DiningSpot(
                name="云谷第一食堂",
                campus="云谷",
                address="云谷校区学生活动中心",
                food="快餐 / 面食",
                hours=["早餐 06:30-09:00", "午餐 11:00-13:00"],
            ),
            DiningSpot(
                name="云栖咖啡吧",
                campus="云栖",
                address="云栖校区主楼一层",
                hours=["10:00-20:00"],
            ),
        ],
    )
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_dining_page_ok(app_client):
    resp = app_client.get("/dining")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "餐饮" in body
    # 按校区分组：两个校区标题都存在。
    assert "云谷 校区" in body
    assert "云栖 校区" in body
    # 名称 / 地点 / 营业时间。
    assert "云谷第一食堂" in body
    assert "云谷校区学生活动中心" in body
    assert "早餐 06:30-09:00" in body
    assert "10:00-20:00" in body


def test_dining_page_200_when_source_fails(monkeypatch):
    def boom():
        raise RuntimeError("boom")

    client = _client(monkeypatch, boom)
    resp = client.get("/dining")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "餐饮数据暂时不可用" in body
    assert "餐饮数据暂不可用" in body


def test_dining_page_200_when_empty(monkeypatch):
    client = _client(monkeypatch, lambda: [])
    resp = client.get("/dining")
    assert resp.status_code == 200
    assert "暂无餐饮数据" in resp.get_data(as_text=True)


def test_dining_page_tolerates_missing_attributes(monkeypatch):
    """餐饮点缺字段时逐字段 getattr，不抛 AttributeError。"""
    from types import SimpleNamespace

    client = _client(monkeypatch, lambda: [SimpleNamespace(name="无名食堂", campus="云谷")])
    resp = client.get("/dining")
    assert resp.status_code == 200
    assert "无名食堂" in resp.get_data(as_text=True)
