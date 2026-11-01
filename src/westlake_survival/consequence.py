"""写操作安全层——对标 sustech_survival 的 consequence.py 并升级「事务预览卡片（Action Card）」。

每个改变真实学生状态的操作携带结构化描述符（改什么 / 风险 / 严重度 / 可逆性）。
升级支持 Action Card 机制：
1. ``--dry-run`` 模式输出清晰的事务预览卡片，包含作用对象、参数指纹与一次性 Ticket 凭据；
2. 非 ``--dry-run`` 且未 ``--yes`` 时，若无有效 ``--ticket`` 则打印 Action Card 凭证拦截退出（退出码 1）；
3. 提供有效 ``--ticket <ticket>`` 或 ``--yes`` 直接放行并防重放销毁凭证，实现免拼长参数的流畅闭环；
4. 保持非交互性，刻意不做交互式 y/n 提示（防 Agent stdin 挂死）。

写操作登记表包含：
- ``canvas.submit``: 提交 Canvas 作业
- ``canvas.reply``: 发布讨论回帖
- ``canvas.send``: 发送私信
- ``booking.book``: 创建场地预约
- ``booking.cancel``: 取消场地预约
- ``canvas.star``: 收藏/星标 Canvas 课程（置顶仪表盘）
- ``canvas.unstar``: 取消收藏/星标 Canvas 课程
- ``lib.renew``: 图书馆在借图书在线续借
- ``timeline.memo``: 本地个人日程生活备忘写入/完成/删除
- ``pms.print``: 联创自助文印文件上传与建任务
- ``pms.cancel``: 联创自助文印待打印作业取消与删除
- ``canvas.upload``: 上传文件至 Canvas 个人文件云盘
- ``canvas.dismiss_todo``: 忽略/归档 Canvas 个人待办事项
- ``calendar.export``: 导出融合时空行动流/日历到本地 .ics 文件
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import click

from westlake_survival._cache import config_root


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
    "canvas.star": Consequence(
        "canvas.star",
        "将指定 Canvas 课程加入个人收藏列表（置顶于课程面板）",
        "改变个人视图展示，可随时取消收藏",
        Severity.LOW,
        irreversible=False,
    ),
    "canvas.unstar": Consequence(
        "canvas.unstar",
        "将指定 Canvas 课程移出个人收藏列表",
        "课程转入全部课程列表，不影响选课与作业提交",
        Severity.LOW,
        irreversible=False,
    ),
    "lib.renew": Consequence(
        "lib.renew",
        "在阿法迪云图书馆平台为在借图书办理在线续借",
        "延长该书借阅归还截止日期（每本书通常限续借 1 次）",
        Severity.LOW,
        irreversible=False,
    ),
    "timeline.memo": Consequence(
        "timeline.memo",
        "在本地日程行动流中新增、完成或删除个人备忘与待办标记",
        "写入本地日常行动流数据，支持删除或标记完成",
        Severity.LOW,
        irreversible=False,
    ),
    "pms.print": Consequence(
        "pms.print",
        "将本地文件上传到联创自助文印云队列并创建待打印作业",
        "文件进入学校打印服务器队列（保留一定时长），在终端网点刷卡取件时才发生扣费结算",
        Severity.LOW,
        irreversible=False,
    ),
    "pms.cancel": Consequence(
        "pms.cancel",
        "从联创自助文印云队列中取消并删除指定未打印作业",
        "该打印作业将被移除，如需打印需重新上传文件",
        Severity.LOW,
        irreversible=True,
    ),
    "canvas.upload": Consequence(
        "canvas.upload",
        "将本地文件上传到 Canvas 个人云盘/文件存储区",
        "占用个人 Canvas 存储配额，上传后可在 Canvas 文件管理中删除",
        Severity.LOW,
        irreversible=False,
    ),
    "canvas.dismiss_todo": Consequence(
        "canvas.dismiss_todo",
        "忽略/归档一条 Canvas 个人待办事项",
        "该事项将从个人待办列表中移除，课程作业/考试本身的截止时间不受影响",
        Severity.LOW,
        irreversible=False,
    ),
    "calendar.export": Consequence(
        "calendar.export",
        "将融合多源（课表、DDL、预约）日程导出并写入本地 .ics 日历文件",
        "将覆盖目标文件路径（若已存在），支持直接导入 Apple Calendar / Outlook / 手机日历",
        Severity.LOW,
        irreversible=False,
    ),
}


@dataclass
class ActionCard:
    """一个具体写操作调用的结构化事务凭证卡片。"""

    action_id: str
    name: str
    title: str
    target: str
    payload: dict[str, Any]
    risk: str
    severity: Severity
    irreversible: bool
    ticket: str
    expires_at: float
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "name": self.name,
            "title": self.title,
            "target": self.target,
            "payload": self.payload,
            "risk": self.risk,
            "severity": self.severity.value,
            "irreversible": self.irreversible,
            "ticket": self.ticket,
            "expires_at": self.expires_at,
            "created_at": self.created_at,
        }

    def render_card(self, use_color: bool = True) -> str:
        """渲染高可读性的结构化事务卡片。"""
        width = 72
        title_tag = f" [事务预览卡片 Action Card: {self.action_id}] "
        top_bar = "┌" + title_tag.center(width - 2, "─") + "┐"
        bot_bar = "└" + "─" * (width - 2) + "┘"

        lines = [top_bar]
        lines.append(f"│ 操作类型: {self.name} (风险等级: {self.severity.value.upper()})".ljust(width - 2) + "│")
        if self.title:
            lines.append(f"│ 事务描述: {self.title}".ljust(width - 2) + "│")
        if self.target:
            lines.append(f"│ 目标对象: {self.target}".ljust(width - 2) + "│")

        if self.payload:
            lines.append(f"│ 变更载荷:".ljust(width - 2) + "│")
            for k, v in self.payload.items():
                val_str = str(v)
                if len(val_str) > 48:
                    val_str = val_str[:45] + "..."
                lines.append(f"│   • {k}: {val_str}".ljust(width - 2) + "│")

        lines.append(f"│ 潜在影响: {self.risk}".ljust(width - 2) + "│")
        lines.append(f"│ 确认凭据: {self.ticket} (15分钟内有效，单次放行)".ljust(width - 2) + "│")
        lines.append(f"│ 执行指令: 加 --yes 或 --ticket {self.ticket}".ljust(width - 2) + "│")
        lines.append(bot_bar)
        return "\n".join(lines)


def _tickets_file() -> Path:
    p = config_root() / "cache" / "action_tickets.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_tickets() -> dict[str, dict[str, Any]]:
    path = _tickets_file()
    if not path.exists():
        return {}
    try:
        now = time.time()
        raw = json.loads(path.read_text(encoding="utf-8"))
        # 自动清理过期凭据
        valid = {k: v for k, v in raw.items() if float(v.get("expires_at", 0)) > now}
        return valid
    except Exception:
        return {}


def _save_tickets(data: dict[str, dict[str, Any]]) -> None:
    path = _tickets_file()
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def create_action_card(
    name: str,
    *,
    target: str = "",
    title: str = "",
    payload: dict[str, Any] | None = None,
) -> ActionCard:
    """根据写操作描述符与调用载荷构建 ActionCard 并生成一次性 Ticket。"""
    c = consequence_by_name(name)
    action_id = "act-" + uuid.uuid4().hex[:6]
    ticket = f"tk-{uuid.uuid4().hex[:4]}-{uuid.uuid4().hex[:4]}"
    now = time.time()
    expires_at = now + 900.0  # 15 分钟

    card = ActionCard(
        action_id=action_id,
        name=name,
        title=title or c.what_changes,
        target=target,
        payload=payload or {},
        risk=c.risk,
        severity=c.severity,
        irreversible=c.irreversible,
        ticket=ticket,
        expires_at=expires_at,
        created_at=now,
    )

    tickets = _load_tickets()
    tickets[ticket] = card.to_dict()
    _save_tickets(tickets)
    return card


def validate_and_consume_ticket(ticket: str, expected_name: str | None = None) -> ActionCard | None:
    """验证并单次消费 Ticket。有效则返回对应 ActionCard 并注销该凭证。"""
    if not ticket:
        return None
    tickets = _load_tickets()
    data = tickets.get(ticket)
    if not data:
        return None

    if float(data.get("expires_at", 0)) < time.time():
        tickets.pop(ticket, None)
        _save_tickets(tickets)
        return None

    if expected_name and data.get("name") != expected_name:
        return None

    # 单次有效，销毁凭证
    tickets.pop(ticket, None)
    _save_tickets(tickets)

    return ActionCard(
        action_id=data["action_id"],
        name=data["name"],
        title=data.get("title", ""),
        target=data.get("target", ""),
        payload=data.get("payload", {}),
        risk=data.get("risk", ""),
        severity=Severity(data.get("severity", "medium")),
        irreversible=bool(data.get("irreversible", False)),
        ticket=data["ticket"],
        expires_at=float(data["expires_at"]),
        created_at=float(data.get("created_at", time.time())),
    )


class ConfirmationRequired(Exception):
    """写操作未获确认：携带 :class:`Consequence` 与 :class:`ActionCard`。"""

    def __init__(self, consequence: Consequence, card: ActionCard | None = None):
        self.consequence = consequence
        self.card = card
        super().__init__(consequence.name)


def consequence_by_name(name: str) -> Consequence:
    try:
        return CONSEQUENCES[name]
    except KeyError:
        raise KeyError(
            f"未登记的写操作 {name!r}：新增写操作必须先在 consequence.py 登记描述符"
        ) from None


def require_confirmation(
    name: str,
    *,
    confirmed: bool = False,
    dry_run: bool = False,
    ticket: str | None = None,
    target: str = "",
    title: str = "",
    payload: dict[str, Any] | None = None,
) -> tuple[Consequence, ActionCard | None]:
    """写操作统一确认门。

    若 ``ticket`` 有效，放行执行；
    若 ``dry_run``，放行执行（并附带生成的 card 用于预检预览）；
    若 ``confirmed`` (即 ``--yes``)，放行执行；
    否则抛出 :class:`ConfirmationRequired` 并包含生成的 :class:`ActionCard`。
    """
    consequence = consequence_by_name(name)

    # 1. 检查 Ticket 闭环
    if ticket:
        consumed = validate_and_consume_ticket(ticket, expected_name=name)
        if consumed:
            return consequence, consumed
        raise click.ClickException(f"提供的 Ticket [{ticket}] 无效、已过期或不匹配操作 {name}")

    # 2. 生成事务预览卡片
    card = create_action_card(name, target=target, title=title, payload=payload)

    # 3. dry-run 放行
    if dry_run:
        return consequence, card

    # 4. --yes 放行
    if confirmed:
        return consequence, card

    # 5. 未确认，拦截
    raise ConfirmationRequired(consequence, card=card)


def gate_cli(
    name: str,
    *,
    confirmed: bool,
    dry_run: bool = False,
    ticket: str | None = None,
    target: str = "",
    title: str = "",
    payload: dict[str, Any] | None = None,
    as_json: bool = False,
) -> ActionCard | None:
    """CLI 侧统一门：打印 Action Card 并以退出码 1 结束（若未确认）。"""
    try:
        _, card = require_confirmation(
            name,
            confirmed=confirmed,
            dry_run=dry_run,
            ticket=ticket,
            target=target,
            title=title,
            payload=payload,
        )
        if dry_run and card:
            if as_json:
                click.echo(json.dumps(card.to_dict(), ensure_ascii=False, indent=2))
            else:
                click.echo(card.render_card())
        return card
    except ConfirmationRequired as exc:
        card = exc.card
        if as_json and card:
            click.echo(json.dumps(card.to_dict(), ensure_ascii=False, indent=2))
        elif card:
            click.secho("[写操作拦截] 需 --yes 或 --ticket 确认执行", fg="yellow", bold=True)
            click.echo(card.render_card())
        else:
            click.secho("[写操作未确认] 需要 --yes 才会执行", fg="yellow")
            click.echo(exc.consequence.describe())
        raise SystemExit(1)
