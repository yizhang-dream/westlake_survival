"""今日时空行动流 CLI 组：``westlake timeline``。"""
from __future__ import annotations

import json
from datetime import date
from typing import Any

import click

from westlake_survival.consequence import gate_cli
from westlake_survival.exceptions import WestlakeError
from westlake_survival.timeline import (
    add_memo,
    build_timeline,
    delete_memo,
    list_memos,
    toggle_memo,
)


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


@click.group(name="timeline", invoke_without_command=True, help="今日时空行动流：跨系统日程编排、冲突检测与个人备忘。")
@click.option("--date", "target_date_str", default="", help="目标日期 YYYY-MM-DD（缺省今天）。")
@click.option("--offline", is_flag=True, help="离线模式：强制使用本地快照，不发网络请求。")
@click.option("--json", "as_json", is_flag=True, help="以 JSON 格式输出。")
@click.pass_context
@_handle_errors
def cli_group(ctx: click.Context, target_date_str: str, offline: bool, as_json: bool) -> None:
    """今日时空行动流总览。"""
    if ctx.invoked_subcommand is not None:
        return

    target_d = None
    if target_date_str:
        try:
            target_d = date.fromisoformat(target_date_str)
        except ValueError:
            raise click.ClickException(f"日期格式不正确：{target_date_str}，请使用 YYYY-MM-DD")

    report = build_timeline(target_date=target_d, offline=offline)
    if as_json:
        click.echo(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return

    # 渲染终端美化视图
    stale_tag = " [离线快照模式]" if report.meta.get("is_stale") else ""
    click.secho(f"=== {report.date_str} 时空行动流（{report.term_info}）{stale_tag} ===", fg="cyan", bold=True)

    if report.conflicts:
        click.secho("\n⚠️  [日程冲突预警]", fg="red", bold=True)
        for c in report.conflicts:
            click.secho(f"   • {c}", fg="yellow")

    if not report.items:
        click.echo("\n今日无日程安排或待办事项。")
    else:
        click.echo("")
        for it in report.items:
            # 状态色彩与分类标记
            color = "white"
            tag = "📅"
            if it.category == "course":
                tag = "🎓 课程"
                color = "green"
            elif it.category == "canvas":
                tag = "📝 作业"
                color = "yellow"
            elif it.category == "booking":
                tag = "🏢 预约"
                color = "blue"
            elif it.category == "transit":
                tag = "🚌 班车"
                color = "magenta"
            elif it.category == "holiday":
                tag = "🎉 假期"
                color = "bright_cyan"
            elif it.category == "memo":
                tag = "📌 备忘"
                color = "bright_yellow"

            conflict_mark = click.style(" [冲突]", fg="red", bold=True) if it.is_conflict else ""
            loc = f" @ {it.location}" if it.location else ""
            click.echo(f"  {click.style(it.time_str.ljust(13), fg='cyan', bold=True)} {tag} {click.style(it.title, fg=color, bold=True)}{conflict_mark}{loc}")
            if it.details:
                click.echo(f"  {' ' * 13}   ↳ {it.details}")

    if report.memos:
        active = [m for m in report.memos if not m.done]
        if active:
            click.secho(f"\n个人待办事项 ({len(active)} 条未完成):", fg="cyan")
            for m in active:
                t_str = f"[{m.time_str}] " if m.time_str else ""
                click.echo(f"  • {t_str}{m.text} (ID: {m.id})")


@cli_group.command(name="add")
@click.argument("text")
@click.option("--time", "time_str", default="", help="指定时间点（如 14:30）。")
@click.option("--dry-run", is_flag=True, help="只预检不保存（输出事务预览卡片）。")
@click.option("--ticket", default=None, help="通过预览卡片生成的单次放行凭证 Ticket。")
@click.option("--yes", "skip_confirm", is_flag=True, help="确认执行（受控写操作确认门）。")
@_handle_errors
def memo_add_cmd(text: str, time_str: str, dry_run: bool, ticket: str | None, skip_confirm: bool) -> None:
    """添加一条个人生活备忘（写操作：--dry-run 预检 / --ticket 或 --yes 执行）。"""
    gate_cli(
        "timeline.memo",
        confirmed=skip_confirm,
        dry_run=dry_run,
        ticket=ticket,
        target=f"备忘: {text}",
        payload={"text": text, "time": time_str, "action": "add"},
    )
    if dry_run:
        return
    memo = add_memo(text, time_str=time_str)
    click.secho(f"已添加备忘 [{memo.id}]: {memo.text}", fg="green")


@cli_group.command(name="done")
@click.argument("memo_id")
@click.option("--ticket", default=None, help="通过预览卡片生成的单次放行凭证 Ticket。")
@click.option("--yes", "skip_confirm", is_flag=True, help="确认执行（受控写操作确认门）。")
@_handle_errors
def memo_done_cmd(memo_id: str, ticket: str | None, skip_confirm: bool) -> None:
    """标记一条备忘已完成（写操作：--ticket 或 --yes 执行）。"""
    gate_cli(
        "timeline.memo",
        confirmed=skip_confirm,
        ticket=ticket,
        target=f"备忘ID: {memo_id}",
        payload={"memo_id": memo_id, "action": "done"},
    )
    memo = toggle_memo(memo_id, done=True)
    click.secho(f"备忘 [{memo.id}] 已标记完成！", fg="green")


@cli_group.command(name="list")
@_handle_errors
def memo_list_cmd() -> None:
    """列出全部个人备忘。"""
    memos = list_memos()
    if not memos:
        click.echo("暂无个人备忘。")
        return
    for m in memos:
        status = "[已完成]" if m.done else "[待办]"
        t_str = f" ({m.time_str})" if m.time_str else ""
        click.echo(f"  {status} {m.text}{t_str} [{m.id}]")


@cli_group.command(name="delete")
@click.argument("memo_id")
@_handle_errors
def memo_delete_cmd(memo_id: str) -> None:
    """删除指定个人备忘。"""
    ok = delete_memo(memo_id)
    if ok:
        click.secho(f"已删除备忘 [{memo_id}]。", fg="green")
    else:
        click.secho(f"未找到备忘 [{memo_id}]。", fg="yellow")
