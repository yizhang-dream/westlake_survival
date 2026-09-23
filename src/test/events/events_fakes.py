"""src/test/events 共用的离线 mock。

响应结构按 2026-09-22 实测校准：列表页/详情页的响应头是
``Content-Type: text/html``（无 charset），``requests`` 会把 ``encoding`` 当成
ISO-8859-1，因此 :class:`FakeResponse` 的 ``text`` 属性故意按 ``encoding``
解码——用来复现"直接读 ``response.text`` 会乱码"的坑，逼着被测代码走
``content`` 字节路径。
"""

from __future__ import annotations

from typing import Any, Callable


class FakeResponse:
    """最小化 :class:`requests.Response` 替身。"""

    def __init__(
        self,
        body: bytes | str = b"",
        *,
        status: int = 200,
        encoding: str = "latin-1",
        url: str = "",
        headers: dict[str, str] | None = None,
    ) -> None:
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.content = body
        self.status_code = status
        self.encoding = encoding
        self.apparent_encoding = "utf-8"
        self.url = url
        self.headers = headers or {}

    @property
    def text(self) -> str:
        """按 ``encoding`` 解码（默认为 latin-1，模拟 requests 的乱码行为）。"""
        try:
            return self.content.decode(self.encoding or "latin-1", errors="replace")
        except LookupError:
            return self.content.decode("utf-8", errors="replace")


class FakeSession:
    """按 handler 决定响应的假 Session，记录全部调用。"""

    def __init__(
        self,
        handler: Callable[[str, dict], FakeResponse] | None = None,
    ) -> None:
        self.headers: dict[str, str] = {}
        self.calls: list[tuple[str, dict]] = []
        self._handler = handler or (lambda url, kw: FakeResponse(b"", url=url))

    def get(self, url: str, **kw: Any) -> FakeResponse:
        self.calls.append((url, kw))
        return self._handler(url, kw)


__all__ = ["FakeResponse", "FakeSession"]