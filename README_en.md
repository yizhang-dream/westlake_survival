English | [简体中文](README.md)

# westlake_survival

> Every campus service at Westlake University, gathered into **one command, one call, one page**.
>
> Python library · CLI · MCP server · local WebUI — one capability set, four entry points, for humans and AI agents alike.

![PyPI](https://img.shields.io/pypi/v/westlake-survival)
![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-58839b)
![MCP](https://img.shields.io/badge/MCP-server-8957e5)
![License](https://img.shields.io/badge/license-PolyForm%20Noncommercial%201.0.0-dd4a4a)

Campus services at Westlake University are scattered across dozens of standalone systems — SIS, the AMS teaching system, Canvas, the booking center, the campus portal, the library, sports venues, and more. **westlake_survival** wires them together at the API level into a single toolkit:

- **Python library (in-process API)** — `pip install westlake-survival`, then `import westlake_survival` for the full structured API: the shortest path for agents that can run code; [examples/](examples/) has runnable samples.
- **CLI** — `westlake` covers queries and a handful of writes; not sure which command? Ask `westlake find <keyword>` (plain-language words like "paper", "borrow", "holiday" all match).
- **Local WebUI** — run `westlake` (or double-click a start script) and a browser opens into the dashboard: 30+ pages including account setup; `/capabilities` lists every capability.
- **MCP server (compatibility layer)** — `westlake-mcp` for clients that can only call registered tools (Claude Desktop, chat sidebars); agents with a terminal (ZCode, Claude Code, …) use the three entries above.

Three principles, stated up front:

1. **Read-only by default.** Only five write operations exist — submit an assignment, reply to a discussion, reply to a message, book a venue, cancel a booking — and each requires your explicit instruction for that turn. No course-selection automation, no seat-grabbing, no bypassing permissions.
2. **Credentials stay on your machine.** OS keychain first, stored exactly once, never printed or committed, never synced across machines; you type your account in the web settings page yourself. See [Credentials & Privacy](#credentials--privacy).
3. **No official endorsement.** A community project, structurally inspired by [sustech_survival](https://github.com/dumixthestpd/sustech_survival), unrelated to Westlake University officially.

## Feature Overview

| Domain | Coverage | Account |
| --- | --- | --- |
| Academics (SIS) | schedule, grades, exam seats, enrollment cart, course evals, second-classroom transcript, status changes, advisor, schedule ICS | unified password |
| Teaching (AMS) | a second schedule, teaching week numbers, enrollment entries | unified password |
| Canvas | courses, deadlines & quizzes, to-dos, modules, file downloads, discussions, announcements, inbox, assignment details (attachments + rubrics); submit / reply / message | token or unified password |
| Venue booking | 17 venue types (study rooms / seminar rooms / piano rooms …): categories, day-by-day availability, slot checks, my bookings, book & cancel | unified password |
| Sports venues | scenes, sites, day-by-day availability, my bookings (read-only) | unified password |
| Tasks & portal | service-hall catalog, my to-dos, portal cards (unread mail / loans / to-do counts) | unified password |
| Research | subscribed database registry, CARSI off-campus SSO (`scholar ensure`), DOI→PDF full text, research news, faculty directory, HPC clusters, reimbursement rules | some need none |
| Careers | job posts, job fairs, info sessions: latest + deep lists + detail | none |
| Curriculum | per-major credit requirements & course tables, course system, general-education catalog, course search | none |
| Campus life | academic calendar, shuttle timetable & ICS, daily digest (`context`/`digest`), dining & cafés, housing, campus map & 360° panoramas, print stations | none |
| Lecture notes | OneDrive/SharePoint shared files, account-free reading & download (needs the optional `[browser]` extra) | none |
| Information | full-site search, news, lectures & events, school updates, the student-built wiki WikiLake | none |
| System inventory | 90+ service registry, subdomain census, site sections, reachability, VPN status & routes | none |
| Library | migrated to the "Afadi Cloud eLibrary" platform on 2026-10-28; borrowing queries unavailable for now ([migration notes](docs/library_migration_2026-10-28.md), Chinese) | — |

Sports venues and library seats live in separate systems; see [docs/module_audit_2026-10-27.md](docs/module_audit_2026-10-27.md) (Chinese) for the mapping. Another 20+ read-only commands cover personal records (status / housing / honors / volunteering / aid / clubs) — `westlake find` knows them all.

## Quick Start

**Easiest**: double-click `start.bat` (Windows) or `start.command` (macOS) in the repo root, or run `./start.sh` (Linux). The first run installs dependencies, then a browser opens — straight to the **Settings** page if no account is configured; you fill in your student ID and unified password once, and after verification the dashboard loads. Later starts go straight to the dashboard. If the server is already running on the port, no second instance starts — the browser is just pointed at it.

**Terminal** (published on PyPI — no clone needed):

```bash
pip install westlake-survival   # from PyPI; for development, clone the repo and pip install -e .
westlake                      # start the web app and open a browser; WESTLAKE_NO_WEBUI=1 disables popups
westlake calendar today       # calendar and other public features need no account
westlake --help
```

Full startup and first-run contract: [docs/first_run.md](docs/first_run.md) (Chinese). If the environment misbehaves (installed but unusable, missing deps, mismatched interpreters), run `westlake doctor` first — it checks interpreter / dependencies / account / network item by item and prints a copy-paste fix for each gap ([docs/doctor.md](docs/doctor.md), Chinese).

## Using It With AI Agents (any agent)

The repo is designed for agents. Three integration paths, freely combined:

1. **Agents that read `AGENTS.md`** (ZCode, DSH, Codex, Claude Code, Cursor, …): clone and go — the root [AGENTS.md](AGENTS.md) states the ground rules, entry points and verification flow, and is picked up automatically at session start; once the account is configured, drive the `westlake` CLI directly.
2. **Agents with a skill mechanism**: the skill document lives at [skills/westlake-survival/SKILL.md](skills/westlake-survival/SKILL.md); copy the folder into your agent's skills root:
   ```bash
   git clone https://github.com/yizhang-dream/westlake_survival.git
   cp -r westlake_survival/skills/westlake-survival ~/.zcode/skills/    # ZCode; use ~/.agents/skills/, ~/.claude/skills/, etc. for others
   ```
3. **MCP clients**: register the `westlake-mcp` process after installing; config snippet and the full MCP tool list are in [docs/skill_reference.md](docs/skill_reference.md) (Chinese).

An agent's first step is always **`westlake doctor`** (`--json` for machine-readable output). Agents never fill in credentials — the user does that once in the web settings page.

## Credentials & Privacy

- **One unified password everywhere**: SIS, Canvas, AMS, booking, sports, printing, and the portal all use Westlake's central authentication; Canvas also accepts a personal token (settable and clearable in the web UI).
- **Stored once, on this machine only**: the OS keychain (Windows Credential Manager / macOS Keychain / Linux Secret Service) is preferred; writing a file automatically clears the keychain and vice versa ([docs/credential_single_store.md](docs/credential_single_store.md), Chinese). No cross-machine or cross-user syncing.
- **Passwords are typed in the web form only**: the terminal never asks for your password by default (`westlake setup --terminal` is the no-GUI fallback); set `WESTLAKE_HOME` or `WESTLAKE_NO_KEYRING` for sandboxed testing.
- **Direct connections by default**: every session sets `trust_env=False`, ignoring `HTTP_PROXY/HTTPS_PROXY` — campus sites often break (502/timeout) behind system proxies; external scripts should reuse `westlake_survival.discovery.direct_session()`.
- Off-campus access to SIS/Canvas needs the campus network or VPN: `westlake vpn status`.

## Verification (end-to-end)

This repo maintains no unit tests; verification is always end-to-end:

```bash
python tools/module_smoke.py   # runs every read-only CLI command for real
python tools/webui_smoke.py    # starts a real Flask server in-process, asserts 200 per page
python tools/pii_scan.py       # pre-commit scan for real student IDs
```

## Documentation

Chinese unless noted; see [README](README.md) for the doc index.

## License & Credits

- License: [PolyForm Noncommercial 1.0.0](LICENSE) — noncommercial use only, attribution preserved.
- Credits: structural reference [sustech_survival](https://github.com/dumixthestpd/sustech_survival); club blurbs adapted from the student-built wiki [WikiLake](docs/clubwiki.md) with per-item source links. See [CREDITS.md](CREDITS.md).
- A community project with no official Westlake University endorsement; accesses only data you are authorized to see.
