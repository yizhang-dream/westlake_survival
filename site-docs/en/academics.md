# Academics: SIS & AMS

Westlake runs two teaching systems, both covered by the unified password: **SIS** (the registrar, IAM OAuth2) and **AMS** (the teaching system, IAM SSO, session cached 8 hours). Campus network / VPN required.

## SIS schedule & exams

```bash
westlake sis schedule        # class sessions (course/teacher/day/time/room)
westlake sis grid            # weekly grid + conflict check (read-only)
westlake sis ical            # export .ics (one-click copy on the web /ical page)
westlake sis exams           # exam seats and schedule
```

The conflict check treats "same session split into parallel rooms by class" as non-conflicting; once the enrollment window opens, cart sessions can be merged in for pre-checks — **no add/drop/grabbing**.

## Grades & enrollment cart

```bash
westlake sis grades          # transcript with GPA estimate
westlake sis cart            # shopping cart (read-only; "no permission" is normal outside the window)
```

## Evals / second classroom / records

```bash
westlake sis-evals list --pending     # pending course evaluations
westlake records second-class        # second-classroom transcript
westlake records advisor             # academic advisor
westlake records other-apps          # status-change applications
westlake profile info|academic|extended   # personal info in three tiers
```

20+ read-only commands across records/aid — ask `westlake find <keyword>` when unsure.

## AMS teaching system

```bash
westlake ams schedule --start 2026-10-27 --end 2026-11-01
westlake ams status          # enrollment entries
westlake ams menus           # service menu
```

A second schedule alongside SIS (each system has its own slant); read-only.
