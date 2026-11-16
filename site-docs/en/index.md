# westlake_survival

Unified campus services for Westlake University across **a CLI, Python API, and local WebUI**.

Python library · CLI · MCP server · local WebUI — one shared core, four entry points, designed for both humans and AI agents.

```bash
pip install westlake-survival   # install from PyPI
westlake                        # launch the local web dashboard
```

## Feature overview

| Domain | Coverage | Account |
| --- | --- | --- |
| Academics (SIS) | timetable, grades, exam seating, enrollment cart, course evaluations, co-curricular records, weekly grid with conflict detection, ICS export | unified password |
| Teaching (AMS) | secondary timetable, academic week numbers, enrollment status | unified password |
| Canvas | active & past courses, deadlines & quizzes, to-dos, modules, file downloads, discussions, announcements, inbox, assignment specs; submit / reply / message / star / upload / dismiss to-do | personal token or unified password |
| Venue booking | 17 venue categories: composite slot recommender (`booking recommend`), availability, active reservations, booking & cancellation | unified password |
| Sports venues | facilities, courts, daily availability, personal bookings (read-only) | unified password |
| Library & cloud print | Afadi Cloud eLibrary search, active loans & online renewal; UniFound printing stations, queues, upload & cancel | partly none |
| Tasks, portal & data market | administrative service catalog, pending to-dos, portal summary cards, `westlake market` sanitized summaries (catalog, profile, resume, courses, honors, clubs, volunteering) | unified password |
| Research / timeline / careers / curriculum / campus life / lecture notes / systems | includes `timeline` cross-system daily scheduler & conflict detection; see the [GitHub README](https://github.com/yizhang-dream/westlake_survival#readme) | most require none |

## Three principles

1. **Read-only by default & Action Card verification.** All 14 guarded write operations pass through `consequence.py`, generating a structured **Action Card** with a single-use confirmation ticket (`--dry-run` to preview, `--ticket <ticket>` or `--yes` to execute). No course-grabbing or seat-sniping.
2. **Credentials stay local.** Stored securely in your native OS keychain; entered once via the local web UI and never prompted in plaintext terminal sessions.
3. **Independent community tool.** Operates strictly within user-authorized permissions with no official affiliation or endorsement from Westlake University.

!!! info "中文版"
    中文文档：[首页](../zh/index.md) · [安装](../zh/install.md) · [Agent 集成](../zh/agents.md)
