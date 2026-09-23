"""天气 / AQI 解析、WMO 映射、AQI 分级边界、to_dict 可序列化。"""

from __future__ import annotations

import importlib
import json
from datetime import datetime

import pytest

from westlake_survival.context import CHINA_TZ, Level, aqi_grade, snapshot, wmo_text
from westlake_survival.context.snapshot import WMO_WEATHER_CN, _parse_aqi, _parse_weather

#: 显式取子模块（``from westlake_survival.context import snapshot`` 拿到的是函数）。
snapshot_module = importlib.import_module("westlake_survival.context.snapshot")


# --------------------------------------------------------------------------- #
# 解析（纯函数）
# --------------------------------------------------------------------------- #
def test_parse_weather_fields(weather_payload) -> None:
    parsed = _parse_weather(weather_payload)
    assert parsed["temperature"] == 22.4
    assert parsed["humidity"] == 84
    assert parsed["wind_speed"] == 5.5
    assert parsed["weather_code"] == 1
    assert parsed["text"] == "少云"
    assert len(parsed["daily"]) == 3
    today = parsed["daily"][0]
    assert today["date"] == "2026-09-22"
    assert today["code"] == 3
    assert today["text"] == "阴"
    assert today["tmax"] == 30.0
    assert today["tmin"] == 21.3
    assert today["precip_prob"] == 2


def test_parse_aqi_fields(aqi_payload) -> None:
    parsed = _parse_aqi(aqi_payload)
    assert parsed["pm10"] == 62.6
    assert parsed["pm2_5"] == 55.6
    assert parsed["us_aqi"] == 151
    assert parsed["european_aqi"] == 75
    assert parsed["grade"] == "中度污染"


def test_parse_weather_missing_daily_ok() -> None:
    parsed = _parse_weather({"current": {"weather_code": 0}})
    assert parsed["text"] == "晴"
    assert parsed["daily"] == []


# --------------------------------------------------------------------------- #
# WMO 映射
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("code", "text"),
    [
        (0, "晴"),
        (1, "少云"),
        (2, "多云"),
        (3, "阴"),
        (45, "雾"),
        (48, "雾凇"),
        (51, "毛毛雨"),
        (55, "毛毛雨"),
        (61, "小雨"),
        (65, "大雨"),
        (66, "冻雨"),
        (71, "小雪"),
        (77, "米雪"),
        (80, "阵雨"),
        (82, "强阵雨"),
        (85, "阵雪"),
        (95, "雷暴"),
        (99, "雷暴伴冰雹"),
    ],
)
def test_wmo_mapping(code, text) -> None:
    assert WMO_WEATHER_CN[code] == text
    assert wmo_text(code) == text


def test_wmo_unknown() -> None:
    assert wmo_text(None) == "未知"
    assert wmo_text(1234) == "未知"


# --------------------------------------------------------------------------- #
# AQI 分级边界
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("value", "grade"),
    [
        (None, "未知"),
        (0, "优"),
        (50, "优"),
        (51, "良"),
        (100, "良"),
        (101, "轻度污染"),
        (150, "轻度污染"),
        (151, "中度污染"),
        (200, "中度污染"),
        (201, "重度污染"),
        (300, "重度污染"),
        (301, "严重污染"),
        (500, "严重污染"),
    ],
)
def test_aqi_grade_boundaries(value, grade) -> None:
    assert aqi_grade(value) == grade


# --------------------------------------------------------------------------- #
# 集成：mock 掉 fetch 后 VERBOSE 档
# --------------------------------------------------------------------------- #
def test_verbose_weather_in_dict_and_str(monkeypatch, weather_payload, aqi_payload) -> None:
    monkeypatch.setattr(snapshot_module, "fetch_weather", lambda *a, **k: _parse_weather(weather_payload))
    monkeypatch.setattr(snapshot_module, "fetch_aqi", lambda *a, **k: _parse_aqi(aqi_payload))

    ctx = snapshot(Level.VERBOSE, now=datetime(2026, 9, 22, 8, 30, tzinfo=CHINA_TZ))
    data = ctx.to_dict()
    assert data["weather"]["temperature"] == 22.4
    assert data["weather"]["text"] == "少云"
    assert data["aqi"]["grade"] == "中度污染"

    text = ctx.to_str()
    assert "少云" in text
    assert "湿度 84%" in text
    assert "中度污染" in text
    assert "今日" in text
    assert "明日" in text


def test_verbose_without_weather_shows_placeholder(monkeypatch) -> None:
    monkeypatch.setattr(snapshot_module, "fetch_weather", lambda *a, **k: None)
    monkeypatch.setattr(snapshot_module, "fetch_aqi", lambda *a, **k: None)
    ctx = snapshot(Level.VERBOSE, now=datetime(2026, 9, 22, 8, 30, tzinfo=CHINA_TZ))
    assert ctx.to_str().count("（暂无）") >= 1


# --------------------------------------------------------------------------- #
# to_dict JSON 可序列化（含天气/AQI/截止）
# --------------------------------------------------------------------------- #
def test_to_dict_is_json_serializable(monkeypatch, weather_payload, aqi_payload) -> None:
    from westlake_survival.canvas.models import Assignment

    monkeypatch.setattr(snapshot_module, "fetch_weather", lambda *a, **k: _parse_weather(weather_payload))
    monkeypatch.setattr(snapshot_module, "fetch_aqi", lambda *a, **k: _parse_aqi(aqi_payload))
    monkeypatch.setattr(
        snapshot_module.Context,
        "_compute_next_deadlines",
        lambda self: [
            Assignment(
                id=1,
                course_id=42,
                name="HW1",
                due_at=datetime(2026, 9, 25, 23, 59, tzinfo=CHINA_TZ),
                html_url="https://canvas.westlake.edu.cn/courses/42/assignments/1",
            )
        ],
    )

    ctx = snapshot(Level.VERBOSE, now=datetime(2026, 9, 22, 8, 30, tzinfo=CHINA_TZ))
    data = ctx.to_dict()
    dumped = json.dumps(data, ensure_ascii=False)  # 直接过
    assert "HW1" in dumped
    assert data["next_deadlines"][0]["due_at"] == "2026-09-25T23:59:00+08:00"
    assert data["level"] == "verbose"
    # 截止渲染带剩余天数
    assert "3天后" in ctx.to_str()