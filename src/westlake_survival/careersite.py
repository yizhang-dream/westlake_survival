"""西湖大学就业服务网（career.westlake.edu.cn）公开三区块。

背景（2026-10-24 实测）
========================
* 站点是就业信息系统：岗位 ``/campus/view/id/<n>``、招聘会 ``/jobfair/view/id/<n>``、
  宣讲会 ``/teachin/view/id/<n>`` 均为服务端渲染详情页。
* **首页三区块免登录**（招聘公告 / 招聘会 / 宣讲会），条目自带日期、时段、
  场地、状态（已举办等）与浏览数。
* 列表页（``/campus`` ``/jobfair`` ``/teachin`` ``/news``）匿名访问会重定向到
  iam 统一认证——深列表需登录，暂未接入；后续可复用 scholar 的 Playwright
  会话模式补。全站岗位检索入口 ``/job/search/…`` 同样需登录。

数据只做读取与展示；条目链接指向官网详情页，投递等动作由本人完成。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from westlake_survival._cache import http_get_with_etag
from westlake_survival._net import http_session
from westlake_survival.exceptions import WestlakeError

__all__ = ["CAREER_SITE_BASE", "CareerItem", "announcements", "cli_group"]

logger = logging.getLogger(__name__)

CAREER_SITE_BASE = "https://career.westlake.edu.cn"

_KIND_LABEL = {"campus": "招聘公告", "jobfair": "招聘会", "teachin": "宣讲会"}


@dataclass
class CareerItem:
    """就业服务网首页一条条目。"""

    kind: str  # campus | jobfair | teachin
    item_id: str = ""
    title: str = ""
    url: str = ""
    date: str = ""  # 2026.10.19 形态（日 + 月拼合）
    time: str = ""  # 13:30-16:00（仅活动类）
    venue: str = ""
    status: str = ""  # 已举办 / 未开始 / 报名中…
    views: str = ""

    @property
    def kind_label(self) -> str:
        return _KIND_LABEL.get(self.kind, self.kind)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "kind_label": self.kind_label,
            "id": self.item_id,
            "title": self.title,
            "url": self.url,
            "date": self.date,
            "time": self.time,
            "venue": self.venue,
            "status": self.status,
            "views": self.views,
        }


def _strip_tags(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text)).strip()


def _parse_home(html: str) -> list[CareerItem]:
    """解析首页三区块（三种条目形态，2026-10-24 实测样例固化）。"""
    items: list[CareerItem] = []
    # 招聘公告：newsline 条目，line-time 两段 <p> + a.title
    for m in re.finditer(
        r'<span class="line-time"><p>(\d{1,2})</p>\s*<p>(20\d\d\.\d{1,2})</p></span>\s*'
        r'<a class="title"[^>]*title="([^"]*)"[^>]*href="/campus/view/id/(\d+)"',
        html,
    ):
        day, month, title, item_id = m.groups()
        items.append(CareerItem(
            kind="campus", item_id=item_id, title=title,
            url=f"{CAREER_SITE_BASE}/campus/view/id/{item_id}",
            date=f"{month}.{day}",
        ))
    # 招聘会 / 宣讲会：活动条目（line-time + view 链接 + 状态 + 时段 + 场地 + 浏览数）
    for m in re.finditer(
        r'<div class="line-time"><p>(\d{1,2})</p><p>(20\d\d\.\d{1,2})</p></div>(.*?)</li>',
        html,
        re.S,
    ):
        day, month, block = m.groups()
        link = re.search(r'href="/(jobfair|teachin)/view/id/(\d+)"', block)
        if not link:
            continue
        kind, item_id = link.group(1), link.group(2)
        title_html = re.search(r'class="title"[^>]*>(.*?)</a>', block, re.S)
        # 招聘会的状态 span 嵌在 <a> 内部，先摘掉再取纯标题
        title_raw = title_html.group(1) if title_html else ""
        title_raw = re.sub(r'<span[^>]*>(?:已举办|未开始|报名中|进行中)</span>', "", title_raw)
        title = _strip_tags(title_raw)
        status = ""
        sm = re.search(r'status-text[^>]*>([^<]+)<', block)
        if sm:
            status = sm.group(1).strip()
        else:  # 宣讲会的状态是内联样式 span（无 status-text 类）
            sm = re.search(r'<span style="[^"]*"[^>]*>(已举办|未开始|报名中|进行中)</span>', block)
            status = sm.group(1) if sm else ""
        tm = re.search(r'<span class="time">([^<]+)</span>', block)
        am = re.search(r'<span class="address">(?:<i[^>]*></i>)?([^<]+)</span>', block)
        vm = re.search(r'<span class="browse">.*?</i>(\d+)</span>', block, re.S)
        items.append(CareerItem(
            kind=kind, item_id=item_id, title=title,
            url=f"{CAREER_SITE_BASE}/{kind}/view/id/{item_id}",
            date=f"{month}.{day}", time=tm.group(1).strip() if tm else "",
            venue=am.group(1).strip() if am else "",
            status=status, views=vm.group(1) if vm else "",
        ))
    return items


def _fetch_home() -> str:
    session = http_session()
    session.trust_env = False  # 校方域名直连（本机代理不吃内网路由）
    session.headers["User-Agent"] = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
    )
    body, _etag = http_get_with_etag(
        f"{CAREER_SITE_BASE}/", cache_name="careersite/home.html", session=session
    )
    return body


def announcements(kind: str | None = None, keyword: str | None = None) -> list[CareerItem]:
    """首页三区块条目（可按类型/关键词过滤）。

    :param kind: ``campus``（招聘公告）/ ``jobfair``（招聘会）/ ``teachin``（宣讲会）。
    """
    try:
        html = _fetch_home()
    except Exception as exc:
        raise WestlakeError(f"就业服务网首页抓取失败：{exc.__class__.__name__}") from exc
    items = _parse_home(html)
    if not items:
        raise WestlakeError("就业服务网首页解析到 0 条——页面结构可能变化")
    if kind:
        items = [i for i in items if i.kind == kind]
    if keyword:
        kw = keyword.lower()
        items = [i for i in items if kw in i.title.lower() or kw in i.venue.lower()]
    return items


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

    @click.group(name="career", help="就业服务网：招聘公告 / 招聘会 / 宣讲会（首页公开面）。")
    def group() -> None:
        """``westlake career list``；详情页链接直通官网。"""

    @group.command(name="list")
    @click.option("-k", "--kind", default=None,
                  type=click.Choice(["campus", "jobfair", "teachin"]),
                  help="campus=招聘公告 jobfair=招聘会 teachin=宣讲会；缺省全部")
    @click.option("--keyword", "-q", default=None, help="标题/场地子串过滤")
    @handle
    def list_cmd(kind: str | None, keyword: str | None) -> None:
        """首页三区块条目（免登录公开面）。"""
        items = announcements(kind, keyword)
        if not items:
            click.echo("没有匹配的条目。")
            return
        for it in items:
            extra = " ".join(x for x in (it.status, it.time, it.venue) if x)
            click.echo(f"  [{it.kind_label}] {it.date} {it.title}" + (f"（{extra}）" if extra else ""))
            click.echo(f"    {it.url}")

    return group


cli_group = _cli()
