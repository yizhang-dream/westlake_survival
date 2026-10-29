# Venue Reservations & Sports Facilities

## Central Booking Portal (Unified Credentials, Automated OIDC Login)

Supports 17 venue categories, including study rooms, seminar rooms, piano practice rooms, and multi-purpose activity spaces.

```bash
westlake booking types                  # available venue categories
westlake booking list --type library    # individual spaces within a category
westlake booking days <room> --start ... --end ...   # daily schedule availability
westlake booking slots <room> --date 2026-11-01      # open time slots for a specific date
westlake booking mine                   # active user reservations
westlake booking book <room> --date ... --start 10:00 --end 11:00 --dry-run  # simulate booking
westlake booking book ... --yes         # confirm reservation (consequence gate)
westlake booking cancel <id> --reason ... --yes      # cancel reservation
```

Categories for which your account lacks reservation privileges return empty lists without error; verify accessible categories via `westlake booking types`.

## Athletic Facilities & Swimming Pool (Zhengyuan System, Read-Only)

```bash
westlake sport scenes               # sports facilities (gym, badminton courts, pool, etc.)
westlake sport sites <scene>        # specific courts and areas within a facility
westlake sport days <scene> <site>  # daily court availability calendar
westlake sport mine                 # personal court reservations
```

Court booking workflows require campus prepaid-card transactions; active booking endpoints are deliberately excluded to safeguard student funds.

## System Boundaries & Upstream Architecture

Athletic facilities and library study seats are managed on isolated upstream infrastructures outside the central reservation portal. Consult the [module audit](https://github.com/yizhang-dream/westlake_survival/blob/main/docs/module_audit_2026-10-27.md) for detailed service mapping (Chinese). Library loan queries are temporarily unavailable pending the ongoing platform migration ([migration notes](https://github.com/yizhang-dream/westlake_survival/blob/main/docs/library_migration_2026-10-28.md), Chinese).
