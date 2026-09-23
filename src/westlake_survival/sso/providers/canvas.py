"""Canvas LMS 认证：Bearer token（不走 CAS）。

实测（2026-09-22）：``https://canvas.westlake.edu.cn`` 未登录会 302 到
``iam.westlake.edu.cn`` 的 CAS；但 API 走 ``Authorization: Bearer <token>``，
无需 CAS 会话。

Token 来源优先级（高到低）：

1. 构造参数 ``CanvasAuth(token=...)``；
2. 环境变量 ``WESTLAKE_CANVAS_TOKEN``；
3. ``~/.westlake_survival/canvas_token.txt`` 首行。

此外，每次 ``get``/``post`` 可传 ``token=`` 作**临时覆盖**：它优先于上面三级
来源，只作用于本次请求（含 401 后的重试），且无需预先配置任何 token 即可
使用——即使三级来源全无也不会触发解析链的报错。
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import requests

from westlake_survival._cache import config_root
from westlake_survival._net import DEFAULT_TIMEOUT
from westlake_survival.exceptions import AuthError
from westlake_survival.sso.authorizer import Authorizer


class CanvasAuth(Authorizer):
    """Canvas API 的 Bearer token 认证器（每子类单例）。"""

    BASE_URL = "https://canvas.westlake.edu.cn"

    #: 环境变量名。
    TOKEN_ENV = "WESTLAKE_CANVAS_TOKEN"

    #: token 文件名（相对 ``config_root()``），取首行。
    TOKEN_FILENAME = "canvas_token.txt"

    #: 轻量探测端点（判断 token 是否有效）。
    CHECK_PATH = "/api/v1/users/self"

    def _setup(self, token: str | None = None) -> None:
        # 单例：仅首次构造时记录显式 token。
        self._token: str | None = token
        #: 当次请求的临时 token（``get``/``post`` 的 ``token=``）。
        self._request_token: str | None = None

    # ----------------------------------------------------------------- token

    @staticmethod
    def token_path() -> Path:
        return config_root() / CanvasAuth.TOKEN_FILENAME

    @property
    def token(self) -> str:
        """按三级优先级解析 token；都没有则抛 :class:`AuthError`。"""
        if self._token:
            return self._token
        env = os.environ.get(self.TOKEN_ENV)
        if env and env.strip():
            return env.strip()
        path = self.token_path()
        if path.exists():
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as exc:  # pragma: no cover - 依赖文件系统状态
                raise AuthError(f"读取 Canvas token 文件失败：{path}（{exc}）。") from exc
            for line in text.splitlines():
                if line.strip():
                    return line.strip()
        raise AuthError(
            "未找到 Canvas token。请任选一种方式提供：\n"
            "  1) CanvasAuth(token='...') 或调用时传 token='...'\n"
            f"  2) export {self.TOKEN_ENV}='...'\n"
            f"  3) 把 token 写入 {self.token_path()} 首行"
        )

    # ------------------------------------------------------------- 会话构建

    def _build_session(self) -> requests.Session:
        session = self._new_session()
        session.headers["Authorization"] = f"Bearer {self._effective_token}"
        return session

    @property
    def _effective_token(self) -> str:
        """当次请求 token 优先，否则回落到三级解析链。"""
        if self._request_token:
            return self._request_token
        return self.token

    def _apply_token(self, token: str | None) -> None:
        """把（可选的）临时 token 应用到当前会话头。

        传入非空 *token* 时不会触发 :attr:`token` 解析链，因此三级来源全无
        也能直接请求；已有会话时仅覆盖当次请求的 Authorization 头。
        """
        if token:
            self._request_token = token
            if self._session is None or self._is_expired():
                self._session = self._new_session()
                self._session_time = time.time()
            self._session.headers["Authorization"] = f"Bearer {token}"
            return
        self._request_token = None
        session = self.session  # 触发 ensure()
        session.headers["Authorization"] = f"Bearer {self.token}"

    def _clear_request_token(self) -> None:
        self._request_token = None

    def get(self, url: str, **kw: Any) -> requests.Response:
        self._apply_token(kw.pop("token", None))
        try:
            return super().get(url, **kw)
        finally:
            self._clear_request_token()

    def post(self, url: str, **kw: Any) -> requests.Response:
        self._apply_token(kw.pop("token", None))
        try:
            return super().post(url, **kw)
        finally:
            self._clear_request_token()

    # -------------------------------------------------------- 失效 / 有效性

    def _is_stale_response(self, response: requests.Response) -> bool:
        # 401 表示 token 失效，触发 refresh() 重新解析 token 后重试。
        return getattr(response, "status_code", 0) == 401

    def check(self) -> bool:
        """GET ``/api/v1/users/self``，401 视为无效。"""
        if self._session is None:
            return False
        try:
            response = self._session.get(
                f"{self.BASE_URL}{self.CHECK_PATH}",
                timeout=DEFAULT_TIMEOUT,
                allow_redirects=False,
            )
        except requests.RequestException:
            return False
        return response.status_code != 401


__all__ = ["CanvasAuth"]