"""写操作安全层——对标 sustech_survival 的 consequence.py（2026-10-29 完全对标裁定）。

每个会改变真实学生状态的操作携带结构化描述符（改什么 / 风险 / 严重度 /
可逆性）；CLI 统一确认门：非 ``--dry-run`` 且未 ``--yes`` 时打印描述符并以
退出码 1 结束。刻意**不做交互式 y/n 提示**：Agent 管道 stdin 下
``click.confirm`` / ``input`` 会挂死或被吞（2026-10-28 实测），非交互门对
人和 Agent 都更可预期——人加 ``--yes``，Agent 凭用户当轮指令传 ``--yes``。

写操作全集与 SKILL.md / AGENTS.md 的「写操作仅五条」一一对应：
``canvas.submit`` / ``canvas.reply`` / ``canvas.send`` /
``booking.book`` / ``booking.cancel``。新增写操作必须先在此登记描述符，
``require_confirmation`` 对未登记的名字直接抛 ``KeyError``（防清单漂移）。
"""
from __future__ import annotations

import click
from dataclasses import dataclass
from enum import Enum


class Severity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class Consequence:
    """一个写操作的结构化风险描述。"""

    name: str
    what_changes: str
    risk: str
    severity: Severity = Severity.MEDIUM
    irreversible: bool = False

    def describe(self) -> str:
        tail = "，不可逆" if self.irreversible else ""
        return "\n".join(
            [
                f"操作：{self.name}",
                f"改变：{self.what_changes}",
                f"风险：{self.risk}",
                f"严重度：{self.severity.value}{tail}",
            ]
        )


CONSEQUENCES: dict[str, Consequence] = {
    "canvas.submit": Consequence(
        "canvas.submit",
        "把指定文件/文本/链接作为作业提交到 Canvas 课程",
        "提交后课程侧与教师可见；误交需重复提交覆盖或联系教师重置",
        Severity.MEDIUM,
    ),
    "canvas.reply": Consequence(
        "canvas.reply",
        "在课程讨论主题下发布一条回帖",
        "内容对全班可见，发布后通常不可编辑或删除",
        Severity.MEDIUM,
    ),
    "canvas.send": Consequence(
        "canvas.send",
        "在 Canvas 收件箱会话里发送一条私信",
        "发送后无法撤回，收件人立即可见",
        Severity.MEDIUM,
    ),
    "booking.book": Consequence(
        "booking.book",
        "在预约中心创建一段场地预约",
        "占用他人可用的名额；预约不赴会占用公共资源",
        Severity.MEDIUM,
    ),
    "booking.cancel": Consequence(
        "booking.cancel",
        "取消一段已有的场地预约",
        "释放名额；原时段需重新预约才能恢复",
        Severity.LOW,
    ),
}


class ConfirmationRequired(Exception):
    """写操作未获确认：携带 :class:`Consequence`，CLI 层打印并退出 1。"""

    def __init__(self, consequence: Consequence):
        self.consequence = consequence
        super().__init__(consequence.name)


def consequence_by_name(name: str) -> Consequence:
    try:
        return CONSEQUENCES[name]
    except KeyError:
        raise KeyError(
            f"未登记的写操作 {name!r}：新增写操作必须先在 consequence.py 登记描述符"
        ) from None


def require_confirmation(
    name: str, *, confirmed: bool = False, dry_run: bool = False
) -> Consequence:
    """写操作确认门。

    ``dry_run=True`` 直接放行（调用方只做预检不改状态）；``confirmed``
    未置位时抛 :class:`ConfirmationRequired`。库层调用者可自行捕获并
    向使用者展示 ``consequence`` 后再决定。
    """
    consequence = consequence_by_name(name)
    if dry_run or confirmed:
        return consequence
    raise ConfirmationRequired(consequence)


def gate_cli(name: str, *, confirmed: bool, dry_run: bool = False) -> Consequence:
    """CLI 侧统一门：未确认时打印描述符并以退出码 1 结束（不挂交互提示）。"""
    try:
        return require_confirmation(name, confirmed=confirmed, dry_run=dry_run)
    except ConfirmationRequired as exc:
        click.secho("[写操作未确认] 需要 --yes 才会执行", fg="yellow")
        click.echo(exc.consequence.describe())
        if name in ("canvas.submit", "booking.book"):
            click.echo("先看计划不执行：加 --dry-run。")
        raise SystemExit(1)
