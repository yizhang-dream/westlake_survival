"""events 模块测试的公共 fixture。

``fixture_events_list.html`` / ``fixture_events_detail.html`` 是 2026-09-22
对真实页面抓取后裁剪得到的 ``new events(...)`` / ``new eventsDetail(...)``
内联片段：列表页保留 ``eventList`` 前 6 条真实条目（含 ``mounted: function
() {}`` 回调），详情页保留 ``left`` / ``right`` 真实键。

``WESTLAKE_HOME`` 被重定位到临时目录，避免污染本机 ETag 缓存。
"""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent


@pytest.fixture(scope="session")
def fixture_list_text() -> str:
    """真实列表页片段（UTF-8 文本）。"""
    return (FIXTURE_DIR / "fixture_events_list.html").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def fixture_list_mojibake() -> str:
    """模拟 ``requests`` 无 charset 时按 ISO-8859-1 解码出的乱码文本。"""
    return (FIXTURE_DIR / "fixture_events_list.html").read_bytes().decode("latin-1")


@pytest.fixture(scope="session")
def fixture_detail_text() -> str:
    """真实详情页片段（UTF-8 文本）。"""
    return (FIXTURE_DIR / "fixture_events_detail.html").read_text(encoding="utf-8")


@pytest.fixture
def isolated_home(monkeypatch, tmp_path):
    """把配置根目录重定位到临时目录，隔离 ETag 缓存。"""
    home = tmp_path / "home"
    monkeypatch.setenv("WESTLAKE_HOME", str(home))
    return home