# How to reproduce the project

This page has the full steps and the list of files. The short version is in `README.md`.

The whole project is in Python. The brief allows any software (section 6.2), and the instructor confirmed it.

## Where things are

The folders follow the list in the course brief (section 6.2):

| The brief asks for | Here |
|---|---|
| `README.md`: how to reproduce | this file |
| `data_raw/` or retrieval code | `analysis/lta_collector.py`, `analysis/get_context_data.py`; the archive check `analysis/verify_raw.py` (see "Data") |
| `data_processed/`: analysis-ready data | not in the repository (see "Data"); documented in `DATA.md` and `docs/model_data/` |
| `R/`: functions or reusable code | `analysis/data_settings.py`, `analysis/data_steps.py` (data); `modelling/settings.py`, `common.py`, `features.py`, `modeldata.py`, `lassofit.py`, `segments.py`, `plotstyle.py` (models) |
| `analysis/`: ordered scripts or notebooks | `notebooks/part1` to `part4` (the walk-through, in order); the same steps as scripts: `analysis/build_data.py`, then `modelling/01_eda.py` to `16_classifiers_and_roc.py` |
| `figures/`: final figures made by code | `figures/report/` (the report's figures), `figures/notebooks/` (drawn by the four notebooks), `figures/pipeline/` (drawn by the scripts in `modelling/`); the four pictures directly in `figures/` come from `03_visuals.ipynb` |
| `report/` | the report is submitted separately and is not in this repository; its three figures are in `figures/report/` |
| `slides/` | not written yet |
| `AI_USE.md` | `AI_USE.md` |

The notebooks at the top of the folder (`01_`, `02_`, `03_`) are the collector monitors and the maps of the raw data.

## Data

The data are not in the repository: the raw files are several GB.

- **Model tables:** two zip files on the Releases page of the repository (release `data-v4`).
  - `data_processed_v4.zip`: unzip it in the project folder. It gives `data_processed/`: the model tables
    (`model/train.parquet` with the train and validation rows, and `model/extra/`), the cleaned panel (`clean/`),
    and the rainfall and calendar tables. Check it with
    `cd data_processed/model && sha256sum -c extra/SHA256SUMS.txt`.
  - `test_week_build.zip`: the same build made on 21 Nov, which also holds the test week (`model/test.parquet`).
    Unzip it into `work/data_build/`. It is only needed to run the test week again (see "The test week" below).
- **Raw files:** `data_raw/` (whole network) and `data_raw_expressway/` (expressway pages). They are archived each
  night to the Google Drive folder `SLDS_1.3_raw`, one file per collector and day, with `MANIFEST.csv` and
  `SHA256SUMS.txt`. [TEAM: say here how the instructor gets access to the Drive folder.]
- **Documentation:** `DATA.md`.

## Part 1: how to reproduce

1. **Set up Python** (3.10 or newer): `./setup_env.sh` on Linux, `setup_env.bat` on Windows. This creates `.venv`
   from `requirements.txt`.
2. **Get the raw data.** LTA serves only the current state, so the raw files cannot be downloaded again. Take them
   from our archive (see "Data" above):

   ```
   python analysis/verify_raw.py dl              # must end with RESULT: OK
   python analysis/verify_raw.py dl --extract .  # unpacks into data_raw/ and data_raw_expressway/
   ```

   To collect new data yourself, see "Collecting" below.
3. **Build the model tables** from the raw files: `./build_processed.sh --no-upload`. It runs four steps and stops
   at the first failure:
   - download the rainfall for any missing day;
   - run the unit tests;
   - run the build, which checks itself (114 checks);
   - run an independent check of sample rows.
4. **Run the Part 1 notebook**, `notebooks/part1_data_collection_and_transformation.ipynb`, from the `notebooks/`
   folder (about 3 minutes). It rebuilds every train and validation day from the raw files, step by step, and stops
   if any row or column differs from the tables of step 3.

To skip steps 2 and 3, take the finished tables from the release (see "Data" above). The Part 1 notebook still
needs the raw files.

## Part 1: the files

| Path | What it does | How to run |
|---|---|---|
| `analysis/lta_collector.py` | Collects the LTA DataMall feeds around the clock into `data_raw/`: Traffic Speed Bands at each LTA update (about every 5 minutes), plus incidents, VMS, travel times, road works and road openings. Python standard library only. Retries failed requests, and pauses to the next hour if LTA's rate limit is hit | a systemd service on Linux (`docs/LINUX_SETUP_FOR_CLAUDE_CODE.md`); on Windows through `01_windows_collector_monitor.ipynb` |
| `analysis/lta_collector.py --mode expressway` | The second collector, with a second key: only the pages that hold the 2,598 expressway links, every 2 minutes, into `data_raw_expressway/`. It catches updates that one fetch can miss, because LTA's pages lag each other | a second systemd service |
| `check.sh`, `02_linux_collector_health.ipynb` | Health checks of both collectors: service, heartbeat, fetches per hour, failures, disk | `./check.sh` |
| `analysis/get_context_data.py` | NEA 5-minute rainfall by date, MOM public holidays, MOE school terms | `python analysis/get_context_data.py` |
| `analysis/00_check_sources.py` | One-off check of every source before collection started | done on 13 and 16 Oct 2026 |
| `upload_raw.sh`, `analysis/archive_raw.py`, `analysis/verify_raw.py` | Nightly archive of the raw files (one file per collector and day, with checksums), and the check of a download | cron on the Linux PC; `verify_raw.py` by hand |
| `analysis/build_data.py` | Raw files to model tables (data version 4). Rebuilds everything from scratch, checks every step, and stops with `CHECK FAILED` if a check fails | through `build_processed.sh` |
| `analysis/data_settings.py` | Every setting of the data pipeline in one place: dates, splits, the label rule, look-backs | read only |
| `analysis/data_steps.py` | The steps of the pipeline as small functions: cleaning, link list, neighbours, joining roads, normal level, labels, inputs | used by `build_data.py` and by the Part 1 notebook |
| `analysis/test_data_steps.py` | 25 tests of the steps on small made-up data with answers worked out by hand | `python analysis/test_data_steps.py -v` |
| `analysis/verify_data.py` | Independent check: recomputes sample rows of the finished tables from the raw files, written from the rules, not from the pipeline code | through `build_processed.sh` |
| `notebooks/part1_data_collection_and_transformation.ipynb` | The walk-through: how the collection went, then every step from the raw files to the model table, each compared with the build's tables. Saved with its outputs | open from `notebooks/`, run all cells |
| `DATA.md` | The data sheet: sources, licence, unit, inclusion rules, how the table is built, quality checks, limitations | read |
| `docs/data_rules.md` | Every rule behind the tables, in words | read |
| `docs/model_data/` | The record of the build: column guide (`README.md`), every check (`build_info.json`), days (`days.csv`), checksums | read |
| `DECISIONS.md` | The dated design and collection decisions | read |

## Parts 2 to 4: how to reproduce

Parts 2 to 4 need the model tables of Part 1 (`data_processed/`).

On a new copy of the repository, run the scripts first: `modelling/run_all.sh` (about 2 hours, 14 GB of memory). The
notebooks check themselves against what the scripts save in `work/`: Part 2 compares its inputs with the scripts'
table, and Part 3 compares its models with the scripts' models. Then open the notebooks from the `notebooks/` folder
with the project's Python.

| Step | What | Time | Reads |
|---|---|---|---|
| Part 2 | `notebooks/part2_eda_and_feature_engineering.ipynb`: the EDA, then the engineered inputs with their checks | 2 min | train and validation days |
| Part 3 | `notebooks/part3_models.ipynb`: baselines, lasso and forest from tuning to the validation week; it stops unless its models equal the frozen ones; then the saved test-week result | about 1 hour, 14 GB of memory | train and validation days |
| Part 4 | `notebooks/part4_summary.ipynb`: the results in one place. It builds the report's tables and figures from the saved result files and fits no model | under a minute | `results/`, and the validation scores written by Part 3 |

The notebooks are the walk-through. The same pipeline as scripts is in `modelling/` (see `modelling/README.md`):
`./run_all.sh` runs the exploration, the inputs, the baselines, both models, the validation week and the freeze,
then a dry run of the test script on the validation week. It writes `results/`, `figures/pipeline/` and `work/`.

On a system without `systemd-run` (macOS, Windows), run the scripts of `run_all.sh` in the same order with plain
`python`.

**The forest's tuning scores are read, not fitted again.** `06_random_forest.py` reads its saved tuning scores from
`results/tables/06_rf_cv_cache.json` and does not fit the grid again. This keeps a new run equal to the frozen run,
including its choice of `max_features` 0.6 (Part 3 notebook, section 5). The Part 3 notebook fits the grid afresh. Delete the
file to tune again with the scripts: the tie rule then picks 0.35, and the numbers after it change a little.

**The test week.** The settings and a hash of every model file were frozen on 25 Nov 2026 (`results/freeze.json`).
The test week was then scored once by `modelling/10_test.py` (`results/tables/10_test.md`). `results/TEST_OPENED.log`
lists every time the test week was read. `DRY_RUN=1` runs the test script on the validation week instead.

**When to run scripts 03 to 09.** They fit the models and write the model files again.
- In a folder that already holds the frozen models (`work/models/`): do not run them. The test script would then stop,
  because the files no longer have the frozen hashes.
- On a new copy of the repository: run them (through `run_all.sh`). They write a new freeze record over
  `results/freeze.json`, with the same settings.

To run the test week again on another computer: fit the models there first (`modelling/run_all.sh`, which writes a new
freeze record), unzip `test_week_build.zip` into `work/data_build/`, then run
`OPEN_TEST_WEEK=yes python modelling/10_test.py`, followed by `11_diagnostics.py`, `12_figures.py` and
`13_leakage_checks.py`. Without the test-week build, scripts 11 and 12 cover the validation week only.

## Parts 2 to 4: the files

| Path | What it holds |
|---|---|
| `notebooks/part2_*.ipynb`, `part3_*.ipynb`, `part4_*.ipynb` | The three walk-through notebooks, saved with their outputs |
| `03_visuals.ipynb` | Maps and time-space diagrams of the raw speed bands, saved with its outputs |
| `modelling/` | The pipeline as numbered scripts (`01_eda.py` to `16_classifiers_and_roc.py`) and its shared code (`settings.py`, `common.py`, `features.py`, `modeldata.py`, `lassofit.py`, `segments.py`, `plotstyle.py`). `modelling/README.md` lists what each script does and which days it reads |
| `results/` | Small result files kept with the code: the freeze records, `TEST_OPENED.log`, and `tables/` (one Markdown and one JSON file per script) |
| `figures/` | Every figure, made by code: `report/` (the report's three figures), `notebooks/` (drawn by the four notebooks), `pipeline/` (drawn by the scripts in `modelling/`) |
| `work/` | Large files rebuilt by the scripts (engineered inputs, fitted models, saved scores). Not in the repository |
| `run_models.py` | The team's first version of the models (25 Nov): the two baselines, a logistic model and a forest on the 53 build inputs, with validation PR-AUC. Kept as it was; the final pipeline is `modelling/` |
| `CONTRIBUTIONS.md` | Who did what [TEAM: to fill in] |

## Collecting

The collector needs no Python packages, only an LTA DataMall key. Create a file named `.Renviron` in the project
folder (the name is a leftover from an early R version; our Python scripts read it). Never commit it.

```
LTA_ACCOUNT_KEY=<LTA DataMall key>
LTA_ACCOUNT_KEY2=<second LTA key, for the expressway collector>
DATA_GOV_KEY=<data.gov.sg key, optional>
HC_PING_URL=<alert URL, optional>
```

LTA cuts a key off after about 4,000 calls in a clock hour, so each collector needs its own key.
