"""live 测试：仅对真实站点做 GET 探测，默认被 ``-m 'not live'`` 排除。

运行：``.venv/Scripts/python -m pytest src/test/sso -q -m live``
"""

from __future__ import annotations

import pytest

from westlake_survival._net import http_session
from westlake_survival.sso.providers.cas import CAS_LOGIN, _EXECUTION_RE

SIS_SERVICE = "https://sis.westlake.edu.cn/psc/CSPRD_3/"


@pytest.mark.live
def test_real_cas_login_page_has_execution():
    """GET 真实 CAS 登录页，断言 execution 正则命中。"""
    session = http_session()
    response = session.get(
        CAS_LOGIN, params={"service": SIS_SERVICE}, timeout=20, allow_redirects=True
    )
    assert response.status_code == 200, response.status_code
    match = _EXECUTION_RE.search(response.text)
    assert match is not None, "execution 正则未命中真实 CAS 登录页"
    assert match.group(1), "execution 值为空"
    # 表单字段核对。
    assert 'name="username"' in response.text
    assert 'name="password"' in response.text
    assert 'name="_eventId"' in response.text
    print(f"\n[live] CAS execution={match.group(1)[:24]}... 页面长度={len(response.text)}")