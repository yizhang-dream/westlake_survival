"""sis 测试用的假 HTTP 层（唯一模块名，避免与其他测试目录的 conftest 撞名）。

不依赖 ``unittest.mock`` 的隐式行为，直接给出可断言的最小实现。
"""

from __future__ import annotations

from typing import Any, Callable


class FakeResponse:
    """最小化 :class:`requests.Response` 替身。"""

    def __init__(
        self,
        status_code: int = 200,
        text: str = "",
        url: str = "",
        headers: dict[str, str] | None = None,
        content: bytes | None = None,
    ) -> None:
        self.status_code = status_code
        self._text = text
        self.url = url
        self.headers = headers or {}
        self._content = content if content is not None else text.encode("utf-8")

    @property
    def text(self) -> str:
        return self._text

    @property
    def content(self) -> bytes:
        return self._content


class FakeSession:
    """按 handler 决定响应的假 Session，记录全部调用。"""

    def __init__(
        self,
        handler: Callable[[str, str, dict], FakeResponse] | None = None,
    ) -> None:
        self.headers: dict[str, str] = {}
        self.cookies: dict[str, str] = {}
        self.calls: list[tuple[str, str, dict]] = []
        self._handler = handler or (lambda m, u, k: FakeResponse(200, text=""))

    def request(self, method: str, url: str, **kw: Any) -> FakeResponse:
        self.calls.append((method, url, kw))
        return self._handler(method, url, kw)

    def get(self, url: str, **kw: Any) -> FakeResponse:
        return self.request("GET", url, **kw)

    def post(self, url: str, **kw: Any) -> FakeResponse:
        return self.request("POST", url, **kw)