"""核对 SKILL.md 声明的 CLI 命令在实际 CLI 里是否都存在（功能保有检查）。"""
from __future__ import annotations

import re
import subprocess
import sys

root = sys.argv[1] if len(sys.argv) > 1 else "."
py = sys.argv[2] if len(sys.argv) > 2 else sys.executable
skill = f"{root}/skills/westlake-survival/SKILL.md"
text = open(skill, encoding="utf-8").read()

# 取实际 CLI 结构（钉 UTF-8：CLI 帮助含中文，Windows 本地码页 cp1252 解码必炸）
help_top = subprocess.run(
    [py, "-m", "westlake_survival", "--help"],
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
    cwd=root,
).stdout
top_ok = set(re.findall(r"^  ([a-z][a-z0-9\-]*)", help_top, re.M))

cmds: set[tuple[str, str | None]] = set()


def _record(top: str, sub: str | None) -> None:
    if top in ("go", "help"):
        cmds.add((top, None))
        return
    cmds.add((top, sub))


# 1. 显式 `westlake <cmd> [<sub>]`
for m in re.finditer(r"westlake\s+([a-z][a-z0-9\-]*)(?:\s+([a-z][a-z0-9\-]*))?", text):
    _record(m.group(1), m.group(2))

# 2. 行内代码片段 `` `<top> [<sub>] ...` ``（识别表格与正文路由命令）
for span in re.findall(r"`([^`\n]+)`", text):
    cleaned = re.sub(r"<[^>]*>|\[[^\]]*\]", "", span).strip()
    if cleaned.startswith("westlake "):
        cleaned = cleaned[len("westlake ") :].strip()
    m = re.match(r"^([a-z][a-z0-9\-]*)(?=$|\s|/)", cleaned)
    if not m:
        continue
    top = m.group(1)
    if top not in top_ok and not span.strip().startswith("westlake "):
        continue
    rest = cleaned[m.end() :].strip()
    sub_m = re.match(r"^([a-z][a-z0-9\-]*(?:[/|][a-z][a-z0-9\-]*)*)(?=$|\s)", rest)
    if sub_m:
        for sub in re.split(r"[/|]", sub_m.group(1)):
            _record(top, sub)
    else:
        _record(top, None)

missing: list[str] = []
checked = 0
sub_cache: dict[str, tuple[set[str], str]] = {}

for top, sub in sorted(cmds, key=lambda x: (x[0], x[1] or "")):
    checked += 1
    if top not in top_ok:
        missing.append(f"{top}（顶层缺失）")
        continue
    if not sub:
        continue
    if top not in sub_cache:
        h = subprocess.run(
            [py, "-m", "westlake_survival", top, "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=root,
        ).stdout
        subs = set(re.findall(r"^  ([a-z][a-z0-9\-]*)", h, re.M))
        sub_cache[top] = (subs, h)
    subs, h = sub_cache[top]
    if sub not in subs and not re.search(rf"\b{re.escape(sub)}\b", h):
        missing.append(f"{top} {sub}")

print(f"SKILL.md 声明命令: {checked} 条")
print(f"实际存在的顶层命令组: {len(top_ok)}")
if missing:
    print(f"缺失 {len(missing)} 条:")
    for m in missing[:20]:
        print("   -", m)
    sys.exit(1)
print("结论: SKILL.md 声明的命令全部存在（功能完整）")
