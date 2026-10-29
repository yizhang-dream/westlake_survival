# Agent integration

Built for AI agents. Three paths, freely combined:

## 1. Agents that read `AGENTS.md` (ZCode, DSH, Codex, Claude Code, Cursor, …)

Clone and go — the root [AGENTS.md](https://github.com/yizhang-dream/westlake_survival/blob/main/AGENTS.md) states the ground rules, entry points, and verification flow; drive the `westlake` CLI once the account is configured.

## 2. Python library (in-process API — shortest path for code-capable agents)

```python
import westlake_survival
from westlake_survival.sis import get_schedule
for s in get_schedule():
    print(s.weekday, s.start_time, s.title)
```

Runnable samples in [examples/](https://github.com/yizhang-dream/westlake_survival/tree/main/examples); no repo needed after `pip install westlake-survival`.

## 3. Skill mechanism

The skill document lives at [skills/westlake-survival/SKILL.md](https://github.com/yizhang-dream/westlake_survival/blob/main/skills/westlake-survival/SKILL.md); copy it into your agent's skills root:

```bash
cp -r westlake_survival/skills/westlake-survival ~/.zcode/skills/   # or ~/.agents/skills/, ~/.claude/skills/
```

The `westlake-mcp` server remains as a compatibility layer for tool-only clients (Claude Desktop, chat sidebars); agents with a terminal use the paths above.

## Write safety (consequence gate)

Exactly five write operations exist: `canvas submit / reply / send`, `booking book / cancel`, all behind [consequence.py](https://github.com/yizhang-dream/westlake_survival/blob/main/src/westlake_survival/consequence.py):

- Without `--yes`: a structured risk descriptor (what changes / risk / severity / reversibility) prints and the command exits 1.
- `--dry-run` (submit / book): plan-only, nothing is changed.
- Deliberately no interactive y/n prompt — it hangs under piped agent stdin.

## First step for any agent

```bash
westlake doctor --json    # all green before doing anything
```

Agents never fill credentials; the user does that once in the web Settings page.
