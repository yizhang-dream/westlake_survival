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
| Canvas | courses, deadlines & quizzes, files, discussions, announcements, inbox, assignment specifications; submit / reply / send message | personal token or unified password |
| Venue booking | 17 venue categories: real-time availability, slot discovery, active reservations, booking & cancellation | unified password |
| Sports venues | facilities, courts, daily availability, personal bookings (read-only) | unified password |
| Tasks & portal | administrative service catalog, pending to-dos, portal summary cards | unified password |
| Research / careers / curriculum / campus life / lecture notes / search / system inventory | see the [GitHub README](https://github.com/yizhang-dream/westlake_survival#readme) | most require none |

## Three principles

1. **Read-only by default.** Only five write operations exist, all protected behind a structured consequence gate (without `--yes`, a detailed risk descriptor prints and the command exits 1). No course-grabbing or seat-sniping.
2. **Credentials stay local.** Stored securely in your native OS keychain; entered once via the local web UI and never prompted in plaintext terminal sessions.
3. **Independent community tool.** Operates strictly within user-authorized permissions with no official affiliation or endorsement from Westlake University.

!!! info "中文版"
    中文文档：[首页](../zh/index.md) · [安装](../zh/install.md) · [Agent 集成](../zh/agents.md)
