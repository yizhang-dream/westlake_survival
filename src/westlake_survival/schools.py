"""学院官网聚合：理学院 / 生命科学 / 工学院 / 医学院 / 理论科学研究院。

五个学院站四种形态（2026-10-24 实测）：

* **理学院** science：Nuxt + ``chemistry_api`` CMS（POST ``outLxyHmNewsList``，
  参数 ``pageNo/pageSize/language``，条目含 title/linkUrl/publishTime）；
* **工学院** engineering：TRS 组件站，首页 ``new homePage('#app', {...})`` 的
  ``mainBanner``/列表即新闻（title + link 指主站或本院 .shtml）；
* **生命科学** sls：静态页，``/NEWS/`` 列表项是 ``p.news_desc`` 带
  ``onClick=window.open('<相对路径>')`` + ``p.news_time`` 两个 span（类别/日期）；
* **医学院** medicine：与 sls 同款 ``news_desc/onClick`` 静态结构；
* **理论科学研究院** its：见 :mod:`westlake_survival.institute`（静态 a 标签）。

聚合入口 :func:`news(school)`；:func:`SCHOOLS` 是注册表（供 CLI/WebUI/注册表页）。
"""

from __future__ import annotations

import json
import re

import requests

from westlake_survival._net import DEFAULT_TIMEOUT
from westlake_survival.discovery import direct_session
from westlake_survival.exceptions import ParseError, WestlakeError

__all__ = ["SCHOOLS", "SchoolArticle", "news", "cli_group"]


class SchoolArticle:
    def __init__(self, title: str, url: str, date: str = "", kind: str = ""):
        self.title = title
        self.url = url
        self.date = date
        self.kind = kind


#: 学院注册表：key → (名称, 站点根, 形态)。
SCHOOLS = {
    "science": ("理学院", "https://science.westlake.edu.cn/", "api"),
    "sls": ("生命科学学院", "https://sls.westlake.edu.cn/", "news_desc"),
    "engineering": ("工学院", "https://engineering.westlake.edu.cn/", "trs_home"),
    "medicine": ("医学院", "https://medicine.westlake.edu.cn/", "news_desc"),
    "institute": ("理论科学研究院", "https://its.westlake.edu.cn/", "institute"),
}


def _fetch(url: str, session: requests.Session, timeout: float) -> str:
    try:
        response = session.get(url, timeout=timeout, verify=False)
    except requests.Timeout as exc:
        raise WestlakeError("学院站点请求超时") from exc
    except requests.RequestException as exc:
        raise WestlakeError(f"学院站点请求失败：{exc}") from exc
    return response.content.decode("utf-8", errors="replace")


def _science_news(session: requests.Session, timeout: float, limit: int,
                   language: str = "Chinese") -> list[SchoolArticle]:
    url = "https://science.westlake.edu.cn/chemistry_api/biz/modularity/project247/outLxyHmNewsList"
    try:
        response = session.post(
            url,
            json={"pageNo": 1, "pageSize": limit, "language": language, "kexi": None, "workType": None},
            timeout=timeout, verify=False,
        )
    except requests.RequestException as exc:
        raise WestlakeError(f"理学院接口失败：{exc}") from exc
    try:
        payload = response.json()
    except ValueError as exc:
        raise ParseError("理学院接口返回非 JSON") from exc
    rows = ((payload.get("data") or {}).get("outputData")) or []
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        out.append(
            SchoolArticle(
                title=title,
                url=str(row.get("linkUrl") or ""),
                date=str(row.get("publishTime") or "")[:10],
            )
        )
    if not out:
        raise ParseError("理学院新闻为空（接口结构可能已变化）")
    return out[:limit]


def _news_desc_news(base: str, path: str, session: requests.Session, timeout: float, limit: int) -> list[SchoolArticle]:
    """sls/medicine 同款静态结构：每条是 div.new_every，内含 news_time 两 span
    （类别/日期）与 news_desc 的 onClick=window.open('<相对路径>')。"""
    html = _fetch(base + path, session, timeout)
    out: list[SchoolArticle] = []
    for chunk in html.split('class="new_every"')[1:]:
        time_match = re.search(
            r'class="news_time">\s*<span>([^<]*)</span>\s*<span>([^<]*)</span>', chunk
        )
        href_match = re.search(r"window\.open\('([^']+\.shtml)'", chunk)
        title_match = re.search(r'class="news_desc"[^>]*>(.*?)</p>', chunk, re.S)
        if not (time_match and href_match and title_match):
            continue
        title = re.sub(r"<[^>]+>", "", title_match.group(1))
        title = re.sub(r"\s+", " ", title).strip()
        if not title:
            continue
        kind, date = time_match.group(1).strip(), time_match.group(2).strip()
        href = href_match.group(1)
        url = href if href.startswith("http") else base + href.lstrip("./")
        out.append(SchoolArticle(title=title, url=url, date=date, kind=kind))
    if not out:
        raise ParseError("新闻列表解析为空（结构可能已变化）")
    return out[:limit]


def _engineering_news(session: requests.Session, timeout: float, limit: int,
                       base: str = "https://engineering.westlake.edu.cn/",
                       label: str = "工学院") -> list[SchoolArticle]:
    """TRS 首页组件：mainBanner 条目即新闻（生科英文站 lifesciences 同构）。"""
    from westlake_survival._trs import balanced, component_script, js_literal

    html = _fetch(base, session, timeout)
    block = component_script(html, "homePage")
    if not block:
        raise ParseError(f"{label}首页未找到 homePage 组件")
    match = re.search(r"mainBanner\s*:\s*\[", block)
    if not match:
        raise ParseError(f"{label}组件缺少 mainBanner")
    items = js_literal(balanced(block, match.end() - 1))
    out = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        link = str(item.get("link") or "").strip()
        if title and link:
            out.append(SchoolArticle(title=title, url=link))
    if not out:
        raise ParseError(f"{label}新闻为空")
    return out[:limit]


def _institute_news(session: requests.Session, timeout: float, limit: int,
                      lang: str = "zh") -> list[SchoolArticle]:
    from westlake_survival.institute import articles

    path = "xwdt.htm" if lang != "en" else "Home/News/News.htm"
    return [
        SchoolArticle(title=a.title, url=a.url)
        for a in articles(path, limit=limit, session=session, timeout=timeout)
    ]


def news(
    school: str,
    *,
    limit: int = 10,
    session: requests.Session | None = None,
    timeout: float | None = None,
    lang: str = "zh",
) -> list[SchoolArticle]:
    """某学院的最新新闻。

    Args:
        school: :data:`SCHOOLS` 的键（science/sls/engineering/medicine/institute）。

    Raises:
        ValueError: 未知学院。
        WestlakeError / ParseError: 网络/结构问题。
    """
    if school not in SCHOOLS:
        raise ValueError(f"未知学院 {school!r}，可选：{', '.join(SCHOOLS)}")
    name, base, kind = SCHOOLS[school]
    if lang == "en" and school == "medicine":
        raise WestlakeError("医学院无英文面（About 页无语言切换，2026-10-25 实测）")
    if lang == "en" and school == "sls":
        raise WestlakeError("生科英文站 lifesciences 结构另型（homePage 无 mainBanner，多 lists 数组），待后续适配")
    if lang == "en" and school == "engineering":
        raise WestlakeError("工学院英文站 en-soe 是空壳 SPA（无服务端内容，2026-10-25 实测）")
    session = session if session is not None else direct_session()
    effective = timeout or DEFAULT_TIMEOUT
    if kind == "api":
        # 理学院双语 = 接口 language 参数（English/Chinese）
        return _science_news(session, effective, limit,
                             language="Chinese" if lang != "en" else "English")
    if kind == "news_desc":
        path = "NEWS/" if school == "sls" else "News/"
        return _news_desc_news(base, path, session, effective, limit)
    if kind == "trs_home":
        return _engineering_news(session, effective, limit)
    return _institute_news(session, effective, limit, lang=lang)


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

    @click.group(name="schools", help="学院官网新闻：理学院/生科/工学/医学/理论院。")
    def group() -> None:
        """``westlake schools list|news <学院>``。"""

    @group.command(name="list")
    def list_cmd() -> None:
        """学院清单。"""
        for key, (name, base, _kind) in SCHOOLS.items():
            click.echo(f"  {key:<12} {name}　{base}")

    @group.command(name="news")
    @click.argument("school")
    @click.option("--limit", type=int, default=10, show_default=True)
    @click.option("--lang", type=click.Choice(["zh", "en"]), default="zh", show_default=True,
                  help="英文（science/institute 支持；medicine/engineering/sls 见报错说明）。")
    @handle
    def news_cmd(school: str, limit: int, lang: str) -> None:
        """某学院最新新闻，如 `westlake schools news science --lang en`。"""
        for a in news(school, limit=limit, lang=lang):
            extra = f"　{a.date}" if a.date else ""
            click.echo(f"  {a.title}{extra}　{a.url}")

    return group


cli_group = _cli()
