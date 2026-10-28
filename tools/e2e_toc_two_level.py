"""端到端验证：全局自动目录两级化改造（base.html，2026-10-28 裁定）。

验证什么
========
``src/westlake_survival/webui/templates/base.html`` 尾部的全局自动目录脚本
（base.html「全局自动目录」<script> 块）在真实浏览器里渲染出的两级结构：

1. ``/program`` —— h2「专业培养方案（学分要求与课程表）」区（目录标签去掉括注后
   为「专业培养方案」）下，各培养方案 ``h3.section`` 成为二级子项；
   组内子链接数 == 页面 h3 数、href 与 h3 自动锚点一一对应。
   若培养方案数据源失败（页面 0 个方案 h3），按真实结构走条件分支并说明。
2. ``/map`` —— 每个校区「到校交通」``h3.section`` 进入目录二级
   （每校区组只有 1 个子项，渲染为「校区」顶部链接 + 1 条二级子链接）。
3. ``/sport`` 与 ``/finance`` —— 无 h2.section 页面，游离 ``details.fold``
   全部挂到「顶部」节点成为二级子项；/sport 的裸 ``<h2>我的场馆预约</h2>``
   （非 h2.section/h2.page）不得进目录。
4. ``/canvas`` —— 回归面：自动目录正常渲染、每条链接锚点有效、无 JS 报错。
   断言按真实结构写（不假定登录态：本机若存有 Canvas 令牌则是带数据态，
   否则是空态，两种态下「目录存在 + 锚点有效 + 无报错」都成立）。
5. ``/sis`` 与 ``/sites`` —— 手建目录未被接管：页面 ``aside.toc-side`` 恰好
   1 个且为手建（aria-label 学业目录/站点目录），自动目录未注入
   （无 ``aside[aria-label="页面目录"]``、无 ``at-`` 自动锚点、无第二个布局）。
6. 首页 ``/?skip=1`` —— 自动目录正常渲染（``/`` 未配置教务凭据时会 302 到
   /setup，``?skip=1`` 是 app.py 里登记的公开浏览口径，不涉及任何凭据）。

怎么验
======
* ``westlake_survival.webui.app.create_app()`` 真实应用工厂 + werkzeug
  ``make_server("127.0.0.1", 0, ...)`` 随机端口起真实 Flask 服务（同
  ``tools/webui_smoke.py``），不 mock 任何取数接缝；页面数据好坏由自身降级。
* Playwright chromium headless（``--no-proxy-server``）逐页打开（同
  ``tools/autotoc_scan.py``），在真实 DOM 上做断言并全页截图。

安全边界（铁律）
================
* 不做任何登录、不填任何凭据、不 POST 任何表单；
* 绝不请求 ``/setup/api/stored``（会回显已存密码）；
* 随机端口，不占用、不杀掉用户已运行的实例；
* 结束关闭服务与浏览器；脚本可重复运行（幂等，截图覆盖写）。

输出与退出码
============
* 每页一行 ``PASS|FAIL <path> — 原因``；
* 最后一行 ``PASS`` 或 ``FAIL``；退出码 0（全过）/ 1（有失败）；
* 截图落 ``out/toc_program.png`` 与 ``out/toc_sport.png``（全页，out/ 不存在则建）。

用法::

    python tools/e2e_toc_two_level.py

当前解释器缺依赖（包/requests/flask/playwright 任一导入失败）时，脚本会按
「仓库 .venv → PATH 上逐个 python 可执行文件」的顺序探测一个能完整导入的
解释器并 ``os.execv`` 原参数重跑自己（环境标记防循环）；探测不到才报原始
导入错误。断言逻辑与本节描述不因解释器切换而变化。
"""

from __future__ import annotations

import re
import sys
import threading
import time
from pathlib import Path
from typing import Callable

#: 截图输出目录（仓库根 out/）。
OUT_DIR = Path(__file__).resolve().parent.parent / "out"

#: 页面导航超时：/sis 24 块并行抓取慢源下可能数分钟（同 webui_smoke 的口径）。
NAV_TIMEOUTS: dict[str, int] = {"/sis": 300_000}
NAV_TIMEOUT_DEFAULT = 180_000

#: 页面渲染后的沉降等待（自动目录是 body 尾部内联脚本，load 前已执行，这里只兜动效）。
SETTLE_MS = 1500

#: 在真实 DOM 上一次性抽取自动目录结构与页面真值（口径对齐 base.html 脚本：
#: h3 排除 details.fold / .stats / .note 内的，fold 取全部）。
PROBE_JS = """() => {
  const wrap = document.querySelector('main .wrap');
  const asideInfo = a => ({
    aria: a.getAttribute('aria-label'),
    id: a.id || null,
    title: (a.querySelector('.toc-title') || {textContent: ''}).textContent.trim(),
  });
  const auto = document.querySelector('aside[aria-label="页面目录"]');
  const grpLabel = g => {
    const c = g.querySelector(':scope > summary').cloneNode(true);
    const n = c.querySelector('.n'); if (n) n.remove();
    return (c.textContent || '').trim();
  };
  const link = a => ({
    href: (a.getAttribute('href') || '').replace(/^#/, ''),
    text: (a.textContent || '').trim(),
    top: a.classList.contains('top'),
  });
  const tagOf = id => { const el = document.getElementById(id); return el ? el.tagName : null; };
  const h3s = wrap ? [...wrap.querySelectorAll('h3')]
    .filter(h => !h.closest('details.fold') && !h.closest('.stats') && !h.closest('.note'))
    .map(h => ({ id: h.id, text: (h.textContent || '').trim() })) : [];
  const folds = wrap ? [...wrap.querySelectorAll('details.fold')]
    .map(d => ({ id: d.id })) : [];
  const all = auto ? [...auto.querySelectorAll('a.toc-site')] : [];
  return {
    url: location.pathname + location.search,
    asides: [...document.querySelectorAll('aside.toc-side')].map(asideInfo),
    autoCount: document.querySelectorAll('aside[aria-label="页面目录"]').length,
    autoTitle: auto ? asideInfo(auto).title : null,
    groups: auto ? [...auto.querySelectorAll(':scope > details.toc-grp')].map(g => ({
      label: grpLabel(g),
      children: [...g.querySelectorAll(':scope > a.toc-site')].map(link),
    })) : [],
    topLinks: auto ? [...auto.querySelectorAll(':scope > a.toc-site.top')].map(link) : [],
    singleLinks: auto ? [...auto.querySelectorAll(':scope > a.toc-site:not(.top)')].map(link) : [],
    allLinks: all.map(link),
    linkTargetTags: all.map(a => tagOf((a.getAttribute('href') || '').replace(/^#/, ''))),
    h3s, folds,
    h2SectionCount: wrap ? wrap.querySelectorAll('h2.section, h2.page').length : 0,
    bareH2: wrap ? [...wrap.querySelectorAll('h2:not(.section):not(.page)')]
      .map(h => (h.textContent || '').trim()) : [],
    atIdCount: document.querySelectorAll('[id^="at-"]').length,
    layoutCount: document.querySelectorAll('.sites-layout').length,
  };
}"""

CheckFn = Callable[[dict], tuple[bool, str]]


# --------------------------------------------------------------------------- #
# 每页断言（全部基于真实 DOM 结构，数据源为空时走条件分支并在原因里说明）
# --------------------------------------------------------------------------- #

def _assert_common_auto(d: dict) -> str | None:
    """自动目录公共前提：恰好注入 1 个、标题形如「目录 · N 项」、每条锚点都存在。"""
    if d["autoCount"] != 1:
        return f"自动目录 aside 数量 {d['autoCount']} != 1"
    if not re.fullmatch(r"目录 · \d+ 项", d["autoTitle"] or ""):
        return f"目录标题异常: {d['autoTitle']!r}"
    bad = [l["href"] for l, t in zip(d["allLinks"], d["linkTargetTags"]) if t is None]
    if bad:
        return f"存在悬空锚点: {bad[:3]}"
    return None


def check_program(d: dict) -> tuple[bool, str]:
    """「专业培养方案」组下各培养方案 h3 成二级子项；0 方案时按真实结构说明。"""
    bad = _assert_common_auto(d)
    if bad:
        return False, bad
    if not any(l["text"] == "顶部" for l in d["topLinks"]):
        return False, "缺「顶部」一级入口"
    h3s = d["h3s"]
    n = len(h3s)
    grp = [g for g in d["groups"] if "培养方案" in g["label"]]
    if n == 0:
        # 数据源失败：无方案 h3，则不应有「…培养方案」分组（真实结构）
        if grp:
            return False, f"页面 0 个方案 h3 却出现分组 {[g['label'] for g in grp]}"
        return True, "数据源 0 个培养方案（条件分支）：无方案 h3，目录无该分组，结构与页面一致"
    if n >= 2:
        if len(grp) != 1:
            return False, f"期望恰好 1 个「…培养方案」分组，实际 {len(grp)} 个: {[g['label'] for g in grp]}"
        g = grp[0]
        hrefs = [c["href"] for c in g["children"]]
        if len(hrefs) != n:
            return False, f"组内二级子链接 {len(hrefs)} != 页面方案 h3 数 {n}"
        if set(hrefs) != {h["id"] for h in h3s}:
            return False, "组内子链接锚点与页面 h3 自动锚点集合不一致"
        for c, h in zip(g["children"], h3s):
            want = " ".join(h["text"].split())[:14]  # base.html h3Text 同口径截断
            if c["text"] != want:
                return False, f"子项文字不符: {c['text']!r} != {want!r}"
        return True, (f"「{g['label']}」组 {len(hrefs)} 条二级子项 == 页面 h3 数 {n}，"
                      f"锚点/文字一一对应；顶部 {len(d['topLinks'])} 条一级入口")
    # n == 1：单子项渲染为「组顶链接 + 1 条二级子链接」
    single = [l for l in d["singleLinks"] if l["href"] == h3s[0]["id"]]
    if len(single) != 1:
        return False, f"仅 1 个方案 h3 时应恰有 1 条指向它的二级子链接，实际 {len(single)}"
    return True, "仅 1 个培养方案（条件分支）：渲染为组顶链接 + 1 条二级子链接"


def check_map(d: dict) -> tuple[bool, str]:
    """「到校交通」h3 进入目录二级（每校区 1 条，锚点指向该 h3）。"""
    bad = _assert_common_auto(d)
    if bad:
        return False, bad
    traffic = [h for h in d["h3s"] if " ".join(h["text"].split()) == "到校交通"]
    if not traffic:
        return True, "地图数据源无校区交通（条件分支）：页面 0 个「到校交通」h3，目录无该项"
    links = [l for l in d["allLinks"] if l["text"] == "到校交通"]
    if len(links) != len(traffic):
        return False, f"目录「到校交通」二级子链接 {len(links)} != 页面 h3 数 {len(traffic)}"
    if any(l["top"] for l in links):
        return False, "「到校交通」不应渲染为一级（top）链接"
    if {l["href"] for l in links} != {h["id"] for h in traffic}:
        return False, "「到校交通」链接锚点与页面 h3 锚点集合不一致"
    tags = {l["href"]: t for l, t in zip(d["allLinks"], d["linkTargetTags"])}
    for l in links:
        if tags.get(l["href"]) != "H3":
            return False, f"锚点 {l['href']} 目标不是 H3（{tags.get(l['href'])}）"
    campus = [l["text"] for l in d["topLinks"] if l["text"].endswith("校区")]
    return True, (f"「到校交通」×{len(links)} 进入二级（== 页面 h3 数），锚点均为 H3；"
                  f"校区一级入口 {campus}")


def _check_top_fold_page(page: str, d: dict, exclude_label: str | None = None) -> tuple[bool, str]:
    """无 h2.section 页面：游离 details.fold 全部挂「顶部」成二级子项。"""
    bad = _assert_common_auto(d)
    if bad:
        return False, bad
    if exclude_label and any(exclude_label in (l["text"] or "") for l in d["allLinks"]):
        return False, f"裸 h2「{exclude_label}」不应出现在目录里"
    folds = d["folds"]
    f = len(folds)
    fold_ids = {x["id"] for x in folds}
    grp = [g for g in d["groups"] if g["label"] == "顶部"]
    if f >= 2:
        if len(grp) != 1:
            return False, f"期望恰好 1 个「顶部」分组，实际 {len(grp)}"
        g = grp[0]
        hrefs = [c["href"] for c in g["children"]]
        if len(hrefs) != f:
            return False, f"「顶部」组二级子项 {len(hrefs)} != 页面 details.fold 数 {f}"
        if set(hrefs) != fold_ids:
            return False, "「顶部」组子项锚点与页面 fold 锚点集合不一致"
        tags = dict(zip([l["href"] for l in d["allLinks"]], d["linkTargetTags"]))
        not_detail = [h for h in hrefs if tags.get(h) != "DETAILS"]
        if not_detail:
            return False, f"子项锚点目标不是 DETAILS 折叠块: {not_detail[:3]}"
        return True, (f"「顶部」组 {f} 条二级子项 == 页面 fold 数，锚点全部指向折叠块"
                      + (f"；裸 h2「{exclude_label}」未入目录" if exclude_label else ""))
    if f == 1:
        single = [l for l in d["singleLinks"] if l["href"] in fold_ids and not l["top"]]
        if len(single) != 1:
            return False, f"仅 1 个 fold 时应恰有 1 条指向它的二级子链接，实际 {len(single)}"
        return True, "仅 1 个折叠块（条件分支）：渲染为「顶部」+ 1 条二级子链接"
    if not any(l["text"] == "顶部" for l in d["topLinks"]):
        return False, "0 个 fold 时仍应有「顶部」一级入口"
    return True, "数据源 0 个折叠块（条件分支）：目录仅「顶部」入口"


def check_sport(d: dict) -> tuple[bool, str]:
    return _check_top_fold_page("/sport", d, exclude_label="我的场馆预约")


def check_finance(d: dict) -> tuple[bool, str]:
    return _check_top_fold_page("/finance", d)


def check_canvas(d: dict) -> tuple[bool, str]:
    """回归面：目录正常渲染、锚点有效。不假定登录态（结构无关断言）。"""
    bad = _assert_common_auto(d)
    if bad:
        return False, bad
    if not d["allLinks"]:
        return False, "自动目录没有任何链接"
    desc = (f"目录「{d['autoTitle']}」：分组 {[g['label'] + '×' + str(len(g['children'])) for g in d['groups']]}, "
            f"一级入口 {len(d['topLinks'])} 条，锚点全部有效")
    return True, desc


def _check_handbuilt(expect_aria: str) -> CheckFn:
    def check(d: dict) -> tuple[bool, str]:
        n = len(d["asides"])
        if n != 1:
            return False, f"aside.toc-side 数量 {n} != 1（手建目录应唯一）"
        a = d["asides"][0]
        if a["aria"] != expect_aria:
            return False, f"aside aria-label {a['aria']!r} != 手建的 {expect_aria!r}"
        if d["autoCount"] != 0:
            return False, f"自动目录注入了 {d['autoCount']} 个 aside（应跳过手建目录页）"
        if d["atIdCount"] != 0:
            return False, f"自动目录给页面打了 {d['atIdCount']} 个 at- 锚点（应完全未接管）"
        if d["layoutCount"] != 1:
            return False, f".sites-layout 数量 {d['layoutCount']} != 1（自动接管会再建一个）"
        return True, (f"手建目录未被接管：唯一 aside#{a['id']}（{expect_aria}，{a['title']}），"
                      "无自动注入、无 at- 锚点")
    return check


def check_home(d: dict) -> tuple[bool, str]:
    bad = _assert_common_auto(d)
    if bad:
        return False, bad
    if not any(l["text"] == "顶部" for l in d["topLinks"]):
        return False, "首页缺「顶部」一级入口"
    labels = [l["text"] for l in d["topLinks"]]
    return True, f"目录「{d['autoTitle']}」一级入口 {labels}"


# --------------------------------------------------------------------------- #
# 服务与浏览器（套路同 tools/webui_smoke.py + tools/autotoc_scan.py）
# --------------------------------------------------------------------------- #

def _reexec_with_capable_interpreter() -> None:
    """找一个能跑完本脚本导入链的解释器，原参数重跑自己；找不到则原样抛错。

    背景（2026-10-28 端到端闸门实录）：闸门可能用「裸」解释器启动本脚本
    （如 msys2 mingw python——无 requests/flask/playwright、未装本包），
    ``No module named 'requests'`` 即此因。这里不做任何安装，只换执行者：
    依次探测 仓库 .venv 与 PATH 上每个 python 可执行文件（shutil.which 只回
    第一个命中，会漏掉排在后面的可用解释器，故手动扫 PATH），用本脚本的
    完整导入面（app + playwright + werkzeug，PYTHONPATH 带 src/）做探针。
    """
    import os
    import subprocess

    if os.environ.get("WESTLAKE_E2E_REEXEC") == "1":
        return  # 已换过一次仍失败：不再循环，让原始导入错误抛出

    root = Path(__file__).resolve().parent.parent
    candidates: list[Path] = [
        root / ".venv" / "Scripts" / "python.exe",
        root / ".venv" / "bin" / "python",
    ]
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if not d:
            continue
        for name in ("python.exe", "python3.exe", "python", "python3"):
            p = Path(d) / name
            if p.is_file():
                candidates.append(p)

    env = dict(os.environ)
    env["WESTLAKE_E2E_REEXEC"] = "1"
    env["PYTHONPATH"] = str(root / "src") + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    probe = "import westlake_survival.webui.app, playwright.sync_api, werkzeug.serving"
    seen = {os.path.normcase(str(Path(sys.executable).resolve()))}
    for cand in candidates:
        try:
            if os.path.normcase(str(cand.resolve())) in seen:
                continue
            seen.add(os.path.normcase(str(cand.resolve())))
            r = subprocess.run([str(cand), "-c", probe], cwd=str(root), env=env,
                               capture_output=True, timeout=120)
        except (OSError, subprocess.SubprocessError):
            continue
        if r.returncode == 0:
            os.execve(str(cand), [str(cand), *sys.argv], env)


def _load_create_app():
    try:
        from westlake_survival.webui.app import create_app
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
        try:
            from westlake_survival.webui.app import create_app
        except ImportError:
            # 当前解释器缺依赖：换一个能完整导入的解释器重跑（断言不变）
            _reexec_with_capable_interpreter()
            raise
    return create_app


def _serve(app):
    """线程内起真实 werkzeug 服务（随机端口）；就绪只等 TCP 可连（同 webui_smoke）。"""
    import socket

    from werkzeug.serving import make_server

    server = make_server("127.0.0.1", 0, app, threaded=True)
    base = f"http://127.0.0.1:{server.server_port}"
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True).start()
    deadline = time.time() + 20.0
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", server.server_port), timeout=1.0):
                return server, base
        except OSError:
            time.sleep(0.2)
    server.shutdown()
    raise RuntimeError("服务 20s 内未监听端口")


#: (路径, 断言函数, 是否全页截图/截图名)
PAGES: list[tuple[str, CheckFn, str | None]] = [
    ("/program", check_program, "toc_program"),
    ("/map", check_map, None),
    ("/sport", check_sport, "toc_sport"),
    ("/finance", check_finance, None),
    ("/canvas", check_canvas, None),
    ("/sis", _check_handbuilt("学业目录"), None),
    ("/sites", _check_handbuilt("站点目录"), None),
    ("/?skip=1", check_home, None),
]


def main() -> int:
    import logging

    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    create_app = _load_create_app()
    app = create_app()
    server, base = _serve(app)

    results: list[tuple[str, bool, str]] = []
    js_errors: list[str] = []

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-proxy-server", "--proxy-bypass-list=*"])
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.on("console", lambda m: js_errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
        page.on("pageerror", lambda e: js_errors.append(f"pageerror: {e}"))

        try:
            for path, check, shot in PAGES:
                js_errors.clear()
                label = f"/{path.lstrip('/')}" if path.startswith("/?") else path
                try:
                    resp = page.goto(base + path, wait_until="load",
                                     timeout=NAV_TIMEOUTS.get(path, NAV_TIMEOUT_DEFAULT))
                    page.wait_for_timeout(SETTLE_MS)
                    data = page.evaluate(PROBE_JS)
                    status = resp.status if resp is not None else None
                    if status != 200:
                        results.append((label, False, f"HTTP {status}"))
                        continue
                    if js_errors:
                        results.append((label, False, f"JS 报错 {len(js_errors)} 条: {js_errors[0][:120]}"))
                        continue
                    ok, reason = check(data)
                    results.append((label, ok, reason))
                except Exception as exc:  # noqa: BLE001 — 单页失败继续验其余页
                    results.append((label, False, f"{type(exc).__name__}: {exc}"[:200]))
                finally:
                    if shot:
                        out = OUT_DIR / f"{shot}.png"
                        try:
                            page.screenshot(path=str(out), full_page=True)
                            print(f"    shot -> {out}", flush=True)
                        except Exception as exc:  # noqa: BLE001
                            print(f"    shot FAILED {out}: {exc}", flush=True)
        finally:
            context.close()
            browser.close()
            try:
                server.shutdown()
            except Exception:  # noqa: BLE001
                pass

    for label, ok, reason in results:
        print(f"{'PASS' if ok else 'FAIL'} {label} — {reason}", flush=True)
    all_ok = all(ok for _, ok, _ in results)
    print("PASS" if all_ok else "FAIL", flush=True)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
