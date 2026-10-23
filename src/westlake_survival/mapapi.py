"""西湖大学电子地图系统（``map.westlake.edu.cn``）的账号与接口会话。

为什么单列一个模块
==================
主站地图功能（见 :mod:`westlake_survival.campusmap`）只用公开数据；楼宇/教室
级 POI 只在电子地图系统里，需要本校账号。该系统是**独立的本地账号体系**
（2026-10-23 实测：``nd.auth.loginType=1``、``nd.auth.thirdLoginOpen=false``、
``ssoAutoRedirect=false``），与教务 SIS 账号不同源——拿 SIS 密码登录会得到
``{"code":"20001","msg":"用户名或密码错误"}``。

一次配置、长期可用
==================
凭据按四级优先级读取（内存 > 环境变量 > 钥匙串 > 配置文件），与
:mod:`westlake_survival.sso.creds` 同口径但**独立命名空间**，避免覆盖教务账号：

1. 进程内 ``map_cred_set(user, password)``；
2. 环境变量 ``WESTLAKE_MAP_CREDENTIALS='账号:密码'``；
3. 系统钥匙串 ``service=westlake_survival_map``（需 ``[secure]``）；
4. 配置文件 ``~/.westlake_survival/map_credentials.txt``（``账号:密码``，写时尽力 0600）。

登录成功后把令牌缓存在 ``~/.westlake_survival/map_token.json``（含过期时间），
后续请求直接复用；过期或服务端判无效时自动用已存凭据重新登录一次。

请求头
======
匿名与登录请求都必须带三个头（2026-10-23 实测，缺一即返回
``10041 非法的客户端``）：

* ``ql-auth-nonce``：32 位大写十六进制随机串（每次请求新建，无需签名）；
* ``ql-auth-timestamp``：Unix 秒；
* ``ql-client-id``：``10``。

本模块不复用 ``requests.Session`` 的 Cookie 语义：令牌走 ``Authorization`` 头。
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

import requests

from westlake_survival._cache import config_root
from westlake_survival._net import DEFAULT_TIMEOUT, http_session
from westlake_survival.exceptions import AuthError, ParseError, WestlakeError

__all__ = [
    "BASE_URL",
    "CLIENT_ID",
    "ENV_VAR",
    "KEYRING_SERVICE",
    "CRED_FILENAME",
    "TOKEN_FILENAME",
    "MapToken",
    "map_cred_set",
    "map_cred_clear",
    "map_cred_status",
    "ping",
    "save_map_credentials",
    "load_map_credentials",
    "delete_map_credentials",
    "login",
    "MapClient",
]

logger = logging.getLogger(__name__)

#: 电子地图系统根地址。
BASE_URL = "https://map.westlake.edu.cn"

#: 固定的客户端 id（前端写死，缺了会被判「非法的客户端」）。
CLIENT_ID = "10"

#: 环境变量名，格式 ``账号:密码``。
ENV_VAR = "WESTLAKE_MAP_CREDENTIALS"

#: 钥匙串 service 名（与教务账号的 ``westlake_survival`` 分开）。
KEYRING_SERVICE = "westlake_survival_map"

#: 凭据配置文件名（相对配置根目录）。
CRED_FILENAME = "map_credentials.txt"

#: 令牌缓存文件名（相对配置根目录）。
TOKEN_FILENAME = "map_token.json"

#: 进程内凭据。
_MEMORY: dict[str, str] = {}

#: 登录失败码 → 中文说明（实测 20001 为账号密码错误）。
_LOGIN_MESSAGES = {
    "20001": "账号或密码错误（地图系统是独立账号，与教务 SIS 密码不同源）",
    "20002": "账号不存在（地图系统是独立账号，需向学校开通）",
    "10041": "客户端头缺失或被拒（ql-auth-nonce / ql-auth-timestamp / ql-client-id）",
}


# --------------------------------------------------------------------------- #
# 凭据四级来源
# --------------------------------------------------------------------------- #
def cred_path() -> Path:
    """凭据配置文件路径。"""
    return config_root() / CRED_FILENAME


def token_path() -> Path:
    """令牌缓存文件路径。"""
    return config_root() / TOKEN_FILENAME


def map_cred_set(user: str, password: str) -> None:
    """把凭据放进进程内存（最高优先级，退出即丢失）。"""
    _MEMORY["user"] = user
    _MEMORY["password"] = password


def map_cred_clear() -> None:
    """清除内存凭据。"""
    _MEMORY.clear()


def save_map_credentials(user: str, password: str) -> bool:
    """保存凭据：优先钥匙串，失败则写 ``map_credentials.txt``（尽力 0600）。

    Returns:
        ``True`` 表示写进钥匙串，``False`` 表示写到文件。
    """
    try:
        import keyring

        keyring.set_password(KEYRING_SERVICE, user, password)
        keyring.set_password(KEYRING_SERVICE, "__user__", user)
        return True
    except Exception:
        logger.debug("钥匙串不可用，回退配置文件", exc_info=True)
    path = cred_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{user}:{password}", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        logger.debug("设置凭据文件权限失败", exc_info=True)
    return False


def delete_map_credentials() -> None:
    """清除钥匙串与配置文件里的地图凭据（含令牌缓存）。"""
    try:
        import keyring

        user = keyring.get_password(KEYRING_SERVICE, "__user__")
        if user:
            keyring.delete_password(KEYRING_SERVICE, user)
        keyring.delete_password(KEYRING_SERVICE, "__user__")
    except Exception:
        logger.debug("清除钥匙串凭据失败", exc_info=True)
    for path in (cred_path(), token_path()):
        try:
            if path.exists():
                path.unlink()
        except OSError:
            logger.debug("删除 %s 失败", path, exc_info=True)


def load_map_credentials() -> tuple[str, str] | None:
    """按优先级读取 ``(user, password)``；都没有返回 ``None``。"""
    if _MEMORY.get("user") and _MEMORY.get("password"):
        return _MEMORY["user"], _MEMORY["password"]
    raw = os.environ.get(ENV_VAR, "").strip()
    if raw and ":" in raw:
        user, _, password = raw.partition(":")
        if user and password:
            return user, password
    try:
        import keyring

        user = keyring.get_password(KEYRING_SERVICE, "__user__")
        if user:
            password = keyring.get_password(KEYRING_SERVICE, user)
            if password:
                return user, password
    except Exception:
        logger.debug("读取钥匙串凭据失败", exc_info=True)
    path = cred_path()
    if path.exists():
        try:
            raw = path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if ":" in raw:
            user, _, password = raw.partition(":")
            if user and password:
                return user, password
    return None


def map_cred_status() -> dict[str, object]:
    """只报来源有无与令牌状态，**不回显任何凭据**。"""
    sources = {
        "内存": bool(_MEMORY.get("user")),
        "环境变量 " + ENV_VAR: bool(os.environ.get(ENV_VAR, "").strip()),
        "keyring": False,
        "配置文件 " + str(cred_path()): cred_path().exists(),
    }
    try:
        import keyring

        sources["keyring"] = bool(keyring.get_password(KEYRING_SERVICE, "__user__"))
    except Exception:
        logger.debug("查询钥匙串失败", exc_info=True)
    token = _load_token()
    return {
        "sources": sources,
        "has_credentials": bool(load_map_credentials()),
        "token_valid": bool(token and not token.expired),
        "token_expires_at": token.expires_at.isoformat(sep=" ") if token else None,
    }


# --------------------------------------------------------------------------- #
# 令牌
# --------------------------------------------------------------------------- #
@dataclass
class MapToken:
    """会话令牌与其过期时间。"""

    access_token: str
    refresh_token: str = ""
    expires_at: float = 0.0

    @property
    def expired(self) -> bool:
        """是否已过期（留 60 秒余量）。"""
        return not self.access_token or (self.expires_at and time.time() >= self.expires_at - 60)


def _load_token() -> MapToken | None:
    """读取令牌缓存。"""
    path = token_path()
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict) or not raw.get("access_token"):
        return None
    return MapToken(
        access_token=str(raw["access_token"]),
        refresh_token=str(raw.get("refresh_token") or ""),
        expires_at=float(raw.get("expires_at") or 0),
    )


def _save_token(token: MapToken) -> None:
    """写令牌缓存（尽力 0600）。"""
    path = token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "access_token": token.access_token,
                "refresh_token": token.refresh_token,
                "expires_at": token.expires_at,
            }
        ),
        encoding="utf-8",
    )
    try:
        os.chmod(path, 0o600)
    except OSError:
        logger.debug("设置令牌文件权限失败", exc_info=True)


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
def _auth_headers() -> dict[str, str]:
    """构造三个必需头（nonce 每次新建，无需签名）。"""
    return {
        "ql-auth-nonce": secrets.token_hex(16).upper(),
        "ql-auth-timestamp": str(int(time.time())),
        "ql-client-id": CLIENT_ID,
    }


def _decode(response: requests.Response, url: str) -> dict:
    """解析统一 JSON 信封 ``{code, msg, data}``。"""
    try:
        payload = json.loads(response.content.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ParseError(f"电子地图接口返回非 JSON：{url}") from exc
    if not isinstance(payload, dict):
        raise ParseError(f"电子地图接口返回结构异常：{url}")
    return payload


def ping(*, session: requests.Session | None = None, timeout: float | None = None) -> str:
    """匿名调用配置接口，验证三个必需头是否被服务端接受。

    返回系统名（如「西湖大学电子地图系统」）。这个接口不需要账号，用它可以把
    「请求头构造对不对」与「账号对不对」分开定位。

    Raises:
        WestlakeError: 网络层失败或服务端返回非成功码。
        ParseError: 响应不是约定 JSON。
    """
    session = session if session is not None else http_session()
    url = BASE_URL + "/api/nsc/uc/ndConfig/findNdConfigListByKeys"
    try:
        response = session.post(
            url,
            json={"confKeyList": ["nd.sys.name"]},
            headers={"Content-Type": "application/json", **_auth_headers()},
            timeout=timeout if timeout is not None else DEFAULT_TIMEOUT,
        )
    except requests.Timeout as exc:
        raise WestlakeError("电子地图配置接口超时") from exc
    except requests.RequestException as exc:
        raise WestlakeError(f"电子地图配置接口请求失败：{exc}") from exc
    payload = _decode(response, url)
    if str(payload.get("code")) not in ("10000", "0", "200"):
        raise WestlakeError(
            f"电子地图配置接口返回 {payload.get('code')}：{payload.get('msg') or ''}"
        )
    for item in payload.get("data") or []:
        if isinstance(item, dict) and item.get("confKey") == "nd.sys.name":
            return str(item.get("confVal") or "")
    return ""


def login(
    user: str,
    password: str,
    *,
    session: requests.Session | None = None,
    timeout: float | None = None,
) -> MapToken:
    """登录并返回令牌。

    请求体是**表单**（``userName``/``password``/``catalog``/``requestType``/
    ``verifyCodeToken``/``authCode``），实测于 2026-10-23。

    Raises:
        AuthError: 账号或密码错误（``20001``）等服务端拒绝。
        WestlakeError: 网络层失败。
        ParseError: 响应不是约定 JSON。
    """
    session = session if session is not None else http_session()
    url = BASE_URL + "/api/nsc/auth/login"
    body = urlencode(
        {
            "userName": user,
            "password": password,
            "catalog": CLIENT_ID,
            "requestType": "web",
            "verifyCodeToken": "null",
            "authCode": "null",
        }
    )
    headers = {"Content-Type": "application/x-www-form-urlencoded", **_auth_headers()}
    try:
        response = session.post(
            url,
            data=body,
            headers=headers,
            timeout=timeout if timeout is not None else DEFAULT_TIMEOUT,
        )
    except requests.Timeout as exc:
        raise WestlakeError("电子地图登录请求超时") from exc
    except requests.RequestException as exc:
        raise WestlakeError(f"电子地图登录请求失败：{exc}") from exc
    payload = _decode(response, url)
    code = str(payload.get("code") or "")
    if code not in ("10000", "0", "200"):
        message = _LOGIN_MESSAGES.get(code) or str(payload.get("msg") or "登录失败")
        raise AuthError(f"电子地图登录失败（{code}）：{message}")
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        raise ParseError("电子地图登录响应缺少 data 对象")
    access = str(data.get("access_token") or data.get("accessToken") or data.get("token") or "")
    if not access:
        raise ParseError("电子地图登录响应里没有令牌字段")
    expires_in = data.get("expires_in") or data.get("expiresIn") or 0
    try:
        expires_at = time.time() + float(expires_in)
    except (TypeError, ValueError):
        expires_at = time.time() + 3600
    return MapToken(
        access_token=access,
        refresh_token=str(data.get("refresh_token") or data.get("refreshToken") or ""),
        expires_at=expires_at,
    )


class MapClient:
    """带令牌的接口客户端：一次登录，后续自动复用与续期。"""

    def __init__(self, session: requests.Session | None = None, timeout: float | None = None) -> None:
        self._session = session if session is not None else http_session()
        self._timeout = timeout if timeout is not None else DEFAULT_TIMEOUT
        self._token: MapToken | None = _load_token()

    @property
    def token(self) -> MapToken | None:
        """当前令牌（可能为空）。"""
        return self._token

    def ensure_token(self) -> MapToken:
        """确保有可用令牌：缓存有效则复用，否则用已存凭据登录一次。"""
        if self._token and not self._token.expired:
            return self._token
        credentials = load_map_credentials()
        if not credentials:
            raise AuthError(
                "电子地图需要本校账号（与教务不同源）。先执行一次 `westlake map login` 配置。"
            )
        user, password = credentials
        self._token = login(user, password, session=self._session, timeout=self._timeout)
        _save_token(self._token)
        return self._token

    def post(self, path: str, payload: dict | None = None) -> dict:
        """向 ``/api/nsc/...`` 发 POST，返回信封里的 ``data``。

        令牌失效（服务端判无效）时自动重登一次。
        """
        return self._post(path, payload, retry=True)

    def _post(self, path: str, payload: dict | None, *, retry: bool) -> dict:
        token = self.ensure_token()
        url = BASE_URL + path
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token.access_token}",
            **_auth_headers(),
        }
        try:
            response = self._session.post(
                url,
                json=payload if payload is not None else {},
                headers=headers,
                timeout=self._timeout,
            )
        except requests.Timeout as exc:
            raise WestlakeError(f"电子地图接口超时：{path}") from exc
        except requests.RequestException as exc:
            raise WestlakeError(f"电子地图接口请求失败：{exc}") from exc
        result = _decode(response, url)
        code = str(result.get("code") or "")
        if code in ("4002", "4006", "4009", "403") and retry:
            self._token = None
            return self._post(path, payload, retry=False)
        if code not in ("10000", "0", "200"):
            raise WestlakeError(f"电子地图接口返回 {code}：{result.get('msg') or ''}")
        return result.get("data") or {}
