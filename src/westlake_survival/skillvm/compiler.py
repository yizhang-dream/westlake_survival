"""SkillVM AOT 编译器（Ahead-Of-Time Compiler）。

借鉴 SkVM（SJTU-IPADS, skillvm.ai）现代系统编译器思想：
将 Canonical Skill IR 针对异构 Harness（ZCode, Claude Code, Cursor, MCP）
与异构 Model 架构（Frontier 强推理大模型 vs Compact 轻量上下文受限模型）
进行 AOT 静态特化编译。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from westlake_survival.skillvm.ir import CapabilityEntry, SkillIR, build_canonical_ir


class HarnessTarget(str, Enum):
    """目标智能体框架 / 宿主环境。"""

    ZCODE = "zcode"
    CLAUDE_CODE = "claude"
    CURSOR = "cursor"
    MCP = "mcp"
    GENERIC = "generic"


class ModelProfile(str, Enum):
    """目标模型架构与能力档位。"""

    FRONTIER = "frontier"  # -O0: Claude 3.5 Sonnet / Opus / GPT-4o（全量上下文、深层推理）
    COMPACT = "compact"    # -Os: Haiku / Flash / DeepSeek 7B/14B（高密度缩减、能力补偿、防幻觉）
    MICRO = "micro"        # -O3: 超轻量常驻微内核（<250 Token，动态分页，极致节省上下文占用）


@dataclass
class CompilationResult:
    """AOT 编译产物包。"""

    target: HarnessTarget
    profile: ModelProfile
    file_name: str
    content: str
    metadata: dict[str, Any]

    def save_to(self, output_dir: Path | str) -> Path:
        p = Path(output_dir) / self.file_name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.content, encoding="utf-8")
        return p


class AOTCompiler:
    """Skill 静态优化与代码生成编译器。"""

    def __init__(self, ir: SkillIR | None = None) -> None:
        self.ir = ir or build_canonical_ir()

    def compile(
        self,
        target: HarnessTarget = HarnessTarget.ZCODE,
        profile: ModelProfile = ModelProfile.FRONTIER,
    ) -> CompilationResult:
        """主编译入口：运行优化 Pass 并生成对应 Harness 的代码。"""
        # 1. 运行 Model 认知优化 Pass
        optimized_ir = self._apply_model_passes(self.ir, profile)

        # 2. 调用目标 Harness 后端代码生成器
        if target == HarnessTarget.ZCODE:
            content = self._emit_zcode(optimized_ir, profile)
            file_name = "SKILL.md"
        elif target == HarnessTarget.CLAUDE_CODE:
            content = self._emit_claude_code(optimized_ir, profile)
            file_name = "SKILL.md"
        elif target == HarnessTarget.CURSOR:
            content = self._emit_cursor_rules(optimized_ir, profile)
            file_name = ".cursorrules"
        elif target == HarnessTarget.MCP:
            content = self._emit_mcp_config(optimized_ir)
            file_name = "mcp_config.json"
        else:
            content = self._emit_generic(optimized_ir, profile)
            file_name = "SKILL.md"

        return CompilationResult(
            target=target,
            profile=profile,
            file_name=file_name,
            content=content,
            metadata={"version": self.ir.version, "rules_count": len(optimized_ir.rules)},
        )

    def _apply_model_passes(self, ir: SkillIR, profile: ModelProfile) -> SkillIR:
        """根据模型 Profile 应用优化 Pass。"""
        if profile == ModelProfile.FRONTIER:
            return ir  # -O0: 全量保持

        if profile == ModelProfile.MICRO:
            # -O3: Micro-Kernel Pass（死代码消除 + 核心分页）
            # 仅保留最核心的高频入口，其余收敛至 westlake find 动态加载，Token 缩减 85%
            micro_caps = [c for c in ir.capabilities if c.command.split()[0] in ("timeline", "booking", "calendar", "transit", "canvas", "find")]
            micro_rules = [
                "【严格安全】写操作必须先带 --dry-run 预检；严禁越界或进行未授权的写操作；",
                "【意图固化】日程查 timeline，空闲场地查 booking recommend，不确定查 find <词>；",
                "【离线优先】若遇网络异常，追加 --offline 即可直接拉取本地快照。",
            ]
            return SkillIR(
                name=ir.name,
                version=ir.version,
                title=f"{ir.title} (Micro Kernel)",
                summary="西湖大学服务微内核（时空行动流/课表/作业/班车/推荐）。不确定先运行 westlake find <关键词>。",
                capabilities=micro_caps[:7],
                write_operations=ir.write_operations[:4],
                rules=micro_rules,
                guidelines=["常用：westlake timeline（今日行动流）与 westlake find <词>（能力自发现）。"],
            )

        # -Os: Compact 模型优化 Pass（Capability Compensation & Token Pruning）
        # 剪枝次要修饰语，强调精确的命令输入输出与防偏离规则
        compensated_rules = [
            "【输出约束】只调用确定的 westlake 命令，严禁臆造子命令；",
            "【写操作门禁】遇到任何写操作，第一步必须带 --dry-run 查看 Action Card 预览；",
            "【复合命令优先】查日程优先使用 westlake timeline，查房间优先使用 westlake booking recommend；",
            "【离线自愈】遇到网络故障或无 VPN，必须追加 --offline 重新运行；",
            "【隐私守卫】绝不向终端回显密码或学号。",
        ]
        return SkillIR(
            name=ir.name,
            version=ir.version,
            title=ir.title,
            summary=ir.summary,
            capabilities=ir.capabilities,
            write_operations=ir.write_operations,
            rules=compensated_rules,
            guidelines=ir.guidelines[:3],
        )

    def _emit_zcode(self, ir: SkillIR, profile: ModelProfile) -> str:
        """ZCode 目标生成器：标准 SKILL.md，带前置元数据与相对路径约定。"""
        lines = [
            "---",
            f"name: {ir.name}",
            f"description: {ir.summary}",
            "---",
            "",
            f"# {ir.title}",
            "",
            "> ⚡ 本文件由 SkillVM AOT 编译器生成（Target: ZCode, Profile: "
            f"{profile.value.upper()}）。",
            "",
            "## 核心纪律与原则",
            "",
        ]
        for r in ir.rules:
            lines.append(f"- {r}")

        lines.extend([
            "",
            "## 能力路由表",
            "",
            "| 用户诉求 | 命令 | 离线支持 | 说明 |",
            "| :--- | :--- | :---: | :--- |",
        ])
        for c in ir.capabilities:
            offline_tag = "✓" if c.is_offline_ready else "—"
            lines.append(f"| {c.user_query} | `{c.command}` | {offline_tag} | {c.description} |")

        lines.extend([
            "",
            "## 受控写操作清单（Action Card 保护）",
            "",
            "| 操作名称 | 命令示例 | 风险等级 | 潜在影响 |",
            "| :--- | :--- | :---: | :--- |",
        ])
        for w in ir.write_operations:
            lines.append(f"| `{w.name}` | `{w.command}` | {w.severity.upper()} | {w.risk} |")

        lines.extend([
            "",
            "## 执行建议与最佳实践",
            "",
        ])
        for g in ir.guidelines:
            lines.append(f"1. {g}")

        lines.append("")
        return "\n".join(lines)

    def _emit_claude_code(self, ir: SkillIR, profile: ModelProfile) -> str:
        """Claude Code 目标生成器：针对 Claude CLI 环境优化。"""
        lines = [
            f"# {ir.title} (Claude Code Edition)",
            "",
            f"{ir.summary}",
            "",
            "## Quick Commands",
            "",
        ]
        for c in ir.capabilities:
            lines.append(f"- **{c.user_query}**: `westlake {c.command}`")

        lines.extend([
            "",
            "## Safety & Action Cards",
            "Write operations strictly require either `--yes` or `--ticket <ticket>` from Action Card preview:",
        ])
        for w in ir.write_operations:
            lines.append(f"- `{w.name}`: {w.description} (Risk: {w.severity})")

        lines.append("")
        return "\n".join(lines)

    def _emit_cursor_rules(self, ir: SkillIR, profile: ModelProfile) -> str:
        """Cursor / Codex rules 目标生成器。"""
        lines = [
            "# Cursor Rules for Westlake Survival",
            f"# {ir.summary}",
            "",
            "You are equipped with the `westlake` CLI toolkit for Westlake University campus services.",
            "",
            "## Golden Rules",
        ]
        for r in ir.rules:
            lines.append(f"- {r}")

        lines.extend([
            "",
            "## Capability Index",
        ])
        for c in ir.capabilities:
            lines.append(f"- When asked about '{c.user_query}', run: `westlake {c.command}`")

        lines.append("")
        return "\n".join(lines)

    def _emit_mcp_config(self, ir: SkillIR) -> str:
        """生成跨平台通用的 MCP 客户端连接配置。"""
        config = {
            "mcpServers": {
                "westlake": {
                    "command": "python",
                    "args": ["-m", "westlake_survival.mcp_server"],
                    "description": ir.summary,
                }
            }
        }
        return json.dumps(config, ensure_ascii=False, indent=2)

    def _emit_generic(self, ir: SkillIR, profile: ModelProfile) -> str:
        return self._emit_zcode(ir, profile)
