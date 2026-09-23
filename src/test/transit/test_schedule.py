"""transit.schedule 离线测试：解析、查表、下一班、兜底。"""

from __future__ import annotations

from datetime import date, datetime, time

import pytest

from westlake_survival.exceptions import ParseError
from westlake_survival.transit import (
    Campus,
    DayKind,
    TransitData,
    parse_schedule,
)
from westlake_survival.transit import schedule as schedule_mod

# 2026-09-22 是星期二（工作日），用作固定时钟。
FIXED_NOW = datetime(2026, 9, 22, 12, 45, tzinfo=schedule_mod.CHINA_TZ)


def test_fixed_now_is_weekday() -> None:
    assert FIXED_NOW.weekday() < 5


def test_parse_fixture_yields_three_campuses_two_daykinds(sample_data: TransitData) -> None:
    assert len(sample_data.tables) == 6
    combos = {(t.campus, t.day_kind) for t in sample_data.tables}
    assert combos == {
        (campus, kind) for campus in Campus for kind in DayKind
    }


def test_parse_weekday_yungu_times(sample_data: TransitData) -> None:
    tbl = sample_data.table(Campus.YUNGU, DayKind.WEEKDAY)
    assert tbl is not None
    assert tbl.morning == ("07:10", "08:40", "09:45", "11:00")
    assert tbl.noon == ("12:30", "13:00", "14:00", "15:30", "17:45")
    assert tbl.night == ("18:30", "19:45", "21:00", "21:15")
    assert tbl.direction_note  # 方向说明非空
    assert "07:10" in tbl.all_times()


def test_parse_tongjianhu_maps_othercar_groups(sample_data: TransitData) -> None:
    tbl = sample_data.table(Campus.TONGJIANHU, DayKind.WEEKDAY)
    assert tbl is not None
    # otherCar1 -> morning, otherCar2 -> noon, night 空
    assert tbl.morning[0] == "06:35"
    assert tbl.noon[0] == "08:20"
    assert tbl.night == ()
    assert "otherCar1" in tbl.direction_note


def test_parse_weekend_yunqi(sample_data: TransitData) -> None:
    tbl = sample_data.table(Campus.YUNQI, DayKind.WEEKEND)
    assert tbl is not None
    assert tbl.morning == ("09:10", "10:10")
    assert tbl.night == ("21:10",)


def test_table_lookup_missing_returns_none(sample_data: TransitData) -> None:
    # 存在的组合返回表。
    assert sample_data.table(Campus.YUNGU, DayKind.WEEKDAY) is not None
    # fixture 恰好覆盖三校区 × 两日别的全部组合，故用一个只含工作日表的
    # TransitData 来真正走到缺失分支；空数据表也返回 None。
    only_weekday = TransitData(tables=[sample_data.table(Campus.YUNGU, DayKind.WEEKDAY)])
    assert only_weekday.table(Campus.YUNGU, DayKind.WEEKEND) is None
    assert only_weekday.table(Campus.YUNQI, DayKind.WEEKDAY) is None
    assert TransitData().table(Campus.YUNGU, DayKind.WEEKDAY) is None
    assert TransitData().table(Campus.YUNQI, DayKind.WEEKEND) is None


def test_next_departures_single_campus(sample_data: TransitData) -> None:
    result = sample_data.next_departures(campus=Campus.YUNGU, now=FIXED_NOW)
    assert [ts for _tbl, ts in result] == ["13:00", "14:00", "15:30"]
    assert all(tbl.campus is Campus.YUNGU for tbl, _ts in result)


def test_next_departures_all_campuses_sorted(sample_data: TransitData) -> None:
    early = datetime(2026, 9, 22, 6, 0, tzinfo=schedule_mod.CHINA_TZ)
    result = sample_data.next_departures(limit=5, now=early)
    assert [ts for _tbl, ts in result] == ["06:35", "06:45", "07:00", "07:10", "07:10"]


def test_next_departures_explicit_after(sample_data: TransitData) -> None:
    result = sample_data.next_departures(after=time(17, 0), campus=Campus.YUNQI, now=FIXED_NOW)
    assert [ts for _tbl, ts in result] == ["17:45", "18:30", "19:45"]


def test_next_departures_rolls_to_next_day(sample_data: TransitData) -> None:
    late = datetime(2026, 9, 22, 23, 30, tzinfo=schedule_mod.CHINA_TZ)
    result = sample_data.next_departures(
        campus=Campus.YUNGU, day_kind=DayKind.WEEKDAY, limit=1, now=late
    )
    assert [ts for _tbl, ts in result] == ["07:10"]


def test_next_departures_weekend_kind(sample_data: TransitData) -> None:
    # 起点是星期二，指定 WEEKEND 会顺延到最近的周末（周六），给当天首班。
    result = sample_data.next_departures(
        campus=Campus.YUNGU, day_kind=DayKind.WEEKEND, now=FIXED_NOW
    )
    assert [ts for _tbl, ts in result] == ["08:00", "09:00", "13:00"]


def test_next_departures_weekend_after_on_weekend_day(sample_data: TransitData) -> None:
    # 起点就是周六时，after 过滤作用于当天。
    saturday = datetime(2026, 9, 26, 12, 45, tzinfo=schedule_mod.CHINA_TZ)
    result = sample_data.next_departures(campus=Campus.YUNGU, now=saturday)
    assert [ts for _tbl, ts in result] == ["13:00", "15:00", "17:00"]


def test_parse_mojibake_encoding(sample_html: str) -> None:
    """模拟共享层按 latin-1 解码页面（中文变乱码）时仍能解析。"""
    mojibake = sample_html.encode("utf-8").decode("latin-1")
    assert "交通方式" not in mojibake  # 确认已乱码
    data = parse_schedule(mojibake)
    assert len(data.tables) == 6


def test_parse_missing_block_raises() -> None:
    with pytest.raises(ParseError):
        parse_schedule("<html><body>no shuttle here</body></html>")


def test_load_falls_back_on_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args, **_kwargs):
        raise ConnectionError("network down")

    monkeypatch.setattr(schedule_mod, "http_get_with_etag", boom)
    data = TransitData.load()
    assert len(data.tables) == 6
    assert data.table(Campus.YUNGU, DayKind.WEEKDAY) is not None


def test_load_parses_network_body(monkeypatch: pytest.MonkeyPatch, sample_html: str) -> None:
    monkeypatch.setattr(
        schedule_mod, "http_get_with_etag", lambda *_a, **_k: (sample_html, "etag")
    )
    data = TransitData.load()
    assert len(data.tables) == 6
    assert data.table(Campus.TONGJIANHU, DayKind.WEEKEND) is not None


def test_calendar_day_kind() -> None:
    assert schedule_mod._calendar_day_kind(date(2026, 9, 22)) is DayKind.WEEKDAY
    assert schedule_mod._calendar_day_kind(date(2026, 9, 26)) is DayKind.WEEKEND
    assert schedule_mod._calendar_day_kind(date(2026, 9, 27)) is DayKind.WEEKEND