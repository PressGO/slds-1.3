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

- [x] Put `.gitignore`, `README.md`, `AI_USE.md` and `TODO.md` in the project folder. (16 Oct)
- [x] Create the folders `R`, `report`, `slides` and `docs`, each with an empty file named `.gitkeep`. (16 Oct)
- [ ] Move the old files into a `_superseded` folder (ignored): `collect.py`, `01_collect.R`, `collector_setup_py.ipynb`, `01_collector_setup.ipynb`, `02_map_speedbands.R`.
- [x] Clear all notebook outputs and save. (16 Oct; keep committing notebooks without outputs)
- [x] Open a terminal in the project folder and run `git init -b main`, then `git add -n .` (this is a dry run that only lists files). **Stop** if `.Renviron`, `data_raw`, `data_processed` or `.venv` appear in the list. (16 Oct, mini PC)
- [x] Run `git add .`, then `git commit -m "Initial commit: collector, context data, processing, visuals"`. (16 Oct)
- [x] Create the GitHub repo: https://github.com/PressGO/slds-1.3. Made **public** on 16 Oct (team decision); check the course allows public repos before the report.
- [x] Push to GitHub. (16 Oct, with `gh repo create`)
- [ ] Add teammates as collaborators (Settings → Collaborators).
- [x] Check that no `.Renviron`, no key and no data files were uploaded. (16 Oct: staged files scanned for both keys before each push)

### Sharing the data (not on GitHub)

- [ ] Share `data_raw/` with the team another way: an external drive, or a Drive folder shared with the team only. Make sure `.Renviron` is never inside the shared folder.
- [ ] For the final package, ask the instructor whether a shared-drive link with checksums is acceptable for the raw data (question 4 in the plan's email, §11).

---

## 2. Collection on the Ubuntu mini PC

**Decided 16 Oct (option C, `docs/COLLECTION_REVIEW_2026-10-16.md`):** the mini PC runs both collectors, each with its own LTA key, because LTA cuts a key off after about 4,000 calls in a clock hour. The desktop is a cold spare and stays off. Accepted risk: no backup machine while it is off.

| Service | Key | Collects | Output |
|---|---|---|---|
| `lta-collector` | `LTA_ACCOUNT_KEY` | whole network at each update, plus incidents, VMS, travel times, road works | `data_raw/` |
| `lta-collector-expressway` | `LTA_ACCOUNT_KEY2` | the 58 expressway pages every 2 min | `data_raw_expressway/` |

Setup steps: `docs/LINUX_SETUP_FOR_CLAUDE_CODE.md`.

### Done (16 Oct)

- [x] Project cloned to `~/slds-1.3`; `.Renviron` with both keys and both Healthchecks URLs (`chmod 600`).
- [x] `lta-collector` service running since 12:07 (code from `60c74a2` since 13:06); `lta-collector-expressway` since 13:21. Both enabled at boot.
- [x] Sleep, suspend and hibernate masked.
- [x] Python environment for the notebooks (`setup_env.sh`), kernel "Python (SLDS 1.3)".
- [x] Rate-limit fix (`deda600`, `60c74a2`) and expressway mode (`0a35c4c`).

### Still to do on the mini PC

- [ ] Confirm a full live hour: `~/slds-1.3/check.sh` shows about 12 fetches for `lta-collector`, about 30 for `lta-collector-expressway`, and no rate-limit errors.
- [ ] Press **Test** on the e-mail integration of both Healthchecks checks.
- [ ] Stop automatic updates until 27 Nov (Linux guide, Step 6): update once by hand, reboot, check both services, then disable `unattended-upgrades`, `apt-daily.timer`, `apt-daily-upgrade.timer` and hold snap refresh. Undo after 27 Nov.
- [ ] `sudo apt install -y lm-sensors`, then `sensors`: CPU under ~70 °C at idle is fine.
- [ ] If the BIOS has "Restore on AC power loss", set it to **Power On**.
- [ ] Check free disk space with `df -h ~` once a week (whole network about 0.5 GB/day; expressway collector much less).

### Desktop (cold spare)

- [ ] Disable its watchdog task so it can't restart on its own, in an admin terminal: `Disable-ScheduledTask -TaskName SLDS_LTA_collector_247`.
- [ ] Pause its Healthchecks check.
- [ ] **Keep its `data_raw/`** (14 to 16 Oct). Copy it to the mini PC as `~/slds-1.3/data_raw_desktop/`; `04_process.ipynb` reads every `data_raw*/` folder and removes duplicates.
- [ ] If it is ever needed again: `git pull` first, and use a key that no running collector uses.

### Weekly (from Wed 21 Oct)

- [ ] Back up `data_raw/` and `data_raw_expressway/` to an external drive or a team-only Drive folder (never include `.Renviron`).
- [ ] Run `~/slds-1.3/check.sh`.

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
- [ ] Log the decision with today's date in `DECISIONS.md`.

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
- [ ] Keep both collectors running until at least Fri 20 Nov 23:59 (Linux guide says 27 Nov, for the school-holiday stress test).
