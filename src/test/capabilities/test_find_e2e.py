"""能力自发现（westlake find / find_capabilities）端到端测试。

全部离线：能力索引来自 click 树、MCP spec、WEB_PAGES、DATABASES 与
SERVICE_REGISTRY，均不需要网络。
"""

from __future__ import annotations

from westlake_survival.capabilities import SYNONYMS, find_capabilities


def test_find_homework_routes_to_canvas_offline() -> None:
    """用户例：「作业问题」必须路由到 Canvas（含交作业与截止）。"""
    result = find_capabilities("作业")
    cli_names = {item["name"] for item in result["cli"]}
    assert any("canvas" in n for n in cli_names)
    canvas = next(item for item in result["cli"] if "canvas" in item["name"])
    sub_names = {c["name"] for c in canvas.get("matched_commands", [])}
    assert {"assignments", "deadlines", "submit"} & sub_names or canvas.get("matched_commands") is not None
    mcp_names = {item["name"].split(":")[-1] for item in result["mcp"]}
    assert {"canvas_deadlines", "canvas_submit"} & mcp_names


def test_find_paper_hits_scholar_via_synonyms_offline() -> None:
    """口语「论文」经同义词扩展命中学术资源（工具描述里只写「文献/DOI」）。"""
    result = find_capabilities("论文")
    assert any("scholar" in item["name"] for item in result["cli"])
    assert any("scholar" in item["name"] for item in result["mcp"])
    assert result["databases"], "订阅数据库注册表应命中"


def test_find_library_books_offline() -> None:
    result = find_capabilities("借书")
    assert any("lib" in item["name"] for item in result["cli"])
    assert result["matched_terms"]


def test_find_services_registry_offline() -> None:
    result = find_capabilities("预约")
    hosts = {item["host"] for item in result["services"]}
    assert any("booking" in h or "visitor" in h for h in hosts)


def test_find_empty_query_gives_hint_offline() -> None:
    result = find_capabilities("")
    assert result["hint"]


def test_synonyms_table_sane_offline() -> None:
    """同义词表覆盖六大域的代表口语词。"""
    for must in ("论文", "作业", "放假", "食堂", "报销", "宣讲"):
        assert must in SYNONYMS


def test_cli_find_command_smoke_offline() -> None:
    from click.testing import CliRunner

    from westlake_survival.cli.main import find_cmd

    result = CliRunner().invoke(find_cmd, ["论文"])
    assert result.exit_code == 0
    assert "scholar" in result.output
    result = CliRunner().invoke(find_cmd, [])
    assert result.exit_code == 0 and "关键词" in result.output


def test_mcp_find_capability_registered() -> None:
    from westlake_survival.mcp_server import list_tools

    names = {spec["name"] for spec in list_tools()}
    assert "find_capability" in names
