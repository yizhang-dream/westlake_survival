#!/usr/bin/env python3
"""PII 泄露扫描：在 skill 仓库里找学号/密码/姓名/宿舍/电话/邮箱/证件/令牌。

只输出「文件:行号:类别:脱敏形状」，绝不打印原值。
用法: python3 pii_scan.py <repo_root>
"""
from __future__ import annotations

import os
import re
import sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".mypy_cache"}
TEXT_EXT = {".py", ".md", ".txt", ".json", ".html", ".toml", ".yaml", ".yml", ".js",
            ".css", ".cfg", ".ini", ".example", ".sh", ".csp", ""}

# 类别 -> (正则, 脱敏函数)
PATTERNS = [
    ("学号(9位数字)", re.compile(r"\b(20\d{7})\b")),
    ("手机号", re.compile(r"\b(1[3-9]\d{9})\b")),
    ("邮箱", re.compile(r"\b([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})\b")),
    ("宿舍号", re.compile(r"\b([A-H]\d{1,2}-\d{1,2}-\d{1,3}(?:-[A-Z])?)\b")),
    ("身份证", re.compile(r"\b(\d{17}[\dXx])\b")),
    ("银行卡", re.compile(r"\b(\d{16,19})\b")),
    ("密码赋值", re.compile(r"(?i)(password|passwd|pwd|密码)\s*[:=]\s*[\"']([^\"'\s]{4,40})[\"']")),
    ("令牌赋值", re.compile(r"(?i)(api[_-]?key|access[_-]?token|canvas_token|secret)\s*[:=]\s*[\"']([^\"'\s]{8,80})[\"']")),
]
# 允许清单：占位/示例/公开数据
ALLOW = re.compile(
    r"(2025XXXXXXX|XXXX|example|placeholder|YOUR_|your-|demo|test@|@example|<|>|\{|\}|"
    r"noreply|schemas|w3\.org|localhost|127\.0\.0\.1|0\.0\.0\.0|@westlake\.edu\.cn/|"
    r"user@|admin@|wangcai|cloudmails|^0+$)", re.I)


def mask(value: str) -> str:
    """脱敏：保留长度与前2后1字符。"""
    if len(value) <= 4:
        return "*" * len(value)
    return value[:2] + "*" * (len(value) - 3) + value[-1]


def main() -> None:
    hits: dict[str, list[str]] = {}
    files = 0
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            ext = os.path.splitext(name)[1].lower()
            if ext not in TEXT_EXT:
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, ROOT)
            try:
                text = open(path, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            files += 1
            for label, pat in PATTERNS:
                for m in pat.finditer(text):
                    raw = m.group(m.lastindex or 1) or m.group(0)
                    if ALLOW.search(raw) or ALLOW.search(m.group(0)):
                        continue
                    # 域名/邮箱白名单：公开学校域名不算泄露
                    if label == "邮箱" and raw.lower().endswith(
                            ("@westlake.edu.cn", "@qq.com", "@gmail.com")) and "noreply" in raw.lower():
                        continue
                    line = text[: m.start()].count("\n") + 1
                    hits.setdefault(label, []).append(f"{rel}:{line}:{mask(raw)}")
    print(f"扫描文件数: {files}")
    if not hits:
        print("结论: 未发现任何 PII 模式命中")
        return
    for label, rows in sorted(hits.items()):
        print(f"\n[{label}] {len(rows)} 处")
        for r in rows[:12]:
            print("  ", r)
        if len(rows) > 12:
            print(f"   …另有 {len(rows) - 12} 处")


if __name__ == "__main__":
    main()
