"""西湖大学理论科学研究院官网（its.westlake.edu.cn）公开内容。

域名虽是 ``its``，站点本体是**理论科学研究院**官网（2026-10-24 盘点确认）。
传统静态站（非 TRS 组件）：栏目页 ``*.htm``，文章 ``info/<栏目>/<id>.htm``。

* :func:`sections`：顶部栏目（机构介绍 / 人员队伍 / 学术活动 / 新闻动态 / …）；
* :func:`articles`：栏目文章列表（标题 + 相对链接归一绝对 URL）。
"""

from __future__ import annotations

import re

import requests

from westlake_survival._net import DEFAULT_TIMEOUT
from westlake_survival.discovery import direct_session
from westlake_survival.exceptions import ParseError, WestlakeError

__all__ = ["ITS_BASE", "Article", "sections", "articles", "cli_group"]

ITS_BASE = "https://its.westlake.edu.cn/"

#: 有文章列表的栏目（名称 → 路径）。
LIST_COLUMNS = (
    ("新闻动态", "xwdt.htm"),
    ("学术活动", "xshd/xshy.htm"),
    ("人才培养", "rcoy/bkspy.htm"),
)

#: 英文版栏目（2026-10-25 实测：英文首页在 ``Home.htm``，同站同构英文树，
#: 文章仍是 ``info/<栏>/<id>.htm`` 形态，:func:`articles` 解析器通用）。
LIST_COLUMNS_EN = (
    ("News", "Home/News/News.htm"),
    ("Colloquium", "Home/Events/Colloquium.htm"),
    ("Programs", "Home/Programs/Undergraduate_Program.htm"),
)


def columns(lang: str = "zh"):
    """栏目清单（名称, 路径）——``lang="en"`` 给英文树。"""
    return LIST_COLUMNS if lang != "en" else LIST_COLUMNS_EN


class Article:
    def __init__(self, title: str, url: str):
        self.title = title
        self.url = url


def _fetch(path: str, session: requests.Session, timeout: float) -> str:
    url = path if path.startswith("http") else ITS_BASE + path.lstrip("/")
    try:
        response = session.get(url, timeout=timeout, verify=False)
    except requests.Timeout as exc:
        raise WestlakeError("理论科学研究院站点请求超时") from exc
    except requests.RequestException as exc:
        raise WestlakeError(f"理论科学研究院站点请求失败：{exc}") from exc
    return response.content.decode("utf-8", errors="replace")


def _absolute(href: str, column_path: str) -> str:
    if href.startswith("http"):
        return href
    base = ITS_BASE
    if href.startswith("../"):
        return base + href[3:]
    if href.startswith("/"):
        return base + href.lstrip("/")
    directory = column_path.rsplit("/", 1)[0] + "/" if "/" in column_path else ""
    return base + directory + href


def articles(
    column_path: str,
    *,
    limit: int = 15,
    session: requests.Session | None = None,
    timeout: float | None = None,
) -> list[Article]:
    """某栏目文章列表（只取 ``info/`` 形态的文章链接，导航自动剔除）。

    Raises:
        WestlakeError: 网络失败。
        ParseError: 栏目无文章（结构可能变化）。
    """
    session = session if session is not None else direct_session()
    html = _fetch(column_path, session, timeout or DEFAULT_TIMEOUT)
    out: list[Article] = []
    seen: set[str] = set()
    for href, raw in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
        if "info/" not in href:
            continue
        title = re.sub(r"<[^>]+>", "", raw)
        title = re.sub(r"\s+", " ", title).strip()
        if not title or len(title) < 6:
            continue
        url = _absolute(href, column_path)
        if url in seen:
            continue
        seen.add(url)
        out.append(Article(title=title, url=url))
    if not out:
        raise ParseError(f"栏目 {column_path} 未解析到文章（结构可能已变化）")
    return out[: max(0, limit)]


def sections(
    *,
    session: requests.Session | None = None,
    timeout: float | None = None,
    lang: str = "zh",
) -> list[tuple[str, str]]:
    """首页栏目（名称, 路径）；``lang="en"`` 解析英文首页 ``Home.htm``。"""
    session = session if session is not None else direct_session()
    html = _fetch("" if lang != "en" else "Home.htm", session, timeout or DEFAULT_TIMEOUT)
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for href, raw in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
        title = re.sub(r"<[^>]+>", "", raw).strip()
        pattern = r"[\u4e00-\u9fff]{2,8}" if lang != "en" else r"[A-Za-z][A-Za-z ]{3,28}"
        ok = re.fullmatch(pattern, title)
        if ok and href.endswith(".htm") and not href.startswith("http"):
            if href not in seen:
                seen.add(href)
                out.append((title, href))
    return out


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _cli():
    import functools

    import click

    from westlake_survival.exceptions import WestlakeError

    def handle(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except WestlakeError as exc:
                click.secho(f"错误：{exc}", fg="red", err=True)
                raise SystemExit(1) from exc

        return wrapper

    @click.group(name="institute", help="理论科学研究院官网内容（新闻/学术活动）。")
    def group() -> None:
        """``westlake institute news|events``。"""

    @group.command(name="news")
    @click.option("--limit", type=int, default=10, show_default=True)
    @click.option("--lang", type=click.Choice(["zh", "en"]), default="zh", show_default=True)
    @handle
    def news_cmd(limit: int, lang: str) -> None:
        """新闻动态（--lang en 走英文树 Home/News）。"""
        path = "xwdt.htm" if lang != "en" else "Home/News/News.htm"
        for a in articles(path, limit=limit):
            click.echo(f"  {a.title}　{a.url}")

    @group.command(name="events")
    @click.option("--limit", type=int, default=10, show_default=True)
    @handle
    def events_cmd(limit: int) -> None:
        """学术活动。"""
        for a in articles("xshd/xshy.htm", limit=limit):
            click.echo(f"  {a.title}　{a.url}")

    return group


cli_group = _cli()
