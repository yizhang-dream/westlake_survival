"""calendar 模块测试的公共 fixture。

``fixture_home.html`` 是从真实校历主页
``https://www.westlake.edu.cn/academics/academic_calendar/``
抽取的 ``new calendar(...)`` 片段（2026-09-22 实测），保持真实 JS 结构与
日期格式，供离线解析测试使用。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from westlake_survival.calendar import AcademicCalendar, parse_calendar

FIXTURE_PATH = Path(__file__).parent / "fixture_home.html"


@pytest.fixture(scope="session")
def fixture_text() -> str:
    """按 UTF-8 读出的真实页面片段。"""
    return FIXTURE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def fixture_mojibake() -> str:
    """模拟 ``requests`` 在无 charset 时用 ISO-8859-1 解码出的乱码文本。"""
    return FIXTURE_PATH.read_bytes().decode("latin-1")


@pytest.fixture(scope="session")
def calendar(fixture_text: str) -> AcademicCalendar:
    return parse_calendar(fixture_text)