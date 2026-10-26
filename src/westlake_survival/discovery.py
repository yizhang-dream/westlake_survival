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
    "archive_hosts",
    "asset_hosts",
]

logger = logging.getLogger(__name__)

TASKCENTER_BASE = "https://one.westlake.edu.cn/taskcenter"

#: 办事大厅免登录统计接口（2026-10-24 实测返回 180 个流程应用）。
APP_DIRECTORY_PATH = "/client/stats/apps?domain=westlake.edu.cn"

#: 普查候选（精选：证书日志命中 + 常见服务前缀；全量字典会拖慢 probe）。
#: 2026-10-24 大字典清扫批扩充：新命中 2dmater/aging-conference/astro/audio/
#: bioinfo/cap/car/career/mp/pan/report/storage/visitor + m./new./old. 前缀。
CENSUS_HOSTS = (
    "www sso iam idp my canvas sis lib library opac print pms map hpc mirrors "
    "finance hr oa one booking alumni international exchange mail energy iot "
    "security remotework its lab yanglab mydisk webvpn webvpn2 1x ac "
    "2dmater aging-conference astro audio bioinfo cap car career cbis "
    "mp pan report storage visitor "
    "m.hpc new.hpc old.hpc m.remotework"
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
    if not apps and not needle:
        raise ParseError("办事大厅目录为空（接口结构可能已变化）")
    return apps


def portal_services() -> list[dict]:
    """登录门户取服务大厅部门/应用目录（18 项）。

    数据源：``my.westlake.edu.cn`` 主门户 ``getSiteMap``/``getWestLakeList``
    接口。门户 API 需要 SPA 自己换到的会话（纯 requests 只拿到
    ``BOOT_1006``），所以这里用**一次性无头 Chromium**（不碰本机 Chrome、
    不复用旧 profile）：表单登录一次 → 监听接口响应 → 解析。

    Raises:
        WestlakeError: Playwright 缺失、登录失败或站点图为空。
        AuthError: 账号密码被拒。
    """
    import json as _json

    from westlake_survival.sso import read_credentials

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - 环境缺依赖
        raise WestlakeError(
            "门户站点图需要 Playwright：pip install playwright && playwright install chromium"
        ) from exc

    sid, password = read_credentials()
    captured: dict[str, str] = {}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        def grab(response):
            if "getSiteMap" in response.url or "getWestLakeList" in response.url:
                try:
                    captured[response.url] = response.text()[:200000]
                except Exception:
                    pass

        page.on("response", grab)
        try:
            page.goto("https://my.westlake.edu.cn/", timeout=60000)
            page.wait_for_timeout(3000)
            if "iam.westlake.edu.cn" in page.url:
                try:
                    page.wait_for_selector(
                        'input[placeholder*="用户名/手机号/邮箱"]', timeout=15000
                    )
                except Exception as exc:
                    raise AuthError("门户登录页未出现用户名输入框") from exc
                page.fill('input[placeholder*="用户名/手机号/邮箱"]', sid)
                page.fill('input[placeholder*="密码"]', password)
                page.locator('button.content_submit').first.click(timeout=10000)
            page.wait_for_timeout(12000)

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
            browser.close()


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
    "https://facilities.westlake.edu.cn/",
    "https://iscms.westlake.edu.cn/",
    "https://iscps.westlake.edu.cn/",
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


#: Wayback CDX 历史 URL 端点（第六种发现方法：历史索引不依赖当前链接）。
ARCHIVE_CDX_URL = (
    "http://web.archive.org/cdx/search/cdx?url=westlake.edu.cn"
    "&matchType=domain&output=text&fl=original&collapse=urlkey&limit=20000"
)


def archive_hosts(
    *, timeout: float = 30.0, session: requests.Session | None = None
) -> dict[str, int]:
    """Wayback 历史索引收割 ``*.westlake.edu.cn``（含已下线服务），带缓存。

    返回 ``{子域: 出现次数}``。2026-10-24 实测：直接访问可通（约 1.8MB、
    千级 URL）；若网络不通返回空并留缓存。CDATA 注意：该端点是 http，部分
    环境会被拦——失败时抛 :class:`WestlakeError`。
    """
    import re as _re
    from collections import Counter

    if session is None:
        # 外网站点：直连优先（2026-10-24 实测直连可通），系统代理兜底
        try:
            response = direct_session().get(ARCHIVE_CDX_URL, timeout=timeout)
            response.raise_for_status()
        except requests.RequestException:
            response = requests.get(ARCHIVE_CDX_URL, timeout=timeout)
            response.raise_for_status()
    else:
        response = session.get(ARCHIVE_CDX_URL, timeout=timeout)
        response.raise_for_status()
    counter: Counter[str] = Counter()
    for line in response.text.splitlines():
        m = _re.match(r"https?://([a-z0-9.-]+)\.westlake\.edu\.cn", line.strip(), _re.I)
        if m:
            counter[m.group(1).lower()] += 1
    from westlake_survival import _cache

    _cache.save_json("discovery/archive_hosts.json", dict(counter))
    return dict(counter)


def asset_hosts(
    hosts: list[str] | None = None,
    *,
    js_per_host: int = 12,
    timeout: float = 8.0,
) -> dict[str, list[str]]:
    """静态资产收割：抓已知站首页与其引用 JS，收集其中的 ``*.westlake.edu.cn``。

    第七种发现方法（2026-10-24 实测：对 50 个已知站收敛为零新增——用于交叉
    验证字典/滚雪球的覆盖度）。返回 ``{子域: [来源页…]}``。
    """
    import re as _re
    from urllib.parse import urljoin

    session = direct_session()
    targets = hosts or [h for h in CENSUS_HOSTS if "." not in h and h not in ("mydisk", "webvpn", "webvpn2", "1x", "ac")]
    found: dict[str, list[str]] = {}
    host_re = _re.compile(r"https?://([a-z0-9.-]+\.westlake\.edu\.cn)", _re.I)

    def _collect(url: str) -> str:
        try:
            response = session.get(url, timeout=timeout, verify=False)
        except requests.RequestException:
            return ""
        return response.text

    for host in targets:
        page = _collect(f"https://{host}.westlake.edu.cn/")
        if not page:
            continue
        for h in host_re.findall(page):
            h = h.lower()
            if h != f"{host}.westlake.edu.cn":
                found.setdefault(h, [])
                if f"{host}.westlake.edu.cn" not in found[h]:
                    found[h].append(f"{host}.westlake.edu.cn")
        scripts = _re.findall(r'src="([^"]+\.js[^"]*)"', page)[:js_per_host]
        for src in scripts:
            js_url = urljoin(f"https://{host}.westlake.edu.cn/", src)
            js = _collect(js_url)
            if not js:
                continue
            for h in host_re.findall(js):
                h = h.lower()
                if h != f"{host}.westlake.edu.cn":
                    found.setdefault(h, [])
                    if js_url not in found[h]:
                        found[h].append(js_url)
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

    @group.command(name="portal")
    def portal_cmd() -> None:
        """登录门户取服务大厅 18 项部门/应用目录（统一密码）。"""
        rows = portal_services()
        click.echo(f"门户服务目录：{len(rows)} 项")
        for item in rows:
            click.echo(f"  {item['name']}　{item['url']}")

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


#: 服务注册表（2026-10-24 盘点；全部接入：mode=接入方式）。
#: 各站 API 面测绘注记（2026-10-25 全网 bundle 常量段扫描批产出；
#: 供未来 Agent 直接知道「哪扇门存在、什么形态、为何没接」）。
SERVICE_API_NOTES: dict[str, str] = {
    "hpc": "Westlake AI 网关 https://hpc-api.westlake.edu.cn/v1（OpenAI 兼容，SSO 领令牌）；手册 /document/*；成果库 172.16.75.35:8007 未发布",
    "car": "JSON API 代理 POST /getdata.ashx（{url:/api/*,request}），匿名可达但上游要会话",
    "pan": "网盘 API 面 /api/v1/file|link、/api/qrcode（需登录）",
    "remotework": "VDI 客户端 API /v1/aUem/*（工作空间/虚拟网络/应用拉起，需登录）",
    "chatbot": "门户 AI 助手后端 /api/form/human_input 等（随门户会话）",
    "visitor": "Ant Design Pro 模板（多数 /api/* 为脚手架 mock，真接口需登录）",
    "booking": "场馆预约 SPA：/manage 壳可匿名打开，数据接口需登录",
    "my": "门户 microflow 接口 /service/<配置>/microflow/*（需会话）",
    "taskcenter": "infoplus 待办（已接 todo/doing）；其余接口走 Playwright 会话",
    "imputationserver": "Michigan 风格填补服务器（layui 应用，提交需登录）",
}


SERVICE_REGISTRY = (
    ("2dmater", "二维材料与量子输运实验室", "内容页（/sites）"),
    ("aging-conference", "衰老生物学会议站（西湖×Cell Press）", "入口卡+在线状态"),
    ("ac", "无线控制器", "入口卡+在线状态"),
    ("1x", "802.1x 网络认证（内网）", "状态卡（内网）"),
    ("alumni", "校友", "入口卡+在线状态"),
    ("astro", "天文平台（SPA）", "内容页（/sites）"),
    ("audio", "李晓飞实验室", "内容页（/sites）"),
    ("assets", "采购办公室", "内容页（/sites）"),
    ("bioinfo", "基因组学与生物信息学核心实验室", "内容页（/sites）"),
    ("brcf", "生物医学实验技术中心", "内容页（/sites）"),
    ("brcfen", "生物医学中心（英文）", "入口卡+在线状态"),
    ("cap", "人工光合作用与太阳能燃料中心", "内容页（/sites）"),
    ("car", "智能交通平台（登录）", "入口卡+在线状态"),
    ("career", "就业服务网（招聘公告/招聘会/宣讲会）", "内容页（三区块）"),
    ("cbis", "CBIS（仅证书存在）", "状态卡"),
    ("chatbot", "门户 AI 助手后端", "入口卡+在线状态"),
    ("cms", "危化品管理系统", "入口卡+在线状态"),
    ("construction", "基本建设部", "内容页（/sites）"),
    ("dq", "党群工作部", "内容页（/sites）"),
    ("en", "英文主站", "入口卡+在线状态"),
    ("en-soe", "工学院英文站", "入口卡+在线状态"),
    ("energy", "能耗监控（第三方）", "入口卡+在线状态"),
    ("eer.lab", "生态环境研究实验室（课题组站）", "内容页（/sites）"),
    ("engineering", "工学院", "内容页（五院聚合）"),
    ("eniscps", "理化平台（英文）", "入口卡+在线状态"),
    ("exchange", "邮件（→heqdata）", "入口卡+在线状态"),
    ("facilities", "实验室与科研设施部", "内容页（/sites）"),
    ("file", "办公文件共享（登录）", "入口卡+在线状态"),
    ("graduateschool", "研究生院", "内容页（/sites）"),
    ("heqdata", "数据平台", "内容页（/sites）"),
    ("hr", "人事（IAM OAuth2）", "入口卡+在线状态"),
    ("huxin", "湖心讲堂", "内容页（/sites）"),
    ("idp", "CARSI 身份提供方（Shibboleth IdP）", "入口卡+在线状态"),
    ("info", "信息技术中心（IT 服务台）", "内容页（/sites）"),
    ("international", "国际处", "内容页（/sites）"),
    ("iot", "物联网", "入口卡+在线状态"),
    ("iscms", "分子科学公共实验平台", "内容页（/sites）"),
    ("iscps", "物质科学公共实验平台", "内容页（/sites）"),
    ("isearch", "搜索（占位）", "状态卡"),
    ("its", "理论科学研究院官网", "内容页（新闻/活动）"),
    ("lab", "实验室综合管理平台", "入口卡+在线状态"),
    ("lams", "站群地图", "内容页（/sites）"),
    ("larc", "实验动物中心", "内容页（/sites）"),
    ("lifesciences", "生科院英文站", "入口卡+在线状态"),
    ("mail", "邮件", "入口卡+在线状态"),
    ("medicine", "医学院", "内容页（五院聚合）"),
    ("my", "门户/办事大厅", "统一会话"),
    ("my-soe", "工学院信息管理系统", "入口卡+在线状态"),
    ("mp", "微信平台后端（403）", "状态卡"),
    ("pan", "校园网盘（登录）", "入口卡+在线状态"),
    ("mydisk", "个人网盘（内网）", "状态卡"),
    ("nanolab", "先进微纳加工与测试平台", "内容页（/sites）"),
    ("oa", "办公自动化（→one）", "入口卡+在线状态"),
    ("oaa", "教学事务部", "入口卡+在线状态"),
    ("opac", "图书馆 OPAC（书目/借阅）", "入口卡+在线状态"),
    ("print", "自助文印（联创云打印）", "入口卡+在线状态"),
    ("oala", "审计与法务办公室", "内容页（/sites）"),
    ("officialweb-test", "官网测试站", "状态卡"),
    ("ohr", "人力资源部", "内容页（/sites）"),
    ("one", "任务中心：我的待办/进行中", "统一会话（浏览器）"),
    ("ore", "科技合作部", "内容页（/sites）"),
    ("osa", "学生事务部", "内容页（/sites）"),
    ("payment", "支付（占位）", "状态卡"),
    ("procurement", "采购门户（CMS）", "入口卡+在线状态"),
    ("report", "报表服务（Tomcat，404）", "状态卡"),
    ("qiushi", "求是西湖", "内容页（/sites）"),
    ("remotework", "远程办公", "入口卡+在线状态"),
    ("science", "理学院", "内容页（五院聚合）"),
    ("security", "保卫处", "入口卡+在线状态"),
    ("share", "大型仪器共享管理系统", "内容页（/sites）"),
    ("sls", "生命科学学院", "内容页（五院聚合）"),
    ("sso", "统一认证 CAS", "入口卡+在线状态"),
    ("storage", "对象存储（403）", "状态卡"),
    ("supply", "采购管理系统（登录）", "入口卡+在线状态"),
    ("test", "智能DNS（基础设施）", "状态卡"),
    ("testrpm", "内部测试（内网）", "状态卡（内网）"),
    ("testzh", "测试站", "状态卡"),
    ("ugadmission", "本科招生入口", "入口卡+在线状态"),
    ("ugadmissions", "本科招生网（英文）", "入口卡+在线状态"),
    ("ugapply", "本科申请系统", "入口卡+在线状态"),
    ("visitor", "访客预约系统", "入口卡+在线状态"),
    ("webvpn", "WebVPN（内网）", "状态卡"),
    ("webvpn2", "WebVPN 备用（内网）", "状态卡（内网）"),
    ("westlakefellows", "Westlake Fellows 项目", "内容页（/sites）"),
    ("wudf", "发展基金会（捐赠）", "内容页（/sites）"),
    ("www", "官网（新闻/讲座/教师/招聘/搜索）", "内容页"),
    ("yanglab", "Yang Lab 课题组站", "内容页（/sites）"),
    ("zh-ugadmissions", "本科招生网（中文）", "入口卡+在线状态"),
)
