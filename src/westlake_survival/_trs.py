"""TRS CMS + Vue SPA 页面内嵌组件数据的定位与解析。

西湖大学官网（www.westlake.edu.cn）由 TRS CMS 生成外壳 HTML，真实数据并不
在 DOM 里，而是以 ``new 组件名("#app", { ...JS 对象字面量... })`` 的形式内嵌
在页面的内联 ``<script>`` 中。``calendar`` 与 ``transit.schedule`` 各自写过
一套"括号配平 + 字符串拆分"的土办法，本模块把两处共用的部分收敛成一份：

- :func:`component_script`：定位 ``new <组件名>(`` 并截取后面的 ``{...}`` 文本；
- :func:`js_literal`：把 JS 对象/数组字面量递归下降解析成 Python ``dict``/``list``；
- :func:`component_data`：上面两步的组合，一步拿到组件数据；
- :func:`balanced`：从 ``[`` / ``{`` 起做字符串感知的括号配平，返回闭合子串；
- :func:`array_of` / :func:`object_of`：在组件块文本里按键取出数组/对象字面量。

各业务模块（``news`` / ``events`` / ``careers`` / ``faculty`` / ``campus`` /
``contact``）的组件块里混有 ``function`` 回调，不能整块 :func:`js_literal`，
统一改用 :func:`balanced` + :func:`array_of` / :func:`object_of` 按键单独截取。

只依赖标准库；解析失败一律抛 :class:`~westlake_survival.exceptions.ParseError`。
"""

from __future__ import annotations

import re

from westlake_survival.exceptions import ParseError

#: 报错时附带的问题片段长度（字符）。
_SNIPPET_LEN = 80

#: 无引号键名 / 标识符（``\w`` 在 Python 3 里含中文，可覆盖中文键）。
_BARE_WORD = re.compile(r"[\w$]+")

#: 数字字面量（含正负号、小数、指数）。
_NUMBER = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")

#: 十六进制数字字符集（``\uXXXX`` 转义校验用）。
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


def component_script(html: str, name: str) -> str:
    """取出 ``new <name>(...)`` 调用里的 ``{...}`` 对象字面量文本。

    先定位 ``new <name>(``，再从其后的第一个 ``{`` 开始做**字符串感知的括号
    配平**：``'``、``"``、`` ` `` 三种引号内的括号不参与配平，反斜杠转义与
    ``//``、``/* */`` 注释中的括号同样跳过。

    Args:
        html: 整页 HTML 文本。
        name: 组件构造函数名（如 ``"calendar"``）。

    Returns:
        含首尾花括号的完整字面量文本；页面中找不到该组件时返回 ``""``。

    Raises:
        ParseError: 找到组件但 ``(`` 后没有 ``{``，或花括号不配平。
    """
    match = re.search(r"new\s+" + re.escape(name) + r"\s*\(", html)
    if not match:
        return ""
    start = html.find("{", match.end())
    if start == -1:
        raise ParseError(
            f"组件 {name!r} 调用后找不到对象起始 '{{'：{html[match.start():match.start() + _SNIPPET_LEN]!r}"
        )
    return balanced(html, start)


def js_literal(text: str) -> "object":
    """把 JS 对象/数组字面量解析成 Python 的 ``dict``/``list``。

    支持的语法子集（覆盖西湖官网 TRS 内嵌数据实际用到的写法）：

    - 无引号键名（含中文键）、单/双引号字符串（转义含 ``\\/`` ``\\n`` ``\\t``
      ``\\\\`` ``\\'`` ``\\"`` ``\\uXXXX``）、正负数字（含小数与指数）、
      ``true`` / ``false`` / ``null``、任意嵌套、尾逗号；
    - ``//`` 行注释与 ``/* */`` 块注释。

    遇到子集之外的语法（模板字符串、函数、表达式等）抛
    :class:`~westlake_survival.exceptions.ParseError`。

    Args:
        text: 字面量文本，可带首尾空白。

    Returns:
        解析结果，类型为 ``dict`` / ``list`` / ``str`` / ``int`` / ``float`` /
        ``bool`` / ``None``。
    """
    parser = _Parser(text)
    value = parser.parse_value()
    parser.skip_trivia()
    if not parser.at_end:
        raise parser.error("字面量末尾存在多余内容")
    return value


def component_data(html: str, name: str) -> dict:
    """一步取出 ``new <name>(...)`` 中的组件数据。

    Args:
        html: 整页 HTML 文本。
        name: 组件构造函数名。

    Returns:
        组件数据字典。

    Raises:
        ParseError: 组件缺失、字面量不合法，或顶层不是对象。
    """
    script = component_script(html, name)
    if not script:
        raise ParseError(f"页面中找不到组件 {name!r}；页面片段：{html[:200]!r}")
    data = js_literal(script)
    if not isinstance(data, dict):
        raise ParseError(f"组件 {name!r} 的顶层数据不是对象：{script[:_SNIPPET_LEN]!r}")
    return data


def balanced(text: str, start: int) -> str:
    """从 ``text[start]``（须为 ``[`` 或 ``{``）起做字符串感知的括号配平。

    与 :func:`component_script` 同一套扫描口径：``'``、``"``、`` ` `` 三种引号
    内的括号不参与配平，反斜杠转义与 ``//``、``/* */`` 注释中的括号同样跳过。

    Args:
        text: 待扫描的文本（通常是 :func:`component_script` 截出的组件块）。
        start: 起始下标，``text[start]`` 必须是 ``[`` 或 ``{``。

    Returns:
        含首尾括号的闭合子串（``[...]`` 或 ``{...}``）。

    Raises:
        ParseError: 起始下标处的括号未配平。
    """
    open_ch = text[start]
    close_ch = "]" if open_ch == "[" else "}"
    depth = 0
    i = start
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in ("'", '"', "`"):
            i += 1
            while i < n and text[i] != ch:
                if text[i] == "\\":
                    i += 1
                i += 1
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] in "/*":
            i = _skip_comment(text, i)
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
        i += 1
    raise ParseError(
        f"括号不配平：从下标 {start} 起未找到匹配的 {close_ch!r}；片段：{text[start:start + _SNIPPET_LEN]!r}"
    )


def array_of(block: str, key: str) -> list:
    """在组件块文本里定位 ``key: [...]`` 并返回 :func:`js_literal` 解析结果。

    组件对象里混有 ``function () {}`` 回调，不能整块解析；本函数先按键定位，
    再用 :func:`balanced` 截出配平的数组字面量后单独解析。

    Args:
        block: 组件块文本（通常是 :func:`component_script` 的返回值）。
        key: 目标键名（如 ``"topicsList"``）。

    Returns:
        解析后的 Python ``list``。

    Raises:
        ParseError: 块里找不到 ``key: [``，或截出的字面量不合法。
    """
    match = re.search(r"\b" + re.escape(key) + r"\s*:\s*\[", block)
    if not match:
        raise ParseError(f"组件数据中找不到键 {key!r}")
    return js_literal(balanced(block, match.end() - 1))


def object_of(block: str, key: str) -> dict:
    """在组件块文本里定位 ``key: {...}`` 并返回 :func:`js_literal` 解析结果。

    与 :func:`array_of` 同口径，只是目标为对象字面量。

    Args:
        block: 组件块文本（通常是 :func:`component_script` 的返回值）。
        key: 目标键名（如 ``"mainObj"``）。

    Returns:
        解析后的 Python ``dict``。

    Raises:
        ParseError: 块里找不到 ``key: {``，或截出的字面量不合法。
    """
    match = re.search(r"\b" + re.escape(key) + r"\s*:\s*\{", block)
    if not match:
        raise ParseError(f"组件数据中找不到键 {key!r}")
    return js_literal(balanced(block, match.end() - 1))


def _skip_comment(text: str, pos: int) -> int:
    """跳过 ``pos`` 处的注释，返回其后第一个下标。"""
    if text.startswith("//", pos):
        newline = text.find("\n", pos)
        return len(text) if newline == -1 else newline + 1
    end = text.find("*/", pos + 2)
    return len(text) if end == -1 else end + 2


class _Parser:
    """递归下降解析器：JS 字面量 → Python 对象。"""

    #: 简单转义字符映射。
    _ESCAPES = {
        "\\": "\\",
        "'": "'",
        '"': '"',
        "/": "/",
        "n": "\n",
        "t": "\t",
        "r": "\r",
        "b": "\b",
        "f": "\f",
    }

    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0

    @property
    def at_end(self) -> bool:
        return self.pos >= len(self.text)

    def error(self, message: str, pos: int | None = None) -> ParseError:
        """构造带问题片段（前 80 字符）的 :class:`ParseError`。"""
        at = self.pos if pos is None else pos
        return ParseError(f"{message}（位置 {at}）：{self.text[at : at + _SNIPPET_LEN]!r}")

    def skip_trivia(self) -> None:
        """跳过空白与注释。"""
        n = len(self.text)
        while self.pos < n:
            ch = self.text[self.pos]
            if ch.isspace():
                self.pos += 1
                continue
            if ch == "/" and self.pos + 1 < n and self.text[self.pos + 1] in "/*":
                self.pos = _skip_comment(self.text, self.pos)
                continue
            break

    def parse_value(self) -> "object":
        """解析一个值。"""
        self.skip_trivia()
        if self.at_end:
            raise self.error("字面量意外结束，期待一个值")
        ch = self.text[self.pos]
        if ch == "{":
            return self.parse_object()
        if ch == "[":
            return self.parse_array()
        if ch in ("'", '"'):
            return self.parse_string()
        if ch == "`":
            raise self.error("暂不支持模板字符串")
        if ch.isdigit() or ch in "+-.":
            return self.parse_number()
        if self.text.startswith("true", self.pos):
            self.pos += 4
            return True
        if self.text.startswith("false", self.pos):
            self.pos += 5
            return False
        if self.text.startswith("null", self.pos):
            self.pos += 4
            return None
        raise self.error(f"无法识别的值，遇到 {ch!r}")

    def parse_object(self) -> dict:
        """解析 ``{ key: value, ... }``，允许尾逗号。"""
        self.pos += 1  # 跳过 '{'
        result: dict = {}
        while True:
            self.skip_trivia()
            if self.at_end:
                raise self.error("对象未闭合，缺少 '}'")
            if self.text[self.pos] == "}":
                self.pos += 1
                return result
            key = self.parse_key()
            self.skip_trivia()
            if self.at_end or self.text[self.pos] != ":":
                raise self.error(f"键 {key!r} 后缺少 ':'")
            self.pos += 1
            result[key] = self.parse_value()
            self.skip_trivia()
            if self.at_end:
                raise self.error("对象未闭合，缺少 '}'")
            if self.text[self.pos] == ",":
                self.pos += 1
                continue
            if self.text[self.pos] == "}":
                self.pos += 1
                return result
            raise self.error(f"对象成员后期待 ',' 或 '}}'，遇到 {self.text[self.pos]!r}")

    def parse_key(self) -> str:
        """解析对象键：带引号字符串或裸标识符（可含中文）。"""
        ch = self.text[self.pos]
        if ch in ("'", '"'):
            return self.parse_string()
        match = _BARE_WORD.match(self.text, self.pos)
        if not match:
            raise self.error("对象键不合法")
        self.pos = match.end()
        return match.group(0)

    def parse_array(self) -> list:
        """解析 ``[ value, ... ]``，允许尾逗号。"""
        self.pos += 1  # 跳过 '['
        result: list = []
        while True:
            self.skip_trivia()
            if self.at_end:
                raise self.error("数组未闭合，缺少 ']'")
            if self.text[self.pos] == "]":
                self.pos += 1
                return result
            result.append(self.parse_value())
            self.skip_trivia()
            if self.at_end:
                raise self.error("数组未闭合，缺少 ']'")
            if self.text[self.pos] == ",":
                self.pos += 1
                continue
            if self.text[self.pos] == "]":
                self.pos += 1
                return result
            raise self.error(f"数组元素后期待 ',' 或 ']'，遇到 {self.text[self.pos]!r}")

    def parse_string(self) -> str:
        """解析单/双引号字符串，处理转义。"""
        quote = self.text[self.pos]
        self.pos += 1
        chunks: list[str] = []
        n = len(self.text)
        while self.pos < n:
            ch = self.text[self.pos]
            if ch == "\\":
                self.pos += 1
                if self.pos >= n:
                    raise self.error("字符串转义符后意外结束")
                escape = self.text[self.pos]
                if escape == "u":
                    hex_text = self.text[self.pos + 1 : self.pos + 5]
                    valid_hex = len(hex_text) == 4 and all(c in _HEX_DIGITS for c in hex_text)
                    if not valid_hex:
                        raise self.error("非法的 \\u 转义")
                    chunks.append(chr(int(hex_text, 16)))
                    self.pos += 5
                    continue
                chunks.append(self._ESCAPES.get(escape, escape))
                self.pos += 1
                continue
            if ch == quote:
                self.pos += 1
                return "".join(chunks)
            chunks.append(ch)
            self.pos += 1
        raise self.error("字符串未闭合")

    def parse_number(self) -> "int | float":
        """解析数字字面量。"""
        match = _NUMBER.match(self.text, self.pos)
        if not match or not match.group(0).strip("+-"):
            raise self.error("非法的数字字面量")
        raw = match.group(0)
        self.pos = match.end()
        if any(mark in raw for mark in ".eE"):
            return float(raw)
        return int(raw)