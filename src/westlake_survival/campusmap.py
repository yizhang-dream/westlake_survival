"""校园地图辅助（全公开数据，无凭据）。

只做**不登录就能拿到**的部分：

* 三个校区的地址、邮编与官方地图图片：复用
  :func:`westlake_survival.contact.campuses`（``contact_us`` 页的
  ``addressArr`` / ``trafficList`` / ``mapList``）。铜鉴湖园区官网不提供
  地图，对应 ``map_url`` 为 ``None``。
* 校园全景：官网「校园生活 → 云栖·云谷」页
  （``campus_life/visit_westlake/``，组件 ``visitWestlake``）的 ``virtualObj``
  给出 720yun 全景外链，云谷、云栖各一条。
* 到校交通：同样来自上述两页的 ``trafficList``，含自驾路径、地铁与公交的
  首末班时间。

设计取舍
========
学校另有一套独立系统 ``map.westlake.edu.cn``（西湖大学电子地图系统），
2026-10-23 实测：根路径 302 到 ``/login``（用户名 + 密码，另有「切换登录
方式」），唯一匿名接口 ``POST /api/nsc/uc/ndConfig/findNdConfigListByKeys``
返回 ``{"code":"10041","msg":"非法的客户端,请重新请求"}``——请求需客户端
签名。本模块**不接**该系统：它需要本人账号与签名逆向，属于另一个凭据域，
也不应绕过权限。

编码与解析：两页均无 ``charset`` 头，取文本后统一走
:func:`_repair_mojibake` 兜底；组件块里混有 ``function`` 回调，先
:func:`~westlake_survival._trs.component_script` 截块再按键解析。
"""

from __future__ import annotations

import functools
import logging
from dataclasses import dataclass, field
from urllib.parse import urljoin

import click
import requests

from westlake_survival._cache import http_get_with_etag
from westlake_survival._net import DEFAULT_TIMEOUT, http_session
from westlake_survival._trs import component_script, object_of
from westlake_survival.contact import CAMPUS_NAMES, CampusInfo, campuses as contact_campuses
from westlake_survival.exceptions import OffCampusError, ParseError, WestlakeError, is_offcampus

__all__ = [
    "VISIT_URL",
    "VISIT_COMPONENT",
    "CACHE_NAME",
    "MAP_SYSTEM_URL",
    "Panorama",
    "MapCampus",
    "parse_panoramas",
    "campus_map",
    "cli_group",
]

logger = logging.getLogger(__name__)

#: 「校园生活 → 云栖·云谷」页（校园全景与首末班来源）。
VISIT_URL = "https://www.westlake.edu.cn/campus_life/visit_westlake/"

#: 该页组件构造函数名。
VISIT_COMPONENT = "visitWestlake"

#: 本地缓存文件名。
CACHE_NAME = "map/visit_westlake.html"

#: 学校电子地图系统的入口（SPA 外壳匿名可取；页面内的会话状态由浏览器自己管理）。
MAP_SYSTEM_URL = "https://map.westlake.edu.cn/"


# --------------------------------------------------------------------------- #
# 数据模型
# --------------------------------------------------------------------------- #
@dataclass
class Panorama:
    """一条校园全景外链（720yun）。"""

    title: str
    url: str
    img_url: str = ""


@dataclass
class MapCampus:
    """一个校区的地图辅助信息。

    :attr:`map_url` 为 ``None`` 表示官网没给该校区地图图（铜鉴湖）。
    :attr:`panoramas` 为空表示该校区没有全景外链。
    """

    name: str
    address: str = ""
    postcode: str = ""
    map_url: str | None = None
    panoramas: list[Panorama] = field(default_factory=list)
    traffic: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# 解析与网络
# --------------------------------------------------------------------------- #
def _repair_mojibake(text: str) -> str:
    """修复"UTF-8 被当成 ISO-8859-1 解码"的乱码（幂等）。"""
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def parse_panoramas(html: str, *, base_url: str = VISIT_URL) -> dict[str, list[Panorama]]:
    """解析「校园全景」区块，返回 ``{校区名: [Panorama, ...]}``。

    ``virtualObj.list`` 的条目形如
    ``{text: "云谷校区", imgUrl: "./virtual_visit/202309/x.png", url: "https://www.720yun.com/vr/..."}``，
    相对图片地址按 ``base_url`` 补全；校区名去掉「校区」后缀以对齐
    :data:`~westlake_survival.contact.CAMPUS_NAMES`。

    Raises:
        ParseError: 页面里找不到组件或 ``virtualObj``。
    """
    text = _repair_mojibake(html)
    block = component_script(text, VISIT_COMPONENT)
    if not block:
        raise ParseError(f"页面中找不到组件 {VISIT_COMPONENT!r}，页面结构可能已变化：{base_url}")
    raw = object_of(block, "virtualObj")
    result: dict[str, list[Panorama]] = {}
    for entry in raw.get("list") or []:
        if not isinstance(entry, dict):
            continue
        url = str(entry.get("url") or "").strip()
        if not url:
            continue
        name = str(entry.get("text") or "").strip()
        normalized = _normalize_campus(name)
        img = str(entry.get("imgUrl") or "").strip()
        panorama = Panorama(
            title=name,
            url=url,
            img_url=urljoin(base_url, img) if img else "",
        )
        result.setdefault(normalized, []).append(panorama)
    if not result:
        raise ParseError(f"校园全景区块为空：{base_url}")
    return result


def _normalize_campus(raw: str) -> str:
    """把「云谷校区」「云栖校区（铜鉴湖园区）」等写法归一到 :data:`CAMPUS_NAMES`。"""
    text = raw.strip()
    if "铜鉴湖" in text:
        return "铜鉴湖"
    for name in CAMPUS_NAMES:
        if name in text:
            return name
    return text


def _fetch_visit_html(
    *,
    refresh: bool = False,
    timeout: float | None = None,
    session: requests.Session | None = None,
) -> str:
    """抓「校园生活」页 HTML（带缓存与乱码兜底）。"""
    if refresh:
        try:
            from westlake_survival import _cache

            path = _cache.cache_path(CACHE_NAME)
            if path.exists():
                path.unlink()
        except OSError:  # 缓存删不掉不应阻断加载
            logger.debug("删除校园地图缓存失败", exc_info=True)
    session = session if session is not None else http_session()
    try:
        body, _etag = http_get_with_etag(
            VISIT_URL,
            cache_name=CACHE_NAME,
            session=session,
            timeout=timeout if timeout is not None else DEFAULT_TIMEOUT,
        )
    except requests.HTTPError as exc:
        response = exc.response
        if response is not None and getattr(response, "status_code", 0) == 403 and is_offcampus(response):
            raise OffCampusError(f"校园生活页拒绝访问（403）：{VISIT_URL}") from exc
        status = getattr(response, "status_code", "?")
        raise ParseError(f"校园生活页返回 HTTP {status}：{VISIT_URL}") from exc
    except requests.Timeout as exc:
        raise WestlakeError(
            f"校园生活页请求超时（{timeout if timeout is not None else DEFAULT_TIMEOUT}s）：{VISIT_URL}"
        ) from exc
    except requests.RequestException as exc:
        raise WestlakeError(f"校园生活页请求失败：{exc}") from exc
    return _repair_mojibake(body)


# --------------------------------------------------------------------------- #
# 公开 API
# --------------------------------------------------------------------------- #
def campus_map(
    campus: str | None = None,
    *,
    refresh: bool = False,
    timeout: float | None = None,
    session: requests.Session | None = None,
) -> list[MapCampus]:
    """返回校区的地址、地图图片、校园全景与到校交通。

    数据来自两个公开页，任一失败都按源降级：全景页失败时仍返回地址与地图
    （``panoramas`` 为空），只有两源全失败才抛异常。

    Args:
        campus: 校区名（``云谷`` / ``云栖`` / ``铜鉴湖``，支持子串）；``None`` 表示全部。
        refresh: 为 ``True`` 时先清缓存。
        timeout: 请求超时（秒）。
        session: 可注入的 :class:`requests.Session`（测试用）。

    Returns:
        :class:`MapCampus` 列表，顺序与官网一致（云谷、云栖、铜鉴湖）。

    Raises:
        WestlakeError: 两个数据源都失败时抛最后一个异常。
        ValueError: ``campus`` 不是已知校区名。
    """
    if campus and not any(campus in name for name in CAMPUS_NAMES):
        raise ValueError(f"未知校区 {campus!r}，可选：{'、'.join(CAMPUS_NAMES)}")

    errors: list[Exception] = []
    infos: list[CampusInfo] = []
    try:
        infos = contact_campuses(refresh=refresh, session=session, timeout=timeout)
    except WestlakeError as exc:
        errors.append(exc)

    panoramas: dict[str, list[Panorama]] = {}
    try:
        panoramas = parse_panoramas(
            _fetch_visit_html(refresh=refresh, timeout=timeout, session=session)
        )
    except WestlakeError as exc:
        errors.append(exc)

    if not infos and errors:
        raise errors[-1]

    result: list[MapCampus] = []
    for info in infos:
        result.append(
            MapCampus(
                name=info.name,
                address=info.address,
                postcode=info.postcode,
                map_url=info.map_url,
                panoramas=list(panoramas.get(info.name, [])),
                traffic=list(info.traffic),
            )
        )
    if campus:
        result = [item for item in result if campus in item.name]
    return result


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _handle_errors(func):
    """把 :class:`WestlakeError` / :class:`ValueError` 转成中文提示 + 退出码 1。"""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (WestlakeError, ValueError) as exc:
            click.secho(f"错误：{exc}", fg="red", err=True)
            if isinstance(exc, OffCampusError):
                click.secho(
                    "提示：该服务仅校园网/VPN 内可达，请先连接西湖大学 VPN："
                    "https://vpn.westlake.edu.cn/",
                    err=True,
                )
            raise SystemExit(1) from exc

    return wrapper


@click.group(name="map", help="校园地图辅助：地址、地图图片、校园全景与到校交通。", invoke_without_command=True)
@click.option("--campus", default=None, help="校区：云谷 / 云栖 / 铜鉴湖（可只写片段）。")
@click.option("--refresh", is_flag=True, help="忽略本地缓存，强制重新抓取。")
@click.pass_context
def cli_group(ctx: click.Context, campus: str | None, refresh: bool) -> None:
    """``westlake map [--campus 云谷]``。"""
    if ctx.invoked_subcommand is not None:
        return
    _run_map(campus=campus, refresh=refresh)


@cli_group.command(name="login")
@click.option("--user", prompt="地图系统账号", help="电子地图账号（与教务 SIS 不同源）。")
@click.option(
    "--password",
    prompt=True,
    hide_input=True,
    confirmation_prompt=False,
    help="电子地图密码；交互输入不回显。",
)
@_handle_errors
def map_login(user: str, password: str) -> None:
    """配置电子地图账号：验证一次，之后自动复用（令牌缓存 + 自动重登）。"""
    from westlake_survival import mapapi

    token = mapapi.login(user, password)
    stored_in_keyring = mapapi.save_map_credentials(user, password)
    mapapi._save_token(token)  # noqa: SLF001 - 同包内部写在登录成功后落盘
    where = "系统钥匙串" if stored_in_keyring else str(mapapi.cred_path())
    click.echo(f"登录成功，凭据已保存到{where}；令牌已缓存，后续命令自动复用。")


@cli_group.command(name="poi")
@click.argument("keyword", required=False)
@click.option("--limit", type=int, default=20, show_default=True, help="最多显示条数。")
@click.option("--endpoint", "endpoint_part", default=None, help="只查某类端点（子串，如 area/building）。")
def map_poi(keyword: str | None, limit: int, endpoint_part: str | None) -> None:
    """离线查楼宇/设施/区域（读随包数据集，不需要登录）。

    数据由维护者用一次性抓取脚本固化，见 tools/capture_map.py。
    """
    from westlake_survival import mapdata

    if not mapdata.dataset_available():
        click.echo("地图数据集尚未生成（当前只有公开的地图图片与全景）。")
        click.echo("生成方式：维护者用有效账号跑一次 tools/capture_map.py，再跑 tools/build_map_dataset.py。")
        click.echo("自己已配置账号时也可先 `westlake map login`，再联系维护者导出。")
        return
    dataset = mapdata.load_dataset()
    if keyword:
        hits = dataset.search(keyword, limit=limit)
    else:
        hits = dataset.records(endpoint_part)[:limit]
    click.echo(f"数据集：{len(dataset)} 条记录，生成于 {dataset.generated_at or '未知'}")
    if not hits:
        click.echo("没有匹配的记录。")
        return
    for hit in hits:
        click.echo(f"  {hit.brief()}　[{hit.endpoint}]")


@cli_group.command(name="status")
@_handle_errors
def map_status() -> None:
    """查看电子地图账号与令牌状态（只报有无，不回显凭据）。"""
    from westlake_survival import mapapi

    status = mapapi.map_cred_status()
    click.echo("电子地图（map.westlake.edu.cn）状态：")
    for name, has in status["sources"].items():
        click.echo(f"  - {name}：{'有' if has else '无'}")
    click.echo(f"  - 可用凭据：{'有' if status['has_credentials'] else '无'}")
    click.echo(f"  - 令牌有效：{'是' if status['token_valid'] else '否'}")
    if status["token_expires_at"]:
        click.echo(f"  - 令牌到期：{status['token_expires_at']}")
    if not status["has_credentials"]:
        click.echo("提示：执行一次 `westlake map login` 即可长期使用（与教务密码不同源）。")


@cli_group.command(name="logout")
def map_logout() -> None:
    """删除已保存的电子地图凭据与令牌缓存。"""
    from westlake_survival import mapapi

    mapapi.delete_map_credentials()
    click.echo("已删除电子地图凭据与令牌缓存。")


@_handle_errors
def _run_map(campus: str | None, refresh: bool) -> None:
    """执行查询并打印每个校区的地址、地图、全景与交通。"""
    items = campus_map(campus, refresh=refresh)
    if not items:
        click.echo("未找到匹配的校区。")
        return
    for index, item in enumerate(items):
        if index:
            click.echo("")
        click.echo(f"== {item.name}校区 ==")
        click.echo(f"地址：{item.address or '—'}　邮编：{item.postcode or '—'}")
        click.echo(f"地图：{item.map_url or '官网未提供'}")
        if item.panoramas:
            for panorama in item.panoramas:
                click.echo(f"全景：{panorama.title}　{panorama.url}")
        else:
            click.echo("全景：无")
        if item.traffic:
            click.echo("交通：")
            for line in item.traffic:
                click.echo(f"  - {line}")
        else:
            click.echo("交通：—")
    click.echo("")
    click.echo(f"电子地图：{MAP_SYSTEM_URL}（浏览器会保留自己的会话；首次可能需要登录一次）")
    click.echo("说明：本命令输出的是官网静态地图图片与全景链接，不读取任何账号。")
