r"""``src/test/faculty`` 公共夹具与离线替身。

``fixture_list.html`` / ``fixture_detail.html`` 是从真实页面（2026-09-22 实测）
裁剪出的 faculty / facultyDetail 组件片段，保留真实 JS 结构（含
``mounted: function () {}`` 回调、``<\/p>`` 转义、``subject`` 尾部逗号等），
供离线解析测试使用。

``fixture_science.json`` / ``fixture_sls.json`` / ``fixture_teaching.html`` 是
2026-09-24 实测的三个子源（理学院接口 / 生科院接口 / 通识课授课教师页）的
真实裁剪片段（姓名保留真实、邮箱等隐私字段脱敏），供多源聚合测试使用。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pytest

FIXTURE_DIR = Path(__file__).parent


class FakeResponse:
    """最小化 :class:`requests.Response` 替身。

    ``text`` 故意按 ``encoding``（默认 latin-1）解码，复现"无 charset 头时
    直接读 ``response.text`` 会得到乱码"的真实坑，逼被测代码走 ``content``
    字节路径。
    """

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
    """按 handler 决定响应的假 Session，记录全部 GET/POST 调用。

    ``get`` 与 ``post`` 共用同一 handler（签名 ``(url, kw)``）；``post`` 额外
    记录 ``json`` 请求体，供断言理学院接口的精确 body。
    """

    def __init__(
        self,
        handler: Callable[[str, dict], FakeResponse] | None = None,
    ) -> None:
        self.headers: dict[str, str] = {}
        self.calls: list[tuple[str, dict]] = []
        self.posts: list[tuple[str, dict]] = []
        self._handler = handler or (lambda url, kw: FakeResponse(b"", url=url))

    def get(self, url: str, **kw: Any) -> FakeResponse:
        self.calls.append((url, kw))
        return self._handler(url, kw)

    def post(self, url: str, **kw: Any) -> FakeResponse:
        self.posts.append((url, kw))
        return self._handler(url, kw)


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch, tmp_path):
    """把缓存根目录重定位到临时目录，避免测试污染真实缓存。"""
    monkeypatch.setenv("WESTLAKE_HOME", str(tmp_path / "home"))


@pytest.fixture(scope="session")
def list_html() -> str:
    """真实列表页裁剪片段（UTF-8 文本）。"""
    return (FIXTURE_DIR / "fixture_list.html").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def detail_html() -> str:
    """真实详情页裁剪片段（UTF-8 文本）。"""
    return (FIXTURE_DIR / "fixture_detail.html").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def science_json() -> str:
    """理学院接口裁剪片段（JSON 文本，含 1 条重复 url）。"""
    return (FIXTURE_DIR / "fixture_science.json").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def sls_json() -> str:
    """生科院接口裁剪片段（JSON 文本）。"""
    return (FIXTURE_DIR / "fixture_sls.json").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def teaching_html() -> str:
    """通识课授课教师页裁剪片段（静态 HTML 表格）。"""
    return (FIXTURE_DIR / "fixture_teaching.html").read_text(encoding="utf-8")


@pytest.fixture
def list_session(list_html: str) -> FakeSession:
    """返回列表页片段的假 Session（响应体按真实无 charset 头构造）。"""
    return FakeSession(lambda url, kw: FakeResponse(list_html, url=url))


@pytest.fixture
def detail_session(detail_html: str) -> FakeSession:
    """返回详情页片段的假 Session。"""
    return FakeSession(lambda url, kw: FakeResponse(detail_html, url=url))


def multi_source_handler(
    list_html: str,
    science_json: str,
    sls_json: str,
    teaching_html: str,
    *,
    fail: set[str] | None = None,
) -> Callable[[str, dict], FakeResponse]:
    """构造一个按 URL 分派的 handler，模拟四个数据源（``fail`` 里的源抛 500）。"""
    fail = fail or set()
    urls = {
        "main": ("https://www.westlake.edu.cn/about/faculty/", list_html),
        "science": (
            "https://science.westlake.edu.cn/chemistry_api/biz/modularity/project247/outLxyTutorList",
            science_json,
        ),
        "sls": ("https://sls.westlake.edu.cn/Our_Faculty/json_401.json", sls_json),
        "teaching": (
            "https://www.westlake.edu.cn/academics/undergraduate_studies/common_courses/TeachingFaculty/",
            teaching_html,
        ),
    }

    def handler(url: str, kw: dict) -> FakeResponse:
        for name, (endpoint, body) in urls.items():
            if url == endpoint:
                if name in fail:
                    return FakeResponse(b"boom", status=500, url=url)
                return FakeResponse(body, url=url)
        return FakeResponse(b"", status=404, url=url)

    return handler