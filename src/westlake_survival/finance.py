"""财务部官网（finance.westlake.edu.cn）公开栏目与文章列表。

站点是传统 TRS 静态站（无 charset 头、相对链接、栏目页 ``*.htm``）。本模块抓：

* :func:`sections`：首页导航栏目（部门职责 / 校内财务制度 / 日常报销 / 预决算 /
  科研经费管理 / 收费票据 等，实测 10 个）；
* :func:`articles`：给定栏目页路径，抓文章列表（标题 + 相对路径转绝对）。

导航条目会混在栏目页的链接里，按「栏目自身路径之外」过滤。
"""

from __future__ import annotations

import re

import requests

from westlake_survival._net import DEFAULT_TIMEOUT
from westlake_survival.discovery import direct_session
from westlake_survival.exceptions import ParseError, WestlakeError

__all__ = ["FINANCE_BASE", "SectionLink", "ArticleLink", "sections", "articles", "cli_group"]

FINANCE_BASE = "https://finance.westlake.edu.cn/"

#: 学生/科研最常用的栏目（路径相对站点根）。
DEFAULT_SECTIONS = (
    ("日常报销", "ywzn1/rcbx1.htm"),
    ("科研经费管理", "ywzn1/kyjfgl.htm"),
    ("校内财务制度", "gzzd1/zmcwzd.htm"),
    ("收费票据", "ywzn1/sfpj.htm"),
)


class SectionLink:
    def __init__(self, title: str, path: str):
        self.title = title
        self.path = path


class ArticleLink:
    def __init__(self, title: str, url: str, date: str = ""):
        self.title = title
        self.url = url
        self.date = date


def _fetch(path: str, session: requests.Session, timeout: float) -> str:
    url = path if path.startswith("http") else FINANCE_BASE + path.lstrip("/")
    try:
        response = session.get(url, timeout=timeout, verify=False)
    except requests.Timeout as exc:
        raise WestlakeError("财务部站点请求超时") from exc
    except requests.RequestException as exc:
        raise WestlakeError(f"财务部站点请求失败：{exc}") from exc
    if response.status_code >= 400:
        # 以前 404/500 页与正常页同管道，坏路径静默变成「该栏目没有文章」。
        raise WestlakeError(f"财务部站点返回 HTTP {response.status_code}：{url[:80]}")
    return response.content.decode("utf-8", errors="replace")


def _absolute(href: str, base_path: str) -> str:
    """把栏目页里的相对链接转成绝对 URL（../ 与裸文件名两种形态）。"""
    if href.startswith("http"):
        return href
    if href.startswith("../"):
        return FINANCE_BASE + href[3:]
    if href.startswith("/"):
        return FINANCE_BASE + href.lstrip("/")
    # 同目录
    directory = base_path.rsplit("/", 1)[0] + "/"
    return FINANCE_BASE + directory + href


def _links(html: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for href, raw in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
        title = re.sub(r"<[^>]+>", "", raw)
        title = re.sub(r"\s+", "", title)
        if not re.search(r"[\u4e00-\u9fff]", title):
            continue
        if href.endswith((".htm", ".html")) and href not in seen:
            seen.add(href)
            out.append((title, href))
    return out


def sections(
    *,
    session: requests.Session | None = None,
    timeout: float | None = None,
) -> list[SectionLink]:
    """首页导航栏目列表。

    Raises:
        WestlakeError: 网络失败。
        ParseError: 栏目解析为空。
    """
    session = session if session is not None else direct_session()
    html = _fetch("", session, timeout or DEFAULT_TIMEOUT)
    items = [
        SectionLink(title=title, path=href)
        for title, href in _links(html)
        # info/ 是新闻详情页（「财务部开展…」），不是栏目；混进来会让栏目数虚高。
        if "/" in href and not href.startswith("http") and not href.startswith("info/")
    ]
    if len(items) < 5:
        raise ParseError("财务部栏目解析异常（结构可能已变化）")
    return items


def articles(
    section_path: str,
    *,
    limit: int = 15,
    exclude: set[str] | None = None,
    session: requests.Session | None = None,
    timeout: float | None = None,
) -> list[ArticleLink]:
    """某栏目的文章列表（导航链接已剔除）。

    Args:
        section_path: 栏目路径（如 ``ywzn1/rcbx1.htm``）。
        limit: 最多返回条数。
        exclude: 需剔除的 URL 集合（业务指南侧栏在各栏目页重复出现，
            页面组装方先取 rcbx 的 URL 集合传进来）。
    """
    session = session if session is not None else direct_session()
    html = _fetch(section_path, session, timeout or DEFAULT_TIMEOUT)
    # 导航条目集合：首页栏目路径（栏目页里以 ../xxx 形态重现），全部剔除。
    try:
        nav_paths = {s_.path for s_ in sections(session=session, timeout=timeout)}
    except WestlakeError:
        nav_paths = set()
    skip = {section_path, section_path.rsplit("/", 1)[-1]} | nav_paths
    out: list[ArticleLink] = []
    seen: set[str] = set()
    for title, href in _links(html):
        normalized = href[3:] if href.startswith("../") else href
        if normalized in skip or href in skip:
            continue  # 栏目导航本身
        # 栏目内容是子目录文档（如 rcbx1/gdzcbx.htm）；根级 *.htm 一律是导航。
        if "/" not in normalized:
            continue
        url = _absolute(href, section_path)
        if url in seen or (exclude and url in exclude):
            continue
        seen.add(url)
        out.append(ArticleLink(title=title, url=url))
    return out[: max(0, limit)]


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

    @click.group(name="finance", help="财务部公开栏目与文章（报销/科研经费/制度）。")
    def group() -> None:
        """``westlake finance sections|articles``。"""

    @group.command(name="sections")
    @handle
    def sections_cmd() -> None:
        """列出全部栏目。"""
        for s in sections():
            click.echo(f"  {s.title}　{s.path}")

    @group.command(name="articles")
    @click.argument("section_path")
    @click.option("--limit", type=int, default=15, show_default=True)
    @handle
    def articles_cmd(section_path: str, limit: int) -> None:
        """列出某栏目文章，如 `westlake finance articles ywzn1/rcbx1.htm`。"""
        items = articles(section_path, limit=limit)
        if not items:
            click.echo("该栏目没有解析到文章。")
            return
        for a in items:
            click.echo(f"  {a.title}　{a.url}")

    return group


cli_group = _cli()
