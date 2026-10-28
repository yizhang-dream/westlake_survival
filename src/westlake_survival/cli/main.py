"""``westlake_survival`` 统一命令行：``westlake <子命令>``。

顶层 click group :data:`cli` 在此定义，各子命令直接调用对应模块的 Python
API（多数 I/O 子命令都要能被离线测试，故模块在函数体内惰性导入）。

约定：

- 所有会发起 I/O 的命令都用 :func:`_handle_errors` 包裹：捕获
  :class:`~westlake_survival.exceptions.WestlakeError`（含 :class:`AuthError` /
  :class:`OffCampusError` 等子类），向 stderr 打印中文友好提示并以退出码 1 结束；
  :class:`OffCampusError` 额外提示连接校园 VPN。
- ``--version`` 输出版本号；``python -m westlake_survival`` 等价于 ``westlake``。
- ``digest`` 把快照 / 活动 / 班车 / 周次 / Canvas 截止合成晨报文本，各源独立
  降级；``probe`` 逐项探测「堵点」状态；``cache clear`` 清理本地 ETag 缓存。
- ``sso creds`` 支持 keyring（系统钥匙串）：``set`` 缺省在 keyring 可用时优先
  写入，``status`` 显示内存 / 环境变量 / keyring / 文件四个来源。
"""

from __future__ import annotations

import functools
import json
import os
from datetime import date
from pathlib import Path
from unicodedata import east_asian_width

import click

from westlake_survival._version import __version__
from westlake_survival.calendar import AcademicCalendar
from westlake_survival.campus import cli_group as campus_cmd
from westlake_survival.campusmap import cli_group as map_cmd
from westlake_survival.careers import cli_group as careers_cmd
from westlake_survival.contact import cli_group as contact_cmd
from westlake_survival.discovery import cli_group as affairs_cmd
from westlake_survival.booking import cli_group as booking_cmd
from westlake_survival.sportvenue import cli_group as sport_cmd
from westlake_survival.hosts import cli_group as hosts_cmd
from westlake_survival.finance import cli_group as finance_cmd
from westlake_survival.hpc import cli_group as hpc_cmd
from westlake_survival.mirrors import cli_group as mirrors_cmd
from westlake_survival.institute import cli_group as institute_cmd
from westlake_survival.schools import cli_group as schools_cmd
from westlake_survival.sites import cli_group as sites_cmd
from westlake_survival.vpn import cli_group as vpn_cmd
from westlake_survival.taskcenter import cli_group as todo_cmd
from westlake_survival.portal import cli_group as portal_cmd
from westlake_survival.scholar import cli_group as scholar_cmd
from westlake_survival.careersite import cli_group as careersite_cmd
from westlake_survival.events import cli_group as events_cmd
from westlake_survival.exceptions import AuthError, OffCampusError, WestlakeError
from westlake_survival.faculty import cli_group as faculty_cmd
from westlake_survival.news import cli_group as news_cmd
from westlake_survival.program import cli_group as program_cmd
from westlake_survival.research import cli_group as research_cmd
from westlake_survival.search import cli_group as search_cmd
from westlake_survival.wikilake import cli_group as wiki_cmd
from westlake_survival.setup_cmd import setup_cmd
from westlake_survival.sharepoint import cli_group as share_cmd
from westlake_survival.sis.aid import cli_group as aid_cmd
from westlake_survival.sis.evals import cli_group as evals_cmd
from westlake_survival.sis.profile import cli_group as profile_cmd
from westlake_survival.sis.records import cli_group as records_cmd
from westlake_survival.transit import Campus, DayKind

#: 星期几的中文名（``date.weekday()`` 0=周一）。
_WEEKDAY_CN = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

#: Canvas 缺少访问令牌时的引导。
_CANVAS_TOKEN_HINT = (
    "获取令牌：登录 Canvas 网页 → 账户 → 设置 → 新建访问令牌；\n"
    "随后设置环境变量 WESTLAKE_CANVAS_TOKEN，或写入 "
    "~/.westlake_survival/canvas_token.txt（首行）。"
)


# --------------------------------------------------------------------------- #
# 通用：错误处理与表格输出
# --------------------------------------------------------------------------- #
def _print_error(exc: WestlakeError) -> None:
    """向 stderr 打印中文错误提示。"""
    click.secho(f"错误：{exc}", fg="red", err=True)
    if isinstance(exc, OffCampusError):
        click.secho(
            "提示：该服务仅校园网/VPN 内可达，请先连接西湖大学 VPN："
            "https://vpn.westlake.edu.cn/",
            err=True,
        )


def _handle_errors(func):
    """装饰器：把 :class:`WestlakeError` 转成中文提示 + 退出码 1。"""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except WestlakeError as exc:
            _print_error(exc)
            raise SystemExit(1) from exc

    return wrapper


def _width(text: str) -> int:
    """按东亚宽度估算显示宽度（全角/宽字符记 2 列）。"""
    return sum(2 if east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def _print_table(rows, headers) -> None:
    """打印对齐的文本表格；按东亚宽度处理中文列宽。"""
    table = [[("" if c is None else str(c)) for c in row] for row in rows]
    table.insert(0, [str(h) for h in headers])
    widths = [max(_width(r[i]) for r in table) for i in range(len(headers))]
    for index, row in enumerate(table):
        cells = [c + " " * (widths[i] - _width(c)) for i, c in enumerate(row)]
        click.echo("  ".join(cells).rstrip())
        if index == 0:
            click.echo("  ".join("-" * w for w in widths))


# --------------------------------------------------------------------------- #
# sso —— 凭据与登录
# --------------------------------------------------------------------------- #
@click.group(name="sso", help="统一身份认证：凭据管理与登录验证。")
def sso_cmd() -> None:
    """SSO（统一身份认证）相关命令。"""


@sso_cmd.group(name="creds", help="凭据管理（set / status）。")
def sso_creds() -> None:
    """凭据写入与来源检测。"""


#: keyring（系统钥匙串）集成的函数名候选。
#:
#: ``sso.creds`` 的 keyring 接口由并行开发提供，命名未必与本文一致；故一律
#: 用 :func:`_find_callable` 按候选名探测，**任何候选都缺失时降级为原有的
#: 三级来源（内存 / 环境变量 / 配置文件）行为**，绝不因缺函数而报错。
_KEYRING_WRITE_NAMES = (
    "save_credentials_keyring",
    "write_keyring_credentials",
    "keyring_write",
    "write_to_keyring",
    "save_keyring_credentials",
    "store_keyring_credentials",
    "keyring_set",
)
_KEYRING_READ_NAMES = (
    "read_credentials_keyring",
    "read_keyring_credentials",
    "keyring_read",
    "read_from_keyring",
    "load_keyring_credentials",
    "keyring_get",
)
_KEYRING_AVAILABLE_NAMES = (
    "keyring_available",
    "is_keyring_available",
    "has_keyring",
    "keyring_supported",
)


def _find_callable(module, names) -> object | None:
    """返回 *module* 上第一个可调用的候选函数；都没有返回 ``None``。"""
    for name in names:
        attr = getattr(module, name, None)
        if callable(attr):
            return attr
    return None


def _keyring_writer(creds_mod):
    """keyring 写入函数；``sso.creds`` 未提供时返回 ``None``。"""
    return _find_callable(creds_mod, _KEYRING_WRITE_NAMES)


def _keyring_reader(creds_mod):
    """keyring 读取函数；``sso.creds`` 未提供时返回 ``None``。"""
    return _find_callable(creds_mod, _KEYRING_READ_NAMES)


def _keyring_available(creds_mod) -> bool:
    """keyring 是否可用（有探测函数用其结果，否则要求读写函数齐备）。"""
    for name in _KEYRING_AVAILABLE_NAMES:
        attr = getattr(creds_mod, name, None)
        if isinstance(attr, bool):
            return attr
        if callable(attr):
            try:
                return bool(attr())
            except Exception:  # noqa: BLE001 - 探测失败即视为不可用
                return False
    return _keyring_writer(creds_mod) is not None and _keyring_reader(creds_mod) is not None


def _as_cred_pair(value) -> tuple[str, str] | None:
    """把 keyring 读取结果规整为 ``(sid, password)``；无法识别返回 ``None``。

    兼容两种契约：``(sid, password)`` 二元组 / ``None``，以及 ``sid:password``
    字符串。``False``（写入结果标志位等）一律视为无凭据。
    """
    if not value or value is True:
        return None
    if isinstance(value, str):
        if ":" not in value:
            return None
        sid, _, password = value.partition(":")
        return (sid.strip(), password.strip()) if sid.strip() and password.strip() else None
    if isinstance(value, (tuple, list)):
        if len(value) < 2:
            return None
        sid, password = str(value[0] or "").strip(), str(value[1] or "").strip()
        return (sid, password) if sid and password else None
    if isinstance(value, dict):
        sid = str(value.get("sid") or value.get("username") or "").strip()
        password = str(value.get("password") or "").strip()
        return (sid, password) if sid and password else None
    return None


def _keyring_lookup(creds_mod) -> tuple[str, str] | None:
    """从 keyring 读凭据；无接口 / 无记录 / 读失败均返回 ``None``。"""
    reader = _keyring_reader(creds_mod)
    if reader is None:
        return None
    try:
        return _as_cred_pair(reader())
    except Exception:  # noqa: BLE001 - 读钥匙串失败不应阻断状态查询
        return None


def _keyring_state(creds_mod) -> tuple[bool, bool]:
    """返回 ``(keyring 中是否有凭据, keyring 是否可用)``。

    隔离模式（``WESTLAKE_NO_KEYRING=1`` 或 ``WESTLAKE_HOME`` 重定向）下读取路径
    完全不看钥匙串，这里也如实报「无」，否则状态页会显示一个实际用不上的来源。
    """
    isolated = getattr(creds_mod, "keyring_isolated", None)
    if isolated is not None and isolated():
        return False, False
    if not _keyring_available(creds_mod):
        return False, False
    return (_keyring_lookup(creds_mod) is not None), True


@sso_creds.command(name="set")
@click.option("--sid", default=None, help="学号（SID）；缺省时交互输入。")
@click.option("--password", default=None, help="密码；缺省时交互输入（隐藏）。")
@click.option(
    "--keyring/--no-keyring",
    "use_keyring",
    default=None,
    help="写入系统钥匙串（keyring）；缺省在 keyring 可用时优先写入并提示，"
    "--no-keyring 强制写配置文件。",
)
@_handle_errors
def sso_creds_set(
    sid: str | None, password: str | None, use_keyring: bool | None
) -> None:
    """写入凭据：keyring 可用时写入钥匙串，否则写配置文件（只会存在一份）。

    缺省参数时会提示输入学号与密码（密码输入隐藏且需二次确认）。
    keyring 需要可选依赖：``pip install 'westlake_survival[secure]'``。
    """
    from westlake_survival.sso import creds as creds_mod

    if not sid:
        sid = click.prompt("西湖大学学号 (SID)", type=str)
    if not password:
        password = click.prompt("密码", hide_input=True, confirmation_prompt=True)

    stored = creds_mod.persist_credentials(
        sid, password, use_keyring=use_keyring is not False
    )
    if stored == "系统钥匙串":
        click.secho("凭据已写入 keyring（系统钥匙串）。", fg="green")
        click.echo("提示：已删除明文 credentials.txt，凭据只保留一份。")
    else:
        click.secho(f"凭据已写入：{stored}", fg="green")
        if use_keyring is not False:
            if os.environ.get("WESTLAKE_HOME"):
                click.echo(
                    "提示：WESTLAKE_HOME 已重定向（沙箱/试跑），只写配置文件，"
                    "不碰本机真实钥匙串。"
                )
            else:
                click.echo("提示：keyring 不可用或写入失败，已回退到明文文件（仍是唯一一份）。")


@sso_creds.command(name="show")
def sso_creds_show() -> None:
    """在终端显示已保存的教务学号与密码（密码管理器的「显示密码」）。

    只应在你自己的机器上使用：输出走 stdout，不写日志。凭据是你本机存的，
    忘记 SIS 密码时用它找回；网页端等价入口在「设置」页。
    """
    from westlake_survival.sso import read_credentials

    try:
        sid, password = read_credentials()
    except Exception as exc:
        click.secho(f"未找到已保存的凭据：{exc}", fg="yellow", err=True)
        raise SystemExit(1) from exc
    click.echo(f"学号：{sid}")
    click.echo(f"密码：{password}")
    click.echo("（此输出仅在你的终端；SIS 密码与校园门户密码不同源）")


@sso_creds.command(name="status")
def sso_creds_status() -> None:
    """检测当前凭据来源（内存 / 环境变量 / keyring / 配置文件 / 无）。

    优先级与 :func:`westlake_survival.sso.read_credentials` 一致；只显示来源
    与路径、以及四来源的「有 / 无」，绝不打印密码。
    """
    from westlake_survival.sso import cred_path
    from westlake_survival.sso import creds as creds_mod

    memory = getattr(creds_mod, "_MEMORY", {}) or {}
    path = cred_path()
    env_value = os.environ.get(creds_mod.ENV_VAR)

    memory_ok = bool(memory.get("sid") and memory.get("password"))
    env_ok = bool(env_value and env_value.strip())
    keyring_ok, keyring_available = _keyring_state(creds_mod)
    file_ok = path.exists()

    if memory_ok:
        click.secho("凭据来源：内存（cred_set）", bold=True)
        click.echo("说明：进程内凭据优先级最高，退出即丢失，不落盘。")
    elif env_ok:
        click.secho(f"凭据来源：环境变量 {creds_mod.ENV_VAR}", bold=True)
        click.echo("说明：格式为 学号:密码，环境变量优先级高于 keyring 与配置文件。")
    elif keyring_ok:
        click.secho("凭据来源：keyring（系统钥匙串）", bold=True)
        click.echo("说明：keyring 优先级高于明文配置文件，凭据由系统加密封存。")
    elif file_ok:
        click.secho(f"凭据来源：配置文件 {path}", bold=True)
    else:
        click.secho("凭据来源：无", bold=True)
        click.echo(f"期望的配置文件路径：{path}")
        click.echo("设置方法：westlake sso creds set（密码输入隐藏）")

    click.echo("来源清单（只报有 / 无，不回显密码）：")
    click.echo(f"  - 内存：{'有' if memory_ok else '无'}")
    click.echo(f"  - 环境变量 {creds_mod.ENV_VAR}：{'有' if env_ok else '无'}")
    if os.environ.get("WESTLAKE_NO_KEYRING"):
        click.echo("  - keyring：已忽略（WESTLAKE_NO_KEYRING 生效，读写都不碰钥匙串）")
    elif os.environ.get("WESTLAKE_HOME"):
        click.echo(
            "  - keyring：已忽略（WESTLAKE_HOME 指向非默认配置目录，沙箱内读写都不碰钥匙串）"
        )
    elif keyring_available:
        click.echo(f"  - keyring：{'有' if keyring_ok else '无'}")
    else:
        click.echo("  - keyring：不可用（未安装 [secure] extra 或 sso.creds 未提供接口）")
    click.echo(f"  - 配置文件 {path}：{'有' if file_ok else '无'}")
    if not (memory_ok or env_ok or keyring_ok or file_ok):
        click.echo("设置方法：westlake setup（或网页 /setup）")


@sso_cmd.command(name="login")
@_handle_errors
def sso_login() -> None:
    """用已配置凭据尝试登录 SIS，验证凭据是否有效。"""
    from westlake_survival.sso import SISAuth

    SISAuth().ensure()
    click.secho("登录成功：凭据有效，SIS 会话已建立。", fg="green")


# --------------------------------------------------------------------------- #
# calendar —— 校历
# --------------------------------------------------------------------------- #
@click.group(name="calendar", help="校历：日期/周次/学期/事件。")
def calendar_cmd() -> None:
    """校历查询命令。"""


def _load_calendar() -> AcademicCalendar:
    """加载校历（网络失败时由模块内部回退到内置数据）。"""
    return AcademicCalendar.load()


@calendar_cmd.command(name="today")
@_handle_errors
def calendar_today() -> None:
    """显示今天的日期、星期、学期、周次与当日事件。"""
    calendar = _load_calendar()
    today = date.today()
    click.echo(f"日期：{today.isoformat()}（{_WEEKDAY_CN[today.weekday()]}）")

    semester = calendar.current(today)
    if semester is None:
        click.echo("学期：当前不在任何学期的教学范围内")
        click.echo("周次：—（假期或学期外）")
        return

    week = semester.week_of(today)
    click.echo(f"学期：{semester.name}")
    click.echo(f"周次：第 {week} 周" if week else "周次：—（假期或学期外）")

    events = [e for e in semester.events if e.covers(today)]
    if events:
        click.echo("今日事件：")
        for event in events:
            click.echo(f"  - {event.title}")
    else:
        click.echo("今日事件：无")


@calendar_cmd.command(name="events")
@_handle_errors
def calendar_events() -> None:
    """列出当前学期（或最近学期）的全部校历事件。"""
    calendar = _load_calendar()
    semester = calendar.current(date.today())
    if semester is None and calendar.semesters:
        semester = calendar.semesters[-1]
    if semester is None:
        click.secho("未找到任何学期数据。", fg="red", err=True)
        raise SystemExit(1)

    click.echo(f"学期：{semester.name}（{semester.start.isoformat()} ~ {semester.end.isoformat()}）")
    rows = [
        (e.start.isoformat(), (e.end.isoformat() if e.end else "—"), e.title)
        for e in semester.events
    ]
    _print_table(rows, ("开始", "结束", "事件"))


@calendar_cmd.command(name="week")
@click.argument("n", type=int)
@_handle_errors
def calendar_week(n: int) -> None:
    """显示本学期第 N 周的起止日期（周一 ~ 周日）。"""
    calendar = _load_calendar()
    semester = calendar.current(date.today())
    if semester is None and calendar.semesters:
        semester = calendar.semesters[-1]
    if semester is None:
        click.secho("未找到任何学期数据。", fg="red", err=True)
        raise SystemExit(1)

    total = semester.teaching_weeks()
    if n < 1 or n > total:
        click.secho(f"第 {n} 周超出本学期范围（共 {total} 周）。", fg="red", err=True)
        raise SystemExit(1)
    click.echo(
        f"{semester.name} 第 {n} 周：{semester.date_of(n, 1).isoformat()} "
        f"~ {semester.date_of(n, 7).isoformat()}"
    )


# --------------------------------------------------------------------------- #
# transit —— 校园巴士
# --------------------------------------------------------------------------- #
@click.group(name="transit", help="校园巴士：下一班 / 时刻表 / 导出日历。")
def transit_cmd() -> None:
    """校园巴士命令。"""


def _campus(value: str | None) -> Campus | None:
    return Campus(value) if value else None


@transit_cmd.command(name="next")
@click.option("--campus", type=click.Choice([c.value for c in Campus]), default=None, help="只看某校区（始发）。")
@click.option("--limit", type=int, default=3, show_default=True, help="返回条数。")
@_handle_errors
def transit_next(campus: str | None, limit: int) -> None:
    """显示下一批发车时刻（默认取前 3 班）。"""
    from westlake_survival.transit import transit

    data = transit()
    departures = data.next_departures(campus=_campus(campus), limit=limit)
    if not departures:
        click.echo("暂无后续班车信息。")
        return
    rows = [
        (str(i), time_str, table.campus.value, table.day_kind.value)
        for i, (table, time_str) in enumerate(departures, start=1)
    ]
    _print_table(rows, ("序号", "时刻", "始发校区", "日别"))


@transit_cmd.command(name="table")
@click.option("--campus", type=click.Choice([c.value for c in Campus]), default=None, help="校区。")
@click.option("--day", type=click.Choice([d.value for d in DayKind]), default=None, help="日别。")
@_handle_errors
def transit_table(campus: str | None, day: str | None) -> None:
    """显示指定校区/日别的班车时刻表。"""
    from westlake_survival.transit import transit

    data = transit()
    campus_enum = _campus(campus)
    day_enum = DayKind(day) if day else None
    tables = [
        t
        for t in data.tables
        if (campus_enum is None or t.campus == campus_enum)
        and (day_enum is None or t.day_kind == day_enum)
    ]
    if not tables:
        click.echo("未找到匹配的时刻表。")
        return
    for table in tables:
        click.echo(f"【{table.campus.value} · {table.day_kind.value}】{table.direction_note}")
        rows = [(section, "、".join(times) or "—") for section, times in (
            ("上午", table.morning),
            ("午间", table.noon),
            ("晚间", table.night),
        )]
        _print_table(rows, ("时段", "时刻"))


@transit_cmd.command(name="ical")
@click.option("--days", type=int, default=14, show_default=True, help="导出未来天数。")
@click.option("--out", type=click.Path(dir_okay=False, path_type=Path), default=None, help="写入 .ics 文件；缺省打印到标准输出。")
@_handle_errors
def transit_ical(days: int, out: Path | None) -> None:
    """导出未来若干天的班车日历（.ics）。"""
    from westlake_survival.transit import transit_to_ical

    text = transit_to_ical(weekdays_ahead=days)
    if out is None:
        click.echo(text, nl=False)
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    click.secho(f"已写入：{out}", fg="green")


# --------------------------------------------------------------------------- #
# canvas —— Canvas LMS
# --------------------------------------------------------------------------- #
def _handle_canvas_errors(func):
    """Canvas 命令专用：AuthError 额外给出令牌获取引导。"""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except AuthError as exc:
            click.secho(f"错误：{exc}", fg="red", err=True)
            # 库自身缺 token 的 AuthError 已含引导；仅在消息未提及时补充。
            if "新建访问令牌" not in str(exc):
                click.secho(_CANVAS_TOKEN_HINT, err=True)
            raise SystemExit(1) from exc
        except WestlakeError as exc:
            _print_error(exc)
            raise SystemExit(1) from exc

    return wrapper


def _human_size(size: int | None) -> str:
    """把字节数转成便于阅读的 KB / MB 文本；未知大小返回 ``—``。"""
    if not size:
        return "—"
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def _download_target(directory: Path, name: str, file_id: int) -> Path:
    """给下载文件挑一个不互相覆盖的落点（只取文件名，防目录穿越）。"""
    safe = Path(name or "").name or f"file-{file_id}"
    target = directory / safe
    if target.exists():
        target = directory / f"{target.stem}-{file_id}{target.suffix}"
    return target


def _download_one(client, file_id: int, target_dir: Path, name: str) -> None:
    """下载一个文件到 *target_dir*；失败只告警，不中断整批下载。"""
    dest = _download_target(target_dir, name, file_id)
    try:
        saved = client.download_file(file_id, dest)
    except WestlakeError as exc:
        click.secho(f"下载失败（file_id={file_id}）：{exc}", fg="red", err=True)
        return
    click.echo(f"已保存：{saved}")


def _people_label(names: list[str] | tuple[str, ...], limit: int = 2) -> str:
    """把参与者名单压成「前 N 人 等 M 人」，避免群发会话撑爆表格。"""
    names = [name for name in names if name]
    if not names:
        return "—"
    if len(names) <= limit:
        return "、".join(names)
    return "、".join(names[:limit]) + f" 等 {len(names)} 人"


@click.group(name="canvas", help="Canvas LMS：课程、作业、文件与公告。")
def canvas_cmd() -> None:
    """Canvas 命令（令牌或统一密码会话均可）。"""


@canvas_cmd.command(name="courses")
@_handle_canvas_errors
def canvas_courses() -> None:
    """列出当前账号的 Canvas 课程。"""
    from westlake_survival.canvas import canvas

    courses = canvas().list_courses()
    rows = [(c.course_code or "—", c.name or "—", c.term_name or "—") for c in courses]
    _print_table(rows, ("课程代码", "课程名称", "学期"))


@canvas_cmd.command(name="deadlines")
@click.option("--limit", type=int, default=10, show_default=True, help="返回条数。")
@_handle_canvas_errors
def canvas_deadlines(limit: int) -> None:
    """列出即将到期的作业截止时间。"""
    from westlake_survival.canvas import canvas

    items = canvas().upcoming_deadlines(limit=limit)
    rows = [
        (
            a.due_at.strftime("%Y-%m-%d %H:%M") if a.due_at else "—",
            a.name or "—",
            a.html_url or "",
        )
        for a in items
    ]
    _print_table(rows, ("截止时间", "作业", "链接"))


@canvas_cmd.command(name="todo")
@click.option("--limit", type=int, default=20, show_default=True, help="返回条数。")
@_handle_canvas_errors
def canvas_todo(limit: int) -> None:
    """列出 Canvas 待办（users/self/todo）。"""
    from westlake_survival.canvas import canvas

    items = canvas().todo(limit=limit)
    if not items:
        click.echo("暂无待办")
        return
    rows = [
        (
            item.due_at.strftime("%Y-%m-%d %H:%M") if item.due_at else "—",
            item.course or "—",
            item.title or "—",
            item.url or "",
        )
        for item in items
    ]
    _print_table(rows, ("截止", "课程", "事项", "链接"))


@canvas_cmd.command(name="modules")
@click.argument("course")
@_handle_canvas_errors
def canvas_modules(course: str) -> None:
    """列出某课程的模块与条目（COURSE 可为 id 或名称关键词）。"""
    from westlake_survival.canvas import canvas

    client = canvas()
    target = client.find_course(course)
    modules = client.modules(target.id)
    if not modules:
        click.echo("该课程没有模块或未开放")
        return
    for index, module in enumerate(modules, 1):
        click.secho(f"{index}. {module['name']}（{module['count']} 项）", bold=True)
        for item in module["items"]:
            click.echo(f"   - [{item['type']}] {item['title']} {item['url']}")


@canvas_cmd.command(name="files")
@click.option("--course", required=True, help="课程 id 或名称关键词。")
@click.option("--match", default=None, help="只处理文件名含该关键词的条目。")
@click.option(
    "--download",
    "download_dir",
    type=click.Path(file_okay=False),
    default=None,
    help="下载到该目录（不存在会自动创建）；不给则只列清单。",
)
@_handle_canvas_errors
def canvas_files(course: str, match: str | None, download_dir: str | None) -> None:
    """列出课程文件区；给 --download 时一并下载。"""
    from westlake_survival.canvas import canvas

    client = canvas()
    found = client.find_course(course)
    files = client.list_files(found.id)
    if match:
        needle = match.lower()
        files = [item for item in files if needle in (item.display_name or "").lower()]
    if not files:
        click.echo("没有匹配的课程文件")
        return
    rows = [
        (str(item.id or "—"), item.display_name or "—", _human_size(item.size))
        for item in files
    ]
    _print_table(rows, ("文件ID", "文件名", "大小"))
    click.echo(f"课程：{found.course_code or ''} {found.name}（{len(files)} 个文件）")
    if not download_dir:
        click.echo("提示：加 --download <目录> 可一并下载。")
        return
    target_dir = Path(download_dir).expanduser()
    target_dir.mkdir(parents=True, exist_ok=True)
    for item in files:
        if item.id is None:
            continue
        _download_one(client, item.id, target_dir, item.display_name or "")


@canvas_cmd.command(name="discussions")
@click.option("--course", required=True, help="课程 id 或名称关键词。")
@_handle_canvas_errors
def canvas_discussions(course: str) -> None:
    """列出课程讨论主题（标题 / 未读 / 回复数 / 时间）。"""
    from westlake_survival.canvas import canvas

    client = canvas()
    found = client.find_course(course)
    items = client.discussions(found.id)
    if not items:
        click.echo("该课程没有讨论主题")
        return
    rows = [
        (
            item["title"] or "—",
            str(item["unread"]),
            str(item["replies"]),
            item["posted"].strftime("%Y-%m-%d %H:%M") if item["posted"] else "—",
            item["url"] or "",
        )
        for item in items
    ]
    _print_table(rows, ("标题", "未读", "回复", "时间", "链接"))


@canvas_cmd.command(name="announcements")
@click.option("--course", required=True, help="课程 id 或名称关键词。")
@_handle_canvas_errors
def canvas_announcements(course: str) -> None:
    """列出课程公告（时间 / 标题 / 链接）。"""
    from westlake_survival.canvas import canvas

    client = canvas()
    found = client.find_course(course)
    items = client.list_announcements(found.id)
    if not items:
        click.echo("该课程没有公告")
        return
    rows = [
        (
            item.posted_at.strftime("%Y-%m-%d %H:%M") if item.posted_at else "—",
            item.title or "—",
            item.html_url or "",
        )
        for item in items
    ]
    _print_table(rows, ("时间", "标题", "链接"))


def _resolve_topic(client, course_id, keyword: str) -> int:
    """把讨论主题 id 或标题关键词解析成 topic id。"""
    return client.find_topic(course_id, keyword)


@canvas_cmd.command(name="inbox")
@click.option("--limit", type=int, default=20, show_default=True, help="返回条数。")
@click.option("--unread", "only_unread", is_flag=True, help="只看未读会话。")
@_handle_canvas_errors
def canvas_inbox(limit: int, only_unread: bool) -> None:
    """收件箱会话列表（未读 / 时间 / 课程 / 主题 / 参与者）。"""
    from westlake_survival.canvas import canvas

    client = canvas()
    unread = client.unread_count()
    items = client.conversations(limit=limit if not only_unread else 100)
    if only_unread:
        items = [item for item in items if item["unread"]][:limit]
    if not items:
        click.echo(f"收件箱没有{'未读' if only_unread else ''}会话" + (f"（未读 {unread}）" if unread else ""))
        return
    rows = [
        (
            "●" if item["unread"] else "",
            item["last_message_at"].strftime("%Y-%m-%d %H:%M") if item["last_message_at"] else "—",
            item["course"] or "—",
            item["subject"] or "—",
            _people_label(item["participants"]),
            str(item["messages"]),
            str(item["id"]),
        )
        for item in items
    ]
    _print_table(rows, ("未读", "时间", "课程", "主题", "参与者", "条数", "会话ID"))
    click.echo(f"未读会话：{unread}")


@canvas_cmd.command(name="conversation")
@click.argument("conversation_id", type=int)
@click.option(
    "--download",
    "download_dir",
    type=click.Path(file_okay=False),
    default=None,
    help="把消息附件下载到该目录。",
)
@_handle_canvas_errors
def canvas_conversation(conversation_id: int, download_dir: str | None) -> None:
    """查看一个会话的完整消息（CONVERSATION_ID 由 canvas inbox 给出）。"""
    from westlake_survival.canvas import canvas
    from westlake_survival.canvas.models import html_to_text

    client = canvas()
    thread = client.conversation(conversation_id)
    click.echo(f"主题：{thread['subject'] or '—'}")
    if thread["course"]:
        click.echo(f"课程：{thread['course']}")
    click.echo(f"参与者：{_people_label(thread['participants'], limit=3)}")
    if thread["cannot_reply"]:
        click.echo("状态：该会话不可回复")
    target_dir = Path(download_dir).expanduser() if download_dir else None
    if target_dir:
        target_dir.mkdir(parents=True, exist_ok=True)
    for message in thread["messages"]:
        when = message["created_at"].strftime("%Y-%m-%d %H:%M") if message["created_at"] else "—"
        click.secho(f"\n[{when}] {message['author'] or '—'}", bold=True)
        body = html_to_text(message["body"])
        if body:
            click.echo(body)
        for item in message["attachments"]:
            click.echo(f"   附件：{item.display_name}（file_id={item.id}，{_human_size(item.size)}）")
            if target_dir and item.id is not None:
                _download_one(client, item.id, target_dir, item.display_name or "")


@canvas_cmd.command(name="send")
@click.option("--conversation", "conversation_id", type=int, required=True, help="会话 id（canvas inbox 可见）。")
@click.option("--text", required=True, help="回复正文（纯文本）。")
@click.option("--yes", "skip_confirm", is_flag=True, help="跳过确认直接发送。")
@_handle_canvas_errors
def canvas_send(conversation_id: int, text: str, skip_confirm: bool) -> None:
    """在已有会话里回一条消息（写操作）。"""
    from westlake_survival.canvas import canvas

    client = canvas()
    thread = client.conversation(conversation_id)
    click.echo(f"会话：{thread['subject'] or '—'}（id={conversation_id}）")
    click.echo(f"参与者：{_people_label(thread['participants'], limit=3)}")
    click.secho(f"将发送：{text}", fg="yellow")
    if thread["cannot_reply"]:
        raise click.ClickException("该会话标记为不可回复")
    if not skip_confirm:
        click.confirm("确认发送以上内容？", abort=True)
    client.reply_conversation(conversation_id, text)
    click.secho("已发送。", fg="green")


@canvas_cmd.command(name="discussion")
@click.option("--course", required=True, help="课程 id 或名称关键词。")
@click.option("--topic", required=True, help="讨论主题 id 或标题关键词。")
@click.option("--download", "download_dir", type=click.Path(file_okay=False), default=None,
              help="把主题附件下载到该目录。")
@_handle_canvas_errors
def canvas_discussion(
    course: str, topic: str, download_dir: str | None
) -> None:
    """查看一个讨论主题的正文（首帖 + 附件 + 回帖数）。"""
    from westlake_survival.canvas import canvas
    from westlake_survival.canvas.models import html_to_text

    client = canvas()
    found = client.find_course(course)
    topic_id = _resolve_topic(client, found.id, topic)
    detail = client.discussion_topic(found.id, topic_id)
    when = detail["posted_at"].strftime("%Y-%m-%d %H:%M") if detail["posted_at"] else "—"
    click.echo(f"主题：{detail['title']}（id={detail['id']}，{when}，{detail['author'] or '—'}）")
    click.echo(f"回帖：{detail['entries']} 条　链接：{detail['url']}")
    body = html_to_text(detail["message"])
    if body:
        click.echo(body)
    target_dir = Path(download_dir).expanduser() if download_dir else None
    if target_dir:
        target_dir.mkdir(parents=True, exist_ok=True)
    for item in detail["attachments"]:
        click.echo(f"附件：{item.display_name}（file_id={item.id}，{_human_size(item.size)}）")
        if target_dir and item.id is not None:
            _download_one(client, item.id, target_dir, item.display_name or "")


@canvas_cmd.command(name="entries")
@click.option("--course", required=True, help="课程 id 或名称关键词。")
@click.option("--topic", required=True, help="讨论主题 id 或标题关键词。")
@click.option("--limit", type=int, default=20, show_default=True, help="返回条数。")
@click.option("--full", is_flag=True, help="不截断回帖正文。")
@_handle_canvas_errors
def canvas_entries(course: str, topic: str, limit: int, full: bool) -> None:
    """列出讨论主题下的回帖。"""
    from westlake_survival.canvas import canvas
    from westlake_survival.canvas.models import html_to_text

    client = canvas()
    found = client.find_course(course)
    topic_id = _resolve_topic(client, found.id, topic)
    items = client.discussion_entries(found.id, topic_id, limit=limit)
    if not items:
        click.echo("该主题还没有回帖")
        return
    rows = [
        (
            item["created_at"].strftime("%Y-%m-%d %H:%M") if item["created_at"] else "—",
            item["author"] or "—",
            "" if item["parent_id"] else "顶层",
            html_to_text(item["message"])[:120] if not full else html_to_text(item["message"]),
        )
        for item in items
    ]
    _print_table(rows, ("时间", "作者", "层级", "内容"))


@canvas_cmd.command(name="reply")
@click.option("--course", required=True, help="课程 id 或名称关键词。")
@click.option("--topic", required=True, help="讨论主题 id 或标题关键词。")
@click.option("--text", required=True, help="回帖正文（纯文本）。")
@click.option("--yes", "skip_confirm", is_flag=True, help="跳过确认直接发布。")
@_handle_canvas_errors
def canvas_reply(course: str, topic: str, text: str, skip_confirm: bool) -> None:
    """在讨论主题下回帖（写操作）。"""
    from westlake_survival.canvas import canvas

    client = canvas()
    found = client.find_course(course)
    topic_id = _resolve_topic(client, found.id, topic)
    detail = client.discussion_topic(found.id, topic_id)
    click.echo(f"课程：{found.course_code or ''} {found.name}")
    click.echo(f"主题：{detail['title']}（id={topic_id}）")
    click.secho(f"将发布：{text}", fg="yellow")
    if not skip_confirm:
        click.confirm("确认发布以上回帖？", abort=True)
    client.reply_to_discussion(found.id, topic_id, text)
    click.secho("已发布。", fg="green")


@canvas_cmd.command(name="exams")
@click.option("--days", type=int, default=None, help="只看未来 N 天（含今天）；缺省不过滤。")
@_handle_canvas_errors
def canvas_exams(days: int | None) -> None:
    """列出考试安排（测验型作业 ∪ 课程日历事件）。"""
    from westlake_survival.canvas import canvas
    from westlake_survival.canvas.models import KIND_QUIZ

    if days is not None and days < 0:
        raise click.UsageError(f"--days 必须 >= 0，得到 {days}")

    items = canvas().exams(days=days)
    rows: list[tuple[str, str, str, str]] = []
    for item in items:
        when = item.due_at if item.kind == KIND_QUIZ else item.start_at
        label = "测验" if item.kind == KIND_QUIZ else "日历"
        rows.append(
            (
                when.strftime("%Y-%m-%d %H:%M") if when else "—",
                item.title or "—",
                label,
                item.url or "",
            )
        )
    _print_table(rows, ("时间", "名称", "类型", "链接"))


@canvas_cmd.command(name="assignments")
@click.option("--course", required=True, help="课程 id 或名称关键词。")
@_handle_canvas_errors
def canvas_assignments(course: str) -> None:
    """列出课程作业（查作业 id / 名称关键词）。"""
    from westlake_survival.canvas import canvas

    found = canvas().find_course(course)
    items = canvas().list_assignments(found.id)
    rows = [
        (
            str(a.id or "—"),
            a.name or "—",
            a.due_at.strftime("%Y-%m-%d %H:%M") if a.due_at else "—",
            "、".join(a.submission_types) or "—",
        )
        for a in items
    ]
    _print_table(rows, ("作业ID", "作业", "截止时间", "提交类型"))
    click.echo(f"课程：{found.course_code or ''} {found.name}（id={found.id}）")


@canvas_cmd.command(name="assignment-info")
@click.option("--course", required=True, help="课程 id 或名称关键词。")
@click.option("--assignment", required=True, help="作业 id 或名称关键词。")
@click.option(
    "--download",
    "download_dir",
    type=click.Path(file_okay=False),
    default=None,
    help="把描述里的附件下载到该目录。",
)
@click.option("--full", is_flag=True, help="显示完整描述（默认截断 2000 字）。")
@_handle_canvas_errors
def canvas_assignment_info(
    course: str, assignment: str, download_dir: str | None, full: bool
) -> None:
    """查看作业详情：题目描述 + 附件 + 评分细则（可下载）。"""
    from westlake_survival.canvas import canvas
    from westlake_survival.canvas.models import html_to_text

    client = canvas()
    found_course = client.find_course(course)
    found_assignment = client.find_assignment(found_course.id, assignment)
    detail = client.get_assignment(found_course.id, found_assignment.id)
    click.echo(f"课程：{found_course.course_code or ''} {found_course.name}（id={found_course.id}）")
    click.echo(f"作业：{detail.name}（id={detail.id}）")
    due = detail.due_at.strftime("%Y-%m-%d %H:%M") if detail.due_at else "—"
    points = "—" if detail.points_possible is None else f"{detail.points_possible:g}"
    locked = "是" if detail.locked_for_user else "否"
    click.echo(
        f"截止：{due}　满分：{points}　锁定：{locked}　"
        f"提交类型：{'、'.join(detail.submission_types) or '—'}"
    )
    constraints: list[str] = []
    if detail.grading_type:
        constraints.append(f"评分方式：{detail.grading_type}")
    if detail.allowed_attempts is not None:
        attempts = "不限" if detail.allowed_attempts < 0 else str(detail.allowed_attempts)
        constraints.append(f"提交次数：{attempts}")
    if detail.allowed_extensions:
        constraints.append(f"允许扩展名：{'、'.join(detail.allowed_extensions)}")
    if constraints:
        click.echo("　".join(constraints))
    if detail.rubric:
        click.secho("评分细则：", bold=True)
        for criterion in detail.rubric:
            name = criterion.get("description") or "—"
            score = criterion.get("points")
            click.echo(f"   - {name}（{score if score is not None else '—'} 分）")
            long_description = html_to_text(str(criterion.get("long_description") or ""))
            if long_description:
                click.echo(f"     {long_description[:300]}")
        settings = detail.rubric_settings or {}
        if settings.get("points_possible") is not None:
            click.echo(f"   合计 {settings['points_possible']} 分")
    description = html_to_text(detail.description or "")
    if description:
        shown = description if full else description[:2000]
        click.secho("描述：", bold=True)
        click.echo(shown + ("…（加 --full 看全文）" if len(description) > len(shown) else ""))
    else:
        click.echo("描述：—")
    attachments = client.assignment_attachments(found_course.id, detail.id)
    if attachments:
        click.secho("描述内附件：", bold=True)
        for item in attachments:
            click.echo(
                f"   - {item['name']}（file_id={item['file_id']}，"
                f"{_human_size(item.get('size'))}）"
            )
    else:
        click.echo("描述内没有附件链接；题目文件也可能在课程文件区（canvas files）或模块里（canvas modules）。")
    if download_dir:
        if not attachments:
            click.echo("没有可下载的描述内附件。")
            return
        target_dir = Path(download_dir).expanduser()
        target_dir.mkdir(parents=True, exist_ok=True)
        for item in attachments:
            _download_one(client, item["file_id"], target_dir, item["name"])


def _print_submission(submission) -> None:
    """统一打印一条提交结果/状态。"""
    state = submission.workflow_state or "—"
    when = (
        submission.submitted_at.strftime("%Y-%m-%d %H:%M") if submission.submitted_at else "—"
    )
    late = "是" if submission.late else "否"
    click.echo(f"状态：{state}（迟交：{late}）")
    click.echo(f"提交时间：{when}")
    if submission.score is not None:
        click.echo(f"得分：{submission.score}")
    for item in submission.attachments:
        click.echo(f"附件：{item.display_name}（file_id={item.id}）")
    if submission.body:
        click.echo(f"文本：{submission.body[:120]}")
    if submission.url:
        click.echo(f"链接：{submission.url}")
    if submission.preview_url:
        click.echo(f"查看：{submission.preview_url}")


@canvas_cmd.command(name="submit")
@click.option("--course", required=True, help="课程 id 或名称关键词。")
@click.option("--assignment", required=True, help="作业 id 或名称关键词。")
@click.option(
    "--file",
    "files",
    multiple=True,
    type=click.Path(exists=True, dir_okay=False),
    help="要上传的文件路径，可重复给多个。",
)
@click.option("--text", default=None, help="文本提交（online_text_entry）内容。")
@click.option("--url", default=None, help="链接提交（online_url）地址。")
@click.option("--dry-run", "dry_run", is_flag=True, help="只预检并显示提交计划，不实际上传/提交。")
@click.option("--yes", "skip_confirm", is_flag=True, help="跳过交互确认直接提交。")
@_handle_canvas_errors
def canvas_submit(
    course: str,
    assignment: str,
    files: tuple[str, ...],
    text: str | None,
    url: str | None,
    dry_run: bool,
    skip_confirm: bool,
) -> None:
    """提交作业（写操作）：上传文件 / 提交文本 / 提交链接。"""
    from westlake_survival.canvas import canvas

    client = canvas()
    found_course = client.find_course(course)
    found_assignment = client.find_assignment(found_course.id, assignment)

    plan = client.submit_assignment(
        found_course.id,
        found_assignment.id,
        file_paths=files,
        text=text,
        url=url,
        dry_run=True,
    )
    click.echo(f"课程：{found_course.course_code or ''} {found_course.name}（id={found_course.id}）")
    click.echo(f"作业：{found_assignment.name}（id={found_assignment.id}）")
    if isinstance(plan, dict):
        click.echo(f"提交类型：{plan.get('submission_type')}")
        for name in plan.get("files", []):
            click.echo(f"文件：{name}")
        if plan.get("due_at"):
            click.echo(f"截止时间：{plan['due_at']}")
    if dry_run:
        click.secho("预检通过（dry-run，未提交）。", fg="yellow")
        return
    if not skip_confirm:
        click.confirm("确认提交以上内容？", abort=True)
    submission = client.submit_assignment(
        found_course.id,
        found_assignment.id,
        file_paths=files,
        text=text,
        url=url,
    )
    click.secho("已提交。", fg="green")
    _print_submission(submission)


@canvas_cmd.command(name="submission")
@click.option("--course", required=True, help="课程 id 或名称关键词。")
@click.option("--assignment", required=True, help="作业 id 或名称关键词。")
@_handle_canvas_errors
def canvas_submission(course: str, assignment: str) -> None:
    """查看本人在某作业上的当前提交状态。"""
    from westlake_survival.canvas import canvas

    client = canvas()
    found_course = client.find_course(course)
    found_assignment = client.find_assignment(found_course.id, assignment)
    submission = client.get_submission(found_course.id, found_assignment.id)
    click.echo(f"作业：{found_assignment.name}（id={found_assignment.id}）")
    _print_submission(submission)


# --------------------------------------------------------------------------- #
# sis —— 教务课表
# --------------------------------------------------------------------------- #
@click.group(name="sis", help="教务 SIS：课表与导出。")
def sis_cmd() -> None:
    """SIS（教务）命令。"""


@sis_cmd.command(name="schedule")
@_handle_errors
def sis_schedule() -> None:
    """打印本学期课表节次。"""
    from westlake_survival.sis import get_schedule

    sessions = get_schedule()
    if not sessions:
        click.echo("课表为空（可能尚未选课或未到教学周）。")
        return
    rows = []
    for s in sessions:
        weekday = _WEEKDAY_CN[s.weekday - 1] if 1 <= s.weekday <= 7 else str(s.weekday)
        time_slot = f"{s.start_time.strftime('%H:%M')}-{s.end_time.strftime('%H:%M')}"
        rows.append((s.title or "—", s.teacher or "—", weekday, time_slot, s.room or "—"))
    _print_table(rows, ("课程", "教师", "星期", "时间", "地点"))


@sis_cmd.command(name="grades")
@_handle_errors
def sis_grades() -> None:
    """打印全部学期成绩（按页面顺序，最近学期在前）。"""
    from westlake_survival.sis import grades as _grades

    items = _grades()
    if not items:
        click.echo("成绩为空（可能尚无成绩记录）。")
        return
    rows = [
        (
            g.term or "—",
            g.course_code or "—",
            g.course_title or "—",
            g.grade or "—",
            g.credits or "—",
        )
        for g in items
    ]
    _print_table(rows, ("学期", "课程代码", "课程名称", "等级", "学分"))


@sis_cmd.command(name="exams")
@_handle_errors
def sis_exams() -> None:
    """打印当前学期考试安排（页头学期由 SIS 决定）。"""
    from westlake_survival.sis import exam_schedule

    items = exam_schedule()
    if not items:
        click.echo("考试安排为空（可能尚未排期）。")
        return
    rows = [
        (
            e.course_code or "—",
            e.course_title or "—",
            e.date or "—",
            e.time or "—",
            e.exam_type or "—",
            e.method or "—",
            e.venue or "—",
            e.seat or "—",
        )
        for e in items
    ]
    _print_table(rows, ("课程代码", "课程名称", "日期", "时间", "类型", "方式", "考场", "座位"))


@sis_cmd.command(name="cart")
@_handle_errors
def sis_cart() -> None:
    """打印选课车内容（只读；不做任何 add/drop/swap 写操作）。"""
    from westlake_survival.sis import shopping_cart

    items = shopping_cart()
    if not items:
        click.echo("解析成功：购物车为空（没有暂存课程）。")
        return
    rows = []
    for c in items:
        extra = "；".join(f"{k}：{v}" for k, v in (c.extra or {}).items())
        rows.append(
            (
                c.course_code or "—",
                c.course_title or "—",
                c.units or "—",
                c.status or "—",
                extra or "—",
            )
        )
    _print_table(rows, ("课程代码", "课程名称", "学分", "状态", "其他"))


@sis_cmd.command(name="ical")
@click.option("--out", type=click.Path(dir_okay=False, path_type=Path), default="schedule.ics", show_default=True, help="写入 .ics 文件。")
@_handle_errors
def sis_ical(out: Path) -> None:
    """把课表导出为 .ics 日历文件。"""
    from westlake_survival.ical import save_ics
    from westlake_survival.sis import get_schedule

    sessions = get_schedule()
    if not sessions:
        click.secho("课表为空，未生成日历文件。", fg="red", err=True)
        raise SystemExit(1)
    target = save_ics(sessions, out)
    click.secho(f"已写入：{target}", fg="green")


# --------------------------------------------------------------------------- #
# ams —— 教学系统（西湖大学 AMS，IAM 统一认证）
# --------------------------------------------------------------------------- #
@click.group(name="ams", help="教学系统（AMS）：课表 / 学期周次 / 学籍与选课入口。")
def ams_cmd() -> None:
    """西湖大学教学系统（ams.westlake.edu.cn），全部只读。"""


def _echo_ams_schedule(rows: list[dict]) -> None:
    if not rows:
        click.echo("该区间没有课程安排。")
        return
    _print_table(
        [(r["date"], f"{r['start']}-{r['end']}", r["title"], r["address"]) for r in rows],
        ("日期", "时间", "课程", "地点"),
    )


@ams_cmd.command(name="status")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
@_handle_errors
def ams_status(as_json: bool) -> None:
    """学期 / 教学周次 + 今天的课。"""
    from westlake_survival import ams

    info = ams.overview()
    rows = ams.today()
    if as_json:
        click.echo(json.dumps({"overview": info, "today": rows}, ensure_ascii=False, indent=2))
        return
    click.echo(
        f"{info.get('semester') or '—'} 第 {info.get('week') or '—'} 周"
        f"（{'在教学周内' if info.get('in_semester') else '不在教学周'}）"
    )
    click.echo("今天：")
    _echo_ams_schedule(rows)


@ams_cmd.command(name="schedule")
@click.option("--start", default=None, help="起始日期 YYYY-MM-DD（默认本周一）。")
@click.option("--end", default=None, help="结束日期 YYYY-MM-DD（默认本周日）。")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
@_handle_errors
def ams_schedule(start: str | None, end: str | None, as_json: bool) -> None:
    """课程表（默认本周）。"""
    from datetime import date, timedelta

    from westlake_survival import ams

    if start or end:
        begin = date.fromisoformat(start) if start else date.fromisoformat(end)
        finish = date.fromisoformat(end) if end else begin
        rows = ams.schedule(begin, finish)
    else:
        now = date.today()
        monday = now - timedelta(days=now.weekday())
        rows = ams.schedule(monday, monday + timedelta(days=6))
    if as_json:
        click.echo(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    _echo_ams_schedule(rows)


@ams_cmd.command(name="today")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
@_handle_errors
def ams_today(as_json: bool) -> None:
    """今天的课。"""
    from westlake_survival import ams

    rows = ams.today()
    if as_json:
        click.echo(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    _echo_ams_schedule(rows)


@ams_cmd.command(name="menus")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
@_handle_errors
def ams_menus(as_json: bool) -> None:
    """服务入口（学籍 / 学术导师 / 选课 / 我的课表 …）。"""
    from westlake_survival import ams

    items = [m for m in ams.menus() if m["href"]]
    if as_json:
        click.echo(json.dumps(items, ensure_ascii=False, indent=2))
        return
    if not items:
        click.echo("没有可跳转的服务入口。")
        return
    _print_table([(m["code"], m["name"], m["href"]) for m in items], ("编号", "服务", "链接"))


@ams_cmd.command(name="notices")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
@_handle_errors
def ams_notices(as_json: bool) -> None:
    """教学系统通知。"""
    from westlake_survival import ams

    rows = ams.notices()
    if as_json:
        click.echo(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    if not rows:
        click.echo("暂无通知。")
        return
    _print_table([(r["date"], "未读" if r["unread"] else "", r["title"]) for r in rows],
                 ("时间", "状态", "标题"))


@ams_cmd.command(name="login")
@_handle_errors
def ams_login() -> None:
    """强制重新登录（缓存会话失效时用）。"""
    from westlake_survival import ams

    ams.login(force=True)
    click.secho("教学系统会话已建立（缓存 8 小时）。", fg="green")


# --------------------------------------------------------------------------- #
# lib —— 图书馆
# --------------------------------------------------------------------------- #
@click.group(name="lib", help="图书馆：书目检索与个人借阅。")
def lib_cmd() -> None:
    """图书馆命令。"""


def _lib_backend_guard() -> bool:
    """老 OPAC 下线时说明现状并返回 False。

    2026-10-28 实测：学校换成「阿法迪云 eLibrary」新平台，老 ``/opac/*`` 连根都
    404。此时**不要**再走 CAS 登录——那条回调已失效，反复失败有锁号风险。
    """
    try:
        from westlake_survival.lib.opac import detect_backend

        backend = detect_backend()
    except Exception:
        return True
    if backend.get("opac_alive"):
        return True
    click.secho(
        "图书馆系统已迁移：老 OPAC 的检索 / 新书 / CAS 借阅接口整体下线"
        f"（{backend.get('detail', '')}）。新平台是「阿法迪云 eLibrary」，"
        "登录改成平台自有账号，本工具还没接新接口；请直接访问图书馆网站。",
        fg="yellow",
        err=True,
    )
    return False


@lib_cmd.command(name="search")
@click.argument("keyword")
@click.option("--page", type=int, default=1, show_default=True, help="页码。")
@_handle_errors
def lib_search(keyword: str, page: int) -> None:
    """检索图书馆书目（按题名）。"""
    from westlake_survival.lib import search

    if not _lib_backend_guard():
        raise SystemExit(1)
    books = search(keyword, page=page)
    if not books:
        click.echo("未找到匹配的书目。")
        return
    rows = [(b.title or "—", b.author or "—", b.call_no or "—", b.location or "—") for b in books]
    _print_table(rows, ("题名", "作者", "索书号", "馆藏地"))


@lib_cmd.command(name="loans")
@_handle_errors
def lib_loans() -> None:
    """列出个人当前借阅记录（需登录）。"""
    from westlake_survival.lib import my_loans

    if not _lib_backend_guard():
        raise SystemExit(1)
    loans = my_loans()
    if not loans:
        click.echo("当前无借阅记录。")
        return
    rows = [
        (
            loan.title or "—",
            loan.due_date or "—",
            "—" if loan.renewable is None else ("可续借" if loan.renewable else "不可续借"),
            loan.location or "—",
        )
        for loan in loans
    ]
    _print_table(rows, ("题名", "应还日期", "续借", "馆藏地"))


# --------------------------------------------------------------------------- #
# pms —— 自助文印
# --------------------------------------------------------------------------- #
@click.group(name="pms", help="自助文印：打印网点与任务。")
def pms_cmd() -> None:
    """自助文印（联创云打印）命令。"""


@pms_cmd.command(name="stations")
@_handle_errors
def pms_stations() -> None:
    """列出全部打印网点（无需登录）。"""
    from westlake_survival.pms import pms

    stations = pms().list_stations()
    if not stations:
        click.echo("未获取到打印网点。")
        return
    rows = [
        (
            s.name or "—",
            s.campus_display or "—",
            s.position_display or "—",
            s.status_text or ("空闲" if s.is_idle else "—"),
            "、".join(s.papers) or "—",
        )
        for s in stations
    ]
    _print_table(rows, ("网点", "校区", "位置", "状态", "纸型"))


@pms_cmd.command(name="jobs")
@_handle_errors
def pms_jobs() -> None:
    """列出个人打印任务（需登录）。"""
    from westlake_survival.pms import pms

    jobs = pms().list_print_jobs()
    if not jobs:
        click.echo("当前无打印任务。")
        return
    rows = [
        (
            job.name or "—",
            str(job.copies) if job.copies is not None else "—",
            str(job.pages) if job.pages is not None else "—",
            job.status_text or "—",
        )
        for job in jobs
    ]
    _print_table(rows, ("文件", "份数", "页数", "状态"))


# --------------------------------------------------------------------------- #
# context —— 此刻西湖
# --------------------------------------------------------------------------- #
@click.command(name="context")
@click.option(
    "--level",
    type=click.Choice(["terse", "normal", "verbose"]),
    default="normal",
    show_default=True,
    help="信息量档位。",
)
@_handle_errors
def context_cmd(level: str) -> None:
    """打印"此刻西湖"中文快照（日期 / 周次 / 事件 / 班车 / 天气）。"""
    from westlake_survival.context import Level, snapshot

    click.echo(snapshot(Level(level)).to_str())


# --------------------------------------------------------------------------- #
# digest —— 晨报一条龙
# --------------------------------------------------------------------------- #
def _digest_source(lines: list[str], title: str, factory, *, placeholder: str = "（暂不可用）") -> None:
    """把某个数据源渲染成 digest 的一节；失败时降级为占位行、绝不中断。"""
    lines.append(f"## {title}")
    try:
        content = factory()
    except Exception as exc:  # noqa: BLE001 - 各源独立降级，绝不炸整份晨报
        content = [f"{placeholder}（{exc.__class__.__name__}）"]
    lines.extend(content or ["（暂无）"])
    lines.append("")


def _digest_overview() -> list[str]:
    """概览节：复用 context 快照（TERSE 档，纯本地）渲染一行紧凑摘要。

    只取快照的日期 / 星期 / 学期 / 周次字段，避免把 ``to_str()`` 里的事件 /
    班车小节与下方各节重复。
    """
    from westlake_survival.context import Level, snapshot

    ctx = snapshot(Level.TERSE)
    parts = [ctx.date.isoformat(), ctx.weekday_cn]
    if ctx.semester_name:
        parts.append(ctx.semester_name)
        if ctx.week_number is not None:
            parts.append(f"第{ctx.week_number}周")
    return ["- " + " · ".join(parts)]


def _digest_events() -> list[str]:
    """今日 / 明日活动节（``events.upcoming(2)``）。"""
    from westlake_survival.events import upcoming

    items = upcoming(2)
    if not items:
        return ["今日 / 明日暂无活动预告。"]
    return [
        f"- {item.date.strftime('%m-%d %H:%M')} {item.title}"
        + (f"（{item.venue}）" if item.venue else "")
        for item in items[:5]
    ]


def _digest_shuttle() -> list[str]:
    """下一班校车节（transit 有内置兜底，基本总可用）。"""
    from westlake_survival.transit import transit

    departures = transit().next_departures(limit=3)
    if not departures:
        return ["暂无后续班车信息。"]
    return [f"- {ts} 从 {table.campus.value} 开出" for table, ts in departures]


def _digest_week() -> list[str]:
    """本周次节（校历）。"""
    from westlake_survival.calendar import AcademicCalendar

    today = date.today()
    calendar = AcademicCalendar.load()
    result = calendar.week_of(today)
    if result is None:
        return ["当前不在任何学期的教学周内。"]
    semester, week = result
    lines = [f"- 学期：{semester.name}", f"- 本周：第 {week} 周（共 {semester.teaching_weeks()} 周）"]
    events = [e for e in semester.events if e.covers(today)]
    if events:
        lines.append("- 今日校历：" + "、".join(e.title for e in events))
    return lines


def _digest_canvas() -> list[str]:
    """Canvas 截止节：仅在配置了 WESTLAKE_CANVAS_TOKEN 时并入。"""
    token_env = "WESTLAKE_CANVAS_TOKEN"
    try:
        from westlake_survival.canvas import TOKEN_ENV_VAR as token_env  # type: ignore[assignment]
    except Exception:  # noqa: BLE001 - 模块形状异常时用默认变量名
        pass
    if not (os.environ.get(token_env) or "").strip():
        return [f"（未配置 {token_env}，跳过 Canvas 截止）"]
    from westlake_survival.canvas import canvas

    items = canvas().upcoming_deadlines(limit=5)
    if not items:
        return ["暂无即将到期的 Canvas 作业。"]
    return [
        f"- {a.due_at.strftime('%m-%d %H:%M') if a.due_at else '—'} {a.name or '（未命名作业）'}"
        for a in items
    ]


@click.command(name="digest")
@click.option(
    "--level",
    type=click.Choice(["terse", "normal"]),
    default="normal",
    show_default=True,
    help="信息量档位：normal 含活动/班车/周次/Canvas 截止，terse 只保留本地快算与周次。",
)
def digest_cmd(level: str) -> None:
    """晨报一条龙：快照 + 活动 + 班车 + 周次（可选 Canvas 截止）合成一段可推送中文文本。"""
    terse = level == "terse"
    header = f"# 西湖大学晨报 · {date.today().isoformat()} {_WEEKDAY_CN[date.today().weekday()]}"
    lines: list[str] = [header, ""]
    _digest_source(lines, "概览", _digest_overview)
    if not terse:
        _digest_source(lines, "今日 / 明日活动", _digest_events)
        _digest_source(lines, "下一班校车", _digest_shuttle)
    _digest_source(lines, "本周次", _digest_week)
    if not terse:
        _digest_source(lines, "Canvas 截止", _digest_canvas)
    click.echo("\n".join(lines).rstrip())


# --------------------------------------------------------------------------- #
# probe —— 堵点状态探测
# --------------------------------------------------------------------------- #
#: probe 每项请求的超时（秒）。
PROBE_TIMEOUT = 8.0

#: probe 里 SIS 选课组件路径（Study Shopping Cart）。
SIS_SHOP_CART_COMPONENT = "SSR_STUDENT_FL.SSR_SHOP_CART_FL.GBL"

#: OPAC 应用基址（实测 404 的内部端点）。
OPAC_PROBE_URL = "http://172.16.10.223:8180/opac/"


def _probe_sis_cart() -> tuple[str, str]:
    """探测 SIS 选课组件授权状态（登录态 GET）。

    PeopleSoft 对未开放选课的角色返回「not authorized」正文（中文界面是
    「您无权访问该页面」），``fetch_page`` 会把它翻成 :class:`ActionError`；
    此处把该情形判为「选课窗口未开」，其余异常（校外 / 未登录等）交由外层
    收敛为「失败」。两种语言都要认——只认英文会把中文拒绝页判成「已授权」。
    """
    from westlake_survival.exceptions import ActionError
    from westlake_survival.sis.cart import _UNAUTHORIZED_MARKERS
    from westlake_survival.sis.pages import fetch_page

    def unauthorized(text: str) -> bool:
        lowered = text.lower()
        return any(marker.lower() in lowered for marker in _UNAUTHORIZED_MARKERS)

    try:
        body = fetch_page(SIS_SHOP_CART_COMPONENT)
    except ActionError as exc:
        if unauthorized(str(exc)):
            return "选课窗口未开", "组件未授权（正文含无权访问/not authorized）"
        raise
    if unauthorized(body):
        return "选课窗口未开", "组件正文含无权访问/not authorized"
    return "已授权（可开发选课功能！）", "组件页可正常访问"


def _probe_opac() -> tuple[str, str]:
    """探测 OPAC 端点状态码（404 = 仍未恢复）。"""
    from westlake_survival._net import http_session

    response = http_session().get(OPAC_PROBE_URL, timeout=PROBE_TIMEOUT, allow_redirects=False)
    status = response.status_code
    if status == 404:
        return f"HTTP {status}", "仍未恢复（服务端 404）"
    if status < 400:
        return f"HTTP {status}", "已恢复"
    return f"HTTP {status}", "异常状态码"


def _probe_pms() -> tuple[str, str]:
    """探测打印系统匿名接口（Station/GetList）可达性。"""
    from westlake_survival._net import http_session

    base = None
    try:
        from westlake_survival import pms as pms_pkg

        resolver = getattr(pms_pkg, "resolve_base_url", None)
        if callable(resolver):
            base = resolver()
        else:
            base = getattr(pms_pkg, "PMS_BASE", None)
    except Exception:  # noqa: BLE001 - pms 模块形状变化时退回默认基址
        base = None
    base = (base or "http://print.lib.westlake.edu.cn:9130").rstrip("/")
    url = f"{base}/api/client/Station/GetList"
    response = http_session().get(url, timeout=PROBE_TIMEOUT)
    status = response.status_code
    if status >= 400:
        return f"HTTP {status}", "接口不可达"
    try:
        payload = response.json()
    except ValueError:
        return f"HTTP {status}", "响应非 JSON"
    code = payload.get("code") if isinstance(payload, dict) else None
    if code == 0:
        count = len(payload.get("result") or []) if isinstance(payload, dict) else 0
        return "可达", f"匿名可读，{count} 个网点"
    return f"HTTP {status}", f"信封 code={code}"


def _probe_canvas_token() -> tuple[str, str]:
    """探测 Canvas token 是否配置。"""
    token_env = "WESTLAKE_CANVAS_TOKEN"
    try:
        from westlake_survival.canvas import TOKEN_ENV_VAR as token_env  # type: ignore[assignment]
    except Exception:  # noqa: BLE001 - 模块形状异常时用默认变量名
        pass
    if (os.environ.get(token_env) or "").strip():
        return "已配置", f"环境变量 {token_env} 非空"
    try:
        from westlake_survival.canvas import resolve_token

        resolved = resolve_token()
    except Exception:  # noqa: BLE001 - 解析失败按未配置处理
        resolved = None
    if resolved:
        return "已配置", "来自 token 文件"
    return "未配置", f"设置环境变量 {token_env} 或写入 canvas_token.txt"


#: 场馆与座位两类「约不了」系统的入口（各自独立，不在预约中心）。
VENUE_ENTRIES = (
    ("sportvenue", "场馆系统 sportvenue（游泳/球场）"),
    ("seats.library", "图书馆座位 seats.library（企业微信）"),
)


def _probe_venue_entries() -> tuple[str, str]:
    """探测场馆/座位系统入口是否在线（只 GET 首页，不登录）。"""
    from westlake_survival.discovery import direct_session

    session = direct_session()
    session.headers["User-Agent"] = "Mozilla/5.0 (westlake-survival probe)"
    alive: list[str] = []
    dead: list[str] = []
    for host, _label in VENUE_ENTRIES:
        try:
            response = session.get(
                f"https://{host}.westlake.edu.cn/", timeout=PROBE_TIMEOUT, verify=False
            )
        except Exception:  # noqa: BLE001 - 探测失败即视为不可达
            dead.append(host)
            continue
        (alive if response.status_code < 500 else dead).append(host)
    if dead and not alive:
        return "全部不可达", "、".join(dead) + "（需校园网/VPN）"
    note = "在线：" + "、".join(alive)
    if dead:
        note += "；不可达：" + "、".join(dead)
    return "在线（独立系统，需登录）", note + "；游泳卡点见 docs/sportvenue_notes.md"


#: probe 各项：(中文名, 探测函数)。探测函数返回 ``(状态, 说明)``。
PROBE_ITEMS = (
    ("SIS 选课组件授权", _probe_sis_cart),
    ("OPAC 端点", _probe_opac),
    ("打印系统匿名接口", _probe_pms),
    ("Canvas token", _probe_canvas_token),
    ("场馆/座位入口", _probe_venue_entries),
)


def _run_probe_item(func) -> tuple[str, str]:
    """跑一项探测；任何异常都收敛为「失败」状态，绝不炸整表。"""
    try:
        return func()
    except Exception as exc:  # noqa: BLE001 - 每项失败不影响其余项
        message = str(exc).strip() or exc.__class__.__name__
        return "失败", message.replace("\n", " ")


@click.group(name="probe", invoke_without_command=True)
@click.pass_context
def probe_cmd(ctx: click.Context) -> None:
    """堵点与服务发现：不带参数跑四项常规探测；scan 做子域普查。"""
    if ctx.invoked_subcommand is not None:
        return
    rows = []
    for name, func in PROBE_ITEMS:
        status, detail = _run_probe_item(func)
        rows.append((name, status, detail))
    _print_table(rows, ("探测项", "状态", "说明"))


@probe_cmd.command(name="scan")
@click.option("--full", is_flag=True, help="扫全量候选（默认精选 36 个）。")
@click.option("--hosts", default=None, help="只扫这些主机（逗号分隔，调试/测试用）。")
@click.option("--timeout", type=float, default=6.0, show_default=True, help="单主机超时秒数。")
@_handle_errors
def probe_scan(full: bool, hosts: str | None, timeout: float) -> None:
    """子域直连普查 + 办事大厅目录（绕系统代理；通配 502 不算活）。"""
    from westlake_survival import discovery

    if hosts:
        host_list = [h.strip() for h in hosts.split(",") if h.strip()]
    else:
        host_list = None if full else discovery.CENSUS_HOSTS
    results = discovery.subdomain_census(host_list, timeout=timeout)
    alive = [r for r in results if r.alive]
    click.echo(f"子域普查：{len(alive)} 活 / {len(results)} 探测（直连、绕系统代理）")
    for r in sorted(alive, key=lambda x: x.host):
        click.echo(f"  {r.status:<4} {r.host + '.westlake.edu.cn':.<34} {r.title[:28]}")
    try:
        apps = discovery.app_directory()
        click.echo("")
        click.echo(f"办事大厅目录：{len(apps)} 个流程应用（免登录接口）")
    except Exception as exc:
        click.echo("")
        click.echo(f"办事大厅目录：获取失败（{exc}）")


# --------------------------------------------------------------------------- #
# cache —— 本地缓存管理
# --------------------------------------------------------------------------- #
@click.group(name="cache", help="本地缓存管理（清除校历 / 班车 / 活动等 ETag 缓存）。")
def cache_cmd() -> None:
    """缓存管理命令。"""


@cache_cmd.command(name="clear")
@click.option(
    "--module",
    "module",
    default=None,
    help="只清某模块的缓存（前缀匹配，如 events / transit / calendar）；缺省清空全部。",
)
@_handle_errors
def cache_clear(module: str | None) -> None:
    """清除本地缓存文件，返回清除数量。"""
    from westlake_survival import _cache

    removed = _cache.clear(module)
    if module:
        click.secho(f"已清除 {removed} 个缓存文件（模块：{module}）。", fg="green")
    else:
        click.secho(f"已清除 {removed} 个缓存文件（全部）。", fg="green")


# --------------------------------------------------------------------------- #
# webui —— 本地 Web 界面
# --------------------------------------------------------------------------- #
@click.group(name="webui", help="本地 Web 界面（Flask，基础依赖随包安装）。")
def webui_cmd() -> None:
    """本地 Web 界面命令。"""


@webui_cmd.command(name="serve")
@click.option("--host", default="127.0.0.1", show_default=True, help="绑定地址。")
@click.option("--port", type=int, default=2018, show_default=True, help="端口。")
def webui_serve(host: str, port: int) -> None:
    """启动本地 Web 界面（默认 http://127.0.0.1:2018/）。"""
    try:
        from westlake_survival.webui import run
    except ImportError as exc:  # Flask 已是基础依赖，缺它说明装的是旧包或 --no-deps
        click.secho(
            "错误：缺少 Web 界面依赖（Flask）。从 2026.10.28 起它随基础依赖一起装，"
            "缺了通常是旧包或用了 --no-deps。修复（任选一条）：\n"
            "  pip install -e .          # 在仓库目录重装\n"
            "  pip install flask         # 只补这一个依赖",
            fg="red",
            err=True,
        )
        raise SystemExit(1) from exc
    try:
        run(host=host, port=port)
    except WestlakeError as exc:
        _print_error(exc)
        raise SystemExit(1) from exc


def _webui_entry_url(port: int) -> str:
    """启动落地页：没配过账号直接进「设置」，配过就进仪表盘。"""
    suffix = "" if _first_run_configured() else "setup"
    return f"http://127.0.0.1:{port}/{suffix}"


def _webui_probe_url(port: int) -> str:
    """就绪/存活探测用的轻量地址。

    不用落地页 ``/``：仪表盘要现拉各服务数据（本机实测冷启动 18 秒），拿它当
    探针会让「等服务就绪再开浏览器」白等十几秒。``/setup`` 是纯模板渲染（3ms）。
    """
    return f"http://127.0.0.1:{port}/setup"


def _webui_already_running(port: int) -> bool:
    """本机同一端口上是否已经有这个网页在跑（按页面里的品牌串认人）。"""
    import urllib.request

    try:
        with urllib.request.urlopen(_webui_probe_url(port), timeout=2) as resp:
            body = resp.read(8192).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001 - 连不上就是没在跑
        return False
    return "西湖生存手册" in body


@click.command(name="go", help="一步启动：起 WebUI 并自动打开浏览器（用户入口）。")
@click.option("--port", default=2018, show_default=True, help="本地端口。")
@click.option("--no-browser", is_flag=True, help="只启动服务，不打开浏览器（Agent/无桌面环境用）。")
def go_cmd(port: int, no_browser: bool) -> None:
    """``westlake go``：启动 WebUI 并自动打开浏览器。

    浏览器落地页就是用户该去的地方：首次启动（本机还没有账号）直达「设置」
    页填一次学号密码，之后每次直达仪表盘。终端侧的 ``westlake setup`` 留给 Agent。

    端口上已经有同一个网页在跑时（重复双击启动脚本的常见情形）不再起第二个
    服务，直接把浏览器指过去——否则第二个进程绑不上端口，浏览器只会开到死页。
    """
    import threading
    import webbrowser

    url = _webui_entry_url(port)
    if _webui_already_running(port):
        click.echo(f"西湖生存手册 · 已在运行：{url}")
        if not no_browser:
            click.echo("浏览器将打开这个地址；服务由已运行的实例提供。")
            webbrowser.open(url)
        return
    if not no_browser:
        # 服务就绪后再开浏览器：最多等 15 秒，避免直接命中连接失败页。
        probe = _webui_probe_url(port)

        def _open_when_ready() -> None:
            import time

            deadline = time.time() + 15
            while time.time() < deadline:
                try:
                    import urllib.request

                    with urllib.request.urlopen(probe, timeout=1):
                        pass
                    break
                except Exception:
                    time.sleep(0.4)
            webbrowser.open(url)

        threading.Thread(target=_open_when_ready, daemon=True).start()
    click.echo(f"西湖生存手册 · Web 界面：{url}")
    if url.endswith("/setup"):
        click.echo("首次启动：请在打开的页面里填一次学号与统一身份认证密码。")
    if not no_browser:
        click.echo("浏览器将自动打开；若没有弹出，手动访问上面的地址。")
    click.echo("Ctrl+C 停止。")
    # webui_serve 是 click 命令对象；直接调它的回调，避免再走一次 CLI 解析。
    webui_serve.callback("127.0.0.1", port)


# --------------------------------------------------------------------------- #
# doctor —— 环境自检（Agent 拿到 skill 的第一步）
# --------------------------------------------------------------------------- #
@click.command(name="doctor", help="环境自检：解释器/依赖/凭据/网络，缺什么给修复命令。")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON（给 Agent / 脚本）。")
@click.option("--offline", is_flag=True, help="跳过联网探测。")
def doctor_cmd(as_json: bool, offline: bool) -> None:
    """全绿就干活；有 ✘ 就照「修复」列抄，不用读 README 猜。"""
    from westlake_survival import doctor

    checks = doctor.run_checks(network=not offline)
    if as_json:
        click.echo(json.dumps(doctor.as_dict(checks), ensure_ascii=False, indent=2))
    else:
        marks = {"ok": "✔", "warn": "!", "missing": "✘"}
        click.echo("环境自检（westlake doctor）")
        for item in checks:
            click.echo(f"  {marks.get(item.status, '?')} {item.name}：{item.detail}")
            if item.fix:
                click.echo(f"      修复：{item.fix}")
        missing = [item for item in checks if item.status == "missing"]
        click.echo("")
        if missing:
            click.echo(f"结论：{len(missing)} 项缺失，按上面的「修复」逐条执行后重跑本命令。")
        else:
            click.echo("结论：环境可用。需要账号的功能，去网页「设置」页填一次即可。")
    raise SystemExit(1 if doctor.has_missing(checks) else 0)


# --------------------------------------------------------------------------- #
# 运行时自发现：westlake find <需求关键词>
# --------------------------------------------------------------------------- #
@click.command(name="find", help="按需求找能力：搜 CLI / MCP / 网页 / 学术库 / 服务注册表。")
@click.argument("query", required=False)
def find_cmd(query: str | None) -> None:
    """``westlake find 作业`` —— Agent 不确定某需求归哪条命令时的路由入口。"""
    from westlake_survival.capabilities import find_capabilities

    result = find_capabilities(query or "")
    if not query:
        click.echo(result["hint"])
        click.echo("例：westlake find 作业 / 论文 / 班车 / 待办 / 预约 / 打印 / 成绩")
        return
    q = query.strip()
    total = 0

    def _label(name: str) -> str:
        return name.split(":", 1)[1] if ":" in name else name

    def _echo_group(title: str, rows: list[dict], render) -> None:
        nonlocal total
        if not rows:
            return
        click.secho(f"{title}（{len(rows)}）", fg="cyan")
        for row in rows[:12]:
            render(row)
        total += len(rows)
        if len(rows) > 12:
            click.echo(f"  …其余 {len(rows) - 12} 条")

    _echo_group("CLI 命令", result["cli"], lambda r: click.echo(
        f"  {_label(r['name'])}"
        f"{' → ' + '、'.join(c['name'] for c in r.get('matched_commands', [])[:4]) if r.get('matched_commands') else ''}"
        f"  — {r['summary'][:52]}"
        + ("（需凭据）" if r.get("needs_auth") else "")))
    _echo_group("MCP 工具", result["mcp"], lambda r: click.echo(
        f"  {_label(r['name'])}  — {r['summary'][:56]}"))
    _echo_group("网页", result["web"], lambda r: click.echo(
        f"  {_label(r['name'])}  — {r['summary'][:56]}"))
    _echo_group("学术数据库", result["databases"], lambda r: click.echo(
        f"  [{r['access']}] {r['name']}  {r['url']}"))
    _echo_group("服务站点", result["services"], lambda r: click.echo(
        f"  {r['host']}  {r['name']}（{r['mode']}）"))
    if total == 0:
        click.echo(f"没有命中「{q}」。试试更短的关键词，或 westlake --help 看全部命令组。")
    else:
        if len(result.get("matched_terms", [])) > 1:
            click.echo(f"匹配词：{' / '.join(result['matched_terms'][:6])}")
        click.echo(f"共 {total} 条命中。详情：westlake <组> --help 或网页 /capabilities。")


# --------------------------------------------------------------------------- #
# 顶层 group
# --------------------------------------------------------------------------- #
@click.group(
    name="westlake",
    help="西湖大学生存手册命令行。使用 `westlake <子命令> --help` 查看详情。",
    invoke_without_command=True,
)
@click.version_option(__version__, "-V", "--version", prog_name="westlake")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """westlake_survival 统一命令行入口。

    不带子命令时**直接起 WebUI 并打开浏览器**：本机还没配过账号就落在「设置」
    页，让用户在那里填一次学号密码；配过就落在仪表盘。脚本或自动化要帮助信息，
    用 ``westlake --help``；要跳过启动，设 ``WESTLAKE_NO_WEBUI=1``。
    """
    if ctx.invoked_subcommand is not None:
        return
    if os.environ.get("WESTLAKE_NO_WEBUI"):
        click.echo(ctx.get_help())
        return
    go_cmd.callback(2018, False)


def _first_run_configured() -> bool:
    """是否已有教务凭据（只看来源有无，不读密码）。"""
    try:
        from westlake_survival.sso import read_credentials

        read_credentials()
    except Exception:
        return False
    return True


for _group in (
    go_cmd,
    doctor_cmd,
    ams_cmd,
    find_cmd,
    setup_cmd,
    sso_cmd,
    calendar_cmd,
    transit_cmd,
    canvas_cmd,
    sis_cmd,
    evals_cmd,
    profile_cmd,
    records_cmd,
    aid_cmd,
    lib_cmd,
    pms_cmd,
    booking_cmd,
    sport_cmd,
    share_cmd,
    search_cmd,
    news_cmd,
    program_cmd,
    research_cmd,
    events_cmd,
    careers_cmd,
    faculty_cmd,
    campus_cmd,
    map_cmd,
    contact_cmd,
    affairs_cmd,
    hosts_cmd,
    hpc_cmd,
    finance_cmd,
    mirrors_cmd,
    institute_cmd,
    schools_cmd,
    sites_cmd,
    wiki_cmd,
    vpn_cmd,
    todo_cmd,
    portal_cmd,
    scholar_cmd,
    careersite_cmd,
    context_cmd,
    digest_cmd,
    probe_cmd,
    cache_cmd,
    webui_cmd,
):
    cli.add_command(_group)
del _group


__all__ = ["cli"]
