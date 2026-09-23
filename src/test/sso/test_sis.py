"""SISAuth：PeopleSoft 本地登录（实测策略）。"""

from __future__ import annotations

import pytest

from westlake_survival.exceptions import InvalidCredentials, OffCampusError
from westlake_survival.sso.providers import sis as sis_mod
from westlake_survival.sso.providers.sis import SISAuth, _hidden_fields

from conftest import FakeResponse, FakeSession

SIS_PAGE = (
    '<form id="login" name="login" method="post" action="?&cmd=login&languageCd=ENG">'
    '<input type="hidden" id="lcsrf_token" name="lcsrf_token" value="CSRF-1">'
    '<input type="hidden" id="timezoneOffset" name="timezoneOffset" value="0">'
    '<input type="hidden" id="ptmode" name="ptmode" value="f">'
    '<input type="text" id="userid" name="userid" value="">'
    '<input type="password" id="pwd" name="pwd">'
    '<input name="Submit" type="submit" value="Sign In">'
    "</form>"
)


@pytest.fixture
def creds(monkeypatch):
    monkeypatch.setattr(sis_mod, "read_credentials", lambda: ("2021001", "secret"))


def test_hidden_fields_extraction():
    fields = _hidden_fields(SIS_PAGE)
    assert fields == {"lcsrf_token": "CSRF-1", "timezoneOffset": "0", "ptmode": "f"}


def test_ps_login_happy_path_sets_ps_token(install_session, creds):
    record: dict = {}

    def handler(method, url, kw):
        if method == "GET":
            record["get_url"] = url
            return FakeResponse(200, text=SIS_PAGE, url=url)
        record["post_url"] = url
        record["post_data"] = kw.get("data")
        session.cookies["PS_TOKEN"] = "TOKEN-1"
        return FakeResponse(302, url=url)

    session = FakeSession(handler=handler)
    install_session(session)

    auth = SISAuth()
    auth.ensure()

    assert auth.session is session
    assert session.cookies["PS_TOKEN"] == "TOKEN-1"
    assert "cmd=login" in record["get_url"]
    data = record["post_data"]
    assert data["userid"] == "2021001"
    assert data["pwd"] == "secret"
    assert data["Submit"] == "Sign In"
    assert data["lcsrf_token"] == "CSRF-1"  # 隐藏字段被回传


def test_ps_login_without_ps_token_is_invalid(install_session, creds):
    def handler(method, url, kw):
        if method == "GET":
            return FakeResponse(200, text=SIS_PAGE, url=url)
        return FakeResponse(200, text=SIS_PAGE, url=url)  # 重渲染登录页

    install_session(FakeSession(handler=handler))
    auth = SISAuth()
    with pytest.raises(InvalidCredentials):
        auth.ensure()


def test_offcampus_login_page_raises(install_session, creds):
    def handler(method, url, kw):
        return FakeResponse(
            403,
            text="Access forbidden, please contact administrator",
            url=url,
        )

    install_session(FakeSession(handler=handler))
    auth = SISAuth()
    with pytest.raises(OffCampusError):
        auth.ensure()


def test_stale_detected_by_cmd_login_in_url():
    auth = SISAuth()
    resp = FakeResponse(200, url="https://sis.westlake.edu.cn/psc/CSPRD_3/?cmd=login")
    assert auth._is_stale_response(resp) is True


def test_stale_detected_by_signon_body():
    auth = SISAuth()
    resp = FakeResponse(
        200,
        url="https://sis.westlake.edu.cn/psc/CSPRD_3/",
        text='<form action="?&cmd=login"><input name="pwd"></form>',
    )
    assert auth._is_stale_response(resp) is True


def test_normal_response_not_stale():
    auth = SISAuth()
    resp = FakeResponse(200, url="https://sis.westlake.edu.cn/psc/CSPRD_3/", text="ok")
    assert auth._is_stale_response(resp) is False


def test_check_false_without_session():
    auth = SISAuth()
    assert auth.check() is False


def test_check_false_when_redirected_to_login(install_session, creds):
    def handler(method, url, kw):
        if method == "GET" and "cmd=login" in url:
            return FakeResponse(200, text=SIS_PAGE, url=url)
        session.cookies["PS_TOKEN"] = "T"
        return FakeResponse(
            200, url="https://sis.westlake.edu.cn/psc/CSPRD_3/?cmd=login", text=SIS_PAGE
        )

    session = FakeSession(handler=handler)
    install_session(session)
    auth = SISAuth()
    auth.ensure()
    assert auth.check() is False


def test_sis_uses_people_soft_local_login_not_cas(install_session, creds):
    """回归：确认 SIS 走 PS 表单（GET 登录页 + POST userid/pwd），未触碰 CAS。"""
    touched = {"cas": False}

    def handler(method, url, kw):
        if "sso.westlake.edu.cn" in url:
            touched["cas"] = True
        if method == "GET":
            return FakeResponse(200, text=SIS_PAGE, url=url)
        session.cookies["PS_TOKEN"] = "T"
        return FakeResponse(302, url=url)

    session = FakeSession(handler=handler)
    install_session(session)
    SISAuth().ensure()
    assert touched["cas"] is False