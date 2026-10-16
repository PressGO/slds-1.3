# Project 1.3: my to-do list

Updated Fri 16 Oct 2026. Tick items as you go: `- [x]`, with the date.

**Deadline: proposal, Sat 17 Oct, 23:59.** Do task 3 first if time is short. Tasks 1 and 2 can slip a day; the proposal can't.

---

## 1. GitHub repo with the course folder structure

The brief (§6.2) expects this layout. Git doesn't track empty folders, so each new folder gets an empty `.gitkeep` file.

```
group project/
├── README.md              how to reproduce + licence notice
├── AI_USE.md              AI log (required, Brief §5)
├── TODO.md                this file
├── PROJECT_PLAN.md
├── .gitignore             keeps out .Renviron, data, .venv
├── requirements.txt
├── setup_env.bat
├── 01_collector_monitor.ipynb
├── 03_visuals.ipynb
├── 04_process.ipynb
├── 00_check_sources.ipynb
├── analysis/              lta_collector.py, get_context_data.py, 00_check_sources.R (R models later)
├── R/                     R functions (later)          .gitkeep
├── figures/               made by code only            (ignored for now)
├── report/                report source + PDF          .gitkeep
├── slides/                slides source + PDF          .gitkeep
├── docs/                  defence notes, decisions     .gitkeep
├── data_raw/              collector output             NOT in Git
└── data_processed/        processing output            NOT in Git
```

Keep the notebooks in the main folder: they use it as their working directory. Moving them breaks their paths.

- [ ] Put `.gitignore`, `README.md`, `AI_USE.md` and `TODO.md` in the project folder.
- [ ] Create the folders `R`, `report`, `slides` and `docs`, each with an empty file named `.gitkeep`.
- [ ] Move the old files into a `_superseded` folder (ignored): `collect.py`, `01_collect.R`, `collector_setup_py.ipynb`, `01_collector_setup.ipynb`, `02_map_speedbands.R`.
- [ ] Clear all notebook outputs and save.
- [ ] Open a terminal in the project folder and run `git init -b main`, then `git add -n .` (this is a dry run that only lists files). **Stop** if `.Renviron`, `data_raw`, `data_processed` or `.venv` appear in the list.
- [ ] Run `git add .`, then `git commit -m "Initial commit: collector, context data, processing, visuals"`.
- [ ] On github.com, create a **private** repo. Don't tick "add README" or ".gitignore".
- [ ] Run `git remote add origin https://github.com/<you>/<repo>.git`, then `git push -u origin main`.
- [ ] Add teammates as collaborators (Settings → Collaborators).
- [ ] Check on github.com that no `.Renviron` and no data files were uploaded.

### Sharing the data (not on GitHub)

- [ ] Share `data_raw/` with the team another way: an external drive, or a Drive folder shared with the team only. Make sure `.Renviron` is never inside the shared folder.
- [ ] For the final package, ask the instructor whether a shared-drive link with checksums is acceptable for the raw data (question 4 in the plan's email, §11).

---

## 2. Ubuntu mini PC runs the collector, so the desktop is free

The plan: run both machines side by side for 1–2 days, check the mini PC is complete, then stop the desktop collector. Don't stop the desktop first, or you'll leave a gap.

### Set up (about 20 minutes)

- [ ] Install Git and Python: `sudo apt update && sudo apt install -y git python3 python3-venv`
- [ ] Clone the repo: `git clone https://github.com/<you>/<repo>.git ~/slds-1.3`
- [ ] Create the key file by typing it in. Never copy it through chat or GitHub. Run `nano ~/slds-1.3/.Renviron`, add the lines below, then run `chmod 600 ~/slds-1.3/.Renviron`.
  ```
  LTA_ACCOUNT_KEY=<your key>
  HC_PING_URL=https://hc-ping.com/<a NEW check for the mini PC>
  ```
- [ ] Test one pass: `cd ~/slds-1.3 && python3 analysis/lta_collector.py --once`. You should see `speedband_snapshots: 1` and an empty `last_error`.
- [ ] Create the service file: `sudo nano /etc/systemd/system/lta-collector.service`, with the content below. Replace `<you>` with your Ubuntu user name (run `whoami` to see it).
  ```ini
  [Unit]
  Description=SLDS 1.3 LTA collector
  Wants=network-online.target
  After=network-online.target

  [Service]
  User=<you>
  WorkingDirectory=/home/<you>/slds-1.3
  ExecStart=/usr/bin/python3 /home/<you>/slds-1.3/analysis/lta_collector.py
  Restart=always
  RestartSec=30

  [Install]
  WantedBy=multi-user.target
  ```
  With `Restart=always`, systemd restarts the collector after a crash or freeze-guard exit. With `WantedBy`, it starts at boot without anyone logging in.
- [ ] Start it now and at every boot: `sudo systemctl daemon-reload && sudo systemctl enable --now lta-collector`
- [ ] Check it: `systemctl status lta-collector` should say "active (running)". To watch it live, run `journalctl -u lta-collector -f` (Ctrl+C to stop watching).
- [ ] Stop the machine from sleeping: `sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target`
- [ ] If the BIOS has "Restore on AC power loss", set it to **Power On**.

### Keep updates from interrupting collection (until 27 Nov)

- [ ] Update once by hand now, while you're watching: `sudo apt update && sudo apt full-upgrade -y && sudo reboot`. After the reboot, check that `systemctl status lta-collector` says active.
- [ ] Turn off automatic apt updates: `sudo systemctl disable --now unattended-upgrades apt-daily.timer apt-daily-upgrade.timer`
- [ ] Hold snap auto-refresh: `sudo snap refresh --hold`
- [ ] Optional, on the desktop version of Ubuntu: `sudo systemctl disable --now packagekit` stops the background update checker.
- [ ] Install a temperature reader: `sudo apt install -y lm-sensors`, then run `sensors`. CPU under ~70 °C at idle is fine. The collector itself uses very little CPU.
- [ ] Check what's using the CPU: `top`. Nothing should sit near 100% for long. If something does, that's what to look into (last time it was an update stuck in a loop).
- [ ] Monthly is fine for manual updates during collection. Do them when you're at the machine, then check the service.
- [ ] After 27 Nov: undo with `sudo systemctl enable --now unattended-upgrades apt-daily.timer apt-daily-upgrade.timer` and `sudo snap refresh --unhold`.
- [ ] Check free disk space with `df -h ~`. Plan for at least what monitor cell 5 projects on the desktop by 27 Nov.

### Switch over

- [ ] After 24–48 h, compare the two machines. On the mini PC, check `cat ~/slds-1.3/data_raw/collector_status.json` and count today's files with `ls ~/slds-1.3/data_raw/speedbands/$(date +%F) | wc -l` (about 288 per full day). On the desktop, run monitor cell 5.
- [ ] Safer option: keep the desktop collector running too, at least until the training weeks end (6 Nov). It costs nothing in your use of the desktop, and if one machine fails the other covers the gap.
- [ ] If you do switch off the desktop, check first that the mini PC is complete, then stop the desktop collector in Command Prompt: `schtasks /End /TN SLDS_LTA_collector_247`, then `schtasks /Delete /TN SLDS_LTA_collector_247 /F`.
- [ ] **Keep the desktop's `data_raw/`.** It holds 14 Oct up to the switch. Later, copy it next to the mini PC data as `data_raw_desktop/`. Processing will read both folders.
- [ ] Pause the desktop's Healthchecks check, so it doesn't e-mail you about a machine you stopped on purpose.

### Weekly (from Wed 21 Oct)

- [ ] Back up the mini PC's `data_raw/` to an external drive or a team-only Drive folder.
- [ ] Health check: `systemctl status lta-collector` and the snapshot count.

---

## 3. Project proposal (due Sat 17 Oct, 23:59)

Proposal doc: https://claude.ai/code/artifact/087debe2-18bc-4a9a-984a-f0087c9ad84f

### Decide with the team (today)

- [ ] Accept or reject the methods changes from 15 Oct:
  - ~1 km segments instead of single links;
  - travel-time label (≥ 1.5× usual, for 2 updates);
  - one weekday norm;
  - test 10–20 Nov;
  - leave one expressway out for the transfer test;
  - drop road works as a feature.
- [ ] Log the decision with today's date in `docs/DECISIONS.md`.

### Numbers to put in the proposal

| Item | Value | Where it comes from |
|---|---|---|
| Collection start | 14 Oct 2026 | collector log |
| Snapshots so far | [n] | monitor cell 5 |
| Completeness | [n ÷ expected]% (288 per full day) | monitor cell 5 |
| Expressway links | 2,598 (13 Oct) | source check |
| Segments (if accepted) | ≈ 320 × 1 km (estimate: ~160 km of expressways × 2 directions) | check: total link length ÷ 1 km |
| Weekdays used | 26: train 15 Oct–6 Nov (17); test 10–20 Nov (9); Mon 9 Nov is a public holiday | calendar |
| Updates per day used | 192 (06:00–22:00, every 5 min) | design |
| Rows | ≈ 320 × 26 × 192 ≈ 1.6 M with segments, or 2,598 × 26 × 192 ≈ 13 M with links | arithmetic |
| Effective sample | number of unusual episodes (counted after collection) | say so explicitly |

### Fill in and fix

- [ ] Team names and the provisional title.
- [ ] Question: dates "14 Oct–20 Nov 2026", not 13 Oct (no data before 14 Oct).
- [ ] Audience: one principal metric. PR-AUC on onset rows is primary; precision at an alert budget is secondary.
- [ ] Unit, outcome, size: from the table above.
- [ ] Methods: drop road works if the changes are accepted.
- [ ] Validation: the new split and transfer test, if accepted.
- [ ] Largest risk: add "onsets may be unpredictable 15 min ahead except when jams spread upstream; we report spreading and origin onsets separately".
- [ ] Data and access: the collector evidence line, plus "second collector on a mini PC" as a mitigation.
- [ ] Responsibilities: names.

### Submit

- [ ] Export to PDF: A4, 12 pt. Check it's **one page**. If it's long, cut the optional clustering sentence first.
- [ ] Each member reads it and can explain every line.
- [ ] Add a row to `AI_USE.md` for the proposal (what was AI-drafted, who checked it).
- [ ] Submit by Sat 17 Oct 23:59. Confirm it went through.
- [ ] Send the instructor email (plan §11), including the data-sharing question.

---

## Later (after approval)

- [ ] Run the three data checks: do links chain end to start; total length per road; how often single links flicker.
- [ ] Processing script: merge both collectors' data → segments → segment travel-time panel → rain and calendar.
- [ ] R modelling (after 6 Nov): norms, labels, baselines, elastic net, random forest.
- [ ] Keep the collector running until at least Fri 20 Nov 23:59.
