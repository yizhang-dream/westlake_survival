"""首次配置向导：填一次学号密码，把能接的服务都接上。

背景
====
新拿到这个工具的人不该先读文档再逐条敲命令。理想路径是：第一次运行
（或执行 ``westlake setup``）就进入一个交互向导，输一次学号与密码，
向导自己去探测哪些服务能用这套凭据、哪些需要单独配置，最后给一张清单。

「一个账号通吃」的真实边界
==========================
如实探测、不假装：
* **教务 SIS**（课表/成绩/考试/评教/学籍/学生记录/资助）：优先走统一身份认证
  （IAM OAuth2，2026-10-24 实测打通）——填**统一（校园门户）密码**即可；
  旧 SIS 专用密码也兼容（自动回落 PeopleSoft 本地登录）；
* **Canvas**：REST 只认访问令牌，但令牌不是必需的——没有令牌时自动回退统一
  密码（IAM CAS 会话 Cookie）。向导/设置页可另存一个令牌（可选、可清除），
  存了会优先使用；被确认拒绝（HTTP 401/403）的令牌不予保存，避免它抢在
  统一密码前面把 Canvas 锁死；
* **打印系统**：独立密码域，本向导不试（无凭据时也只用公开网点列表）。
  电子地图已按用户裁定完全走公开内容（图片 + 720° 全景链接），无账号。

凭据落盘沿用既有四级机制：优先系统钥匙串，退配置文件，写时尽力 0600。
**验证未通过也先落盘**（页面/终端都会标明「未验证」），避免校外、验证码或
网络抖动时白填一次；令牌则只存「有效或无法判定」的，确定无效的不存。
向导**不回显、不写日志**任何密码；``--password`` 参数仅为自动化保留，
进程列表里可见，不建议日常使用。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import click

from westlake_survival.exceptions import AuthError, OffCampusError, WestlakeError

__all__ = ["SetupReport", "run_setup", "setup_cmd"]


@dataclass
class SetupReport:
    """向导探测结果。"""

    sid: str = ""
    sis_ok: bool = False
    sis_note: str = ""
    stored_in: str = ""
    canvas_saved: bool = False
    canvas_note: str = ""
    extra: list[str] = field(default_factory=list)


def _probe_sis(sid: str, password: str) -> tuple[bool, str]:
    """用给定凭据真登一次 SIS（PeopleSoft 本地登录）。"""
    from westlake_survival.sso import SISAuth, cred_clear, cred_set

    cred_set(sid, password)
    try:
        SISAuth().ensure()
    except OffCampusError:
        return False, "校外网络不可达（连校园网/VPN 后再试）"
    except AuthError as exc:
        return False, f"登录失败：{exc}"
    except WestlakeError as exc:
        return False, f"网络或解析失败：{exc}"
    except Exception as exc:  # pragma: no cover - 兜底不让向导崩
        return False, f"{exc.__class__.__name__}: {exc}"
    finally:
        cred_clear()
    return True, "登录成功"


def _persist(sid: str, password: str, *, use_keyring: bool = True) -> str:
    """保存教务凭据：钥匙串优先（可关），否则配置文件。返回存放位置描述。

    ``use_keyring=False`` 时只写配置文件——自动化与端到端测试必须走这条，
    否则会往真实的 Windows 凭据管理器里写测试账号。
    """
    import os

    from westlake_survival.sso import keyring_available, save_credentials_keyring, write_credentials

    use_keyring = use_keyring and not os.environ.get("WESTLAKE_NO_KEYRING")
    if use_keyring and keyring_available() and save_credentials_keyring(sid, password):
        return "系统钥匙串"
    path = write_credentials(sid, password)
    return str(path)


def _persist_canvas(token: str) -> str:
    """把 Canvas 令牌写到配置文件首行。"""
    from westlake_survival.canvas.client import save_token_file

    return str(save_token_file(token))


def _clear_canvas() -> bool:
    """删除本地 Canvas 令牌文件；本就不存在返回 ``False``。"""
    from westlake_survival.canvas.client import clear_token_file

    return clear_token_file()


def _handle_canvas_token(token: str, verify: bool) -> tuple[bool, str]:
    """校验并保存 Canvas 令牌，返回 ``(是否保存, 说明)``。

    确定被拒（HTTP 401/403）的令牌不保存——它一旦落盘就会优先于统一密码，
    反而把 Canvas 锁死；网络不可达等「未知」情况按「先存后重试」处理。
    """
    if not token.strip():
        return False, ""
    note = "未校验（直接保存）"
    if verify:
        from westlake_survival.canvas.client import check_token

        state, note = check_token(token)
        if state == "rejected":
            return False, f"{note}；未保存"
    return True, f"{note}；已保存到 {_persist_canvas(token)}"


def _print_report(report: SetupReport) -> None:
    """打印结果清单。"""
    click.echo("")
    click.echo("结果：")
    mark = lambda ok: click.style("✓", fg="green") if ok else click.style("✗", fg="yellow")
    click.echo(f"  {mark(report.sis_ok)} 校园账号（教务课表/成绩/考试 + Canvas 课程作业）  {report.sis_note}")
    click.echo("  ✓  公开功能（校历/班车/新闻/培养方案/通识课程/地图）  始终可用，无需账号")
    if report.stored_in:
        state = "已验证" if report.sis_ok else "未验证（查询时会重新验证）"
        click.echo(f"\n教务凭据已保存到：{report.stored_in}（{state}）")
    if report.canvas_note:
        click.echo(f"Canvas 令牌：{report.canvas_note}")
    for line in report.extra:
        click.echo(line)
    if not report.sis_ok and report.sid:
        click.echo("\n提示：教务未接通不影响公开功能；校内网络下可重跑 `westlake setup`。")


def run_setup(
    *,
    sid: str | None = None,
    password: str | None = None,
    canvas_token: str | None = None,
    verify: bool = True,
    save: bool = True,
    force_save: bool = False,
    use_keyring: bool = True,
    clear_canvas_token: bool = False,
) -> SetupReport:
    """执行向导主体（可被命令与测试直接调用）。

    只给了 ``--canvas-token`` / ``--clear-canvas-token`` 而不给学号密码时，
    走「只管理令牌」路径：不碰教务凭据、不做验证。
    """
    report = SetupReport()
    canvas_token = (canvas_token or "").strip()
    token_only = not sid and not password and bool(canvas_token or clear_canvas_token)

    if token_only:
        if clear_canvas_token:
            report.canvas_note = "已清除本地令牌" if _clear_canvas() else "本地本无令牌，无需清除"
        if canvas_token:
            report.canvas_saved, note = _handle_canvas_token(canvas_token, verify)
            report.canvas_note = "；".join(x for x in (report.canvas_note, note) if x)
        _print_report(report)
        return report

    click.echo("西湖生存手册 · 首次配置")
    click.echo("公开功能（校历 / 班车 / 新闻 / 培养方案 / 通识课程 / 地图图片）无需账号，已可直接使用。")
    click.echo("下面填一次学号与密码；能自动接上的服务会一并接上，接不上的会说明原因。")
    click.echo("")

    if not sid:
        from westlake_survival.sso import read_credentials

        try:
            existing_sid, _ = read_credentials()
        except Exception:
            existing_sid = ""
        sid = click.prompt("学号", default=existing_sid, show_default=bool(existing_sid))
    if not password:
        password = click.prompt("密码", hide_input=True, confirmation_prompt=False)

    report.sid = sid

    if verify:
        click.echo("[1/2] 验教务（SIS）…", nl=False)
        ok, note = _probe_sis(sid, password)
        click.echo((" 成功" if ok else f" 未通过（{note}）"))
        report.sis_ok, report.sis_note = ok, note

    else:
        report.sis_ok, report.sis_note = False, "已跳过验证（--no-verify）"

    if save:
        # 先保存再报状态：验证失败也落盘，避免「校外/验证码/网络抖动」时白填一次；
        # 保存与否由 stored_in 与状态后缀如实标明，不冒充已验证。
        report.stored_in = _persist(sid, password, use_keyring=use_keyring)
        if verify and not report.sis_ok:
            report.extra.append(f"验证未通过（{report.sis_note}），凭据已先保存；之后查询会重新验证。")

    if clear_canvas_token:
        report.canvas_note = "已清除本地令牌" if _clear_canvas() else "本地本无令牌，无需清除"
    if canvas_token:
        report.canvas_saved, note = _handle_canvas_token(canvas_token, verify)
        report.canvas_note = "；".join(x for x in (report.canvas_note, note) if x)

    _print_report(report)
    return report


@click.command(name="setup")
@click.option("--sid", default=None, help="学号；缺省交互输入。")
@click.option("--password", default=None, help="密码；缺省交互隐藏输入（不要在共享环境用参数）。")
@click.option("--canvas-token", default=None, help="Canvas 令牌；会写入配置文件，供 REST API 优先使用。")
@click.option("--clear-canvas-token", is_flag=True, help="只删除本地 Canvas 令牌（回退统一密码）。")
@click.option("--no-verify", is_flag=True, help="跳过网络验证，只保存凭据/令牌。")
@click.option("--no-save", is_flag=True, help="只探测，不落盘。")
@click.option("--force-save", is_flag=True, help="兼容保留：现在验证未通过也会保存，无需此开关。")
@click.option("--no-keyring", is_flag=True, help="只写配置文件，不碰系统钥匙串（自动化用）。")
def setup_cmd(
    sid, password, canvas_token, clear_canvas_token, no_verify, no_save, force_save, no_keyring
) -> None:
    """首次配置：填一次学号密码，自动接上能用的服务。"""
    report = run_setup(
        sid=sid,
        password=password,
        canvas_token=canvas_token,
        verify=not no_verify,
        save=not no_save,
        force_save=force_save,
        use_keyring=not no_keyring,
        clear_canvas_token=clear_canvas_token,
    )
    # 交互向导本身跑完即成功；验证未通过时给非零退出码，便于脚本判断。
    # 只管理令牌（没填学号）时没有可判定的教务状态，按成功处理。
    ok_exit = no_verify or report.sis_ok or not report.sid
    raise SystemExit(0 if ok_exit else 1)
