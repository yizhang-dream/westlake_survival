"""SkillVM 中间表示（Canonical Skill IR）——对标 SkVM 编译器前端架构。

将校园服务聚合工具的业务领域、能力路由、受控写操作、环境约束与行为纪律
解耦为中立的中间表示（SkillIR），为后续面向异构 Harness 与异构 Model 的
编译优化（AOT & JIT）提供统一输入。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from westlake_survival._version import __version__


class CapabilityDomain(str, Enum):
    """业务领域。"""

    TIMELINE = "时空行动流"
    ACADEMICS = "学业教务"
    CANVAS = "Canvas课程"
    BOOKING = "场地预约"
    SPORTS = "体育场馆"
    SCHOLAR = "学术科研"
    LIFE = "校园生活"
    AFFAIRS = "办事门户"
    SYSTEM = "系统可达性"


@dataclass(frozen=True)
class CapabilityEntry:
    """一个标准化的能力条目。"""

    user_query: str
    command: str
    description: str
    domain: CapabilityDomain
    requires_auth: bool = False
    is_offline_ready: bool = True
    example: str = ""


@dataclass(frozen=True)
class WriteOperationIR:
    """一个受控写操作的规约。"""

    name: str
    command: str
    description: str
    risk: str
    severity: str
    supports_dry_run: bool = True
    supports_ticket: bool = True


@dataclass
class SkillIR:
    """西湖大学工具包的 Canonical Skill Specification。"""

    name: str = "westlake-survival"
    version: str = __version__
    title: str = "西湖大学服务工具包（westlake-survival）"
    summary: str = "面向西湖大学师生的校园服务聚合工具（学业/教学/科研/生活/办事/信息六域）。"
    capabilities: list[CapabilityEntry] = field(default_factory=list)
    write_operations: list[WriteOperationIR] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)
    guidelines: list[str] = field(default_factory=list)


def build_canonical_ir() -> SkillIR:
    """构建全量标准 Skill IR。"""
    caps: list[CapabilityEntry] = [
        CapabilityEntry(
            "今天日程安排 / 时空行动流 / 冲突检测 / 个人备忘",
            "timeline [--offline]",
            "跨系统全天日程融合（课表/作业/预约/班车）、重叠冲突预警与个人备忘（支持离线秒出）",
            CapabilityDomain.TIMELINE,
            requires_auth=False,
            is_offline_ready=True,
            example="westlake timeline --offline",
        ),
        CapabilityEntry(
            "场地空闲智能推荐求解器（避免多次轮询）",
            "booking recommend [--date ...] [--time ...] [--min-hours ...]",
            "复合求解连续可用房间时段，给出单次预约预检指令",
            CapabilityDomain.BOOKING,
            requires_auth=True,
            is_offline_ready=False,
            example="westlake booking recommend --date today --min-hours 1.5",
        ),
        CapabilityEntry(
            "今天几号 / 第几周 / 校历事件 / 放假",
            "calendar today [--offline] / week N / events",
            "校历学期、教学周次、调休补课与假期安排",
            CapabilityDomain.LIFE,
            requires_auth=False,
            is_offline_ready=True,
            example="westlake calendar today --offline",
        ),
        CapabilityEntry(
            "下一班校车 / 班车时刻表 / 导出日历",
            "transit next / table [--offline] / transit ical",
            "三校区班车时刻与接驳建议",
            CapabilityDomain.LIFE,
            requires_auth=False,
            is_offline_ready=True,
            example="westlake transit table --offline",
        ),
        CapabilityEntry(
            "此刻快照 / 每日快报",
            "context [--level terse|normal|verbose] / digest",
            "聚合日期、周次、事件、天气与作业的一屏速览",
            CapabilityDomain.LIFE,
            requires_auth=False,
            is_offline_ready=True,
            example="westlake context --level terse",
        ),
        CapabilityEntry(
            "SIS 课表 / 成绩 / 考试安排 / 选课车",
            "sis schedule / grades / exams / cart / sis grid",
            "教务系统学业数据查询与周网格冲突预检（只读）",
            CapabilityDomain.ACADEMICS,
            requires_auth=True,
            is_offline_ready=True,
            example="westlake sis schedule",
        ),
        CapabilityEntry(
            "教学系统 AMS 课表 / 周次 / 学籍入口",
            "ams schedule / status / menus",
            "新版教学管理系统课表与学期（走 IAM 统一认证）",
            CapabilityDomain.ACADEMICS,
            requires_auth=True,
            is_offline_ready=True,
            example="westlake ams schedule",
        ),
        CapabilityEntry(
            "Canvas 课程 / 作业截止 / 待办 / 题目附件 / 收藏",
            "canvas courses / deadlines / todo / assignment-info / canvas star",
            "在修课程、作业详情、评分细则与面板置顶",
            CapabilityDomain.CANVAS,
            requires_auth=True,
            is_offline_ready=True,
            example="westlake canvas deadlines",
        ),
        CapabilityEntry(
            "图书馆书目检索 / 在借图书与应还 / 在线续借",
            "lib search <关键词> / lib loans / lib renew <条码>",
            "新版阿法迪云平台公开检索、在借查询与在线续借延期",
            CapabilityDomain.LIFE,
            requires_auth=True,
            is_offline_ready=False,
            example="westlake lib search 数据结构",
        ),
        CapabilityEntry(
            "场地预约分类 / 资源 / 空闲时段 / 我的预约",
            "booking types / list / days / slots / mine",
            "预约中心研习仓、研讨室、自习室逐格空闲状态",
            CapabilityDomain.BOOKING,
            requires_auth=True,
            is_offline_ready=False,
            example="westlake booking types",
        ),
        CapabilityEntry(
            "体育场馆与游泳（独立正元系统）",
            "sport scenes / sites / days / mine",
            "体育馆羽毛球/乒乓球/游泳场次可约状态（只读）",
            CapabilityDomain.SPORTS,
            requires_auth=True,
            is_offline_ready=False,
            example="westlake sport scenes",
        ),
        CapabilityEntry(
            "学术数据库 / CARSI 校外 SSO / DOI 论文全文",
            "scholar dbs / ensure / doi <doi> -o out.pdf",
            "订阅数据库列表、校外 SSO 会话保障与全文直接获取",
            CapabilityDomain.SCHOLAR,
            requires_auth=False,
            is_offline_ready=True,
            example="westlake scholar dbs",
        ),
        CapabilityEntry(
            "高性能计算 HPC / 免费大模型对话 / 镜像站",
            "hpc overview / hpc chat <内容> / mirrors",
            "调用校内 GPU 集群免费进行 DeepSeek/GLM/Qwen 对话",
            CapabilityDomain.SCHOLAR,
            requires_auth=False,
            is_offline_ready=True,
            example="westlake hpc chat 1+1=?",
        ),
        CapabilityEntry(
            "网上办事大厅 / 表单直达 / 官方 AI 问答",
            "affairs apps [关键词] / affairs app <名称> / portal ask <问题>",
            "办事流程说明、直达表单链接与权威 AI 办事问答",
            CapabilityDomain.AFFAIRS,
            requires_auth=False,
            is_offline_ready=True,
            example="westlake portal ask 图书馆开放时间",
        ),
        CapabilityEntry(
            "全校服务注册表 / 堵点探测 / VPN 隧道",
            "probe / services / vpn status",
            "全站 90+ 服务存活与隧道连通性探测",
            CapabilityDomain.SYSTEM,
            requires_auth=False,
            is_offline_ready=True,
            example="westlake probe",
        ),
    ]

    writes: list[WriteOperationIR] = [
        WriteOperationIR(
            "canvas.submit",
            "canvas submit --course … --assignment … --file …",
            "提交作业到 Canvas 课程（--dry-run 预览 / --ticket 或 --yes 执行）",
            "课程侧与教师可见；误交需重复提交覆盖或联系教师重置",
            "medium",
        ),
        WriteOperationIR(
            "canvas.reply",
            "canvas reply --course … --topic … --text …",
            "在课程讨论主题下发布一条回帖",
            "对全班可见，通常不可撤回",
            "medium",
        ),
        WriteOperationIR(
            "canvas.send",
            "canvas send --conversation … --text …",
            "在 Canvas 收件箱会话里发送私信",
            "发送后收件人立即可见，无法撤回",
            "medium",
        ),
        WriteOperationIR(
            "canvas.star",
            "canvas star <课程>",
            "将课程加入个人收藏列表（置顶于课程面板）",
            "仅改变个人视图展示，可随时取消收藏",
            "low",
        ),
        WriteOperationIR(
            "canvas.unstar",
            "canvas unstar <课程>",
            "将课程移出个人收藏列表",
            "仅改变个人视图，不影响选课与作业提交",
            "low",
        ),
        WriteOperationIR(
            "booking.book",
            "booking book <房间> --date … --start … --end …",
            "在预约中心创建一段场地预约",
            "占用他人可用名额，爽约可能影响信用",
            "medium",
        ),
        WriteOperationIR(
            "booking.cancel",
            "booking cancel <预约号>",
            "取消一段已有的场地预约",
            "释放名额，原时段需重新预约才能恢复",
            "low",
        ),
        WriteOperationIR(
            "lib.renew",
            "lib renew <图书条形码>",
            "在阿法迪云图书馆平台为在借图书在线续借",
            "延长图书应还日期，每本书通常限续借 1 次",
            "low",
        ),
        WriteOperationIR(
            "timeline.memo",
            "timeline add <备忘内容> [--time ...] / timeline done <ID>",
            "新增或标记完成个人生活备忘",
            "写入本地行动流，随时可增删改",
            "low",
        ),
    ]

    rules = [
        "默认只读与受控写操作：严禁越界，绝不执行选课、代抢课等任何未授权的系统写操作；",
        "事务预览卡片（Action Card）机制：写操作未带确认或加 --dry-run 时，自动输出结构化卡片与单次放行凭据 Ticket；",
        "免拼长参数闭环：支持传 --ticket <ticket> 执行放行，单次有效且防重放销毁；",
        "离线优先原则：遇校外无 VPN 或网络波动时，自动降级为本地快照并输出时间戳，不生硬报错；",
        "凭据单一存储与绝对保密：凭据优先存本机系统钥匙串，绝不在输出中打印学号与明文密码；",
        "网络直连规范：校内请求默认 trust_env=False 绕过全局代理，避免内网转发异常。",
    ]

    guidelines = [
        "遇到模糊需求先运行 `westlake find <关键词>` 自适应命中命令；",
        "日常早间先运行 `westlake timeline` 获得今日全局时空编排行动指南；",
        "寻找空闲自习室/研讨室时，优先运行 `westlake booking recommend` 复合求解，避免多次原子轮询；",
        "校外访问教务或 Canvas 时，若遇离线快照且需最新数据，先检查 `westlake vpn status`；",
        "写操作建议先加 `--dry-run` 获取 Action Card 预览，确认无误后再加 `--yes` 或带 Ticket 闭环。",
    ]

    return SkillIR(
        capabilities=caps,
        write_operations=writes,
        rules=rules,
        guidelines=guidelines,
    )
