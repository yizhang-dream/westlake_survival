"""公开 API（__init__ 导出、单例工厂、便捷函数）测试。"""

from __future__ import annotations

import westlake_survival.canvas as canvas_module
from westlake_survival.canvas import (
    Assignment,
    CanvasClient,
    canvas,
    reset_canvas,
    upcoming_deadlines,
)


def test_public_names_importable():
    # 验收标准 #2 要求的导入集合
    from westlake_survival.canvas import (
        Assignment,
        CanvasClient as Client,
        Course,
        canvas as factory,
        upcoming_deadlines as deadlines,
    )

    assert all(obj is not None for obj in (Client, factory, Course, Assignment, deadlines))


def test_singleton_returns_same_instance(monkeypatch):
    monkeypatch.setenv("WESTLAKE_CANVAS_TOKEN", "tok")
    reset_canvas()
    try:
        first = canvas()
        second = canvas()
        assert isinstance(first, CanvasClient)
        assert first is second
    finally:
        reset_canvas()


def test_explicit_token_rebuilds_singleton(monkeypatch):
    monkeypatch.setenv("WESTLAKE_CANVAS_TOKEN", "tok")
    reset_canvas()
    try:
        first = canvas()
        rebuilt = canvas(token="other")
        assert rebuilt is not first
        assert rebuilt.token == "other"
    finally:
        reset_canvas()


def test_module_level_upcoming_deadlines_delegates(monkeypatch, tmp_path):
    monkeypatch.setenv("WESTLAKE_HOME", str(tmp_path))
    monkeypatch.setenv("WESTLAKE_CANVAS_TOKEN", "tok")
    reset_canvas()
    sentinel = [Assignment(id=1)]
    try:
        client = canvas_module.canvas()
        client.upcoming_deadlines = lambda limit=10: sentinel
        assert upcoming_deadlines(3) is sentinel
    finally:
        reset_canvas()
