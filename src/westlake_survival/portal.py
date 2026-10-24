"""门户个人卡片：未读邮件 / 在借图书 / 待办计数 / AI 助手入口。

数据通道（2026-10-24 实测）
==========================
my 门户首页的个人卡片数值（未读邮件、在借图书、我的待办 0/2/1）是前端
渲染产物，``GeRenKaPianController`` 系列接口返回的是标签配置而非数值。
可靠做法：复用 taskcenter 持久化浏览器会话打开门户，直接从渲染后的
DOM 抽取数值——所见即所得，不怕接口换形态。

AI 助手：``mainPortal/getAiChatbotLink`` 返回 chatbot.westlake.edu.cn
的聊天直链。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from westlake_survival.exceptions import AuthError, WestlakeError

__all__ = ["PortalCards", "fetch_cards", "chatbot_link", "cli_group"]


@dataclass
class PortalCards:
    """门户首页的个人卡片数值。"""

    unread_email: str = ""
    borrowed_books: str = ""
    todo_pending: str = ""
    todo_started: str = ""
    todo_done: str = ""


def _logged_in_page():
    """返回 (manager, context, page, sid, password)；用完 context.close() + manager.__exit__()。"""
    from westlake_survival.sso import read_credentials
    from westlake_survival.taskcenter import PROFILE_DIR, _browser

    try:
        sid, password = read_credentials()
    except Exception as exc:
        raise AuthError("未配置统一凭据；先在网页「设置」页或 westlake setup 配置") from exc
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    cm = _browser()
    manager = cm.__enter__()
    context = manager.chromium.launch_persistent_context(
        str(PROFILE_DIR), headless=True, viewport={"width": 1440, "height": 900}
    )
    page = context.pages[0] if context.pages else context.new_page()
    return cm, context, page, sid, password


def _ensure_portal(page, sid: str, password: str) -> None:
    page.goto("https://my.westlake.edu.cn/", timeout=60000)
    page.wait_for_timeout(3000)
    if "iam.westlake" in page.url:
        page.wait_for_selector('input[placeholder*="用户名/手机号/邮箱"]', timeout=15000)
        page.fill('input[placeholder*="用户名/手机号/邮箱"]', sid)
        page.fill('input[placeholder*="密码"]', password)
        page.locator('span:has-text("立即登录")').first.click(force=True)
    page.wait_for_timeout(10000)
    if "my.westlake" not in page.url:
        raise AuthError("门户登录失败（统一密码可能不对）")


def fetch_cards() -> PortalCards:
    """取门户个人卡片数值（渲染后 DOM 抽取）。"""
    cm, context, page, sid, password = _logged_in_page()
    try:
        _ensure_portal(page, sid, password)
        text = page.inner_text("body")
        lines = [line.strip() for line in text.split("\n") if line.strip()]

        def value_after(label: str, offset: int = 1) -> str:
            for index, line in enumerate(lines):
                if line == label and index + offset < len(lines):
                    candidate = lines[index + offset]
                    if re.fullmatch(r"[\d,.*]+", candidate):
                        return candidate
            return ""

        return PortalCards(
            unread_email=value_after("未读邮件"),
            borrowed_books=value_after("在借图书"),
            todo_pending=value_after("待办理"),
            todo_started=value_after("已发起"),
            todo_done=value_after("已处理"),
        )
    finally:
        context.close()
        cm.__exit__(None, None, None)


def chatbot_link() -> str:
    """AI 助手（chatbot）聊天直链。"""
    cm, context, page, sid, password = _logged_in_page()
    captured: list[str] = []
    page.on("response", lambda r: captured.append(r.text())
            if "getAiChatbotLink" in r.url else None)
    try:
        _ensure_portal(page, sid, password)
        import json as _json

        for body in captured:
            try:
                link = str(_json.loads(body).get("data", {}).get("content") or "")
                if link:
                    return link
            except (ValueError, AttributeError):
                continue
        result = page.evaluate(
            """async () => {
                const r = await fetch('/service/xhdxkfzyy7882320728204987658/mainPortal/getAiChatbotLink',
                    {headers: {'Accept': 'application/json'}});
                const d = await r.json();
                return (d.data || {}).content || '';
            }"""
        )
        return str(result)
    finally:
        context.close()
        cm.__exit__(None, None, None)


def _cli():
    import functools

    import click

    from westlake_survival.exceptions import WestlakeError

    def handle(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except WestlakeError as exc:
                click.secho(f"错误：{exc}", fg="red", err=True)
                raise SystemExit(1) from exc

        return wrapper

    @click.group(name="portal", help="门户个人卡片与 AI 助手入口。")
    def group() -> None:
        """``westlake portal cards|chatbot``。"""

    @group.command(name="cards")
    @handle
    def cards_cmd() -> None:
        """未读邮件 / 在借图书 / 待办计数。"""
        cards = fetch_cards()
        click.echo(f"未读邮件：{cards.unread_email or '—'}")
        click.echo(f"在借图书：{cards.borrowed_books or '—'}")
        click.echo(f"我的待办：待办理 {cards.todo_pending or '—'}　已发起 {cards.todo_started or '—'}　已处理 {cards.todo_done or '—'}")

    @group.command(name="chatbot")
    @handle
    def chatbot_cmd() -> None:
        """AI 助手（chatbot）聊天入口。"""
        click.echo(chatbot_link())

    return group


cli_group = _cli()
