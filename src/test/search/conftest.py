"""search 模块测试的公共 fixture。

``fixture_search_p1.json`` / ``fixture_search_p2.json`` 是 2026-09-22 对真实
接口 ``GET https://www.westlake.edu.cn/was5/web/search?channelid=276758``
（``searchword=西湖``）抓取后**原样保留前导空行、裁剪 data 至 3 条**的响应体，
供离线解析/分页测试使用。
"""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent


def _read(name: str) -> bytes:
    """按字节读出 fixture（保留前导空行，模拟真实响应体）。"""
    return (FIXTURE_DIR / name).read_bytes()


@pytest.fixture(scope="session")
def raw_page1() -> bytes:
    """第 1 页真实响应体（含前导空行）。"""
    return _read("fixture_search_p1.json")


@pytest.fixture(scope="session")
def raw_page2() -> bytes:
    """第 2 页真实响应体（含前导空行）。"""
    return _read("fixture_search_p2.json")


@pytest.fixture(scope="session")
def mojibake_page1(raw_page1: bytes) -> str:
    """模拟 ``requests`` 按 latin-1 解码出的乱码文本。"""
    return raw_page1.decode("latin-1")