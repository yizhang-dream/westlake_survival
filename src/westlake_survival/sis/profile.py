"""SIS 个人资料页读取：个人信息 / 学籍数据 / 扩展信息。

数据源（2026-09-23 登录态实测，三个组件页均为 ``EMPLOYEE/SA/c/`` 前缀）::

    WL_CUSTOMIZE_MENU.WL_PERS_DATA_FL.GBL?page=WL_PERS_DATA_FL&NavColl=true   # 个人信息
    WL_CUSTOMIZE_MENU.WL_ACADPRG_DATA_FL.GBL?page=WL_ACADPRG_DATA_FL          # 学籍数据
    WL_CUSTOMIZE_MENU.WL_EXTINFO_DATA_FL.GBL?page=WL_EXTINFO_DATA_FL          # 扩展信息

返回「字典 + 键名清单」而非 dataclass
=====================================
这三个页面的字段集合由学校 PeopleSoft 配置决定，**随配置漂移**：同一个组件
页在不同角色/不同年份可能多出或少掉若干 ``label-value`` 对，网格数量与列名
同理。为 dataclass 固化字段会在页面漂移时直接构造失败，故本模块只返回
``dict``，并在各函数 docstring 里列出**实测到的键名**（键名可写，值属个人
信息不写）。调用方按需 ``.get(key)``，缺键即缺字段，不做臆造默认。

解析委托给 :mod:`westlake_survival.sis.pages`（登录态抓页 +
``parse_label_values`` / ``parse_fluid_grid``），本模块只做页面到 dict 的映射。

页面结构
========
个人信息 / 学籍页是纯 ``ps_box-label`` + ``ps_box-value`` 页面（无网格）；
扩展信息页除 label-value 外还含多张 fluid 网格（紧急联系人、学历、保险、
奖惩），故后两者的返回结构为::

    {"fields": {标签: 值, ...}, "grids": {网格 id: [行字典, ...]}}

其中 ``grids`` 只包含**页面实际存在**的网格：已知网格 id 在页面上找不到时
（配置未启用 / 结构变化）整条跳过，不影响其余字段。
"""

from __future__ import annotations

import functools

import click

from westlake_survival.exceptions import (
    OffCampusError,
    ParseError,
    WestlakeError,
)
from westlake_survival.sis import pages

__all__ = [
    "PERSONAL_INFO_COMPONENT",
    "PERSONAL_INFO_QUERY",
    "ACADEMIC_RECORD_COMPONENT",
    "ACADEMIC_RECORD_QUERY",
    "EXTENDED_INFO_COMPONENT",
    "EXTENDED_INFO_QUERY",
    "EXTENDED_INFO_GRID_IDS",
    "personal_info",
    "academic_record",
    "extended_info",
    "cli_group",
]

#: 个人信息页组件。
PERSONAL_INFO_COMPONENT = "WL_CUSTOMIZE_MENU.WL_PERS_DATA_FL.GBL"

#: 个人信息页查询串（``NavColl=true`` 展开折叠区块）。
PERSONAL_INFO_QUERY = "page=WL_PERS_DATA_FL&NavColl=true"

#: 学籍数据页组件。
ACADEMIC_RECORD_COMPONENT = "WL_CUSTOMIZE_MENU.WL_ACADPRG_DATA_FL.GBL"

#: 学籍数据页查询串。
ACADEMIC_RECORD_QUERY = "page=WL_ACADPRG_DATA_FL"

#: 扩展信息页组件。
EXTENDED_INFO_COMPONENT = "WL_CUSTOMIZE_MENU.WL_EXTINFO_DATA_FL.GBL"

#: 扩展信息页查询串。
EXTENDED_INFO_QUERY = "page=WL_EXTINFO_DATA_FL"

#: 扩展信息页的 fluid 网格 id（实测存在；缺省未启用时解析被跳过）。
EXTENDED_INFO_GRID_IDS = (
    "EXT_ORG_TBL",  # 紧急联系人 / 工作单位
    "WL_EDUEXPMDY_VW",  # 学历经历
    "WL_INSURMDY_VW",  # 保险
    "WL_REWPUNMDY_VW",  # 奖惩
)


# --------------------------------------------------------------------------- #
# 解析
# --------------------------------------------------------------------------- #
def personal_info() -> dict[str, str]:
    """取个人信息页的全部 ``label-value`` 字段。

    Returns:
        标签到值的映射。

    Raises:
        AuthError: 会话失效。
        OffCampusError: 校外访问被拒。
        ActionError: 组件未授权。
        ParseError: 页面结构变化导致解析失败。

    实测键名（11 个，2026-09-23）：
        ``Admission Category`` / ``BirthDate`` / ``Campus ID`` /
        ``Certificate No.`` / ``Certificate Type`` / ``Country`` /
        ``Ethnic Group`` / ``Gender`` / ``Learning Style`` / ``Name`` /
        ``Train Ticket Section``。空值字段不产出（键可能缺失）。
    """
    html = pages.fetch_page(PERSONAL_INFO_COMPONENT, query=PERSONAL_INFO_QUERY)
    return pages.parse_label_values(html)


def _fields_and_grids(
    component: str, query: str, grid_ids: tuple[str, ...] = ()
) -> dict:
    """抓页并组装 ``{"fields": ..., "grids": ...}``。

    ``grid_ids`` 中在页面上找不到的网格（``ParseError``）整条跳过——扩展信息
    页的网格可随学校配置增减，缺一张不应让整页失败。
    """
    html = pages.fetch_page(component, query=query)
    grids: dict[str, list[dict]] = {}
    for grid_id in grid_ids:
        try:
            grids[grid_id] = pages.parse_fluid_grid(html, grid_id)
        except ParseError:
            continue
    return {"fields": pages.parse_label_values(html), "grids": grids}


def academic_record() -> dict:
    """取学籍数据页：``label-value`` 字段 + 页面上的网格。

    Returns:
        ``{"fields": {标签: 值}, "grids": {网格 id: [行字典]}}``。实测该页
        **无网格**，故 ``grids`` 通常为空字典；保留结构以应对配置漂移。

    Raises:
        AuthError: 会话失效。
        OffCampusError: 校外访问被拒。
        ActionError: 组件未授权。
        ParseError: 页面结构变化导致解析失败。

    实测 ``fields`` 键名（20 个，2026-09-23）：
        ``Admissions ID No`` / ``Admissions Type`` / ``College`` /
        ``Current Years Of Study`` / ``Date of Enrollment`` /
        ``Degree Type`` / ``Expected Graduation Date`` / ``Grade`` /
        ``Length of Program`` / ``Major`` / ``Primary Discipline`` /
        ``Program Level`` / ``Program Type`` / ``School`` / ``Status`` /
        ``Student Category`` / ``Student Status`` / ``Supervisor`` /
        ``Supervisor ID`` / ``Year of Admissions``。
    """
    return _fields_and_grids(ACADEMIC_RECORD_COMPONENT, ACADEMIC_RECORD_QUERY)


def extended_info() -> dict:
    """取扩展信息页：``label-value`` 字段 + 多张 fluid 网格。

    Returns:
        ``{"fields": {标签: 值}, "grids": {网格 id: [行字典]}}``；``grids``
        只含页面实际存在的网格（见 :data:`EXTENDED_INFO_GRID_IDS`）。

    Raises:
        AuthError: 会话失效。
        OffCampusError: 校外访问被拒。
        ActionError: 组件未授权。
        ParseError: 页面结构变化导致解析失败。

    实测 ``fields`` 键名（16 个，2026-09-23）：
        ``Bank Of Deposit`` / ``Campus Accommodation (Yes/No)`` /
        ``Conselor Name`` / ``Dormitory Information`` / ``E-mail Address`` /
        ``Home Address`` / ``Hukou Type`` / ``Marital Status`` /
        ``Native Place`` / ``Personal Email`` / ``Phone Number`` /
        ``Phone Of Conselor`` / ``Place Of Origin`` / ``Politics`` /
        ``Registered Residence`` / ``Religious Belief``。

    实测网格列名：
        - ``EXT_ORG_TBL``：``Birth Date`` / ``Contact Name`` /
          ``Emergency Contact`` / ``Employer(Institute or Company)`` /
          ``Job Title`` / ``Relationship`` / ``Telephone``；
        - ``WL_EDUEXPMDY_VW``：``Career`` / ``Graduation School`` /
          ``Graduation Time`` / ``专业``；
        - ``WL_INSURMDY_VW``：``Insurance Name`` / ``Insurance Number`` /
          ``Insurance Place`` / ``Insurance Range`` / ``Purchase Date``；
        - ``WL_REWPUNMDY_VW``：``Release Date`` /
          ``Reward And Punishment Name`` /
          ``Reward And Punishment Organization/Unit`` /
          ``Reward And Punishment Type``。
    """
    return _fields_and_grids(
        EXTENDED_INFO_COMPONENT, EXTENDED_INFO_QUERY, EXTENDED_INFO_GRID_IDS
    )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _handle_errors(func):
    """装饰器：把 :class:`WestlakeError` 转成中文提示 + 退出码 1。"""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except WestlakeError as exc:
            click.secho(f"错误：{exc}", fg="red", err=True)
            if isinstance(exc, OffCampusError):
                click.secho(
                    "提示：该服务仅校园网/VPN 内可达，请先连接西湖大学 VPN："
                    "https://vpn.westlake.edu.cn/",
                    err=True,
                )
            raise SystemExit(1) from exc

    return wrapper


@click.group(name="profile", help="个人信息：个人资料 / 学籍 / 扩展信息。")
def cli_group() -> None:
    """``westlake profile`` 命令组。"""


def _print_pairs(fields: dict[str, str]) -> None:
    """按标签排序打印键值表；空字典打印占位提示。"""
    from westlake_survival.cli.main import _print_table

    if not fields:
        click.echo("未解析到任何字段（页面结构可能已变化）。")
        return
    _print_table(sorted(fields.items()), ("字段", "值"))


@cli_group.command(name="info")
@_handle_errors
def profile_info() -> None:
    """打印个人信息页字段。"""
    _print_pairs(personal_info())


def _print_record(data: dict) -> None:
    """打印 ``{"fields": ..., "grids": ...}``：先字段表，再逐网格列表。"""
    from westlake_survival.cli.main import _print_table

    _print_pairs(data.get("fields", {}))
    grids = data.get("grids", {})
    if not grids:
        click.echo("（无网格数据）")
        return
    for grid_id, rows in grids.items():
        click.echo(f"【{grid_id}】")
        if not rows:
            click.echo("（空）")
            continue
        headers = list(rows[0].keys())
        _print_table([[row.get(h, "") for h in headers] for row in rows], headers)


@cli_group.command(name="academic")
@_handle_errors
def profile_academic() -> None:
    """打印学籍数据页字段与网格。"""
    _print_record(academic_record())


@cli_group.command(name="extended")
@_handle_errors
def profile_extended() -> None:
    """打印扩展信息页字段与多张网格。"""
    _print_record(extended_info())