"""CASAuthorizer：登录流程、凭据错误、execution 解析。"""

from __future__ import annotations

from urllib.parse import quote

import pytest

from westlake_survival.exceptions import AuthError, InvalidCredentials
from westlake_survival.sso import providers as providers_pkg
from westlake_survival.sso.providers import cas as cas_mod
from westlake_survival.sso.providers.cas import CAS_LOGIN, CASAuthorizer

from conftest import CAS_LOGIN_PAGE, FakeResponse, FakeSession

SERVICE = "https://sis.westlake.edu.cn/psc/CSPRD_3/"


class ServiceAuth(CASAuthorizer):
    SERVICE_URL = SERVICE


@pytest.fixture
def creds(monkeypatch):
    monkeypatch.setattr(cas_mod, "read_credentials", lambda: ("2021001", "secret"))


def _happy_handler(record: dict):
    def handler(method, url, kw):
        if method == "GET" and url.startswith(CAS_LOGIN):
            record["login_url"] = url
            return FakeResponse(200, text=CAS_LOGIN_PAGE, url=url)
        if method == "POST":
            record["post_data"] = kw.get("data")
            record["post_allow_redirects"] = kw.get("allow_redirects")
            return FakeResponse(
                302,
                url=url,
                headers={"Location": "https://sis.westlake.edu.cn/psc/CSPRD_3/?ticket=ST-9"},
            )
        if method == "GET" and "ticket=" in url:
            record["redeem_url"] = url
            return FakeResponse(200, text="welcome", url=url)
        return FakeResponse(200, url=url)

    return handler


def test_login_url_quotes_service():
    auth = ServiceAuth()
    assert auth.login_url() == f"{CAS_LOGIN}?service={quote(SERVICE, safe='')}"


def test_happy_path_returns_session_with_ticket(install_session, creds):
    record: dict = {}
    session = FakeSession(handler=_happy_handler(record))
    install_session(session)

    auth = ServiceAuth()
    auth.ensure()

    assert auth.session is session
    assert record["login_url"] == f"{CAS_LOGIN}?service={quote(SERVICE, safe='')}"
    data = record["post_data"]
    assert data["username"] == "2021001"
    assert data["password"] == "secret"
    assert data["execution"] == "EXEC-123"
    assert data["_eventId"] == "submit"
    assert data["geolocation"] == ""
    # POST 必须不自动跟随重定向，以便读取 302 Location 里的 ticket。
    assert record["post_allow_redirects"] is False
    # ticket 被兑换（GET 到带 ticket 的回调）。
    assert "ticket=ST-9" in record["redeem_url"]


def test_invalid_credentials_redirect_without_ticket(install_session, creds):
    def handler(method, url, kw):
        if method == "GET":
            return FakeResponse(200, text=CAS_LOGIN_PAGE, url=url)
        return FakeResponse(
            302, url=url, headers={"Location": f"{CAS_LOGIN}?service={quote(SERVICE)}"}
        )

    install_session(FakeSession(handler=handler))
    auth = ServiceAuth()
    with pytest.raises(InvalidCredentials):
        auth.ensure()


def test_invalid_credentials_rerendered_form(install_session, creds):
    def handler(method, url, kw):
        if method == "GET":
            return FakeResponse(200, text=CAS_LOGIN_PAGE, url=url)
        return FakeResponse(200, text=CAS_LOGIN_PAGE, url=url)

    install_session(FakeSession(handler=handler))
    auth = ServiceAuth()
    with pytest.raises(InvalidCredentials):
        auth.ensure()


def test_missing_execution_raises_auth_error(install_session, creds):
    def handler(method, url, kw):
        return FakeResponse(200, text="<html>no execution here</html>", url=url)

    install_session(FakeSession(handler=handler))
    auth = ServiceAuth()
    with pytest.raises(AuthError):
        auth.ensure()


def test_unexpected_status_raises_auth_error(install_session, creds):
    def handler(method, url, kw):
        if method == "GET":
            return FakeResponse(200, text=CAS_LOGIN_PAGE, url=url)
        return FakeResponse(500, text="boom", url=url)

    install_session(FakeSession(handler=handler))
    auth = ServiceAuth()
    with pytest.raises(AuthError):
        auth.ensure()


def test_execution_regex_matches_single_space_and_newlines():
    from westlake_survival.sso.providers.cas import _EXECUTION_RE

    assert _EXECUTION_RE.search('<input type="hidden" name="execution" value="ABC"/>').group(1) == "ABC"
    multiline = '<input type="hidden"\n  name="execution"\n  value="XYZ-1"/>'
    assert _EXECUTION_RE.search(multiline).group(1) == "XYZ-1"


def test_missing_service_url_raises():
    auth = CASAuthorizer()
    with pytest.raises(AuthError):
        auth.login_url()


def test_providers_package_exports_cas():
    assert providers_pkg.CASAuthorizer is CASAuthorizer