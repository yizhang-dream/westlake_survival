"""Canvas LMS 子模块：在 API 层面访问西湖大学 Canvas。

当前实现基于 Canvas 自带的 REST API（Bearer Token 认证）::

    from westlake_survival.canvas import canvas

    client = canvas()                 # 单例工厂，token 自动解析
    client.me()                       # 当前用户
    client.list_courses()             # active 课程
    client.upcoming_deadlines(5)      # 即将到期的作业
    client.submit_assignment(101, 202, file_paths=["hw1.pdf"])  # 交作业

模块级还提供一个便捷函数 :func:`upcoming_deadlines`，等价于
``canvas().upcoming_deadlines(...)``。
"""

from __future__ import annotations

from westlake_survival.canvas.client import (
    CANVAS_BASE,
    TOKEN_ENV_VAR,
    CanvasClient,
    resolve_token,
)
from westlake_survival.canvas.models import (
    CHINA_TZ,
    SUBMISSION_TYPE_TEXT,
    SUBMISSION_TYPE_UPLOAD,
    SUBMISSION_TYPE_URL,
    Announcement,
    Assignment,
    Course,
    File,
    Submission,
    TodoItem,
    User,
)

__all__ = [
    "CANVAS_BASE",
    "CHINA_TZ",
    "SUBMISSION_TYPE_TEXT",
    "SUBMISSION_TYPE_UPLOAD",
    "SUBMISSION_TYPE_URL",
    "TOKEN_ENV_VAR",
    "Announcement",
    "Assignment",
    "CanvasClient",
    "Course",
    "File",
    "Submission",
    "TodoItem",
    "User",
    "canvas",
    "reset_canvas",
    "upcoming_deadlines",
]

_singleton: CanvasClient | None = None


def canvas(token: str | None = None) -> CanvasClient:
    """返回共享的 :class:`CanvasClient` 单例（首次调用时创建）。

    传入 *token* 会重建单例（便于测试或切换账号）。
    """
    global _singleton
    if _singleton is None or token is not None:
        _singleton = CanvasClient(token=token)
    return _singleton


def reset_canvas() -> None:
    """清空单例（测试用）。"""
    global _singleton
    _singleton = None


def upcoming_deadlines(limit: int = 10) -> list[Assignment]:
    """便捷函数：用单例客户端取即将到期的作业。"""
    return canvas().upcoming_deadlines(limit=limit)
