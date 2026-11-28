#!/usr/bin/env bash
# run_all.sh - the modelling pipeline, from the model tables (data version 4) to the frozen models.
# The test week is NOT run from here: it needs the plan-freeze git tag or OPEN_TEST_WEEK=yes (see the end).
# Scripts 03-09 write the models and the freeze records again: run them only for a new freeze (README.md).
set -euo pipefail
cd "$(dirname "$0")"
PY=../.venv/bin/python; [[ -x $PY ]] || PY=../../.venv/bin/python     # the project's Python (setup_env.sh)
cap() { systemd-run --user --scope -q -p MemoryMax=14G -p MemorySwapMax=1G nice -n 10 "$@"; }

cap $PY 03_baselines.py                 # B1, B2; the baseline numbers of 18 Nov are asserted
cap $PY 02_features.py                  # NORM and HOP inputs, with independent checks
cap $PY 01_eda.py                       # exploratory figures (train and validation days)
cap $PY 04_screen_features.py           # which input groups each model family keeps (forward-chaining)
cap $PY 05_lasso.py                     # M1 (IRLS + coordinate descent, lassofit.py)
cap $PY 06_random_forest.py             # M2 (results/tables/06_rf_cv_cache.json skips grid points already computed)
cap $PY 07_validate_and_freeze.py       # validation: final model, calibration, alert share; writes results/freeze.json
cap $PY 08_secondary.py --family base   # horizons for B1 / B2
cap $PY 08_secondary.py --family rf     # horizons, input ablations, leave-own-day-out (forest)
cap $PY 08_secondary.py --family lasso  # the same for the lasso
cap $PY 09_segments.py                  # 1 km segments: build, checks, models
systemd-run --user --scope -q -p MemoryMax=14G -E DRY_RUN=1 nice -n 10 $PY 10_test.py   # dry run on validation
# optional, about 1.5 h (scikit-learn's saga is the slow part): cap $PY check_lassofit.py
# optional supporting checks on the train and validation days (about 2.5 h together; no frozen file changes):
#   cap $PY 14_validation_windows.py; cap $PY 15_tree_and_importance.py; cap $PY 16_classifiers_and_roc.py
echo "Frozen. To open the test week (only with the plan-freeze git tag, or OPEN_TEST_WEEK=yes after the freeze):"
echo "  OPEN_TEST_WEEK=yes ./build_test_data.sh"
echo "  systemd-run --user --scope -q -p MemoryMax=14G -E OPEN_TEST_WEEK=yes nice -n 10 $PY 10_test.py"
echo "  then: 11_diagnostics.py, 12_figures.py and 13_leakage_checks.py (same memory cap)"
