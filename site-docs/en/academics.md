# Academics: SIS & AMS

Westlake University operates two primary academic management backends, both accessible via unified campus credentials: **SIS** (Student Information System / registrar, using IAM OAuth2) and **AMS** (Academic Management System, using IAM SSO with an 8-hour session cache). Both systems require an on-campus network or active VPN connection.

## SIS Timetable & Examinations

```bash
westlake sis schedule        # class sessions (course, instructor, day, time, classroom)
westlake sis grid            # weekly timetable grid with conflict detection (read-only)
westlake sis ical            # export timetable to .ics (one-click subscription on the web /ical page)
westlake sis exams           # exam schedule and seat assignments
```

The conflict detection engine accounts for course-specific edge cases: multi-room allocations or parallel classrooms for a single course section are recognized as non-conflicting. When the course registration window is open, cart items can be staged into the grid for pre-enrollment validation. **Automated course adding, dropping, or seat-grabbing is strictly unsupported.**

## Grades & Enrollment Cart

```bash
westlake sis grades          # academic transcript and cumulative GPA summary
westlake sis cart            # enrollment shopping cart (read-only; "permission denied" is expected outside active windows)
```

## Course Evaluations, Co-Curricular & Student Records

```bash
westlake sis-evals list --pending         # pending course teaching evaluations
westlake records second-class            # second-classroom (co-curricular) transcript
westlake records advisor                 # assigned academic advisor details
westlake records other-apps              # status change and administrative petitions
westlake profile info|academic|extended  # student profile partitioned into three detail tiers
```

Over 20 additional read-only commands cover administrative records, scholarships, and financial aid. Run `westlake find <keyword>` to discover specific queries.

## AMS Teaching System

```bash
westlake ams schedule --start 2026-10-27 --end 2026-11-01
westlake ams status          # course enrollment records
westlake ams menus           # accessible service modules
```

AMS provides an alternate class schedule view and faculty portal perspective; all endpoints are strictly read-only.
