"""CAS（Apereo CAS 6.x）认证：统一登录入口。

实测（2026-09-22，西湖大学 sso.westlake.edu.cn）：

- 登录页 ``GET /cas/login?service=...`` 返回表单
  ``<form id="loginForm" class="loginForm" method="post">``（**无 action**，
  即 POST 回当前带 ``?service=`` 的 URL）。
- 隐藏字段 ``execution``（JWT webflow token，正则
  ``name="execution"\\s+value="([^"]+)"`` 命中）、``_eventId=submit``、
  ``geolocation``；可见字段 ``username`` / ``password`` / ``rememberMe``。
- 密码**无前端加密**，明文 POST 走 TLS。
- ``POST`` 成功返回 302，``Location`` 带 ``ticket=ST-...``；凭据错误则
  302 回登录页（无 ticket）或 200 重渲染表单。
- CAS 有 SP 白名单：``service`` 必须是已注册应用。
"""

from __future__ import annotations

import re
from urllib.parse import quote, urljoin

from westlake_survival._net import AUTH_TIMEOUT
from westlake_survival.exceptions import (
    AuthError,
    InvalidCredentials,
    OffCampusError,
    is_offcampus,
)
from westlake_survival.sso.authorizer import Authorizer
from westlake_survival.sso.creds import read_credentials

#: CAS 登录页地址。
CAS_LOGIN = "https://sso.westlake.edu.cn/cas/login"

#: 抓取 ``execution`` 隐藏字段（属性间允许任意空白）。
_EXECUTION_RE = re.compile(r'name="execution"\s+value="([^"]+)"')

#: 判定响应体是否为 CAS 登录页（用于识别"凭据错误、重渲染表单"）。
_LOGIN_FORM_MARKER = 'name="execution"'

#: 校外访问提示。
_OFFCAMPUS_HINT = (
    "统一认证页不可达或拒绝访问，可能处于校外网络，请先连接西湖大学 VPN"
    "（https://vpn.westlake.edu.cn/）后重试。"
)


class CASAuthorizer(Authorizer):
    """基于 Apereo CAS 的服务认证器基类。

    子类只需覆写 :attr:`SERVICE_URL` 为已注册的 SP 回调地址。
    """

    #: 已注册的 SP 服务地址（CAS 白名单内），子类必须覆写。
    SERVICE_URL: str = ""

    #: CAS 登录页地址（子类一般不改）。
    CAS_LOGIN: str = CAS_LOGIN

    def login_url(self) -> str:
        """返回带 ``service`` 参数的 CAS 登录页地址。"""
        if not self.SERVICE_URL:
            raise AuthError(f"{type(self).__name__} 未设置 SERVICE_URL")
        return f"{self.CAS_LOGIN}?service={quote(self.SERVICE_URL, safe='')}"

    # ---------------------------------------------------------------- 登录

    def _build_session(self):
        sid, password = read_credentials()
        session = self._new_session()
        login_url = self.login_url()

        page = session.get(login_url, timeout=AUTH_TIMEOUT)
        if is_offcampus(page):
            raise OffCampusError(_OFFCAMPUS_HINT)
        match = _EXECUTION_RE.search(page.text or "")
        if not match:
            raise AuthError(
                "CAS 登录页结构变化：未找到 execution 字段（可能被重定向或服务未授权）。"
            )
        execution = match.group(1)

        data = {
            "username": sid,
            "password": password,
            "execution": execution,
            "_eventId": "submit",
            "geolocation": "",
        }
        response = session.post(
            login_url, data=data, timeout=AUTH_TIMEOUT, allow_redirects=False
        )

        status = response.status_code
        if status in (301, 302, 303, 307, 308):
            location = response.headers.get("Location", "") or ""
            if "ticket=" in location:
                # 兑换服务会话（拿到目标站点 cookie）。
                session.get(
                    urljoin(login_url, location),
                    timeout=AUTH_TIMEOUT,
                    allow_redirects=True,
                )
                return session
            # 无 ticket 的跳转 = 被打回登录页（通常是凭据错误）。
            raise InvalidCredentials("用户名或密码错误（CAS 未下发 ticket）。")

        if status == 200 and _LOGIN_FORM_MARKER in (response.text or ""):
            raise InvalidCredentials("用户名或密码错误（CAS 重渲染登录表单）。")

        raise AuthError(f"CAS 登录返回未预期的状态码 {status}。")


__all__ = ["CASAuthorizer", "CAS_LOGIN"]