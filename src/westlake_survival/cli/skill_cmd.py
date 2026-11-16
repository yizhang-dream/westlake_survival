"""SkillVM CLI 入口：``westlake skill`` 命令组。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from westlake_survival.exceptions import WestlakeError
from westlake_survival.skillvm.compiler import AOTCompiler, HarnessTarget, ModelProfile
from westlake_survival.skillvm.installer import SkillInstaller
from westlake_survival.skillvm.runtime import JITRuntime


def _handle_errors(func):
    import functools

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except WestlakeError as exc:
            click.secho(f"错误：{exc}", fg="red", err=True)
            raise SystemExit(1)
        except Exception as exc:
            click.secho(f"异常：{exc}", fg="red", err=True)
            raise SystemExit(1)

    return wrapper


@click.group(name="skill", help="SkillVM 工具链：AOT 静态编译、JIT 运行时探测与跨机一键挂载。")
def cli_group() -> None:
    """Skill 编译与跨机挂载工具链。"""


@cli_group.command(name="compile")
@click.option(
    "--target",
    type=click.Choice(["zcode", "claude", "cursor", "mcp", "all"]),
    default="zcode",
    help="目标 Harness / 智能体框架，缺省 zcode。",
)
@click.option(
    "--profile",
    type=click.Choice(["frontier", "compact", "micro"]),
    default="frontier",
    help="目标模型档位（frontier: 强推理大模型; compact: 紧凑轻量模型; micro: -O3 微内核常驻）。",
)
@click.option("--out", "output_dir", default="", help="产物输出目录（缺省当前目录或 stdout）。")
@_handle_errors
def compile_cmd(target: str, profile: str, output_dir: str) -> None:
    """AOT 静态特化编译：生成面向特定 Harness 与模型的 Skill 产物。"""
    compiler = AOTCompiler()
    p_enum = ModelProfile(profile)

    targets_to_run = (
        [HarnessTarget.ZCODE, HarnessTarget.CLAUDE_CODE, HarnessTarget.CURSOR, HarnessTarget.MCP]
        if target == "all"
        else [HarnessTarget(target)]
    )

    out_p = Path(output_dir) if output_dir else Path.cwd() / "dist" / "skills"

    click.secho(
        f"⚡ [SkillVM AOT 编译开始] Target: {target}, Profile: {profile.upper()}",
        fg="cyan",
        bold=True,
    )
    for t in targets_to_run:
        res = compiler.compile(target=t, profile=p_enum)
        saved = res.save_to(out_p / t.value)
        click.echo(f"  ✓ [{t.value.upper()}] 已编译生成: {saved}")


@cli_group.command(name="runtime")
@click.option("--json", "as_json", is_flag=True, help="以 JSON 格式输出环境画像。")
@_handle_errors
def runtime_cmd(as_json: bool) -> None:
    """JIT 即时探活与动态特化：探测宿主机器画像并输出自适应上下文补丁。"""
    host = JITRuntime.probe_host()
    if as_json:
        click.echo(json.dumps(host.to_dict(), ensure_ascii=False, indent=2))
        return

    click.secho(f"=== SkillVM JIT 宿主环境画像 ===", fg="cyan", bold=True)
    click.echo(f"  操作系统: {host.os_system} ({host.os_release}, {host.machine_arch})")
    click.echo(f"  解释器:   {host.python_executable} (venv: {host.is_in_venv})")
    click.echo(f"  网络状态: {'校外/未连VPN (启用离线降级)' if host.network_is_offcampus else '校园内网/VPN已连通 (在线直达)'}")
    click.echo(f"  教务凭据: {'已配置 ✓' if host.credentials_sis_present else '未配置 (引导 westlake setup)'}")
    click.echo(f"  Canvas:   {'已配置令牌 ✓' if host.credentials_canvas_present else '回退统一密码'}")
    click.echo(f"  依赖就绪: Playwright={'✓' if host.has_playwright else '×'} | Keyring={'✓' if host.has_keyring else '×'}")

    click.secho(f"\n=== JIT 即时编译生成的特化补丁 ===", fg="yellow", bold=True)
    click.echo(JITRuntime.generate_jit_context_patch())


@cli_group.command(name="install")
@click.option(
    "--target",
    type=click.Choice(["all", "zcode", "claude", "cursor"]),
    default="all",
    help="要挂载的目标框架，缺省 all（自动探查本机已安装框架并全部挂载）。",
)
@click.option(
    "--profile",
    type=click.Choice(["frontier", "compact", "micro"]),
    default="frontier",
    help="目标模型档位（frontier: 强推理大模型; compact: 紧凑轻量模型; micro: -O3 微内核常驻）。",
)
@click.option("--aot", is_flag=True, help="强制写入 AOT 精简编译产物，而非仓库完整手写 SKILL.md。")
@click.option("--force", is_flag=True, help="覆盖已存在的外部软链或联接目标（谨慎使用）。")
@_handle_errors
def install_cmd(target: str, profile: str, aot: bool, force: bool) -> None:
    """一键跨机挂载：将 Skill 自动安装到本机对应智能体框架目录。"""
    p_enum = ModelProfile(profile)
    click.secho("⚡ [SkillVM 跨机安装自适应检测中...]", fg="cyan", bold=True)

    if target == "all":
        results = SkillInstaller.autodetect_and_install_all(profile=p_enum, force=force, aot=aot)
        for t, p in results:
            click.secho(f"  ✓ 成功挂载至 [{t.value}]: {p}", fg="green")
    else:
        t_enum = HarnessTarget(target)
        p = SkillInstaller.install(target=t_enum, profile=p_enum, force=force, aot=aot)
        click.secho(f"  ✓ 成功挂载至 [{t_enum.value}]: {p}", fg="green")

    click.secho("跨机安装完成！可以在当前机器对应的 Agent 中直接调用 /westlake-survival。", fg="cyan")


@cli_group.command(name="status")
@click.option("--json", "as_json", is_flag=True, help="以 JSON 格式输出挂载状态。")
@_handle_errors
def status_cmd(as_json: bool) -> None:
    """检查各智能体宿主目录的 Skill 挂载、软链指向与同步状态。"""
    report = SkillInstaller.inspect_status()
    if as_json:
        click.echo(json.dumps(report, ensure_ascii=False, indent=2))
        return

    click.secho("=== Skill 插件挂载与同步状态 ===", fg="cyan", bold=True)
    click.echo(f"  Python 解释器: {report['python_executable']}")
    click.echo(f"  仓库真源目录:  {report['repo_skill_dir'] or '（未命中）'}")
    marks = {"ok": "✔", "outdated": "!", "linked-outdated": "!", "missing": "·"}
    for row in report["targets"]:
        mark = marks.get(row["status"], "?")
        click.echo(f"  {mark} [{row['target']}] {row['path']}")
        click.echo(f"      状态: {row['note']}")


@cli_group.command(name="mcp-config")
@click.option(
    "--client",
    type=click.Choice(["generic", "claude", "cursor", "zcode"]),
    default="generic",
    show_default=True,
    help="目标客户端类型（影响提示语，配置片段通用）。",
)
@_handle_errors
def mcp_config_cmd(client: str) -> None:
    """输出可直接粘贴到 MCP 客户端的 mcpServers JSON 配置块。"""
    payload = {
        "mcpServers": {
            "westlake-survival": {
                "command": sys.executable,
                "args": ["-m", "westlake_survival.mcp_server"],
            }
        }
    }
    click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    hints = {
        "claude": "将上述片段合并至 ~/.claude.json 或 Claude Desktop 配置文件 mcpServers 节点。",
        "cursor": "将上述片段合并至 .cursor/mcp.json 或 Cursor 全局 MCP 配置。",
        "zcode": "将上述片段合并至 ZCode / Antigravity MCP 配置的 mcpServers 节点。",
        "generic": "将其粘贴到任意支持 stdio MCP 的客户端配置中即可启用全部 89 个工具。",
    }
    click.echo(f"# {hints[client]}", err=True)
