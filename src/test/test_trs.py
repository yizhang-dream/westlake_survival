"""_trs 私有共享模块离线测试：组件定位、括号配平、JS 字面量解析。"""

from __future__ import annotations

import pytest

from westlake_survival._trs import (
    array_of,
    balanced,
    component_data,
    component_script,
    js_literal,
    object_of,
)
from westlake_survival.exceptions import ParseError


# --- component_script：定位与字符串感知的括号配平 -------------------------


def test_component_script_returns_object_literal() -> None:
    html = '<script>new calendar("#app", {title: "校历", items: [1, 2]});</script>'
    assert component_script(html, "calendar") == '{title: "校历", items: [1, 2]}'


def test_component_script_missing_component_returns_empty_string() -> None:
    assert component_script("<html><body>无组件</body></html>", "calendar") == ""


def test_component_script_ignores_braces_inside_strings() -> None:
    html = "new calendar(\"#app\", {tpl: \"{ 未闭合的 } { [ ]\", n: 1})"
    assert component_script(html, "calendar") == '{tpl: "{ 未闭合的 } { [ ]", n: 1}'


def test_component_script_ignores_braces_in_line_comment() -> None:
    html = "new x(\"#app\", {\n// } 注释里的右括号\n a: 1 })"
    assert component_script(html, "x") == "{\n// } 注释里的右括号\n a: 1 }"


def test_component_script_ignores_braces_in_block_comment() -> None:
    html = "new x(\"#app\", { /* } { */ a: [1] })"
    assert component_script(html, "x") == "{ /* } { */ a: [1] }"


def test_component_script_unbalanced_raises_parse_error() -> None:
    with pytest.raises(ParseError):
        component_script('new calendar("#app", {a: 1)', "calendar")


def test_component_script_handles_escaped_quote_in_string() -> None:
    html = "new x(\"#app\", {s: 'a\\'}b'})"
    assert component_script(html, "x") == "{s: 'a\\'}b'}"


# --- js_literal：语法子集 ------------------------------------------------


def test_js_literal_bare_keys() -> None:
    assert js_literal("{a: 1, b_c: 2, $d: 3}") == {"a": 1, "b_c": 2, "$d": 3}


def test_js_literal_single_and_double_quotes() -> None:
    assert js_literal("{'a': '单', \"b\": \"双\"}") == {"a": "单", "b": "双"}


def test_js_literal_strings_with_structural_chars() -> None:
    data = js_literal('{a: "{ } [ ]", b: "// 不是注释", c: "/* 也不是 */"}')
    assert data == {"a": "{ } [ ]", "b": "// 不是注释", "c": "/* 也不是 */"}


def test_js_literal_slash_escapes() -> None:
    assert js_literal('{html: "<br\\/>", path: "a\\/b"}') == {
        "html": "<br/>",
        "path": "a/b",
    }


def test_js_literal_trailing_commas() -> None:
    assert js_literal("{a: 1, b: [1, 2, ], }") == {"a": 1, "b": [1, 2]}


def test_js_literal_comments() -> None:
    text = "{\n// 行注释\n a: 1, /* 块注释\n 跨行 */ b: 2\n}"
    assert js_literal(text) == {"a": 1, "b": 2}


def test_js_literal_deep_nesting() -> None:
    text = '{a: {b: {c: {d: [{e: "深"}]}}}}'
    assert js_literal(text) == {"a": {"b": {"c": {"d": [{"e": "深"}]}}}}


def test_js_literal_chinese_values() -> None:
    assert js_literal('{名称: "云谷校区", 备注: "中文，含标点。"}') == {
        "名称": "云谷校区",
        "备注": "中文，含标点。",
    }


def test_js_literal_numbers_booleans_null() -> None:
    assert js_literal("{i: 42, neg: -7, f: 3.14, nf: -0.5, t: true, f2: false, z: null}") == {
        "i": 42,
        "neg": -7,
        "f": 3.14,
        "nf": -0.5,
        "t": True,
        "f2": False,
        "z": None,
    }


def test_js_literal_top_level_array() -> None:
    assert js_literal('[1, "二", {三: 3}]') == [1, "二", {"三": 3}]


def test_js_literal_escapes_newline_tab_backslash() -> None:
    assert js_literal('{s: "a\\nb\\tc\\\\d"}') == {"s": "a\nb\tc\\d"}


def test_js_literal_unicode_escape() -> None:
    assert js_literal('{s: "\\u4e2d\\u6587"}') == {"s": "中文"}


def test_js_literal_whitespace_only_is_error() -> None:
    with pytest.raises(ParseError):
        js_literal("   ")


def test_js_literal_malformed_missing_colon_raises() -> None:
    with pytest.raises(ParseError):
        js_literal("{a 1}")


def test_js_literal_malformed_unterminated_object_raises() -> None:
    with pytest.raises(ParseError):
        js_literal('{a: "未闭合')


def test_js_literal_trailing_garbage_raises() -> None:
    with pytest.raises(ParseError):
        js_literal("{a: 1} 多余")


def test_js_literal_template_string_unsupported() -> None:
    with pytest.raises(ParseError):
        js_literal("{a: `模板`}")


def test_js_literal_error_message_includes_snippet() -> None:
    with pytest.raises(ParseError) as excinfo:
        js_literal("{a: @坏值}")
    assert "@坏值" in str(excinfo.value)


# --- component_data：组合便捷函数 ---------------------------------------


def test_component_data_parses_nested_component() -> None:
    html = (
        "<html><script>new schedule(\"#app\", {"
        "list: [{name: 'A', times: ['08:00', '17:30'], }], "
        "note: \"备注<br\\/>\", ok: true});</script></html>"
    )
    assert component_data(html, "schedule") == {
        "list": [{"name": "A", "times": ["08:00", "17:30"]}],
        "note": "备注<br/>",
        "ok": True,
    }


def test_component_data_missing_component_raises_with_context() -> None:
    html = "<html><body>没有目标组件，只有一堆无关内容。</body></html>"
    with pytest.raises(ParseError) as excinfo:
        component_data(html, "calendar")
    assert "calendar" in str(excinfo.value)
    assert "没有目标组件" in str(excinfo.value)


# --- balanced：字符串感知的括号配平 -------------------------------------


def test_balanced_object_returns_closed_substring() -> None:
    text = '{a: 1, b: {c: 2}} 尾巴'
    assert balanced(text, 0) == "{a: 1, b: {c: 2}}"


def test_balanced_array_returns_closed_substring() -> None:
    text = "前缀 [1, [2, 3], 4] 后缀"
    assert balanced(text, text.index("[")) == "[1, [2, 3], 4]"


def test_balanced_ignores_brackets_inside_strings() -> None:
    text = '{s: "} ] 都不算", n: 1}'
    assert balanced(text, 0) == '{s: "} ] 都不算", n: 1}'


def test_balanced_handles_escaped_quote() -> None:
    text = "{s: 'a\\'}b', n: 1}"
    assert balanced(text, 0) == "{s: 'a\\'}b', n: 1}"


def test_balanced_ignores_brackets_in_line_comment() -> None:
    text = "{\n// } 注释里的右括号\n a: 1 }"
    assert balanced(text, 0) == "{\n// } 注释里的右括号\n a: 1 }"


def test_balanced_ignores_brackets_in_block_comment() -> None:
    text = "{ /* ] { */ a: [1] }"
    assert balanced(text, 0) == "{ /* ] { */ a: [1] }"


def test_balanced_unbalanced_raises_parse_error() -> None:
    with pytest.raises(ParseError):
        balanced("{a: 1", 0)


# --- array_of / object_of：按键提取 ------------------------------------


def test_array_of_extracts_nested_array() -> None:
    block = "{ list: [{a: [1, 2]}], tail: 1 }"
    assert array_of(block, "list") == [{"a": [1, 2]}]


def test_array_of_key_inside_string_is_not_matched() -> None:
    # 真正的键在前，字符串里后出现的 "list: [" 不该干扰配平（引号内括号被跳过）。
    block = '{ list: [1, 2], note: "list: [ 假的" }'
    assert array_of(block, "list") == [1, 2]


def test_array_of_missing_key_raises() -> None:
    with pytest.raises(ParseError, match="list"):
        array_of("{other: [1]}", "list")


def test_object_of_extracts_nested_object() -> None:
    block = "{ main: {title: 'x', sub: {n: 1}}, other: 1 }"
    assert object_of(block, "main") == {"title": "x", "sub": {"n": 1}}


def test_object_of_ignores_key_inside_string() -> None:
    block = '{ main: {title: "真"}, note: "main: { 假的" }'
    assert object_of(block, "main") == {"title": "真"}


def test_object_of_missing_key_raises() -> None:
    with pytest.raises(ParseError, match="main"):
        object_of("{other: {n: 1}}", "main")