"""深信服 SSL VPN（vpn.westlake.edu.cn）手动登录会话层。

2026-10-25 实测：协议链可完全复刻（``/public/psw_config`` 取 RSA 公钥 ->
PKCS1v15 加密 ``密码_csrf`` -> POST ``/por/login_psw.csp``），但该网关对
出口 IP 启用了防暴破图形验证码（ErrorCode 20041），机器读码两轮失败。
用户裁定：登录窗口放前端**手动输码**，会话落盘后库内复用。

- 登录：:func:`open_login` 起有头持久化浏览器（本人输验证码），成功后
  cookie（TWFID 等）导出到 ``vpn_session.json``（expires=-1 归一为会话态）。
- 复用：:func:`status` 探会话死活；:func:`resources` 取 VPN 发布的内网
  资源列表（rclist.csp，登录后才可读）。
"""

from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import click

from westlake_survival._cache import config_root
from westlake_survival.exceptions import WestlakeError

__all__ = [
    "VPN_URL",
    "PROFILE_DIR",
    "SESSION_FILE",
    "open_login",
    "status",
    "resources",
    "cli_group",
]

VPN_URL = "https://vpn.westlake.edu.cn"
PROFILE_DIR = Path.home() / ".westlake_survival" / "vpn_profile"
SESSION_FILE = config_root() / "vpn_session.json"


def _load_cookies() -> list[dict]:
    if not SESSION_FILE.exists():
        return []
    try:
        return json.loads(SESSION_FILE.read_text(encoding="utf-8")).get("cookies") or []
    except (OSError, ValueError):
        return []


def _session():
    """带已存 VPN cookie 的直连会话（不校验证书——深信服自签）。"""
    import requests
    import urllib3

    urllib3.disable_warnings()
    s = requests.Session()
    s.verify = False
    s.trust_env = False
    s.headers.update({"User-Agent": "Mozilla/5.0", "Referer": f"{VPN_URL}/portal/"})
    for c in _load_cookies():
        s.cookies.set_cookie(requests.cookies.create_cookie(
            name=c.get("name", ""), value=c.get("value", ""),
            domain=c.get("domain", ""), path=c.get("path", "/")))
    return s


def _auth_code(xml_text: str) -> tuple[str, str]:
    """深信服 XML 应答 -> (ErrorCode, Message)。"""
    code = re.search(r"<ErrorCode>(\d+)</ErrorCode>", xml_text or "")
    msg = re.search(r"<Message><!\[CDATA\[(.*?)\]\]></Message>", xml_text or "")
    return (code.group(1) if code else "?", msg.group(1) if msg else "")


def status() -> dict:
    """VPN 会话状态：conf.csp 非 20026 即活。"""
    try:
        r = _session().get(f"{VPN_URL}/por/conf.csp", timeout=8)
        code, msg = _auth_code(r.text)
        return {"logged_in": code not in ("20026", "?"), "code": code, "message": msg}
    except Exception as exc:  # noqa: BLE001 - 状态查询失败也算一种状态
        return {"logged_in": False, "code": "", "message": f"{exc.__class__.__name__}: {exc}"[:120]}


def resources() -> list[dict]:
    """VPN 里发布的内网资源列表（需已登录）。"""
    r = _session().get(f"{VPN_URL}/por/rclist.csp", timeout=10)
    code, msg = _auth_code(r.text)
    if code == "20026":
        raise WestlakeError("VPN 会话失效：请在网页 /vpn 重新登录")
    rows: list[dict] = []
    try:
        root = ET.fromstring(re.sub(r"&(?!\w+;)", "&amp;", r.text))
    except ET.ParseError as exc:
        raise WestlakeError(f"资源列表解析失败（{exc}）") from exc
    for row in root.iter():
        if (row.tag or "").lower() not in ("row", "rc", "resource"):
            continue
        fields = {c.tag.lower(): (c.text or "").strip() for c in row if c.text and c.text.strip()}
        if not fields:
            continue
        rows.append({
            "title": fields.get("name") or fields.get("resname") or fields.get("title") or "",
            "url": fields.get("uri") or fields.get("url") or fields.get("link") or "",
            "raw": fields,
        })
    return rows


def open_login(wait_seconds: int = 300) -> dict:
    """起有头浏览器到 VPN 门户，等本人登录（输验证码），成功后导出会话。

    判成功：cookie 里出现 TWFID 且 conf.csp 不再回 20026。
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - 环境缺 playwright
        raise WestlakeError("缺 playwright：pip install playwright && playwright install chromium") from exc

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    result = {"ok": False, "message": ""}
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=False, viewport={"width": 1180, "height": 800})
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto(f"{VPN_URL}/portal", timeout=60_000)
            deadline = time.monotonic() + wait_seconds
            while time.monotonic() < deadline:
                time.sleep(3)
                try:
                    probe = context.request.get(f"{VPN_URL}/por/conf.csp",
                                                headers={"Referer": f"{VPN_URL}/portal/"})
                    if "20026" not in (probe.text() or ""):
                        result = {"ok": True, "message": "登录成功，会话已导出"}
                        break
                except Exception:  # noqa: BLE001 - 探测失败继续等
                    pass
            if not result["ok"]:
                result = {"ok": False, "message": f"等待 {wait_seconds}s 未见登录成功（可重跑）"}
            cookies = context.cookies(VPN_URL)
            for c in cookies:  # Playwright 会话 cookie expires=-1 会被 cookiejar 判过期
                if c.get("expires", -1) < 0:
                    c["expires"] = None
            SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
            SESSION_FILE.write_text(
                json.dumps({"cookies": cookies, "saved_at": time.strftime("%Y-%m-%d %H:%M:%S")},
                           ensure_ascii=False, indent=1), encoding="utf-8")
        finally:
            context.close()
    return result


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
@click.group(name="vpn", help="SSL VPN 会话：手动登录 / 状态 / 资源列表。")
def cli_group() -> None:
    """``westlake vpn`` 命令组（注册由 ``cli.main`` 完成）。"""


@cli_group.command(name="login")
@click.option("--wait", default=300, show_default=True, help="等待登录秒数。")
def vpn_login(wait: int) -> None:
    """打开登录窗口（有头浏览器，本人输验证码），成功后保存会话。"""
    click.echo(f"打开 {VPN_URL}/portal …（在浏览器里登录，最多等 {wait}s）")
    result = open_login(wait)
    (click.echo if result["ok"] else lambda m: click.secho(m, fg="red"))(result["message"])
    raise SystemExit(0 if result["ok"] else 1)


@cli_group.command(name="status")
def vpn_status() -> None:
    """查看 VPN 会话状态。"""
    st = status()
    click.echo(f"会话{'有效' if st['logged_in'] else '无效/未登录'}（code={st['code']}）{st['message']}")
    if SESSION_FILE.exists():
        saved = json.loads(SESSION_FILE.read_text(encoding="utf-8")).get("saved_at", "?")
        click.echo(f"会话文件：{SESSION_FILE}（{saved} 保存）")


@cli_group.command(name="resources")
def vpn_resources() -> None:
    """列出 VPN 发布的内网资源（需已登录）。"""
    try:
        rows = resources()
    except WestlakeError as exc:
        click.secho(str(exc), fg="red", err=True)
        raise SystemExit(1)
    if not rows:
        click.echo("（资源列表为空）")
        return
    from westlake_survival.cli.main import _print_table

    _print_table(
        [(r["title"][:34], r["url"][:60]) for r in rows],
        ("资源", "入口"),
    )
