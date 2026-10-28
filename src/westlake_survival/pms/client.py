"""联创自助文印（PMS）REST 客户端。

目标系统：西湖大学图书馆自助文印控制器
``http://print.lib.westlake.edu.cn:9130``（联创 UniOpm「云打印」）。

背景与探测结论（2026-09-22 实测，详见同目录 ``api_notes.md``）：

- 控制器自带 API 文档页 ``/api.html``，但它只是一个 JS 壳：真正的文档由
  ``GET /api/system/Help/Get`` 返回的 HTML 渲染（实测 200，约 360 KB，
  覆盖 client / selfservice / admin / system 四个模块、32 个控制器、711 个
  动作）。
- **URL 里的控制器名是短名**：文档写
  ``api/client/server.controller.client.PrintJobController/Get``，实际路由是
  ``/api/client/PrintJob/Get``（前缀 ``/api`` 来自前端 ``js/host.js`` 的
  ``var host = "/api"``）。本模块只使用实测可路由的短名。
- 所有响应统一包一层信封 ``{"code": 0, "message": "", "result": ...}``；
  ``code == 0`` 成功，``code == 4`` 表示「无效会话，未登录」。
- 认证流程（对照前端 ``js/login.js``）::

      GET  /api/client/Auth/PublicKey     -> result.publicKey / result.nonceStr
      POST /api/client/Auth/GetAuthToken  -> 顶层 szToken
      POST /api/client/Auth/Login         body {szLogonName, szPassword, szToken}

  其中 ``szPassword`` 是 **RSA(PKCS#1 v1.5)** 加密后的 base64（明文是
  ``password + ";" + nonceStr``）。本模块用纯标准库实现该加密（见
  :func:`encrypt_password`），不引入新的第三方依赖。
- 后续请求靠 ``requests.Session`` 持有的会话 Cookie 维持登录态，因此所有
  请求都走同一个 Session 实例。

安全约定：凭据只在构造/登录时读入内存，绝不写日志、绝不落盘；涉及一卡通
扣费的接口（:mod:`PayController`）只做封装，调用前请先读 docstring 警告。
"""

from __future__ import annotations

import base64
import os
import secrets
from pathlib import Path
from typing import Any, Iterable, Mapping

import requests

from westlake_survival._net import AUTH_TIMEOUT, DEFAULT_TIMEOUT, http_session
from westlake_survival.exceptions import (
    ActionError,
    AuthError,
    InvalidCredentials,
    NotFound,
    OffCampusError,
    ParseError,
    SessionExpired,
    WestlakeError,
    is_offcampus,
)
from westlake_survival.pms.models import (
    Paper,
    PrintJob,
    ScanJob,
    Station,
    UsagePage,
    UsageRecord,
    UsageSummary,
)

#: 打印控制器根地址；测试/换环境可用 ``WESTLAKE_PMS_BASE`` 环境变量覆盖。
PMS_BASE = "http://print.lib.westlake.edu.cn:9130"

#: 覆盖根地址的环境变量名。
BASE_ENV_VAR = "WESTLAKE_PMS_BASE"

#: 信封里的成功码。
CODE_OK = 0

#: 信封里的「无效会话，未登录」码（实测）。
CODE_NOT_LOGGED_IN = 4

#: 单个 PUT/POST 上传文件的分块大小（字节）。
UPLOAD_CHUNK_SIZE = 8192

#: 错误消息里附带响应体长度上限。
_ERROR_BODY_LIMIT = 200

#: ``CloudPrint/Upload`` 表达「跟随网点纸盒设置」的 ``dwPaperId`` 哨兵值。
PAPER_AUTO = -1

_ENDPOINT = "/api/client"

# 控制器名（实测短名）——集中定义，便于对照 api_notes.md。
_AUTH = f"{_ENDPOINT}/Auth"
_STATION = f"{_ENDPOINT}/Station"
_PAPER = f"{_ENDPOINT}/Paper"
_PRINTJOB = f"{_ENDPOINT}/PrintJob"
_SCAN = f"{_ENDPOINT}/Scan"
_REPORT = f"{_ENDPOINT}/Report"
_PAY = f"{_ENDPOINT}/Pay"
_FEESTD = f"{_ENDPOINT}/FeeStd"
_CLOUD = f"{_ENDPOINT}/CloudPrint"

# --------------------------------------------------------------------------
# 凭据读取（对 sso 模块做惰性导入，避免并行开发期的硬依赖）
# --------------------------------------------------------------------------

try:  # pragma: no cover - 正常环境走这一支
    from westlake_survival.sso import read_credentials as _read_credentials
except Exception:  # pragma: no cover - sso 未完成/导入失败时降级
    _read_credentials = None  # type: ignore[assignment]

_CRED_HELP = (
    "没有可用的文印系统凭据。请任选一种方式提供（优先级从高到低）：\n"
    "  1) 显式传入 PMSClient(username=..., password=...)\n"
    "  2) 进程内：westlake_survival.sso.cred_set(sid, password)\n"
    "  3) 环境变量：export WESTLAKE_CREDENTIALS='学号:密码'\n"
    "  4) 配置文件：westlake_survival.sso.write_credentials(sid, password)"
)


def default_credentials() -> tuple[str, str]:
    """按 sso 的三级优先级读取 ``(sid, password)``。

    ``westlake_survival.sso`` 未就绪时延迟导入；仍失败则抛
    :class:`~westlake_survival.exceptions.AuthError`。
    """
    global _read_credentials
    if _read_credentials is None:
        try:
            from westlake_survival.sso import read_credentials as fn
        except Exception as exc:  # pragma: no cover - 防御性
            raise AuthError(
                "无法从 westlake_survival.sso 导入 read_credentials，且未显式提供凭据。\n"
                f"{_CRED_HELP}"
            ) from exc
        _read_credentials = fn
    return _read_credentials()


def resolve_base_url() -> str:
    """返回控制器根地址，优先取环境变量 ``WESTLAKE_PMS_BASE``。"""
    return (os.environ.get(BASE_ENV_VAR) or PMS_BASE).rstrip("/")


# --------------------------------------------------------------------------
# 纯标准库 RSA(PKCS#1 v1.5) 加密：用于登录时的密码字段
# --------------------------------------------------------------------------


def _der_read(data: bytes, offset: int) -> tuple[int, bytes, int]:
    """读一个 DER TLV：返回 ``(tag, value_bytes, next_offset)``。"""
    if offset + 2 > len(data):
        raise ValueError("DER 数据不完整")
    tag = data[offset]
    offset += 1
    length = data[offset]
    offset += 1
    if length & 0x80:
        count = length & 0x7F
        if count == 0 or offset + count > len(data):
            raise ValueError("DER 长度域非法")
        length = int.from_bytes(data[offset : offset + count], "big")
        offset += count
    if offset + length > len(data):
        raise ValueError("DER 值域越界")
    return tag, data[offset : offset + length], offset + length


def rsa_public_numbers(public_key_b64: str) -> tuple[int, int]:
    """从 base64 的 **X.509 SubjectPublicKeyInfo** 里取出 RSA ``(n, e)``。

    只解析非加密的 PKCS#1 RSAPublicKey 结构，不依赖任何第三方库。
    """
    try:
        der = base64.b64decode(public_key_b64, validate=False)
    except Exception as exc:  # pragma: no cover - 防御性
        raise ValueError("公钥不是合法 base64") from exc
    tag, seq, _ = _der_read(der, 0)
    if tag != 0x30:
        raise ValueError("公钥外层不是 SEQUENCE")
    t_alg, _alg, off = _der_read(seq, 0)
    t_bits, bits, _ = _der_read(seq, off)
    if t_alg != 0x30:
        raise ValueError("AlgorithmIdentifier 结构异常")
    if t_bits != 0x03:
        raise ValueError("缺少 BIT STRING")
    inner = bits[1:] if bits[:1] == b"\x00" else bits  # 去掉 unused-bits 字节
    t_rsa, rsa_seq, _ = _der_read(inner, 0)
    if t_rsa != 0x30:
        raise ValueError("RSAPublicKey 结构异常")
    t_n, n_bytes, off = _der_read(rsa_seq, 0)
    t_e, e_bytes, _ = _der_read(rsa_seq, off)
    if t_n != 0x02 or t_e != 0x02:
        raise ValueError("RSAPublicKey 缺少 INTEGER 字段")
    return int.from_bytes(n_bytes, "big"), int.from_bytes(e_bytes, "big")


def encrypt_password(password: str, public_key_b64: str, nonce: str) -> str:
    """按前端口径加密登录密码：``RSA(password + ";" + nonce)``。

    Returns:
        base64 编码的 RSAES-PKCS1-v1_5 密文（长度等于模长）。
    """
    n, e = rsa_public_numbers(public_key_b64)
    message = f"{password};{nonce}".encode("utf-8")
    size = (n.bit_length() + 7) // 8
    if len(message) > size - 11:
        raise ValueError(f"明文过长（{len(message)} 字节），该公钥最多支持 {size - 11} 字节")
    pad_len = size - 3 - len(message)
    # PS 必须是 pad_len 个非零随机字节。
    padding = bytes(secrets.randbelow(255) + 1 for _ in range(pad_len))
    block = b"\x00\x02" + padding + b"\x00" + message
    cipher = pow(int.from_bytes(block, "big"), e, n)
    return base64.b64encode(cipher.to_bytes(size, "big")).decode("ascii")


# --------------------------------------------------------------------------
# 客户端
# --------------------------------------------------------------------------


class PMSClient:
    """西湖大学自助文印系统客户端。

    Args:
        username: 学号/账号；``None`` 时延后到登录时按 :func:`default_credentials`
            解析（参数 > sso 三级优先级）。
        password: 密码；同上。
        session: 可注入的 :class:`requests.Session`（测试用）。
        base_url: 覆盖控制器根地址（测试用）。

    构造时**不发任何请求**，也**不强制要求凭据**——只读接口（网点、纸型、
    公共信息）无需登录即可调用；需要登录的动作会按需读取凭据。
    """

    def __init__(
        self,
        username: str | None = None,
        password: str | None = None,
        *,
        session: requests.Session | None = None,
        base_url: str | None = None,
    ) -> None:
        self._username = username
        self._password = password
        self._session = session if session is not None else http_session()
        self.base_url = (base_url or resolve_base_url()).rstrip("/")
        self._user: dict[str, Any] | None = None
        self._session_id: str | None = None
        # 自动重登的失败缓存：登录被服务端拒绝（密码错误）后记住原因，
        # 后续会话过期不再反复撞密码（防风控）；显式 login() 成功即清除。
        self._auto_login_blocked: str | None = None

    # -- 小工具 ---------------------------------------------------------
    @property
    def session(self) -> requests.Session:
        """底层 :class:`requests.Session`（只读，供高级用法复用 Cookie）。"""
        return self._session

    @property
    def user(self) -> dict[str, Any] | None:
        """最近一次 ``Check`` / ``Login`` 拿到的原始用户信息字典。"""
        return self._user

    @property
    def session_id(self) -> str | None:
        """服务端返回的 ``SessionId``（若信封里带）。"""
        return self._session_id

    @property
    def is_logged_in(self) -> bool:
        """是否已经拿到过用户信息（不代表会话一定仍有效）。"""
        return self._user is not None

    def _url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        return f"{self.base_url}{path if path.startswith('/') else '/' + path}"

    @staticmethod
    def _text(response: requests.Response) -> str:
        try:
            return response.text or ""
        except Exception:  # pragma: no cover - 防御性
            return ""

    def _check_http(self, response: requests.Response, context: str) -> None:
        """把非 2xx 响应映射为本库异常。"""
        status = response.status_code
        if 200 <= status < 300:
            return
        if status == 403 and is_offcampus(response):
            raise OffCampusError(f"{context} 被拒绝：需要校园网/VPN（HTTP 403）")
        snippet = self._text(response)[:_ERROR_BODY_LIMIT]
        if status == 404:
            raise NotFound(f"{context} 不存在（HTTP 404）：{snippet}")
        if status in (401, 403):
            raise AuthError(f"{context} 认证失败（HTTP {status}）：{snippet}")
        raise WestlakeError(f"{context} 请求失败（HTTP {status}）：{snippet}")

    def _json(self, response: requests.Response, context: str) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            snippet = self._text(response)[:_ERROR_BODY_LIMIT]
            raise ParseError(f"{context} 返回内容不是合法 JSON：{snippet}") from exc

    def _result(self, payload: Any, context: str) -> Any:
        """解信封：``code == 0`` 返回 ``result``，否则抛对应异常。"""
        if not isinstance(payload, Mapping):
            raise ParseError(f"{context} 返回内容不是 JSON 对象：{type(payload).__name__}")
        if "code" not in payload:
            raise ParseError(f"{context} 返回内容缺少 code 字段")
        code = payload.get("code")
        message = payload.get("message") or ""
        if code == CODE_OK:
            return payload.get("result")
        if code == CODE_NOT_LOGGED_IN:
            raise SessionExpired(f"{context}：{message or '无效会话，未登录'}")
        raise ActionError(f"{context} 被拒绝（code={code}）：{message or '未知错误'}")

    def _send(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        data: Mapping[str, Any] | None = None,
        files: Any = None,
        timeout: float | None = None,
        context: str | None = None,
        _allow_relogin: bool = True,
    ) -> Any:
        """发一次请求并返回解信封后的 ``result``。

        会话过期（``code == 4``）时自动重登一次并重试；登录被拒
        （密码错误等）则带原因抛出，并缓存失败、不再重试。
        """
        label = context or f"{method} {path}"
        try:
            response = self._session.request(
                method,
                self._url(path),
                params=dict(params) if params else None,
                json=json_body,
                data=dict(data) if data else None,
                files=files,
                timeout=timeout if timeout is not None else DEFAULT_TIMEOUT,
            )
        except requests.ConnectionError as exc:
            raise OffCampusError(
                f"{label} 连接失败：{self.base_url} 仅校园网/VPN 内可达，"
                "请先连接学校 VPN 后重试。"
            ) from exc
        except requests.Timeout as exc:
            raise WestlakeError(f"{label} 请求超时（{timeout or DEFAULT_TIMEOUT}s）") from exc
        except requests.RequestException as exc:  # pragma: no cover - 防御性
            raise WestlakeError(f"{label} 请求失败：{exc}") from exc
        self._check_http(response, label)
        payload = self._json(response, label)
        if isinstance(payload, Mapping) and payload.get("SessionId"):
            self._session_id = payload.get("SessionId")
        try:
            return self._result(payload, label)
        except SessionExpired:
            if not _allow_relogin or self._auto_login_blocked:
                raise
        try:
            self.login()
        except (InvalidCredentials, AuthError) as exc:
            raise type(exc)(f"{label} 需要登录，自动登录失败：{exc}") from exc
        # upload 等 multipart 请求的文件句柄已被读过一次，重试前回卷。
        for item in ((files or {}) if isinstance(files, Mapping) else {}).values():
            handle = item[1] if isinstance(item, tuple) and len(item) > 1 else None
            seek = getattr(handle, "seek", None)
            if callable(seek):
                try:
                    seek(0)
                except Exception:  # noqa: BLE001 - 回卷失败只能原样重试
                    pass
        return self._send(
            method,
            path,
            params=params,
            json_body=json_body,
            data=data,
            files=files,
            timeout=timeout,
            context=context,
            _allow_relogin=False,
        )

    def _send_raw(
        self, method: str, path: str, **kwargs: Any
    ) -> requests.Response:
        """发一次请求但**不解信封**（用于 ``GetAuthToken`` / 二进制下载）。"""
        label = kwargs.pop("context", None) or f"{method} {path}"
        timeout = kwargs.pop("timeout", None)
        json_body = kwargs.pop("json_body", None)
        if json_body is not None:
            kwargs["json"] = json_body
        try:
            response = self._session.request(
                method,
                self._url(path),
                timeout=timeout if timeout is not None else DEFAULT_TIMEOUT,
                **kwargs,
            )
        except requests.ConnectionError as exc:
            raise OffCampusError(
                f"{label} 连接失败：{self.base_url} 仅校园网/VPN 内可达，"
                "请先连接学校 VPN 后重试。"
            ) from exc
        except requests.Timeout as exc:
            raise WestlakeError(f"{label} 请求超时（{timeout or DEFAULT_TIMEOUT}s）") from exc
        except requests.RequestException as exc:  # pragma: no cover - 防御性
            raise WestlakeError(f"{label} 请求失败：{exc}") from exc
        self._check_http(response, label)
        return response

    def _payload(self, method: str, path: str, **kwargs: Any) -> Mapping[str, Any]:
        """发请求但返回**完整信封**（不解 ``result``）。"""
        response = self._send_raw(method, path, **kwargs)
        payload = self._json(response, kwargs.get("context") or f"{method} {path}")
        if not isinstance(payload, Mapping):
            raise ParseError(f"{path} 返回内容不是 JSON 对象")
        if payload.get("SessionId"):
            self._session_id = payload.get("SessionId")
        return payload

    # -- 凭据 -----------------------------------------------------------
    def resolve_credentials(self) -> tuple[str, str]:
        """返回 ``(username, password)``：显式参数优先，其次 sso 三级优先级。"""
        if self._username and self._password:
            return self._username, self._password
        try:
            sid, password = default_credentials()
        except AuthError:
            if self._username or self._password:
                raise AuthError(
                    "凭据不完整：只能同时提供 username 与 password，"
                    "或都不提供交给 sso 读取。\n" + _CRED_HELP
                ) from None
            raise
        return self._username or sid, self._password or password

    def public_key(self) -> tuple[str, str]:
        """``GET /api/client/Auth/PublicKey`` → ``(publicKey, nonceStr)``。"""
        result = self._send(
            "GET", f"{_AUTH}/PublicKey", context="Auth/PublicKey"
        )
        if not isinstance(result, Mapping) or not result.get("publicKey"):
            raise ParseError("Auth/PublicKey 未返回 publicKey")
        return str(result["publicKey"]), str(result.get("nonceStr") or "")

    def auth_token(self) -> str:
        """``POST /api/client/Auth/GetAuthToken`` → ``szToken``（顶层字段）。"""
        payload = self._payload(
            "POST", f"{_AUTH}/GetAuthToken", context="Auth/GetAuthToken"
        )
        if payload.get("code") != CODE_OK:
            raise AuthError(
                f"Auth/GetAuthToken 失败（code={payload.get('code')}）："
                f"{payload.get('message') or '未知错误'}"
            )
        token = payload.get("szToken")
        if not token:
            raise ParseError("Auth/GetAuthToken 未返回 szToken")
        return str(token)

    def login(self) -> dict[str, Any]:
        """完整登录流程（PublicKey → GetAuthToken → Login），返回用户信息字典。

        失败映射：``code != 0`` → :class:`~westlake_survival.exceptions.InvalidCredentials`
        （服务端把「账号或密码错误」「无账号信息」等一律以非 0 code + message 返回，
        实测文档未给出枚举值，故按登录失败的语义归一到凭据异常）。
        """
        username, password = self.resolve_credentials()
        public_key, nonce = self.public_key()
        token = self.auth_token()
        try:
            encrypted = encrypt_password(password, public_key, nonce)
        except ValueError as exc:
            raise AuthError(f"登录密码加密失败：{exc}") from exc
        body = {
            "szLogonName": username,
            "szPassword": encrypted,
            "szToken": token,
        }
        payload = self._payload(
            "POST",
            f"{_AUTH}/Login",
            json_body=body,
            timeout=AUTH_TIMEOUT,
            context="Auth/Login",
        )
        code = payload.get("code")
        if code != CODE_OK:
            reason = (
                f"登录失败（code={code}）：{payload.get('message') or '账号或密码错误'}"
                f"（打印系统账号可能与统一身份密码不同）"
            )
            self._auto_login_blocked = reason
            self._user = None
            raise InvalidCredentials(reason)
        self._auto_login_blocked = None
        result = payload.get("result")
        self._user = dict(result) if isinstance(result, Mapping) else {}
        return self._user

    def check(self) -> dict[str, Any] | None:
        """``POST /api/client/Auth/Check``：会话有效返回用户信息，否则 ``None``。"""
        payload = self._payload("POST", f"{_AUTH}/Check", context="Auth/Check")
        if payload.get("code") != CODE_OK:
            self._user = None
            return None
        result = payload.get("result")
        self._user = dict(result) if isinstance(result, Mapping) else {}
        return self._user

    def ensure_logged_in(self) -> dict[str, Any]:
        """已登录返回用户信息；否则自动走一次 :meth:`login`。

        之前登录被服务端拒绝（密码错误）时直接抛缓存的失败原因，
        不再反复尝试（防风控）；重建客户端或显式 :meth:`login` 成功可清除。
        """
        user = self.check()
        if user is not None:
            return user
        if self._auto_login_blocked:
            raise InvalidCredentials(self._auto_login_blocked)
        return self.login()

    def logout(self) -> None:
        """``GET /api/client/Auth/Logout``：结束会话并清空本地用户信息。"""
        payload = self._payload("GET", f"{_AUTH}/Logout", context="Auth/Logout")
        if payload.get("code") != CODE_OK:
            raise ActionError(
                f"退出登录失败（code={payload.get('code')}）："
                f"{payload.get('message') or '未知错误'}"
            )
        self._user = None
        self._session_id = None

    def user_info(self, logon_name: str | None = None) -> dict[str, Any]:
        """``GET /api/client/Auth/GetUserInfo``：当前（或指定）用户信息。

        返回原始字典——服务端字段（``szLogonName`` / ``szTrueName`` /
        ``szEmail`` / ``dwSex`` 等）随部署而变，不做强类型映射；
        金额相关字段一律以「分」为单位。
        """
        params = {"szLogonName": logon_name} if logon_name else None
        result = self._send(
            "GET",
            f"{_AUTH}/GetUserInfo",
            params=params,
            context="Auth/GetUserInfo",
        )
        return dict(result) if isinstance(result, Mapping) else {}

    def change_password(self, old_password: str, new_password: str) -> None:
        """``POST /api/client/Auth/ChgPassword``：修改登录密码。

        请求体字段名依据文档 ``ChgPasswordReq``（``szLogonName`` /
        ``szOldPassword`` / ``szNewPassword``）推断，**未经真实环境验证**。
        """
        username, _ = self.resolve_credentials()
        self._send(
            "POST",
            f"{_AUTH}/ChgPassword",
            json_body={
                "szLogonName": username,
                "szOldPassword": old_password,
                "szNewPassword": new_password,
            },
            timeout=AUTH_TIMEOUT,
            context="Auth/ChgPassword",
        )

    # -- 网点 / 纸型 / 费率 ---------------------------------------------
    def list_stations(self) -> list[Station]:
        """``GET /api/client/Station/GetList``：全部打印网点（无需登录，实测可匿名）。"""
        result = self._send("GET", f"{_STATION}/GetList", context="Station/GetList")
        return [Station.from_json(item) for item in _iter_mapping(result)]

    def list_servers(self) -> list[dict[str, Any]]:
        """``GET /api/client/Station/GetSrvList``：打印服务器列表（匿名可读）。"""
        result = self._send("GET", f"{_STATION}/GetSrvList", context="Station/GetSrvList")
        return [dict(item) for item in _iter_mapping(result)]

    def get_station(self, dev_sn: int) -> Station:
        """``GET /api/client/Station/GetByDevSN``：按设备号取单个网点。"""
        result = self._send(
            "GET",
            f"{_STATION}/GetByDevSN",
            params={"dwDevSN": dev_sn},
            context="Station/GetByDevSN",
        )
        if not isinstance(result, Mapping):
            raise NotFound(f"未找到网点 dwDevSN={dev_sn}")
        return Station.from_json(result)

    def list_papers(self) -> list[Paper]:
        """``GET /api/client/Paper/GetPaper``：可用纸型（无需登录，实测可匿名）。"""
        result = self._send("GET", f"{_PAPER}/GetPaper", context="Paper/GetPaper")
        return [Paper.from_json(item) for item in _iter_mapping(result)]

    def fee_standards(self, fee_item_sn: int | None = None) -> list[dict[str, Any]]:
        """``GET /api/client/PrintJob/GetCurrentUserFeeStd``：当前用户的费率项。

        返回原始字典列表（``OPMFEESTD`` 字段随部署而变，未做强类型映射）。
        """
        params = {"dwFeeItemSN": fee_item_sn} if fee_item_sn is not None else None
        result = self._send(
            "GET",
            f"{_PRINTJOB}/GetCurrentUserFeeStd",
            params=params,
            context="PrintJob/GetCurrentUserFeeStd",
        )
        return [dict(item) for item in _iter_mapping(result)]

    def fee_standard(self, req: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        """``POST /api/client/FeeStd/Get``：按条件查询费率（``FeeStdReq`` 透传）。"""
        result = self._send(
            "POST",
            f"{_FEESTD}/Get",
            json_body=dict(req or {}),
            context="FeeStd/Get",
        )
        return [dict(item) for item in _iter_mapping(result)]

    # -- 打印任务 -------------------------------------------------------
    def list_print_jobs(self, dev_sn: int | None = None) -> list[PrintJob]:
        """``GET /api/client/PrintJob/Get``（或 ``GetByDevSN``）：我的打印任务列表。"""
        if dev_sn is None:
            result = self._send("GET", f"{_PRINTJOB}/Get", context="PrintJob/Get")
        else:
            result = self._send(
                "GET",
                f"{_PRINTJOB}/GetByDevSN",
                params={"dwDevSN": dev_sn},
                context="PrintJob/GetByDevSN",
            )
        return [PrintJob.from_json(item) for item in _iter_mapping(result)]

    def upload(
        self,
        file_path: str | Path,
        *,
        copies: int = 1,
        paper_id: int = PAPER_AUTO,
        duplex: int = 1,
        color: int = 1,
        pdf_image: bool = False,
        page_from: int = 0,
        page_to: int = 0,
        back_url: str = "",
        dest_name: str | None = None,
    ) -> None:
        """上传文件并创建打印任务（``POST /api/client/CloudPrint/Upload``，multipart）。

        这是前端「云打印」实际使用的建任务+上传一体化接口（字段名取自
        ``client/new/cprintMobile/cprint.html`` 的 ``#tf`` 表单）。

        Args:
            file_path: 待打印文件路径。
            copies: 份数 ``dwCopies``。
            paper_id: 纸型 ``dwPaperId``；默认 :data:`PAPER_AUTO`（-1，跟随网点纸盒）。
            duplex: 单双面 ``dwDuplex``（1 单面 / 2 双面长边 / 3 双面短边）。
            color: 颜色 ``dwColor``（1 黑白 / 2 彩色）。
            pdf_image: ``dwPdfImage``，PDF 图像模式输出（预览乱码时用）。
            page_from / page_to: 页码范围 ``dwFrom`` / ``dwTo``（0 表示不限）。
            back_url: 上传完成后的回跳地址 ``BackURL``。
            dest_name: 上传文件名；默认取 *file_path* 的文件名。
        """
        path = Path(file_path)
        if not path.is_file():
            raise NotFound(f"待上传文件不存在：{path}")
        if page_from == 0:
            page_to = 0
        fields: dict[str, str] = {
            "dwPaperId": str(paper_id),
            "dwDuplex": str(duplex),
            "dwColor": str(color),
            "dwFrom": str(page_from),
            "dwTo": str(page_to),
            "dwCopies": str(copies),
            "BackURL": back_url,
        }
        if pdf_image:
            fields["dwPdfImage"] = "on"
        name = dest_name or path.name
        with open(path, "rb") as handle:
            files = {"szPath": (name, handle, "application/octet-stream")}
            self._send(
                "POST",
                f"{_CLOUD}/Upload",
                data=fields,
                files=files,
                timeout=AUTH_TIMEOUT,
                context="CloudPrint/Upload",
            )

    def create_print_job(self, req: Mapping[str, Any]) -> Any:
        """``POST /api/client/PrintJob/Create``（``CreatePrintJobReq`` 透传）。

        文档只给出类型名 ``CreatePrintJobReq`` 而未给字段清单，前端也未使用
        该动作（前端走 ``CloudPrint/Upload``），因此这里只做请求体透传：
        调用方需自备 ``req`` 字典。要「上传文件+建任务」请直接用 :meth:`upload`。
        """
        return self._send(
            "POST",
            f"{_PRINTJOB}/Create",
            json_body=dict(req),
            context="PrintJob/Create",
        )

    def set_print_job(self, **fields: Any) -> Any:
        """``POST /api/client/PrintJob/Set``（``SetPrintJobReq`` 透传）。

        常用于改份数/单双面等；字段名参照 ``Get`` 返回的
        ``dwJobId`` / ``dwCopies`` / ``dwDuplex`` / ``dwColor`` 等。
        """
        return self._send(
            "POST",
            f"{_PRINTJOB}/Set",
            json_body=dict(fields),
            context="PrintJob/Set",
        )

    def delete_print_job(self, job_id: int, old_job_id: int | None = None) -> None:
        """``POST /api/client/PrintJob/Del``：删除任务（``{dwJobId, dwOldJobId}``）。"""
        body = {
            "dwJobId": job_id,
            "dwOldJobId": old_job_id if old_job_id is not None else job_id,
        }
        self._send("POST", f"{_PRINTJOB}/Del", json_body=body, context="PrintJob/Del")

    def preview_page(self, job_id: int, create_time: int, page_no: int = 1) -> bytes:
        """``GET /api/client/PrintJob/PreviewPage``：取某页预览图（PNG 字节）。

        服务端把图片以 base64 放在 ``result`` 里，本方法解码为原始字节。
        """
        result = self._send(
            "GET",
            f"{_PRINTJOB}/PreviewPage",
            params={
                "dwJobId": job_id,
                "dwCreateTime": create_time,
                "pageNo": page_no,
            },
            context="PrintJob/PreviewPage",
        )
        if not isinstance(result, str):
            raise ParseError("PrintJob/PreviewPage 的 result 不是 base64 字符串")
        try:
            return base64.b64decode(result)
        except Exception as exc:
            raise ParseError(f"PrintJob/PreviewPage 预览图不是合法 base64：{exc}") from exc

    def take_out(self, job_id: int | None = None, old_job_id: int | None = None) -> Any:
        """``GET /api/client/PrintJob/TakeOut``：扫码取件（``TakeOutResponse``）。

        该动作服务端会校验设备会话，通常只在网点终端上有意义；
        本方法只做透传封装，未在真实设备上验证。
        """
        params: dict[str, Any] = {}
        if job_id is not None:
            params["dwJobId"] = job_id
        if old_job_id is not None:
            params["dwOldJobId"] = old_job_id
        return self._send(
            "GET", f"{_PRINTJOB}/TakeOut", params=params or None, context="PrintJob/TakeOut"
        )

    # -- 扫描任务 -------------------------------------------------------
    def list_scan_jobs(self) -> list[ScanJob]:
        """``GET /api/client/Scan/Get``：我的扫描文档列表。"""
        result = self._send("GET", f"{_SCAN}/Get", context="Scan/Get")
        return [ScanJob.from_json(item) for item in _iter_mapping(result)]

    def set_scan_job(self, **fields: Any) -> Any:
        """``POST /api/client/Scan/Set``（``SetScanReq`` 透传）。

        文档只给类型名，字段清单未给出；需要扫描仪会话参数，仅做透传封装。
        """
        return self._send("POST", f"{_SCAN}/Set", json_body=dict(fields), context="Scan/Set")

    def delete_scan_job(self, job_id: int) -> None:
        """``POST /api/client/Scan/Del``：删除扫描文档。

        文档写 ``req(DelScanReq)`` 但未给字段；按 ``PrintJob/Del`` 的同构口径
        传 ``{dwJobId}``（与前端一致的假设，**未在真实环境验证**）。
        """
        self._send("POST", f"{_SCAN}/Del", json_body={"dwJobId": job_id}, context="Scan/Del")

    def download_scan(
        self,
        job_id: int,
        dest: str | Path,
        *,
        additional: int | None = None,
    ) -> Path:
        """``GET /api/client/Scan/Download``：下载扫描件到 *dest*（流式写入）。

        Args:
            job_id: 扫描任务号 ``dwJobId``。
            dest: 目标路径（父目录不存在时自动创建）。
            additional: ``dwAdditional``，前端传 ``dwSubmitTime`` 作为附加校验。
        """
        params: dict[str, Any] = {"dwJobId": job_id}
        if additional is not None:
            params["dwAdditional"] = additional
        response = self._send_raw(
            "GET",
            f"{_SCAN}/Download",
            params=params,
            stream=True,
            context="Scan/Download",
        )
        destination = Path(dest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(destination, "wb") as handle:
                for chunk in response.iter_content(chunk_size=UPLOAD_CHUNK_SIZE):
                    if chunk:
                        handle.write(chunk)
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        return destination

    # -- 消费 / 用量记录 ------------------------------------------------
    def usage_stat(
        self, begin_date: str | int = "0", end_date: str | int = "99999999"
    ) -> list[UsageSummary]:
        """``POST /api/client/Report/Stat``：按类型汇总的累计用量。

        Args:
            begin_date / end_date: 日期区间，形如 ``"20260901"``；
                默认 ``"0"`` / ``"99999999"`` 表示不限（前端首页口径）。
        """
        result = self._send(
            "POST",
            f"{_REPORT}/Stat",
            json_body={"dwBeginDate": str(begin_date), "dwEndDate": str(end_date)},
            context="Report/Stat",
        )
        return [UsageSummary.from_json(item) for item in _iter_mapping(result)]

    def usage_records(
        self,
        begin_date: str | int = "0",
        end_date: str | int = "99999999",
        *,
        type: int = 1,
        page_no: int = 1,
        row_count: int = 10,
    ) -> UsagePage:
        """``POST /api/client/Report/DetailPage``：分页查询消费/用量明细。

        Args:
            begin_date / end_date: 日期区间（``YYYYMMDD``）。
            type: 类别 ``dwType``（前端「足迹」页：1 打印 / 2 复印 / 3 扫描）。
            page_no / row_count: 页码与每页条数。

        Returns:
            :class:`UsagePage`；``total_page`` 取自**信封顶层**的 ``dwTotalPage``
            （服务端把它放在 ``result`` 的兄弟位置，前端也是读 ``redata.dwTotalPage``）。
        """
        payload = self._payload(
            "POST",
            f"{_REPORT}/DetailPage",
            json_body={
                "dwBeginDate": str(begin_date),
                "dwEndDate": str(end_date),
                "dwType": type,
                "dwPageNo": page_no,
                "dwRowCount": row_count,
            },
            context="Report/DetailPage",
        )
        result = self._result(payload, "Report/DetailPage")
        return UsagePage(
            records=[UsageRecord.from_json(item) for item in _iter_mapping(result)],
            total_page=_opt_int(payload.get("dwTotalPage")),
            total_count=_opt_int(payload.get("dwTotalCount") or payload.get("dwTotalRows")),
            raw=dict(payload),
        )

    def usage_detail(self, req: Mapping[str, Any]) -> Any:
        """``POST /api/client/Report/Detail``（``ReportDetailReq`` 透传）。"""
        return self._send(
            "POST", f"{_REPORT}/Detail", json_body=dict(req), context="Report/Detail"
        )

    def invoice_page(self, req: Mapping[str, Any]) -> Any:
        """``POST /api/client/Report/InvoicePage``（``ReportDetailPageReq`` 透传）。"""
        return self._send(
            "POST", f"{_REPORT}/InvoicePage", json_body=dict(req), context="Report/InvoicePage"
        )

    def make_invoice(self, req: Mapping[str, Any]) -> Any:
        """``POST /api/client/Report/DoInvoice``（``InvoiceDoReq`` 透传）：申请开票。"""
        return self._send(
            "POST", f"{_REPORT}/DoInvoice", json_body=dict(req), context="Report/DoInvoice"
        )

    # -- 支付（涉及一卡通扣费） -----------------------------------------
    def get_bill(self, req: Mapping[str, Any] | None = None, **extra: Any) -> Any:
        """``POST /api/client/Pay/GetBill``：查询待支付账单（``GetBillResponse``）。

        .. warning::
            该接口属于支付链路。文档只给出 ``req(GetBillReq)`` 类型名而未给
            字段清单，故本方法只做请求体透传，**未在真实环境验证**。
            查询本身不扣费，但仍建议只在必要时调用。
        """
        body = dict(req or {})
        return self._send(
            "POST", f"{_PAY}/GetBill", json_body=body, context="Pay/GetBill",
            params=extra or None,
        )

    def pay_result(self, **extra: Any) -> Any:
        """``POST /api/client/Pay/GetPayResult``：查询上一次支付结果（透传）。"""
        return self._send(
            "POST", f"{_PAY}/GetPayResult", context="Pay/GetPayResult", params=extra or None,
        )

    def wait_pay_result(self, **extra: Any) -> Any:
        """``POST /api/client/Pay/WaitPayResult``：等待支付结果（透传）。"""
        return self._send(
            "POST", f"{_PAY}/WaitPayResult", context="Pay/WaitPayResult", params=extra or None,
        )

    def recharge(
        self,
        *,
        sz_type: str = "",
        dw_fee: int = 0,
        state: str = "",
        operator: str = "",
        memo: str = "",
    ) -> Any:
        """``POST /api/client/Pay/Recharge``：按 ``szType``/``dwFee``/``state`` 充值。

        .. danger::
           这是 **一卡通充值** 接口，会真实扣款/入账。仅在明确知道后果时调用；
           本库不做任何金额校验，也不做二次确认。

           参数名对应查询串 ``szType`` / ``dwFee`` / ``state`` /
           ``szOperator`` / ``szMemo``（``dwFee`` 单位为分）。
        """
        params = {"szType": sz_type, "dwFee": dw_fee, "state": state}
        if operator:
            params["szOperator"] = operator
        if memo:
            params["szMemo"] = memo
        return self._send(
            "POST", f"{_PAY}/Recharge", params=params, context="Pay/Recharge"
        )

    # -- 未实现 ---------------------------------------------------------
    def submit_print_job(self, *args: Any, **kwargs: Any) -> Any:
        """TODO: ``PlayController/GetPrintPayInfo`` 等自助端动作尚未封装。

        API 文档中还包含 ``selfservice`` 模块（``PrintJob/PrintOut``、
        ``Pay/CardPay`` 等），那些接口面向网点自助终端、需要设备会话
        （``SessionId`` / ``dwDevSN``），本模块暂不实现。
        """
        raise NotImplementedError(
            "网点自助端（selfservice）动作需设备会话，尚未实现；"
            "参见 pms/api_notes.md 的「未实现」一节。"
        )


def _iter_mapping(result: Any) -> Iterable[Any]:
    """把 ``result`` 规整为可迭代：列表原样，单对象包一层，``None`` 视作空。"""
    if result is None:
        return ()
    if isinstance(result, Mapping):
        return (result,)
    if isinstance(result, (list, tuple)):
        return result
    return ()


def _opt_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "BASE_ENV_VAR",
    "CODE_NOT_LOGGED_IN",
    "CODE_OK",
    "PAPER_AUTO",
    "PMS_BASE",
    "PMSClient",
    "default_credentials",
    "encrypt_password",
    "resolve_base_url",
    "rsa_public_numbers",
]

