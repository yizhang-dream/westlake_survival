"""西湖大学新版图书馆个人服务（mylib.westlake.edu.cn，阿法迪云平台）。

系统背景（2026-10-28 迁移实测，2026-10-31 攻坚完成）
======================================================
老 OPAC（172.16.10.223:8180/opac）整体下线后，学校启用了新平台：
- 门户地址：https://mylib.westlake.edu.cn/
- 身份认证：CAS 统一认证联动（由 metaauth.com 经 libyyd.westlake.edu.cn 接入校内统一认证）；
- 核心服务：当前在借图书（/westlakesearch/thirdPart/getReaderCurrentLoan）、借阅历史、还书提醒、在线续借；
- 认证协议：登录后下发长效 userJwt（多日有效），业务请求走 ``PrimoAuthorization: Bearer <userJwt>``。

本模块实现：
1. 自动登录与 JWT 跨会话缓存（~/.westlake_survival/lib_jwt.json）；
2. 借阅查询 ``get_reader_loans()`` 封装为通用 :class:`~westlake_survival.lib.models.Loan` 模型；
3. 失效自愈：JWT 过期或被服务端拒收时自动重新建立会话。
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import requests

from westlake_survival._cache import config_root, load_cached, save_cached
from westlake_survival._net import DEFAULT_TIMEOUT
from westlake_survival.discovery import direct_session
from westlake_survival.exceptions import AuthError, NotFound, OffCampusError, WestlakeError
from westlake_survival.lib.models import Loan

__all__ = [
    "MYLIB_BASE_URL",
    "get_mylib_jwt",
    "get_reader_loans",
    "renew_loan",
]

logger = logging.getLogger(__name__)

MYLIB_BASE_URL = "https://mylib.westlake.edu.cn"
_JWT_CACHE_FILE = "lib/user_jwt.json"


def _jwt_cache_path() -> Path:
    return config_root() / "cache" / _JWT_CACHE_FILE


def _load_cached_jwt() -> str | None:
    path = _jwt_cache_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        token = data.get("token")
        exp = float(data.get("exp") or 0)
        # 预留 10 分钟缓冲区
        if token and exp > time.time() + 600:
            return token
    except Exception:
        pass
    return None


def _save_cached_jwt(token: str, exp: float, user_info: dict | None = None) -> None:
    path = _jwt_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "token": token,
        "exp": exp,
        "user_info": user_info or {},
        "updated_at": time.time(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _clear_cached_jwt() -> None:
    path = _jwt_cache_path()
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass


def get_mylib_jwt(*, force_refresh: bool = False) -> str:
    """获取读者在 mylib.westlake.edu.cn 的有效认证 userJwt（长效缓存）。"""
    if not force_refresh:
        cached = _load_cached_jwt()
        if cached:
            return cached

    from westlake_survival.sso import read_credentials

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise WestlakeError(
            "新版图书馆登录需要 Playwright 浏览器链路：pip install 'westlake-survival[browser]'"
        ) from exc

    try:
        sid, password = read_credentials()
    except Exception as exc:
        raise AuthError("未配置校园统一身份认证账号，无法登录图书馆") from exc

    target_entry = f"{MYLIB_BASE_URL}/entrance/myLibEntrance/myLibIndex/MyLibBorrowNow"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        try:
            page.goto(target_entry, timeout=30000)
            for _ in range(20):
                if "iam.westlake" in page.url or "mylib" in page.url:
                    break
                page.wait_for_timeout(500)

            if "iam.westlake" in page.url:
                page.wait_for_selector('input[placeholder*="用户名/手机号/邮箱"]', timeout=10000)
                page.fill('input[placeholder*="用户名/手机号/邮箱"]', sid)
                page.fill('input[placeholder*="密码"]', password)
                page.locator('button.content_submit, span:has-text("立即登录")').first.click()

            for _ in range(40):
                if "mylib.westlake.edu.cn" in page.url and "transition" not in page.url:
                    page.wait_for_timeout(2000)
                    break
                page.wait_for_timeout(500)

            user_info_raw = page.evaluate('() => localStorage.getItem("userInfo")')
            if not user_info_raw:
                raise AuthError("图书馆认证未返回读者信息，统一认证密码可能不正确或账号受限。")

            user_info = json.loads(user_info_raw)
            token = user_info.get("userJwt")
            if not token:
                raise AuthError("读者信息中缺少 userJwt 令牌。")

            # 解码 JWT exp
            import base64

            exp = time.time() + 86400 * 3  # 默认 3 天
            try:
                parts = token.split(".")
                if len(parts) >= 2:
                    padding = "=" * (4 - len(parts[1]) % 4)
                    body = json.loads(base64.urlsafe_b64decode(parts[1] + padding))
                    exp = float(body.get("exp") or exp)
            except Exception:
                pass

            _save_cached_jwt(token, exp, user_info)
            return token

        except Exception as exc:
            if "Timeout" in exc.__class__.__name__:
                raise OffCampusError("访问图书馆新系统登录超时，校外请先连接西湖大学 VPN。") from exc
            raise
        finally:
            context.close()
            browser.close()


def get_reader_loans(*, force_refresh: bool = False, session: requests.Session | None = None) -> list[Loan]:
    """查询读者当前在借图书列表。"""
    jwt = get_mylib_jwt(force_refresh=force_refresh)
    session = session or direct_session()

    url = f"{MYLIB_BASE_URL}/westlakesearch/thirdPart/getReaderCurrentLoan"
    headers = {
        "PrimoAuthorization": f"Bearer {jwt}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {"pageNo": 1, "pageSize": 50}

    try:
        resp = session.post(url, headers=headers, data=data, timeout=DEFAULT_TIMEOUT, verify=False)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        raise WestlakeError(f"请求借阅列表失败：{exc}") from exc

    code = payload.get("code")
    if code != 200:
        if not force_refresh:
            # 尝试刷新 JWT 重试一次
            _clear_cached_jwt()
            return get_reader_loans(force_refresh=True, session=session)
        raise AuthError(f"获取借阅列表被拒（{payload.get('msg')}）")

    loans: list[Loan] = []
    items_list = payload.get("data", {}).get("list") or []

    for item in items_list:
        inst = (item.get("itemInfo") or {}).get("instance") or {}
        log = item.get("loanLog") or {}
        item_det = (item.get("itemInfo") or {}).get("item") or {}

        title = inst.get("title") or ""
        barcode = log.get("itemBarcode") or item_det.get("barcode") or ""
        due_date = log.get("dueDate") or ""
        location = item_det.get("permanentLocationName") or log.get("permanentLocationCode") or ""
        renewal_count = log.get("renewalCount", 0)

        loans.append(
            Loan(
                title=title,
                barcode=barcode,
                due_date=due_date,
                renewable=bool(renewal_count < 1),
                location=location,
            )
        )

    return loans


def renew_loan(barcode: str, *, dry_run: bool = False, session: requests.Session | None = None) -> dict:
    """在借图书在线续借（写操作，带 dry-run 校验）。"""
    loans = get_reader_loans(session=session)
    matched = [item for item in loans if item.barcode == barcode]
    if not matched:
        raise NotFound(f"在借图书中未找到条码为 [{barcode}] 的图书。")
    book = matched[0]
    if not book.renewable:
        raise WestlakeError(f"图书《{book.title}》（条码 {barcode}）不可续借（已达续借上限或超期）。")

    if dry_run:
        return {
            "dry_run": True,
            "barcode": barcode,
            "title": book.title,
            "current_due_date": book.due_date,
            "renewable": True,
            "msg": "校验通过，符合续借条件",
        }

    jwt = get_mylib_jwt()
    session = session or direct_session()
    url = f"{MYLIB_BASE_URL}/westlakesearch/thirdPart/renewBook"
    headers = {
        "PrimoAuthorization": f"Bearer {jwt}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {"itemBarcode": barcode}
    try:
        resp = session.post(url, headers=headers, data=data, timeout=DEFAULT_TIMEOUT, verify=False)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        raise WestlakeError(f"续借请求网络失败：{exc}") from exc

    if payload.get("code") != 200:
        raise WestlakeError(f"续借失败：{payload.get('msg') or payload}")

    return {
        "barcode": barcode,
        "title": book.title,
        "result": payload.get("data") or "续借成功",
    }
