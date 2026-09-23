"""pms 测试用的假 HTTP 层（唯一模块名，避免与其他测试目录的 conftest 撞名）。

不依赖 ``unittest.mock`` 的隐式行为，直接给出可断言的最小实现：
:class:`FakeSession` 按 URL 路由并记录每次调用，:class:`FakeResponse`
按真实信封回放 JSON。
"""

from __future__ import annotations

import json
from typing import Any

#: 测试用根地址（不是真实地址，避免误打真实服务）。
TEST_BASE = "http://pms.test"


class FakeResponse:
    """最小可用的 :class:`requests.Response` 替身。"""

    def __init__(
        self,
        payload: Any = None,
        *,
        status_code: int = 200,
        text: str | None = None,
        headers: dict[str, str] | None = None,
        chunks: list[bytes] | None = None,
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {"Content-Type": "application/json"}
        self._chunks = chunks
        if text is not None:
            self._text = text
        elif payload is not None:
            self._text = json.dumps(payload, ensure_ascii=False)
        else:
            self._text = ""
        self.closed = False

    @property
    def text(self) -> str:
        return self._text

    @property
    def content(self) -> bytes:
        return self._text.encode("utf-8")

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("no json body")
        return self._payload

    def iter_content(self, chunk_size: int = 1) -> Any:
        for chunk in self._chunks or []:
            yield chunk

    def close(self) -> None:
        self.closed = True


class FakeSession:
    """按 URL 子串路由的假 Session，同时记录全部调用。"""

    def __init__(self, routes: dict[str, FakeResponse] | None = None) -> None:
        self.routes: dict[str, FakeResponse] = dict(routes or {})
        self.calls: list[dict[str, Any]] = []

    def add(self, path: str, response: FakeResponse) -> "FakeSession":
        self.routes[path] = response
        return self

    def _match(self, url: str) -> FakeResponse:
        for key, response in self.routes.items():
            if key in url:
                return response
        raise AssertionError(f"FakeSession 未配置路由：{url}\n已配置：{list(self.routes)}")

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"method": method.upper(), "url": url, **kwargs})
        return self._match(url)

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        return self.request("POST", url, **kwargs)

    def calls_for(self, path: str) -> list[dict[str, Any]]:
        """返回 URL 命中该路径的所有调用记录。"""
        return [call for call in self.calls if path in call["url"]]

    def paths(self) -> list[str]:
        """按调用顺序返回各次请求的 URL 路径（去掉 base）。"""
        out = []
        for call in self.calls:
            url = call["url"]
            for marker in ("/api/",):
                index = url.find(marker)
                if index >= 0:
                    url = url[index:]
                    break
            out.append(url)
        return out


def envelope(result: Any = None, *, code: int = 0, message: str = "") -> dict[str, Any]:
    """按真实信封构造响应体。"""
    return {"code": code, "message": message, "result": result}


__all__ = ["FakeResponse", "FakeSession", "TEST_BASE", "envelope"]
