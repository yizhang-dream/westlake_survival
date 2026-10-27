"""WikiLake（西湖大学学生自建校园百科）只读检索。

站点 <https://wiki.mestlake.cc> 是 Docusaurus 静态站：**没有站内搜索**，目录只有
侧边栏。这里补一层最小检索：

* 目录：读 ``/sitemap.xml``（2026-10-27 实测 157 个 URL），本地缓存；
* 标题检索：在目录上匹配，零额外请求；
* 正文检索（``deep``）：按需抓页面，提取 ``<article class="theme-doc-markdown">``
  正文，并发 6、结果缓存 12 小时；
* 单页正文：给名字（``音游社``）、路径（``clubs/音游社``）或完整 URL 都能取。

只读、匿名、不带任何凭据，也不提交内容。条目版权归 WikiLake 贡献者（该站未声明
许可证）；``people`` 类条目含真实姓名与照片，引用时自行判断（本项目对 PII 的口径
见 AGENTS.md），检索结果只在本地展示、不落盘到仓库。
"""

from __future__ import annotations

import html as _html
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict

import requests
import click

from westlake_survival._cache import load_cached, save_cached
from westlake_survival._net import DEFAULT_TIMEOUT
from westlake_survival.discovery import direct_session

__all__ = [
    "WIKILAKE_URL",
    "CATEGORY_LABELS",
    "PageRef",
    "pages",
    "search",
    "lookup",
    "page",
    "cli_group",
]

#: 站点根地址。
WIKILAKE_URL = "https://wiki.mestlake.cc"

#: 路径首段 → 中文栏目名（Docusaurus 的目录名）。
CATEGORY_LABELS = {
    "clubs": "社团",
    "buildings": "建筑",
    "guides": "指南",
    "courses": "课程",
    "curriculum": "培养方案",
    "foods": "餐饮",
    "memes": "梗",
    "miscs": "杂项",
    "people": "人物",
    "colleges": "书院",
    "tools": "工具",
}

#: 缓存 TTL：目录 12 小时、正文索引 12 小时。
_TTL = 12 * 3600

#: 并发抓取上限（站点是 Netlify 静态页，保持客气）。
_WORKERS = 6

_LOC_RE = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.S)
#: 正文容器：Docusaurus 的 `<div class="theme-doc-markdown markdown">`（实测不是 article）。
_DOC_OPEN_RE = re.compile(r'(?is)<div[^>]*class="[^"]*theme-doc-markdown[^"]*"[^>]*>')
_ARTICLE_OPEN_RE = re.compile(r"(?is)<article[^>]*>")
_DIV_TAG_RE = re.compile(r"(?is)</?div\b[^>]*>")
_DROP_BLOCK_RE = re.compile(r"(?is)<(script|style|nav|footer|svg)\b.*?</\1>")
_BLOCK_END_RE = re.compile(r"(?i)</(p|div|li|h[1-6]|tr|table|section|article|blockquote|pre|header)>")
_BR_RE = re.compile(r"(?i)<br\s*/?>")
_CELL_END_RE = re.compile(r"(?i)</t[dh]>")
_TAG_RE = re.compile(r"<[^>]+>")

#: 页面框架文案（正文提取时丢弃）。
_CHROME_LINES = {"跳到主要内容", "本页总览", "编辑此页", "上一页", "下一页"}


@dataclass(frozen=True)
class PageRef:
    """一条目录项：路径、标题、栏目、完整 URL。"""

    path: str
    title: str
    category: str
    url: str

    def to_dict(self) -> dict:
        return asdict(self)


def _session() -> requests.Session:
    """每个请求独立会话（本项目并发约定，避免连接池串味）。"""
    return direct_session()


def _fetch(path: str, *, timeout: float | None = None) -> str:
    """GET 站点路径，返回文本（相对路径会自动补全）。"""
    url = path if path.startswith("http") else f"{WIKILAKE_URL}/{path.lstrip('/')}"
    response = _session().get(url, timeout=timeout or DEFAULT_TIMEOUT)
    response.raise_for_status()
    if not response.encoding:
        response.encoding = "utf-8"
    return response.text


def _title_of(path: str) -> tuple[str, str]:
    """由路径推出（标题, 栏目）：末段解码为标题，首段映射栏目。"""
    clean = path.strip("/")
    if not clean:
        return "首页", "首页"
    parts = clean.split("/")
    category = CATEGORY_LABELS.get(parts[0], "其它")
    if len(parts) == 1:
        return category, category
    return urllib.parse.unquote(parts[-1]), category


def _parse_sitemap(xml: str) -> list[PageRef]:
    """sitemap → 目录项；跳过标签页、markdown-page 与站外链接。"""
    refs: list[PageRef] = []
    seen: set[str] = set()
    for raw in _LOC_RE.findall(xml):
        url = _html.unescape(raw.strip())
        if not url.startswith(WIKILAKE_URL):
            continue
        path = urllib.parse.urlsplit(url).path
        if path.startswith("/tags") or path.startswith("/markdown-page"):
            continue
        if path in seen:
            continue
        seen.add(path)
        title, category = _title_of(path)
        refs.append(PageRef(path=path or "/", title=title, category=category, url=WIKILAKE_URL + path))
    refs.sort(key=lambda ref: (ref.category, ref.title))
    return refs


def pages(*, refresh: bool = False) -> list[PageRef]:
    """WikiLake 目录（sitemap 解析，缓存 12 小时；网络失败时用旧缓存）。

    Args:
        refresh: 忽略缓存强制重抓。

    Raises:
        WestlakeError: 首次抓取失败且本地无缓存。
    """
    from westlake_survival.exceptions import WestlakeError

    ttl = 0 if refresh else _TTL
    cached = load_cached("wikilake/pages.json", ttl)
    if cached:
        return [PageRef(**item) for item in cached]
    try:
        xml = _fetch("/sitemap.xml")
    except requests.RequestException as exc:
        stale = load_cached("wikilake/pages.json", 10**9)
        if stale:
            return [PageRef(**item) for item in stale]
        raise WestlakeError(f"WikiLake 目录抓取失败：{exc}") from exc
    refs = _parse_sitemap(xml)
    if not refs:
        raise WestlakeError("WikiLake 目录为空：sitemap 结构可能已变化。")
    save_cached("wikilake/pages.json", [ref.to_dict() for ref in refs])
    return refs


def _doc_fragment(markup: str) -> str:
    """切出正文容器内部 HTML（div 深度计数，容忍嵌套）。"""
    match = _DOC_OPEN_RE.search(markup)
    if match:
        start = match.end()
        depth = 1
        for tag in _DIV_TAG_RE.finditer(markup, start):
            depth += -1 if tag.group(0).lower().startswith("</div") else 1
            if depth == 0:
                return markup[start : tag.start()]
        return markup[start:]
    match = _ARTICLE_OPEN_RE.search(markup)
    if match:
        start = match.end()
        end = markup.lower().find("</article>", start)
        return markup[start:end] if end > 0 else markup[start:]
    return ""


def _article_text(markup: str, *, title: str = "", category: str = "") -> str:
    """HTML → 纯文本：去脚本/样式与页面框架文案，块级标签换行，压空白。"""
    fragment = _DROP_BLOCK_RE.sub(" ", markup)
    fragment = _CELL_END_RE.sub(" | ", fragment)
    fragment = _BR_RE.sub("\n", fragment)
    fragment = _BLOCK_END_RE.sub("\n", fragment)
    text = _TAG_RE.sub("", fragment)
    text = _html.unescape(text).replace("\u200b", "").replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    # 开头可能是面包屑（栏目名）与重复的标题，连同「跳到主要内容」一类框架文案一起去掉
    leading = True
    cleaned: list[str] = []
    for line in lines:
        if line in _CHROME_LINES or line.startswith("上次更新"):
            continue
        if leading and (line == title or line == category or line == f"{title} | WikiLake"):
            continue
        leading = False
        cleaned.append(line)
    return "\n".join(cleaned)


def _page_text(ref: PageRef) -> str:
    """抓单页并提取正文（失败返回空串，供批量检索降级）。"""
    try:
        markup = _fetch(ref.path)
    except requests.RequestException:
        return ""
    return _article_text(_doc_fragment(markup), title=ref.title, category=ref.category) or _article_text(
        markup, title=ref.title, category=ref.category
    )


def _texts(refs: list[PageRef], *, refresh: bool = False) -> dict[str, str]:
    """全部条目正文（并发抓、缓存 12 小时；失败的页留空）。"""
    ttl = 0 if refresh else _TTL
    cached = load_cached("wikilake/texts.json", ttl)
    if cached:
        return cached
    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        results = list(pool.map(_page_text, refs))
    texts = {ref.path: text for ref, text in zip(refs, results) if text}
    if len(texts) >= max(1, len(refs) // 2):  # 抓到一半以上才写缓存，避免半残结果长期驻留
        save_cached("wikilake/texts.json", texts)
    return texts


def _match_title(ref: PageRef, query: str) -> bool:
    """标题包含检索词（大小写不敏感）。"""
    return query.lower() in ref.title.lower()


def search(query: str, *, limit: int = 10, deep: bool = False) -> list[dict]:
    """检索 WikiLake 条目。

    Args:
        query: 检索词（中文或英文）。
        limit: 返回条数上限（1–50）。
        deep: 同时检索正文；首次会抓全站页面（约 150 页，几秒），随后走缓存。

    Returns:
        ``[{title, category, path, url, snippet}]``；正文检索未命中时 ``snippet`` 为空。
    """
    term = (query or "").strip()
    if not term:
        return []
    refs = pages()
    hits = [ref for ref in refs if _match_title(ref, term)]
    results = [
        {**ref.to_dict(), "snippet": ""}
        for ref in (hits[:limit] if not deep else hits)
    ]
    if not deep:
        return results[:limit]
    texts = _texts(refs)
    matched: list[dict] = []
    lowered = term.lower()
    for ref in refs:
        text = texts.get(ref.path, "")
        body_hit = lowered in text.lower()
        if not body_hit and ref not in hits:
            continue
        snippet = ""
        if body_hit:
            index = text.lower().find(lowered)
            snippet = text[max(0, index - 40) : index + len(term) + 80].replace("\n", " ")
        matched.append({**ref.to_dict(), "snippet": snippet})
    # 标题命中优先
    matched.sort(key=lambda item: (item["title"].lower().find(lowered) < 0, item["category"], item["title"]))
    return matched[:limit]


def _normalize_path(name: str) -> str:
    """把「名字 / 路径 / URL」统一成站点路径。"""
    text = (name or "").strip()
    if text.startswith(WIKILAKE_URL):
        text = urllib.parse.urlsplit(text).path
    text = urllib.parse.unquote(text)
    if not text.startswith("/") and "/" not in text:
        return ""
    return "/" + text.strip("/") + ("/" if text.endswith("/") else "")


def lookup(name: str) -> PageRef | None:
    """按名字、路径或 URL 找目录项；同名取第一个，找不到返回 ``None``。"""
    text = (name or "").strip()
    if not text:
        return None
    refs = pages()
    if text.startswith(WIKILAKE_URL) or "/" in text:
        target = _normalize_path(text).rstrip("/")
        for ref in refs:
            if urllib.parse.unquote(ref.path).rstrip("/") == target:
                return ref
        return None
    exact = [ref for ref in refs if ref.title == text]
    if exact:
        return exact[0]
    fuzzy = [ref for ref in refs if text.lower() in ref.title.lower()]
    return fuzzy[0] if len(fuzzy) == 1 else (fuzzy[0] if fuzzy else None)


def page(name: str) -> dict:
    """取单页正文。

    Args:
        name: 条目名（``音游社``）、路径（``clubs/音游社``）或完整 URL。

    Raises:
        WestlakeError: 找不到条目或抓取失败。
    """
    from westlake_survival.exceptions import WestlakeError

    ref = lookup(name)
    if ref is None:
        raise WestlakeError(f"WikiLake 没有匹配「{name}」的条目。")
    try:
        markup = _fetch(ref.path)
    except requests.RequestException as exc:
        raise WestlakeError(f"WikiLake 页面抓取失败：{exc}") from exc
    body = _article_text(_doc_fragment(markup), title=ref.title, category=ref.category)
    if not body:
        raise WestlakeError(f"WikiLake 页面「{ref.title}」没有可提取的正文。")
    return {
        "title": ref.title,
        "category": ref.category,
        "path": ref.path,
        "url": ref.url,
        "text": body,
        "source": "WikiLake（学生自建校园百科，非官方）",
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _handle_errors(func):
    """把 :class:`WestlakeError` 转成中文提示 + 退出码 1。"""

    import functools

    from westlake_survival.exceptions import WestlakeError

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except WestlakeError as exc:
            click.secho(f"错误：{exc}", fg="red", err=True)
            raise SystemExit(1) from exc

    return wrapper


@click.group(
    name="wiki",
    help="WikiLake 校园百科（学生自建）：目录、检索、单页正文（只读，无需凭据）。",
)
def cli_group() -> None:
    """``westlake wiki`` 命令组。"""


@cli_group.command(name="list")
@click.option("--cat", "category", default="", help="只看某栏目（clubs/buildings/guides…或中文名）。")
@click.option("--limit", type=int, default=200, show_default=True, help="最多显示条数。")
@click.option("--refresh", is_flag=True, help="忽略缓存重新抓目录。")
@_handle_errors
def wiki_list(category: str, limit: int, refresh: bool) -> None:
    """列出条目（按栏目分组）。"""
    refs = pages(refresh=refresh)
    if category:
        key = category.strip()
        label = CATEGORY_LABELS.get(key, key)
        refs = [ref for ref in refs if ref.category in {label, key}]
    if not refs:
        click.echo("没有匹配的条目。")
        return
    current = ""
    for ref in refs[:limit]:
        if ref.category != current:
            current = ref.category
            click.echo(f"\n== {current} ==")
        click.echo(f"  {ref.title}  ({ref.path})")
    if len(refs) > limit:
        click.echo(f"\n… 共 {len(refs)} 条，仅显示前 {limit} 条。")


@cli_group.command(name="search")
@click.argument("query")
@click.option("--deep", is_flag=True, help="同时检索正文（首次抓全站，几秒）。")
@click.option("--limit", type=int, default=10, show_default=True, help="最多返回条数。")
@_handle_errors
def wiki_search(query: str, deep: bool, limit: int) -> None:
    """检索条目（标题；加 --deep 检索正文）。"""
    results = search(query, limit=max(1, min(limit, 50)), deep=deep)
    if not results:
        click.echo("没有匹配的条目。" + ("" if deep else "试试 --deep 检索正文。"))
        return
    for item in results:
        click.echo(f"- [{item['category']}] {item['title']}")
        click.echo(f"  {item['url']}")
        if item.get("snippet"):
            click.echo(f"  {item['snippet'][:120]}")


@cli_group.command(name="page")
@click.argument("name")
@_handle_errors
def wiki_page(name: str) -> None:
    """打印单页正文（名字 / 路径 / URL 都行）。"""
    data = page(name)
    click.echo(f"# {data['title']}（{data['category']}）")
    click.echo(data["url"])
    click.echo("")
    click.echo(data["text"])
