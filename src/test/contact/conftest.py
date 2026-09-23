"""contact 模块测试的公共 fixture。

``fixture_contact.html`` 是 2026-09-22 对真实页面
``https://www.westlake.edu.cn/about/contact_us/`` 抓取后裁剪的
``new contactUs("#app", {...})`` 片段（见文件头注释），保留真实 JS 结构、
``<br>`` 变体、``function`` 回调与 contactList 富文本，供离线解析测试使用。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from westlake_survival.contact import ContactPage, parse

FIXTURE_PATH = Path(__file__).parent / "fixture_contact.html"


@pytest.fixture(scope="session")
def fixture_text() -> str:
    """按 UTF-8 读出的真实页面片段。"""
    return FIXTURE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def fixture_bytes() -> bytes:
    """真实页面的 UTF-8 字节（模拟 ``response.content``）。"""
    return FIXTURE_PATH.read_bytes()


@pytest.fixture(scope="session")
def page(fixture_text: str) -> ContactPage:
    """解析 fixture 得到的 :class:`ContactPage`。"""
    return parse(fixture_text)
