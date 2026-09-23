"""news 模块测试的公共 fixture。

``fixture_list.html`` 是从真实「西湖新闻」列表页
``https://www.westlake.edu.cn/news_events/westlakenews/allnews/``（2026-09-22
实测）抽取的 ``new allNews(...)`` 片段：保留真实的 ``turnToEn: function`` 回调
（用于验证"不能整块 js_literal"的坑）与 ``topicsList`` **前 4 条**真实条目。

``fixture_detail.html`` 是从真实详情页
``https://www.westlake.edu.cn/news_events/westlakenews/people/202609/t20260922_69940.html``
抽取的 ``new newsDetail(...)`` 片段，``detailContent`` 裁剪为一段正文。
"""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent


def _read(name: str) -> bytes:
    """按字节读出 fixture。"""
    return (FIXTURE_DIR / name).read_bytes()


@pytest.fixture(scope="session")
def list_html() -> str:
    """按 UTF-8 读出的真实列表页片段。"""
    return _read("fixture_list.html").decode("utf-8")


@pytest.fixture(scope="session")
def list_mojibake() -> str:
    """模拟 ``requests`` 在无 charset 时用 ISO-8859-1 解码出的乱码列表页。"""
    return _read("fixture_list.html").decode("latin-1")


@pytest.fixture(scope="session")
def detail_html() -> str:
    """按 UTF-8 读出的真实详情页片段。"""
    return _read("fixture_detail.html").decode("utf-8")