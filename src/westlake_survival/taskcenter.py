"""网上办事大厅（任务中心）个人数据：我的待办。

解锁方式（2026-10-24 实测）
==========================
requests 走不完 infoplus OAuth 回环（authnEngine → one/infoplus/login?
retUrl=…/oauth2/authorize → 又回 IAM），但**真浏览器可以**——引擎页的
auto-submit JS 在浏览器里执行后落地为登录态。因此本模块用 Playwright
**持久化浏览器配置**（``~/.westlake_survival/taskcenter_profile``）：

* 首次（或会话失效时）：自动打开 IAM 登录页，用已存统一凭据填表（不打印），
  浏览器完成全部跳转；
* 会话有效时：headless 打开即取数，无感。

数据接口（页面 apiMap 实测）：

* ``/taskcenter/api/me/tasks/todo`` —— 我的待办；
* ``/taskcenter/api/me/processes/doing`` —— 进行中流程。

依赖：``pip install playwright && playwright install chromium``。
无 Playwright 时抛 :class:`WestlakeError` 给出指引。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from westlake_survival._cache import config_root
from westlake_survival.exceptions import AuthError, WestlakeError

__all__ = ["TASKCENTER_HOME", "PROFILE_DIR", "TodoTask", "todo", "doing", "cli_group"]

logger = logging.getLogger(__name__)

TASKCENTER_HOME = "https://one.westlake.edu.cn/taskcenter/workflow/index"

PROFILE_DIR = Path.home() / ".westlake_survival" / "taskcenter_profile"


@dataclass
class TodoTask:
    """一条待办/进行中流程。"""

    title: str = ""
    department: str = ""
    status: str = ""
    start: str = ""
    url: str = ""
    raw: dict = field(default_factory=dict)


def _browser() -> "object":
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise WestlakeError(
            "办事大厅个人数据需要 Playwright：pip install playwright && playwright install chromium"
        ) from exc
    return sync_playwright()


def _logged_in(page) -> bool:
    """落地页是否已登录（IAM 表单消失、出现用户名/LOGOUT）。"""
    text = page.inner_text("body")[:400]
    return ("LOGOUT" in text) and ("用户名/手机号/邮箱" not in text)


def _ensure_session(page, sid: str, password: str) -> None:
    page.goto(TASKCENTER_HOME, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)
    if _logged_in(page):
        return
    page.wait_for_selector('input[placeholder*="用户名/手机号/邮箱"]', timeout=15000)
    page.fill('input[placeholder*="用户名/手机号/邮箱"]', sid)
    page.fill('input[placeholder*="密码"]', password)
    page.locator('span:has-text("立即登录")').first.click(force=True)
    page.wait_for_timeout(9000)
    if not _logged_in(page):
        raise AuthError("办事大厅登录失败：统一密码可能不对，或页面结构变化")


def _fetch_api(page, path: str, params: str = "") -> dict:
    result = page.evaluate(
        """async ([path, params]) => {
            const r = await fetch('/taskcenter/' + path + params,
                {headers: {'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'}});
            return {status: r.status, body: await r.text()};
        }""",
        [path, params],
    )
    if result["status"] != 200:
        raise WestlakeError(f"办事大厅接口 HTTP {result['status']}")
    try:
        payload = json.loads(result["body"])
    except ValueError as exc:
        raise WestlakeError("办事大厅接口返回非 JSON") from exc
    if payload.get("errno") not in (0, "0"):
        raise AuthError(f"办事大厅会话失效：{payload.get('error')}")
    return payload


def _parse_tasks(payload: dict) -> list[TodoTask]:
    out: list[TodoTask] = []
    for item in payload.get("entities") or []:
        if not isinstance(item, dict):
            continue
        out.append(
            TodoTask(
                title=str(item.get("title") or item.get("name") or ""),
                department=str(item.get("departmentName") or item.get("department") or ""),
                status=str(item.get("status") or item.get("state") or ""),
                start=str(item.get("startDate") or item.get("createTime") or ""),
                url=str(item.get("uri") or item.get("url") or ""),
                raw=dict(item),
            )
        )
    return out


def _collect(path: str, params: str = "") -> list[TodoTask]:
    """起持久化浏览器（或复用会话）取一个个人接口。"""
    from westlake_survival.sso import read_credentials

    try:
        sid, password = read_credentials()
    except Exception as exc:
        raise AuthError("未配置统一凭据；先在网页「设置」页或 westlake setup 配置") from exc

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with _browser() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=True, viewport={"width": 1280, "height": 800}
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            _ensure_session(page, sid, password)
            return _parse_tasks(_fetch_api(page, path, params))
        finally:
            context.close()


def todo() -> list[TodoTask]:
    """我的待办任务（可能为空——没有待办是正常状态）。"""
    return _collect("api/me/tasks/todo")


def doing() -> list[TodoTask]:
    """我发起的进行中流程。"""
    return _collect("api/me/processes/doing", "?limit=20&start=0")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
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

    @click.group(name="todo", help="办事大厅个人事项：我的待办 / 进行中流程。")
    def group() -> None:
        """``westlake todo list|doing``（首次运行自动用统一密码登录）。"""

    @group.command(name="list")
    @handle
    def list_cmd() -> None:
        """我的待办（没有待办输出空）。"""
        items = todo()
        if not items:
            click.echo("没有待办任务。")
            return
        for t in items:
            click.echo(f"  {t.title}　[{t.department}] {t.start} {t.url}")

    @group.command(name="doing")
    @handle
    def doing_cmd() -> None:
        """我发起的进行中流程。"""
        items = doing()
        if not items:
            click.echo("没有进行中的流程。")
            return
        for t in items:
            click.echo(f"  {t.title}　[{t.department}] {t.status}")

    return group


cli_group = _cli()
