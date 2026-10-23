"""一次性抓取西湖电子地图的数据接口（人工登录，密码不经手）。

为什么是这个形态
================
地图数据接口全部要令牌（匿名 ``10031``），但数据本身与账号无关。所以只需要
**任意一位有账号的人成功登录一次**，把接口响应固化下来随包发布；其他用户
不需要账号。

本脚本使用**持久化浏览器配置**（``~/.westlake_survival/map_browser_profile``）：
第一次需要你本人在窗口里登录（脚本不读、不存、不打印密码），之后重跑会直接
复用登录态，不必重复登录。登录完成后遍历页面并把所有 ``/api/**`` 列表响应
存成 JSON，同时写一份 ``.summary.json`` 接口清单供人工确认。

用法::

    python tools/capture_map.py --out raw_map_capture.json
    python tools/build_map_dataset.py raw_map_capture.json \
        --out src/westlake_survival/data/campus_map.json

登录阶段最长等 10 分钟；登录成功后自动等待数据加载、点击可见的区域/菜单项，
尽量把各接口都触发一遍。抓完后请人工看一眼 ``endpoints`` 里是否包含楼宇/
设施/区域三类数据。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE_URL = "https://map.westlake.edu.cn"

#: 登录最长等待（秒）。
LOGIN_TIMEOUT_S = 900

#: 持久化浏览器配置目录（保存登录态，重跑免登录）。
PROFILE_DIR = Path.home() / ".westlake_survival" / "map_browser_profile"


def _wait_for_login(page, state: dict) -> bool:
    """等真正登录完成。

    不能只看「URL 离开 /login」——点「统一身份认证」也会跳走（到 IAM），
    那时还没登录。可靠判据是**出现带 Authorization 的业务请求**。
    """
    deadline = time.time() + LOGIN_TIMEOUT_S
    print("请在弹出的浏览器窗口里登录（可用「切换登录方式 → 统一身份认证」）。", flush=True)
    print("账号密码只有你自己看到；检测到登录成功会自动继续。", flush=True)
    while time.time() < deadline:
        if state.get("authorized"):
            time.sleep(5)  # 让首屏接口跑完
            return True
        page.wait_for_timeout(800)
    return False


def _walk_ui(page) -> None:
    """尽量触发各数据接口：滚动、点击可见菜单/列表项。"""
    page.wait_for_timeout(3000)
    for _ in range(3):
        page.mouse.wheel(0, 1200)
        page.wait_for_timeout(800)
    selectors = [
        ".el-menu-item", ".el-tabs__item", ".el-submenu__title", ".menu-item",
        "li[class*=menu]", "div[class*=tree-node]", "div[class*=list-item]",
        "div[class*=card]", "span[class*=title]", "div[class*=category]",
        "button", "a",
    ]
    clicked = 0
    for selector in selectors:
        try:
            items = page.query_selector_all(selector)
        except Exception:
            continue
        for item in items[:10]:
            try:
                item.click(timeout=1500)
                page.wait_for_timeout(1200)
                clicked += 1
            except Exception:
                continue
    print(f"已点击 {clicked} 个界面元素以触发接口。", flush=True)


def capture(out_path: Path) -> int:
    """启动浏览器、等登录、抓响应、写文件。返回进程退出码。"""
    captured: dict[str, list] = {}
    raw_log: list[dict] = []
    state: dict = {"authorized": False}

    def on_request(request):
        if "/api/nsc/" in request.url and request.headers.get("authorization"):
            state["authorized"] = True

    summary: dict[str, dict] = {}

    def on_response(response):
        url = response.url
        if "/api/" not in url:
            return
        try:
            payload = response.json()
        except Exception:
            return
        if not isinstance(payload, dict):
            return
        endpoint = url.split("map.westlake.edu.cn", 1)[-1].split("?", 1)[0]
        data = payload.get("data")
        entry = summary.setdefault(
            endpoint,
            {"code": str(payload.get("code")), "type": type(data).__name__, "count": 0, "keys": []},
        )
        if payload.get("code") not in ("10000", 0, "0", 200, "200"):
            return
        raw_log.append({"endpoint": endpoint, "code": payload.get("code")})
        if isinstance(data, list) and data and isinstance(data[0], dict):
            entry["count"] = max(entry["count"], len(data))
            entry["keys"] = sorted(data[0].keys())[:12]
            if len(data) > len(captured.get(endpoint, [])):
                captured[endpoint] = data  # 同一端点多次请求取最长的一份
        elif isinstance(data, dict):
            entry["count"] = max(entry["count"], 1)
            entry["keys"] = sorted(data.keys())[:12]

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=False, viewport={"width": 1440, "height": 900}
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.on("response", on_response)
        page.on("request", on_request)
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)
        if not state.get("authorized") and not _wait_for_login(page, state):
            print("等待登录超时，未抓到数据。", file=sys.stderr)
            context.close()
            return 2
        print(f"登录完成，当前页面：{page.url}", flush=True)
        page.wait_for_timeout(6000)
        try:
            page.goto(BASE_URL + "/home", wait_until="networkidle", timeout=60000)
        except Exception:
            pass
        page.wait_for_timeout(6000)
        clicked = _walk_ui(page)
        print(f"已点击 {clicked} 个界面元素以触发接口。", flush=True)
        page.wait_for_timeout(3000)
        context.close()

    print("")
    print("接口清单：")
    for endpoint, info in sorted(summary.items()):
        print(f"  {endpoint} | code={info['code']} | {info['type']} | {info['count']} 条 | {info['keys'][:6]}")

    out_path.with_suffix(".summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if not captured:
        print("没有抓到列表型数据；接口清单已写入 .summary.json 供判断。", file=sys.stderr)
        return 3

    out_path.write_text(
        json.dumps(
            {
                "captured_at": datetime.now().isoformat(timespec="seconds"),
                "source": BASE_URL,
                "endpoints": captured,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    total = sum(len(rows) for rows in captured.values())
    print(f"抓取完成：{len(captured)} 个端点、{total} 条记录 → {out_path}")
    for endpoint, rows in captured.items():
        print(f"  {endpoint}: {len(rows)} 条")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="一次性抓取西湖电子地图数据接口")
    parser.add_argument("--out", default="raw_map_capture.json", help="输出 JSON 路径")
    args = parser.parse_args()
    return capture(Path(args.out))


if __name__ == "__main__":
    raise SystemExit(main())
