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
2026-10-16  Time t, confirmed: each row's own last_updated, not the snapshot time (LTA serves pages from out-of-sync servers; per-row label reliable: 9.7 M repeats, 0 conflicts; see Background below)   (team)
2026-10-16  Collection (supersedes 2026-10-14): option C on one machine. Linux mini PC runs lta-collector (whole network at each update, key 1, data_raw/) and lta-collector-expressway (58 expressway pages every 2 min, key 2 from a different LTA account, data_raw_expressway/). Desktop is a cold spare; its 14-16 Oct data to be merged as data_raw_desktop/. Accepted risk: no backup machine while the desktop is off (one-update fetching misses ~20% of expressway links per update; the expressway collector closes that gap; commit 0a35c4c)   (team)
2026-10-16  Flood Alerts (PUB, API guide 2.30) collected by lta-collector-expressway (key 2) every 3 min, saved on change, into data_raw_expressway/feeds/flood_alerts/. Use: label audit and masking (e.g. flag or exclude rows near an active flash flood) and explaining failure cases; NOT a model feature (too few events). Past alerts can't be downloaded later. About 20 calls/hour on key 2 (key 1 is near the ~4,000/hour limit)   (team)
2026-10-16  Flood Alerts interval (supersedes 3 min in the entry above, before it went live): every 5 min, to match the 5-min speed-band grid; alerts usually stay up about an hour and carry their own issue time, so only the clear time is less precise (±5 min). About 12 calls/hour on key 2   (team)
2026-11-11  Population presence (supersedes ">= 95%" in 2026-10-14): presence >= 90% of the updates captured 19-23 Oct, 06:00-22:00 (first full weekday week; 16 Oct is a part day). Every expressway link is at 94-97% (std 0.5 points) because whole pages lag, not because links disappear, so 95% dropped 1,698 links at random (MCE to 1 link). [L] = 2,598 links. Decided before any model was fitted (analysis/build_model_data.py)   (Juan Peng)
2026-11-11  Label with missing snapshots: U(l,t) is known only when the link was captured at both t and t-5 (else null); y = U(t+15) the same way; null-label rows are dropped. A rule that settles U = 0 from one known snapshot can never settle U = 1 that way, so it dropped ~25% of onset positives (14,431 null vs 43,529 positives in train) and almost no negatives. Gaps are page lag, unrelated to traffic. Decided before any model was fitted   (Juan Peng)
2026-11-11  Roads joining the expressways as extra inputs: every link whose end is within 5 m of an expressway link's start (into it) or whose start is within 5 m of its end (out of it), any road category (mostly slip roads and major arterials). Their deficit against their own frozen training-day norm, at the same lags, as f_conn_* inputs (0 + flag when absent). Rows and label unchanged. Models are compared with and without f_conn_* on the same rows (sensitivity check). Data version 2. Decided before any model was fitted   (Juan Peng)
```

## Background: speed-band collection findings (16 Oct 2026)

Summary of the 16 Oct collection review (desktop data 14 Oct 22:00 to 16 Oct 12:05: 225 snapshots, 32.4 M rows), behind the 16 Oct entries above.

- **Rate limit.** LTA's terms publish 10 M calls/day, but each key is cut off after about 4,000 calls in a clock hour (HTTP 500 "Rate limit quota violation", which names the key) and works again on the hour. The old collector refetched every mixed-time snapshot and never recorded the update as done, so it used about 577 calls per probe and ran out by about minute 8 of every hour: about 6 instead of 12 snapshots an hour.
- **Out-of-sync pages.** LTA serves the 288 pages from several servers that are not in sync. One fetch carries two or three update times scattered across the pages, and a page can step back to the previous update. Refetching never gives a clean snapshot.
- **Per-row time is reliable.** When a link was seen several times with the same `last_updated`, its band was identical every time (9.7 M repeats, 0 conflicts). Data age at download: median 5 min, 95th percentile 9 min.
- **Coverage before the fix.** Fine hourly (37 of 39 hours with at least 95% of links), not at 5 minutes (121 of 458 update times seen; median 81% of links per update). A link's band changes between consecutive updates 23% of the time, so gaps can't be filled from the previous update.
- **Expressway pages.** The 2,598 expressway links sit on 58 of the 288 pages (mostly pages 60–69), on the same pages on 14 and 16 Oct. Fetching only those pages is cheap enough to do every 2 minutes.
- **Options considered.** A: one collector, one fetch per update (~80–95% of expressway links per update). B: one key, expressway pages every minute plus the whole network every 15 min. C (chosen): two keys, whole network per update plus expressway pages often.

### 2026-10-24: Raw-data backup to Google Drive (lead)

- The school OneDrive needs Zscaler on the Linux PC, and Zscaler could cut the collectors' connection, so the backup goes to a Google Drive folder (`SLDS_1.3_raw`) shared with the team as Viewer. This replaces the weekly copy planned in PROJECT_PLAN §6 (item 4, Backups).
- `upload_raw.sh` runs nightly from cron at 02:30 SGT (cron because it needs no sudo; after midnight log rotation, quiet hours). One `.tar` per collector per finished day, because Drive is slow with ~2,000 small files a day and a teammate needs only one file per day. Checksums (SHA-256 in `SHA256SUMS.txt`; rclone compares MD5 with Drive).
- Append only: `rclone copy --immutable` and `rclone check` only; no `sync`, `delete` or `move`. A packed day is never rebuilt; files that change later are reported as `WARN` in the log. Local tars are kept (about 6 GB by 20 Nov, 830 GB free).
- Drive layout, one folder per source: `lta_network/`, `lta_expressway/`, `lta_fetch_logs/`, `lta_source_check/`, `nea_rainfall/`, `calendar/`, with `README.txt`, `MANIFEST.csv` and `SHA256SUMS.txt` (every file) at the top. `archive_raw/` is an exact local copy, so one `rclone check` covers everything.
- rclone uses its built-in shared Google client_id. rclone will retire it "during 2026" with 90 days' notice, which had not started by 19 Sep 2026 (rclone forum), so it should outlast collection (20 Nov). Publishing our own OAuth app needs a home page and privacy policy, so not worth it. If uploads fail with an auth error (Healthchecks "SLDS upload" alerts), create our own client in Testing mode and reconnect weekly; no data is lost meanwhile, the next run uploads every missing day.
- The desktop's data (`data_raw_desktop/`, 14-16 Oct) is not uploaded or used: it is mostly 14 Oct, and 16 Oct is already on the Linux PC, so adding it would mix two sources for little gain.
- The same job runs `get_context_data.py`, so NEA rainfall for each day is downloaded the night after (backfilled 17-23 Oct on 24 Oct; key `DATA_GOV_KEY`). If data.gov.sg fails it retries 4 times, 20 min apart, and any day still missing is fetched the next night. It does not affect the LTA collectors: different API and key, and it writes only `data_raw/nea_rainfall/`, `data_raw/calendar/` and `data_processed/`, which the collectors never touch (checked 24 Oct: fetch counts unchanged during the backfill).

Pending team decision: the 15 Oct methods changes (1 km segments, travel-time label, one weekday norm, test 10-20 Nov, leave one expressway out, drop road works). If accepted, add them here with the date and mark which entries above they supersede.
