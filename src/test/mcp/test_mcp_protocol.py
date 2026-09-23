"""MCP stdio 服务器的 JSON-RPC 协议层测试（离线）。"""

from __future__ import annotations

import json
from io import StringIO

from westlake_survival import mcp_server as mcp


def _send(payload) -> dict | None:
    """走 ``handle_line`` 发一条请求，返回解析后的响应（通知返回 None）。"""
    line = payload if isinstance(payload, str) else json.dumps(payload)
    response = mcp.handle_line(line)
    if response is None:
        return None
    parsed = json.loads(response)
    assert "\n" not in response
    return parsed


def test_initialize_handshake_shape() -> None:
    """``initialize`` 回显协议版本并给出 serverInfo / capabilities.tools。"""
    response = _send(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {}},
        }
    )
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 1
    result = response["result"]
    assert result["protocolVersion"] == "2025-03-26"
    assert result["serverInfo"]["name"] == mcp.SERVER_NAME
    assert result["serverInfo"]["version"]
    assert "tools" in result["capabilities"]


def test_initialize_without_protocol_version_uses_default() -> None:
    """客户端没给协议版本时回落到默认版本。"""
    response = _send({"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {}})
    assert response["result"]["protocolVersion"] == mcp.DEFAULT_PROTOCOL_VERSION


def test_initialized_notification_is_ignored() -> None:
    """``notifications/initialized`` 通知不产生任何输出。"""
    assert _send({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_ping_returns_empty_result() -> None:
    """``ping`` 返回空 result 且 id 原样回显。"""
    response = _send({"jsonrpc": "2.0", "id": "abc", "method": "ping"})
    assert response["id"] == "abc"
    assert response["result"] == {}


def test_unknown_method_returns_method_not_found() -> None:
    """未知方法返回 -32601。"""
    response = _send({"jsonrpc": "2.0", "id": 3, "method": "no/such/method"})
    assert response["error"]["code"] == mcp.METHOD_NOT_FOUND
    assert response["id"] == 3


def test_missing_method_returns_invalid_request() -> None:
    """缺 method 字段返回 -32600。"""
    response = _send({"jsonrpc": "2.0", "id": 4, "params": {}})
    assert response["error"]["code"] == mcp.INVALID_REQUEST


def test_batch_request_rejected() -> None:
    """JSON-RPC 批量数组暂不支持，返回 -32600。"""
    response = _send('[{"jsonrpc":"2.0","id":1,"method":"ping"}]')
    assert response["error"]["code"] == mcp.INVALID_REQUEST
    assert response["id"] is None


def test_malformed_json_returns_parse_error() -> None:
    """非法 JSON 返回 -32700，且 id 为 null。"""
    response = _send("{not json")
    assert response["error"]["code"] == mcp.PARSE_ERROR
    assert response["id"] is None


def test_blank_line_produces_no_output() -> None:
    """空行 / 纯空白行不产生响应。"""
    assert mcp.handle_line("") is None
    assert mcp.handle_line("   \n") is None


def test_serve_reads_lines_until_eof() -> None:
    """``serve`` 逐行处理并在 stdin 耗尽（EOF）后正常返回。"""
    stdin = StringIO(
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n'
        '{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
        '{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n'
    )
    stdout = StringIO()
    mcp.serve(stdin=stdin, stdout=stdout)

    lines = [line for line in stdout.getvalue().split("\n") if line]
    assert len(lines) == 2  # 通知不写输出
    first, second = (json.loads(line) for line in lines)
    assert first["id"] == 1
    assert second["result"]["tools"]


def test_main_exists_and_returns_int(monkeypatch) -> None:
    """``main()`` 走完 stdio 循环返回 0（用空 stdin 模拟 EOF）。"""
    monkeypatch.setattr(mcp.sys, "stdin", StringIO(""))
    assert mcp.main() == 0
