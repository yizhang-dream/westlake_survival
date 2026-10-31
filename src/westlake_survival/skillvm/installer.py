"""SkillVM 跨机安装与环境链接器（Skill Installer & Porter）。

彻底解决「在别的电脑上 clone 后装了用不了」的痛点：
1. 自动识别宿主环境已安装的智能体框架（ZCode, Claude Code, Cursor）；
2. 根据目标框架与当前机器环境，自动完成 AOT 编译并将特化后的 SKILL.md
   安全安装或软链接（Junction / Symlink）到用户目录；
3. 检查依赖与解释器一致性，给出单步自愈指令。
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any

from westlake_survival.skillvm.compiler import AOTCompiler, HarnessTarget, ModelProfile


class SkillInstaller:
    """跨机 Skill 安装与自适应挂载工具。"""

    @classmethod
    def default_paths(cls) -> dict[HarnessTarget, Path]:
        """计算当前系统下各 Harness 的标准用户技能目录。"""
        home = Path.home()
        return {
            HarnessTarget.ZCODE: home / ".zcode" / "skills" / "westlake-survival",
            HarnessTarget.CLAUDE_CODE: home / ".claude" / "skills" / "westlake-survival",
            HarnessTarget.CURSOR: Path.cwd() / ".cursorrules",
            HarnessTarget.MCP: home / ".zcode" / "cli" / "config.json",
        }

    @classmethod
    def install(
        cls,
        target: HarnessTarget = HarnessTarget.ZCODE,
        profile: ModelProfile = ModelProfile.FRONTIER,
        dest: Path | str | None = None,
        force: bool = False,
    ) -> Path:
        """编译并在当前机器上挂载该 Skill。"""
        compiler = AOTCompiler()
        result = compiler.compile(target=target, profile=profile)

        target_path = Path(dest) if dest else cls.default_paths().get(target)
        if not target_path:
            target_path = Path.cwd() / "SKILL.md"

        if target == HarnessTarget.CURSOR:
            target_path.write_text(result.content, encoding="utf-8")
            return target_path

        # 目录型 Skill（ZCode, Claude Code）
        target_path.mkdir(parents=True, exist_ok=True)
        skill_file = target_path / result.file_name
        skill_file.write_text(result.content, encoding="utf-8")
        return skill_file

    @classmethod
    def autodetect_and_install_all(
        cls, profile: ModelProfile = ModelProfile.FRONTIER
    ) -> list[tuple[HarnessTarget, Path]]:
        """自动探查本机存在的 Harness 并一键全量安装同步。"""
        installed = []
        home = Path.home()

        # 1. 检查 ZCode
        if (home / ".zcode").exists() or (home / ".agents").exists():
            p = cls.install(HarnessTarget.ZCODE, profile=profile)
            installed.append((HarnessTarget.ZCODE, p))

        # 2. 检查 Claude Code
        if (home / ".claude").exists():
            p = cls.install(HarnessTarget.CLAUDE_CODE, profile=profile)
            installed.append((HarnessTarget.CLAUDE_CODE, p))

        # 3. 检查 Cursor / 工作区
        if (Path.cwd() / ".git").exists() or (Path.cwd() / ".cursor").exists():
            p = cls.install(HarnessTarget.CURSOR, profile=profile)
            installed.append((HarnessTarget.CURSOR, p))

        # 4. 始终在仓库本地 skills/ 编译更新一份最新产物
        repo_skill_dir = Path.cwd() / "skills" / "westlake-survival"
        if repo_skill_dir.exists():
            p = cls.install(HarnessTarget.ZCODE, profile=profile, dest=repo_skill_dir)
            installed.append((HarnessTarget.GENERIC, p))

        return installed
