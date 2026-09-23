"""transit 测试共享 fixture。"""

from __future__ import annotations

from pathlib import Path

import pytest

from westlake_survival.transit import parse_schedule

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_html() -> str:
    """离线 fixture：按官网实测结构构造的「住宿餐饮」页面。"""
    return (FIXTURES / "housing_dining.html").read_text(encoding="utf-8")


@pytest.fixture
def sample_data(sample_html: str):
    """从 fixture 解析出的 TransitData。"""
    return parse_schedule(sample_html)