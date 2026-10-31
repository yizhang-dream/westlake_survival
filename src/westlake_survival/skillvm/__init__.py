"""SkillVM（Skill Virtual Machine）编译器与运行时体系。

借鉴现代系统编译器与 SkVM（SJTU-IPADS, skillvm.ai）架构思想：
- AOT 静态特化编译：面向不同智能体框架（ZCode / Claude Code / Cursor / MCP）
  与异构模型认知档位（Frontier 强推理大模型 vs Compact 紧凑小模型）生成优化产物；
- JIT 运行时即时优化：动态探针感知宿主操作系统、真实 Python 解释器、网络连通态与已存凭据，
  即时编译生成自适应执行上下文，并将高频复合场景过程固化为单步指令；
- 跨机一键挂载：消除硬编码绝对路径，在任何机器上一键完成 Skill 安装与跨框架自愈。
"""
from __future__ import annotations

from westlake_survival.skillvm.compiler import (
    AOTCompiler,
    CompilationResult,
    HarnessTarget,
    ModelProfile,
)
from westlake_survival.skillvm.installer import SkillInstaller
from westlake_survival.skillvm.ir import (
    CapabilityDomain,
    CapabilityEntry,
    SkillIR,
    WriteOperationIR,
    build_canonical_ir,
)
from westlake_survival.skillvm.runtime import HostEnvironmentProfile, JITRuntime

__all__ = [
    "AOTCompiler",
    "CapabilityDomain",
    "CapabilityEntry",
    "CompilationResult",
    "HarnessTarget",
    "HostEnvironmentProfile",
    "JITRuntime",
    "ModelProfile",
    "SkillIR",
    "SkillInstaller",
    "WriteOperationIR",
    "build_canonical_ir",
]
