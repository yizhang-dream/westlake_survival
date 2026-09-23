"""``westlake calendar`` 命令测试。"""

from __future__ import annotations

from datetime import date

import pytest

from westlake_survival.calendar import AcademicCalendar, CalendarEvent, Semester
from westlake_survival.cli import main as main_mod


@pytest.fixture
def fallback_calendar(monkeypatch):
    """把 ``AcademicCalendar.load`` 打桩为内置 fallback 数据。"""
    calendar = AcademicCalendar.from_fallback()
    monkeypatch.setattr(
        main_mod.AcademicCalendar, "load", classmethod(lambda cls, refresh=False: calendar)
    )
    return calendar


def test_calendar_today_shows_week(runner, cli_group, fallback_calendar, monkeypatch) -> None:
    """today 输出应包含「第」「周」。"""
    # 2026-09-22 落在 2026 秋季学期。
    class FakeDate(date):
        @classmethod
        def today(cls):
            return date(2026, 9, 22)

    monkeypatch.setattr(main_mod, "date", FakeDate)
    result = runner.invoke(cli_group, ["calendar", "today"])
    assert result.exit_code == 0, result.output
    assert "第" in result.output
    assert "周" in result.output
    assert "2026-09-22" in result.output


def test_calendar_events_lists_table(runner, cli_group, fallback_calendar, monkeypatch) -> None:
    class FakeDate(date):
        @classmethod
        def today(cls):
            return date(2026, 9, 22)

    monkeypatch.setattr(main_mod, "date", FakeDate)
    result = runner.invoke(cli_group, ["calendar", "events"])
    assert result.exit_code == 0
    assert "期末考试周" in result.output


def test_calendar_week_range(runner, cli_group, fallback_calendar, monkeypatch) -> None:
    class FakeDate(date):
        @classmethod
        def today(cls):
            return date(2026, 9, 22)

    monkeypatch.setattr(main_mod, "date", FakeDate)
    result = runner.invoke(cli_group, ["calendar", "week", "1"])
    assert result.exit_code == 0
    # 第 1 周周一 = 含 2026-08-31 那一周的周一 = 2026-08-31。
    assert "2026-08-31" in result.output
    assert "2026-09-06" in result.output


def test_calendar_week_out_of_range(runner, cli_group, fallback_calendar, monkeypatch) -> None:
    class FakeDate(date):
        @classmethod
        def today(cls):
            return date(2026, 9, 22)

    monkeypatch.setattr(main_mod, "date", FakeDate)
    result = runner.invoke(cli_group, ["calendar", "week", "99"])
    assert result.exit_code == 1
    assert "超出" in result.stderr


def test_calendar_today_accepts_manual_calendar(monkeypatch) -> None:
    """用构造的极简学期验证 today 的周次计算（不依赖 fallback）。"""
    from click.testing import CliRunner

    semester = Semester(
        name="测试学期",
        start=date(2026, 9, 1),
        end=date(2026, 12, 20),
        events=[CalendarEvent(title="测试事件", start=date(2026, 9, 10))],
    )
    calendar = AcademicCalendar(semesters=[semester])
    monkeypatch.setattr(
        main_mod.AcademicCalendar, "load", classmethod(lambda cls, refresh=False: calendar)
    )

    class FakeDate(date):
        @classmethod
        def today(cls):
            return date(2026, 9, 10)

    monkeypatch.setattr(main_mod, "date", FakeDate)
    result = CliRunner().invoke(main_mod.cli, ["calendar", "today"])
    assert result.exit_code == 0
    assert "第 2 周" in result.output
    assert "测试事件" in result.output
