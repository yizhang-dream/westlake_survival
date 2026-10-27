"""模块冒烟矩阵：把所有只读命令跑一遍，输出一张「能不能用」的体检表。

为什么需要它
============
每条能力都做过端到端验证，但验证的是「当时那条路」。预约中心那次说明：
主链路跑通≠模块被验证——权限、空列表、占位外链、服务端未配置，都可能在
主链路之外。这个脚本把「每个模块至少有一次真实调用」变成可重复的检查。

用法
====
    python tools/module_smoke.py            # 全量（约 3-8 分钟，视网络）
    python tools/module_smoke.py sis canvas # 只跑匹配的模块
    python tools/module_smoke.py --json out.json

判定（逐条命令）
================
``OK``      正常返回且有内容
``EMPTY``   正常返回但空——**空是合法结果，也可能是没权限**，需人工判断
``AUTH``    缺凭据/登录失败
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
import subprocess
import sys
import time
from dataclasses import asdict, dataclass

#: (模块, 参数, 说明)。只放只读命令（排除口径见模块 docstring）。
COMMANDS: list[tuple[str, list[str], str]] = [
    ("calendar", ["calendar", "today"], "今日日期/周次"),
    ("calendar", ["calendar", "week", "8"], "第 8 周起止"),
    ("calendar", ["calendar", "events"], "校历事件"),
    ("transit", ["transit", "next", "--campus", "云谷", "--limit", "2"], "下一班校车"),
    ("transit", ["transit", "table", "--campus", "云谷", "--day", "工作日"], "班车时刻表"),
    ("context", ["context", "--level", "terse"], "此刻快照"),
    ("digest", ["digest", "--level", "terse"], "晨报"),
    ("find", ["find", "论文"], "按需求搜能力（CLI/MCP/网页/学术库/注册表）"),
    ("search", ["search", "西湖", "--limit", "3"], "官网搜索"),
    ("news", ["news", "--limit", "3"], "新闻"),
    ("news", ["news", "detail", "https://www.westlake.edu.cn/news_events/westlakenews/News/202610/t20261026_70719.html"], "新闻详情（样例 URL 会过期）"),
    ("events", ["events", "--days", "7", "--limit", "3"], "讲座活动"),
    ("events", ["events", "detail", "https://www.westlake.edu.cn/news_events/EventCalendars/science/202610/t20261023_70627.html"], "活动详情（样例 URL 会过期）"),
    ("research", ["research", "--limit", "3"], "科研进展"),
    ("research", ["research", "detail", "https://www.westlake.edu.cn/research/research_at_westlake/good_health_wellbeing/202510/t20251016_60343.html"], "科研进展详情（样例 URL 会过期）"),
    ("careers", ["careers", "--limit", "3"], "招聘岗位"),
    ("careers", ["careers", "detail", "https://www.westlake.edu.cn/careers/OpenPositions/postdoctoral_fellow/bshsls/202508/t20250827_58224.html"], "岗位详情（样例 URL 会过期）"),
    ("career", ["career", "list", "--kind", "jobfair"], "就业服务网招聘会"),
    ("career", ["career", "deep", "--kind", "campus", "--page", "1"], "就业深列表（登录态）"),
    ("career", ["career", "detail", "1129124"], "就业详情（样例 id 会过期，失效则换 deep 输出里的新 id）"),
    ("faculty", ["faculty", "--limit", "3"], "教师名录"),
    ("faculty", ["faculty", "detail", "https://www.westlake.edu.cn/faculty/jianhao-zhang.html"], "教师主页详情"),
    ("campus", ["campus", "dining", "--campus", "云谷"], "食堂"),
    ("campus", ["campus", "housing", "--campus", "云谷"], "公寓"),
    ("contact", ["contact", "--campus", "云谷"], "校区联系"),
    ("contact", ["contact", "phones"], "常用电话"),
    ("map", ["map"], "校区地图"),
    ("program", ["program", "overview"], "培养目标"),
    ("program", ["program", "curriculum"], "课程体系"),
    ("program", ["program", "majors"], "专业总览"),
    ("program", ["program", "plan"], "培养方案"),
    ("program", ["program", "courses"], "通识课程"),
    ("program", ["program", "course", "机器学习"], "跨源课程查询"),
    ("sites", ["sites", "list"], "站点索引"),
    ("sites", ["sites", "site", "hpc"], "单站栏目与条目"),
    ("sites", ["sites", "detail", "https://hpc.westlake.edu.cn/document/science/index.html"], "条目详情（样例 URL 会过期）"),
    ("hosts", ["hosts", "list", "--limit", "3"], "子站清单（缓存）"),
    ("hosts", ["hosts", "mine", "hpc"], "单站挖掘（--all 全量普查不入表）"),
    ("hosts", ["hosts", "show", "hpc"], "已挖掘站点的栏目条目"),
    ("affairs", ["affairs", "apps", "预约"], "办事大厅应用"),
    ("affairs", ["affairs", "links"], "常用服务入口直达（HPC/预约中心/镜像站）"),
    ("affairs", ["affairs", "portal"], "门户服务"),
    ("hpc", ["hpc", "overview"], "集群队列"),
    ("hpc", ["hpc", "ai"], "AI 网关"),
    ("finance", ["finance", "sections"], "财务栏目"),
    ("mirrors", ["mirrors"], "镜像目录"),
    ("probe", ["probe"], "堵点探测"),
    ("pms", ["pms", "stations"], "打印网点（匿名）"),
    ("scholar", ["scholar", "dbs"], "订阅数据库"),
    ("scholar", ["scholar", "campus"], "校园 IP 信标"),
    ("scholar", ["scholar", "carsi"], "CARSI 目录（随包快照，356 个 SP）"),
    ("scholar", ["scholar", "open", "cnki"], "打印某库直达/CARSI 入口 URL"),
    ("scholar", ["scholar", "status"], "CARSI 会话有效性（不弹窗）"),
    ("scholar", ["scholar", "doi", "10.1038/nature12373"], "DOI 题录解析（不带 --out 不下载）"),
    ("share", ["share", "saved"], "已登记分享"),
    ("share", ["share", "files", "--name", "2183-lecture-notes"], "列分享文件夹（需已登记分享）"),
    ("institute", ["institute", "news"], "理论院新闻动态"),
    ("institute", ["institute", "events"], "理论院学术活动"),
    ("schools", ["schools", "list"], "学院清单"),
    ("schools", ["schools", "news", "science"], "学院最新新闻"),
    ("sso", ["sso", "creds", "status"], "凭据来源有无（不回显密码）"),
    # —— 需凭据 / 校园网 ——
    ("lib", ["lib", "search", "数据结构"], "书目检索"),
    ("lib", ["lib", "loans"], "我的借阅"),
    ("pms", ["pms", "jobs"], "我的打印任务"),
    ("todo", ["todo", "list"], "办事待办"),
    ("todo", ["todo", "doing"], "我发起的进行中流程"),
    ("todo", ["todo", "done"], "我已处理的流程"),
    ("todo", ["todo", "cc"], "抄送给我的流程（未读）"),
    ("todo", ["todo", "apps"], "可发起/访问的应用"),
    ("sis", ["sis", "schedule"], "课表"),
    ("sis", ["sis", "grades"], "成绩"),
    ("sis", ["sis", "exams"], "考试"),
    ("sis", ["sis", "cart"], "选课车（只读）"),
    ("sis-evals", ["sis-evals", "list", "--pending"], "待评教"),
    ("profile", ["profile", "info"], "个人信息"),
    ("profile", ["profile", "academic"], "学籍数据"),
    ("profile", ["profile", "extended"], "扩展信息"),
    ("records", ["records", "second-class"], "第二课堂"),
    ("records", ["records", "advisor"], "学业导师"),
    ("records", ["records", "dorm"], "住宿申请与宿舍信息"),
    ("records", ["records", "leave"], "请假申请"),
    ("records", ["records", "honors"], "荣誉记录"),
    ("records", ["records", "volunteer"], "志愿服务记录"),
    ("records", ["records", "vol-history"], "志愿服务历史（含总时长）"),
    ("records", ["records", "practice"], "社会实践记录"),
    ("records", ["records", "discipline"], "违纪信息"),
    ("records", ["records", "appointments"], "本周预约（心理健康）"),
    ("records", ["records", "registration"], "学期注册缴费状态"),
    ("records", ["records", "leaving-check"], "离校自查清单"),
    ("records", ["records", "source-info"], "生源信息确认状态"),
    ("records", ["records", "other-apps"], "异动/认定/衔接/就业申请状态"),
    ("aid", ["aid", "loans"], "贷款记录"),
    ("aid", ["aid", "jobs"], "勤工助学岗位/工时/工资"),
    ("aid", ["aid", "outbound"], "海外交流派出申请"),
    ("aid", ["aid", "exchange"], "交换生申请记录"),
    ("aid", ["aid", "orgs"], "学生组织与社团目录"),
    ("aid", ["aid", "activities"], "社团活动登记记录"),
    ("aid", ["aid", "claim"], "工时申报状态（有无岗位）"),
    ("portal", ["portal", "cards"], "门户个人卡片（未读/在借/待办）"),
    ("sso", ["sso", "login"], "验证 SIS 凭据有效性"),
    ("canvas", ["canvas", "courses"], "Canvas 课程"),
    ("canvas", ["canvas", "deadlines", "--limit", "3"], "作业截止"),
    ("canvas", ["canvas", "exams", "--days", "30"], "考试安排"),
    ("canvas", ["canvas", "todo", "--limit", "5"], "Canvas 待办"),
    ("canvas", ["canvas", "assignments", "--course", "概率论"], "课程作业列表（课程名随学期）"),
    ("canvas", ["canvas", "assignment-info", "--course", "概率论", "--assignment", "Quiz 1"], "作业详情（参数随学期）"),
    ("canvas", ["canvas", "files", "--course", "概率论"], "课程文件区清单"),
    ("canvas", ["canvas", "discussions", "--course", "马克思"], "课程讨论主题"),
    ("canvas", ["canvas", "announcements", "--course", "概率论"], "课程公告"),
    ("canvas", ["canvas", "discussion", "--course", "马克思", "--topic", "什么是空间"], "讨论主题正文"),
    ("canvas", ["canvas", "entries", "--course", "马克思", "--topic", "什么是空间", "--limit", "5"], "讨论回帖列表"),
    ("canvas", ["canvas", "inbox", "--limit", "5"], "收件箱会话"),
    ("canvas", ["canvas", "conversation", "2041"], "会话全文（id 由 inbox 给出）"),
    ("canvas", ["canvas", "modules", "概率论"], "课程模块与条目"),
    ("canvas", ["canvas", "submission", "--course", "概率论", "--assignment", "Quiz 1"], "作业提交状态"),
    ("booking", ["booking", "types"], "预约中心分类"),
    ("booking", ["booking", "sports"], "预约中心体育类体检"),
    ("booking", ["booking", "list", "--type", "图书馆"], "可预约资源列表"),
    ("booking", ["booking", "days", "E12-302研讨室", "--start", "2026-11-02", "--end", "2026-11-08"], "某资源逐日可约（日期样例）"),
    ("booking", ["booking", "slots", "E12-302研讨室", "--date", "2026-11-03"], "某资源空闲时段（日期样例）"),
    ("booking", ["booking", "mine"], "我的预约"),
    ("sport", ["sport", "scenes"], "场馆场景"),
    ("sport", ["sport", "sites", "游泳次卡"], "场景当日场地与可约状态"),
    ("sport", ["sport", "days", "游泳次卡", "游泳场次"], "逐日可约与不可约原因"),
    ("sport", ["sport", "mine"], "我的场馆预约"),
]


@dataclass
class Result:
    module: str
    argv: str
    note: str
    status: str
    detail: str
    seconds: float


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


def main() -> int:
    argv = sys.argv[1:]
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
    args = [a for a in argv if not a.startswith("--")]
    as_json = bool(out_path) or bare_json or "--stdout-json" in sys.argv
    chosen = [row for row in COMMANDS if not args or any(a in row[0] for a in args)]
    results: list[Result] = []
    for module, argv, note in chosen:
        status, detail, seconds = run(argv)
        results.append(Result(module, " ".join(argv), note, status, detail, seconds))
        if not as_json:
            print(f"{status:8}{module:12}{' '.join(argv)}  ← {detail}", flush=True)

    if not as_json:
        print()
        counts: dict[str, int] = {}
        for item in results:
            counts[item.status] = counts.get(item.status, 0) + 1
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
