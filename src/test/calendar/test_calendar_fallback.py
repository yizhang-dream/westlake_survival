"""离线兜底与在线加载路径的测试（网络均被 monkeypatch 替换）。"""

from __future__ import annotations

import logging
from datetime import date

import pytest
import requests

from westlake_survival import calendar as calendar_module
from westlake_survival.calendar import AcademicCalendar


def test_fallback_when_network_fails(monkeypatch, caplog) -> None:
    def boom(*args, **kwargs):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(calendar_module, "http_get_with_etag", boom)
    with caplog.at_level(logging.WARNING, logger="westlake_survival.calendar"):
        cal = AcademicCalendar.load()

    assert [s.name for s in cal.semesters] == ["2026年春季", "2026年秋季"]
    assert len(cal.semesters[1].events) == 19
    assert cal.current(date(2026, 9, 22)) is cal.semesters[1]
    assert any("抓取校历失败" in r.message for r in caplog.records)


def test_fallback_when_page_structure_changes(monkeypatch, caplog) -> None:
    """官网改版导致解析抛 ParseError 时，load() 同样回退内置数据。

    抓取本身成功（返回 200 的乱页），但页面里已没有 ``new calendar(...)``
    数据块，``parse_calendar`` 会抛解析异常。对齐 transit 口径：不向上抛，
    而是返回内置 ``FALLBACK_DATA`` 构建的校历。
    """
    # 改版后的页面：没有任何 seasonList / contentList 数据块。
    revamped_html = "<html><body><div id='app'></div><p>校历页面维护中</p></body></html>"
    monkeypatch.setattr(
        calendar_module, "http_get_with_etag", lambda *a, **k: (revamped_html, "etag")
    )
    with caplog.at_level(logging.WARNING, logger="westlake_survival.calendar"):
        cal = AcademicCalendar.load()  # 不应抛异常

    fallback = AcademicCalendar.from_fallback()
    assert [s.name for s in cal.semesters] == [s.name for s in fallback.semesters]
    assert len(cal.semesters) == len(calendar_module.FALLBACK_DATA)
    for got, expected in zip(cal.semesters, fallback.semesters):
        assert len(got.events) == len(expected.events)
    assert any("解析校历失败" in r.message for r in caplog.records)


def test_load_uses_fetched_html(monkeypatch, fixture_mojibake: str) -> None:
    # http_get_with_etag 返回的是 requests 解码后的文本（此处模拟乱码）。
    monkeypatch.setattr(
        calendar_module, "http_get_with_etag", lambda *a, **k: (fixture_mojibake, None)
    )
    cal = AcademicCalendar.load()
    assert [s.name for s in cal.semesters] == ["2026年春季", "2026年秋季"]


def test_load_passes_url_and_cache_name(monkeypatch) -> None:
    captured = {}

    def fake_get(url, *, cache_name, **kwargs):
        captured["url"] = url
        captured["cache_name"] = cache_name
        return "<html>seasonList: [\"x\"], contentList: [[{title:\"课程开始\",time:\"2026-01-01\",endtime:\"\"},{title:\"课程结束\",time:\"2026-02-01\",endtime:\"\"}]]</html>", "etag"

    monkeypatch.setattr(calendar_module, "http_get_with_etag", fake_get)
    cal = AcademicCalendar.load()
    assert captured["url"] == calendar_module.CALENDAR_URL
    assert captured["cache_name"] == calendar_module.CACHE_NAME
    assert cal.semesters[0].name == "x"


def test_from_fallback_is_offline_safe() -> None:
    cal = AcademicCalendar.from_fallback()
    fall = cal.semesters[1]
    assert fall.start.isoformat() == "2026-08-31"
    assert fall.end.isoformat() == "2026-12-25"
    assert len(fall.exams()) == 1


def test_fallback_exam_week_and_teaching_weeks_regression() -> None:
    """离线兜底同样要把考试周算进学期，且教学周数不变（P1 回归）。"""
    cal = AcademicCalendar.from_fallback()
    fall = cal.semesters[1]
    assert fall.teaching_weeks() == 17  # 教学周数语义不变
    assert fall.last_day == date(2027, 1, 22)  # 含"课程成绩提交截止"事件
    assert fall.week_of(date(2026, 12, 28)) is not None
    assert cal.current(date(2027, 1, 1)) is fall