"""careers 模块测试的公共 fixture。

``fixture_positions.html`` 是 2026-09-22 对真实招聘主页
``https://www.westlake.edu.cn/careers/OpenPositions/`` 抓取后，**原样保留**
``new career("#app", {...})`` 外壳并裁剪 ``roleList`` 至前 6 条的结果；
``fixture_detail.html`` 同样取自真实详情页，保留 ``topObj`` 全文、``mainStr``
截断到约 1.5 KB。两者都保留真实 JS 结构与中英文逗号混用的 ``type`` 字段。

所有测试离线：网络层用 ``careers_fakes`` 的替身打桩，配置目录重定位到临时目录。
"""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent


def _read_bytes(name: str) -> bytes:
    return (FIXTURE_DIR / name).read_bytes()


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch, tmp_path):
    """把配置根目录重定位到临时目录，避免测试写入真实 ~/.westlake_survival。"""
    monkeypatch.setenv("WESTLAKE_HOME", str(tmp_path / "home"))
    yield tmp_path / "home"


@pytest.fixture(scope="session")
def fixture_positions_html() -> str:
    """真实招聘主页片段（UTF-8 解码）。"""
    return (FIXTURE_DIR / "fixture_positions.html").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def fixture_positions_bytes() -> bytes:
    """真实招聘主页片段的原始字节（模拟无 charset 头的响应体）。"""
    return _read_bytes("fixture_positions.html")


@pytest.fixture(scope="session")
def fixture_positions_mojibake(fixture_positions_bytes: bytes) -> str:
    """模拟 ``requests`` 按 latin-1 解码出的乱码文本。"""
    return fixture_positions_bytes.decode("latin-1")


@pytest.fixture(scope="session")
def fixture_detail_html() -> str:
    """真实岗位详情页片段（UTF-8 解码）。"""
    return (FIXTURE_DIR / "fixture_detail.html").read_text(encoding="utf-8")