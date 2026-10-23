"""一次性抓取西湖电子地图的数据接口（人工登录，密码不经手）。

为什么是这个形态
================
地图数据接口全部要令牌（匿名 ``10031``），但数据本身与账号无关。所以只需要
**任意一位有账号的人成功登录一次**，把接口响应固化下来随包发布；其他用户
不需要账号。

本脚本打开**有头浏览器**，由你本人在窗口里输入账号密码（脚本不读、不存、
不打印），登录完成后自动遍历页面并把所有 ``/api/nsc/**`` 响应存成 JSON。

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

#: 登录成功判据：URL 离开 /login 且出现令牌类存储键。
LOGIN_TIMEOUT_S = 600


def _wait_for_login(page) -> bool:
    """等用户在浏览器里完成登录。"""
    deadline = time.time() + LOGIN_TIMEOUT_S
    print("请在弹出的浏览器窗口里登录（账号密码只有你自己看到），等待中…", flush=True)
    while time.time() < deadline:
        if "/login" not in page.url:
            time.sleep(3)  # 让首屏接口先跑
            return True
        page.wait_for_timeout(1000)
    return False


def _walk_ui(page) -> None:
    """尽量触发各数据接口：滚动、点击可见菜单/列表项。"""
    page.wait_for_timeout(3000)
    for _ in range(3):
        page.mouse.wheel(0, 1200)
        page.wait_for_timeout(800)
    selectors = [
        ".el-menu-item", ".menu-item", "li[class*=menu]", "div[class*=tree-node]",
        "div[class*=list-item]", "span[class*=title]",
    ]
    clicked = 0
    for selector in selectors:
        try:
            items = page.query_selector_all(selector)
        except Exception:
            continue
        for item in items[:8]:
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

    def on_response(response):
        url = response.url
        if "/api/nsc/" not in url:
            return
        try:
            payload = response.json()
        except Exception:
            return
        if not isinstance(payload, dict) or payload.get("code") not in ("10000", 0, "0", 200, "200"):
            return
        data = payload.get("data")
        endpoint = url.split("map.westlake.edu.cn", 1)[-1].split("?", 1)[0]
        raw_log.append({"endpoint": endpoint, "code": payload.get("code")})
        if isinstance(data, list) and data and isinstance(data[0], dict):
            bucket = captured.setdefault(endpoint, [])
            if len(data) > len(bucket):
                captured[endpoint] = data  # 同一端点多次请求取最长的一份

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.on("response", on_response)
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60000)
        if not _wait_for_login(page):
            print("等待登录超时，未抓到数据。", file=sys.stderr)
            browser.close()
            return 2
        print(f"登录完成，当前页面：{page.url}", flush=True)
        _walk_ui(page)
        page.wait_for_timeout(2000)
        browser.close()

    if not captured:
        print("没有抓到任何列表型数据（可能页面结构变化或需要更多点击）。", file=sys.stderr)
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
