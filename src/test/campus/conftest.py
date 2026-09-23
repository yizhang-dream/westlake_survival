"""campus 模块测试的公共 fixture。

``fixture_housing_dining.html`` 是从真实「餐饮住宿」页面
``https://www.westlake.edu.cn/campus_life/housing_dining/``（2026-09-22 实测）
裁剪的 ``new housingDining(...)`` 片段：保留 ``allData`` 结构与真实 HTML
换行变体，住宿/食堂/咖啡轻食/其他校园服务各留若干条，交通方式只留 notice 外链。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from westlake_survival.campus import CampusData, parse_campus

FIXTURE_PATH = Path(__file__).parent / "fixture_housing_dining.html"


@pytest.fixture(scope="session")
def fixture_text() -> str:
    """按 UTF-8 读出的真实页面片段。"""
    return FIXTURE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def fixture_mojibake(fixture_text: str) -> str:
    """模拟 ``requests`` 在无 charset 时用 ISO-8859-1 解码出的乱码文本。"""
    return fixture_text.encode("utf-8").decode("latin-1")


@pytest.fixture(scope="session")
def campus_data(fixture_text: str) -> CampusData:
    return parse_campus(fixture_text)