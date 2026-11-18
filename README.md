# Recurring or unusual? Early warning of abnormal slowdowns on Singapore expressways

42.510 Statistical Learning for Data Science (SUTD, 2026), catalog topic 1.3.
Team: Aveline, Liam, Juan Peng, Ronnie

Status, 18 Nov 2026: the instructor has approved our proposal. The whole project is in Python (the brief allows any software, §6.2). LTA traffic data collected 24/7 since 14 Oct 2026 (desktop until 16 Oct; since then two collectors with two keys on the Linux mini PC, see `DECISIONS.md`). The model tables (data version 4: weekdays only, AYE and CTE held out) are on Google Drive: see "Getting the modelling data".

## Files

| Path | What it does | How to run |
|---|---|---|
| `analysis/lta_collector.py` | Collects LTA DataMall feeds 24/7: Traffic Speed Bands once per LTA update (about every 5 min), incidents and VMS (every 2 min), estimated travel times (every 5 min), road works and road openings (daily), into `data_raw/`. Python standard library only. Pauses to the next hour if LTA's rate limit (~4,000 calls/key/hour) is hit. | systemd service `lta-collector` on the Linux PC (`docs/LINUX_SETUP_FOR_CLAUDE_CODE.md`); on Windows via `01_windows_collector_monitor.ipynb` |
| `analysis/lta_collector.py --mode expressway` | Second collector (option C, decided 16 Oct 2026): only the 58 speed-band pages that hold the 2,598 expressway links, every 2 min, with a second key (`LTA_ACCOUNT_KEY2`), into `data_raw_expressway/`. Also polls PUB Flood Alerts every 5 min (saved on change), for label checks and masking, not as a model feature. Catches updates that one fetch per update misses, because LTA's pages lag each other. | systemd service `lta-collector-expressway` on the Linux PC; see `docs/LINUX_SETUP_FOR_CLAUDE_CODE.md` Step 4b |
| `check.sh` | Health check of both Linux collectors (service, heartbeat, last hour's speed-band fetches, last poll of every other feed incl. Flood Alerts, disk), plus the latest data.gov.sg rainfall day and the last nightly upload | `~/slds-1.3/check.sh` |
| `02_linux_collector_health.ipynb` | The same checks as a notebook, read-only: services, heartbeats, speed-band fetches per hour by status, rate-limit errors, every other LTA feed (incidents, VMS, travel times, road works, road openings, Flood Alerts: on time or late, failures, changes saved, current records), expressway coverage per 5-min update (data_raw alone vs both collectors, with a chart), disk | Top to bottom; set `HOURS` to look further back |
| `01_windows_collector_monitor.ipynb` | Windows only (desktop, now a cold spare): creates the scheduled task that keeps the collector running; health check; stop. | Cells 1–4 once per machine; cell 5 daily |
| `analysis/get_context_data.py` | NEA 5-minute rainfall (downloaded by date), MOM public holidays, MOE school terms and F1 closure dates, written to `data_processed/` | `.venv\Scripts\python analysis\get_context_data.py` |
| `upload_raw.sh` | Nightly backup (cron, 02:30 SGT): downloads any missing rainfall day, packs each finished day into one `.tar` per collector, copies them with rainfall, calendar, fetch logs and `MANIFEST.csv` to the Google Drive folder `SLDS_1.3_raw` (one folder per source) with `rclone copy` (never deletes; an uploaded tar is never replaced), then `rclone check`. Log: `archive_raw/upload.log` | cron on the Linux PC; by hand: `./upload_raw.sh; tail archive_raw/upload.log` |
| `analysis/archive_raw.py` | Stages `archive_raw/`, an exact copy of the Drive folder: daily tars from `data_raw/` and `data_raw_expressway/`, rainfall, calendar, fetch logs, `README.txt`, `MANIFEST.csv`, `SHA256SUMS.txt`. Only reads the raw folders; a packed day is never rebuilt | Called by `upload_raw.sh`; `--dry-run` to preview |
| `analysis/verify_raw.py` | For teammates: checks downloaded files against `SHA256SUMS.txt` and puts them into the project | See "Getting the raw data" |
| `analysis/build_data.py` | Raw files → model tables (data version 4 since 14 Nov; replaces `04_process.ipynb` and `build_model_data.py`, 14 Nov). Reads only `data_raw/`, `data_raw_expressway/` and the rainfall and calendar tables; rebuilds everything from scratch on every run (no cache), so the same raw files give the same tables. Checks every step and stops with `CHECK FAILED` if a check fails; every check and its result is listed in `extra/build_info.json`. Writes to temporary folders that are swapped in only at the end, so a failed build never leaves half-written files. Writes `data_processed/model/` (the Drive copy) and `docs/model_data/` | Via `build_processed.sh` |
| `analysis/data_settings.py` | Every setting of the data pipeline in one place (dates, splits, label rule, look-backs), each with the decision behind it. A change here is a decision: `DECISIONS.md` first | Read only |
| `analysis/data_steps.py` | The steps of the pipeline as small functions (tables in, tables out): cleaning, registry, neighbours, joining roads, normal level, labels, inputs, incidents | Used by `build_data.py` |
| `analysis/test_data_steps.py` | Tests every step on small made-up data with answers worked out by hand | `.venv/bin/python analysis/test_data_steps.py -v` |
| `analysis/verify_data.py` | Independent check: recomputes sample rows of the finished tables straight from the raw files, written from the rules only (not from the pipeline code) | Via `build_processed.sh` |
| `build_processed.sh` | Rainfall download, tests, `build_data.py` (memory capped at 14 GB so the collectors are safe), `verify_data.py`, then copies `data_processed/model/` to the Google Drive folder `SLDS_1.3_processed` (test files only with `SHARE_TEST=1`). Stops at the first failure. `BUILD_NOW="YYYY-MM-DD HH:MM"` rebuilds an earlier state (the same days). Log: `data_processed/build.log` | `./build_processed.sh` (or `--no-upload`) |
| `03_visuals.ipynb` | Maps, time–space diagrams, share of links by speed band | Cell 1, then any plot cell |
| `analysis/00_check_sources.py` | One-off check of every source (standard library only); outputs in `data_raw/source_check/`. Run 13 Oct 2026 (first version, in R) and 16 Oct 2026: 315 requests, 0 failed both times | `python3 analysis/00_check_sources.py` (done) |
| `DECISIONS.md` | Dated, frozen design and collection decisions (append only), and the background to the 16 Oct collection change: LTA's rate limit and out-of-sync pages | Read before changing anything |
| `docs/LINUX_SETUP_FOR_CLAUDE_CODE.md` | Step-by-step setup of both collectors on the Linux PC | Once per machine |
| `setup_env.bat` (Windows), `setup_env.sh` (Linux), `requirements.txt` | Creates `.venv` with polars, numpy, matplotlib, Jupyter, pandas, pyarrow and scikit-learn, and the kernel "Python (SLDS 1.3)" | Once per machine |

The notebooks sit in the project folder because they use it as their working directory.

Planned: the team's model scripts in Python (baselines, penalised logistic regression, random forest), reading `data_processed/model/train.parquet`.

Not in git: `project_docs/` on the Linux PC (the course brief and catalog, our submitted proposal, and our working notes such as the changelog).

## Setup on a new machine

1. Install Python 3.10 or newer, then run `setup_env.bat` (Windows) or `./setup_env.sh` (Linux). This is needed for the notebooks, the data build and the models; the collector needs no packages.
2. Create `.Renviron` in the project folder (the name comes from R; our Python scripts read it). It is excluded by `.gitignore`; never commit it or paste its contents anywhere.

   ```
   LTA_ACCOUNT_KEY=<LTA DataMall key>
   HC_PING_URL=https://hc-ping.com/<check id>
   DATA_GOV_KEY=<data.gov.sg key>
   LTA_ACCOUNT_KEY2=<second LTA key, for the expressway collector>
   HC_PING_URL2=https://hc-ping.com/<second check id>
   ```

   `HC_PING_URL` (e-mail alert when collection stops) and `DATA_GOV_KEY` (higher rate limit) are optional. The `...2` lines are only needed on the PC that runs the expressway collector. LTA's rate limit (about 4,000 calls an hour, resetting on the hour; not published) is per key, so each collector needs its own key.
3. To collect on Windows: run `01_windows_collector_monitor.ipynb` cells 1–4, and keep the machine awake and signed in. On Linux: a systemd service; see `docs/LINUX_SETUP_FOR_CLAUDE_CODE.md`. Collection needs no Python packages.
4. To process: `./build_processed.sh --no-upload` (rainfall, tests, build, independent check).

## Data

Not in this repository. `data_raw/` (whole network) and `data_raw_expressway/` (expressway pages) hold the collector output (several GB, never edited); `data_processed/` is rebuilt from them. LTA serves only the current state, so raw snapshots cannot be downloaded again: back up both folders separately.

## Getting the raw data

The Linux PC uploads the raw data each night at about 02:30 SGT (the previous day) to the Google Drive folder `SLDS_1.3_raw`, shared with the team as Viewer. Files are only added, never deleted or replaced. `README.txt` in the folder repeats this.

```
README.txt  MANIFEST.csv  SHA256SUMS.txt   MANIFEST: every file with date, size, SHA-256, raw files inside, speed-band snapshots
lta_network/       lta_network_<date>.tar      whole network (data_raw/): speed bands, incidents, VMS, travel times, road works/openings
lta_expressway/    lta_expressway_<date>.tar   expressway pages every 2 min + PUB flood alerts (data_raw_expressway/)
lta_fetch_logs/    network_log_*.csv, expressway_log_*.csv   every fetch of both collectors, refreshed nightly
lta_source_check/  lta_source_check_2026-10-16.tar           13-16 Oct check of every source
nea_rainfall/      rain_YYYYMMDD.jsonl.gz      NEA 5-minute rainfall, one file per day
calendar/          mom_public_holidays_2026.json
```

1. Open `MANIFEST.csv` to see which days exist (and `n_speedbands` per day for gaps).
2. Download `SHA256SUMS.txt` and the files you need into one folder, keeping the folder names (e.g. `dl/SHA256SUMS.txt`, `dl/lta_expressway/lta_expressway_2026-10-20.tar`).
3. From the repo: `python analysis/verify_raw.py dl` must end `RESULT: OK`.
4. `python analysis/verify_raw.py dl --extract .` unpacks the tars into `data_raw/` and `data_raw_expressway/` and puts rainfall, calendar and fetch logs where the notebooks expect them. Existing files are kept.

The desktop's 14-16 Oct data is not uploaded (team decision, 24 Oct): it is mostly 14 Oct, and 16 Oct is already here.

## Getting the modelling data

The tables for the models are in the Google Drive folder `SLDS_1.3_processed` (Viewer), rebuilt with `./build_processed.sh` on the Linux PC.

```
README.md        what every column means, the rules, Python quick start (also in docs/model_data/README.md)
train.parquet    the rows to train on (Mon-Fri, no public holidays); split = "train" (fit, tune) or "validate"
                 (choose, calibrate); heldout_road = TRUE for AYE and CTE (only for the transfer check)
test.parquet     the test week, added after it ends and the plan is frozen
extra/           everything else: a small sample, the full table with info_ columns, links, neighbours,
                 joining roads, normal levels, days.csv, incidents, build_info.json, SHA256SUMS.txt
```

Download what you need into `data_processed/model/` (keep `extra/` as a folder), then check it there: `sha256sum -c --ignore-missing ../../docs/model_data/SHA256SUMS.txt`. To try code quickly, start with `extra/train_sample.parquet`. `README.md` and `extra/build_info.json` give the data version; a change of rule raises it and is listed under "Changes".

## Licence notice

Contains information from LTA DataMall (Traffic Speed Bands, Traffic Incidents, VMS/EMAS, Estimated Travel Times, Approved Road Works, Planned Road Openings), accessed from 13 Oct 2026, and from NEA rainfall and MOM public holiday data accessed from data.gov.sg, which are made available under the terms of the Singapore Open Data Licence version 1.0 (https://data.gov.sg/open-data-licence).

## AI use

See `AI_USE.md`.
