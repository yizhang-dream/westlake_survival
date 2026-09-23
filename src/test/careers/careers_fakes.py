"""src/test/careers 共用的离线 mock。

``FakeResponse`` 的 ``text`` 属性故意按 ``encoding``（默认 latin-1）解码，
用来复现"无 charset 头时直接读 ``response.text`` 会乱码"的坑，逼着被测代码
走 ``content`` 字节路径。
"""

from __future__ import annotations

from typing import Any, Callable

from westlake_survival.careers import CACHE_NAME


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
        """按 ``encoding`` 解码（默认 latin-1，模拟 requests 的乱码行为）。"""
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


class FakeCache:
    """内存版 ETag 缓存，替代 :mod:`westlake_survival._cache` 的落盘实现。

    用法：``monkeypatch.setattr(careers._cache, "load_json", cache.load_json)``
    等三处。``store`` 记录 :func:`save_json` 收到的内容，供断言缓存行为。
    """

    def __init__(self, etag: str | None = None, body: str | None = None) -> None:
        self.store: dict[str, Any] = {}
        if etag is not None:
            self.store[CACHE_NAME] = {"etag": etag, "body": body or ""}

    def load_json(self, name: str, default: Any = None) -> Any:
        return self.store.get(name, default)

    def save_json(self, name: str, obj: Any) -> None:
        self.store[name] = obj

    def cache_path(self, name: str):
        from pathlib import Path

        return Path(name)


__all__ = ["FakeResponse", "FakeSession", "FakeCache"]