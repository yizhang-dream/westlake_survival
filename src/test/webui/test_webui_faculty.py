"""教师检索页（/faculty）：200、渲染结果表、异常降级、空态与新增字段兜底。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from westlake_survival.faculty import FacultyMember, SCHOOL_NAMES
from westlake_survival.webui import app as webui_app
from westlake_survival.webui import create_app


def _client(monkeypatch, seam):
    monkeypatch.setattr(webui_app, "_faculty_data", seam)
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


@pytest.fixture
def app_client(monkeypatch):
    monkeypatch.setattr(
        webui_app,
        "_faculty_data",
        lambda school=None, keyword=None: [
            FacultyMember(
                name="李奕璠",
                name_en="Yifan Li, Ph.D.",
                school="理学院",
                subject="物理学",
                lab="冷原子量子调控实验室",
                url="https://www.westlake.edu.cn/faculty/yifan-li.html",
            )
        ],
    )
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_faculty_page_ok(app_client):
    resp = app_client.get("/faculty?school=理学院&keyword=量子")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "教师检索" in body
    # 姓名 / 英文名 / 学院 / 方向 / 官网链接。
    assert "李奕璠" in body
    assert "Yifan Li, Ph.D." in body
    assert "物理学" in body
    assert "冷原子量子调控实验室" in body
    assert "https://www.westlake.edu.cn/faculty/yifan-li.html" in body
    # 下拉选项来自 faculty.SCHOOL_NAMES。
    for school in SCHOOL_NAMES:
        assert school in body


def test_faculty_page_200_when_source_fails(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    client = _client(monkeypatch, boom)
    resp = client.get("/faculty?keyword=量子")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "教师名录暂时不可用" in body
    assert "教师名录暂不可用" in body


def test_faculty_page_200_when_empty(monkeypatch):
    client = _client(monkeypatch, lambda school=None, keyword=None: [])
    resp = client.get("/faculty?keyword=不存在的关键词")
    assert resp.status_code == 200
    assert "未找到匹配的教师" in resp.get_data(as_text=True)


def test_faculty_page_first_visit_not_searched(monkeypatch):
    """首次进入（无筛选条件）给出引导文案，而不是「未找到」，也不发起抓取。"""

    def seam(school=None, keyword=None):  # pragma: no cover - 不应被调用
        raise AssertionError("裸访问不应触发抓取")

    client = _client(monkeypatch, seam)
    resp = client.get("/faculty")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "输入学院或关键词" in body
    assert "未找到匹配的教师" not in body


def test_faculty_page_tolerates_extra_fields(monkeypatch):
    """faculty 模块新增「代表作」字段时页面照常渲染（getattr 兜底）。"""

    def seam(school=None, keyword=None):
        return [
            FacultyMember(name="张三", school="工学院", subject="计算机"),
            SimpleNamespace(
                name="李四",
                name_en="",
                school="医学院",
                subject="生物学",
                lab=None,
                url="https://www.westlake.edu.cn/faculty/li-si.html",
                works="Cell, 2025",  # 另一个 agent 正在新增的字段
            ),
        ]

    client = _client(monkeypatch, seam)
    resp = client.get("/faculty?keyword=李")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "张三" in body
    assert "李四" in body
    assert "Cell, 2025" in body


def test_faculty_page_tolerates_missing_attributes(monkeypatch):
    """结果对象缺字段时逐字段 getattr，不抛 AttributeError。"""
    client = _client(monkeypatch, lambda school=None, keyword=None: [SimpleNamespace(name="王五")])
    resp = client.get("/faculty?keyword=王")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "王五" in body
