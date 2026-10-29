# westlake_survival

Every campus service at Westlake University, gathered into **one command, one call, one page**.

Python library · CLI · MCP server · local WebUI — one capability set, four entry points, for humans and AI agents alike.

```bash
pip install westlake-survival   # from PyPI
westlake                        # start the local web dashboard
```

## Feature overview

| Domain | Coverage | Account |
| --- | --- | --- |
| Academics (SIS) | schedule, grades, exams, enrollment cart, evals, second classroom, weekly grid with conflict check, ICS | unified password |
| Teaching (AMS) | a second schedule, teaching weeks, enrollment entries | unified password |
| Canvas | courses, deadlines & quizzes, files, discussions, announcements, inbox, assignment details; submit / reply / message | token or unified password |
| Venue booking | 17 venue types: availability, slot checks, my bookings, book & cancel | unified password |
| Sports venues | scenes, sites, availability, my bookings (read-only) | unified password |
| Tasks & portal | service-hall catalog, to-dos, portal cards | unified password |
| Research / careers / curriculum / campus life / lecture notes / search / system inventory | see the [GitHub README](https://github.com/yizhang-dream/westlake_survival#readme) | most need none |

## Three principles

1. **Read-only by default.** Only five write operations exist, all behind a structured confirmation gate (without `--yes`, a risk description prints and the command exits 1). No course-grabbing.
2. **Credentials stay on your machine.** OS keychain first, stored once, never asked in the terminal.
3. **No official endorsement.** A community tool; accesses only data you are authorized to see.

!!! info "中文版"
    中文文档：[首页](../zh/index.md) · [安装](../zh/install.md) · [Agent 集成](../zh/agents.md)
