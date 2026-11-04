English | [简体中文](README.md)

# westlake_survival

> Unified campus services for Westlake University across **a CLI, Python API, and local WebUI**.
>
> Python library · CLI · MCP server · local WebUI — one capability set, four entry points, for humans and AI agents alike.
>
> 📚 Docs: https://yizhang-dream.github.io/westlake_survival/

![Docs](https://img.shields.io/badge/docs-online-8957e5)

![PyPI](https://img.shields.io/pypi/v/westlake-survival)
![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-58839b)
![MCP](https://img.shields.io/badge/MCP-server-8957e5)
![License](https://img.shields.io/badge/license-PolyForm%20Noncommercial%201.0.0-dd4a4a)

Westlake University campus services are split across dozens of isolated portals: SIS, AMS, Canvas, venue reservations, the central campus portal, the library, sports facilities, and more. **westlake_survival** unifies them at the API layer into a single, coherent toolkit:

- **Python library (in-process API)** — `pip install westlake-survival`, then `import westlake_survival` to access the full structured API with typed data structures. This is the fastest, lowest-overhead path for code-capable AI agents (see [examples/](examples/) for runnable samples).
- **CLI** — `westlake` provides complete read coverage and guarded write operations. Not sure where a command lives? Run `westlake find <keyword>` (supports plain-language queries such as `paper`, `borrow`, or `holiday`).
- **Local WebUI** — run `westlake` (or double-click a launch script) to open the browser dashboard with 30+ pages, visual account setup, and a full `/capabilities` directory.
- **MCP server (compatibility layer)** — `westlake-mcp` bridges clients that interact strictly via registered tools (e.g., Claude Desktop, chat sidebars). Agents with shell or Python execution access (such as ZCode or Claude Code) should prefer the in-process API or CLI.

Three core principles:

1. **Read-only by default & Action Card verification.** Write operations are strictly restricted to a safe whitelist (Canvas assignment submission, replies, direct messages, course starring; venue booking & cancellation; library loan renewals; iCalendar export). Each write operation is guarded by `consequence.py`, generating a structured **Action Card** with an ephemeral single-use confirmation ticket (`--ticket`) or explicit per-execution confirmation (`--yes`). No automated course-sniping, no seat-grabbing, and no permission bypasses.
2. **Offline-first architecture (SWR).** Low-frequency datasets such as class schedules, academic calendar weeks, and shuttle timetables support Stale-While-Revalidate caching and `--offline` flags. Lookups return instant local snapshots even in basements, offline environments, or outside campus without VPN.
3. **Credentials stay local.** Stored in your native OS keychain, saved exactly once, never logged to terminals or committed to git, and never synced across machines. Enter your credentials once via the local web settings UI. See [Credentials & Privacy](#credentials--privacy).
4. **Independent community project.** Structurally inspired by [sustech_survival](https://github.com/dumixthestpd/sustech_survival); not officially affiliated with or endorsed by Westlake University.

## Feature Overview

| Domain | Coverage | Account |
| --- | --- | --- |
| Academics (SIS) | class timetable, grades, exam seating, enrollment cart, course evaluations, co-curricular records, status changes, advisor info, ICS calendar export | unified password |
| Teaching (AMS) | secondary timetable, academic calendar week numbering, course registration status | unified password |
| Canvas | courses, deadlines & quizzes, to-dos, modules, file downloads, discussions, announcements, inbox, assignment specifications (attachments & rubrics); submit / reply / send message / star course | personal token or unified password |
| Venue booking | 17 venue categories (study rooms, seminar rooms, piano rooms, etc.): composite availability solver (`booking recommend`), slot discovery, active reservations, booking & cancellation | unified password |
| Sports venues | facilities, courts, daily availability, personal bookings (read-only) | unified password |
| Tasks & portal | administrative service catalog, pending tasks, portal dashboard cards (unread mail, book loans, pending approvals) | unified password |
| Portal data market (skill script) | [Read-only guide](skills/westlake-survival/references/data-market.md) (Chinese): dataset catalog and the current account's profile, education history, completed courses, honors, clubs, and volunteering; no dedicated CLI/MCP entry yet | unified password |
| Research | subscribed database registry, CARSI off-campus SSO (`scholar ensure`), DOI→PDF full text, research news, faculty directory, HPC clusters, reimbursement rules | most require none |
| Careers | job postings, campus fairs, employer info sessions: recent digests and detailed listings | none |
| Curriculum | major requirements & degree roadmaps, course system, general education catalog, cross-department course search | none |
| Campus life | academic calendar, shuttle schedules & ICS export, daily status summaries (`context`/`digest`), dining halls & cafés, residential buildings, campus services (supermarket, deliveries, dry cleaning, barbershop, banking), campus map & panoramas, cloud printing stations | none |
| Lecture notes | shared OneDrive/SharePoint course folders, public index browsing & file downloads (requires optional `[browser]` extra) | none |
| Information | university-wide search, news feeds, academic lectures, announcements, WikiLake student encyclopedia | none |
| System inventory | directory of 90+ internal services, subdomain mapping, endpoint reachability probes, Sangfor VPN status & routing | none |
| Library | Afadi Cloud eLibrary search (`lib search`), active loans & due dates (`lib loans`), online loan renewal (`lib renew`, guarded write) | partly none |

Sports facilities and library seating reside on distinct upstream backends; see [docs/module_audit.md](docs/module_audit.md) (Chinese) for architecture details. Over 20 additional read-only commands expose student records (academic status, dorm assignments, honors, volunteer hours, financial aid, club directory)—all discoverable via `westlake find`.

## Quick Start

**One-Click Launcher**: Double-click `start.bat` (Windows) or `start.command` (macOS) in the repository root, or run `./start.sh` (Linux). On the first run, the script installs dependencies and opens your browser directly to the **Settings** page. Enter your student ID and unified password once; upon successful authentication, the dashboard appears. Subsequent launches skip setup and navigate directly to the dashboard. If a server instance is already running on the port, the launcher simply focuses the active browser window rather than spinning up a duplicate process.

**Terminal Installation** (available on PyPI):

```bash
pip install westlake-survival   # install from PyPI; or clone and run pip install -e . for local dev
westlake                        # start the local web dashboard (set WESTLAKE_NO_WEBUI=1 to suppress auto-opening browser)
westlake calendar today         # public queries run without credentials
westlake --help
```

For complete startup specifications, see [docs/first_run.md](docs/first_run.md) (Chinese). If you encounter environment issues (such as missing dependencies, version incompatibilities, or interpreter mismatches), run `westlake doctor` first. It inspects Python environments, dependencies, credentials, and network connectivity step-by-step, providing ready-to-run resolution commands for any detected issues (see [docs/doctor.md](docs/doctor.md), Chinese).

## AI Agent Integration

This repository is engineered agent-first. You can integrate via three primary methods:

1. **Instruction-driven agents via `AGENTS.md`** (ZCode, DSH, Codex, Claude Code, Cursor, etc.): Clone and start. The root [AGENTS.md](AGENTS.md) outlines operating rules, execution boundaries, and verification procedures. Agents read this file automatically on session initialization and invoke the `westlake` CLI directly once credentials are configured.
2. **Skill-based agents & SkillVM toolchain**: The packaged skill definition is located at [skills/westlake-survival/SKILL.md](skills/westlake-survival/SKILL.md). To install or compile across heterogeneous harnesses and machines, run:
   ```bash
   westlake skill install --target all    # automatically detects ZCode, Claude Code, and Cursor on your machine
   westlake skill compile --target all    # AOT compiles tailored specs (supporting -O0 frontier and -Os compact profiles)
   ```
   Or manually copy `skills/westlake-survival` into your agent framework directory (`~/.zcode/skills/`, `~/.claude/skills/`, etc.).
3. **Model Context Protocol (MCP)**: Register the `westlake-mcp` entry point in your client configuration. See [docs/skill_reference.md](docs/skill_reference.md) (Chinese) for client configuration snippets and the complete MCP tool catalog.

An agent's standard health check should always begin with **`westlake doctor`** (or `westlake doctor --json` for structured output). Agents must never request or write credentials directly; users configure authentication once via the local web Settings UI.

## Credentials & Privacy

- **Unified campus authentication**: SIS, Canvas, AMS, room reservations, athletic facilities, cloud printing, and the campus portal share central institutional credentials. Canvas optionally supports dedicated personal access tokens (configurable and revocable via the web UI).
- **Local-only single store**: Credentials are saved exclusively in your native OS keychain (Windows Credential Manager, macOS Keychain, or Linux Secret Service / Keyring). File-based fallback automatically evicts keychain entries to guarantee a single source of truth ([docs/credential_single_store.md](docs/credential_single_store.md), Chinese). No credentials are synced across machines or user profiles.
- **Web-based credential entry**: Passwords are entered securely via the local web UI. The CLI avoids prompting for plaintext passwords in terminal buffers (`westlake setup --terminal` is available as a headless fallback). Use `WESTLAKE_HOME` or `WESTLAKE_NO_KEYRING=1` for isolated testing.
- **Direct connections by default**: Network requests enforce `trust_env=False`, bypassing ambient `HTTP_PROXY`/`HTTPS_PROXY` settings. Campus internal gateways frequently drop or reject proxied traffic (resulting in 502 Bad Gateway or timeouts). Custom automation scripts should inherit `westlake_survival.discovery.direct_session()`.
- Accessing internal systems (e.g., SIS or AMS) off campus requires an active on-campus network or VPN connection; run `westlake vpn status` to inspect connectivity.

## Verification (End-to-End)

In accordance with project architecture, this repository relies strictly on end-to-end validation rather than synthetic unit tests or mocks:

```bash
python tools/module_smoke.py   # curated tier (anonymous + offline, no account needed) runs every public read-only CLI command
python tools/module_smoke.py --auth   # credential tier (68 commands): personal data, requires campus network + local account
python tools/webui_smoke.py    # starts an in-process web instance and validates HTTP 200 across all routes (no credentials needed)
python tools/pii_scan.py       # pre-commit linting to prevent exposure of real student identifiers or credentials
```

## Documentation

Documentation is primarily maintained in Chinese; refer to [README.md](README.md) for the comprehensive documentation directory or browse the [online documentation site](https://yizhang-dream.github.io/westlake_survival/).

## License & Credits

- License: [PolyForm Noncommercial 1.0.0](LICENSE) — noncommercial use only, with source attribution required.
- Architecture: Structurally referenced from [sustech_survival](https://github.com/dumixthestpd/sustech_survival); student organization descriptions adapted from the community-built encyclopedia [WikiLake](docs/clubwiki.md) with source references preserved. See [CREDITS.md](CREDITS.md).
- Compliance: Community project operating strictly within the authenticated user's permission boundaries. Not affiliated with or endorsed by Westlake University.
