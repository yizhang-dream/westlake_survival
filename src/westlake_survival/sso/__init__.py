"""sso — 西湖大学统一身份认证。

对外公开：认证器基类 :class:`Authorizer`、CAS 基类 :class:`CASAuthorizer`、
三个服务子类（:class:`SISAuth` / :class:`LibAuth` / :class:`CanvasAuth`）、
凭据工具与 :func:`require_auth` 装饰器。

会话只在内存，凭据不落盘（可选系统钥匙串与配置文件除外，见
:mod:`westlake_survival.sso.creds`）。
"""

from __future__ import annotations

from westlake_survival.exceptions import (
    AuthError,
    InvalidCredentials,
    OffCampusError,
    SessionExpired,
)
from westlake_survival.sso.authorizer import Authorizer, require_auth
from westlake_survival.sso.creds import (
    cred_clear,
    cred_path,
    cred_set,
    delete_credentials_keyring,
    keyring_available,
    read_credentials,
    read_credentials_keyring,
    save_credentials_keyring,
    write_credentials,
)
from westlake_survival.sso.providers import (
    CAS_LOGIN,
    CASAuthorizer,
    CanvasAuth,
    LibAuth,
    SISAuth,
)

__all__ = [
    # 认证器
    "Authorizer",
    "CASAuthorizer",
    "SISAuth",
    "LibAuth",
    "CanvasAuth",
    "require_auth",
    # 凭据
    "cred_set",
    "cred_clear",
    "read_credentials",
    "write_credentials",
    "cred_path",
    "keyring_available",
    "save_credentials_keyring",
    "read_credentials_keyring",
    "delete_credentials_keyring",
    # 常量
    "CAS_LOGIN",
    # 异常（便于调用方只 import 本模块）
    "AuthError",
    "InvalidCredentials",
    "SessionExpired",
    "OffCampusError",
]