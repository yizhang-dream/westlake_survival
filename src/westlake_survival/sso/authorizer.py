"""统一认证的抽象基类与 ``require_auth`` 装饰器。

设计要点（与 sustech_survival 同源，实现独立）：

- **每子类单例**：同一 ``Authorizer`` 子类在任意位置构造都返回同一实例，
  让整个进程共享一个已登录的 :class:`requests.Session`。
- **会话只在内存**：cookie/凭据绝不落盘；进程退出即丢失。
- **TTL 25 分钟**：超过 ``SESSION_TTL`` 视为过期，下次访问自动重新登录。
- **失效自愈**：请求返回 CAS 登录页（或子类定义的 stale 特征）时自动
  ``refresh()`` 并重试一次，仍失效才抛 :class:`SessionExpired`。
"""

from __future__ import annotations

import functools
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, TypeVar

import requests

from westlake_survival._net import DEFAULT_TIMEOUT, http_session
from westlake_survival.exceptions import AuthError, OffCampusError, SessionExpired, is_offcampus

#: 统一认证 CAS 所在域；基类的 stale 检测用它判定"被打回登录页"。
CAS_DOMAIN = "sso.westlake.edu.cn"

#: CAS 登录页路径片段。
CAS_LOGIN_PATH = "/cas/login"

#: 校外访问被拒时的引导信息。
_OFFCAMPUS_HINT = (
    "目标系统仅校园网/VPN 内可达，请先连接西湖大学 VPN（https://vpn.westlake.edu.cn/）后重试。"
)

F = TypeVar("F", bound=Callable[..., Any])


class Authorizer(ABC):
    """某个校内服务的会话持有者（每子类单例）。"""

    #: 会话有效期（秒），默认 25 分钟。
    SESSION_TTL: float = 25 * 60

    #: 子类覆写：服务根地址，供 ``check()`` 之类的轻量探测使用。
    BASE_URL: str = ""

    #: 每个子类一个实例：``{cls: instance}``。
    _instances: dict[type, "Authorizer"] = {}

    def __new__(cls, *args: Any, **kwargs: Any) -> "Authorizer":
        if cls not in cls._instances:
            instance = super().__new__(cls)
            instance._initialized = False  # type: ignore[attr-defined]
            cls._instances[cls] = instance
        return cls._instances[cls]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # 单例：只在首次构造时初始化，之后重复构造不覆盖已有会话。
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self._session: requests.Session | None = None
        self._session_time: float = 0.0
        # 每个子类单例自己的锁：串行化"检查+登录"，避免并发首访重复登录
        # 或读到半初始化会话。用 RLock 以便 ensure() 在持锁时调用 refresh()。
        self._lock = threading.RLock()
        self._setup(*args, **kwargs)

    def _setup(self, *args: Any, **kwargs: Any) -> None:
        """子类初始化钩子；因单例语义**只会被调用一次**。

        子类需要构造参数时覆写本方法（而非 ``__init__``），即可保证
        重复构造不会重置实例状态。
        """

    # ------------------------------------------------------------------ 会话

    @property
    def session(self) -> requests.Session:
        """返回已确保登录的 :class:`requests.Session`。"""
        self.ensure()
        assert self._session is not None  # ensure() 保证非空
        return self._session

    def ensure(self) -> None:
        """未登录或会话过期时执行一次登录。

        并发安全：先无锁快查，未命中再拿锁复查（double-checked），
        保证多线程首访只触发一次登录。锁只包登录，不包业务请求。
        """
        if self._session is not None and not self._is_expired():
            return
        with self._lock:
            if self._session is not None and not self._is_expired():
                return
            self.refresh()

    def refresh(self) -> None:
        """强制重新登录并替换当前会话（持锁串行化，防并发重复登录）。"""
        with self._lock:
            self._session = self._build_session()
            self._session_time = time.time()

    def _is_expired(self) -> bool:
        return (time.time() - self._session_time) > self.SESSION_TTL

    def _new_session(self) -> requests.Session:
        """创建一个空 Session；测试可覆写/打桩以注入假 Session。"""
        return http_session()

    # ------------------------------------------------------------ 请求入口

    def get(self, url: str, **kw: Any) -> requests.Response:
        return self._request("GET", url, **kw)

    def post(self, url: str, **kw: Any) -> requests.Response:
        return self._request("POST", url, **kw)

    def _request(self, method: str, url: str, **kw: Any) -> requests.Response:
        self.ensure()
        kw.setdefault("timeout", DEFAULT_TIMEOUT)
        assert self._session is not None
        response = self._session.request(method, url, **kw)
        self._raise_if_offcampus(response)
        if self._is_stale_response(response):
            # 会话失效：刷新一次后重试一次。
            self.refresh()
            assert self._session is not None
            response = self._session.request(method, url, **kw)
            self._raise_if_offcampus(response)
            if self._is_stale_response(response):
                raise SessionExpired(
                    f"会话已过期且自动刷新失败：{method} {url}"
                )
        return response

    def _raise_if_offcampus(self, response: requests.Response) -> None:
        if is_offcampus(response):
            raise OffCampusError(_OFFCAMPUS_HINT)

    # -------------------------------------------------------- 失效 / 有效性

    def _is_stale_response(self, response: requests.Response) -> bool:
        """判断响应是否表示"会话已失效、被重定向回 CAS 登录页"。

        基类默认规则：302/303（等重定向）且 Location 指向 CAS 登录页，
        或响应的最终 URL 落在 CAS 登录页。子类可覆写（如 SIS 看 ``cmd=login``）。
        """
        status = getattr(response, "status_code", 0)
        if status in (301, 302, 303, 307, 308):
            location = response.headers.get("Location", "") or ""
            if CAS_DOMAIN in location and CAS_LOGIN_PATH in location:
                return True
        final_url = getattr(response, "url", "") or ""
        if CAS_DOMAIN in final_url and CAS_LOGIN_PATH in final_url:
            return True
        return False

    def check(self) -> bool:
        """探测当前会话是否仍然有效（GET 一个轻量页，不跟随重定向）。

        未登录返回 ``False``；网络异常也返回 ``False``，由调用方决定是否
        重新登录。
        """
        if self._session is None:
            return False
        probe = self.BASE_URL
        if not probe:
            return True
        try:
            response = self._session.get(
                probe, timeout=DEFAULT_TIMEOUT, allow_redirects=False
            )
        except requests.RequestException:
            return False
        return not self._is_stale_response(response)

    # -------------------------------------------------------------- 抽象点

    @abstractmethod
    def _build_session(self) -> requests.Session:
        """执行完整登录，返回已携带会话 cookie 的 Session。

        失败时抛 :class:`AuthError` 子类（如 :class:`InvalidCredentials`）。
        """
        raise NotImplementedError


def require_auth(auth_cls: type[Authorizer]) -> Callable[[F], F]:
    """装饰器：给被装饰函数注入一个已 ``ensure()`` 的 *auth_cls* 实例。

    用法::

        @require_auth(SISAuth)
        def grades(*, auth): ...

    调用方若显式传入 ``auth=`` 则原样透传，不做覆盖。
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if kwargs.get("auth") is None:
                auth = auth_cls()
                auth.ensure()
                kwargs["auth"] = auth
            return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


__all__ = ["Authorizer", "require_auth", "AuthError"]