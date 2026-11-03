"""模块冒烟矩阵：把只读命令分层精选，输出一张「能不能用」的体检表。

为什么需要它
============
每条能力都做过端到端验证，但验证的是「当时那条路」。预约中心那次说明：
主链路跑通≠模块被验证——权限、空列表、占位外链、服务端未配置，都可能在
主链路之外。这个脚本把「每个模块至少有一次真实调用」变成可重复的检查。

分层（2026-11-03 精选口径）
==========================
每条命令按「依赖什么」打标，**默认只跑不依赖账号的精选集**：

* 无标（匿名）：公开网页/公开接口，任何机器有网就能跑；
* ``offline``：连网都不用（随包快照、本地计算），CI 与无外网环境可跑；
* ``auth``：要本机凭据 / 登录态 / 个人数据 / 校园网——用**使用者自己的**
  账号真跑，结果含个人数据，只适合本机验证，绝不在 CI 或他人环境执行。

参数自举（2026-11-03，auth 组不再绑具体账号的内容）
==================================================
每个人账号里的课程、作业、讨论、会话、可约资源、已登记分享都不同——
把样例参数写死（「概率论」「Quiz 1」「会话 2041」「E12-302研讨室」）
等于把测试绑在**某一个账号某一个学期**上，换人跑必挂。因此带 ``{占位符}``
的命令在执行前先跑取数命令、从**该账号的真实列表**提取第一项替换：

* ``{canvas_course}`` / ``{course_with_assignment}``+``{first_assignment}`` /
  ``{course_with_topic}``+``{first_topic}``：课程表里第一门课 / 第一门有
  作业的课（最多扫 12 门）/ 第一门有讨论主题的课；``--course`` 一律传
  课程 id——同名课多门时按名称关键词会匹配歧义；
* ``{canvas_conversation}``：inbox 第一条会话 id；``{booking_resource}``：
  可约资源列表第一项；``{sport_scene}``/``{sport_slot}``：第一场景及其
  第一场地；``{share_name}``：第一笔已登记分享；
* ``{today}``/``{tomorrow}``/``{today+6d}``：运行日动态生成，不随时间过期。

该账号没有此类内容（收件箱空、没登记分享……）时该条标 ``SKIP``——
是「此账号无此内容」的有效结果，不是失败。

用法
====
    python tools/module_smoke.py            # 默认：匿名+离线精选集，不碰账号
    python tools/module_smoke.py --auth     # 只跑需凭据组（本机、自己账号）
    python tools/module_smoke.py --all      # 全量（≈旧版默认行为）
    python tools/module_smoke.py --offline  # 只跑纯离线条目（CI 用的子集）
    python tools/module_smoke.py sis canvas # 按模块过滤，与上述选择器取交集
    python tools/module_smoke.py --list     # 只列选中清单不执行（审计口径）
    python tools/module_smoke.py --json out.json

判定（逐条命令）
================
``OK``      正常返回且有内容
``EMPTY``   正常返回但空——**空是合法结果，也可能是没权限**，需人工判断
``AUTH``    缺凭据/登录失败
``SKIP``    参数自举失败：该账号没有占位符所需的内容（不是失败）
``MIGRATED``服务端系统换掉了、本工具尚未接新接口（不是 bug，不列入待处理）
``FAIL``    其他错误（含超时、解析异常）
``MISSING`` 命令不存在（文档承诺了但没实现）

只跑只读命令。不进表的命令（2026-10-27 对账口径）：
* 写操作：canvas submit/reply/send、booking book/cancel、setup、sso creds set、
  share add/remove、cache clear（清本地缓存）；
* 会弹浏览器或交互输入：go、vpn login、scholar ensure/sso、sso creds set；
* 长跑普查：probe scan（含 --full）、hosts mine --all；
* 落盘导出：transit ical --out、sis ical、share download、canvas * --download；
* 打印凭据：sso creds show（红线：冒烟输出绝不出现学号/密码/令牌）。
带具体 URL/课程/作业/日期参数的条目是「样例参数」，随内容时效会过期：
FAIL 时先换新参数再定性（空结果/缺凭据归 AUTH/EMPTY，属有效结果）。
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import date, timedelta

#: (模块, 参数, 说明, 标签)。只放只读命令（排除口径见模块 docstring）。
#: 标签：``"auth"``=需凭据/登录态/个人数据/校园网；``"offline"``=不碰网；
#: 空=匿名公网。默认选择器跑「非 auth」，--auth/--offline/--all 单选。
COMMANDS: list[tuple[str, list[str], str, tuple[str, ...]]] = [
    # —— 匿名 + 离线（默认精选集）——
    ("calendar", ["calendar", "today"], "今日日期/周次", ()),
    ("calendar", ["calendar", "today", "--offline"], "今日日期/周次（离线）", ("offline",)),
    ("calendar", ["calendar", "week", "8"], "第 8 周起止", ()),
    ("calendar", ["calendar", "events"], "校历事件", ()),
    ("transit", ["transit", "next", "--campus", "云谷", "--limit", "2"], "下一班校车", ()),
    ("transit", ["transit", "table", "--campus", "云谷", "--day", "工作日"], "班车时刻表", ()),
    ("transit", ["transit", "table", "--offline"], "班车时刻表（离线）", ("offline",)),
    ("version", ["version"], "版本信息与契约", ("offline",)),
    ("version", ["version", "--json"], "版本信息结构化 JSON", ("offline",)),
    ("skill", ["skill", "runtime"], "SkillVM JIT 运行时画像探测", ()),
    ("skill", ["skill", "compile", "--target", "zcode"], "SkillVM AOT 编译 (ZCode)", ("offline",)),
    ("booking", ["booking", "recommend", "--date", "today", "--limit", "2"], "场地空闲推荐复合求解", ()),
    ("context", ["context", "--level", "terse"], "此刻快照", ()),
    ("digest", ["digest", "--level", "terse"], "晨报", ()),
    ("find", ["find", "论文"], "按需求搜能力（本地索引，CLI/MCP/网页/学术库/注册表）", ("offline",)),
    ("search", ["search", "西湖", "--limit", "3"], "官网搜索", ()),
    ("news", ["news", "--limit", "3"], "新闻", ()),
    ("news", ["news", "detail", "https://www.westlake.edu.cn/news_events/westlakenews/News/202610/t20261026_70719.html"], "新闻详情（样例 URL 会过期）", ()),
    ("events", ["events", "--days", "7", "--limit", "3"], "讲座活动", ()),
    ("events", ["events", "detail", "https://www.westlake.edu.cn/news_events/EventCalendars/science/202610/t20261023_70627.html"], "活动详情（样例 URL 会过期）", ()),
    ("research", ["research", "--limit", "3"], "科研进展", ()),
    ("research", ["research", "detail", "https://www.westlake.edu.cn/research/research_at_westlake/good_health_wellbeing/202510/t20251016_60343.html"], "科研进展详情（样例 URL 会过期）", ()),
    ("careers", ["careers", "--limit", "3"], "招聘岗位", ()),
    ("careers", ["careers", "detail", "https://www.westlake.edu.cn/careers/OpenPositions/postdoctoral_fellow/bshsls/202508/t20250827_58224.html"], "岗位详情（样例 URL 会过期）", ()),
    ("career", ["career", "list", "--kind", "jobfair"], "就业服务网招聘会", ()),
    ("career", ["career", "deep", "--kind", "campus", "--page", "1"], "就业深列表（登录态）", ("auth",)),
    ("career", ["career", "detail", "zpxz"], "就业服务网详情（招聘指南常设页面）", ()),
    ("faculty", ["faculty", "--limit", "3"], "教师名录", ()),
    ("faculty", ["faculty", "detail", "https://www.westlake.edu.cn/faculty/jianhao-zhang.html"], "教师主页详情", ()),
    ("campus", ["campus", "dining", "--campus", "云谷"], "食堂", ()),
    ("campus", ["campus", "housing", "--campus", "云谷"], "公寓", ()),
    ("campus", ["campus", "services", "--campus", "云谷"], "生活服务网点（超市/快递/干洗/理发/打印/银行）", ()),
    ("contact", ["contact", "--campus", "云谷"], "校区联系", ()),
    ("contact", ["contact", "phones"], "常用电话", ()),
    ("map", ["map"], "校区地图", ()),
    ("program", ["program", "overview"], "培养目标", ()),
    ("program", ["program", "curriculum"], "课程体系", ()),
    ("program", ["program", "majors"], "专业总览", ()),
    ("program", ["program", "plan"], "培养方案", ()),
    ("program", ["program", "courses"], "通识课程", ()),
    ("program", ["program", "course", "机器学习"], "跨源课程查询", ()),
    ("sites", ["sites", "list"], "站点索引", ()),
    ("sites", ["sites", "site", "hpc"], "单站栏目与条目", ()),
    ("sites", ["sites", "detail", "https://hpc.westlake.edu.cn/document/science/index.html"], "条目详情（样例 URL 会过期）", ()),
    ("hosts", ["hosts", "list", "--limit", "3"], "子站清单（缓存）", ()),
    ("hosts", ["hosts", "mine", "hpc"], "单站挖掘（--all 全量普查不入表）", ()),
    ("hosts", ["hosts", "show", "hpc"], "已挖掘站点的栏目条目", ()),
    ("affairs", ["affairs", "apps", "预约"], "办事大厅应用", ()),
    ("affairs", ["affairs", "app", "证明"], "办事流程应用详情与直达链接", ()),
    ("affairs", ["affairs", "links"], "常用服务入口直达（HPC/预约中心/镜像站）", ()),
    ("affairs", ["affairs", "portal"], "门户服务", ()),
    ("hpc", ["hpc", "overview"], "集群队列", ()),
    ("hpc", ["hpc", "ai"], "AI 网关", ()),
    ("hpc", ["hpc", "chat", "1+1=?", "--no-think"], "集群 AI 大模型对话", ()),
    ("portal", ["portal", "ask", "图书馆开放时间"], "官方 AI 助手问答", ()),
    ("instrument", ["instrument", "search", "质谱", "--limit", "2"], "大型仪器共享检索", ()),
    ("finance", ["finance", "sections"], "财务栏目", ()),
    ("mirrors", ["mirrors"], "镜像目录", ()),
    ("wiki", ["wiki", "list", "--cat", "guides"], "百科目录（WikiLake，学生自建）", ()),
    ("wiki", ["wiki", "search", "班车"], "百科标题检索", ()),
    ("wiki", ["wiki", "page", "guides/班车"], "百科单页正文（抓整页）", ()),
    ("probe", ["probe"], "堵点探测", ()),
    ("pms", ["pms", "stations"], "打印网点（匿名）", ()),
    ("scholar", ["scholar", "dbs"], "订阅数据库", ()),
    ("scholar", ["scholar", "campus"], "校园 IP 信标", ()),
    ("scholar", ["scholar", "carsi"], "CARSI 目录（随包快照，356 个 SP）", ("offline",)),
    ("scholar", ["scholar", "open", "cnki"], "打印某库直达/CARSI 入口 URL（本地拼链）", ("offline",)),
    ("scholar", ["scholar", "doi", "10.1038/nature12373"], "DOI 题录解析（不带 --out 不下载）", ()),
    ("share", ["share", "saved"], "已登记分享（本地登记表）", ("offline",)),
    ("institute", ["institute", "news"], "理论院新闻动态", ()),
    ("institute", ["institute", "events"], "理论院学术活动", ()),
    ("schools", ["schools", "list"], "学院清单", ()),
    ("schools", ["schools", "news", "science"], "学院最新新闻", ()),
    ("sso", ["sso", "creds", "status"], "凭据来源有无（本地探测；无凭据时 AUTH 属预期，不回显密码）", ("offline",)),
    # —— 需凭据 / 登录态 / 个人数据 / 校园网（--auth，用自己账号真跑）——
    ("scholar", ["scholar", "status"], "CARSI 会话有效性（依赖本机已有会话）", ("auth",)),
    ("share", ["share", "files", "--name", "{share_name}"], "列分享文件夹（自举：第一笔已登记分享）", ("auth",)),
    ("lib", ["lib", "search", "数据结构"], "书目检索", ("auth",)),
    ("lib", ["lib", "loans"], "我的借阅", ("auth",)),
    ("pms", ["pms", "jobs"], "我的打印任务", ("auth",)),
    ("todo", ["todo", "list"], "办事待办", ("auth",)),
    ("todo", ["todo", "doing"], "我发起的进行中流程", ("auth",)),
    ("todo", ["todo", "done"], "我已处理的流程", ("auth",)),
    ("todo", ["todo", "cc"], "抄送给我的流程（未读）", ("auth",)),
    ("todo", ["todo", "apps"], "可发起/访问的应用", ("auth",)),
    ("sis", ["sis", "schedule"], "课表", ("auth",)),
    ("sis", ["sis", "grid"], "周课表网格+冲突检测（只读）", ("auth",)),
    ("sis", ["sis", "grades"], "成绩", ("auth",)),
    ("sis", ["sis", "exams"], "考试", ("auth",)),
    ("sis", ["sis", "cart"], "选课车（只读）", ("auth",)),
    ("sis-evals", ["sis-evals", "list", "--pending"], "待评教", ("auth",)),
    ("profile", ["profile", "info"], "个人信息", ("auth",)),
    ("profile", ["profile", "academic"], "学籍数据", ("auth",)),
    ("profile", ["profile", "extended"], "扩展信息", ("auth",)),
    ("records", ["records", "second-class"], "第二课堂", ("auth",)),
    ("records", ["records", "advisor"], "学业导师", ("auth",)),
    ("records", ["records", "dorm"], "住宿申请与宿舍信息", ("auth",)),
    ("records", ["records", "leave"], "请假申请", ("auth",)),
    ("records", ["records", "honors"], "荣誉记录", ("auth",)),
    ("records", ["records", "volunteer"], "志愿服务记录", ("auth",)),
    ("records", ["records", "vol-history"], "志愿服务历史（含总时长）", ("auth",)),
    ("records", ["records", "practice"], "社会实践记录", ("auth",)),
    ("records", ["records", "discipline"], "违纪信息", ("auth",)),
    ("records", ["records", "appointments"], "本周预约（心理健康）", ("auth",)),
    ("records", ["records", "registration"], "学期注册缴费状态", ("auth",)),
    ("records", ["records", "leaving-check"], "离校自查清单", ("auth",)),
    ("records", ["records", "source-info"], "生源信息确认状态", ("auth",)),
    ("records", ["records", "other-apps"], "异动/认定/衔接/就业申请状态", ("auth",)),
    ("aid", ["aid", "loans"], "贷款记录", ("auth",)),
    ("aid", ["aid", "jobs"], "勤工助学岗位/工时/工资", ("auth",)),
    ("aid", ["aid", "outbound"], "海外交流派出申请", ("auth",)),
    ("aid", ["aid", "exchange"], "交换生申请记录", ("auth",)),
    ("aid", ["aid", "orgs"], "学生组织与社团目录", ("auth",)),
    ("aid", ["aid", "activities"], "社团活动登记记录", ("auth",)),
    ("aid", ["aid", "claim"], "工时申报状态（有无岗位）", ("auth",)),
    ("portal", ["portal", "cards"], "门户个人卡片（未读/在借/待办）", ("auth",)),
    ("sso", ["sso", "login"], "验证 SIS 凭据有效性", ("auth",)),
    ("canvas", ["canvas", "courses"], "Canvas 课程", ("auth",)),
    ("canvas", ["canvas", "deadlines", "--limit", "3"], "作业截止", ("auth",)),
    ("canvas", ["canvas", "exams", "--days", "30"], "考试安排", ("auth",)),
    ("canvas", ["canvas", "todo", "--limit", "5"], "Canvas 待办", ("auth",)),
    ("canvas", ["canvas", "assignments", "--course", "{course_with_assignment}"], "课程作业列表（自举：第一门有作业的课）", ("auth",)),
    ("canvas", ["canvas", "assignment-info", "--course", "{course_with_assignment}", "--assignment", "{first_assignment}"], "作业详情（课程+作业自举）", ("auth",)),
    ("canvas", ["canvas", "files", "--course", "{canvas_course}"], "课程文件区清单（自举：第一门课）", ("auth",)),
    ("canvas", ["canvas", "discussions", "--course", "{course_with_topic}"], "课程讨论主题（自举：第一门有讨论的课）", ("auth",)),
    ("canvas", ["canvas", "announcements", "--course", "{canvas_course}"], "课程公告（自举：第一门课）", ("auth",)),
    ("canvas", ["canvas", "discussion", "--course", "{course_with_topic}", "--topic", "{first_topic}"], "讨论主题正文（自举）", ("auth",)),
    ("canvas", ["canvas", "entries", "--course", "{course_with_topic}", "--topic", "{first_topic}", "--limit", "5"], "讨论回帖列表（自举）", ("auth",)),
    ("canvas", ["canvas", "inbox", "--limit", "5"], "收件箱会话", ("auth",)),
    ("canvas", ["canvas", "conversation", "{canvas_conversation}"], "会话全文（id 自举自 inbox 第一条）", ("auth",)),
    ("canvas", ["canvas", "modules", "{canvas_course}"], "课程模块与条目（自举：第一门课）", ("auth",)),
    ("canvas", ["canvas", "submission", "--course", "{course_with_assignment}", "--assignment", "{first_assignment}"], "作业提交状态（自举）", ("auth",)),
    ("booking", ["booking", "types"], "预约中心分类", ("auth",)),
    ("booking", ["booking", "sports"], "预约中心体育类体检", ("auth",)),
    ("booking", ["booking", "list", "--type", "图书馆"], "可预约资源列表", ("auth",)),
    ("booking", ["booking", "days", "{booking_resource}", "--start", "{today}", "--end", "{today+6d}"], "某资源逐日可约（资源+日期自举）", ("auth",)),
    ("booking", ["booking", "slots", "{booking_resource}", "--date", "{tomorrow}"], "某资源空闲时段（资源+日期自举）", ("auth",)),
    ("booking", ["booking", "mine"], "我的预约", ("auth",)),
    ("sport", ["sport", "scenes"], "场馆场景", ("auth",)),
    ("sport", ["sport", "sites", "{sport_scene}"], "场景当日场地与可约状态（自举：第一场景）", ("auth",)),
    ("sport", ["sport", "days", "{sport_scene}", "{sport_slot}"], "逐日可约与不可约原因（场景+场地自举）", ("auth",)),
    ("sport", ["sport", "mine"], "我的场馆预约", ("auth",)),
]

#: 选择器旗标 → 选中条件。默认（无旗标）跑非 auth 的精选集。
_SELECTOR_FLAGS: dict[str, str] = {
    "--all": "all",
    "--auth": "auth",
    "--offline": "offline",
}


@dataclass
class Result:
    module: str
    argv: str
    note: str
    status: str
    detail: str
    seconds: float
    tags: tuple[str, ...] = ()


#: 空结果标记。只看**首行**：正文里出现「太空/空间/没有」这类字眼不算空
#: （2026-10-27 修正：旧版对全文做「空」「没有」子串匹配，把新闻详情、
#: 培养方案等有内容的输出误判成 EMPTY）。
EMPTY_MARKERS: tuple[str, ...] = (
    "没有", "暂无", "无记录", "没有记录", "没有待办", "无评估任务",
    "共 0 条", "0 条记录", "（无）",
)


def _classify(output: str, code: int) -> tuple[str, str]:
    text = output.strip()
    low = text.lower()
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if code != 0:
        if "系统已迁移" in text:
            return "MIGRATED", first[:90]
        if any(k in text for k in ("未配置统一凭据", "登录失败", "凭据", "验证码", "未获得 PS_TOKEN",
                                   "无权访问", "未授权", "not authorized")):
            return "AUTH", first[:90]
        if any(k in low for k in ("no such command", "no such option", "usage:")) or code == 2:
            return "MISSING", first[:90]
        return "FAIL", first[:90]
    if not text or any(k in first for k in EMPTY_MARKERS):
        return "EMPTY", first[:90]
    return "OK", first[:90]


def run(argv: list[str], timeout: float = 90.0) -> tuple[str, str, float]:
    started = time.time()
    try:
        proc = subprocess.run(
            ["westlake", *argv],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        status, detail = _classify(out, proc.returncode)
    except subprocess.TimeoutExpired:
        status, detail = "FAIL", f"超时 {timeout:.0f}s"
    except FileNotFoundError:
        status, detail = "MISSING", "westlake 不在 PATH"
    return status, detail, round(time.time() - started, 1)


#: —— 参数自举（见模块 docstring）：占位符 → 该账号真实内容的第一项 ——
#: 提取器只认各列表命令的表格输出特征（首列数字 id、列间多空格、行尾会话 id、
#: 全角空格分隔、TAB 分隔），列名表头/虚线/汇总行天然不匹配。

_boot_cache: dict[str, str | None] = {}


def _capture(argv: list[str], timeout: float = 60.0) -> str:
    """跑一条只读取数命令拿合并输出（自举专用，不做结果分类）。"""
    try:
        proc = subprocess.run(
            ["westlake", *argv],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout,
        )
        return (proc.stdout or "") + (proc.stderr or "")
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return f"{exc.__class__.__name__}: {exc}"


def _pick_course_id(out: str) -> str | None:
    """courses 表第一个数据行（首列为纯数字 id；表头「ID」不匹配）。"""
    m = re.search(r"(?m)^\s*(\d+)\s", out)
    return m.group(1) if m else None


def _pick_assignment(out: str) -> str | None:
    """assignments 表第一行作业名：列间≥2 空格对齐，名字内部单空格保留。"""
    m = re.search(r"(?m)^\s*\d+\s+(.+?)\s{2,}", out)
    return m.group(1).strip() if m else None


def _pick_topic(out: str) -> str | None:
    """discussions 表第一行主题：第 4 列（或空未读时第 3 列后）是日期时间。"""
    for line in out.splitlines():
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) >= 4 and re.match(r"^\d{4}-\d{2}-\d{2}", parts[-2] if len(parts) > 4 else parts[3]):
            return parts[0]
    return None


def _pick_conversation(out: str) -> str | None:
    """inbox 第一个数据行行尾的会话 id（行内含 hh:mm 时间列，避开汇总行）。"""
    for line in out.splitlines():
        if re.search(r"\d{2}:\d{2}", line):
            m = re.search(r"(\d{3,})\s*$", line)
            if m:
                return m.group(1)
    return None


def _pick_booking_resource(out: str) -> str | None:
    """可约资源第一项：名称与「[类型]」之间是全角空格。"""
    for line in out.splitlines():
        if "\u3000[" in line:
            return line.split("\u3000")[0].strip()
    return None


def _first_tab_field(out: str) -> str | None:
    """TAB 分隔表第一行第一列（sport scenes 的场景名 / sport sites 的场地名）。"""
    for line in out.splitlines():
        first = line.split("\t")[0].strip()
        if first and "\t" in line:
            return first
    return None


def _pick_share_name(out: str) -> str | None:
    """share saved 第一笔登记的名称（名称 + URL 两列）。"""
    for line in out.splitlines():
        if "http" in line:
            return line.split()[0]
    return None


def _scan_course_with(kind: str) -> tuple[str, str] | None:
    """扫课程表（最多 12 门）找第一门有作业/讨论主题的课，返回 (课程id, 第一项)。

    第一门课未必有作业或讨论（实测本账号讨论在第 10 门）——直接取第一门
    会让这两类条目在多数账号上常年 SKIP/EMPTY，扫描保证自举命中。
    """
    out = _capture(["canvas", "courses"])
    ids = re.findall(r"(?m)^\s*(\d+)\s", out)[:12]
    for cid in ids:
        if kind == "assignment":
            item = _pick_assignment(_capture(["canvas", "assignments", "--course", cid]))
        else:
            item = _pick_topic(_capture(["canvas", "discussions", "--course", cid]))
        if item:
            return cid, item
    return None


def _boot_value(token: str) -> str | None:
    if token in _boot_cache:
        return _boot_cache[token]
    if token == "{today}":
        value: str | None = date.today().isoformat()
    elif token == "{tomorrow}":
        value = (date.today() + timedelta(days=1)).isoformat()
    elif token == "{today+6d}":
        value = (date.today() + timedelta(days=6)).isoformat()
    elif token == "{canvas_course}":
        value = _pick_course_id(_capture(["canvas", "courses"]))
    elif token == "{canvas_conversation}":
        value = _pick_conversation(_capture(["canvas", "inbox", "--limit", "5"]))
    elif token == "{booking_resource}":
        value = _pick_booking_resource(_capture(["booking", "list", "--type", "图书馆"]))
    elif token == "{sport_scene}":
        value = _first_tab_field(_capture(["sport", "scenes"]))
    elif token == "{sport_slot}":
        scene = _boot_value("{sport_scene}")
        value = _first_tab_field(_capture(["sport", "sites", scene])) if scene else None
    elif token == "{share_name}":
        value = _pick_share_name(_capture(["share", "saved"]))
    elif token in ("{course_with_assignment}", "{first_assignment}"):
        found = _scan_course_with("assignment")
        _boot_cache["{course_with_assignment}"] = found[0] if found else None
        _boot_cache["{first_assignment}"] = found[1] if found else None
        return _boot_cache[token]
    elif token in ("{course_with_topic}", "{first_topic}"):
        found = _scan_course_with("topic")
        _boot_cache["{course_with_topic}"] = found[0] if found else None
        _boot_cache["{first_topic}"] = found[1] if found else None
        return _boot_cache[token]
    else:
        value = None
    _boot_cache[token] = value
    return value


def _bootstrap(argv: list[str]) -> tuple[list[str], str]:
    """替换 argv 中的 ``{占位符}``；返回 (新 argv, 失败原因)。原因非空 → 该条 SKIP。"""
    resolved = list(argv)
    for i, token in enumerate(resolved):
        if token.startswith("{") and token.endswith("}"):
            value = _boot_value(token)
            if value is None:
                return resolved, f"自举失败：{token} 本账号取不到"
            resolved[i] = value
    return resolved, ""


def _select(argv: list[str]) -> tuple[list[tuple[str, list[str], str, tuple[str, ...]]], str]:
    """按旗标+位置参数选命令，返回 (选中清单, 口径描述)。"""
    modes = [name for flag, name in _SELECTOR_FLAGS.items() if flag in argv]
    if len(modes) > 1:
        raise SystemExit(f"选择器互斥：{' '.join(modes)} 只能给一个")
    args = [a for a in argv if not a.startswith("--")]
    if modes == ["all"]:
        chosen, label = COMMANDS, "全量"
    elif modes == ["auth"]:
        chosen = [row for row in COMMANDS if "auth" in row[3]]
        label = "需凭据组（--auth，本机自己账号）"
    elif modes == ["offline"]:
        chosen = [row for row in COMMANDS if "offline" in row[3]]
        label = "纯离线子集（--offline）"
    else:
        chosen = [row for row in COMMANDS if "auth" not in row[3]]
        label = "匿名+离线精选集（默认，不碰账号）"
    if args:
        chosen = [row for row in chosen if any(a in row[0] for a in args)]
        label += f"，模块过滤 {','.join(args)}"
    return chosen, label


def main() -> int:
    argv = sys.argv[1:]
    list_only = "--list" in argv
    argv = [a for a in argv if a != "--list"]
    out_path = ""
    bare_json = False
    if "--json" in argv:
        index = argv.index("--json")
        if index + 1 < len(argv) and not argv[index + 1].startswith("--"):
            out_path = argv[index + 1]
            argv = argv[:index] + argv[index + 2 :]
        else:
            bare_json = True  # 裸 --json：stdout 输出 JSON（此前会静默降级成文本，坑过工作流）
            argv = argv[:index] + argv[index + 1 :]
    as_json = bool(out_path) or bare_json or "--stdout-json" in sys.argv
    chosen, label = _select(argv)

    if list_only:  # 审计口径：只列清单不执行，供核对精选了哪些、砍掉了哪些
        for module, cmd, note, tags in chosen:
            mark = "/".join(tags) if tags else "-"
            print(f"{mark:8}{module:12}{' '.join(cmd)}  ← {note}")
        total_auth = sum(1 for row in COMMANDS if "auth" in row[3])
        print(f"\n{label}：{len(chosen)} 条（全量 {len(COMMANDS)}，其中需凭据 {total_auth} 条）")
        return 0

    results: list[Result] = []
    for module, cmd, note, tags in chosen:
        boot_cmd, skip_reason = _bootstrap(cmd)
        if skip_reason:  # 该账号没有占位符所需内容：保留占位符原样便于审计
            results.append(Result(module, " ".join(cmd), note, "SKIP", skip_reason, 0.0, tags))
            if not as_json:
                print(f"{'SKIP':8}{module:12}{' '.join(cmd)}  ← {skip_reason}", flush=True)
            continue
        status, detail, seconds = run(boot_cmd)
        results.append(Result(module, " ".join(boot_cmd), note, status, detail, seconds, tags))
        if not as_json:
            print(f"{status:8}{module:12}{' '.join(boot_cmd)}  ← {detail}", flush=True)

    if not as_json:
        print()
        counts: dict[str, int] = {}
        for item in results:
            counts[item.status] = counts.get(item.status, 0) + 1
        print(f"口径：{label}，本次 {len(results)} 条")
        print("汇总：" + "　".join(f"{k} {v}" for k, v in sorted(counts.items())))
        broken = [r for r in results if r.status in ("FAIL", "MISSING")]
        if broken:
            print("\n需要处理：")
            for item in broken:
                print(f"  {item.status} {item.argv} ← {item.detail}")
    else:
        payload = json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2)
        if out_path:
            pathlib.Path(out_path).write_text(payload, encoding="utf-8")
            counts: dict[str, int] = {}
            for item in results:
                counts[item.status] = counts.get(item.status, 0) + 1
            print(f"写入 {out_path}；" + "　".join(f"{k} {v}" for k, v in sorted(counts.items())))
        else:
            print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
