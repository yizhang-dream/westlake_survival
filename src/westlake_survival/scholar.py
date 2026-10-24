"""学术资源访问层：订阅数据库注册表 + CARSI 联盟登录 + DOI 全文获取。

背景与实测（2026-10-24）
========================

西湖大学是 **CARSI 联盟成员**：``idp.westlake.edu.cn`` 是标准 Shibboleth
IdP（``/idp/shibboleth`` 元数据 200），在 CARSI 高校名单与 CNKI 联盟名单
（fsso.cnki.net，1072 所）均可见。IdP 登录页会跳 IAM 统一认证
（``/ac/#/index?lck=context_CAS_…&entityId=https://idp.westlake.edu.cn``），
即**统一密码通吃数据库登录**；但 IAM 在失败计数后会要求图形验证码
（账号级、跨 entityId，canvas 同样触发），纯 headless 密码登录不可依赖——
因此 SSO 走 Playwright 持久化 profile（用户看一次验证码，之后 IdP 会话
自动续，与 taskcenter 同一套路）。

访问矩阵（两条通道）：

* **校园网/VPN 内：出版社按 IP 认账**——ScienceDirect 首页实测显示
  "Westlake University"，Springer ``content/pdf/<doi>.pdf`` 直下实测
  200 / application/pdf。Agent 拿全文的主通道是 DOI → 出版社页面 →
  ``citation_pdf_url`` 元标签 → 直下。
* **校外：CARSI 联盟 SSO**——各库入口跳本校 IdP；CNKI 的入口是
  ``fsso.cnki.net/Shibboleth.sso/Login?entityID=<本校IdP>&target=…``
  （实测全链路 302 通到 IAM 登录页）。

数据来源：CARSI 官网 SPlist（356 个资源，随包快照 ``data/carsi_sps.json``，
可 ``--refresh`` 在线更新）；CrossRef / OpenAlex 公共 API 做文献元数据与
OA 副本定位。
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, urljoin

from westlake_survival._cache import load_json, save_json
from westlake_survival._net import DEFAULT_TIMEOUT, http_session
from westlake_survival.exceptions import AuthError, WestlakeError

__all__ = [
    "IDP_ENTITY_ID",
    "Database",
    "CampusStatus",
    "Paper",
    "databases",
    "campus_status",
    "carsi_catalog",
    "carsi_sso_entry",
    "resolve_doi",
    "fetch_pdf",
    "sso_status",
    "sso_browser",
    "cli_group",
]

logger = logging.getLogger(__name__)

#: 本校在 CARSI 联盟的 Shibboleth IdP entityID（元数据实测）。
IDP_ENTITY_ID = "https://idp.westlake.edu.cn/idp/shibboleth"

#: 校园网判定信标：Elsevier 首页对校园 IP 显示机构名（2026-10-24 实测）。
CAMPUS_BEACON_URL = "https://www.sciencedirect.com"
CAMPUS_BEACON_MARK = "Westlake University"

#: CARSI 服务目录页（内联 ``var SPList=[...]``，356 条）。
CARSI_SPLIST_URL = "https://www.carsi.edu.cn/SPlist.html"

#: 随包的 CARSI 目录快照（公开目录数据，来源见文件内 source 字段）。
_CARSI_FIXTURE = Path(__file__).parent / "data" / "carsi_sps.json"

#: SSO 持久化浏览器 profile（IdP/IAM 会话跨命令复用）。
PROFILE_DIR = Path.home() / ".westlake_survival" / "scholar_profile"


# --------------------------------------------------------------------------- #
# 数据库注册表
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Database:
    """一个学术资源入口。

    :attr:`access` 为主通道：``campus``（校园网/VPN 内 IP 认证）、
    ``carsi``（联盟 SSO，校外可用）、``open``（公开免费）、
    ``account``（独立账号体系）。
    """

    key: str
    name: str
    url: str
    category: str
    access: str = "campus"
    vendor: str = ""
    note: str = ""


#: 精选核心库（覆盖中西文全文/索引/事实库/数据平台/开放获取）。
#: access 标主通道；CARSI 是否覆盖某库以 ``carsi_catalog`` 实查为准。
DATABASES: tuple[Database, ...] = (
    Database("cnki", "中国知网", "https://kns.cnki.net", "中文全文", "carsi",
             "同方知网", "校外走 fsso.cnki.net 联盟登录（实测认本校 IdP）；主站有滑块验证"),
    Database("wanfang", "万方数据", "https://www.wanfangdata.com.cn", "中文全文", "carsi",
             "万方", "学位论文/中文期刊"),
    Database("cqvip", "维普中文期刊服务平台", "https://www.cqvip.com", "中文全文", "carsi",
             "维普", ""),
    Database("ncpssd", "国家哲学社会科学文献中心", "https://www.ncpssd.cn", "中文全文", "open",
             "", "免费注册即用"),
    Database("wos", "Web of Science", "https://www.webofscience.com", "引文索引", "carsi",
             "Clarivate", ""),
    Database("scopus", "Scopus", "https://www.scopus.com", "引文索引", "campus",
             "Elsevier", ""),
    Database("sciencedirect", "ScienceDirect", "https://www.sciencedirect.com", "外文全文",
             "campus", "Elsevier", "校园 IP 实测自动认证（首页显示 Westlake University）"),
    Database("springer", "SpringerLink", "https://link.springer.com", "外文全文", "campus",
             "Springer Nature", "content/pdf/<doi>.pdf 校园直下实测 200"),
    Database("nature", "Nature 系列", "https://www.nature.com", "外文全文", "campus",
             "Springer Nature", ""),
    Database("wiley", "Wiley Online Library", "https://onlinelibrary.wiley.com", "外文全文",
             "campus", "Wiley", ""),
    Database("ieee", "IEEE Xplore", "https://ieeexplore.ieee.org", "外文全文", "carsi",
             "IEEE", "IEEE/IET Electronic Library"),
    Database("acs", "ACS Publications", "https://pubs.acs.org", "外文全文", "campus",
             "美国化学学会", ""),
    Database("aps", "APS（Physical Review）", "https://journals.aps.org", "外文全文", "campus",
             "美国物理学会", ""),
    Database("iop", "IOPscience", "https://iopscience.iop.org", "外文全文", "campus",
             "英国物理学会", ""),
    Database("tandf", "Taylor & Francis Online", "https://www.tandfonline.com", "外文全文",
             "campus", "Taylor & Francis", ""),
    Database("siam", "SIAM", "https://epubs.siam.org", "外文全文", "campus",
             "工业与应用数学学会", ""),
    Database("jstor", "JSTOR", "https://www.jstor.org", "外文全文", "campus", "ITHAKA", ""),
    Database("ebsco", "EBSCOhost", "https://search.ebscohost.com", "外文全文", "carsi",
             "EBSCO", ""),
    Database("proquest", "ProQuest", "https://www.proquest.com", "外文全文", "carsi",
             "ProQuest", "学位论文数据库 PQDT 也在此平台"),
    Database("scifinder", "CAS SciFinder", "https://scifinder-n.cas.org", "化学事实", "account",
             "CAS", "需先在本校注册 CAS 账号并关联机构"),
    Database("reaxys", "Reaxys", "https://www.reaxys.com", "化学事实", "campus",
             "Elsevier", ""),
    Database("heqdata", "西湖大学数据平台", "https://heqdata.westlake.edu.cn", "数据平台",
             "account", "学校自建", "独立登录体系；机构数据管理与共享"),
    Database("pubmed", "PubMed", "https://pubmed.ncbi.nlm.nih.gov", "开放索引", "open",
             "NLM", "题录免费；全文跳出版社按上文通道判定"),
    Database("openalex", "OpenAlex", "https://openalex.org", "开放索引", "open", "",
             "本文献元数据/OA 定位用的公共 API 即此"),
    Database("arxiv", "arXiv", "https://arxiv.org", "开放预印本", "open", "", ""),
)


def databases(query: str | None = None) -> list[Database]:
    """注册表（可按名称/类别/厂商子串过滤）。"""
    if not query:
        return list(DATABASES)
    q = query.lower()
    return [
        db for db in DATABASES
        if q in db.name.lower() or q in db.category.lower()
        or q in db.vendor.lower() or q in db.key
    ]


# --------------------------------------------------------------------------- #
# 校园网 IP 认证状态
# --------------------------------------------------------------------------- #
@dataclass
class CampusStatus:
    """当前出口 IP 是否被出版社认作校园网。"""

    ip_authorized: bool
    checked_at: str = ""
    evidence: str = ""

    def to_dict(self) -> dict:
        return {
            "ip_authorized": self.ip_authorized,
            "checked_at": self.checked_at,
            "evidence": self.evidence,
        }


def _direct_session(**kw) -> "requests.Session":
    """直连会话：本机代理不吃校方路由（2026-10-24 实测盘点结论）。"""
    session = http_session(**kw)
    session.trust_env = False
    session.headers["User-Agent"] = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "Chrome/126.0 Safari/537.36"
    )
    return session


def campus_status(refresh: bool = False) -> CampusStatus:
    """探测出版社是否认当前 IP（信标：ScienceDirect 首页机构名）。

    结果缓存 30 分钟（键 ``scholar/campus_status.json``）；网络失败给
    ``ip_authorized=False`` 并在 evidence 里说明探测失败（区别于「确认不在
    校园网」）。
    """
    cache = "scholar/campus_status.json"
    if not refresh:
        cached = load_json(cache)
        if cached and time.time() - cached.get("ts", 0) < 1800:
            return CampusStatus(
                cached.get("ip_authorized", False),
                checked_at=cached.get("checked_at", ""),
                evidence=cached.get("evidence", ""),
            )
    try:
        response = _direct_session().get(CAMPUS_BEACON_URL, timeout=DEFAULT_TIMEOUT)
        ok = CAMPUS_BEACON_MARK in response.text
        evidence = (
            f"信标 {CAMPUS_BEACON_URL} HTTP {response.status_code}，"
            f"机构名「{CAMPUS_BEACON_MARK}」{'命中' if ok else '未出现'}"
        )
    except Exception as exc:  # 探测失败≠不在校园网，如实说明
        ok = False
        evidence = f"信标探测失败：{exc.__class__.__name__}"
    status = CampusStatus(
        ip_authorized=ok,
        checked_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        evidence=evidence,
    )
    save_json(cache, {"ts": time.time(), **status.to_dict()})
    return status


# --------------------------------------------------------------------------- #
# CARSI 联盟目录
# --------------------------------------------------------------------------- #
def _load_carsi_fixture() -> list[dict]:
    if not _CARSI_FIXTURE.exists():
        return []
    try:
        payload = json.loads(_CARSI_FIXTURE.read_text(encoding="utf-8"))
    except ValueError:
        return []
    sps = payload.get("sps") if isinstance(payload, dict) else payload
    return sps if isinstance(sps, list) else []


def carsi_catalog(query: str | None = None, refresh: bool = False) -> list[dict]:
    """CARSI 联盟资源目录（356 个 SP，来源 www.carsi.edu.cn/SPlist.html）。

    随包快照离线可用；``refresh=True`` 在线更新并写缓存
    ``scholar/carsi_sps.json``。条目字段：``production``（资源名）、
    ``vendor_name``、``url``、``searchStr``。
    """
    sps: list[dict] = []
    if refresh:
        try:
            response = _direct_session().get(CARSI_SPLIST_URL, timeout=30.0)
            match = re.search(r"var\s+SPList\s*=\s*(\[.*?\])\s*;", response.text, re.S)
            if not match:
                raise WestlakeError("CARSI SPlist 页未找到 SPList 数组——页面结构可能变化")
            sps = json.loads(match.group(1))
            save_json("scholar/carsi_sps.json", sps)
        except WestlakeError:
            raise
        except Exception as exc:
            raise WestlakeError(f"CARSI 目录在线更新失败：{exc.__class__.__name__}") from exc
    if not sps:
        cached = load_json("scholar/carsi_sps.json")
        if isinstance(cached, list) and cached:
            sps = cached
        else:
            sps = _load_carsi_fixture()
    if not sps:
        raise WestlakeError("CARSI 目录不可用：随包快照缺失且未在线更新过")
    if not query:
        return sps
    q = query.lower()
    return [
        s for s in sps
        if q in str(s.get("production") or "").lower()
        or q in str(s.get("vendor_name") or "").lower()
        or q in str(s.get("searchStr") or "").lower()
    ]


def carsi_sso_entry(target: str = "cnki", return_url: str | None = None) -> str:
    """构造某数据库「校外 CARSI 联盟登录」入口 URL。

    ``target`` 是注册表 key（v1 实测支持 ``cnki``）或任意 https URL；
    通用 Shibboleth SP 的入口是 ``<SP>/Shibboleth.sso/Login?entityID=<本校IdP>``。
    """
    if target.startswith("https://"):
        from urllib.parse import urlparse

        parts = urlparse(target)
        entry = (
            f"{parts.scheme}://{parts.netloc}"
            f"/Shibboleth.sso/Login?entityID={quote(IDP_ENTITY_ID, safe='')}"
        )
        if return_url:
            entry += f"&target={quote(return_url, safe='')}"
        return entry
    if target == "cnki":
        # fsso.cnki.net 是知网的 CARSI 专用集群（login2.js 实测拼法）。
        ret = return_url or "https://fsso.cnki.net/secure/default.aspx"
        return (
            "https://fsso.cnki.net/Shibboleth.sso/Login"
            f"?entityID={quote(IDP_ENTITY_ID, safe='')}&target={quote(ret, safe='')}"
        )
    db = next((d for d in DATABASES if d.key == target), None)
    if db and db.url.startswith("https://"):
        return carsi_sso_entry(db.url, return_url)
    raise WestlakeError(f"未知的数据库标识：{target}（可用 keys 见 databases()）")


# --------------------------------------------------------------------------- #
# DOI → 元数据 + 全文
# --------------------------------------------------------------------------- #
@dataclass
class Paper:
    """一篇文献的解析结果：元数据 + 各通道全文线索。"""

    doi: str = ""
    title: str = ""
    authors: list[str] = field(default_factory=list)
    journal: str = ""
    year: str = ""
    publisher: str = ""
    doi_url: str = ""
    oa_pdf_url: str = ""
    publisher_pdf_url: str = ""
    campus_hint: str = ""

    def to_dict(self) -> dict:
        return {
            "doi": self.doi,
            "title": self.title,
            "authors": self.authors,
            "journal": self.journal,
            "year": self.year,
            "publisher": self.publisher,
            "doi_url": self.doi_url,
            "oa_pdf_url": self.oa_pdf_url,
            "publisher_pdf_url": self.publisher_pdf_url,
            "campus_hint": self.campus_hint,
        }


def normalize_doi(doi: str) -> str:
    """剥掉 doi.org/ doi: 前缀与空白，只留 DOI 本体。"""
    text = doi.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/",
                   "http://dx.doi.org/", "doi.org/", "doi:", "DOI:"):
        if text.lower().startswith(prefix.lower()):
            text = text[len(prefix):].strip()
    return text


def resolve_doi(doi: str, *, with_pdf_url: bool = True) -> Paper:
    """解析 DOI：CrossRef 元数据 + OpenAlex OA 副本 + 出版社 citation_pdf_url。

    Raises:
        WestlakeError: DOI 格式为空或元数据完全取不到。
    """
    clean = normalize_doi(doi)
    if not clean or "/" not in clean:
        raise WestlakeError(f"不是有效的 DOI：{doi!r}")
    paper = Paper(doi=clean, doi_url=f"https://doi.org/{clean}")
    session = _direct_session()

    meta_error: list[str] = []
    try:  # CrossRef：题录权威来源
        r = session.get(f"https://api.crossref.org/works/{quote(clean, safe='')}",
                        timeout=DEFAULT_TIMEOUT)
        if r.status_code == 200:
            msg = (r.json().get("message") or {})
            paper.title = " ".join(msg.get("title") or []) or paper.title
            paper.journal = " ".join(msg.get("container-title") or [])
            paper.publisher = msg.get("publisher") or ""
            authors = msg.get("author") or []
            paper.authors = [
                f"{a.get('given', '').strip()} {a.get('family', '').strip()}".strip()
                for a in authors if (a.get("family") or a.get("given"))
            ]
            issued = (msg.get("issued") or {}).get("date-parts") or []
            if issued and issued[0]:
                paper.year = str(issued[0][0])
        else:
            meta_error.append(f"CrossRef HTTP {r.status_code}")
    except Exception as exc:
        meta_error.append(f"CrossRef {exc.__class__.__name__}")

    try:  # OpenAlex：OA 副本定位（免费无 key）
        r = session.get(f"https://api.openalex.org/works/doi:{quote(clean, safe='')}",
                        timeout=DEFAULT_TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            best = data.get("best_oa_location") or {}
            paper.oa_pdf_url = (
                best.get("pdf_url") or (data.get("open_access") or {}).get("oa_url") or ""
            )
        else:
            meta_error.append(f"OpenAlex HTTP {r.status_code}")
    except Exception as exc:
        meta_error.append(f"OpenAlex {exc.__class__.__name__}")

    if with_pdf_url and not paper.publisher_pdf_url:
        paper.publisher_pdf_url = _publisher_pdf_url(session, paper.doi_url)
    if not paper.title and not paper.oa_pdf_url and not paper.publisher_pdf_url:
        raise WestlakeError(f"DOI 解析不到任何信息（{'; '.join(meta_error) or '无元数据'}）")
    status = campus_status()
    paper.campus_hint = (
        "当前出口 IP 被出版社认作校园网：publisher_pdf_url 大概率可直接下载"
        if status.ip_authorized else
        "当前不在校园网认证范围：OA 副本可用，订阅全文需 CARSI SSO 或 VPN"
    )
    return paper


_PDF_META = re.compile(
    r'<meta[^>]+name=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)["\']|'
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']citation_pdf_url["\']',
    re.I,
)


def _publisher_pdf_url(session, doi_url: str) -> str:
    """打开出版社落地页，找 ``citation_pdf_url`` 元标签（行业标准做法）。"""
    try:
        r = session.get(doi_url, timeout=DEFAULT_TIMEOUT, allow_redirects=True)
        if r.status_code != 200:
            return ""
        match = _PDF_META.search(r.text)
        if not match:
            return ""
        return urljoin(str(r.url), match.group(1) or match.group(2) or "")
    except Exception:
        return ""


def fetch_pdf(doi: str, out: str | Path | None = None, *, paper: Paper | None = None) -> Path:
    """尽力获取一篇文献的 PDF：OA 副本 → 出版社直链（校园 IP 内认证）。

    成功返回落盘路径（校验 %PDF 魔数）；失败抛 :class:`WestlakeError`，
    信息里带人工兜底链接。
    """
    paper = paper or resolve_doi(doi, with_pdf_url=True)
    session = _direct_session()
    candidates: list[tuple[str, str]] = []
    if paper.oa_pdf_url:
        candidates.append(("OA 副本", paper.oa_pdf_url))
    if paper.publisher_pdf_url:
        candidates.append(("出版社直链", paper.publisher_pdf_url))
    # Springer 的 content/pdf 规律可靠，作为无元标签时的兜底候选
    springer = f"https://link.springer.com/content/pdf/{paper.doi}.pdf"
    if springer not in [u for _, u in candidates]:
        candidates.append(("Springer 规律直链", springer))

    out_path = Path(out) if out else Path.cwd() / f"{paper.doi.replace('/', '_')}.pdf"
    last_error = ""
    for label, url in candidates:
        try:
            r = session.get(url, timeout=60.0, allow_redirects=True,
                            headers={"Referer": paper.doi_url})
            if r.status_code == 200 and r.content[:5].startswith(b"%PDF"):
                out_path.write_bytes(r.content)
                logger.info("已下载 %s：%s（%d 字节，通道=%s）",
                            paper.doi, out_path, len(r.content), label)
                return out_path
            last_error = f"{label} HTTP {r.status_code}（{len(r.content)} 字节，非 PDF）"
        except Exception as exc:
            last_error = f"{label} {exc.__class__.__name__}"
    raise WestlakeError(
        f"PDF 获取失败（{last_error}）。人工通道：{paper.doi_url}"
        f"{'；OA：' + paper.oa_pdf_url if paper.oa_pdf_url else ''}"
    )


# --------------------------------------------------------------------------- #
# CARSI SSO（Playwright 持久化会话，taskcenter 同套路）
# --------------------------------------------------------------------------- #
def _browser() -> "object":
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise WestlakeError(
            "数据库 SSO 需要 Playwright：pip install playwright && playwright install chromium"
        ) from exc
    return sync_playwright()


def _iam_login_pending(page) -> bool:
    """当前是否停在 IAM 登录表单（未登录态）。"""
    return page.locator('input[placeholder*="用户名/手机号/邮箱"]').count() > 0


def _fill_iam_login(page, sid: str, password: str) -> None:
    """用统一凭据填 IAM 表单（验证码留给用户在可见窗口输入）。"""
    page.fill('input[placeholder*="用户名/手机号/邮箱"]', sid)
    page.fill('input[placeholder*="密码"]', password)
    page.locator('span:has-text("立即登录")').first.click(force=True)


def sso_browser(target: str = "cnki", *, headless: bool = False,
                return_url: str | None = None, timeout_ms: int = 180000) -> str:
    """打开浏览器走一次 CARSI 联盟登录，落回数据库后返回最终 URL。

    首次（或 IdP 会话失效）：自动填统一凭据；如 IAM 弹图形验证码，**由用户
    在窗口里输入**（不代解验证码）。会话持久化在 ``~/.westlake_survival/
    scholar_profile``，之后 ``sso_status``/headless 复用无需再登录。
    """
    from westlake_survival.sso import read_credentials

    try:
        sid, password = read_credentials()
    except Exception as exc:
        raise AuthError("未配置统一凭据；先 westlake setup 或网页「设置」页配置") from exc

    entry = carsi_sso_entry(target, return_url)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with _browser() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=headless, viewport={"width": 1280, "height": 860}
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto(entry, wait_until="domcontentloaded", timeout=60000)
            deadline = time.time() + timeout_ms / 1000
            filled = False
            while time.time() < deadline:
                page.wait_for_timeout(2000)
                url = str(page.url)
                if "iam.westlake.edu.cn" in url and _iam_login_pending(page) and not filled:
                    _fill_iam_login(page, sid, password)
                    filled = True  # 只填一次；验证码错回表单则交还给用户
                    if not headless:
                        print("已在 IAM 表单填入账号密码；若出现验证码请在窗口中输入。")
                if "idp.westlake.edu.cn" not in url and "iam.westlake.edu.cn" not in url \
                        and "Shibboleth.sso" not in url:
                    return url  # 已离开身份层，落到数据库侧
            raise WestlakeError(
                f"SSO 在 {timeout_ms / 1000:.0f}s 内未完成——若弹了验证码请在浏览器窗口输入；"
                "仍失败则检查统一密码或数据库入口结构是否变化"
            )
        finally:
            context.close()


def sso_status(target: str = "cnki") -> dict:
    """headless 检查 CARSI 会话是否仍有效（不动凭据、不弹窗）。"""
    entry = carsi_sso_entry(target)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    if not any(PROFILE_DIR.iterdir()):
        return {"logged_in": False, "detail": "尚未做过首次登录（westlake scholar sso cnki）"}
    with _browser() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=True, viewport={"width": 1280, "height": 860}
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto(entry, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(6000)
            url = str(page.url)
            logged_in = ("idp.westlake.edu.cn" not in url
                         and "iam.westlake.edu.cn" not in url
                         and "Shibboleth.sso" not in url)
            return {"logged_in": logged_in, "final_url": url[:160],
                    "detail": "IdP 会话有效" if logged_in else "需要重新 SSO（westlake scholar sso）"}
        finally:
            context.close()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _cli():
    import functools

    import click

    def handle(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except WestlakeError as exc:
                click.secho(f"错误：{exc}", fg="red", err=True)
                raise SystemExit(1) from exc

        return wrapper

    @click.group(name="scholar", help="学术资源：数据库注册表 / CARSI 联盟登录 / DOI 全文。")
    def group() -> None:
        """``westlake scholar dbs|campus|doi|carsi|sso|open``。"""

    @group.command(name="dbs")
    @click.option("-k", "--keyword", default=None, help="按名称/类别/厂商过滤")
    @handle
    def dbs_cmd(keyword: str | None) -> None:
        """订阅与常用学术数据库注册表。"""
        rows = databases(keyword)
        if not rows:
            click.echo("没有匹配的条目。")
            return
        click.echo(f"共 {len(rows)} 个（access：campus=校园IP carsi=联盟SSO open=免费 account=独立账号）：")
        for db in rows:
            click.echo(f"  [{db.access:6}] {db.name}（{db.category}） {db.url}"
                       + (f"  — {db.note}" if db.note else ""))

    @group.command(name="campus")
    @click.option("--refresh", is_flag=True, help="强制重新探测（默认缓存 30 分钟）")
    @handle
    def campus_cmd(refresh: bool) -> None:
        """当前出口 IP 是否被出版社认作校园网。"""
        status = campus_status(refresh=refresh)
        click.echo(("✅ 校园网认证范围内" if status.ip_authorized else "❌ 不在校园网认证范围")
                   + f"（{status.checked_at}）")
        click.echo(f"  {status.evidence}")
        if not status.ip_authorized:
            click.echo("  校外通道：westlake scholar sso cnki（CARSI）或连接校园 VPN。")

    @group.command(name="doi")
    @click.argument("doi")
    @click.option("--out", "-o", default=None, help="PDF 落盘路径（不给则只解析不下载）")
    @handle
    def doi_cmd(doi: str, out: str | None) -> None:
        """解析 DOI 元数据；--out 时尽力下载 PDF（OA→出版社订阅通道）。"""
        paper = resolve_doi(doi)
        click.echo(f"{paper.title or '(无题录)'}")
        who = "，".join(paper.authors[:6]) + (" 等" if len(paper.authors) > 6 else "")
        click.echo(f"  {who}｜{paper.journal} {paper.year}｜{paper.publisher}")
        click.echo(f"  DOI 页：{paper.doi_url}")
        if paper.oa_pdf_url:
            click.echo(f"  OA PDF：{paper.oa_pdf_url}")
        if paper.publisher_pdf_url:
            click.echo(f"  出版社 PDF：{paper.publisher_pdf_url}")
        click.echo(f"  {paper.campus_hint}")
        if out:
            path = fetch_pdf(doi, out, paper=paper)
            size = path.stat().st_size
            click.echo(f"  已下载：{path}（{size / 1024:.0f} KB）")

    @group.command(name="carsi")
    @click.argument("query", required=False)
    @click.option("--refresh", is_flag=True, help="在线更新 CARSI 目录快照")
    @handle
    def carsi_cmd(query: str | None, refresh: bool) -> None:
        """CARSI 联盟资源目录（356 个 SP，支持校外联盟登录的库）。"""
        if refresh:
            click.echo(f"在线更新：{CARSI_SPLIST_URL}")
        sps = carsi_catalog(query, refresh=refresh)
        click.echo(f"共 {len(sps)} 个资源：")
        for s in sps[:60]:
            click.echo(f"  {str(s.get('production') or '')[:44]:46} {s.get('url') or ''}")
        if len(sps) > 60:
            click.echo(f"  …（其余 {len(sps) - 60} 条请加关键词过滤）")

    @group.command(name="sso")
    @click.argument("target", default="cnki")
    @handle
    def sso_cmd(target: str) -> None:
        """浏览器走一次 CARSI 联盟登录（统一密码；验证码本人输入一次）。"""
        url = sso_browser(target, headless=False)
        click.echo(f"已登录并落到：{url}")
        click.echo("会话已存入 ~/.westlake_survival/scholar_profile，后续 headless 复用。")

    @group.command(name="status")
    @handle
    def status_cmd() -> None:
        """CARSI SSO 会话是否仍有效（headless，不动凭据）。"""
        result = sso_status()
        click.echo(("✅ " if result["logged_in"] else "❌ ") + str(result["detail"]))
        if result.get("final_url"):
            click.echo(f"  落点：{result['final_url']}")

    @group.command(name="open")
    @click.argument("target")
    @handle
    def open_cmd(target: str) -> None:
        """打印某库直达与 CARSI 入口 URL（不打开浏览器）。"""
        db = next((d for d in DATABASES if d.key == target), None)
        if db is None:
            raise WestlakeError(f"未知数据库：{target}（scholar dbs 查全部 key）")
        click.echo(f"{db.name}: {db.url}")
        click.echo(f"CARSI 入口: {carsi_sso_entry(target)}")

    return group


cli_group = _cli()
