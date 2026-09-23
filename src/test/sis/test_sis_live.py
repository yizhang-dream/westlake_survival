"""真实网络探测（``@pytest.mark.live``，默认被 ``-m 'not live'`` 排除）。

只做**匿名 GET**：SIS 课表页未登录会 302 到 ``?cmd=login``（或 ckreq）。
固化这一现状，便于日后检测 SIS 登录方式是否变化。**不登录、不发凭据。**

运行：``pytest src/test/sis -q -m live``
"""

from __future__ import annotations

import pytest

from westlake_survival._net import http_session
from westlake_survival.sis.client import SIS_URLS

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def http():
    session = http_session()
    try:
        session.get(SIS_URLS["base"], timeout=20, allow_redirects=False)
    except Exception as exc:  # pragma: no cover - 需要校园网
        pytest.skip(f"无法访问 SIS（需校园网/VPN）：{exc}")
    return session


def test_schedule_page_redirects_to_login_when_anonymous(http):
    response = http.get(SIS_URLS["schedule_page"], timeout=20, allow_redirects=False)
    assert response.status_code in (301, 302, 303, 307, 308), response.status_code
    location = response.headers.get("Location", "")
    assert "cmd=login" in location or "ckreq" in location, location


def test_schedule_page_menu_redirects_to_login_when_anonymous(http):
    response = http.get(SIS_URLS["schedule_page_menu"], timeout=20, allow_redirects=False)
    assert response.status_code in (301, 302, 303, 307, 308), response.status_code


def test_schedule_page_followed_lands_on_login_page(http):
    response = http.get(SIS_URLS["schedule_page"], timeout=20, allow_redirects=True)
    assert response.status_code == 200
    assert "cmd=login" in response.url or "ckreq" in response.url
    # PeopleSoft 登录表单特征。
    assert 'name="pwd"' in response.text