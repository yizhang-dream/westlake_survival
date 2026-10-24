"""服务发现：子域直连普查 + 办事大厅应用目录。

背景
====
2026-10-24 盘点教训（见记忆 westlake-services-probing-facts）：服务发现此前全靠
任务驱动，从未做过系统清点。本模块把两套清点方法固化：

1. :func:`subdomain_census`：候选子域**直连**探测。必须显式绕过系统代理
   （用户本机代理不吃内网路由，走代理会把可达服务误判成 502/超时）。
   校园 DNS 对任意子域有通配兜底（返回 502 占位），因此判据是「响应码非 502」。
2. :func:`app_directory`：任务中心（网上办事大厅）的**免登录**统计接口，
   返回全校 180 个流程应用——官方注册表，比子域扫描更权威。

两个入口都供 ``westlake probe scan`` 与 WebUI 使用。
"""

from __future__ import annotations

import json
import logging
import re
import ssl
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import requests
import urllib3
from requests.adapters import HTTPAdapter

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from westlake_survival._cache import http_get_with_etag
from westlake_survival._net import DEFAULT_TIMEOUT, http_session
from westlake_survival.exceptions import ParseError, WestlakeError

__all__ = [
    "TASKCENTER_BASE",
    "cli_group",
    "APP_DIRECTORY_PATH",
    "CENSUS_HOSTS",
    "HostProbe",
    "AppEntry",
    "direct_session",
    "subdomain_census",
    "app_directory",
    "snowball_hosts",
    "portal_services",
]

logger = logging.getLogger(__name__)

TASKCENTER_BASE = "https://one.westlake.edu.cn/taskcenter"

#: 办事大厅免登录统计接口（2026-10-24 实测返回 180 个流程应用）。
APP_DIRECTORY_PATH = "/client/stats/apps?domain=westlake.edu.cn"

#: 普查候选（精选：证书日志命中 + 常见服务前缀；全量字典会拖慢 probe）。
CENSUS_HOSTS = (
    "www sso iam my canvas sis lib library opac print pms map hpc mirrors "
    "finance hr oa one booking alumni international exchange mail energy iot "
    "security remotework its lab yanglab mydisk webvpn webvpn2"
).split()


def direct_session() -> requests.Session:
    """不走系统代理的 Session（内网服务直连；证书宽松以覆盖自签场景）。"""
    session = requests.Session()
    session.trust_env = False  # 关键：无视 HTTP(S)_PROXY
    adapter = HTTPAdapter(max_retries=0)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers["User-Agent"] = "Mozilla/5.0 (westlake-survival probe)"
    return session


@dataclass
class HostProbe:
    """一个子域的探测结果。"""

    host: str
    status: int
    title: str = ""
    final_url: str = ""

    @property
    def alive(self) -> bool:
        """是否为活服务（校园 DNS 通配 502 占位不算）。"""
        return self.status not in (0, 502)


@dataclass
class AppEntry:
    """办事大厅的一个流程应用。"""

    name: str
    department: str = ""
    description: str = ""
    uri: str = ""
    app_id: str = ""


def _title_of(body: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", body, re.I | re.S)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()[:60]


def subdomain_census(
    hosts: list[str] | None = None,
    *,
    timeout: float = 6.0,
    workers: int = 12,
    session: requests.Session | None = None,
) -> list[HostProbe]:
    """直连探测候选子域，返回全部结果（含不可达，alive 字段区分）。"""
    session = session if session is not None else direct_session()
    targets = hosts or list(CENSUS_HOSTS)

    def _one(host: str) -> HostProbe:
        url = f"https://{host}.westlake.edu.cn/"
        try:
            response = session.get(url, timeout=timeout, allow_redirects=True, verify=False)
            body = response.content[:4000].decode(
                response.apparent_encoding or "utf-8", errors="replace"
            )
            return HostProbe(
                host=host,
                status=response.status_code,
                title=_title_of(body),
                final_url=response.url[:90],
            )
        except requests.HTTPError as exc:
            code = getattr(exc.response, "status_code", 0) or 0
            return HostProbe(host=host, status=code)
        except requests.RequestException:
            return HostProbe(host=host, status=0)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(_one, targets))


def app_directory(
    keyword: str | None = None,
    *,
    refresh: bool = False,
    timeout: float | None = None,
) -> list[AppEntry]:
    """拉取办事大厅应用目录（免登录），可按名称/部门子串过滤。

    Raises:
        WestlakeError: 网络失败。
        ParseError: 接口返回结构异常。
    """
    url = TASKCENTER_BASE + APP_DIRECTORY_PATH
    if refresh:
        from westlake_survival import _cache

        path = _cache.cache_path("discovery/app_directory.json")
        if path.exists():
            path.unlink()
    try:
        body, _etag = http_get_with_etag(
            url,
            cache_name="discovery/app_directory.json",
            session=direct_session(),
            timeout=timeout if timeout is not None else DEFAULT_TIMEOUT,
        )
    except requests.HTTPError as exc:
        raise WestlakeError(f"办事大厅目录请求失败：HTTP {getattr(exc.response, 'status_code', '?')}") from exc
    except requests.Timeout as exc:
        raise WestlakeError("办事大厅目录请求超时") from exc
    except requests.RequestException as exc:
        raise WestlakeError(f"办事大厅目录请求失败：{exc}") from exc
    try:
        payload = json.loads(body if isinstance(body, str) else body.decode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise ParseError("办事大厅目录返回非 JSON") from exc
    entities = payload.get("entities") if isinstance(payload, dict) else None
    if not isinstance(entities, list):
        raise ParseError("办事大厅目录缺少 entities 数组")
    apps: list[AppEntry] = []
    needle = (keyword or "").strip().casefold()
    for item in entities:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name or name.startswith("测试"):
            continue
        department = str(item.get("department") or "").strip()
        if needle and needle not in name.casefold() and needle not in department.casefold():
            continue
        apps.append(
            AppEntry(
                name=name,
                department=department,
                description=str(item.get("description") or "").strip()[:120],
                uri=str(item.get("uri") or "").strip(),
                app_id=str(item.get("id") or ""),
            )
        )
    if not apps:
        raise ParseError("办事大厅目录为空（接口结构可能已变化）")
    return apps


def portal_services() -> list[dict]:
    """登录门户（统一会话浏览器）取服务大厅部门/应用目录。

    数据源：``my.westlake.edu.cn`` 主门户 ``getSiteMap``/``getWestLakeList``
    接口（2026-10-24 实测 18 项，含 9 个此前未知的部门域名）。需要
    Playwright 与已配置的统一凭据；会话持久化在 taskcenter profile。

    Raises:
        WestlakeError: Playwright 缺失或网络失败。
        AuthError: 登录失败。
    """
    import json as _json
    import re as _re
    from westlake_survival.sso import read_credentials
    from westlake_survival.taskcenter import PROFILE_DIR, _browser, _ensure_session, _fetch_api

    sid, password = read_credentials()
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with _browser() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=True, viewport={"width": 1280, "height": 800}
        )
        page = context.pages[0] if context.pages else context.new_page()
        captured: dict[str, str] = {}

        def grab(response):
            if "getSiteMap" in response.url or "getWestLakeList" in response.url:
                try:
                    captured[response.url.split("get")[-1]] = response.text()[:200000]
                except Exception:
                    pass

        page.on("response", grab)
        try:
            page.goto("https://my.westlake.edu.cn/", timeout=60000)
            page.wait_for_timeout(3000)
            # 门户是独立 OAuth client；复用 IAM 会话可能直接过，否则填表一次
            if "iam.westlake.edu.cn" in page.url:
                page.wait_for_selector('input[placeholder*="用户名/手机号/邮箱"]', timeout=15000)
                page.fill('input[placeholder*="用户名/手机号/邮箱"]', sid)
                page.fill('input[placeholder*="密码"]', password)
                page.locator('span:has-text("立即登录")').first.click(force=True)
            page.wait_for_timeout(10000)
            rows: list[dict] = []
            for body in captured.values():
                try:
                    for item in _json.loads(body).get("data", {}).get("content") or []:
                        name = str(item.get("yingyongmingcheng") or "").strip()
                        url = str(item.get("tiaozhuanurl") or "").strip()
                        if name and url and not any(name == r["name"] for r in rows):
                            rows.append({"name": name, "url": url})
                except (ValueError, AttributeError):
                    continue
            if not rows:
                raise WestlakeError("门户站点图为空（接口结构可能已变化）")
            return rows
        finally:
            context.close()


# --------------------------------------------------------------------------- #
# 常用入口（实测 2026-10-24）
# --------------------------------------------------------------------------- #
HPC_PORTAL = "https://hpc.westlake.edu.cn:9002/login.html"
HPC_MAIN = "https://hpc.westlake.edu.cn/"
BOOKING_URL = "https://booking.westlake.edu.cn/yy-sys/"
MIRRORS_URL = "https://mirrors.westlake.edu.cn/posts/mirrors.html"


def _handle_errors(func):
    import functools

    import click

    from westlake_survival.exceptions import WestlakeError

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except WestlakeError as exc:
            click.secho(f"错误：{exc}", fg="red", err=True)
            raise SystemExit(1) from exc

    return wrapper


#: 滚雪球种子（已知高价值入口；两轮收割实测收敛）。
SNOWBALL_SEEDS = (
    "https://www.westlake.edu.cn/",
    "https://science.westlake.edu.cn/",
    "https://sls.westlake.edu.cn/About/",
    "https://engineering.westlake.edu.cn/",
    "https://medicine.westlake.edu.cn/About/",
    "https://its.westlake.edu.cn/",
    "https://my.westlake.edu.cn/",
    "https://one.westlake.edu.cn/taskcenter/home",
    "https://hpc.westlake.edu.cn/",
    "https://finance.westlake.edu.cn/",
    "https://international.westlake.edu.cn/",
    "https://alumni.westlake.edu.cn/",
    "https://security.westlake.edu.cn/",
    "https://remotework.westlake.edu.cn/portal/",
    "https://zh-ugadmissions.westlake.edu.cn/",
    "https://info.westlake.edu.cn/",
)


def snowball_hosts(
    rounds: int = 2,
    *,
    session: requests.Session | None = None,
    timeout: float = 8.0,
) -> dict[str, list[str]]:
    """滚雪球链接收割：从种子页收集 ``*.westlake.edu.cn`` 域名，迭代轮次。

    比子域字典更能发现「按机构组织」的站点（学院、党群、基金会、讲堂等
    常只在彼此的页脚互链）。返回 ``{域名: [来源页…]}``。
    """
    import re as _re
    from urllib.parse import urlparse

    session = session if session is not None else direct_session()
    found: dict[str, list[str]] = {}
    queue = [urlparse(u).geturl() for u in SNOWBALL_SEEDS]
    visited: set[str] = set()
    for _round in range(max(1, rounds)):
        next_queue: list[str] = []
        for url in queue:
            if url in visited:
                continue
            visited.add(url)
            try:
                response = session.get(url, timeout=timeout, verify=False)
            except requests.RequestException:
                continue
            body = response.content[:200000].decode("utf-8", errors="replace")
            for host in _re.findall(r"https?://([a-z0-9-]+)\.westlake\.edu\.cn", body):
                found.setdefault(host, [])
                if url not in found[host]:
                    found[host].append(url)
            # 新域名首页作为下一轮种子
            for host in _re.findall(r"https?://([a-z0-9-]+)\.westlake\.edu\.cn", body):
                candidate = f"https://{host}.westlake.edu.cn/"
                if candidate not in visited and host not in ("payment", "isearch"):
                    next_queue.append(candidate)
        queue = next_queue[:24]  # 控制规模
    return found


def _cli():
    import click

    @click.group(name="affairs", help="网上办事大厅与计算/预约入口（目录免登录）。")
    def group() -> None:
        """``westlake affairs apps|links``。"""

    @group.command(name="apps")
    @click.argument("keyword", required=False)
    @click.option("--limit", type=int, default=30, show_default=True, help="最多显示条数。")
    @click.option("--refresh", is_flag=True, help="忽略缓存重新拉取。")
    def apps_cmd(keyword: str | None, limit: int, refresh: bool) -> None:
        """办事大厅流程应用目录（176 个），KEYWORD 按名称/部门过滤。"""
        items = app_directory(keyword, refresh=refresh)
        click.echo(f"办事大厅应用目录：{len(items)} 条" + (f"（关键词 {keyword!r}）" if keyword else ""))
        for item in items[: max(0, limit)]:
            dept = f"　[{item.department}]" if item.department else ""
            click.echo(f"  {item.name}{dept}")

    @group.command(name="links")
    def links_cmd() -> None:
        """常用服务入口直达（HPC / 预约中心 / 镜像站，直连实测）。"""
        from westlake_survival.discovery import direct_session

        click.echo("常用入口：")
        for name, url in (
            ("HPC 门户（统一密码登录）", HPC_PORTAL),
            ("HPC 官网（集群/队列/手册）", HPC_MAIN),
            ("预约中心", BOOKING_URL),
            ("开源镜像站", MIRRORS_URL),
        ):
            note = ""
            try:
                response = direct_session().get(url, timeout=8, verify=False)
                note = f"（实测 {response.status_code}）"
            except Exception:
                note = "（当前直连不可达）"
            click.echo(f"  {name}：{url} {note}")

    return group


cli_group = _cli()
