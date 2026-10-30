"""西湖大学大型仪器设备共享平台（share.westlake.edu.cn）只读检索。

系统背景
========
西湖大学科研公共平台群（理学/工学/医学/生科/微纳/电镜等）的大型科学仪器
接入基理（Genee）大型仪器共享管理系统：
- 站点：https://share.westlake.edu.cn/genee/
- 涵盖透射电镜、冷冻电镜、有机/无机质谱、核磁共振、激光共焦显微镜、超净间微纳设备等；
- 开放免登录接口提供仪器名称、型号、放置房间（学术环E区等）、联系老师与预约/送样入口。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urljoin

import click
import requests
from bs4 import BeautifulSoup

from westlake_survival._cache import load_cached, save_cached
from westlake_survival._net import DEFAULT_TIMEOUT
from westlake_survival.discovery import direct_session
from westlake_survival.exceptions import WestlakeError

__all__ = [
    "SHARE_BASE_URL",
    "Instrument",
    "search_instruments",
    "cli_group",
]

SHARE_BASE_URL = "https://share.westlake.edu.cn/genee/"
_EQUIPMENTS_API = "AJAX/Wias/Equipment/getEquipments/"
_CACHE_TTL = 3600 * 24  # 仪器信息 24 小时本地缓存


@dataclass(frozen=True)
class Instrument:
    """一台大型科研仪器设备。"""

    id: str
    name: str
    contact: str
    address: str
    phone: str
    url: str
    actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clean_text(text: str) -> str:
    """清理连续空白与不可见空格。"""
    cleaned = text.replace("\xa0", " ").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", cleaned).strip()


def _parse_box(box: BeautifulSoup) -> Instrument | None:
    heading_link = box.select_one(".media-heading a")
    if not heading_link:
        return None
    name = _clean_text(heading_link.get_text())
    href = heading_link.get("href", "")
    url = urljoin(SHARE_BASE_URL, href)
    item_id = url.rstrip("/").split("/")[-1] if url else ""

    text = box.get_text("\n")
    contact = ""
    address = ""
    phone = ""

    for line in text.splitlines():
        line = _clean_text(line)
        if "联系人:" in line:
            contact = line.split("联系人:", 1)[-1].strip()
        elif "地 址:" in line or "地址:" in line:
            address = line.split("址:", 1)[-1].strip()
        elif "电 话:" in line or "电话:" in line:
            phone = line.split("话:", 1)[-1].strip()

    actions = [btn.get_text(strip=True) for btn in box.select(".media-heading a.btn, a.btn")]
    actions = [a for a in actions if a and a != name]

    return Instrument(
        id=item_id,
        name=name,
        contact=contact,
        address=address,
        phone=phone,
        url=url,
        actions=actions,
    )


def search_instruments(
    keyword: str = "",
    *,
    limit: int = 20,
    refresh: bool = False,
    timeout: float | None = None,
) -> list[Instrument]:
    """按关键词检索大型科研仪器（免登录）。

    Args:
        keyword: 仪器名称、类型关键词（如「电镜」、「质谱」、「核磁」）；为空时返回综合排序清单。
        limit: 最多返回条数。
        refresh: 忽略本地缓存重新请求。
        timeout: 超时秒数。
    """
    keyword_clean = keyword.strip()
    cache_key = f"instruments/search_{keyword_clean or 'all'}.json"

    if not refresh:
        cached = load_cached(cache_key, _CACHE_TTL)
        if cached and isinstance(cached, list):
            items = [Instrument(**row) for row in cached]
            return items[:limit]

    session = direct_session()
    results: list[Instrument] = []
    seen_ids: set[str] = set()

    # 每页 10 条，分页拉取直到凑足 limit
    start = 0
    max_to_fetch = min(max(1, limit), 100)

    while len(results) < max_to_fetch:
        target_url = urljoin(SHARE_BASE_URL, f"{_EQUIPMENTS_API}{start}")
        data = {"ajax_form[keywords]": keyword_clean, "ajax_form[m]": ""}
        try:
            resp = session.post(
                target_url,
                data=data,
                timeout=timeout or DEFAULT_TIMEOUT,
                verify=False,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            stale = load_cached(cache_key, 10**9)
            if stale and isinstance(stale, list):
                return [Instrument(**row) for row in stale][:limit]
            raise WestlakeError(f"请求大仪共享平台失败：{exc}") from exc

        html = resp.text
        if not html.strip() or "media-box" not in html:
            break

        soup = BeautifulSoup(html, "html.parser")
        boxes = soup.select(".media-box")
        if not boxes:
            break

        new_count = 0
        for box in boxes:
            item = _parse_box(box)
            if item and item.id not in seen_ids:
                seen_ids.add(item.id)
                results.append(item)
                new_count += 1
                if len(results) >= max_to_fetch:
                    break

        if new_count == 0 or len(boxes) < 10:
            break
        start += 10

    if results:
        save_cached(cache_key, [item.to_dict() for item in results])

    return results[:limit]


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _cli():
    import functools

    def handle(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except WestlakeError as exc:
                click.secho(f"错误：{exc}", fg="red", err=True)
                raise SystemExit(1) from exc

        return wrapper

    @click.group(name="instrument", help="大型仪器共享平台：检索科研仪器、实验室地点、联系人与预约入口。")
    def group() -> None:
        """``westlake instrument search|list``。"""

    @group.command(name="search")
    @click.argument("keyword")
    @click.option("--limit", default=10, show_default=True, help="返回条数上限。")
    @click.option("--refresh", is_flag=True, help="强制刷新缓存。")
    @handle
    def search_cmd(keyword: str, limit: int, refresh: bool) -> None:
        """按仪器名称/分类搜索（如「质谱」、「冷冻电镜」、「核磁」）。"""
        items = search_instruments(keyword, limit=limit, refresh=refresh)
        if not items:
            click.echo(f"未找到与「{keyword}」匹配的大型仪器。")
            return
        click.echo(f"找到 {len(items)} 台匹配仪器：")
        for i, item in enumerate(items, 1):
            click.secho(f"\n{i}. {item.name}", bold=True, fg="bright_cyan")
            click.echo(f"   房间位置：{item.address or '—'}")
            click.echo(f"   联系老师：{item.contact or '—'}（{item.phone or '无电话'}）")
            click.echo(f"   预约链接：{item.url}")

    @group.command(name="list")
    @click.option("--limit", default=15, show_default=True, help="返回条数上限。")
    @click.option("--refresh", is_flag=True, help="强制刷新缓存。")
    @handle
    def list_cmd(limit: int, refresh: bool) -> None:
        """浏览学校大型仪器共享平台最新仪器列表。"""
        items = search_instruments("", limit=limit, refresh=refresh)
        click.echo(f"大型仪器列表（前 {len(items)} 台）：")
        for i, item in enumerate(items, 1):
            click.echo(f"  [{item.id}] {item.name:<26}  {item.address:<18}  {item.contact} ({item.phone})")

    return group


cli_group = _cli()
