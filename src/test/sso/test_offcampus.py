"""``is_offcampus`` 的形态判定：403 正文特征 + 302 跳转 ckreq 特征。"""

from __future__ import annotations

from westlake_survival.exceptions import is_offcampus

from conftest import FakeResponse


def test_403_with_block_marker_is_offcampus():
    resp = FakeResponse(
        status_code=403,
        text="Access forbidden, please contact administrator",
        url="https://sis.westlake.edu.cn/",
    )
    assert is_offcampus(resp) is True


def test_403_with_ckreq_body_marker_is_offcampus():
    resp = FakeResponse(
        status_code=403,
        text="<html>... /psc/CSPRD_3/?cmd=login&errorPg=ckreq ...</html>",
    )
    assert is_offcampus(resp) is True


def test_403_with_unrelated_text_is_not_offcampus():
    resp = FakeResponse(status_code=403, text="<html>Forbidden</html>")
    assert is_offcampus(resp) is False


def test_302_redirect_with_ckreq_location_is_offcampus():
    resp = FakeResponse(
        status_code=302,
        url="https://sis.westlake.edu.cn/psc/CSPRD_3/",
        headers={
            "Location": "https://sis.westlake.edu.cn/psc/CSPRD_3/?cmd=login&errorPg=ckreq"
        },
    )
    assert is_offcampus(resp) is True


def test_301_and_303_redirect_with_ckreq_location_is_offcampus():
    for status in (301, 303):
        resp = FakeResponse(
            status_code=status,
            headers={"Location": "https://sis.westlake.edu.cn/?cmd=login&errorPg=ckreq"},
        )
        assert is_offcampus(resp) is True, status


def test_302_plain_login_redirect_is_not_offcampus():
    resp = FakeResponse(
        status_code=302,
        headers={
            "Location": "https://sso.westlake.edu.cn/cas/login?service=https%3A%2F%2Fsis"
        },
    )
    assert is_offcampus(resp) is False


def test_302_redirect_to_cmd_login_without_ckreq_is_not_offcampus():
    resp = FakeResponse(
        status_code=302,
        headers={"Location": "https://sis.westlake.edu.cn/psc/CSPRD_3/?cmd=login"},
    )
    assert is_offcampus(resp) is False


def test_200_is_not_offcampus():
    resp = FakeResponse(status_code=200, text="ok")
    assert is_offcampus(resp) is False