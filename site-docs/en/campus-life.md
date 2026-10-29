# Campus Life & Services

Most utilities in this section operate completely **without credentials**, except where authenticated personal records are indicated.

## Academic Calendar, Shuttle Transit & Daily Context

```bash
westlake calendar today        # current date, teaching week number, and academic events
westlake calendar week 10      # week 10 schedule overview
westlake calendar events       # institutional academic calendar milestones
westlake transit next          # next scheduled campus shuttle departures
westlake transit table         # complete cross-campus shuttle timetable
westlake transit ical          # shuttle schedule exported to .ics format
westlake context               # comprehensive real-time snapshot: week, shuttle, weather, AQI, upcoming deadlines
westlake digest                # morning briefing summary
```

`westlake context` queries real-time weather and air quality index (AQI) conditions by default (powered by Open-Meteo, zero API keys required).

## Dining, Residential Life, Navigation & Directory

```bash
westlake campus dining         # dining halls, cafeterias, and campus coffee shops
westlake campus housing        # student and residential apartment details
westlake map [--campus yungu]  # campus geographic map, 360° panoramas, and transit directions
westlake contact phones        # essential campus emergency and administrative contacts
```

## Cloud Printing, Campus Portal & Task Center (Unified Credentials)

```bash
westlake pms stations          # campus print station locations (no login required)
westlake pms jobs              # active print queue and job history
westlake portal cards          # portal dashboard summary cards (unread email, book loans, pending approvals)
westlake todo list|doing|done  # administrative to-do task tracker
westlake affairs apps booking  # administrative service directory (guide to campus workflows)
```
