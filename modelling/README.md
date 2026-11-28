# modelling/: baselines, lasso and random forest

This folder holds the code behind the model results: two baselines (B1 time-of-week rate, B2 last observation), a
lasso logistic regression (M1) and a random forest (M2), as in the proposal. It starts from the model tables of
Part 1 (`data_processed/model/`) and ends with the test-week result.

**The models were frozen on 25 Nov 2026 at 23:46. The test week was run with them on 26 Nov.** The saved results
are in `results/`. After a freeze, do not run scripts 03 to 09 again (see "The test-week guard").

## How to run

Use the project's Python (`setup_env.sh`, `requirements.txt`). Run from this folder:

```
./run_all.sh          # 03, 02, 01, then 04 to 09, then the dry run of 10: about 2 hours
```

Or run one script at a time, under a memory cap:

```
systemd-run --user --scope -q -p MemoryMax=14G nice -n 10 ../.venv/bin/python 03_baselines.py
```

`settings.py` finds the data. It looks for `data_processed/` in `$SLDS_PROJECT_DIR`, then in the project folder,
then one folder above the project folder.

## The scripts

- Train = 16 Oct to 6 Nov (16 weekdays).
- Validation = 10 to 13 Nov (4 weekdays; Mon 9 Nov is a public holiday).
- Test = 16 to 20 Nov (5 weekdays).

The numbers are names. `run_all.sh` gives the order: 03 first (a quick check of the data), then 02, then 01 (it
needs the inputs of 02), then 04 to 09.

| Script | What it does | Days it reads | Time |
|---|---|---|---|
| `01_eda.py` | Exploratory figures and numbers: completeness, recurring and unusual slowdowns, onsets by hour and by road, episode lengths, rain, drift, early signs | train and validation | 2 min |
| `02_features.py` | Builds the engineered inputs: NORM (the normal level ahead) and HOP (links further upstream and downstream). Checks them against the build's own columns and against an independent recomputation | train and validation | 3 min |
| `03_baselines.py` | B1 and B2. Chooses B1's weight m by forward validation. Stops if the baseline numbers of 18 Nov do not come out again | train to fit; validation to score | 10 s |
| `04_screen_features.py` | Decides which input groups each model keeps. The rule is fixed in `settings.py` before the run | train only | 19 min |
| `05_lasso.py` | M1. The penalty is chosen on two forward windows inside the train days. Final fit on all train days | train to fit; validation to score | 7 min |
| `06_random_forest.py` | M2. `max_features` and the leaf size are chosen on the same two windows. Final fit with 400 trees | train to fit; validation to score | 25 min |
| `07_validate_and_freeze.py` | Validation week: picks the final model, fits the calibration, sets the alert share. Then writes `results/freeze.json` with the hash of every model file | validation (saved scores) | 3 min |
| `08_secondary.py --family base`, `rf`, `lasso` | Secondary analyses with the frozen settings: horizons of 5, 10 and 30 minutes; inputs left out; the normal level without the row's own day | train to fit; validation to score | 1, 48 and 6 min |
| `09_segments.py` | 1 km segments: build, checks, and the same models | train and validation | 1 min |
| `10_test.py` | The test run with everything frozen. Gated (see below). `DRY_RUN=1` runs the same code on the validation week | test; with `DRY_RUN=1` only validation | 9 min (dry run 6 min) |
| `11_diagnostics.py` | Which lasso inputs are stable (day bootstrap). Which onsets are caught and which are missed. Incidents are used only to interpret, never as an input | train and validation; the test week once `10` has run | 5 min |
| `12_figures.py` | The result figures (precision-recall curves, calibration, intervals, horizons), redrawn from saved scores. No model is fitted. The report itself uses `figures/report/`, drawn by the Part 2 and Part 4 notebooks | saved validation scores; saved test scores once `10` has run | under 1 min |
| `13_leakage_checks.py` | Checks that no step uses information it should not have: the days stay apart, every input is known at time t, HIST leaves the row's own day out | train and validation; of the test week only the dates of the saved scores | 10 min |
| `14_validation_windows.py` | Course tool: forward validation by windows. The two frozen windows against six windows that add 2 days at a time, for the lasso penalty and the forest settings | train only | about 1 h 40 min |
| `15_tree_and_importance.py` | Course tools: one decision tree pruned by cost-complexity; out-of-bag error; permutation and impurity importance; lasso odds ratios | train and validation | 50 min |
| `16_classifiers_and_roc.py` | Course tools: deviance and AIC; ridge and elastic net; LDA and QDA; ROC, AUC and confusion matrices; thresholds from unequal costs | train and validation | 10 min |
| `check_lassofit.py` | Our lasso solver against scikit-learn's | train days 16 to 23 Oct | 1.5 h |

Scripts 14 to 16 are supporting checks. They change no frozen file. Run 14 and 15 before 16.

Shared code:

| File | What it holds |
|---|---|
| `settings.py` | every setting in one place: file locations, dates, grids, seeds |
| `common.py` | loading with the test-week guard, PR-AUC, alerts at a share, the day-block bootstrap |
| `features.py` | the engineered inputs (NORM, HOP) |
| `modeldata.py` | model rows, input groups, the HIST input, fitting helpers |
| `lassofit.py` | the lasso solver (the glmnet algorithm) |
| `segments.py` | the 1 km segments |
| `plotstyle.py` | one look for every figure |

## The test-week guard

- **Before the freeze, nothing after 13 Nov is read.** Every loader stops if it sees a later row
  (`assert_closed` in `common.py`).
- **The freeze.** `07` writes `results/freeze.json`: the settings, and the sha256 of every model file. `08` and `09`
  add their own records. `07` stops if a test-week build exists already.
- **The gate of `10_test.py`.** It runs only when both are true:
  1. every frozen model file still has its recorded hash;
  2. the git tag `plan-freeze` exists, or `OPEN_TEST_WEEK=yes` is set. Set it only after the freeze.
- **The test-week build.** `build_test_data.sh` has the same gate. It writes only to `work/data_build/`, and it adds
  a line to `results/TEST_OPENED.log` each time.
- **The dry run.** `DRY_RUN=1 python 10_test.py` runs the test code on the validation week. It must give the saved
  validation scores again (largest gap below 1e-9), or it stops. It never reads the test week.
- **After a freeze, do not run 03 to 09 again.** They write the model files again. Even the same rows in another
  order change a file's hash, and then `10_test.py` stops. (`03` does this: its two B1 tables come out in another
  row order.) For a new freeze, run everything from `03` again; `07` then writes a new record.

## Where things are

| Folder | What is in it | In the repository? |
|---|---|---|
| `results/` | `freeze.json`, `freeze_secondary_*.json`, `freeze_segments.json`: the freeze records, never edited | yes |
| `results/tables/` | one `.md` or `.json` per script, named after the script. `10_test.md` is the test-week result; `dry_10_test.md` is the dry run | yes |
| `figures/pipeline/` | the figures the scripts draw: `eda_*`, `m1_*`, `m2_*`, `val_*`, `test_*`, `dry_test_*`, `diag_*`, `fig_*`, `14_*`, `15_*`, `16_*` | yes |
| `work/features/` | the engineered inputs (`fe_trainval.parquet`, `fe_test.parquet`), the ring pairs, the segment tables | no |
| `work/models/` | the fitted models: the B1 tables, `lasso.pkl`, `rf.pkl`, `sec_*.pkl`, `seg_*.pkl` (2.7 GB) | no |
| `work/preds/` | the saved scores: `val_*.parquet`, `test_scores.parquet`, `dry_test_scores.parquet` | no |
| `work/data_build/` | the test-week build | no |
| `work/data_dryrun/` | the validation week dressed as a test build, made by the dry run | no |

`work/` is large and is never committed (`work/.gitignore`). The scripts make it again from the model tables.

## Notes

- `06_random_forest.py` reads its saved tuning scores from `results/tables/06_rf_cv_cache.json` and does not fit
  the grid again. This keeps a new run equal to the frozen run, including its choice of `max_features` 0.6 (0.35 and
  0.6 tie; see the Part 3 notebook, section 5). The Part 3 notebook fits the grid afresh. Delete the file to tune again: the
  tie rule then picks 0.35.
- `run_all.sh` uses `systemd-run` to cap the memory (Linux). On another system, run the scripts in the same order
  with plain `python`.
- The model files were saved with scikit-learn 1.9.1. Another version may not open them. In that case run the
  scripts again.
- A forest fitted with several threads has the same trees each time, but its scores can differ in the last digit.
  That can move a PR-AUC in about the 6th decimal.
- In `results/tables/14_validation_windows.json`, twelve forest settings of the two-window scheme have no pooled
  score. The saved run took their window scores from the same forests fitted earlier. A new run of the script fits
  them itself and fills the pooled scores in.
