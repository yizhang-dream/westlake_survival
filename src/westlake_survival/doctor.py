"""环境自检：解释器 / 包 / 命令 / 可选依赖 / 凭据 / 网络，缺什么给一条能直接抄的修复命令。

用途
====
Agent 拿到本 skill 的第一件事是 ``westlake doctor``：全绿就直接干活；有 MISSING
就照「修复」列的原文执行，不用去读 README 猜。人也可以跑，输出是给人看的。

判定口径
========
* 只报「有 / 无」与路径，**绝不回显学号、密码、令牌**；
* ``missing`` = 缺了就干不了对应的事；``warn`` = 能降级但值得知道；
* 退出码：有任何 ``missing`` 返回 1，否则 0（便于脚本/Agent 判断）。
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from dataclasses import asdict, dataclass, field

__all__ = ["Check", "run_checks", "as_dict", "has_missing"]


@dataclass
class Check:
    """一项检查结果。``status`` 取 ok / warn / missing。"""

    key: str
    name: str
    status: str
    detail: str
    fix: str = ""


#: 可选依赖 → （展示名，装它的命令，缺了会影响什么）。
_OPTIONAL = (
    (
        "flask",
        "Web 界面（基础依赖）",
        "在仓库目录运行：pip install -e .（缺它通常是旧包或 --no-deps 装的）",
        "起不了网页（`westlake` 默认就是开网页「设置」）",
    ),
)

#: 公开站点：判断「这台机器能不能直连校园网之外的世界」。
_PUBLIC_PROBE = "https://www.westlake.edu.cn/"


def _spec(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _check_python() -> Check:
    ok = sys.version_info >= (3, 10)
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    return Check(
        key="python",
        name="解释器",
        status="ok" if ok else "missing",
        detail=f"Python {version} @ {sys.executable}",
        fix="" if ok else "装 Python 3.10+，再在仓库目录 pip install -e .",
    )


def _check_package() -> Check:
    from westlake_survival._version import __version__

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return Check(
        key="package",
        name="包本体",
        status="ok",
        detail=f"westlake_survival {__version__}（{root}）",
    )


def _check_command() -> Check:
    """``westlake`` 是否在 PATH 上，以及它是否指向当前这个解释器。

    两个环境各装一份是最常见的「明明装了却用不了」：命令跑的是 A 环境，
    Agent 用 B 环境的 ``python`` 写脚本，两边看到的包与凭据都不一样。
    """
    exe = shutil.which("westlake")
    if not exe:
        return Check(
            key="command",
            name="命令 westlake",
            status="warn",
            detail="不在 PATH 上；可用 python -m westlake_survival 等效调用",
            fix="在仓库目录 pip install -e .（或把 Scripts/bin 目录加进 PATH）",
        )
    same = os.path.normcase(os.path.dirname(os.path.abspath(exe))) == os.path.normcase(
        os.path.dirname(os.path.abspath(sys.executable))
    )
    if same:
        return Check(key="command", name="命令 westlake", status="ok", detail=exe)
    return Check(
        key="command",
        name="命令 westlake",
        status="warn",
        detail=f"{exe}（与当前解释器 {sys.executable} 不是同一个环境）",
        fix="统一解释器：用 python -m westlake_survival 调用，或把包装进同一个环境",
    )


def _check_optionals() -> list[Check]:
    checks: list[Check] = []
    for module, name, fix, impact in _OPTIONAL:
        present = _spec(module)
        checks.append(
            Check(
                key=module,
                name=name,
                status="ok" if present else "missing",
                detail="已安装" if present else f"缺 {module}：{impact}",
                fix="" if present else fix,
            )
        )
    return checks


def _check_playwright() -> Check:
    """浏览器链路是可选增强（2026-10-29 用户裁定：没有浏览器也能用）。

    缺 playwright 只报 warn 不挡活：share 讲义 / hosts 渲染深挖 / CARSI
    校外 SSO 三条链路自动降级，其余全部功能照常，装不装都不影响退出码。
    """
    if _spec("playwright"):
        return Check(key="playwright", name="浏览器链路（browser，可选）", status="ok",
                     detail="已安装")
    return Check(
        key="playwright",
        name="浏览器链路（browser，可选）",
        status="warn",
        detail="缺 playwright：share 讲义 / hosts 渲染深挖 / CARSI 校外 SSO 三条链路自动降级，其余功能不受影响",
        fix="需要这三条链路时：在仓库目录运行 pip install -e '.[browser]'，然后 playwright install chromium"
            "；Linux 无桌面环境缺系统库时再补 playwright install-deps chromium",
    )


def _check_keyring() -> Check:
    """keyring 装了不等于能用：无桌面/D-Bus 的 Linux 上没有任何可用后端。

    只 ``find_spec`` 会把「已安装但运行时必失败」误报成 ✔；真实取一次后端，
    落在 fail/null 兜底上就如实降级为 warn（凭据退回明文文件存）。
    """
    if not _spec("keyring"):
        return Check(
            key="keyring",
            name="钥匙串（secure）",
            status="missing",
            detail="缺 keyring：凭据退回明文文件存，能用但不加密",
            fix="在仓库目录运行：pip install -e '.[secure]'",
        )
    try:
        import keyring

        backend = keyring.get_keyring()
        mod = type(backend).__module__
    except Exception as exc:  # noqa: BLE001 - 取后端失败也是一种不可用
        return Check(
            key="keyring",
            name="钥匙串（secure）",
            status="warn",
            detail=f"keyring 已安装但取后端失败（{exc.__class__.__name__}）：凭据退回明文文件存",
            fix="",
        )
    if ".fail" in mod or ".null" in mod:
        return Check(
            key="keyring",
            name="钥匙串（secure）",
            status="warn",
            detail="keyring 已安装但无可用后端（Linux 无桌面钥匙串/D-Bus 服务时常见）：凭据退回明文文件存",
            fix="无桌面环境可接受此降级；桌面会话安装 gnome-keyring 可启用加密存储",
        )
    return Check(key="keyring", name="钥匙串（secure）", status="ok",
                 detail=f"已安装（{type(backend).__name__}）")


def _check_credentials() -> Check:
    try:
        from westlake_survival.sso import read_credentials

        read_credentials()
        detail = "已配置（来源有，不回显）"
        status = "ok"
        fix = ""
    except Exception:
        detail = "未配置：课表/成绩/作业/图书馆这些要登录的功能用不了，公开功能照常"
        status = "warn"
        fix = "由本人在网页「设置」页填一次：运行 `westlake`（或启动脚本 start.bat / start.command / start.sh）；Agent 不得代填"
    return Check(key="credentials", name="校园账号", status=status, detail=detail, fix=fix)


def _check_canvas_token() -> Check:
    from westlake_survival.canvas.client import TOKEN_ENV_VAR

    env = bool(os.environ.get(TOKEN_ENV_VAR))
    return Check(
        key="canvas_token",
        name="Canvas 令牌（选填）",
        status="ok",
        detail="有环境变量令牌" if env else "无独立令牌，走统一密码（IAM CAS 会话）",
    )


def _check_network() -> Check:
    """直连探一次公开站点：排除代理劫持与「根本连不上网」。"""
    import requests

    session = requests.Session()
    session.trust_env = False  # 全库默认直连，与业务口径一致
    try:
        resp = session.get(_PUBLIC_PROBE, timeout=5)
        ok = resp.status_code < 500
        return Check(
            key="network",
            name="网络（直连）",
            status="ok" if ok else "warn",
            detail=f"{_PUBLIC_PROBE} → HTTP {resp.status_code}",
            fix="" if ok else "检查网络；校园内网服务还需校园网或 VPN",
        )
    except Exception as exc:  # noqa: BLE001 - 任何失败都只影响这一项
        return Check(
            key="network",
            name="网络（直连）",
            status="warn",
            detail=f"{_PUBLIC_PROBE} 连不上（{exc.__class__.__name__}）",
            fix="先确认能上网；校外访问教务/Canvas 要连 VPN（`westlake vpn status`）",
        )


def run_checks(*, network: bool = True) -> list[Check]:
    """跑全部检查。``network=False`` 时跳过联网探测（离线/脚本用）。"""
    checks = [_check_python(), _check_package(), _check_command()]
    checks.extend(_check_optionals())
    checks.append(_check_playwright())
    checks.append(_check_keyring())
    checks.append(_check_credentials())
    checks.append(_check_canvas_token())
    if network:
        checks.append(_check_network())
    return checks


def has_missing(checks: list[Check]) -> bool:
    return any(c.status == "missing" for c in checks)


def as_dict(checks: list[Check]) -> dict:
    """结构化输出（给 Agent / 脚本）：不返回任何凭据内容。"""
    return {
        "ok": not has_missing(checks),
        "missing": [c.key for c in checks if c.status == "missing"],
        "warn": [c.key for c in checks if c.status == "warn"],
        "checks": [asdict(c) for c in checks],
    }
