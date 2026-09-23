"""MCP 只读工具的清单、分发与错误处理测试（离线，业务模块打桩）。"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from westlake_survival import mcp_server as mcp


def _call(name: str, arguments: dict | None = None) -> dict:
    """经 ``tools/call`` 协议路径调用工具，返回 result 对象。"""
    response = json.loads(
        mcp.handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": name, "arguments": arguments or {}},
                }
            )
        )
    )
    assert "result" in response, response
    return response["result"]


def _patch_calendar(monkeypatch, calendar_mod, cal) -> None:
    """把 ``AcademicCalendar.load`` 换成返回固定校历的桩。"""
    monkeypatch.setattr(
        calendar_mod.AcademicCalendar, "load", classmethod(lambda cls, refresh=False: cal)
    )


def _payload(name: str, arguments: dict | None = None):
    """调用工具并解出 content 里的紧凑 JSON 文本。"""
    result = _call(name, arguments)
    assert "isError" not in result, result
    assert len(result["content"]) == 1
    block = result["content"][0]
    assert block["type"] == "text"
    return json.loads(block["text"])


# --------------------------------------------------------------------------- #
# tools/list
# --------------------------------------------------------------------------- #
def test_tools_list_count_and_shape() -> None:
    """``tools/list`` 返回 17 个工具，每个字段齐备。"""
    response = json.loads(
        mcp.handle_line('{"jsonrpc":"2.0","id":1,"method":"tools/list"}')
    )
    tools = response["result"]["tools"]
    assert len(tools) == 17
    names = [tool["name"] for tool in tools]
    assert len(set(names)) == len(names)
    assert set(names) == {
        "sis_schedule",
        "sis_grades",
        "sis_exams",
        "sis_evals_pending",
        "calendar_today",
        "calendar_week",
        "transit_next",
        "news_latest",
        "events_upcoming",
        "research_latest",
        "site_search",
        "faculty_search",
        "campus_dining",
        "campus_housing",
        "contact_info",
        "context_snapshot",
        "canvas_deadlines",
    }


def test_tools_list_schemas_are_valid_json_schema() -> None:
    """每个 inputSchema 都是 object 型合法 JSON Schema（属性类型可识别）。"""
    tools = mcp.list_tools()
    for tool in tools:
        schema = tool["inputSchema"]
        assert schema["type"] == "object", tool["name"]
        assert isinstance(schema.get("properties"), dict), tool["name"]
        for prop, sub in schema["properties"].items():
            assert sub["type"] in {"string", "integer", "number", "boolean", "array", "object"}
            if sub["type"] == "integer":
                assert isinstance(sub.get("minimum"), int), (tool["name"], prop)
        for key in schema.get("required", []):
            assert key in schema["properties"], (tool["name"], key)
        assert tool["description"], tool["name"]


def test_tools_call_unknown_tool_returns_invalid_params() -> None:
    """未注册的工具名属协议错误：-32602。"""
    response = json.loads(
        mcp.handle_line(
            '{"jsonrpc":"2.0","id":9,"method":"tools/call",'
            '"params":{"name":"nope","arguments":{}}}'
        )
    )
    assert response["error"]["code"] == mcp.INVALID_PARAMS


def test_tools_call_missing_name_returns_invalid_params() -> None:
    """``tools/call`` 缺 name 返回 -32602。"""
    response = json.loads(
        mcp.handle_line('{"jsonrpc":"2.0","id":9,"method":"tools/call","params":{}}')
    )
    assert response["error"]["code"] == mcp.INVALID_PARAMS


# --------------------------------------------------------------------------- #
# tools/call 分发（monkeypatch 各模块公开函数）
# --------------------------------------------------------------------------- #
def test_news_latest_passes_limit_and_serializes(monkeypatch) -> None:
    import westlake_survival.news as news

    captured = {}

    class Item:
        title = "某条新闻"
        category = "资讯"
        date = datetime(2026, 9, 22, 10, 0, 0)
        url = "https://example.test/n.html"

    def fake_latest(category=None, limit=None, **kwargs):
        captured["limit"] = limit
        return [Item()]

    monkeypatch.setattr(news, "latest", fake_latest)
    payload = _payload("news_latest", {"limit": 3})
    assert captured["limit"] == 3
    assert payload[0]["title"] == "某条新闻"
    assert payload[0]["date"] == "2026-09-22T10:00:00"


def test_transit_next_passes_campus_enum_and_limit(monkeypatch) -> None:
    import westlake_survival.transit as transit_pkg

    captured = {}

    class Table:
        campus = transit_pkg.Campus.YUNGU
        day_kind = transit_pkg.DayKind.WEEKDAY
        direction_note = "始发云谷"

    class Data:
        def next_departures(self, campus=None, limit=3):
            captured["campus"] = campus
            captured["limit"] = limit
            return [(Table(), "08:30")]

    monkeypatch.setattr(transit_pkg, "transit", lambda refresh=False: Data())
    payload = _payload("transit_next", {"campus": "云谷", "limit": 2})
    assert captured["campus"] == transit_pkg.Campus.YUNGU
    assert captured["limit"] == 2
    assert payload[0] == {
        "time": "08:30",
        "campus": "云谷",
        "day_kind": "工作日",
        "direction": "始发云谷",
    }


def test_site_search_requires_query() -> None:
    """缺 query 时工具内部报错 → isError（而不是崩溃）。"""
    result = _call("site_search", {})
    assert result["isError"] is True
    assert "query" in result["content"][0]["text"]


def test_site_search_returns_hits(monkeypatch) -> None:
    import westlake_survival.search as search_mod

    class Hit:
        title = "<font color=red>西湖</font>大学"
        url = "https://example.test/1"
        date = date(2026, 9, 1)
        desc = "简介"

        @property
        def clean_title(self):
            return "西湖大学"

        @property
        def clean_desc(self):
            return "简介"

    class Result:
        page = 2
        page_count = 5
        total = 42
        hits = [Hit()]

    monkeypatch.setattr(search_mod, "search", lambda keyword, page=1, **kw: Result())
    payload = _payload("site_search", {"query": "西湖", "page": 2})
    assert payload["total"] == 42
    assert payload["page"] == 2
    assert payload["hits"][0]["title"] == "西湖大学"


def test_faculty_search_passes_filters(monkeypatch) -> None:
    import westlake_survival.faculty as faculty

    captured = {}

    class Member:
        name = "李奕璠博士"
        name_en = "Yifan Li, Ph.D."
        school = "理学院"
        subject = "物理学"
        lab = "冷原子实验室"
        url = "https://example.test/f.html"

    def fake_members(school=None, keyword=None, **kwargs):
        captured["school"] = school
        captured["keyword"] = keyword
        return [Member()]

    monkeypatch.setattr(faculty, "members", fake_members)
    payload = _payload("faculty_search", {"school": "理学院", "keyword": "李"})
    assert captured == {"school": "理学院", "keyword": "李"}
    assert payload[0]["name"] == "李奕璠博士"


def test_calendar_today_local_computation(monkeypatch) -> None:
    import westlake_survival.calendar as calendar_mod

    class Event:
        title = "中秋节放假"

        @property
        def start(self):
            return date.today()

        end = None

        def covers(self, d):
            return d == date.today()

    class Semester:
        name = "2026年秋季"

        def week_of(self, d):
            return 4

        def is_teaching_day(self, d):
            return False

        def is_holiday(self, d):
            return True

        events = [Event()]

    class Cal:
        semesters = [Semester()]

        def current(self, when=None):
            return Semester()

    _patch_calendar(monkeypatch, calendar_mod, Cal())
    payload = _payload("calendar_today")
    assert payload["semester"] == "2026年秋季"
    assert payload["week"] == 4
    assert payload["is_holiday"] is True
    assert payload["events"][0]["title"] == "中秋节放假"


def test_calendar_week_explicit_week(monkeypatch) -> None:
    import westlake_survival.calendar as calendar_mod

    class Semester:
        name = "2026年秋季"

        def week_of(self, d):
            return 3

        def teaching_weeks(self):
            return 18

        def date_of(self, week, weekday):
            assert 1 <= weekday <= 7
            return date(2026, 9, 1 + (week - 1) * 7 + (weekday - 1))

    class Cal:
        semesters = [Semester()]

        def current(self, when=None):
            return Semester()

    _patch_calendar(monkeypatch, calendar_mod, Cal())
    payload = _payload("calendar_week", {"week": 2})
    assert payload["week"] == 2
    assert payload["total_weeks"] == 18
    assert payload["start"] < payload["end"]


def test_calendar_week_out_of_range_is_error(monkeypatch) -> None:
    import westlake_survival.calendar as calendar_mod

    class Semester:
        name = "2026年秋季"

        def week_of(self, d):
            return 3

        def teaching_weeks(self):
            return 18

        def date_of(self, week, weekday):
            return date(2026, 9, 1)

    class Cal:
        semesters = [Semester()]

        def current(self, when=None):
            return Semester()

    _patch_calendar(monkeypatch, calendar_mod, Cal())
    result = _call("calendar_week", {"week": 99})
    assert result["isError"] is True


def test_context_snapshot_passes_level(monkeypatch) -> None:
    import westlake_survival.context as context_pkg

    captured = {}

    class Ctx:
        def to_dict(self):
            return {"level": "verbose", "week_number": 12}

    def fake_snapshot(level=context_pkg.Level.NORMAL, now=None):
        captured["level"] = level
        return Ctx()

    monkeypatch.setattr(context_pkg, "snapshot", fake_snapshot)
    payload = _payload("context_snapshot", {"level": "verbose"})
    assert captured["level"] == context_pkg.Level.VERBOSE
    assert payload["week_number"] == 12


def test_context_snapshot_rejects_unknown_level() -> None:
    result = _call("context_snapshot", {"level": "bogus"})
    assert result["isError"] is True
    assert "level" in result["content"][0]["text"]


def test_canvas_deadlines_without_token_returns_hint() -> None:
    """没有 token（conftest 已清环境变量并重定位配置根）时返回引导文本，不报错。"""
    result = _call("canvas_deadlines", {"days": 7})
    assert "isError" not in result
    text = result["content"][0]["text"]
    assert "WESTLAKE_CANVAS_TOKEN" in text


def test_canvas_deadlines_filters_by_days(monkeypatch) -> None:
    import westlake_survival.canvas as canvas_pkg
    from westlake_survival.canvas.models import CHINA_TZ

    monkeypatch.setattr(canvas_pkg, "resolve_token", lambda token=None: "fake-token")

    now = datetime.now(CHINA_TZ)
    soon = now + timedelta(minutes=5)  # 落在 3 天窗口内
    far = now + timedelta(days=999)

    class Assignment:
        def __init__(self, name, due_at):
            self.name = name
            self.due_at = due_at
            self.course_id = 1
            self.html_url = "https://example.test/a"

    class Client:
        def upcoming_deadlines(self, limit=10):
            return [Assignment("短期作业", soon), Assignment("远期作业", far), Assignment("无期限", None)]

    monkeypatch.setattr(canvas_pkg, "canvas", lambda token=None: Client())
    payload = _payload("canvas_deadlines", {"days": 3})
    names = [item["name"] for item in payload]
    assert names == ["短期作业"]


# --------------------------------------------------------------------------- #
# 异常 → isError
# --------------------------------------------------------------------------- #
def test_tool_exception_becomes_is_error(monkeypatch) -> None:
    """业务模块抛异常时包成 isError，且进程不崩。"""
    import westlake_survival.news as news

    def boom(category=None, limit=None, **kwargs):
        raise RuntimeError("网络炸了")

    monkeypatch.setattr(news, "latest", boom)
    result = _call("news_latest", {})
    assert result["isError"] is True
    assert "RuntimeError" in result["content"][0]["text"]
    assert "网络炸了" in result["content"][0]["text"]


def test_missing_module_import_error_becomes_is_error(monkeypatch) -> None:
    """惰性 import 失败（模块缺失）也转 isError，不整个进程崩。"""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "westlake_survival.sis":
            raise ImportError("simulated missing module")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    result = _call("sis_grades", {})
    assert result["isError"] is True
    assert "ImportError" in result["content"][0]["text"]


def test_output_is_compact_single_line_json(monkeypatch) -> None:
    """content 文本是紧凑单行 JSON（可被 json.loads 解析）。"""
    import dataclasses

    import westlake_survival.campus as campus

    @dataclasses.dataclass
    class Dining:
        name: str
        campus: str

    monkeypatch.setattr(campus, "dining", lambda kind=None, campus=None: [Dining("一食堂", "云谷")])
    result = _call("campus_dining", {})
    text = result["content"][0]["text"]
    assert "\n" not in text
    assert json.loads(text) == [{"name": "一食堂", "campus": "云谷"}]


def test_enum_values_serialized_to_their_value() -> None:
    """``str`` 子类枚举序列化成中文值，而不是 ``Campus.YUNGU``。"""
    from westlake_survival.transit import Campus, DayKind

    assert mcp._to_plain(Campus.YUNGU) == "云谷"
    assert mcp._to_plain(DayKind.WEEKDAY) == "工作日"
