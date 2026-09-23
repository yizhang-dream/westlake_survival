"""Authorizer 基类：单例、TTL、失效自愈、check、require_auth、校外拦截。"""

from __future__ import annotations

import threading
import time as _time

import pytest

from westlake_survival.exceptions import OffCampusError, SessionExpired
from westlake_survival.sso import require_auth
from westlake_survival.sso.authorizer import Authorizer
from westlake_survival.sso.creds import cred_set

from conftest import FakeResponse, FakeSession


class DummyAuth(Authorizer):
    BASE_URL = "https://dummy.example.edu/"

    def _setup(self) -> None:
        self.builds = 0

    def _build_session(self):
        self.builds += 1
        session = self._new_session()
        session.headers["X-Build"] = str(self.builds)
        return session


def _cas_stale() -> FakeResponse:
    return FakeResponse(
        status_code=302,
        url="https://dummy.example.edu/",
        headers={"Location": "https://sso.westlake.edu.cn/cas/login?service=x"},
    )


def test_singleton_identity_per_subclass():
    assert DummyAuth() is DummyAuth()
    assert DummyAuth() is not None


def test_singleton_is_not_reinitialized():
    first = DummyAuth()
    first.builds = 42
    second = DummyAuth()
    assert second is first
    assert second.builds == 42


def test_distinct_subclasses_have_distinct_instances():
    class Other(Authorizer):
        def _build_session(self):
            return self._new_session()

    assert DummyAuth() is not Other()


def test_ensure_logs_in_once(install_session):
    session = install_session(FakeSession())
    auth = DummyAuth()
    auth.ensure()
    auth.ensure()
    assert auth.builds == 1
    assert auth.session is session


def test_ttl_expiry_triggers_relogin(install_session, clock):
    install_session(FakeSession(), FakeSession())
    auth = DummyAuth()
    auth.ensure()
    assert auth.builds == 1
    clock.advance(Authorizer.SESSION_TTL + 1)
    auth.ensure()
    assert auth.builds == 2


def test_within_ttl_does_not_relogin(install_session, clock):
    install_session(FakeSession())
    auth = DummyAuth()
    auth.ensure()
    clock.advance(Authorizer.SESSION_TTL - 1)
    auth.ensure()
    assert auth.builds == 1


def test_stale_triggers_refresh_then_retry_succeeds(install_session):
    stale = FakeSession(handler=lambda m, u, k: _cas_stale())
    fresh = FakeSession(handler=lambda m, u, k: FakeResponse(200, text="ok", url=u))
    install_session(stale, fresh)

    auth = DummyAuth()
    response = auth.get("https://dummy.example.edu/grades")
    assert response.status_code == 200
    assert auth.builds == 2  # 初始登录 + 失效后刷新
    assert len(stale.calls) == 1
    assert len(fresh.calls) == 1


def test_stale_twice_raises_session_expired(install_session):
    install_session(
        FakeSession(handler=lambda m, u, k: _cas_stale()),
        FakeSession(handler=lambda m, u, k: _cas_stale()),
    )
    auth = DummyAuth()
    with pytest.raises(SessionExpired):
        auth.get("https://dummy.example.edu/grades")


def test_post_also_heals(install_session):
    stale = FakeSession(handler=lambda m, u, k: _cas_stale())
    fresh = FakeSession(handler=lambda m, u, k: FakeResponse(200, text="ok", url=u))
    install_session(stale, fresh)
    auth = DummyAuth()
    response = auth.post("https://dummy.example.edu/action", data={"a": "b"})
    assert response.status_code == 200
    assert fresh.calls[0][0] == "POST"


def test_final_url_in_cas_domain_is_stale():
    auth = DummyAuth()
    resp = FakeResponse(200, url="https://sso.westlake.edu.cn/cas/login?service=x")
    assert auth._is_stale_response(resp) is True


def test_normal_200_is_not_stale():
    auth = DummyAuth()
    assert auth._is_stale_response(FakeResponse(200, url="https://dummy.example.edu/")) is False


def test_offcampus_response_raises(install_session):
    forbidden = FakeResponse(
        status_code=403,
        text="Access forbidden, please contact administrator",
        url="https://dummy.example.edu/",
    )
    install_session(FakeSession(handler=lambda m, u, k: forbidden))
    auth = DummyAuth()
    with pytest.raises(OffCampusError):
        auth.get("https://dummy.example.edu/x")


def test_check_without_session_is_false():
    assert DummyAuth().check() is False


def test_check_true_on_healthy_session(install_session):
    install_session(FakeSession(handler=lambda m, u, k: FakeResponse(200, url=u)))
    auth = DummyAuth()
    auth.ensure()
    assert auth.check() is True


def test_check_false_when_redirected_to_cas(install_session):
    install_session(FakeSession(handler=lambda m, u, k: _cas_stale()))
    auth = DummyAuth()
    auth.ensure()
    assert auth.check() is False


def test_require_auth_injects_instance(install_session):
    install_session(FakeSession())

    @require_auth(DummyAuth)
    def view(*, auth):
        return auth

    auth = view()
    assert isinstance(auth, DummyAuth)
    assert auth.builds == 1  # 已 ensure
    assert view() is auth  # 单例


def test_require_auth_respects_explicit_auth(install_session):
    install_session(FakeSession())
    sentinel = DummyAuth()

    @require_auth(DummyAuth)
    def view(*, auth):
        return auth

    assert view(auth=sentinel) is sentinel


def test_session_property_ensures_login(install_session):
    session = install_session(FakeSession())
    auth = DummyAuth()
    assert auth.session is session
    assert auth.builds == 1


def test_concurrent_ensure_logs_in_once(install_session):
    """多线程并发首访 ensure() 只触发一次 _build_session（double-checked 加锁）。"""
    session = install_session(FakeSession())
    auth = DummyAuth()

    # 放大竞争窗口：让登录慢一点，确保各线程在锁上真正相遇。
    original_build = auth._build_session

    def slow_build():
        _time.sleep(0.02)
        return original_build()

    auth._build_session = slow_build  # type: ignore[method-assign]

    n = 8
    barrier = threading.Barrier(n)
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            barrier.wait()
            auth.ensure()
        except BaseException as exc:  # noqa: BLE001 - 收集线程内异常
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert auth.builds == 1  # 只登录一次
    assert auth.session is session