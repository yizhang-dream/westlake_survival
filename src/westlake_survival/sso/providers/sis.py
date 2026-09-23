"""SIS（教务，Oracle PeopleSoft）认证。

实测结论（2026-09-22）：**SIS 走 PeopleSoft 本地登录，而非 CAS。**

依据：

- ``GET https://sis.westlake.edu.cn/psc/CSPRD_3/?cmd=login`` 返回 200，
  响应头 ``RespondingWithSignonPage: true``，页面为 PeopleSoft 自带登录表单
  ``<form id="login" method="post" action="?&cmd=login&languageCd=ENG">``，
  字段 ``userid`` / ``pwd`` / ``Submit``，外加隐藏的 ``lcsrf_token`` 等；
- 该请求**没有** 302 到 ``sso.westlake.edu.cn``（若启用 CAS SSO，cmd=login
  会跳转 CAS），故判定为 PS 本地认证；
- 成功标志为 ``PS_TOKEN`` cookie（失败时 ``Set-Cookie: PS_TOKEN=;`` 被清空）。
- 附注：CAS 侧确实接受 ``service=https://sis.westlake.edu.cn/psc/CSPRD_3/``
  （会渲染"学生信息系统"主题登录页），但 SIS 自身并未把 cmd=login 交给 CAS，
  故本项目 SIS 采用 PS 本地表单策略。

因此 :class:`SISAuth` 保留 ``CASAuthorizer`` 的基类身份，但覆写
``_build_session`` / ``_is_stale_response`` 走 PeopleSoft 表单。

2026-09-23 复测：凭据更正后 ``_build_session`` 连续三次真实登录成功
（每次均获得 ``PS_TOKEN``），登录态可直达课表页并完成两段式导出
（见 :mod:`westlake_survival.sis.client` 的实测校准）。
"""

from __future__ import annotations

import re

from westlake_survival._net import AUTH_TIMEOUT
from westlake_survival.exceptions import (
    InvalidCredentials,
    OffCampusError,
    is_offcampus,
)
from westlake_survival.sso.creds import read_credentials
from westlake_survival.sso.providers.cas import CASAuthorizer

#: SIS 根地址。
SIS_BASE = "https://sis.westlake.edu.cn/psc/CSPRD_3/"

#: PS 登录页（GET 渲染表单，POST 提交）。
SIS_LOGIN_URL = "https://sis.westlake.edu.cn/psc/CSPRD_3/?cmd=login&languageCd=ENG"

_INPUT_RE = re.compile(r"<input\b[^>]*>", re.IGNORECASE)
_NAME_RE = re.compile(r'name="([^"]*)"', re.IGNORECASE)
_VALUE_RE = re.compile(r'value="([^"]*)"', re.IGNORECASE)
_TYPE_RE = re.compile(r'type="([^"]*)"', re.IGNORECASE)

_OFFCAMPUS_HINT = (
    "SIS 仅校园网/VPN 内可达，请先连接西湖大学 VPN（https://vpn.westlake.edu.cn/）后重试。"
)


def _hidden_fields(html: str) -> dict[str, str]:
    """从 HTML 中抽取 ``type="hidden"`` 的 input 字段（name -> value）。"""
    fields: dict[str, str] = {}
    for tag in _INPUT_RE.findall(html or ""):
        type_match = _TYPE_RE.search(tag)
        if not type_match or type_match.group(1).lower() != "hidden":
            continue
        name_match = _NAME_RE.search(tag)
        if not name_match:
            continue
        value_match = _VALUE_RE.search(tag)
        fields[name_match.group(1)] = value_match.group(1) if value_match else ""
    return fields


class SISAuth(CASAuthorizer):
    """教务 SIS 会话（PeopleSoft 本地登录）。"""

    #: 名义上的 CAS 服务地址（CAS 接受但 SIS 实际未走 CAS），仅作记录。
    SERVICE_URL = SIS_BASE

    BASE_URL = SIS_BASE

    LOGIN_URL = SIS_LOGIN_URL

    def _build_session(self):
        sid, password = read_credentials()
        session = self._new_session()

        page = session.get(self.LOGIN_URL, timeout=AUTH_TIMEOUT, allow_redirects=True)
        if is_offcampus(page):
            raise OffCampusError(_OFFCAMPUS_HINT)

        data = _hidden_fields(page.text)
        data.update({"userid": sid, "pwd": password, "Submit": "Sign In"})

        response = session.post(
            self.LOGIN_URL, data=data, timeout=AUTH_TIMEOUT, allow_redirects=True
        )
        if is_offcampus(response):
            raise OffCampusError(_OFFCAMPUS_HINT)

        if not session.cookies.get("PS_TOKEN"):
            raise InvalidCredentials("用户名或密码错误（未获得 PS_TOKEN）。")
        return session

    def _is_stale_response(self, response) -> bool:
        final_url = getattr(response, "url", "") or ""
        if "cmd=login" in final_url:
            return True
        body = getattr(response, "text", "") or ""
        if 'name="pwd"' in body and "cmd=login" in body:
            return True
        return super()._is_stale_response(response)

    def check(self) -> bool:
        if self._session is None:
            return False
        if not self._session.cookies.get("PS_TOKEN"):
            return False
        try:
            response = self._session.get(
                self.BASE_URL, timeout=AUTH_TIMEOUT, allow_redirects=True
            )
        except Exception:  # noqa: BLE001 - 网络异常一律视为无效
            return False
        return not self._is_stale_response(response)


__all__ = ["SISAuth", "SIS_BASE", "SIS_LOGIN_URL"]