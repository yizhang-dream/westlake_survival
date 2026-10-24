"""能力清单：把 CLI / MCP / WebUI 三处入口汇总成可展示的数据。

用途
====
``westlake webui`` 自带一个前端，但此前各页面是分散的功能页，没有一个地方
能回答「这套工具到底能干什么、哪些要账号」。本模块做三件事：

1. 从 :mod:`westlake_survival.cli.main` 的 click 命令树里取全部命令组与子命令；
2. 从 :mod:`westlake_survival.mcp_server` 取全部 MCP 工具及其参数；
3. 附加 WebUI 页面清单与「是否需要凭据」的判定，输出统一的
   :class:`Capability` 列表（供 ``/capabilities`` 页与 ``/api/capabilities``）。

判定口径
========
需要凭据的只有三类，其余全部是官网公开数据：

* SIS 类（``sis`` / ``sis-evals`` / ``profile`` / ``records`` / ``aid``）与
  依赖它的 ``lib loans`` / ``pms jobs``：教务账号 + 校园网/VPN；
* Canvas 类：``WESTLAKE_CANVAS_TOKEN``；
* 电子地图的楼宇 POI（若将来有数据源）：需 ``westlake map login``；
  当前 ``map`` 的公开部分不需要。

``webui`` 自身也被列进来——它就是承载这份清单的前端。
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "Capability",
    "WEB_PAGES",
    "AUTH_GROUPS",
    "collect",
    "as_dict",
]

#: 需要凭据的 CLI 命令组 → 凭据说明。
AUTH_GROUPS = {
    "sis": "教务账号 + 校园网/VPN（westlake sso creds set）",
    "sis-evals": "教务账号 + 校园网/VPN",
    "profile": "教务账号 + 校园网/VPN",
    "records": "教务账号 + 校园网/VPN",
    "aid": "教务账号 + 校园网/VPN",
    "lib": "借阅部分需教务账号 + 校园网/VPN；书目检索公开",
    "pms": "打印任务需打印系统账号；网点列表公开",
    "canvas": "Canvas API 令牌（WESTLAKE_CANVAS_TOKEN）",
    "sso": "仅用于配置教务凭据本身",
}

#: WebUI 页面清单：路径、标题、说明、是否需要凭据。
WEB_PAGES = (
    ("/", "仪表盘", "日期 / 周次 / 天气 / 最近事件 / 下班车 / 作业", False),
    ("/shuttle", "班车", "三校区班车时刻与下一班", False),
    ("/calendar", "校历", "学期周次与校历事件；班车/课表 ICS 订阅入口", False),
    ("/events", "讲座活动", "讲座 / 会议 / 演出预告", False),
    ("/faculty", "教师", "四源聚合的教师名录与详情", False),
    ("/news", "新闻", "西湖新闻按分类浏览", False),
    ("/program", "培养方案", "培养理念、课程体系、8 专业学分要求与课程表", False),
    ("/courses", "通识课程", "三类通识课程清单（99 门）与筛选", False),
    ("/map", "地图", "校区地址、官方地图图片、720yun 全景、到校交通", False),
    ("/dining", "餐饮", "食堂 / 咖啡 / 其他服务点", False),
    ("/search", "搜索", "官网全站搜索", False),
    ("/capabilities", "能力总览", "本页：CLI + MCP + WebUI 全部入口", False),
    ("/sis", "学业", "课表/成绩/考试/待评教（教务凭据）", True),
    ("/canvas", "Canvas", "在修课程与未来截止（令牌或统一密码）", True),
    ("/careers", "招聘", "官网岗位 + 就业服务网三区块（招聘公告/招聘会/宣讲会，公开）", False),
    ("/hpc", "集群", "HPC 队列配置表（公开）与 Portal 入口", False),
    ("/finance", "财务", "报销/制度/科研经费文档（公开）", False),
    ("/mirrors", "镜像", "开源镜像仓库目录与换源 Help", False),
    ("/schools", "学院", "五学院官网最新新闻聚合（理/生/工/医/理论院）", False),
    ("/institute", "理论院", "理论科学研究院新闻与学术活动（公开）", False),
    ("/services", "服务", "全站服务注册表（盘点快照+在线普查）", False),
    ("/scholar", "学术", "订阅数据库注册表 / CARSI 联盟 / DOI 全文（校园 IP 探测）", False),
    ("/affairs", "办事", "办事大厅 176 个流程应用目录 + HPC/预约/镜像入口", False),
    ("/setup", "设置", "网页端账号配置：学号密码一次填入，自动检测各服务", True),
)


@dataclass
class Capability:
    """一个可展示的能力条目。

    :attr:`kind` 取 ``cli`` / ``mcp`` / ``web``；:attr:`commands` 只对 CLI 组
    有意义（子命令名与一句话说明）。
    """

    name: str
    summary: str
    kind: str
    needs_auth: bool = False
    auth_hint: str = ""
    example: str = ""
    commands: list[tuple[str, str]] = field(default_factory=list)
    params: list[str] = field(default_factory=list)


def _clean(text: str | None) -> str:
    """压平 help 文本里的换行（click 的 help 常带二次缩进）。"""
    if not text:
        return ""
    return " ".join(str(text).split())


def _cli_capabilities() -> list[Capability]:
    """从 click 命令树收集 CLI 能力。"""
    from westlake_survival.cli.main import cli

    items: list[Capability] = []
    for name, command in sorted(cli.commands.items()):
        subs: list[tuple[str, str]] = []
        for sub_name, sub in sorted(getattr(command, "commands", {}).items()):
            subs.append((sub_name, _clean(sub.get_short_help_str(limit=60))))
        summary = _clean(command.get_short_help_str(limit=80)) or _clean(command.help)
        auth_hint = AUTH_GROUPS.get(name, "")
        items.append(
            Capability(
                name=f"westlake {name}",
                summary=summary,
                kind="cli",
                needs_auth=bool(auth_hint),
                auth_hint=auth_hint,
                example=f"westlake {name}" + (" --help" if subs else ""),
                commands=subs,
            )
        )
    return items


def _mcp_capabilities() -> list[Capability]:
    """从 MCP 工具表收集能力。"""
    from westlake_survival.mcp_server import list_tools

    items: list[Capability] = []
    for tool in list_tools():
        schema = tool.get("inputSchema") or {}
        params = sorted((schema.get("properties") or {}).keys())
        name = str(tool.get("name") or "")
        needs_auth = name.startswith(("sis_", "canvas_")) or name == "canvas_submit"
        items.append(
            Capability(
                name=f"mcp:{name}",
                summary=_clean(tool.get("description")),
                kind="mcp",
                needs_auth=needs_auth,
                auth_hint=(
                    "Canvas 令牌（WESTLAKE_CANVAS_TOKEN）" if name.startswith("canvas")
                    else ("教务账号 + 校园网/VPN" if needs_auth else "")
                ),
                params=params,
            )
        )
    return items


def _web_capabilities() -> list[Capability]:
    """WebUI 页面清单。"""
    return [
        Capability(
            name=f"web:{path}",
            summary=f"{title} — {note}",
            kind="web",
            needs_auth=needs_auth,
        )
        for path, title, note, needs_auth in WEB_PAGES
    ]


def collect() -> list[Capability]:
    """汇总全部能力（CLI → MCP → WebUI）。"""
    return _cli_capabilities() + _mcp_capabilities() + _web_capabilities()


def as_dict() -> dict:
    """转成可直接 JSON 化的结构（供 ``/api/capabilities``）。"""
    items = collect()

    def _row(item: Capability) -> dict:
        row = {
            "name": item.name,
            "summary": item.summary,
            "kind": item.kind,
            "needs_auth": item.needs_auth,
        }
        if item.auth_hint:
            row["auth_hint"] = item.auth_hint
        if item.commands:
            row["commands"] = [{"name": name, "summary": summary} for name, summary in item.commands]
        if item.params:
            row["params"] = item.params
        return row

    return {
        "counts": {
            "total": len(items),
            "cli": sum(1 for item in items if item.kind == "cli"),
            "mcp": sum(1 for item in items if item.kind == "mcp"),
            "web": sum(1 for item in items if item.kind == "web"),
            "needs_auth": sum(1 for item in items if item.needs_auth),
        },
        "items": [_row(item) for item in items],
    }
