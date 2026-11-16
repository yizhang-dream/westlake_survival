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

from westlake_survival.exceptions import WestlakeError
from westlake_survival.skillvm.compiler import AOTCompiler, HarnessTarget, ModelProfile


class SkillInstaller:
    """跨机 Skill 安装与自适应挂载工具。"""

    @staticmethod
    def _repo_skill_dir() -> Path | None:
        candidate = Path(__file__).resolve().parents[3] / "skills" / "westlake-survival"
        if candidate.is_dir():
            return candidate
        cwd_candidate = Path.cwd() / "skills" / "westlake-survival"
        return cwd_candidate if cwd_candidate.is_dir() else None

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

    @staticmethod
    def _is_link_or_junction(path: Path) -> bool:
        """探测是否为符号链接或 Windows 目录联接（Junction）。"""
        if path.is_symlink():
            return True
        if not path.exists():
            return False
        try:
            return os.path.realpath(str(path)) != os.path.abspath(str(path))
        except OSError:
            return False

    @classmethod
    def inspect_status(cls) -> dict[str, Any]:
        """巡检本机各智能体框架挂载状态与仓库真源文本同步情况。"""
        repo_skill = cls._repo_skill_dir()
        repo_md = (repo_skill / "SKILL.md") if repo_skill else None
        repo_text = repo_md.read_text(encoding="utf-8") if (repo_md and repo_md.is_file()) else None

        entries: list[dict[str, Any]] = []
        for target in (HarnessTarget.ZCODE, HarnessTarget.CLAUDE_CODE, HarnessTarget.CURSOR):
            p = cls.default_paths()[target]
            exists = p.exists()
            is_link = cls._is_link_or_junction(p) if exists else False
            resolved = ""
            if exists:
                try:
                    resolved = str(p.resolve())
                except OSError:
                    resolved = str(p)

            skill_file = p if target == HarnessTarget.CURSOR else (p / "SKILL.md")
            in_sync: bool | None = None
            if not exists:
                status = "missing"
                note = "尚未挂载"
            else:
                if repo_text is not None and skill_file.is_file():
                    try:
                        in_sync = skill_file.read_text(encoding="utf-8") == repo_text
                    except OSError:
                        in_sync = None
                if in_sync is True:
                    status = "ok"
                    note = "已挂载且与仓库 SKILL.md 一致"
                elif is_link:
                    status = "linked-outdated" if in_sync is False else "ok"
                    note = (
                        f"外部软链/联接 -> {resolved}（内容与仓库存在差异，请经由外部管理器同步）"
                        if in_sync is False
                        else f"外部软链/联接 -> {resolved}"
                    )
                else:
                    status = "outdated" if in_sync is False else "ok"
                    note = "已挂载但内容与仓库 SKILL.md 不同步" if in_sync is False else "已挂载"

            entries.append(
                {
                    "target": target.value,
                    "path": str(p),
                    "exists": exists,
                    "is_link": is_link,
                    "resolved_path": resolved,
                    "in_sync": in_sync,
                    "status": status,
                    "note": note,
                }
            )

        return {
            "python_executable": sys.executable,
            "repo_skill_dir": str(repo_skill) if repo_skill else "",
            "repo_skill_exists": bool(repo_md and repo_md.is_file()),
            "targets": entries,
        }

    @classmethod
    def install(
        cls,
        target: HarnessTarget = HarnessTarget.ZCODE,
        profile: ModelProfile = ModelProfile.FRONTIER,
        dest: Path | str | None = None,
        force: bool = False,
        aot: bool = False,
    ) -> Path:
        """编译并在当前机器上挂载该 Skill。"""
        repo_skill = cls._repo_skill_dir()
        repo_md = (repo_skill / "SKILL.md") if repo_skill else None
        use_full_manual = (
            not aot
            and profile == ModelProfile.FRONTIER
            and target in (HarnessTarget.ZCODE, HarnessTarget.CLAUDE_CODE)
            and repo_md is not None
            and repo_md.is_file()
        )
        if use_full_manual:
            content = repo_md.read_text(encoding="utf-8")
            file_name = "SKILL.md"
        else:
            compiler = AOTCompiler()
            result = compiler.compile(target=target, profile=profile)
            content = result.content
            file_name = result.file_name

        target_path = Path(dest) if dest else cls.default_paths().get(target)
        if not target_path:
            target_path = Path.cwd() / "SKILL.md"

        if target == HarnessTarget.CURSOR:
            target_path.write_text(content, encoding="utf-8")
            return target_path

        if target == HarnessTarget.MCP and target_path.suffix == ".json":
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(content, encoding="utf-8")
            return target_path

        # 保护仓库真源及指向仓库的 Junction/Symlink，防止编译产物覆盖手写 SKILL.md
        if (
            repo_skill is not None
            and target_path.exists()
            and target_path.resolve() == repo_skill.resolve()
        ):
            return target_path / file_name

        # 保护外部管理器接管的软链/Junction（如 agent-skills-external），禁止静默覆写
        if target_path.exists() and cls._is_link_or_junction(target_path) and not force:
            resolved = str(target_path.resolve())
            raise WestlakeError(
                f"{target_path} 是指向外部目录（{resolved}）的软链/联接，"
                "已跳过覆盖以保护外部技能真源；若确定写入此路径请传 --force。"
            )

        # 目录型 Skill（ZCode, Claude Code）
        target_path.mkdir(parents=True, exist_ok=True)
        skill_file = target_path / file_name
        skill_file.write_text(content, encoding="utf-8")
        if repo_skill is not None:
            for sub in ("scripts", "references"):
                src_sub = repo_skill / sub
                if src_sub.is_dir():
                    shutil.copytree(src_sub, target_path / sub, dirs_exist_ok=True)
        return skill_file

    @classmethod
    def autodetect_and_install_all(
        cls,
        profile: ModelProfile = ModelProfile.FRONTIER,
        *,
        force: bool = False,
        aot: bool = False,
    ) -> list[tuple[HarnessTarget, Path]]:
        """自动探查本机存在的 Harness 并一键全量安装同步。"""
        installed = []
        home = Path.home()

        # 1. 检查 ZCode
        if (home / ".zcode").exists() or (home / ".agents").exists():
            p = cls.install(HarnessTarget.ZCODE, profile=profile, force=force, aot=aot)
            installed.append((HarnessTarget.ZCODE, p))

        # 2. 检查 Claude Code
        if (home / ".claude").exists():
            p = cls.install(HarnessTarget.CLAUDE_CODE, profile=profile, force=force, aot=aot)
            installed.append((HarnessTarget.CLAUDE_CODE, p))

        # 3. 仅在存在 .cursor 目录时同步生成 .cursorrules
        if (Path.cwd() / ".cursor").exists():
            p = cls.install(HarnessTarget.CURSOR, profile=profile, force=force, aot=aot)
            installed.append((HarnessTarget.CURSOR, p))

        return installed
