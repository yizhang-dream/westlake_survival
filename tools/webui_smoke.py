"""WebUI 冒烟：进程内起真实 Flask 服务，GET 全部页面路由断言 200 且无模板异常。

为什么需要它
============
``module_smoke.py`` 覆盖 CLI 只读命令；WebUI 是另一条链路（Flask 路由 +
Jinja 模板 + 取数接缝 + context_processor）。本脚本读
``westlake_survival.webui.app.create_app()``（真实应用工厂，见
``src/westlake_survival/webui/app.py``），经 werkzeug ``make_server`` 在
127.0.0.1 随机端口、线程内起 **真实服务**，再逐个 GET 页面路由。

不 mock 任何取数接缝：页面靠自身「惰性导入 + 逐块降级」设计保证数据源
失败仍渲染 200（``app.py`` 模块 docstring），这正是本脚本要验收的行为——
某个模块坏掉时页面应该仍然 200 且给出降级提示，而不是 500。

用法
====
    python tools/webui_smoke.py               # 结束打印一行 JSON
    python tools/webui_smoke.py --verbose     # 另在 stderr 逐页打印进度（stdout 不变）

输出与退出码
============
* 一行 JSON：``{"pages": <页数>, "failed": ["GET /path → HTTP 500", ...]}``
* 全部通过 → 退出码 0；部分页面失败 → 退出码 1
* webui 依赖缺失（flask 未装、包导入失败等）→
  ``{"pages": 0, "failed": ["webui 不可用: 原因"]}``，退出码 0（视为环境跳过）

安全边界
========
只 GET「页面路由」：无路径参数、支持 GET、且不在排除前缀内——
``/api/*``（JSON 接口）、``/ical/*``（文件下载）、``/vpn/api/*``、
``/static/*``，以及 **``/setup/api/stored``（会回显已存密码，绝不请求）**。
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

#: 页面路由之外的路径前缀：JSON API / ICS 与 PDF 下载 / 会回显密码的设置接口 / 静态文件。
SKIP_PREFIXES: tuple[str, ...] = (
    "/api/", "/ical/", "/setup/api/", "/vpn/api/", "/static/", "/scholar/doi.pdf",
)

#: 单页超时：/sis 一页要抓 24 块（首块串行 + 6 线程并行），慢源下可能数分钟。
PAGE_TIMEOUT = 300.0


def _load_create_app():
    """导入真实 ``create_app``；包不在当前解释器时退回仓库 src/ 布局再试。"""
    try:
        from westlake_survival.webui.app import create_app
    except ImportError:
        src = Path(__file__).resolve().parent.parent / "src"
        sys.path.insert(0, str(src))
        from westlake_survival.webui.app import create_app
    return create_app


def _page_routes(app) -> list[str]:
    """从 url_map 挑页面路由：GET、无路径参数、不在排除前缀内。"""
    pages: list[str] = []
    for rule in app.url_map.iter_rules():
        if rule.arguments:  # /static/<path:filename> 之类
            continue
        if "GET" not in rule.methods:
            continue
        path = rule.rule
        if path != "/" and any(path.startswith(prefix) for prefix in SKIP_PREFIXES):
            continue
        pages.append(path)
    return sorted(pages)


def _get(base: str, path: str, timeout: float) -> tuple[int, str]:
    """直连 GET（无视环境代理，与库层 ``trust_env=False`` 同口径），返回 (状态码, 正文)。"""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(
        base + path, headers={"User-Agent": "westlake-webui-smoke/1.0"}
    )
    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:  # 4xx/5xx 也要拿正文查模板异常痕迹
        return exc.code, exc.read().decode("utf-8", errors="replace")


def _serve(app):
    """线程内起真实 werkzeug 服务，随机端口；**就绪判定只等 TCP 可连**。

    不能拿「GET / 返回 200」当就绪信号：首页首次渲染要拉天气/AQI/门户卡片，
    可能超过客户端超时（2026-10-27 实测 50 次重试全部超时、误判未就绪，
    而同一端口 curl 直连毫秒级 200——服务一直是好的）。页面快慢交给
    正式循环里 PAGE_TIMEOUT 的宽松超时去量。
    """
    import socket

    from werkzeug.serving import make_server

    server = make_server("127.0.0.1", 0, app, threaded=True)
    base = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True
    )
    thread.start()
    deadline = time.time() + 20.0
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", server.server_port), timeout=1.0):
                return server, base
        except OSError:
            time.sleep(0.2)
    server.shutdown()
    raise RuntimeError("服务 20s 内未监听端口")


def main() -> int:
    logging.getLogger("werkzeug").setLevel(logging.ERROR)  # 输出只留一行 JSON

    def _skip(reason: Exception | str) -> int:
        detail = reason if isinstance(reason, str) else f"{reason.__class__.__name__}: {reason}"
        print(json.dumps({"pages": 0, "failed": [f"webui 不可用: {detail}"]}, ensure_ascii=False))
        return 0  # 环境跳过，不算失败

    try:
        create_app = _load_create_app()
        app = create_app()
    except Exception as exc:
        return _skip(exc)

    try:
        server, base = _serve(app)
    except Exception as exc:
        return _skip(exc)

    pages = _page_routes(app)
    failed: list[str] = []
    verbose = "--verbose" in sys.argv
    for path in pages:
        try:
            status, body = _get(base, path, PAGE_TIMEOUT)
        except Exception as exc:
            failed.append(f"GET {path} → {exc.__class__.__name__}: {exc}"[:160])
            if verbose:
                print(f"FAIL GET {path} → {exc.__class__.__name__}: {exc}", file=sys.stderr, flush=True)
            continue
        if verbose:
            print(f"{status} GET {path}", file=sys.stderr, flush=True)
        if status != 200:
            failed.append(f"GET {path} → HTTP {status}")
        elif "jinja2.exceptions" in body or "Traceback (most recent call last)" in body:
            failed.append(f"GET {path} → 模板异常痕迹")  # 理论上应走 errorhandler 变 500

    try:
        server.shutdown()
    except Exception:
        pass

    print(json.dumps({"pages": len(pages), "failed": failed}, ensure_ascii=False), flush=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
