# Recurring or unusual? Early warning of abnormal slowdowns on Singapore expressways

42.510 Statistical Learning for Data Science (SUTD, 2026), catalog topic 1.3.
Team: Aveline, Liam, Juan Peng, Ronnie

Status, 16 Oct 2026: LTA traffic data collected 24/7 since 14 Oct 2026 (desktop until 16 Oct; since then two collectors with two keys on the Linux mini PC, see `DECISIONS.md`). Proposal due 17 Oct; no modelling until the proposal is approved (Brief §6.1).

## Files

| Path | What it does | How to run |
|---|---|---|
| `analysis/lta_collector.py` | Collects LTA DataMall feeds 24/7: Traffic Speed Bands once per LTA update (about every 5 min), incidents and VMS (every 2 min), estimated travel times (every 5 min), road works and road openings (daily), into `data_raw/`. Python standard library only. Pauses to the next hour if LTA's rate limit (~4,000 calls/key/hour) is hit. | systemd service `lta-collector` on the Linux PC (`docs/LINUX_SETUP_FOR_CLAUDE_CODE.md`); on Windows via `01_windows_collector_monitor.ipynb` |
| `analysis/lta_collector.py --mode expressway` | Second collector (option C, decided 16 Oct 2026): only the 58 speed-band pages that hold the 2,598 expressway links, every 2 min, with a second key (`LTA_ACCOUNT_KEY2`), into `data_raw_expressway/`. Also polls PUB Flood Alerts every 5 min (saved on change), for label checks and masking, not as a model feature. Catches updates that one fetch per update misses, because LTA's pages lag each other. | systemd service `lta-collector-expressway` on the Linux PC; see `docs/LINUX_SETUP_FOR_CLAUDE_CODE.md` Step 4b |
| `check.sh` | Health check of both Linux collectors (service, heartbeat, last hour's fetches, disk) | `~/slds-1.3/check.sh` |
| `02_linux_collector_health.ipynb` | The same checks as a notebook, read-only: services, heartbeats, fetches per hour by status, rate-limit errors, expressway coverage per 5-min update (data_raw alone vs both collectors, with a chart), disk | Top to bottom; set `HOURS` to look further back |
| `01_windows_collector_monitor.ipynb` | Windows only (desktop, now a cold spare): creates the scheduled task that keeps the collector running; health check; stop. | Cells 1–4 once per machine; cell 5 daily |
| `analysis/get_context_data.py` | NEA 5-minute rainfall (downloaded by date), MOM public holidays, MOE school terms and F1 closure dates, written to `data_processed/` | `.venv\Scripts\python analysis\get_context_data.py` |
| `04_process.ipynb` | Raw files → link registry, expressway speed-band panel, quality report, incidents, analysis panel (Parquet). Reads every `data_raw*/` folder (both collectors, plus the desktop's data if copied in as `data_raw_desktop/`) and removes duplicates on (link, LTA update time). | Top to bottom |
| `03_visuals.ipynb` | Maps, time–space diagrams, share of links by speed band | Cell 1, then any plot cell |
| `analysis/00_check_sources.R`, `00_check_sources.ipynb` | One-off check of every source (run 13 Oct 2026: 315 requests, 0 failed) | Done |
| `analysis/00_check_sources.py`, `00_check_sources_python.ipynb` | The same check in Python (standard library only); same outputs in `data_raw/source_check/` (run 16 Oct 2026: 315 requests, 0 failed) | `python3 analysis/00_check_sources.py`, or the notebook |
| `DECISIONS.md` | Dated, frozen design and collection decisions (append only), and the background to the 16 Oct collection change: LTA's rate limit and out-of-sync pages | Read before changing anything |
| `docs/LINUX_SETUP_FOR_CLAUDE_CODE.md` | Step-by-step setup of both collectors on the Linux PC | Once per machine |
| `setup_env.bat` (Windows), `setup_env.sh` (Linux), `requirements.txt` | Creates `.venv` with polars, numpy, matplotlib and Jupyter, and the kernel "Python (SLDS 1.3)" | Once per machine |

The notebooks sit in the project folder because they use it as their working directory.

Planned: processing into ~1 km expressway segments, and the modelling scripts in R (after approval).

## Setup on a new machine

1. Install Python 3.10 or newer, then run `setup_env.bat` (Windows) or `./setup_env.sh` (Linux). This is only needed for the notebooks; the collector needs no packages.
2. Create `.Renviron` in the project folder. It is excluded by `.gitignore`; never commit it or paste its contents anywhere.

   ```
   LTA_ACCOUNT_KEY=<LTA DataMall key>
   HC_PING_URL=https://hc-ping.com/<check id>
   DATAGOVSG_API_KEY=<data.gov.sg key>
   LTA_ACCOUNT_KEY2=<second LTA key, for the expressway collector>
   HC_PING_URL2=https://hc-ping.com/<second check id>
   ```

   `HC_PING_URL` (e-mail alert when collection stops) and `DATAGOVSG_API_KEY` (higher rate limit) are optional. The `...2` lines are only needed on the PC that runs the expressway collector. LTA's rate limit (about 4,000 calls an hour, resetting on the hour; not published) is per key, so each collector needs its own key.
3. To collect on Windows: run `01_windows_collector_monitor.ipynb` cells 1–4, and keep the machine awake and signed in. On Linux: a systemd service; see `docs/LINUX_SETUP_FOR_CLAUDE_CODE.md`. Collection needs no Python packages.
4. To process: run `get_context_data.py`, then `04_process.ipynb`.

## Data

Not in this repository. `data_raw/` (whole network) and `data_raw_expressway/` (expressway pages) hold the collector output (several GB, never edited); `data_processed/` is rebuilt from them. LTA serves only the current state, so raw snapshots cannot be downloaded again: back up both folders separately.

## Licence notice

Contains information from LTA DataMall (Traffic Speed Bands, Traffic Incidents, VMS/EMAS, Estimated Travel Times, Approved Road Works, Planned Road Openings), accessed from 13 Oct 2026, and from NEA rainfall and MOM public holiday data accessed from data.gov.sg, which are made available under the terms of the Singapore Open Data Licence version 1.0 (https://data.gov.sg/open-data-licence).

## AI use

See `AI_USE.md`.
