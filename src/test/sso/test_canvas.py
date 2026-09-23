"""CanvasAuth：Bearer token 三级解析、401 处理。"""

from __future__ import annotations

import pytest

from westlake_survival.exceptions import AuthError, SessionExpired
from westlake_survival.sso.providers.canvas import CanvasAuth

from conftest import FakeResponse, FakeSession


def test_token_from_constructor_param():
    assert CanvasAuth(token="PARAM").token == "PARAM"


def test_token_from_env(monkeypatch):
    monkeypatch.setenv("WESTLAKE_CANVAS_TOKEN", "ENVTOK")
    assert CanvasAuth().token == "ENVTOK"


def test_token_from_file(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    (home / "canvas_token.txt").write_text("\nFILETOK\nsecond-line\n", encoding="utf-8")
    assert CanvasAuth().token == "FILETOK"


def test_param_beats_env_and_file(monkeypatch, tmp_path):
    monkeypatch.setenv("WESTLAKE_CANVAS_TOKEN", "ENVTOK")
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    (home / "canvas_token.txt").write_text("FILETOK", encoding="utf-8")
    assert CanvasAuth(token="PARAM").token == "PARAM"


def test_env_beats_file(monkeypatch, tmp_path):
    monkeypatch.setenv("WESTLAKE_CANVAS_TOKEN", "ENVTOK")
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    (home / "canvas_token.txt").write_text("FILETOK", encoding="utf-8")
    assert CanvasAuth().token == "ENVTOK"


def test_missing_token_raises():
    with pytest.raises(AuthError):
        CanvasAuth().token


def test_get_injects_bearer_header(install_session):
    session = install_session(FakeSession(handler=lambda m, u, k: FakeResponse(200, url=u)))
    auth = CanvasAuth(token="T")
    auth.get("https://canvas.westlake.edu.cn/api/v1/courses")
    assert session.headers["Authorization"] == "Bearer T"


def test_per_call_token_overrides(install_session):
    session = install_session(FakeSession(handler=lambda m, u, k: FakeResponse(200, url=u)))
    auth = CanvasAuth(token="T")
    auth.get("https://canvas.westlake.edu.cn/api/v1/courses", token="U")
    assert session.headers["Authorization"] == "Bearer U"


def test_per_call_token_without_any_config(install_session):
    """三级来源全无时，per-call token 仍可用且不触发 AuthError。"""
    session = install_session(FakeSession(handler=lambda m, u, k: FakeResponse(200, url=u)))
    auth = CanvasAuth()
    auth.get("https://canvas.westlake.edu.cn/api/v1/courses", token="U")
    assert session.headers["Authorization"] == "Bearer U"


def test_per_call_token_overrides_existing_session(install_session):
    """已有会话时，per-call token 覆盖当次请求头。"""
    session = install_session(FakeSession(handler=lambda m, u, k: FakeResponse(200, url=u)))
    auth = CanvasAuth(token="T")
    auth.ensure()
    assert session.headers["Authorization"] == "Bearer T"
    auth.get("https://canvas.westlake.edu.cn/api/v1/courses", token="U")
    assert session.headers["Authorization"] == "Bearer U"


def test_post_injects_bearer_header(install_session):
    session = install_session(FakeSession(handler=lambda m, u, k: FakeResponse(200, url=u)))
    auth = CanvasAuth(token="T")
    auth.post("https://canvas.westlake.edu.cn/api/v1/x", data={"a": "b"})
    assert session.headers["Authorization"] == "Bearer T"


def test_401_triggers_refresh_then_still_401_raises(install_session):
    install_session(
        FakeSession(handler=lambda m, u, k: FakeResponse(401, url=u)),
        FakeSession(handler=lambda m, u, k: FakeResponse(401, url=u)),
    )
    auth = CanvasAuth(token="T")
    with pytest.raises(SessionExpired):
        auth.get("https://canvas.westlake.edu.cn/api/v1/courses")


def test_401_then_success_after_refresh(install_session):
    install_session(
        FakeSession(handler=lambda m, u, k: FakeResponse(401, url=u)),
        FakeSession(handler=lambda m, u, k: FakeResponse(200, url=u, json_data={"id": 1})),
    )
    auth = CanvasAuth(token="T")
    response = auth.get("https://canvas.westlake.edu.cn/api/v1/users/self")
    assert response.status_code == 200
    assert response.json() == {"id": 1}


def test_check_false_on_401(install_session):
    install_session(FakeSession(handler=lambda m, u, k: FakeResponse(401, url=u)))
    auth = CanvasAuth(token="T")
    auth.ensure()
    assert auth.check() is False


def test_check_true_on_200(install_session):
    install_session(FakeSession(handler=lambda m, u, k: FakeResponse(200, url=u)))
    auth = CanvasAuth(token="T")
    auth.ensure()
    assert auth.check() is True


def test_check_without_session_is_false():
    assert CanvasAuth(token="T").check() is False