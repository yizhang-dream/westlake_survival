"""全量子站清单与通用内容挖掘。

目的：把 ``*.westlake.edu.cn`` 的每一个子域都过一遍——能打开的取标题与
栏目，栏目里再抓若干条目；内网/离线站点如实标注状态。结果带 12 小时磁盘
缓存，避免每次刷新都全量打一遍。

两类使用者：

* :func:`sweep` —— 清单（host / URL / 状态 / 标题 / 是否已有人工站点配置）；
* :func:`content` —— 单个站点的栏目与条目（首页导航 + 每栏第一页）。

范围：``discovery.SERVICE_REGISTRY`` 的 92 个前缀 + CENSUS_HOSTS + 一组功能词候选
+ 证据源缓存（Wayback/滚雪球/资产收割）里的主机。只做只读 GET，不登录、不提交表单。
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor

from westlake_survival._cache import load_cached, save_cached

__all__ = [
    "candidate_hosts",
    "sweep",
    "content",
    "cached_content",
    "cli_group",
    "INVENTORY_TTL",
    "CONTENT_TTL",
]

#: 清单缓存 12 小时（子域增减不频繁）。
INVENTORY_TTL = 12 * 3600
#: 单站内容缓存 24 小时。
CONTENT_TTL = 24 * 3600

#: 常见候选名（命中即补进清单，未解析的会被标 NXDOMAIN）。
#: 2026-10-27 审计：按「校园里存在什么服务」补功能词——场馆/座位/就诊/
#: 缴费/快递/报修/洗衣/教室/考试/评教。此前只有主机名式缩写，sportvenue
#: 与 seats.library 两个真实系统因此从未进入普查（详见
#: docs/module_audit_2026-10-27.md）。
_EXTRA_CANDIDATES = (
    "library", "opac", "print", "my-sls", "mail", "webmail", "git", "wiki", "cloud",
    "course", "lms", "exam", "jw", "jwc", "yjs", "yjsy", "job", "foundation",
    "giving", "news", "video", "live", "meeting", "zoom", "teams", "ai", "api",
    "open", "status", "monitor", "dns", "ns1", "www2", "intl", "global",
    "summer", "camp", "admission", "admissions", "career2", "heqdata2",
    # 功能词（2026-10-27）
    "sport", "sports", "venue", "gym", "stadium", "swim", "fitness", "court",
    "seat", "seats", "studyroom", "classroom", "seminar", "activity", "club",
    "card", "ecard", "pay", "express", "parcel", "laundry", "repair",
    "hospital", "clinic", "health", "medical", "appointment", "vaccine",
    "cet", "ielts", "elearning", "mooc", "teach", "eval", "survey",
    "form", "flow", "approval", "sign", "doc", "docs", "disk", "storage",
    "backup", "gitlab", "jira", "ticket", "help", "helpdesk", "service",
    "campus", "life", "student", "union", "volunteer", "chem",
)

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_ANCHOR_RE = re.compile(r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")

#: 导航里常见的非栏目路径（登录、检索、下载等），挖掘时跳过。
_SKIP_PAT = re.compile(
    r"(login|logout|search|signin|signup|register|download|attachment|\.pdf$|"
    r"javascript:|mailto:|tel:|^#|rss|sitemap|/en/|language)",
    re.I,
)


def _session():
    import requests

    session = requests.Session()
    session.trust_env = False
    session.headers.update({"User-Agent": "Mozilla/5.0 Chrome/140"})
    return session


def _decode(response) -> str:
    """按响应头/内容猜测编码，返回文本。"""
    raw = getattr(response, "content", b"") or b""
    for encoding in (
        getattr(response, "encoding", None),
        "utf-8",
        "gb18030",
    ):
        if not encoding or encoding.lower() in ("iso-8859-1", "latin-1"):
            continue
        try:
            return raw.decode(encoding, errors="strict")
        except Exception:
            continue
    return raw.decode("utf-8", errors="ignore")


def candidate_hosts() -> list[str]:
    """候选子域（不含 ``.westlake.edu.cn`` 后缀的相对名）。

    三类来源合并：服务注册表（已人工确认的系统）、功能词/常见名候选、
    证据源缓存（Wayback 索引 / 滚雪球互链 / 资产收割）。第三类专门兜
    「系统存在但名字猜不到」——2026-10-27 审计的 sportvenue 即属此类。
    """
    from westlake_survival.discovery import (
        CENSUS_HOSTS,
        EVIDENCE_HOSTS,
        SERVICE_REGISTRY,
        evidence_hosts,
    )

    names = {key for key, _, _ in SERVICE_REGISTRY}
    names.update(_EXTRA_CANDIDATES)
    names.update(CENSUS_HOSTS)
    names.update(EVIDENCE_HOSTS)
    names.update(evidence_hosts())
    return sorted(names)


def _probe_one(prefix: str, session=None) -> dict:
    # 注意：requests.Session 不是线程安全的，连接池默认 10；并发探测必须
    # 每任务独立 Session，否则会在池上互相等待（实测 40 站卡住 200 秒）。
    session = session or _session()
    # 带点的是二级子域（seats.library / eer.lab / m.hpc），仍属 westlake.edu.cn；
    # 早前按「带点即完整域名」处理，把这几类一路探测到裸主机名上，全部误判 DEAD。
    host = prefix if prefix.endswith(".westlake.edu.cn") else f"{prefix}.westlake.edu.cn"
    for scheme in ("https", "http"):
        try:
            response = session.get(
                f"{scheme}://{host}/", timeout=(3, 5), allow_redirects=True, verify=False
            )
        except Exception:
            continue
        html = _decode(response)
        title = _TITLE_RE.search(html[:30000])
        return {
            "host": prefix,
            "fqdn": host,
            "url": response.url,
            "status": str(response.status_code),
            "title": _TAG_RE.sub("", title.group(1)).strip()[:80] if title else "",
        }
    return {"host": prefix, "fqdn": host, "url": "", "status": "DEAD", "title": ""}


def sweep(refresh: bool = False) -> list[dict]:
    """探测全部候选子域，返回清单（带缓存）。"""
    if not refresh:
        cached = load_cached("hosts/inventory.json", INVENTORY_TTL)
        if cached is not None:
            return cached
    import urllib3

    urllib3.disable_warnings()
    hosts = candidate_hosts()
    # 每个任务独立 Session（见 _probe_one 注释）
    with ThreadPoolExecutor(max_workers=16) as pool:
        rows = list(pool.map(lambda prefix: _probe_one(prefix), hosts))
    from westlake_survival import sites

    covered = set(sites.all_keys())
    for row in rows:
        row["sites_key"] = row["host"] in covered
        row["live"] = row["status"] not in ("DEAD", "NXDOMAIN")
    save_cached("hosts/inventory.json", rows)
    return rows


def _nav_columns(html: str, base: str, limit: int) -> list[tuple[str, str]]:
    """从首页锚点里挑栏目：同域、文字像栏目名、路径不重复。"""
    from urllib.parse import urljoin, urlparse

    seen: set[str] = set()
    columns: list[tuple[str, str]] = []
    base_host = urlparse(base).netloc
    for href, inner in _ANCHOR_RE.findall(html or ""):
        if _SKIP_PAT.search(href):
            continue
        url = urljoin(base, href)
        parsed = urlparse(url)
        if parsed.netloc and parsed.netloc != base_host:
            continue
        path = parsed.path.rstrip("/")
        if not path or path == urlparse(base).path.rstrip("/"):
            continue
        label = re.sub(r"\s+", " ", _TAG_RE.sub("", inner)).strip()
        if not (2 <= len(label) <= 18):
            continue
        if path in seen:
            continue
        seen.add(path)
        columns.append((label, url))
        if len(columns) >= limit:
            break
    return columns


def _items(html: str, base: str, limit: int = 15) -> list[dict]:
    """栏目页条目：先用站点模块的列表抽取器，再退回通用锚点。"""
    from urllib.parse import urljoin, urlparse

    from westlake_survival import sites as _sites

    try:
        extracted = _sites._extract_items(html or "", base, limit)
    except Exception:
        extracted = []
    if extracted:
        return [
            {"title": item.title, "url": item.url, "date": getattr(item, "date", "")}
            for item in extracted
        ]

    items: list[dict] = []
    seen: set[str] = set()
    base_path = urlparse(base).path.rstrip("/")
    for href, inner in _ANCHOR_RE.findall(html or ""):
        if _SKIP_PAT.search(href):
            continue
        url = urljoin(base, href)
        parsed = urlparse(url)
        if parsed.netloc and parsed.netloc != urlparse(base).netloc:
            continue
        if parsed.path.rstrip("/") == base_path:
            continue
        label = re.sub(r"\s+", " ", _TAG_RE.sub("", inner)).strip()
        if len(label) < 4:
            continue
        if url in seen:
            continue
        seen.add(url)
        items.append({"title": label[:120], "url": url})
        if len(items) >= limit:
            break
    return items


def cached_content(host: str) -> dict | None:
    """只读缓存版本的内容（页面渲染用，不在请求线程里现抓）。"""
    key = f"hosts/content_{host.replace('.', '_')}.json"
    return load_cached(key, CONTENT_TTL)


def content(host: str, refresh: bool = False, column_limit: int = 8, render: bool = False) -> dict:
    """单个站点的栏目与条目（首页导航 + 每栏第一页）。

    Args:
        render: 用无头 Chromium 渲染（JS 站；工程/医学院这类 SPA）。
            默认 requests 直取，快但拿不到前端渲染的列表。
    """
    key = f"hosts/content_{host.replace('.', '_')}.json"
    if not refresh:
        cached = load_cached(key, CONTENT_TTL)
        if cached is not None:
            return cached
    fqdn = host if "." in host else f"{host}.westlake.edu.cn"

    if render:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            render = False

    if render:
        from playwright.sync_api import sync_playwright

        columns = []
        entry = ""
        title = ""
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            try:
                page.goto(f"https://{fqdn}/", timeout=45000, wait_until="domcontentloaded")
                page.wait_for_timeout(3000)
                entry = page.url
                title = (page.title() or "")[:80]
                html = page.content()
                for label, url in _nav_columns(html, entry, column_limit):
                    try:
                        page.goto(url, timeout=30000, wait_until="domcontentloaded")
                        page.wait_for_timeout(1200)
                        items = _items(page.content(), url)
                    except Exception:
                        items = []
                    columns.append({"name": label, "url": url, "items": items})
            finally:
                context.close()
                browser.close()
        if not entry:
            return {"host": host, "url": "", "title": "", "columns": [], "error": "unreachable"}
    else:
        session = _session()
        import urllib3

        urllib3.disable_warnings()
        entry = ""
        html = ""
        for scheme in ("https", "http"):
            try:
                response = session.get(
                    f"{scheme}://{fqdn}/", timeout=(3, 6), allow_redirects=True, verify=False
                )
                entry = response.url
                html = _decode(response)
                break
            except Exception:
                continue
        if not entry:
            return {"host": host, "url": "", "title": "", "columns": [], "error": "unreachable"}
        title_match = _TITLE_RE.search(html[:30000])
        title = _TAG_RE.sub("", title_match.group(1)).strip()[:80] if title_match else ""

        columns = []
        for label, url in _nav_columns(html, entry, column_limit):
            try:
                response = session.get(url, timeout=(3, 6), allow_redirects=True, verify=False)
                page_html = _decode(response)
            except Exception:
                page_html = ""
            columns.append({"name": label, "url": url, "items": _items(page_html, url)})

    payload = {
        "host": host,
        "url": entry,
        "title": title,
        "columns": columns,
        "item_count": sum(len(column["items"]) for column in columns),
    }
    save_cached(key, payload)
    return payload


def _cli():
    import click

    @click.group(name="hosts", help="全量子站：清单探测与内容挖掘。")
    def group() -> None:
        """``westlake hosts list|mine|show``。"""

    @group.command(name="list")
    @click.option("--refresh", is_flag=True, help="忽略缓存重新探测。")
    @click.option("--limit", type=int, default=200, show_default=True)
    def list_cmd(refresh: bool, limit: int) -> None:
        """列出全部子域（状态/标题/是否已有人工站点配置）。"""
        rows = sweep(refresh=refresh)
        live = [r for r in rows if r["live"]]
        click.echo(f"子域 {len(rows)} 个：存活 {len(live)}，不可达 {len(rows) - len(live)}")
        for row in live[:limit]:
            flag = "已配置" if row.get("sites_key") else "未配置"
            click.echo(f"  {row['host']:22} {row['status']:>3} {flag}　{row['title'][:36]}")

    @group.command(name="mine")
    @click.argument("host", required=False)
    @click.option("--all", "mine_all", is_flag=True, help="挖掘所有未配置的存活站点。")
    @click.option("--refresh", is_flag=True)
    @click.option("--render", is_flag=True, help="用无头浏览器渲染（JS 站）。")
    def mine_cmd(host: str | None, mine_all: bool, refresh: bool, render: bool) -> None:
        """挖掘一个或全部站点的栏目与条目。"""
        if mine_all:
            targets = [r["host"] for r in sweep() if r["live"] and not r.get("sites_key")]
        elif host:
            targets = [host]
        else:
            raise click.UsageError("给 HOST 或 --all")
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda h: content(h, refresh=refresh, render=render), targets))
        for item in results:
            click.echo(
                f"  {item['host']:22} 栏目 {len(item.get('columns') or []):>2}"
                f" 条目 {item.get('item_count', 0):>3}　{item.get('title', '')[:30]}"
            )

    @group.command(name="show")
    @click.argument("host")
    @click.option("--refresh", is_flag=True)
    @click.option("--render", is_flag=True, help="用无头浏览器渲染（JS 站）。")
    def show_cmd(host: str, refresh: bool, render: bool) -> None:
        """显示某站点挖到的栏目与条目。"""
        data = content(host, refresh=refresh, render=render)
        click.echo(f"{data.get('title') or host}　{data.get('url', '')}")
        for column in data.get("columns") or []:
            click.echo(f"  [{column['name']}] {column['url']}")
            for item in column.get("items") or []:
                click.echo(f"    - {item['title']}　{item['url']}")

    return group


cli_group = _cli()
