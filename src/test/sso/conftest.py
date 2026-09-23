"""src/test/sso 的公共夹具：假 Session/Response + 单例/环境清理。

所有测试**离线**：不发起任何真实网络请求（live 测试除外）。
"""

from __future__ import annotations

import os
from typing import Any, Callable

import pytest

from westlake_survival.sso import authorizer as authorizer_mod
from westlake_survival.sso.authorizer import Authorizer
from westlake_survival.sso.creds import cred_clear


class FakeResponse:
    """最小化 :class:`requests.Response` 替身。"""

    def __init__(
        self,
        status_code: int = 200,
        text: str = "",
        url: str = "",
        headers: dict[str, str] | None = None,
        json_data: Any = None,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self.url = url
        self.headers = headers or {}
        self._json = json_data

    def json(self) -> Any:
        return self._json


class FakeSession:
    """最小化 :class:`requests.Session` 替身。

    通过 *handler* 决定每个请求的响应；若未提供 handler，则按顺序弹出
    *responses*。``get``/``post``/``request`` 都会被记录到 ``calls``。
    """

    def __init__(
        self,
        responses: list[FakeResponse] | None = None,
        handler: Callable[[str, str, dict], FakeResponse] | None = None,
    ) -> None:
        self.headers: dict[str, str] = {}
        self.cookies: dict[str, str] = {}
        self.calls: list[tuple[str, str, dict]] = []
        self._responses = list(responses or [])
        self._handler = handler

    def request(self, method: str, url: str, **kw: Any) -> FakeResponse:
        self.calls.append((method, url, kw))
        if self._handler is not None:
            return self._handler(method, url, kw)
        return self._responses.pop(0)

    def get(self, url: str, **kw: Any) -> FakeResponse:
        return self.request("GET", url, **kw)

    def post(self, url: str, **kw: Any) -> FakeResponse:
        return self.request("POST", url, **kw)


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch, tmp_path):
    """每个测试前：清空单例、内存凭据、凭据相关环境变量，重定位配置目录。"""
    Authorizer._instances.clear()
    cred_clear()
    monkeypatch.delenv("WESTLAKE_CREDENTIALS", raising=False)
    monkeypatch.delenv("WESTLAKE_CANVAS_TOKEN", raising=False)
    monkeypatch.setenv("WESTLAKE_HOME", str(tmp_path / "home"))
    yield
    Authorizer._instances.clear()
    cred_clear()


@pytest.fixture
def install_session(monkeypatch):
    """把 ``http_session`` 打桩为一串假 Session。

    用法::

        session = install_session(handler=...)
        # 或
        first, second = install_session(FakeSession(...), FakeSession(...))
    """

    def _install(*sessions: FakeSession) -> FakeSession:
        if not sessions:
            sessions = (FakeSession(),)
        iterator = iter(sessions)

        def _factory(**kw: Any) -> FakeSession:
            try:
                return next(iterator)
            except StopIteration:  # pragma: no cover - 测试配置错误
                raise AssertionError("http_session() 被调用次数超过预期")

        monkeypatch.setattr(authorizer_mod, "http_session", _factory)
        return sessions[0]

    return _install


@pytest.fixture
def clock(monkeypatch):
    """可控时钟：``clock.advance(seconds)`` 推进 ``authorizer.time.time``。"""

    class Clock:
        def __init__(self) -> None:
            self.now = 1_000_000.0

        def advance(self, seconds: float) -> None:
            self.now += seconds

    clock = Clock()
    monkeypatch.setattr(authorizer_mod.time, "time", lambda: clock.now)
    return clock


def write_cred_file(tmp_path, content: str) -> None:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    (home / "credentials.txt").write_text(content, encoding="utf-8")


def set_env_cred(monkeypatch, value: str) -> None:
    monkeypatch.setenv("WESTLAKE_CREDENTIALS", value)


# 常用响应片段。
CAS_LOGIN_PAGE = (
    '<form id="loginForm" method="post">'
    '<input id="username" name="username" type="text"/>'
    '<input id="password" name="password" type="password"/>'
    '<input type="hidden" name="execution" value="EXEC-123"/>'
    '<input type="hidden" name="_eventId" value="submit"/>'
    '<input type="hidden" name="geolocation"/>'
    "</form>"
)


def cas_location(ticket: str = "ST-abc-123") -> dict[str, str]:
    return {"Location": f"https://example.edu/callback?ticket={ticket}"}


CAS_LOGIN_URL = "https://sso.westlake.edu.cn/cas/login"

os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")