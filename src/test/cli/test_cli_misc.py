"""sis / lib / pms / transit 命令与统一错误处理测试。"""

from __future__ import annotations

from datetime import date, time

from westlake_survival.exceptions import AuthError, OffCampusError, ParseError
from westlake_survival.cli import main as main_mod


# --------------------------------------------------------------------------- #
# sis
# --------------------------------------------------------------------------- #
def test_sis_schedule_renders(runner, cli_group, monkeypatch) -> None:
    import westlake_survival.sis as sis_pkg

    class FakeSession:
        title = "高等数学"
        teacher = "张老师"
        weekday = 1
        start_time = time(8, 0)
        end_time = time(9, 35)
        room = "A101"

    monkeypatch.setattr(sis_pkg, "get_schedule", lambda **kw: [FakeSession()])
    result = runner.invoke(cli_group, ["sis", "schedule"])
    assert result.exit_code == 0
    assert "高等数学" in result.output
    assert "周一" in result.output
    assert "08:00-09:35" in result.output


def test_sis_schedule_empty(runner, cli_group, monkeypatch) -> None:
    import westlake_survival.sis as sis_pkg

    monkeypatch.setattr(sis_pkg, "get_schedule", lambda **kw: [])
    result = runner.invoke(cli_group, ["sis", "schedule"])
    assert result.exit_code == 0
    assert "课表为空" in result.output


def test_sis_ical_writes_file(runner, cli_group, monkeypatch, tmp_path) -> None:
    import westlake_survival.ical as ical_pkg
    import westlake_survival.sis as sis_pkg

    session = object()
    monkeypatch.setattr(sis_pkg, "get_schedule", lambda **kw: [session])
    monkeypatch.setattr(ical_pkg, "save_ics", lambda sessions, path: tmp_path / "s.ics")
    target = tmp_path / "s.ics"
    result = runner.invoke(cli_group, ["sis", "ical", "--out", str(target)])
    assert result.exit_code == 0
    assert "已写入" in result.output


def test_sis_ical_empty_errors(runner, cli_group, monkeypatch) -> None:
    import westlake_survival.sis as sis_pkg

    monkeypatch.setattr(sis_pkg, "get_schedule", lambda **kw: [])
    result = runner.invoke(cli_group, ["sis", "ical"])
    assert result.exit_code == 1
    assert "课表为空" in result.stderr


def test_sis_schedule_auth_error(runner, cli_group, monkeypatch) -> None:
    import westlake_survival.sis as sis_pkg

    def boom(**kw):
        raise AuthError("会话未认证")

    monkeypatch.setattr(sis_pkg, "get_schedule", boom)
    result = runner.invoke(cli_group, ["sis", "schedule"])
    assert result.exit_code == 1
    assert "错误" in result.stderr


# --------------------------------------------------------------------------- #
# lib
# --------------------------------------------------------------------------- #
def test_lib_search_renders(runner, cli_group, monkeypatch) -> None:
    import westlake_survival.lib as lib_pkg

    class FakeBook:
        title = "机器学习"
        author = "周志华"
        call_no = "TP181/Z78"
        location = "云谷校区"

    monkeypatch.setattr(lib_pkg, "search", lambda kw, *, page=1: [FakeBook()])
    result = runner.invoke(cli_group, ["lib", "search", "机器学习"])
    assert result.exit_code == 0
    assert "机器学习" in result.output
    assert "周志华" in result.output


def test_lib_search_empty(runner, cli_group, monkeypatch) -> None:
    import westlake_survival.lib as lib_pkg

    monkeypatch.setattr(lib_pkg, "search", lambda kw, *, page=1: [])
    result = runner.invoke(cli_group, ["lib", "search", "不存在的书"])
    assert result.exit_code == 0
    assert "未找到" in result.output


def test_lib_loans_renders(runner, cli_group, monkeypatch) -> None:
    import westlake_survival.lib as lib_pkg

    class FakeLoan:
        title = "深入理解计算机系统"
        due_date = "2026-10-15"
        renewable = True
        location = "云栖校区"

    monkeypatch.setattr(lib_pkg, "my_loans", lambda: [FakeLoan()])
    result = runner.invoke(cli_group, ["lib", "loans"])
    assert result.exit_code == 0
    assert "2026-10-15" in result.output
    assert "可续借" in result.output


def test_lib_loans_offcampus_hint(runner, cli_group, monkeypatch) -> None:
    import westlake_survival.lib as lib_pkg

    def boom():
        raise OffCampusError("仅校园网可达")

    monkeypatch.setattr(lib_pkg, "my_loans", boom)
    result = runner.invoke(cli_group, ["lib", "loans"])
    assert result.exit_code == 1
    assert "vpn.westlake.edu.cn" in result.stderr


# --------------------------------------------------------------------------- #
# pms
# --------------------------------------------------------------------------- #
def test_pms_stations_renders(runner, cli_group, monkeypatch) -> None:
    import westlake_survival.pms as pms_pkg

    class FakeStation:
        name = "图书馆1楼"
        campus = "云谷"
        position = "图书馆"
        room_name = "101"
        status_text = "空闲"
        is_idle = True
        papers = ["A4"]

    class FakeClient:
        def list_stations(self):
            return [FakeStation()]

    monkeypatch.setattr(pms_pkg, "pms", lambda *a, **k: FakeClient())
    result = runner.invoke(cli_group, ["pms", "stations"])
    assert result.exit_code == 0
    assert "图书馆1楼" in result.output
    assert "A4" in result.output


def test_pms_jobs_renders(runner, cli_group, monkeypatch) -> None:
    import westlake_survival.pms as pms_pkg

    class FakeJob:
        name = "hw.pdf"
        copies = 2
        pages = 10
        status_text = "待打印"

    class FakeClient:
        def list_print_jobs(self):
            return [FakeJob()]

    monkeypatch.setattr(pms_pkg, "pms", lambda *a, **k: FakeClient())
    result = runner.invoke(cli_group, ["pms", "jobs"])
    assert result.exit_code == 0
    assert "hw.pdf" in result.output
    assert "待打印" in result.output


def test_pms_stations_parse_error_exit_1(runner, cli_group, monkeypatch) -> None:
    import westlake_survival.pms as pms_pkg

    class FakeClient:
        def list_stations(self):
            raise ParseError("响应结构变化")

    monkeypatch.setattr(pms_pkg, "pms", lambda *a, **k: FakeClient())
    result = runner.invoke(cli_group, ["pms", "stations"])
    assert result.exit_code == 1
    assert "响应结构变化" in result.stderr


# --------------------------------------------------------------------------- #
# 通用：WestlakeError → exit 1 + 中文 stderr
# --------------------------------------------------------------------------- #
def test_generic_westlake_error_exit_code_and_chinese_stderr(runner, cli_group, monkeypatch) -> None:
    import westlake_survival.transit as transit_pkg

    def boom(refresh=False):
        raise ParseError("时刻表解析失败")

    monkeypatch.setattr(transit_pkg, "transit", boom)
    result = runner.invoke(cli_group, ["transit", "next"])
    assert result.exit_code == 1
    assert "错误" in result.stderr
    assert "时刻表解析失败" in result.stderr
