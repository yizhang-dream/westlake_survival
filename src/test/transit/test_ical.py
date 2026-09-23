"""transit.ical 离线测试：VCALENDAR 结构与 DTSTART 格式。"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone

from westlake_survival.transit import Campus
from westlake_survival.transit.ical import transit_to_ical

TODAY = date(2026, 9, 22)  # 星期二
AHEAD = 14
DTSTAMP = datetime(2026, 9, 22, 0, 0, tzinfo=timezone.utc)


def _ical(sample_data, **kwargs) -> str:
    return transit_to_ical(AHEAD, data=sample_data, today=TODAY, now=DTSTAMP, **kwargs)


def test_ical_wrapped_and_unfolded(sample_data) -> None:
    text = _ical(sample_data)
    assert text.startswith("BEGIN:VCALENDAR\r\n")
    assert text.rstrip("\r\n").endswith("END:VCALENDAR")
    assert "VERSION:2.0" in text
    assert text.count("BEGIN:VEVENT") == text.count("END:VEVENT")


def test_ical_event_count(sample_data) -> None:
    text = _ical(sample_data)
    # 9/22~10/5 含 10 个工作日 + 4 个周末日。
    # 工作日每天 52 班（云谷13+云栖13+铜鉴湖26），周末每天 24 班。
    assert text.count("BEGIN:VEVENT") == 10 * 52 + 4 * 24


def test_ical_dtstart_floating_format(sample_data) -> None:
    text = _ical(sample_data)
    dtstarts = re.findall(r"DTSTART:(\S+)", text)
    assert dtstarts, "no DTSTART found"
    for value in dtstarts:
        assert re.fullmatch(r"\d{8}T\d{6}", value), value
        assert not value.endswith("Z")  # 浮动本地时间


def test_ical_dates_within_range(sample_data) -> None:
    text = _ical(sample_data)
    dates = {m[:8] for m in re.findall(r"DTSTART:(\d{8})T", text)}
    assert min(dates) == "20260922"
    assert max(dates) == "20261005"


def test_ical_uid_and_summary(sample_data) -> None:
    text = _ical(sample_data)
    uids = re.findall(r"UID:(\S+)", text)
    assert len(uids) == len(set(uids))  # UID 唯一
    pattern = re.compile(
        r"shuttle-(YUNGU|YUNQI|TONGJIANHU)-(WEEKDAY|WEEKEND)-\d{8}-\d{4}@westlake_survival"
    )
    for uid in uids:
        assert pattern.fullmatch(uid), uid
    assert "SUMMARY:校巴 云谷始发 13:00" in text  # 周二 13:00 云谷始发


def test_ical_weekend_events_use_weekend_times(sample_data) -> None:
    text = _ical(sample_data)
    # 2026-09-26 是周六：云谷首班应为周末表 08:00，而非工作日的 07:10。
    assert "DTSTART:20260926T080000" in text
    assert "DTSTART:20260926T071000" not in text


def test_ical_tongjianhu_included(sample_data) -> None:
    text = _ical(sample_data)
    assert "shuttle-TONGJIANHU-WEEKDAY" in text
    assert "校巴 铜鉴湖始发" in text
    assert Campus.TONGJIANHU.value in text


def test_ical_single_day(sample_data) -> None:
    text = transit_to_ical(1, data=sample_data, today=TODAY, now=DTSTAMP)
    # 星期二仅工作日表：13+13+26 = 52 班。
    assert text.count("BEGIN:VEVENT") == 52
    assert "shuttle-YUNGU-WEEKDAY-20260922" in text
    assert "WEEKEND-20260922" not in text  # 周二不应出现周末表