# Venue booking & sports

## Booking center (unified password, OIDC auto-login)

17 venue types: study rooms, seminar rooms, piano rooms, event rooms and more.

```bash
westlake booking types                  # categories
westlake booking list --type library    # resources in a category
westlake booking days <room> --start ... --end ...   # day-by-day availability
westlake booking slots <room> --date 2026-11-01      # free slots
westlake booking mine                   # my bookings
westlake booking book <room> --date ... --start 10:00 --end 11:00 --dry-run  # plan
westlake booking book ... --yes         # book (consequence gate)
westlake booking cancel <id> --reason ... --yes      # cancel
```

Categories without permission simply return empty lists — trust `booking types`.

## Sports venues / swimming (separate Zhengyuan system, read-only)

```bash
westlake sport scenes               # scenes
westlake sport sites <scene>        # sites
westlake sport days <scene> <site>  # day-by-day availability
westlake sport mine                 # my bookings
```

Placing orders involves prepaid-card payment and is deliberately not wired.

## Boundaries

Sports venues and library seats live in separate systems outside the booking center; see the [module audit](https://github.com/yizhang-dream/westlake_survival/blob/main/docs/module_audit_2026-10-27.md) for the four-system mapping (Chinese). Library borrowing is unavailable during the platform migration ([notes](https://github.com/yizhang-dream/westlake_survival/blob/main/docs/library_migration_2026-10-28.md), Chinese).
