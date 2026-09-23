"""个人借阅解析（mock LibAuth）的离线测试。"""

from __future__ import annotations

import pytest

from _helpers import (
    CN_LOGIN_HTML,
    LOGIN_HTML,
    LOANS_HTML,
    PLAIN_PAGE_WITH_PASSWORD_LINK_HTML,
    FakeAuth,
    FakeResponse,
)
from westlake_survival.exceptions import AuthError, ParseError
from westlake_survival.lib import Loan, my_loans
from westlake_survival.lib.opac import _looks_like_login_page, parse_loans


def test_parse_loans() -> None:
    loans = parse_loans(LOANS_HTML)

    assert len(loans) == 2
    first = loans[0]
    assert isinstance(first, Loan)
    assert first.title == "机器学习"
    assert first.barcode == "B1001"
    assert first.due_date == "2026-10-01"
    assert first.renewable is True
    assert first.location == "云谷校区"

    assert loans[1].renewable is False
    assert loans[1].barcode == "B1002"


def test_parse_loans_empty_page() -> None:
    assert parse_loans("<html><body><p>无借阅</p></body></html>") == []


def test_my_loans_with_mock_auth() -> None:
    auth = FakeAuth(lambda url: FakeResponse(LOANS_HTML, url=url))
    loans = my_loans(auth=auth)

    assert len(loans) == 2
    assert loans[0].title == "机器学习"
    # 命中第一个候选路径即返回
    assert auth.calls == ["http://172.16.10.223:8180/opac/reader/loanList.do"]


def test_my_loans_login_page_raises_auth_error() -> None:
    auth = FakeAuth(lambda url: FakeResponse(LOGIN_HTML, url=url))
    with pytest.raises(AuthError):
        my_loans(auth=auth)


def test_my_loans_all_paths_404_raises_parse_error() -> None:
    auth = FakeAuth(lambda url: FakeResponse("not found", status=404, url=url))
    with pytest.raises(ParseError):
        my_loans(auth=auth)


# --------------------------------------------------------------------------- #
# _looks_like_login_page 判定收紧（reviewer P2）
# --------------------------------------------------------------------------- #


def test_looks_like_login_page_plain_page_with_password_link_is_false() -> None:
    """① 普通页带“修改密码 password”链接 + “登录”字样但无密码输入框 → False。"""
    assert _looks_like_login_page(PLAIN_PAGE_WITH_PASSWORD_LINK_HTML) is False


def test_looks_like_login_page_password_form_is_true() -> None:
    """② 含 <form><input type="password"> 的登录页 → True。"""
    assert _looks_like_login_page(LOGIN_HTML) is True


def test_looks_like_login_page_chinese_only_login_is_true() -> None:
    """③ 纯中文登录页（可见文本无 login/登录，旧规则漏判）→ True。

    注：``<input type="password">`` 的属性本身含拉丁 ``password``，但旧规则要求
    与 ``login|登录`` **同时**出现；本样本可见文本只有中文，故旧规则返回 False。
    """
    assert "登录" not in CN_LOGIN_HTML and "login" not in CN_LOGIN_HTML.lower()
    assert _looks_like_login_page(CN_LOGIN_HTML) is True


def test_looks_like_login_page_loan_page_is_false() -> None:
    """④ 借阅页（在借/续借字样）→ False。"""
    assert _looks_like_login_page(LOANS_HTML) is False


def test_my_loans_plain_page_not_treated_as_login() -> None:
    """回归：普通页不再误判为登录页，继续走 parse_loans 分支。"""
    auth = FakeAuth(lambda url: FakeResponse(PLAIN_PAGE_WITH_PASSWORD_LINK_HTML, url=url))
    with pytest.raises(ParseError):
        my_loans(auth=auth)


def test_my_loans_chinese_login_page_raises_auth_error() -> None:
    """回归：纯中文登录页现在能正确抛 AuthError。"""
    auth = FakeAuth(lambda url: FakeResponse(CN_LOGIN_HTML, url=url))
    with pytest.raises(AuthError):
        my_loans(auth=auth)