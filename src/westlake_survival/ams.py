"""西湖大学教学系统（AMS）：课表 / 学期周次 / 服务入口（只读）。

系统形态（2026-10-28 实测）
==========================
``ams.westlake.edu.cn`` 就是「西湖大学教学系统」门户：前端 Vue SPA 在 ``/home/``，
后端网关 ``/portal-service/api/v1/…``。登录走 **IAM 统一认证**：

* ``GET /`` → 302 ``/login`` → 302 ``/sso/login`` → ``iam.westlake.edu.cn/ac/#/index``
  带 ``entityId=https://ams.westlake.edu.cn``（即 IAM 的 CAS 上下文，与 SIS 同一套
  统一密码，不需要另设账号）；
* 经典 CAS（``sso.westlake.edu.cn/cas/login``）**不接**这个 service（返回
  ``Application Not Authorized``），所以走 :func:`westlake_survival.iam.login_for`。

已实测可用的只读接口（``identity=STUDENT``）：

* ``/home/index`` —— 学期名、教学周次、是否在学期内；
* ``/schedule/get-calendars?startDateStr=&endDateStr=&reqType=Date`` —— 课程日程
  （标题 / 起止时间 / 地点）；
* ``/common/home/get-all-menus`` —— 服务菜单，含学籍、学术导师、选课、我的课表
  等子系统链接；
* ``/notice-view/get-all-notice`` —— 通知。

会话：IAM 登录一次后把 ``ams.westlake.edu.cn`` 的 cookie 存
``~/.westlake_survival/ams_cookies.json``（0600），之后先用缓存验活，避免每次
都去 IAM 走一遍密码（减少验证码风控与锁号风险）。cookie 只存不打印。
"""

from __future__ import annotations

import json
import os
import time
from datetime import date, timedelta
from http.cookiejar import Cookie as _Cookie
from pathlib import Path
from typing import Any

from westlake_survival._net import DEFAULT_TIMEOUT
from westlake_survival.discovery import direct_session
from westlake_survival.exceptions import AuthError, WestlakeError

__all__ = [
    "BASE",
    "login",
    "session_alive",
    "overview",
    "schedule",
    "today",
    "menus",
    "notices",
]

BASE = os.environ.get("WESTLAKE_AMS_BASE", "https://ams.westlake.edu.cn")
PORTAL = BASE + "/portal-service/api/v1"
ENTRY = BASE + "/sso/login"

#: 缓存会话的落盘位置（遵循 ``WESTLAKE_HOME`` 重定位约定）。
COOKIES_FILENAME = "ams_cookies.json"

#: 缓存有效期（秒）：8 小时，覆盖一个工作日的反复调用。
_TTL = 8 * 3600


def _cookies_path() -> Path:
    override = os.environ.get("WESTLAKE_HOME")
    root = Path(override) if override else Path.home() / ".westlake_survival"
    return root / COOKIES_FILENAME


def _save_jar(session) -> None:
    jar = [
        {"name": c.name, "value": c.value, "domain": c.domain, "path": c.path,
         "expires": c.expires}
        for c in session.cookies
        if "ams.westlake.edu.cn" in (c.domain or "")
    ]
    path = _cookies_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"ts": time.time(), "cookies": jar}, ensure_ascii=False),
                    encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:  # pragma: no cover - Windows 上权限语义有限
        pass


def _load_jar():
    """从缓存 cookie 建会话；无缓存或过期返回 ``None``。"""
    path = _cookies_path()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if time.time() - float(payload.get("ts") or 0) > _TTL:
        return None
    jar = payload.get("cookies") or []
    if not jar:
        return None
    session = direct_session()
    for item in jar:
        expires = item.get("expires") or None
        if expires is not None and expires <= 0:
            expires = None
        try:
            session.cookies.set_cookie(_Cookie(
                version=0, name=item["name"], value=item["value"],
                port=None, port_specified=False,
                domain=item["domain"], domain_specified=True, domain_initial_dot=False,
                path=item.get("path") or "/", path_specified=True,
                secure=True, expires=expires,
                discard=expires is None, comment=None, comment_url=None,
                rest={}, rfc2109=False,
            ))
        except Exception:  # noqa: BLE001 - 单条 cookie 异常不影响其余
            continue
    return session


def session_alive(session) -> bool:
    """缓存会话是否还有效（访问一次 home/index，看是否被踢回登录）。"""
    try:
        response = session.get(f"{PORTAL}/home/index", params={"identity": "STUDENT"},
                               timeout=DEFAULT_TIMEOUT, allow_redirects=False)
    except Exception:  # noqa: BLE001 - 网络异常按失效处理
        return False
    return response.status_code == 200 and "json" in response.headers.get("Content-Type", "")


def login(*, force: bool = False):
    """返回已登录的教学系统会话（优先复用缓存 cookie）。"""
    if not force:
        cached = _load_jar()
        if cached is not None and session_alive(cached):
            return cached

    from westlake_survival.iam import login_for
    from westlake_survival.sso import read_credentials

    try:
        sid, password = read_credentials()
    except Exception as exc:
        raise AuthError("未配置统一凭据；先 westlake setup 或网页「设置」页配置") from exc

    session = direct_session()
    login_for(ENTRY, sid, password, session=session)
    if not session_alive(session):
        raise AuthError("统一认证已通过，但教学系统会话未建立（入口或协议可能变化）")
    _save_jar(session)
    return session


def _get_json(session, path: str, params: dict | None = None) -> dict:
    response = session.get(f"{PORTAL}{path}", params=params, timeout=DEFAULT_TIMEOUT)
    if response.status_code in (401, 403) or "iam.westlake.edu.cn" in response.url:
        raise AuthError("教学系统会话失效，请重新登录（westlake ams login）")
    if response.status_code != 200:
        raise WestlakeError(f"教学系统接口 {path} 返回 HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise WestlakeError(f"教学系统接口 {path} 返回非 JSON") from exc
    if payload.get("code") not in (0, None):
        raise WestlakeError(f"教学系统接口 {path} 返回 {payload.get('code')}: {payload.get('msg')}")
    return payload.get("data") or {}


def overview() -> dict:
    """学期名、教学周次、是否在学期内（不含个人身份信息）。"""
    data = _get_json(login(), "/home/index", {"identity": "STUDENT"})
    return {
        "semester": data.get("currentSemester"),
        "week": data.get("weekIndex"),
        "in_semester": data.get("isInSemester"),
        "last_week": data.get("lastWeekIndex"),
    }


def schedule(start: date | str, end: date | str) -> list[dict]:
    """课程日程：给定日期区间返回排课条目（按开始时间排序）。"""
    start_s = start.isoformat() if isinstance(start, date) else str(start)
    end_s = end.isoformat() if isinstance(end, date) else str(end)
    data = _get_json(
        login(),
        "/schedule/get-calendars",
        {"startDateStr": start_s, "endDateStr": end_s, "reqType": "Date"},
    )
    days = (data or {}).get("schedule") or {}
    rows: list[dict] = []
    seen: set[tuple] = set()
    for day, payload in days.items():
        for item in (payload or {}).get("calendarList") or []:
            row = (
                day,
                item.get("startTime") or "",
                item.get("endTime") or "",
                item.get("title") or "",
                item.get("address") or "",
            )
            # 同一门课的分组/重复行会被接口重复吐回来，按「日期+时段+课名+地点」去重。
            if row in seen:
                continue
            seen.add(row)
            rows.append(
                {
                    "date": day,
                    "title": row[3],
                    "start": row[1],
                    "end": row[2],
                    "address": row[4],
                    "whole_day": item.get("isWholeDay") in ("1", 1, True),
                }
            )
    rows.sort(key=lambda r: (r["date"], r["start"]))
    return rows


def today() -> list[dict]:
    """今天的课程安排。"""
    now = date.today()
    return schedule(now, now)


def this_week() -> list[dict]:
    """本周（周一至周日）的课程安排。"""
    now = date.today()
    monday = now - timedelta(days=now.weekday())
    return schedule(monday, monday + timedelta(days=6))


def menus() -> list[dict]:
    """服务菜单（学籍 / 学术导师 / 选课 / 我的课表 …），带跳转链接。"""
    data = _get_json(login(), "/common/home/get-all-menus", {"identity": "STUDENT"})
    items = data if isinstance(data, list) else []
    return [
        {
            "name": item.get("nameZh") or "",
            "code": item.get("menuCode") or "",
            "href": item.get("href"),
            "parent": item.get("parentId"),
            "show": bool(item.get("show")),
        }
        for item in items
    ]


def notices() -> list[dict]:
    """通知列表（未读 + 全部）。"""
    data = _get_json(login(), "/notice-view/get-all-notice")
    out: list[dict] = []
    for key in ("noReadNotices", "allNotices"):
        for item in (data.get(key) or []):
            out.append(
                {
                    "title": item.get("title") or item.get("noticeTitle") or "",
                    "date": item.get("publishTime") or item.get("createTime") or "",
                    "unread": key == "noReadNotices",
                    "url": item.get("url") or item.get("href") or "",
                }
            )
    return out
