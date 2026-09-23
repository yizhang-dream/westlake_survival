"""LibAuth：OPAC CAS 回调配置与登录流程。"""

from __future__ import annotations

import pytest

from westlake_survival.sso.providers import cas as cas_mod
from westlake_survival.sso.providers.lib import (
    OPAC_SERVICE_URL,
    OPAC_SERVICE_URL_PUBLIC,
    LibAuth,
)

from conftest import CAS_LOGIN_PAGE, FakeResponse, FakeSession


@pytest.fixture
def creds(monkeypatch):
    # LibAuth 复用 CASAuthorizer._build_session，凭据从 cas 模块读取。
    monkeypatch.setattr(cas_mod, "read_credentials", lambda: ("2021001", "secret"))


def test_service_url_is_cas_callback():
    assert LibAuth.SERVICE_URL == OPAC_SERVICE_URL
    assert OPAC_SERVICE_URL.endswith("/opac/cas/casLogin.do")
    assert OPAC_SERVICE_URL.startswith("http://")


def test_public_alias_differs():
    assert OPAC_SERVICE_URL_PUBLIC != OPAC_SERVICE_URL
    assert OPAC_SERVICE_URL_PUBLIC.endswith("/opac/cas/casLogin.do")


def test_lib_login_uses_opac_service(install_session, creds):
    record: dict = {}

    def handler(method, url, kw):
        if method == "GET" and "cas/login" in url and "ticket=" not in url:
            record["login_url"] = url
            return FakeResponse(200, text=CAS_LOGIN_PAGE, url=url)
        if method == "POST":
            return FakeResponse(
                302, url=url, headers={"Location": OPAC_SERVICE_URL + "?ticket=ST-1"}
            )
        return FakeResponse(200, text="ok", url=url)

    install_session(FakeSession(handler=handler))
    LibAuth().ensure()
    assert "opac" in record["login_url"]
    assert "casLogin.do" in record["login_url"]