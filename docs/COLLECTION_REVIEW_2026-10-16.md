# Speed-band collection review, 16 Oct 2026

For: whoever runs a collector (desktop and Ubuntu mini PC). Decision needed before collection restarts on the desktop.

**Status (16 Oct, ~12:45 SGT):** the desktop collector is **stopped** while we decide how to collect. Its watchdog task `SLDS_LTA_collector_247` still needs disabling in an admin terminal (`Disable-ScheduledTask -TaskName SLDS_LTA_collector_247`). LTA serves only the current state, so if the mini PC isn't running, every minute stopped is lost for good.

Data checked: 225 desktop snapshots, 32.4 M rows, 143,787 links, 14 Oct 22:00 to 16 Oct 12:05.

**Decision (16 Oct, ~13:20 SGT): option C, both collectors on the Ubuntu mini PC.** Accepted trade-off: no backup machine. The desktop stays off and is a cold spare.

| Service | Key | What it collects | Output |
|---|---|---|---|
| `lta-collector` | `LTA_ACCOUNT_KEY` | Whole network at every update (`60c74a2` logic), plus incidents, VMS, travel times, road works | `data_raw/` |
| `lta-collector-expressway` | `LTA_ACCOUNT_KEY2` (different LTA account) | `--mode expressway`: the 58 expressway pages every 2 min; saves only pages whose time changed; full fetch to rebuild the page map at start, every 6 h, and whenever an expressway LinkID is missing from the mapped pages | `data_raw_expressway/` |

- **Interval.** 2 minutes rather than 1 keeps the second key at about 1,800 calls an hour, well under the ~4,000 limit, because each page shows each update for about 5 minutes. Tighten it with `--every 60` only if coverage turns out short.
- **Processing.** `04_process.ipynb` now reads every `data_raw*/speedbands` folder and de-duplicates on `(LinkID, t)`. Copy the desktop's data in as `data_raw_desktop/` to merge it the same way.
- **Answers to section 5 from the mini PC:**
  1. Collecting since 12:07 on 16 Oct, but rate-limited from 12:17 to 13:00, so it does not cover the desktop gap.
  2. Option C was chosen.
  3. Yes, the same pattern: about 4,000 calls in 10 minutes on the old code, blocked at 12:17, reset at 13:00.
  4. The live-hour check of `60c74a2` starts at 13:06.

---

## 1. Rate limit: what happened and what is already fixed

Both keys hit `Rate limit quota violation` (HTTP 500) every hour. On the desktop since 14 Oct, each hour looked like this:

| Minute | What happened |
|---|---|
| :00–:08 | about 6 full fetches, all `ok_flagged`, several with the same `last_updated` |
| :08 | `fetch_failed`: the hourly quota ran out mid-fetch |
| :10–:59 | about 35 `probe_failed`, all rate-limited |
| next :00 | works again (the quota resets on the hour, per key) |

Result: about 6 instead of 12 snapshots an hour, and about 450 failures a day.

**Cause.** Almost every fetch carries mixed `lastUpdatedTime` values (see section 2). `check_snapshot()` flagged them, and then:

1. the refetch-once loop downloaded all 288 pages a second time;
2. `sb_last_updated` was saved only when there was no problem, so it was never saved. The next 60-second probe saw "new data" and started again.

So each probe cost about 577 calls, instead of 288 per 5-minute update. The quota (about 4,000 calls an hour, judging by our logs) ran out by about minute 8. Rate-limit errors were also retried 4 times each.

**Fixed in two commits:**

- `deda600`:
  - each LTA update is fetched once, and mixed snapshots are saved as `ok_flagged`;
  - the refetch-once loop is removed;
  - rate-limit faults are not retried;
  - after a rate-limit fault, probes pause until just after the next hour.
- `60c74a2`: a fetch starts only when page 1's time moves forward (`is_newer()`), because pages can step back in time (section 2).

Tested offline with a fake LTA server:

| Case | Calls |
|---|---|
| New update | 289 |
| Unchanged probe | 1 |
| Step back, or return to an update already fetched | 1, no fetch |
| Rate-limited probe | 1, then a pause until the hour |

Expected use is about 3,500 calls an hour. It ran live only for a few minutes, inside a rate-limited hour, so it has **not yet been confirmed on a full live hour**.

**Mini PC:** `git pull` and restart the service, or it is still running the old code.

**Key in old logs:** logs written before `71b12b2` (`data_raw/logs/`, `log_speedbands.csv`, `collector_status.json`) contain the key in plain text inside the rate-limit messages. Don't share those files as they are.

---

## 2. What the data shows about LTA's speed-band feed

**Pages come from several servers that are not in sync.** Pages are not updated in order. One fetch can carry three update times scattered across the pages. For example, the snapshot taken at 12:05:17 has 11:55, 12:00 and 12:05 on different pages. A page can also step back: page 13 read 12:00 at 12:01 and 12:02, then 11:55 at 12:04. Fetching again therefore never gives a clean snapshot.

**The per-row label is reliable.** When a link was seen in several snapshots with the same `last_updated`, its SpeedBand was identical every time: 9.7 M repeats, 0 conflicts. A row from a lagging server is genuine data for its stated update time. `04_process.ipynb` already does the right thing: `t` = each row's own `last_updated`, then de-duplicated on `(LinkID, t)`.

**Data age at download:** median 5 min, 95th percentile 9 min, maximum 15 min.

**Coverage so far, desktop only, pre-fix:**

| Resolution | Coverage |
|---|---|
| 5 min | 121 of 458 update times seen; median 81% of links per update seen |
| 15 min | 80 of 153 periods empty (the 2nd–4th quarter of every hour) |
| Hourly | 37 of 39 hours have at least 95% of links. Missing: about 05:00–07:00 on 15 Oct (desktop gap) |

A link's band changes between consecutive updates 23% of the time, so filling gaps from the previous update is not safe at 5-minute resolution.

**Usable for:** hourly analysis (daily profiles, EDA). **Not usable for:** the 5-minute label and lag features, which need consecutive updates per link.

---

## 3. What this means for the project design

The plan (§4.1–4.2) works on one link at every 5-minute LTA update:

- `U(l,t)` needs the band at *t* and at *t* − 5;
- the features use lags back to *t* − 30;
- the outcome is 15 minutes ahead.

So what matters is an unbroken 5-minute series for each of the **2,598 expressway links**. Full-network coverage matters less.

Even with the fix, one fetch per update captures only about 80% of links at the newest update. The rest lag one or two updates, and their newest value is captured only if a later fetch happens to land on it. Gaps break the two-in-a-row label and the lag features.

**Expressways sit on only 58 of the 288 pages,** mostly pages 60–69 (2,099 links), plus small numbers scattered elsewhere. All 2,598 links were on exactly the same pages on 14 Oct 22:00 and 16 Oct 12:00. Fetching just those pages costs 58 calls instead of 288, which is cheap enough to fetch every minute and catch every update of every expressway link.

---

## 4. Options (decision needed)

| Option | Expressway 5-minute series | Whole network | Calls per hour, per key |
|---|---|---|---|
| A. Keep the fixed collector as it is | About 80–95% per update (to be measured) | Every update | ~3,500 (close to the limit) |
| B. One machine: the 58 expressway pages every minute, the whole network every 15 min | Nearly complete | Every 15 min | ~3,500 |
| **C. Two machines, two keys (recommended):** desktop collects the 58 expressway pages every minute; mini PC collects the whole network at every update | Nearly complete | Every update | ~3,500 each |

**Why C:**

- It gives complete data for the analysis population and keeps the full network, which is the plan's fallback (adding major arterials).
- The mini PC is already planned as a second collector (`TODO.md` §2).
- Each key has its own quota: LTA's rate-limit fault names the key.

**Guards needed for B or C:**

- If LTA adds or removes links, the pages shift. The collector should check that it still finds the 2,598 expressway links (by LinkID) and fall back to a full fetch if not, logging it. A full fetch every hour also confirms the page map.
- The proposal and data documentation should state the polling scheme per road category.

**Docs to update once decided:**

- `PROJECT_PLAN.md` §6.3, "Paging overlaps a 5-minute update": it still says "refetches once if LTA updated mid-fetch". That is no longer true, and the reason is section 2.
- `PIPELINE.md`.
- `DECISIONS.md`: add an entry on the collection scheme.

---

## 5. Questions for you

1. Is the mini PC collecting right now, and since when? It may be covering the desktop gap.
2. Do you agree with option C? Or do you prefer A, or B on one machine?
3. Did your key show the same hourly pattern? Check `log_speedbands.csv`: `fetch_failed` around minute :08, then `probe_failed` until :00.
4. After you pull `60c74a2`, please confirm on a full live hour: one `log_speedbands.csv` row per LTA update, about 12 an hour, and no rate-limit errors.

Analysis scripts used for these numbers can be shared on request. They are read-only checks on `data_raw/`.
