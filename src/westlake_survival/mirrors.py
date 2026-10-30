"""西湖开源镜像站（mirrors.westlake.edu.cn）仓库目录。

首页是静态卡片：仓库名 + 镜像地址 + （部分）Help 配置说明页。公开、免登录。
"""

from __future__ import annotations

import re

import requests

from westlake_survival._cache import load_cached, save_cached
from westlake_survival._net import DEFAULT_TIMEOUT
from westlake_survival.discovery import direct_session, MIRRORS_URL
from westlake_survival.exceptions import ParseError, WestlakeError

__all__ = ["MIRRORS_URL", "MirrorRepo", "repos", "cli_group"]

#: 镜像目录本地缓存（公开数据，24 小时 TTL）。
_CACHE_NAME = "mirrors/repos.json"
_TTL = 24 * 3600


class MirrorRepo:
    def __init__(self, name: str, url: str, help_url: str = ""):
        self.name = name
        self.url = url
        self.help_url = help_url


def _parse_html(html: str) -> list[MirrorRepo]:
    items: list[MirrorRepo] = []
    seen: set[str] = set()
    for href, title in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
        title = re.sub(r"<[^>]+>", " ", title)
        title = re.sub(r"\s+", " ", title).strip()
        if href.startswith("/posts/") and "_help" in href:
            # Help 链接跟在它所属仓库之后：挂到上一个仓库。
            slug = href.rsplit("/", 1)[-1].replace("_help.html", "")
            for item in items:
                if item.name.lower().replace("-", "") == slug.lower().replace("-", ""):
                    # 存绝对地址：CLI 输出可复制、页面 href 也可直接点。
                    if href.startswith("http"):
                        item.help_url = href
                    else:
                        origin = MIRRORS_URL.split("/", 3)
                        item.help_url = "/".join(origin[:3]) + href
                    break
            continue
        if href.startswith("https://mirrors.westlake.edu.cn/") and title and title != "Help" and href not in seen:
            seen.add(href)
            items.append(MirrorRepo(name=title, url=href))
    if len(items) < 6:
        raise ParseError(f"镜像仓库解析异常（仅 {len(items)} 个）")
    return items


def repos(
    *,
    session: requests.Session | None = None,
    timeout: float | None = None,
    refresh: bool = False,
) -> list[MirrorRepo]:
    """镜像仓库列表（含 Help 链接；带 24h 缓存与离线降级）。

    Raises:
        WestlakeError: 网络失败。
        ParseError: 解析结果异常偏少。
    """
    if not refresh:
        cached = load_cached(_CACHE_NAME, _TTL)
        if cached and isinstance(cached, list):
            return [MirrorRepo(**item) for item in cached]

    session = session if session is not None else direct_session()
    try:
        response = session.get(MIRRORS_URL, timeout=timeout or DEFAULT_TIMEOUT, verify=False)
        html = response.content.decode("utf-8", errors="replace")
        items = _parse_html(html)
        save_cached(
            _CACHE_NAME,
            [{"name": item.name, "url": item.url, "help_url": item.help_url} for item in items],
        )
        return items
    except Exception as exc:
        stale = load_cached(_CACHE_NAME, 10**9)
        if stale and isinstance(stale, list):
            return [MirrorRepo(**item) for item in stale]
        if isinstance(exc, requests.Timeout):
            raise WestlakeError("镜像站请求超时") from exc
        raise WestlakeError(f"镜像站请求失败：{exc}") from exc


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

    @click.command(name="mirrors", help="西湖开源镜像站仓库目录（公开）。")
    @click.option("--refresh", is_flag=True, help="忽略缓存重新拉取。")
    @handle
    def cli_group(refresh: bool) -> None:
        """列出镜像仓库与地址。"""
        for r in repos(refresh=refresh):
            help_note = f"　Help: {r.help_url}" if r.help_url else ""
            click.echo(f"  {r.name:<16} {r.url}{help_note}")

    return cli_group


cli_group = _cli()
