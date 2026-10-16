# Decisions log

Dated, frozen choices and every change to them (`PROJECT_PLAN.md`: "Decision" items). Append new entries at the bottom; never edit or delete an old one. To change a decision, add a dated entry that names the one it supersedes and gives the reason. This is our evidence that the outcome and metric were fixed before models were compared [Brief §4 p.3].

Format: `date  topic: decision (reason; author)`

## Entries

```
2026-10-13  Outcome: U(l,t+15); unusual = deficit >= 2 bands for 2 consecutive snapshots   (lead)
2026-10-13  Norm: median band by link x daytype (Mon-Thu, Fri) x 15-min slot, training weeks only, frozen   (lead)
2026-10-13  Split: train 13 Oct-6 Nov; validate 7-13 Nov; test 14-20 Nov (locked)   (lead)
2026-10-13  Primary metric: PR-AUC on onset rows, test week; 95% day-block bootstrap   (lead)
2026-10-14  Population: RoadCategory 1 (expressways, 2,598 links on 13 Oct), presence >= 95%; weekdays excl. PH; 06:00-22:00   (lead)
2026-10-14  Time t = LTA lastUpdatedTime (fallback: retrieval time)   (lead)
2026-10-14  Collection: lta_collector.py (Python) on the desktop; no cloud sync for now, weekly backup from 21 Oct   (lead)
2026-10-16  Collection fix: each LTA speed-band update is fetched once; no refetch of mixed-time snapshots; no retry on rate-limit faults, pause to the next hour (LTA cuts a key off after ~4,000 calls in a clock hour; commits deda600, 60c74a2)   (team)
2026-10-16  Time t, confirmed: each row's own last_updated, not the snapshot time (LTA serves pages from out-of-sync servers; per-row label reliable: 9.7 M repeats, 0 conflicts; docs/COLLECTION_REVIEW_2026-10-16.md §2)   (team)
2026-10-16  Collection (supersedes 2026-10-14): option C on one machine. Linux mini PC runs lta-collector (whole network at each update, key 1, data_raw/) and lta-collector-expressway (58 expressway pages every 2 min, key 2 from a different LTA account, data_raw_expressway/). Desktop is a cold spare; its 14-16 Oct data to be merged as data_raw_desktop/. Accepted risk: no backup machine while the desktop is off (one-update fetching misses ~20% of expressway links per update; the expressway collector closes that gap; commit 0a35c4c)   (team)
```

Pending (`TODO.md` §3): the 15 Oct methods changes (1 km segments, travel-time label, one weekday norm, test 10-20 Nov, leave one expressway out, drop road works). If accepted, add them here with the date and mark which entries above they supersede.
