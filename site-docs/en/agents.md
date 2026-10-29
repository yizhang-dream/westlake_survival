# AI Agent Integration

Designed from the ground up for autonomous AI agents and developer workflows. Integrate via any of the three patterns below:

## 1. Instruction-driven agents via `AGENTS.md` (ZCode, DSH, Codex, Claude Code, Cursor, etc.)

Clone and run directly. The repository root [AGENTS.md](https://github.com/yizhang-dream/westlake_survival/blob/main/AGENTS.md) specifies behavioral boundaries, entry points, and verification procedures. Agents read this file automatically on session initialization and invoke the `westlake` CLI directly once credentials are configured.

## 2. In-Process Python API (Recommended for code-capable agents)

Direct in-process function calls provide the lowest latency and strongly typed data models:

```python
import westlake_survival
from westlake_survival.sis import get_schedule

for session in get_schedule():
    print(session.weekday, session.start_time, session.title)
```

Runnable examples are provided in [examples/](https://github.com/yizhang-dream/westlake_survival/tree/main/examples). When installed via `pip install westlake-survival`, the library runs without requiring a local repository clone.

## 3. Skill Mechanism

The standalone skill definition is located at [skills/westlake-survival/SKILL.md](https://github.com/yizhang-dream/westlake_survival/blob/main/skills/westlake-survival/SKILL.md). Copy it into your agent's skills directory:

```bash
cp -r westlake_survival/skills/westlake-survival ~/.zcode/skills/   # or ~/.agents/skills/, ~/.claude/skills/
```

The `westlake-mcp` server serves as a compatibility layer for clients restricted to tool-calling interfaces (such as Claude Desktop or chat sidebars). Agents with shell or Python execution access should prefer the CLI or Python API.

## Write Safety & Consequence Gate

Exactly five write operations exist across the entire toolkit: `canvas submit`, `canvas reply`, `canvas send`, `booking book`, and `booking cancel`. All write paths are protected by [consequence.py](https://github.com/yizhang-dream/westlake_survival/blob/main/src/westlake_survival/consequence.py):

- **Mandatory `--yes` flag**: Without `--yes`, execution terminates immediately with exit code 1, outputting a structured risk descriptor (action target, risk category, severity rating, and reversibility).
- **Pre-flight simulation with `--dry-run`**: Supported on `submit` and `book` to preview request payloads and constraints without altering remote state.
- **Non-interactive by design**: Interactive `[y/N]` prompts are intentionally omitted to prevent agent pipelines from hanging on blocked stdin buffers.

## Initialization & Health Check

```bash
westlake doctor --json    # inspects environment, dependencies, and network health
```

Ensure `westlake doctor` passes before executing multi-step tasks. AI agents must never handle raw credentials directly; users configure authentication once via the local web Settings UI.
