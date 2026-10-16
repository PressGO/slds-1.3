# Task for Claude Code: run the LTA collector 24/7 on this Ubuntu PC

Hand this whole file to Claude Code on the Linux PC, for example: "Read LINUX_SETUP_FOR_CLAUDE_CODE.md and do it with me."

---

## Context (for Claude Code)

- This is a university project (SUTD 42.510, topic 1.3). It collects LTA DataMall traffic data (Singapore).
- `lta_collector.py` is a finished, tested collector that uses only the Python standard library.
  - It probes the Traffic Speed Bands API every 60 s and fetches all 288 pages once per LTA update (about every 5 min), when page 1's `lastUpdatedTime` moves forward.
  - It also saves incidents, VMS and travel times when they change, and road works and openings once a day.
  - It retries failures, writes files atomically, and allows only one copy per output folder (file lock).
  - It has a freeze guard: if its loop stalls for 20 min it exits with code 3, so the service manager should restart it.
  - It pings Healthchecks.io after each snapshot if `HC_PING_URL` is set.
- **Rate limit.** LTA's published limit is 10 M calls/day, but in practice each key is cut off after about 4,000 calls in a clock hour (HTTP 500 "Rate limit quota violation", resetting on the hour). The collector does not retry these and pauses until the next hour. Never run two collectors on the same key.
- **Current set-up (decided 16 Oct 2026, option C in `docs/COLLECTION_REVIEW_2026-10-16.md`):** this Linux PC runs both collectors, each with its own key: `lta-collector` (whole network, `LTA_ACCOUNT_KEY`, Step 4) and `lta-collector-expressway` (expressway pages every 2 min, `LTA_ACCOUNT_KEY2`, Step 4b). The Windows desktop is a cold spare and stays off.
- The data can never be re-downloaded (LTA serves only the current state), so reliability matters more than anything else.
- Collection must run until at least **Fri 27 Nov 2026**.

## Rules

1. **Never read, print, log, copy or commit the contents of `.Renviron`.** It holds the LTA API key and the Healthchecks URL. The user types those into the file themselves. To check the file exists, only test for the variable names, for example `grep -c '^LTA_ACCOUNT_KEY=' .Renviron`.
2. **Don't modify `lta_collector.py`** unless the `--once` test fails. In that case show the error and propose a fix before changing anything.
3. Commands needing `sudo`: show each one and let the user run it or approve it. Explain in one line what it does.
4. Don't delete anything in `data_raw/`.
5. The user is not a Linux expert. Explain each step in one plain sentence.

---

## Step 1: Project folder, code and Python

Get the code from GitHub (https://github.com/PressGO/slds-1.3; done 16 Oct 2026). It holds the complete project with the course's folder structure and no data:

```
slds-1.3/
├── README.md  AI_USE.md  PROJECT_PLAN.md  DECISIONS.md  .gitignore  check.sh
├── requirements.txt  setup_env.bat  setup_env.sh   (notebook environment: Windows / Linux)
├── 00_check_sources.ipynb  00_check_sources_python.ipynb  01_collector_monitor.ipynb  03_visuals.ipynb  04_process.ipynb
├── analysis/   lta_collector.py  get_context_data.py  00_check_sources.R  00_check_sources.py
├── R/  report/  slides/                      (empty for now, .gitkeep)
└── docs/       LINUX_SETUP_FOR_CLAUDE_CODE.md (this file)  COLLECTION_REVIEW_2026-10-16.md
```

```bash
sudo apt update && sudo apt install -y python3 git
git clone https://github.com/PressGO/slds-1.3.git ~/slds-1.3
cd ~/slds-1.3 && ls -la
grep -c "HC_PING_URL" analysis/lta_collector.py   # must be > 0 (correct version)
python3 --version                                 # needs 3.9+
```

**Two separate Python setups, on purpose:**

- **Collection:** the systemd service runs the collector on the system `python3`, with no packages. Never point the service at `.venv`. A broken package install must not be able to stop collection.
- **Analysis and graphs:** the user also wants to run the processing and visual notebooks here. These need polars, numpy, matplotlib and Jupyter, which go into a virtual environment in `~/slds-1.3/.venv` (excluded by `.gitignore`):

```bash
sudo apt install -y python3-venv
cd ~/slds-1.3 && chmod +x setup_env.sh && ./setup_env.sh
# expect a final line: OK  Python 3.x | polars ... | numpy ... | matplotlib ...
```

To use the notebooks, start Jupyter **from the project folder**, because the notebooks use it as their working directory: `cd ~/slds-1.3 && .venv/bin/jupyter lab`. Then pick the kernel "Python (SLDS 1.3)". In VS Code, open the `~/slds-1.3` folder and choose that kernel.

Do this step after Step 9, so collection is running first.

The collector treats the parent of `analysis/` as the project folder, so data goes to `~/slds-1.3/data_raw/`, which `.gitignore` excludes.

## Step 2: Secrets file (the user does this)

Ask the user to create a **new** check on healthchecks.io for this PC:
- Name: "SLDS Linux collector"; Period: 5 minutes; Grace: 15 minutes.
- Use a separate check from the Windows one, so an alert says which machine stopped.

Then the user runs `nano ~/slds-1.3/.Renviron` and types:

```
LTA_ACCOUNT_KEY=<their LTA key>
HC_PING_URL=https://hc-ping.com/<the Linux check's id>
```

Afterwards, run:

```bash
chmod 600 ~/slds-1.3/.Renviron
grep -c '^LTA_ACCOUNT_KEY=' ~/slds-1.3/.Renviron   # expect 1
grep -c '^HC_PING_URL=' ~/slds-1.3/.Renviron       # expect 1
```

## Step 3: One test pass

```bash
cd ~/slds-1.3 && python3 analysis/lta_collector.py --once
```

Expected:
- It ends by printing a JSON status with `"speedband_snapshots": 1` under `today` and `"last_error": null`.
- One file appears in `data_raw/speedbands/<today>/`.
- Run `ls data_raw/speedbands/$(date +%F)` to confirm.
- The Healthchecks check turns green within a minute.

If HTTP 401/403 appears, the key is wrong: the user fixes `.Renviron`. Never print it.

## Step 4: systemd service (starts at boot, no login needed, restarts on failure)

Create `/etc/systemd/system/lta-collector.service`. Replace `USER` with the output of `whoami`.

```ini
[Unit]
Description=SLDS 1.3 LTA DataMall collector
Wants=network-online.target
After=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
User=USER
WorkingDirectory=/home/USER/slds-1.3
ExecStart=/usr/bin/python3 /home/USER/slds-1.3/analysis/lta_collector.py
Restart=always
RestartSec=30
Nice=5

[Install]
WantedBy=multi-user.target
```

- `StartLimitIntervalSec=0` means systemd never gives up restarting it, for example during a long internet outage.

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now lta-collector
systemctl status lta-collector --no-pager    # expect "active (running)"
journalctl -u lta-collector -n 30 --no-pager
```

## Step 4b: Second service, expressway collector (added 16 Oct 2026)

Option C from `docs/COLLECTION_REVIEW_2026-10-16.md`, run on this PC: a second copy of the same script fetches only the 58 pages that hold the expressway links, every 2 minutes, with its own key, into `data_raw_expressway/`. It has its own lock, so it runs alongside `lta-collector`.

`.Renviron` needs `LTA_ACCOUNT_KEY2=` (a key from a different LTA account) and, for alerts, `HC_PING_URL2=` (a separate Healthchecks check, e.g. "SLDS expressway collector", period 5 min, grace 15 min).

Test once: `python3 analysis/lta_collector.py --once --mode expressway --key-name LTA_ACCOUNT_KEY2 --hc-name HC_PING_URL2`. It should log "page map rebuilt: 2598 expressway links on 58 of 288 pages".

Create `/etc/systemd/system/lta-collector-expressway.service` (replace `USER`):

```ini
[Unit]
Description=SLDS 1.3 LTA collector, expressway pages (second key)
Wants=network-online.target
After=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
User=USER
WorkingDirectory=/home/USER/slds-1.3
ExecStart=/usr/bin/python3 /home/USER/slds-1.3/analysis/lta_collector.py --mode expressway --key-name LTA_ACCOUNT_KEY2 --hc-name HC_PING_URL2
Restart=always
RestartSec=30
Nice=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now lta-collector-expressway
systemctl status lta-collector-expressway --no-pager
```

`~/slds-1.3/check.sh` reports on both services.

## Step 5: Never sleep, suspend or hibernate

```bash
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
```

On Ubuntu Desktop (GNOME), also turn off automatic suspend. Run these as the normal user, not sudo:

```bash
gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type 'nothing'
gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-battery-type 'nothing'
```

- **Screen lock and screen blanking are fine.** Leave them on. The service runs at system level and doesn't depend on a logged-in or unlocked session.
- Logging out is fine as well. Only suspend, hibernate or shutdown stop collection.

To confirm, run `systemctl status sleep.target`. It should say "masked".

## Step 6: Stop updates from interrupting collection (until 27 Nov)

The user once had an update loop that ran all night and overheated the PC. So:

```bash
# 1. Update once now, while the user is present, then reboot and confirm the service comes back
sudo apt update && sudo apt full-upgrade -y
sudo reboot
# after reboot:
systemctl status lta-collector --no-pager

# 2. Turn off automatic updates until collection ends
sudo systemctl disable --now unattended-upgrades apt-daily.timer apt-daily-upgrade.timer
sudo snap refresh --hold                       # if snap is installed
sudo systemctl disable --now packagekit 2>/dev/null || true
```

Undo after 27 Nov:

```bash
sudo systemctl enable --now unattended-upgrades apt-daily.timer apt-daily-upgrade.timer
sudo snap refresh --unhold
sudo systemctl enable packagekit 2>/dev/null || true
```

## Step 7: Temperature, disk and power

```bash
sudo apt install -y lm-sensors && sensors    # note idle CPU temperature; < ~70 °C is fine
top -b -n 1 | head -15                        # nothing should sit near 100% CPU
df -h ~                                       # free space
```

- The desktop collector uses very roughly 0.5 GB/day. For 6 weeks, keep at least 40 GB free.
- Tell the user: if the BIOS has "Restore on AC power loss", set it to **Power On**, so the PC comes back after a power cut.

## Step 8: Daily health-check command

`check.sh` is in the repo. It is read-only and reports on both services: active or not, files saved today, heartbeat age, last error, the last hour's speed-band fetches by status, disk use and CPU temperature.

```bash
~/slds-1.3/check.sh
```

A healthy hour: `lta-collector` about 12 `ok`/`ok_flagged` rows; `lta-collector-expressway` about 30 rows; no `probe_failed` or `fetch_failed`; heartbeats under 2 minutes.

## Step 9: Final checks (report results to the user)

- [ ] `systemctl is-enabled lta-collector lta-collector-expressway` prints `enabled` twice; `systemctl is-active` on both prints `active` twice.
- [ ] After 15 minutes, `check.sh` shows 2–3 new snapshots and a heartbeat under 2 minutes.
- [ ] Both Healthchecks checks are green.
- [ ] `systemctl status sleep.target` is masked.
- [ ] Automatic updates are disabled.
- [ ] Test the restart: `sudo systemctl kill lta-collector`, wait 40 s, then `systemctl is-active lta-collector` prints `active` again.
- [ ] Tell the user: press **Test** on the e-mail integration in Healthchecks to confirm alerts reach their inbox.

## Useful commands for the user

| Task | Command |
|---|---|
| Are they running? | `systemctl status lta-collector lta-collector-expressway` |
| Health check | `~/slds-1.3/check.sh` |
| Live log | `journalctl -u lta-collector -f` or `-u lta-collector-expressway -f` (Ctrl+C stops watching, not the collector) |
| Collectors' own logs | `tail -n 30 ~/slds-1.3/data_raw/logs/collector.log` and `~/slds-1.3/data_raw_expressway/logs/collector.log` |
| Restart both (e.g. after `git pull`) | `sudo systemctl restart lta-collector lta-collector-expressway` |
| Stop for good (after 27 Nov) | `sudo systemctl disable --now lta-collector lta-collector-expressway` |

## Step 10: GitHub (done 16 Oct 2026)

The repo is https://github.com/PressGO/slds-1.3 (public). Git ignores `.Renviron`, `.venv/`, `data_raw/`, `data_raw_*/` and `data_processed/`. Before every commit, check that no staged file contains a key: `sed -n 's/^LTA_ACCOUNT_KEY=//p' .Renviron | tr -d "\"' \r" | git grep --cached -lF -f -` must print nothing (repeat with `LTA_ACCOUNT_KEY2`).

To update the code on this PC: `cd ~/slds-1.3 && git pull`, then restart both services.

## Later (not part of this task)

- The desktop is a cold spare: keep its existing folder (it holds data from 14 to 16 Oct and its `.Renviron`). To use it again, `git pull` there first, and never run it on a key that a running collector already uses.
- Copy the desktop's `data_raw/` to this PC as `~/slds-1.3/data_raw_desktop/`. `04_process.ipynb` reads every `data_raw*/` folder and removes duplicates.
- Once a week, back up `~/slds-1.3/data_raw/` and `~/slds-1.3/data_raw_expressway/` to an external drive.
