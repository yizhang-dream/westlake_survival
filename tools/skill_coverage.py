"""核对 SKILL.md 声明的 CLI 命令在实际 CLI 里是否都存在（功能保有检查）。"""
import re
import subprocess
import sys

root = sys.argv[1] if len(sys.argv) > 1 else "."
py = sys.argv[2] if len(sys.argv) > 2 else sys.executable
skill = f"{root}/.zcode/skills/westlake-survival/SKILL.md"
text = open(skill, encoding="utf-8").read()

# 提取 `westlake <cmd> ...` 形式（去重、只取前两级）
cmds = set()
for m in re.finditer(r"westlake\s+([a-z][a-z0-9\-]*)(?:\s+([a-z][a-z0-9\-]*))?", text):
    top, sub = m.group(1), m.group(2)
    if top in ("go", "help"):
        cmds.add((top, None))
        continue
    cmds.add((top, sub))

# 取实际 CLI 结构
help_top = subprocess.run([py, "-m", "westlake_survival", "--help"],
                          capture_output=True, text=True, cwd=root).stdout
top_ok = set(re.findall(r"^  ([a-z][a-z0-9\-]*)", help_top, re.M))

missing = []
checked = 0
for top, sub in sorted(cmds, key=lambda x: (x[0], x[1] or '')):
    checked += 1
    if top not in top_ok:
        missing.append(f"{top}（顶层缺失）")
        continue
    if not sub:
        continue
    h = subprocess.run([py, "-m", "westlake_survival", top, "--help"],
                       capture_output=True, text=True, cwd=root).stdout
    subs = set(re.findall(r"^  ([a-z][a-z0-9\-]*)", h, re.M))
    if sub not in subs and not re.search(rf"\b{sub}\b", h):
        missing.append(f"{top} {sub}")

print(f"SKILL.md 声明命令: {checked} 条")
print(f"实际存在的顶层命令组: {len(top_ok)}")
if missing:
    print(f"缺失 {len(missing)} 条:")
    for m in missing[:20]:
        print("   -", m)
else:
    print("结论: SKILL.md 声明的命令全部存在（功能完整）")
