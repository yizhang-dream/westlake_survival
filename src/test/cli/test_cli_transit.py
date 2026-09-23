"""``westlake transit`` 命令测试（打桩 transit() 单例）。"""

from __future__ import annotations

from westlake_survival.transit import (
    FALLBACK_TABLES,
    Campus,
    DayKind,
    ShuttleTable,
    TransitData,
)

_DATA = TransitData(tables=list(FALLBACK_TABLES))


def test_transit_next_uses_stubbed_data(runner, cli_group, monkeypatch) -> None:
    import westlake_survival.transit as transit_pkg

    monkeypatch.setattr(transit_pkg, "transit", lambda refresh=False: _DATA)
    result = runner.invoke(cli_group, ["transit", "next", "--limit", "2"])
    assert result.exit_code == 0, result.output
    assert "始发校区" in result.output


def test_transit_next_campus_filter(runner, cli_group, monkeypatch) -> None:
    import westlake_survival.transit as transit_pkg

    captured = {}

    class FakeData:
        def next_departures(self, *, campus=None, limit=3, **kwargs):
            captured["campus"] = campus
            captured["limit"] = limit
            return []

    monkeypatch.setattr(transit_pkg, "transit", lambda refresh=False: FakeData())
    result = runner.invoke(cli_group, ["transit", "next", "--campus", "云谷", "--limit", "5"])
    assert result.exit_code == 0
    assert captured["campus"] == Campus.YUNGU
    assert captured["limit"] == 5
    assert "暂无后续班车" in result.output


def test_transit_table_renders(runner, cli_group, monkeypatch) -> None:
    table = ShuttleTable(
        campus=Campus.YUNGU,
        day_kind=DayKind.WEEKDAY,
        direction_note="测试方向",
        morning=("07:10",),
        noon=("12:30",),
        night=(),
    )
    data = TransitData(tables=[table])
    import westlake_survival.transit as transit_pkg

    monkeypatch.setattr(transit_pkg, "transit", lambda refresh=False: data)
    result = runner.invoke(cli_group, ["transit", "table", "--campus", "云谷", "--day", "工作日"])
    assert result.exit_code == 0
    assert "07:10" in result.output
    assert "测试方向" in result.output


def test_transit_ical_stdout(runner, cli_group, monkeypatch) -> None:
    import westlake_survival.transit as transit_pkg

    monkeypatch.setattr(transit_pkg, "transit", lambda refresh=False: _DATA)
    result = runner.invoke(cli_group, ["transit", "ical", "--days", "1"])
    assert result.exit_code == 0
    assert result.output.startswith("BEGIN:VCALENDAR")


def test_transit_ical_out_file(runner, cli_group, monkeypatch, tmp_path) -> None:
    import westlake_survival.transit as transit_pkg

    monkeypatch.setattr(transit_pkg, "transit", lambda refresh=False: _DATA)
    target = tmp_path / "shuttle.ics"
    result = runner.invoke(cli_group, ["transit", "ical", "--days", "1", "--out", str(target)])
    assert result.exit_code == 0, result.output
    assert target.exists()
    assert target.read_text(encoding="utf-8").startswith("BEGIN:VCALENDAR")
