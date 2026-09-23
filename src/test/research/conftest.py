"""research 模块测试的公共 fixture。

``fixture_list.html`` 是从真实「科研进展」列表页
``https://www.westlake.edu.cn/research/research_at_westlake/``（2026-09-23 实测）
抽取的 ``new researchWestlake(...)`` 片段：保留真实的 ``mounted: function``
回调（用于验证"不能整块 js_literal"的坑）与 ``researchList`` **前 2 个分组**
（各裁剪至前几条真实条目），以及 ``brief`` / ``topCountList``。

``fixture_detail.html`` 取自真实详情页
``https://www.westlake.edu.cn/research/research_at_westlake/good_health_wellbeing/202510/t20251016_60343.html``，
是 ``new newsDetail(...)`` 片段，``detailContent`` 裁剪为两段正文。

两者均小于 80 行。
"""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent


def _read(name: str) -> bytes:
    """按字节读出 fixture。"""
    return (FIXTURE_DIR / name).read_bytes()


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch, tmp_path):
    """把配置根目录重定位到临时目录，避免测试写入真实 ~/.westlake_survival。"""
    monkeypatch.setenv("WESTLAKE_HOME", str(tmp_path / "home"))
    yield tmp_path / "home"


@pytest.fixture(scope="session")
def list_html() -> str:
    """按 UTF-8 读出的真实列表页片段。"""
    return _read("fixture_list.html").decode("utf-8")


@pytest.fixture(scope="session")
def list_bytes() -> bytes:
    """真实列表页片段的原始字节（模拟无 charset 头的响应体）。"""
    return _read("fixture_list.html")


@pytest.fixture(scope="session")
def list_mojibake(list_bytes: bytes) -> str:
    """模拟 ``requests`` 在无 charset 时用 ISO-8859-1 解码出的乱码列表页。"""
    return list_bytes.decode("latin-1")


@pytest.fixture(scope="session")
def detail_html() -> str:
    """按 UTF-8 读出的真实详情页片段。"""
    return _read("fixture_detail.html").decode("utf-8")
