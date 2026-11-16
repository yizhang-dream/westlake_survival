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
    "sis": "教务账号 + 校园网/VPN（westlake setup）",
    "sis-evals": "教务账号 + 校园网/VPN",
    "profile": "教务账号 + 校园网/VPN",
    "records": "教务账号 + 校园网/VPN",
    "aid": "教务账号 + 校园网/VPN",
    "ams": "统一密码 + 校园网/VPN（IAM 统一认证）",
    "booking": "统一密码 + 校园网/VPN（预约中心 OIDC）",
    "market": "统一密码（门户数据市集，进程内会话）",
    "todo": "统一密码 + 校园网/VPN（办事大厅任务中心）",
    "portal": "个人卡片需统一密码；portal ask 官方 AI 问答免登录",
    "hpc": "hpc overview/ai 公开；hpc chat 需 HPC 令牌或统一密码",
    "share": "公开分享链接免登录；组织内限制分享需 share login",
    "lib": "书目检索免登录；借阅与续借需阿法迪云会话 + 校园网",
    "pms": "打印任务与提交/取消需打印系统账号；网点列表公开",
    "sport": "统一密码 + 校园网/VPN（场馆系统走 IAM CAS，独立于预约中心）",
    "canvas": "Canvas API 令牌（WESTLAKE_CANVAS_TOKEN）或统一密码（IAM CAS）",
    "sso": "仅用于配置教务凭据本身",
}

#: WebUI 页面清单：路径、标题、说明、是否需要凭据。
WEB_PAGES = (
    ("/", "仪表盘", "日期 / 周次 / 天气 / 最近事件 / 下班车 / 作业", False),
    ("/timeline", "行动流", "跨系统全天日程编排、冲突检测与个人备忘", False),
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
    ("/sis", "学业", "课表/成绩/考试/待评教/第二课堂/学业导师（教务凭据）", True),
    ("/canvas", "Canvas", "在修课程与未来截止（令牌或统一密码）", True),
    ("/careers", "招聘", "官网岗位 + 就业服务网三区块（招聘公告/招聘会/宣讲会，公开）", False),
    ("/hpc", "集群", "HPC 队列配置表（公开）与 Portal 入口", False),
    ("/finance", "财务", "报销/制度/科研经费文档（公开）", False),
    ("/mirrors", "镜像", "开源镜像仓库目录与换源 Help", False),
    ("/schools", "学院", "五学院官网最新新闻聚合（理/生/工/医/理论院）", False),
    ("/institute", "理论院", "理论科学研究院新闻与学术活动（公开）", False),
    ("/services", "服务", "全站服务注册表（盘点快照+在线普查）", False),
    ("/sites", "全站", "37 个已接入站点的栏目与条目（左目录两级）", False),
    ("/hosts", "子站", "全量子域探测：存活/不可达 + 通用栏目挖掘", False),
    ("/wiki", "百科", "学生自建百科 WikiLake 目录、检索与词条", False),
    ("/scholar", "学术", "订阅数据库注册表 / CARSI 联盟 / DOI 全文（校园 IP 探测）", False),
    ("/ams", "教学系统", "课表 / 学期周次 / 学籍与选课入口（IAM 统一认证）", True),
    ("/pms", "文印", "打印网点 / 我的打印任务 / 用量统计（需校园网）", True),
    ("/sport", "场馆", "体育场馆/游泳（独立正元系统）：场景、当日可约、我的预约", True),
    ("/affairs", "办事", "办事大厅 176 个流程应用 + 待办/进行中/已处理/抄送 + 门户 18 项服务", False),
    ("/vpn", "VPN", "深信服 SSL VPN 状态与手动登录入口", False),
    ("/setup", "设置", "网页端账号配置：学号密码一次填入，Canvas 令牌可选可清除，自动检测各服务", True),
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

    def _mcp_auth_hint(name: str) -> str:
        if name.startswith("canvas_"):
            return "Canvas 令牌（WESTLAKE_CANVAS_TOKEN）或统一密码"
        if name.startswith("sis_") or name == "calendar_export":
            return "教务账号 + 校园网/VPN"
        if name.startswith(("booking_", "sport_")) or name in ("affairs_portal", "portal_cards"):
            return "统一密码 + 校园网/VPN"
        if name in ("lib_loans", "lib_renew"):
            return "统一密码 + 校园网/VPN（阿法迪云图书馆）"
        if name.startswith("market_"):
            return "统一密码（门户数据市集，进程内会话）"
        if name in ("pms_jobs", "pms_print", "pms_cancel"):
            return "文印账号（统一密码）+ 校园网/VPN"
        if name == "hpc_chat":
            return "HPC 令牌或统一密码"
        return ""

    items: list[Capability] = []
    for tool in list_tools():
        schema = tool.get("inputSchema") or {}
        params = sorted((schema.get("properties") or {}).keys())
        name = str(tool.get("name") or "")
        auth_hint = _mcp_auth_hint(name)
        items.append(
            Capability(
                name=f"mcp:{name}",
                summary=_clean(tool.get("description")),
                kind="mcp",
                needs_auth=bool(auth_hint),
                auth_hint=auth_hint,
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


#: 需求同义词（用户口语 → 能力词汇）。find 的命中判定 = 原词 ∪ 同义词。
SYNONYMS: dict[str, tuple[str, ...]] = {
    "论文": ("文献", "doi", "学术", "全文", "scholar", "数据库"),
    "文献": ("论文", "doi", "学术", "全文", "scholar"),
    "下载": ("pdf", "全文", "doi"),
    "作业": ("canvas", "assignments", "deadlines", "submit", "截止"),
    "交作业": ("submit", "canvas"),
    "截止": ("deadlines", "canvas", "作业"),
    "附件": ("canvas", "files", "assignment-info"),
    "课程文件": ("canvas", "files"),
    "公告": ("canvas", "announcements"),
    "讨论": ("canvas", "discussions", "讨论区"),
    "回帖": ("canvas", "reply", "entries", "discussion"),
    "私信": ("canvas", "inbox", "conversation", "send"),
    "收件箱": ("canvas", "inbox", "conversation"),
    "评分细则": ("canvas", "assignment-info", "rubric"),
    "成绩": ("grades", "gpa"),
    "gpa": ("grades", "成绩"),
    "课表": ("schedule", "课程", "上课"),
    "考试": ("exams", "quiz", "测验"),
    "评教": ("evals", "评估"),
    "绩点": ("grades", "gpa", "sis"),
    "放假": ("calendar", "校历", "事件", "假期"),
    "校历": ("calendar", "周次", "学期", "事件"),
    "班车": ("transit", "校车", "shuttle"),
    "校车": ("transit", "班车"),
    "食堂": ("dining", "餐饮", "咖啡"),
    "吃饭": ("dining", "食堂", "餐饮"),
    "宿舍": ("dorm", "住宿", "housing", "公寓"),
    "打印": ("pms", "文印"),
    "借书": ("lib", "loans", "search", "图书", "书目", "续借"),
    "图书馆": ("lib", "书目", "借阅", "opac"),
    "待办": ("todo", "affairs", "办事"),
    "办事": ("affairs", "todo", "apps", "流程", "申请"),
    "报销": ("finance", "经费", "财务"),
    "讲座": ("events", "宣讲", "活动"),
    "宣讲": ("career", "就业", "宣讲会"),
    "就业": ("career", "招聘", "岗位", "宣讲"),
    "招聘": ("careers", "岗位", "就业"),
    "导师": ("faculty", "教师", "老师"),
    "学业导师": ("advisor", "records", "导师选择", "轮转"),
    "学籍异动": ("other-apps", "转专业", "休学", "复学", "records"),
    "转专业": ("other-apps", "学籍异动", "records"),
    "老师": ("faculty", "教师", "导师"),
    "地图": ("map", "全景", "校区"),
    "邮件": ("mail", "邮箱", "outlook"),
    "网盘": ("pan", "mydisk", "文件"),
    "预约": ("booking", "visitor", "appointments", "share", "预约中心"),
    "自习": ("booking", "研讨室", "研习仓", "座位", "图书馆"),
    "自习室": ("booking", "研讨室", "研习仓", "座位", "图书馆"),
    "空教室": ("booking", "recommend", "自习室", "研讨室", "空闲"),
    "研讨室": ("booking", "研习仓", "图书馆", "预约"),
    "游泳": ("sport", "体育场馆", "泳", "预约"),
    "体育": ("sport", "体育场馆", "游泳", "球场", "预约"),
    "球场": ("sport", "体育场馆", "羽毛球", "网球", "篮球"),
    "超算": ("hpc", "集群", "gpu"),
    "集群": ("hpc", "队列", "gpu"),
    "镜像": ("mirrors", "换源", "pip"),
    "讲义": ("share", "onedrive", "sharepoint", "课件"),
    "课件": ("share", "canvas", "files", "讲义"),
    "分享": ("share", "onedrive", "sharepoint", "讲义"),
    "onedrive": ("share", "sharepoint", "讲义"),
    "sharepoint": ("share", "onedrive", "讲义"),
    "奖学金": ("aid", "资助", "贷款"),
    "志愿": ("volunteer", "records", "时长", "market"),
    "第二课堂": ("second-class", "records", "二课", "成绩单"),
    "二课": ("second-class", "第二课堂", "records"),
    "培养方案": ("program", "课程体系", "学分"),
    "选课": ("program", "course", "课程目录"),
    "学籍": ("profile", "academic", "records", "market"),
    "百科": ("wiki", "wikilake", "词条", "社团简介"),
    "词条": ("wiki", "wikilake", "百科"),
    "社团": ("wiki", "aid", "orgs", "clubs", "market"),
    "ai": ("hpc", "chat", "chatbot", "portal", "大模型", "问答"),
    "大模型": ("hpc", "chat", "ai", "deepseek", "glm", "qwen"),
    "chat": ("hpc", "chat", "ai", "chatbot"),
    "问答": ("portal", "ask", "chatbot", "ai"),
    "仪器": ("instrument", "share", "设备", "电镜", "质谱", "核磁"),
    "设备": ("instrument", "share", "仪器"),
    "电镜": ("instrument", "share", "冷冻电镜", "透射电镜"),
    "质谱": ("instrument", "share"),
    "核磁": ("instrument", "share"),
    "流程": ("affairs", "apps", "taskcenter", "todo"),
    "表单": ("affairs", "apps", "infoplus"),
    "还书": ("lib", "loans", "应还"),
    "图书": ("lib", "search", "loans", "书目"),
    "索书号": ("lib", "search", "callno"),
    "快递": ("campus", "services", "驿站", "菜鸟"),
    "超市": ("campus", "services", "罗森"),
    "洗衣": ("campus", "services", "干洗"),
    "理发": ("campus", "services"),
    "日程": ("timeline", "sis", "schedule", "grid", "ams", "calendar", "canvas"),
    "冲突": ("timeline", "sis", "grid", "schedule", "课表冲突"),
    "行动流": ("timeline", "日程", "备忘", "冲突"),
    "时间轴": ("timeline", "行动流", "日程"),
    "备忘": ("timeline", "add", "done", "delete", "待办"),
    "timeline": ("行动流", "日程", "备忘", "冲突"),
    "数据市集": ("market", "catalog", "profile", "resume", "courses", "honors", "clubs", "volunteer"),
    "市集": ("market", "数据市集", "catalog"),
    "履历": ("market", "resume", "profile"),
    "已修": ("market", "courses", "学分", "成绩"),
    "vpn": ("vpn", "隧道", "校外", "probe"),
    "推荐": ("booking", "recommend", "场地", "空闲"),
    "续借": ("lib", "renew", "借书", "在借"),
    "收藏": ("canvas", "star", "unstar", "置顶"),
    "星标": ("canvas", "star", "unstar"),
    "离线": ("offline", "calendar", "transit", "timeline"),
}


def find_capabilities(query: str) -> dict:
    """按需求关键词搜全部能力并按相关性排序：CLI 组/子命令、MCP 工具、Web 页、学术数据库、
    全站服务注册表。

    给 Agent 的运行时自发现入口（``westlake find <需求>``）——解决「装了
    skill 却不知道某需求归它管」的路由问题。用户口语与能力词汇有鸿沟
    （说「论文」而工具描述写「文献/DOI」），用 :data:`SYNONYMS` 扩展；
    排序上强偏好「原词精确命中 > 原词部分命中 > 同义词泛化命中」。
    """
    import re

    q = (query or "").strip().lower()
    if not q:
        return {"query": "", "hint": "给关键词，如：作业 / 论文 / 班车 / 待办 / 预约 / 打印", "cli": [],
                "mcp": [], "web": [], "databases": [], "services": []}

    raw_tokens = {q} | {t for t in re.split(r"[\s,，、/+]+", q) if t}
    syn_terms: set[str] = set()
    for tok in raw_tokens:
        syn_terms.update(t.lower() for t in SYNONYMS.get(tok, ()))
    syn_only = syn_terms - raw_tokens
    terms = raw_tokens | syn_only

    def _hit(text: str) -> bool:
        low = (text or "").lower()
        return any(t in low for t in terms)

    def _text_score(text: str, *, exact_w: int, syn_w: int, full_bonus: int = 0) -> int:
        low = (text or "").lower()
        if not low:
            return 0
        s = 0
        if q in low:
            s += full_bonus
        if any(t in low for t in raw_tokens):
            s += exact_w
        elif any(t in low for t in syn_only):
            s += syn_w
        return s

    out: dict = {"query": query, "matched_terms": sorted(terms), "cli": [], "mcp": [],
                 "web": [], "databases": [], "services": []}

    scored_buckets: dict[str, list[tuple[int, dict]]] = {"cli": [], "mcp": [], "web": []}
    for item in collect():
        hit_cmd_scored: list[tuple[int, dict]] = []
        for cmd_name, cmd_summary in item.commands:
            c_score = (
                _text_score(cmd_name, exact_w=40, syn_w=10, full_bonus=20)
                + _text_score(cmd_summary, exact_w=28, syn_w=8, full_bonus=15)
            )
            if c_score > 0:
                hit_cmd_scored.append((c_score, {"name": cmd_name, "summary": cmd_summary}))
        hit_cmd_scored.sort(key=lambda pair: (-pair[0], pair[1]["name"]))

        short_name = item.name.split()[-1].split(":")[-1].lstrip("/").lower()
        item_score = 0
        if short_name == q or item.name.lower() == q:
            item_score += 120
        item_score += _text_score(item.name, exact_w=55, syn_w=18, full_bonus=20)
        item_score += _text_score(item.summary, exact_w=45, syn_w=12, full_bonus=25)
        if hit_cmd_scored:
            item_score += min(45, hit_cmd_scored[0][0]) + 4

        if item_score <= 0:
            continue
        entry = {
            "name": item.name,
            "summary": item.summary,
            "example": item.example,
            "needs_auth": item.needs_auth,
            "auth_hint": item.auth_hint,
        }
        if hit_cmd_scored:
            entry["matched_commands"] = [row for _, row in hit_cmd_scored]
        scored_buckets[item.kind].append((item_score, entry))

    for kind in ("cli", "mcp", "web"):
        scored_buckets[kind].sort(key=lambda pair: (-pair[0], pair[1]["name"]))
        out[kind] = [entry for _, entry in scored_buckets[kind]]

    try:  # 学术数据库注册表（scholar）
        from westlake_survival.scholar import DATABASES

        db_scored: list[tuple[int, dict]] = []
        for db in DATABASES:
            s = sum(
                _text_score(x, exact_w=30, syn_w=10, full_bonus=15)
                for x in (db.key, db.name, db.category, db.vendor, db.note)
            )
            if s > 0:
                db_scored.append((s, {"key": db.key, "name": db.name, "access": db.access, "url": db.url}))
        db_scored.sort(key=lambda pair: (-pair[0], pair[1]["name"]))
        out["databases"] = [row for _, row in db_scored]
    except Exception:
        pass

    try:  # 全站服务注册表
        from westlake_survival.discovery import SERVICE_REGISTRY

        svc_scored: list[tuple[int, dict]] = []
        for host, name, mode in SERVICE_REGISTRY:
            s = (
                _text_score(host, exact_w=45, syn_w=14, full_bonus=20)
                + _text_score(name, exact_w=40, syn_w=12, full_bonus=20)
                + _text_score(mode, exact_w=20, syn_w=8)
            )
            if s > 0:
                svc_scored.append((s, {"host": f"{host}.westlake.edu.cn", "name": name, "mode": mode}))
        svc_scored.sort(key=lambda pair: (-pair[0], pair[1]["host"]))
        out["services"] = [row for _, row in svc_scored]
    except Exception:
        pass
    return out


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
