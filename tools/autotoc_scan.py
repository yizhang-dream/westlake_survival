"""One-off scan: per-page TOC sidebar / h2.section counts on local webui.

Usage: python tools/autotoc_scan.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:2018"
PAGES = [
    "program",
    "affairs",
    "vpn",
    "hpc",
    "events",
    "map",
    "shuttle",
    "dining",
    "careers",
    "capabilities",
    "scholar",
    "finance",
    "faculty",
    "news",
    "services",
    "search",
    "schools",
    "mirrors",
    "setup",
    "/",
]
SHOT_PAGES = ["program", "affairs"]
OUT_DIR = Path(r"D:\westlake_survival")

JS = """() => {
  const aside = document.querySelector('aside.toc-side');
  const title = aside ? aside.querySelector('.toc-title') : null;
  return {
    sidebar: aside ? 1 : 0,
    title: title ? (title.textContent || '').trim() : null,
    items: aside ? aside.querySelectorAll('a.toc-site').length : 0,
    groups: aside ? aside.querySelectorAll('details.toc-grp').length : 0,
    h2: document.querySelectorAll('h2.section').length,
  };
}"""


def url_of(page: str) -> str:
    return f"{BASE}/{page}" if page != "/" else f"{BASE}/"


def main() -> int:
    rows = []
    failures = []
    shots = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-proxy-server", "--proxy-bypass-list=*"],
        )
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        for name in PAGES:
            url = url_of(name)
            label = "/" if name == "/" else f"/{name}"
            try:
                resp = page.goto(url, wait_until="load", timeout=120_000)
                page.wait_for_timeout(3000)
                data = page.evaluate(JS)
                data["status"] = resp.status if resp is not None else None
                rows.append((label, data, None))
                print(
                    f"OK {label} status={data['status']} sidebar={data['sidebar']} "
                    f"items={data['items']} groups={data['groups']} h2={data['h2']} "
                    f"title={data['title']!r}",
                    flush=True,
                )
                if name in SHOT_PAGES:
                    out = OUT_DIR / f"shot_autotoc_{name}.png"
                    page.screenshot(path=str(out), full_page=True)
                    shots.append(str(out))
                    print(f"   shot -> {out}", flush=True)
            except Exception as exc:  # noqa: BLE001 - keep scanning other pages
                failures.append((label, f"{type(exc).__name__}: {exc}"))
                rows.append((label, None, f"{type(exc).__name__}: {exc}"))
                print(f"ERR {label} {type(exc).__name__}: {exc}", flush=True)

        context.close()
        browser.close()

    print()
    print("| 页面 | 侧栏 | 目录项 | 分组 | h2数 |")
    print("|---|---|---|---|---|")
    for label, data, err in rows:
        if data is None:
            print(f"| {label} | ERR | ERR | ERR | ERR |")
        else:
            print(
                f"| {label} | {data['sidebar']} | {data['items']} | "
                f"{data['groups']} | {data['h2']} |"
            )

    print()
    print("titles:", json.dumps({r[0]: (r[1] or {}).get("title") for r in rows}, ensure_ascii=False))
    print("status:", json.dumps({r[0]: (r[1] or {}).get("status") for r in rows}, ensure_ascii=False))
    if failures:
        print("failures:")
        for label, err in failures:
            print(f"  {label}: {err}")
    print("screenshots:")
    for s in shots:
        print(f"  {s}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
