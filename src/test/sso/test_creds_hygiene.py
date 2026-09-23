"""凭据卫生静态扫描：凭据路径知识必须收敛在 ``sso/`` 目录内。

纪律：只有 :mod:`westlake_survival.sso` 包内的模块可以直接拼装凭据文件路径、
读 ``~/.westlake_survival``、操作 ``credentials.txt`` / ``session.json``；
其它模块若需要这些能力，必须经 ``sso`` 的公开 API（``cred_path`` /
``read_credentials`` / ``write_credentials`` / ``*_keyring`` 等）——调用公开
API 不算泄漏，本测试只盯「自行拼装路径 / 自行推导主目录」这类知识复制。

本测试**不导入**被测模块，只读源码文本做模式扫描，因此不受运行时状态影响。
少数既有模块因历史原因就地实现了配置根目录逻辑（见 *EXEMPTIONS*），逐条
显式豁免并注明理由；新增豁免必须在此登记。
"""

from __future__ import annotations

import re
from pathlib import Path

#: 源码包根：本文件位于 ``src/test/sso/``，``parents[2] == src``。
PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "westlake_survival"

#: 允许自由出现凭据路径模式的目录（相对包根，posix 风格）。
ALLOWED_PREFIX = "sso/"

#: 扫描的模式：名称 -> 编译后的正则。只覆盖「凭据路径/落盘位置知识」，
#: 不含环境变量名或公开 API 标识符（那些是接口，不在此纪律范围内）。
PATTERNS: dict[str, re.Pattern[str]] = {
    # 凭据文件名（含文档字符串里的路径示例）。
    "credentials_filename": re.compile(r"credentials\.txt"),
    # 默认配置目录字面量 ``~/.westlake_survival``。
    "config_dir_literal": re.compile(r"\.westlake_survival\b"),
    # 主目录推导：``Path.home()`` / ``.expanduser()``。
    "home_dir": re.compile(r"Path\.home\s*\(|\.expanduser\s*\("),
    # 会话落盘文件名。
    "session_file": re.compile(r"session\.json"),
    # 针对凭据/配置路径的 ``open(`` 调用（同一行同时出现 open 与凭据线索）。
    "open_on_cred_path": re.compile(
        r"open\s*\(.*(credential|session\.json|\.westlake_survival)", re.IGNORECASE
    ),
}

#: 显式豁免名单：``相对包根的 posix 路径`` -> ``{模式名: 豁免理由}``。
#: 每一条都是对既有代码的就地登记，不覆盖新代码；新增请务必写明理由。
EXEMPTIONS: dict[str, dict[str, str]] = {
    "_cache.py": {
        "config_dir_literal": "配置根目录的唯一定义处（模块职责即此）",
        "home_dir": "配置根目录默认值 ~/.westlake_survival 的推导处",
    },
    "canvas/client.py": {
        "config_dir_literal": "Canvas API token 文件（非登录凭据），自带 WESTLAKE_HOME 重定位",
        "home_dir": "同上：Canvas token 路径的默认根目录推导",
    },
    "cli/main.py": {
        "config_dir_literal": "仅出现在 Canvas token 的提示文案里（非登录凭据路径逻辑）",
    },
    "mcp_server.py": {
        "config_dir_literal": "仅出现在 Canvas token 的文档串/引导文案里（非登录凭据）",
    },
}


def scan_text(rel_path: str, text: str) -> list[tuple[str, int, str]]:
    """扫描单个文件文本，返回 ``[(模式名, 行号, 行内容)]``（已剔除豁免）。

    ``rel_path`` 为相对包根的 posix 路径；``sso/`` 下的文件整体放行。
    """
    if rel_path.startswith(ALLOWED_PREFIX):
        return []
    exempt = EXEMPTIONS.get(rel_path, {})
    hits: list[tuple[str, int, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for name, pattern in PATTERNS.items():
            if pattern.search(line) and name not in exempt:
                hits.append((name, lineno, line.strip()))
    return hits


def scan_package() -> list[tuple[str, str, int, str]]:
    """扫描整个源码包，返回 ``[(相对路径, 模式名, 行号, 行内容)]``。"""
    violations: list[tuple[str, str, int, str]] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        rel = path.relative_to(PACKAGE_ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        for name, lineno, line in scan_text(rel, text):
            violations.append((rel, name, lineno, line))
    return violations


def test_no_credential_paths_outside_sso() -> None:
    """``sso/`` 之外的模块不得出现凭据路径模式（豁免名单除外）。"""
    violations = scan_package()
    detail = "\n".join(f"  {rel}:{lineno} [{name}] {line}" for rel, name, lineno, line in violations)
    assert not violations, f"凭据路径知识泄漏到 sso/ 之外：\n{detail}"


def test_exemptions_reference_existing_files() -> None:
    """豁免名单不得指向已不存在的文件（防陈旧豁免掩盖回归）。"""
    for rel in EXEMPTIONS:
        assert (PACKAGE_ROOT / rel).is_file(), f"豁免名单引用了不存在的文件：{rel}"


def test_exemptions_are_actually_needed() -> None:
    """豁免若已不再命中任何模式，应删除（保持名单最小）。"""
    for rel, patterns in EXEMPTIONS.items():
        text = (PACKAGE_ROOT / rel).read_text(encoding="utf-8")
        for name in patterns:
            assert name in PATTERNS, f"豁免 {rel} 引用了未知模式：{name}"
            hit = any(PATTERNS[name].search(line) for line in text.splitlines())
            assert hit, f"豁免已失效（{rel} 不再出现 {name}），请从名单移除"


def test_scan_detects_synthetic_leak() -> None:
    """扫描器本身有效：非 sso 模块里出现凭据路径应被判为违规。"""
    leak = 'path = Path.home() / ".westlake_survival" / "credentials.txt"\n'
    assert scan_text("some/module.py", leak), "扫描器未能识别合成泄漏"

    cases = {
        "home_dir": "root = Path.home()\n",
        "session_file": 'p = "session.json"\n',
        "config_dir_literal": 'p = "~/.westlake_survival/x"\n',
        "credentials_filename": 'p = "credentials.txt"\n',
        "open_on_cred_path": 'with open(credential_file, "rb") as fh:\n',
    }
    for expected, snippet in cases.items():
        names = {name for name, _, _ in scan_text("some/module.py", snippet)}
        assert expected in names, f"模式 {expected} 未命中合成样例 {snippet!r}"


def test_sso_files_are_always_allowed() -> None:
    """``sso/`` 目录内的文件整体放行（凭据逻辑的唯一合法归属地）。"""
    leak = 'Path.home() / ".westlake_survival" / "credentials.txt"\n'
    assert scan_text("sso/creds.py", leak) == []


def test_exempted_patterns_are_ignored_for_exempted_file() -> None:
    """豁免的文件-模式组合不再产生违规，但同文件其它模式照常命中。"""
    # canvas/client.py 豁免 config_dir_literal / home_dir，但不豁免 session_file。
    text = 'a = Path.home() / ".westlake_survival"\nb = "session.json"\n'
    names = {name for name, _, _ in scan_text("canvas/client.py", text)}
    assert "config_dir_literal" not in names
    assert "home_dir" not in names
    assert "session_file" in names
