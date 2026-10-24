"""西湖大学统一身份认证（IAM）编程登录。

背景
====
SIS 登录页脚本会跳 ``iam.westlake.edu.cn/cas/oauth2.0/authorize``（OAuth2，
client_id ``0c0b89c56b63e302``，回调 SIS 的 PeopleSoft 落地页）。所以教务可以
用**统一身份认证密码**登录，不必记 SIS 专用密码——这正是用户要的「一个入口
通吃」。

协议（2026-10-24 用虚构账号在真页面抓包实测）
================================================
1. ``GET {SIS_LOGIN_URL}`` → 页面脚本重定向到 ``/cas/oauth2.0/authorize?...``,
   IAM 落到 ``/ac/#/index?lck=context_CAS_xxx&entityId=<回调>``, 得到 ``lck``。
2. ``POST /idp/authn/queryAuthMethods`` ``{lck, entityId}`` → 认证链。
3. ``POST /idp/authn/verifyCodeIsNeed`` ``{lang, loginName, chainCode, authModuleCode}``。
4. ``POST /idp/authn/getJsPublicKey`` → RSA 公钥（模数/指数）。
5. 密码用该公钥 RSA 加密（前端 JS_PK 方式），``POST /idp/authn/authExecute``
   ``{authModuleCode:'userAndPwd', authChainCode, entityId, requestType,
   lck, loginName, password:<RSA密文>, ...}`` → 成功后 IAM 下发会话与跳转。
6. 带 IAM 会话重放 authorize → 302 到回调地址拿 ``code`` → SIS 发 PS_TOKEN。

失败语义（实测）：用户名或密码错误 → 页面提示「已认证失败 N 次」，接口
``code`` 非 0。**本模块不做口令猜测**：一次失败即抛错。
"""

from __future__ import annotations

import base64
import json
import logging
import re
from urllib.parse import urlencode, urlparse, parse_qs

import requests

from westlake_survival._net import DEFAULT_TIMEOUT, http_session
from westlake_survival.exceptions import AuthError, WestlakeError

__all__ = [
    "IAM_BASE",
    "SIS_LOGIN_URL",
    "SIS_OAUTH_CLIENT_ID",
    "authorize_url_for_sis",
    "login",
    "exchange_sis_session",
    "canvas_login",
]

logger = logging.getLogger(__name__)

IAM_BASE = "https://iam.westlake.edu.cn"
SIS_LOGIN_URL = "https://sis.westlake.edu.cn/psp/CSPRD_3/?cmd=login"
SIS_REDIRECT_URI = (
    "https://sis.westlake.edu.cn/psc/CSPRD/EMPLOYEE/SA/c/"
    "NUI_FRAMEWORK.PT_LANDINGPAGE.GBL"
)
SIS_OAUTH_CLIENT_ID = "0c0b89c56b63e302"

#: Canvas 的 CAS 入口（实测 302 → IAM /cas/login?service=…/login/cas）。
CANVAS_CAS_ENTRY = "https://canvas.westlake.edu.cn/login/cas"


def authorize_url_for_sis() -> str:
    """构造 SIS 的 IAM OAuth2 授权地址。"""
    return (
        f"{IAM_BASE}/cas/oauth2.0/authorize?"
        + urlencode(
            {
                "client_id": SIS_OAUTH_CLIENT_ID,
                "redirect_uri": SIS_REDIRECT_URI,
                "response_type": "code",
                "scope": "base_api",
                "state": "",
            }
        )
    )


def _post_json(session: requests.Session, url: str, payload: dict, *, referer: str) -> dict:
    response = session.post(
        url,
        json=payload,
        headers={"Referer": referer, "X-Requested-With": "XMLHttpRequest"},
        timeout=DEFAULT_TIMEOUT,
    )
    try:
        data = response.json()
    except ValueError as exc:
        raise WestlakeError(f"IAM 返回非 JSON：{url}") from exc
    if not isinstance(data, dict):
        raise WestlakeError(f"IAM 返回结构异常：{url}")
    return data


def _auth_chain(session, lck: str, entity_id: str, user: str, password: str) -> str:
    """在既有 lck 上完成「用户名+密码」认证，返回 loginToken。

    queryAuthMethods → verifyCodeIsNeed → getJsPublicKey → authExecute，
    失败一次即抛 :class:`AuthError`，不做口令猜测。
    """
    referer = f"{IAM_BASE}/ac/"
    chain = _post_json(
        session,
        f"{IAM_BASE}/idp/authn/queryAuthMethods",
        {"lck": lck, "entityId": entity_id},
        referer=referer,
    )
    chain_code = ""
    for item in chain.get("data") or []:
        if isinstance(item, dict) and item.get("moduleCode") == "userAndPwd":
            chain_code = str(item.get("authChainCode") or "")
            break
    if not chain_code:
        raise WestlakeError("未取得 userAndPwd 认证链——IAM 协议可能已变化")

    _post_json(
        session,
        f"{IAM_BASE}/idp/authn/verifyCodeIsNeed",
        {"lang": "zh_CN", "loginName": user, "chainCode": chain_code, "authModuleCode": "userAndPwd"},
        referer=referer,
    )
    key = _post_json(session, f"{IAM_BASE}/idp/authn/getJsPublicKey", {}, referer=referer)
    public_b64 = str(key.get("data") or "")
    if not public_b64:
        raise WestlakeError("未取得 IAM RSA 公钥")
    execute = _post_json(
        session,
        f"{IAM_BASE}/idp/authn/authExecute",
        {
            "authModuleCode": "userAndPwd",
            "authChainCode": chain_code,
            "entityId": entity_id,
            "requestType": "chain_type",
            "lck": lck,
            "authPara": {"loginName": user, "password": _rsa_encrypt(password, public_b64), "verifyCode": ""},
        },
        referer=referer,
    )
    message = str(execute.get("message") or execute.get("msg") or "")
    if "成功" not in message or "失败" in message:
        code = str(execute.get("code") or "")
        if code == "4333" or "验证码" in message:
            # 4333=验证码/登录名缺失：IAM 失败计数态开着（可持续一天且成功
            # 登录也不复位）。此时继续试错只会给计数续期——提示走浏览器。
            raise AuthError(
                "IAM 当前强制图形验证码（失败计数态）：无头密码登录被禁。"
                "请 westlake scholar ensure（浏览器本人输一次验证码），"
                "或等学校侧重置后再试。原始信息："
                f"（{code}）{message or '验证码或登录名为空'}"
            )
        raise AuthError(f"IAM 登录失败（{code}）：{message or '用户名或密码错误'}")
    token = str(execute.get("loginToken") or "")
    if not token:
        raise WestlakeError("IAM 认证成功但未返回 loginToken——协议可能已变化")
    return token


def _run_engine(session, login_token: str):
    """把 loginToken 交给 authnEngine（form 编码），返回引擎响应。"""
    return session.post(
        f"{IAM_BASE}/idp/authCenter/authnEngine?locale=zh-CN",
        data={"loginToken": login_token},
        headers={"Referer": f"{IAM_BASE}/ac/", "Content-Type": "application/x-www-form-urlencoded"},
        timeout=DEFAULT_TIMEOUT,
        allow_redirects=False,
    )


def canvas_login(
    user: str,
    password: str,
    *,
    session: requests.Session | None = None,
) -> requests.Session:
    """用统一身份认证登 Canvas，返回带 Canvas 会话 Cookie 的 Session。

    Canvas 走经典 CAS：``/login/cas`` → IAM ``/cas/login?service=…`` →
    ``/ac/#/index?lck=context_CAS_…&entityId=https://canvas.westlake.edu.cn``。
    认证链与 SIS 相同；引擎响应会带回带 ticket 的跳转，落到 Canvas 换会话。

    Raises:
        AuthError: 账号或密码错误（一次失败即抛）。
        WestlakeError: 网络或协议异常。
    """
    session = session if session is not None else http_session()
    # 1) 走 Canvas CAS 入口拿 lck
    first = session.get(CANVAS_CAS_ENTRY, timeout=DEFAULT_TIMEOUT, allow_redirects=False)
    url = first.headers.get("Location", "")
    for _ in range(4):
        if "lck=" in url:
            break
        hop = session.get(url, timeout=DEFAULT_TIMEOUT, allow_redirects=False)
        url = hop.headers.get("Location", "")
    match = re.search(r"lck=(context_[A-Za-z0-9_]+)&entityId=([^&]+)", url)
    if not match:
        raise WestlakeError(f"未从 Canvas CAS 跳转解析到 lck：{url[:120]}")
    lck, entity_id = match.group(1), match.group(2)

    # 2) 同一套用户名密码认证 + 引擎
    login_token = _auth_chain(session, lck, entity_id, user, password)
    engine = _run_engine(session, login_token)

    # 3) 引擎页带 ticket 跳回 Canvas，跟下去换会话 Cookie
    target = engine.headers.get("Location", "")
    if not target:
        found = re.search(r"https://canvas\.westlake\.edu\.cn[^\"'<>\s]+", engine.text)
        target = found.group(0) if found else ""
    if not target:
        raise WestlakeError("authnEngine 未返回 Canvas 跳转——协议可能已变化")
    session.get(target, timeout=DEFAULT_TIMEOUT, allow_redirects=True)
    return session


def login(
    user: str,
    password: str,
    *,
    session: requests.Session | None = None,
    timeout: float | None = None,
) -> requests.Session:
    """用统一身份认证账号登录，返回带 IAM 会话的 Session。

    Raises:
        AuthError: 账号或密码错误（一次失败即抛，不重试）。
        WestlakeError: 网络或协议异常。
    """
    session = session if session is not None else http_session()
    lck, entity_id = _obtain_lck(session)
    referer = f"{IAM_BASE}/ac/"

    # 认证链（实测 data 是数组，取 userAndPwd 那条）
    chain = _post_json(
        session,
        f"{IAM_BASE}/idp/authn/queryAuthMethods",
        {"lck": lck, "entityId": entity_id},
        referer=referer,
    )
    chain_code = ""
    for item in chain.get("data") or []:
        if isinstance(item, dict) and item.get("moduleCode") == "userAndPwd":
            chain_code = str(item.get("authChainCode") or "")
            break
    if not chain_code:
        raise WestlakeError("未取得 userAndPwd 认证链——IAM 协议可能已变化")

    _post_json(
        session,
        f"{IAM_BASE}/idp/authn/verifyCodeIsNeed",
        {
            "lang": "zh_CN",
            "loginName": user,
            "chainCode": chain_code,
            "authModuleCode": "userAndPwd",
        },
        referer=referer,
    )

    # RSA 公钥（data 是 base64 DER SPKI，实测 2026-10-24）
    key = _post_json(session, f"{IAM_BASE}/idp/authn/getJsPublicKey", {}, referer=referer)
    public_b64 = str(key.get("data") or "")
    if not public_b64:
        raise WestlakeError("未取得 IAM RSA 公钥")
    encrypted = _rsa_encrypt(password, public_b64)

    execute = _post_json(
        session,
        f"{IAM_BASE}/idp/authn/authExecute",
        {
            "authModuleCode": "userAndPwd",
            "authChainCode": chain_code,
            "entityId": entity_id,
            "requestType": "chain_type",
            "lck": lck,
            "authPara": {"loginName": user, "password": encrypted, "verifyCode": ""},
        },
        referer=referer,
    )
    code = str(execute.get("code") or "")
    message = str(execute.get("message") or execute.get("msg") or "")
    # 实测：成功时 code="200"、message="认证成功"；失败时 code 仍可能是 "200"
    # 但 message 为「认证失败」类文案。以文案为准，另保留 code 便于排查。
    if "成功" not in message or "失败" in message:
        raise AuthError(f"IAM 登录失败（{code}）：{message or '用户名或密码错误'}")
    login_token = str(execute.get("loginToken") or "")
    if not login_token:
        raise WestlakeError("IAM 认证成功但未返回 loginToken——协议可能已变化")
    # 完成引擎：POST authnEngine（form: loginToken），返回带 code 的跳转页
    engine = session.post(
        f"{IAM_BASE}/idp/authCenter/authnEngine?locale=zh-CN",
        data={"loginToken": login_token},
        headers={"Referer": f"{IAM_BASE}/ac/", "Content-Type": "application/x-www-form-urlencoded"},
        timeout=DEFAULT_TIMEOUT,
        allow_redirects=False,
    )
    # 引擎页里写着去 SIS 的地址（?code=…），把它跟下去换 PS_TOKEN
    target = engine.headers.get("Location", "")
    if not target:
        match = re.search(r"https://sis\.westlake\.edu\.cn[^\"'<>\s]+", engine.text)
        target = match.group(0) if match else ""
    if target:
        session.get(target, timeout=DEFAULT_TIMEOUT, allow_redirects=True)
    return session


def _obtain_lck(session: requests.Session) -> tuple[str, str]:
    """走 SIS 登录页 → IAM 授权，取登录上下文 ``(lck, entityId)``。

    实测（2026-10-24）：authorize 302 到 ``/idp/authCenter/authenticate``，再 302
    到 ``/ac/#/index?lck=context_oauth2_<uuid>&entityId=<client_id>``——lck 与
    entityId 都在第二个 302 的 Location 里；entityId 就是 OAuth client_id。
    """
    first = session.get(authorize_url_for_sis(), timeout=DEFAULT_TIMEOUT, allow_redirects=False)
    location = first.headers.get("Location", "")
    if not location:
        raise WestlakeError("IAM 授权地址未跳转——协议可能已变化")
    second = session.get(location, timeout=DEFAULT_TIMEOUT, allow_redirects=False)
    target = second.headers.get("Location", "") or second.url
    match = re.search(r"lck=(context_[A-Za-z0-9_]+)&entityId=([^&]+)", target)
    if not match:
        raise WestlakeError(f"未从跳转里解析到 lck/entityId：{target[:120]}")
    return match.group(1), match.group(2)


def exchange_sis_session(session: requests.Session) -> str:
    """用 IAM 会话换 SIS 会话，返回 PS_TOKEN（同时也挂在 session 上）。

    Raises:
        AuthError: 未取得 PS_TOKEN（授权失败或协议变化）。
    """
    response = session.get(authorize_url_for_sis(), timeout=DEFAULT_TIMEOUT, allow_redirects=True)
    token = None
    for cookie in session.cookies:
        if cookie.name.upper() == "PS_TOKEN":
            token = cookie.value
            break
    if not token:
        raise AuthError(
            f"IAM 会话换 SIS 会话失败（未拿到 PS_TOKEN，最终 URL {urlparse(response.url).path}）"
        )
    return token


def _rsa_encrypt(password: str, public_key_b64: str) -> str:
    """用 ``getJsPublicKey`` 的公钥加密密码（标准 PKCS#1 v1.5，base64 输出）。

    公钥是 base64 的 DER SubjectPublicKeyInfo（实测 2048 位，密文 344 字符）。
    """
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except ImportError as exc:  # pragma: no cover
        raise WestlakeError(
            "IAM 登录需要 RSA：请安装 cryptography（pip install 'westlake_survival[crypto]'）"
        ) from exc
    public = serialization.load_der_public_key(base64.b64decode(public_key_b64))
    ciphertext = public.encrypt(password.encode("utf-8"), padding.PKCS1v15())
    return base64.b64encode(ciphertext).decode("ascii")
