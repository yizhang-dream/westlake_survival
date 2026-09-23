"""图书馆 OPAC（阿法迪 JSP 系统）认证：走 CAS。

实测（2026-09-22）：

- OPAC 首页 ``http://opac.westlake.edu.cn/``（200，静态快照）中"我的图书馆"
  链接指向 ``http://172.16.10.223:8180/opac/cas/casLogin.do`` —— 即 CAS 回调。
- CAS SP 白名单实测：
  - ``http://172.16.10.223:8180/opac/cas/casLogin.do`` → 接受（渲染登录表单）；
  - ``http://opac.westlake.edu.cn/opac/cas/casLogin.do`` → 接受；
  - ``https://opac.westlake.edu.cn/opac/cas/casLogin.do`` → 拒绝
    （"Application Not Authorized to Use CAS"，说明确为白名单且必须 http）。
- 因站点自身使用内网地址回调，本项目取内网地址为 :attr:`SERVICE_URL`，
  并保留公网别名 :data:`OPAC_SERVICE_URL_PUBLIC`。
"""

from __future__ import annotations

from westlake_survival.sso.providers.cas import CASAuthorizer

#: OPAC CAS 回调（站点"我的图书馆"实际使用地址，CAS 白名单内）。
OPAC_SERVICE_URL = "http://172.16.10.223:8180/opac/cas/casLogin.do"

#: 公网别名（CAS 同样接受；校园网内等价）。
OPAC_SERVICE_URL_PUBLIC = "http://opac.westlake.edu.cn/opac/cas/casLogin.do"

#: OPAC 首页。
OPAC_BASE = "http://opac.westlake.edu.cn/"


class LibAuth(CASAuthorizer):
    """图书馆 OPAC 会话（CAS）。"""

    SERVICE_URL = OPAC_SERVICE_URL

    BASE_URL = OPAC_SERVICE_URL


__all__ = ["LibAuth", "OPAC_SERVICE_URL", "OPAC_SERVICE_URL_PUBLIC", "OPAC_BASE"]