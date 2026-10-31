"""SkillVM JIT 运行时优化引擎（Just-In-Time Runtime & Environment Prober）。

在目标机器上运行时，动态探测宿主环境指标（操作系统、Python 解释器真实位置、
网络拓扑与校园凭据状态），即时编译生成最适配当前机器与会话的执行上下文与固化管道。
"""
from __future__ import annotations

import os
import platform
import shutil
import sys
from dataclasses import asdict, dataclass
from typing import Any

from westlake_survival.exceptions import is_offcampus


@dataclass
class HostEnvironmentProfile:
    """目标电脑当前宿主环境画像。"""

    os_system: str
    os_release: str
    machine_arch: str
    python_executable: str
    is_in_venv: bool
    has_playwright: bool
    has_keyring: bool
    network_is_offcampus: bool
    credentials_sis_present: bool
    credentials_canvas_present: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class JITRuntime:
    """JIT 即时环境探测与特化优化器。"""

    @classmethod
    def probe_host(cls) -> HostEnvironmentProfile:
        """运行即时探针，获取当前机器的硬件、环境与网络画像。"""
        # 1. 基础系统与解释器
        os_sys = platform.system()
        os_rel = platform.release()
        arch = platform.machine()
        py_exe = sys.executable
        is_venv = hasattr(sys, "real_prefix") or (
            hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix
        )

        # 2. 可选依赖检查
        try:
            import playwright  # noqa: F401

            has_pw = True
        except ImportError:
            has_pw = False

        try:
            import keyring  # noqa: F401

            has_kr = True
        except ImportError:
            has_kr = False

        # 3. 网络环境（校内/校外/VPN）
        try:
            from westlake_survival.discovery import direct_session

            # 探校内信标
            s = direct_session()
            resp = s.get("https://iam.westlake.edu.cn/", timeout=3.0)
            offcampus = False
        except Exception:
            offcampus = True

        # 4. 凭据状态检查
        has_sis = False
        try:
            from westlake_survival.sso import read_credentials

            sid, pwd = read_credentials()
            has_sis = bool(sid and pwd)
        except Exception:
            has_sis = False

        has_canvas = False
        try:
            from westlake_survival.canvas import resolve_token

            tok = resolve_token()
            has_canvas = bool(tok)
        except Exception:
            has_canvas = False

        return HostEnvironmentProfile(
            os_system=os_sys,
            os_release=os_rel,
            machine_arch=arch,
            python_executable=py_exe,
            is_in_venv=is_venv,
            has_playwright=has_pw,
            has_keyring=has_kr,
            network_is_offcampus=offcampus,
            credentials_sis_present=has_sis,
            credentials_canvas_present=has_canvas,
        )

    @classmethod
    def generate_jit_context_patch(cls) -> str:
        """根据当前宿主机器画像，即时编译生成上下文补丁提示。"""
        host = cls.probe_host()
        patches: list[str] = [
            f"⚡ [SkillVM JIT 运行时特化 (Host: {host.os_system} {host.machine_arch}, Python: {os.path.basename(host.python_executable)})]"
        ]

        # 解释器一致性补丁
        if " " in host.python_executable:
            patches.append(f"- 解释器路径含空格，建议统一使用 `python -m westlake_survival <命令>` 调用；")

        # 网络环境补丁
        if host.network_is_offcampus:
            patches.append(
                "- ⚠️ 当前处于校外且未连接校园 VPN：教务实时接口受限，已自动启用 --offline 优先模式（历史快照秒出）；"
            )
        else:
            patches.append("- ✓ 当前处于校园网或 VPN 连接态：全域在线服务均可直达；")

        # 凭据自愈引导
        if not host.credentials_sis_present:
            patches.append("- 💡 未配置教务凭据：如需查询个人课表或成绩，引导用户运行 `westlake setup` 配置；")

        # 过程固化推荐
        patches.append(
            "- 🚀 JIT 固化管道：查询今日全天日程安排请直接执行 `westlake timeline`，寻找研讨室请直接执行 `westlake booking recommend`。"
        )

        return "\n".join(patches)

    @classmethod
    def solidify_intent(cls, user_intent: str) -> str | None:
        """JIT 过程固化：将常见的复合场景意图直接编译为最优单步指令。"""
        q = (user_intent or "").lower()
        if any(k in q for k in ("今天安排", "今天日程", "今日安排", "今日日程", "今天上课", "timeline", "行动流")):
            return "westlake timeline"
        if any(k in q for k in ("找研讨室", "找自习室", "空闲研讨室", "空闲自习室", "推荐房间", "推荐场地")):
            return "westlake booking recommend --date today --min-hours 1.5"
        if any(k in q for k in ("放假", "校历", "第几周", "今天几号")):
            return "westlake calendar today --offline"
        if any(k in q for k in ("班车时刻", "下一班车", "校车")):
            return "westlake transit next --limit 3"
        return None
