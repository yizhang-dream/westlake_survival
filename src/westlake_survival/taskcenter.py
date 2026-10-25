"""网上办事大厅（任务中心）个人数据：待办 / 进行中 / 已处理 / 抄送 / 应用。

解锁方式（2026-10-25 更新）
==========================
早先 requests 走不完 infoplus OAuth 回环（authnEngine → one/infoplus/login?
retUrl=…/oauth2/authorize → 又回 IAM），只能靠 Playwright 让引擎页的
auto-submit JS 自己跑。现在把引擎页里的 ``locationValue`` 直接跟下去即可：

1. ``GET /taskcenter/workflow/index`` → 302 authorize → 303 login →
   IAM ``/ac/#/index?lck=…&entityId=https://one.westlake.edu.cn``；
2. IAM 认证链（queryAuthMethods → verifyCodeIsNeed → getJsPublicKey →
   authExecute）拿到 ``loginToken``；
3. ``POST /idp/authCenter/authnEngine`` 返回的 HTML 里有
   ``var locationValue = "https://one.westlake.edu.cn/infoplus/login?retUrl=…"``，
   GET 它即完成 OAuth，会话落进 ``requests.Session``。

统一封装在 :func:`westlake_survival.iam.login_for`，本模块不再依赖浏览器。

数据接口（页面网络实测）：

* ``api/me/tasks/todo?entrust=true`` —— 我的待办；
* ``api/me/processes/todo`` / ``doing`` / ``done`` / ``cc``（``unread=true``）；
* ``api/me/processes/merge`` —— 合并列表；
* ``api/me/apps`` —— 我有权限发起/访问的应用；
* ``api/me/preference/FavoriteApps`` —— 常用应用。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from westlake_survival._cache import config_root
from westlake_survival.exceptions import AuthError, WestlakeError

__all__ = [
    "TASKCENTER_HOME",
    "PROFILE_DIR",
    "TodoTask",
    "todo",
    "doing",
    "done",
    "cc",
    "apps",
    "cli_group",
]

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
    """取一个个人接口（请求直连，2026-10-25 起不再依赖浏览器）。

    任务中心是 infoplus OAuth 客户端；登录走
    :func:`westlake_survival.iam.login_for`，认证后 authnEngine 回跳落地，
    会话保存在 ``requests.Session`` 里。
    """
    return _parse_tasks(_fetch_json(path, params))


_SESSION = None


def _http_session():
    """共享的任务中心会话（首次调用时用统一凭据登录 IAM）。"""
    global _SESSION
    if _SESSION is None:
        from westlake_survival import iam
        from westlake_survival.sso import read_credentials

        try:
            sid, password = read_credentials()
        except Exception as exc:
            raise AuthError("未配置统一凭据；先在网页「设置」页或 westlake setup 配置") from exc
        _SESSION = iam.login_for(TASKCENTER_HOME, sid, password)
    return _SESSION


def _fetch_json(path: str, params: str = "") -> dict:
    """请求任务中心接口并返回 JSON；会话失效时重登一次。"""
    global _SESSION
    url = f"https://one.westlake.edu.cn/taskcenter/{path.lstrip('/')}"
    if params:
        url = f"{url}?{params.lstrip('?')}"
    for attempt in (0, 1):
        session = _http_session()
        response = session.get(url, timeout=30, allow_redirects=True)
        if "iam.westlake.edu.cn" in response.url or response.status_code in (401, 403):
            _SESSION = None
            if attempt == 0:
                continue
            raise AuthError("办事大厅会话失效，请重新登录统一认证")
        try:
            payload = response.json()
        except ValueError as exc:
            raise WestlakeError(f"任务中心接口返回非 JSON：{response.text[:120]}") from exc
        return payload
    raise AuthError("办事大厅会话失效")


def todo() -> list[TodoTask]:
    """我的待办任务（可能为空——没有待办是正常状态）。"""
    return _collect("api/me/tasks/todo", "entrust=true")


def doing() -> list[TodoTask]:
    """我发起的进行中流程。"""
    return _collect("api/me/processes/doing", "limit=20&start=0")


def done() -> list[TodoTask]:
    """我已处理的流程（``processes/done``）。"""
    return _collect("api/me/processes/done", "limit=20&start=0")


def cc() -> list[TodoTask]:
    """抄送给我的流程（``processes/cc``，只看未读）。"""
    return _collect("api/me/processes/cc", "limit=10&start=0&unread=true")


def apps() -> list[dict]:
    """我有权限发起/访问的应用（``api/me/apps``）。"""
    payload = _fetch_json("api/me/apps")
    rows = []
    for item in payload.get("entities") or []:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "name": str(item.get("name") or ""),
                "code": str(item.get("code") or ""),
                "uri": str(item.get("uri") or ""),
            }
        )
    return rows


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

    @group.command(name="done")
    @handle
    def done_cmd() -> None:
        """我已处理的流程。"""
        items = done()
        if not items:
            click.echo("没有已处理的流程。")
            return
        for t in items:
            click.echo(f"  {t.title}　[{t.department}] {t.status}")

    @group.command(name="cc")
    @handle
    def cc_cmd() -> None:
        """抄送给我的流程（未读）。"""
        items = cc()
        if not items:
            click.echo("没有抄送事项。")
            return
        for t in items:
            click.echo(f"  {t.title}　[{t.department}] {t.status}")

    @group.command(name="apps")
    @handle
    def apps_cmd() -> None:
        """我有权限发起/访问的应用。"""
        items = apps()
        if not items:
            click.echo("没有可用应用。")
            return
        for item in items:
            click.echo(f"  {item['name']}　{item['uri']}")

    return group


cli_group = _cli()
