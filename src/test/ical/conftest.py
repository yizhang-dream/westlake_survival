"""src/test/ical 的公共夹具：构造课表节次。"""

from __future__ import annotations

from datetime import date, time

import pytest

from westlake_survival.sis import ClassSession


@pytest.fixture
def thursday_course() -> ClassSession:
    """每周四 13:30-15:55，2026-03-05（周四）~ 2026-06-18（周四）。"""
    return ClassSession(
        title="计算机程序设计",
        course_code="CS101",
        teacher="张三",
        room="H6-303",
        weekday=4,
        start_time=time(13, 30),
        end_time=time(15, 55),
        date_start=date(2026, 3, 5),
        date_end=date(2026, 6, 18),
    )


@pytest.fixture
def monday_course() -> ClassSession:
    """每周一 10:40-12:15，2026-03-09（周一）~ 2026-06-15（周一）。"""
    return ClassSession(
        title="普通物理学",
        course_code="PHY200",
        teacher="王五",
        room="A-101",
        weekday=1,
        start_time=time(10, 40),
        end_time=time(12, 15),
        date_start=date(2026, 3, 9),
        date_end=date(2026, 6, 15),
    )


@pytest.fixture
def single_day_course() -> ClassSession:
    """单次课：2026-04-10（周五）18:30-20:05。"""
    return ClassSession(
        title="形势与政策",
        course_code="SEM101",
        teacher="孙八",
        room="报告厅",
        weekday=5,
        start_time=time(18, 30),
        end_time=time(20, 5),
        date_start=date(2026, 4, 10),
        date_end=date(2026, 4, 10),
    )