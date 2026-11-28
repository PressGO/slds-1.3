#!/usr/bin/env bash
# build_test_data.sh - the test-week build: the project's own build program (analysis/build_data.py), as of
# Sat 21 Nov 06:00 (the plan's build time), written ONLY under work/data_build/. Nothing in data_processed/ changes,
# nothing is uploaded. Gated like 10_test.py: needs results/freeze.json and either the plan-freeze git tag or
# OPEN_TEST_WEEK=yes (set it only after the freeze). Every opening adds a line to results/TEST_OPENED.log.
set -euo pipefail
cd "$(dirname "$0")/.."                       # the project folder
[[ -f results/freeze.json ]] || { echo "!! no results/freeze.json: run 07 first"; exit 1; }
if ! git rev-parse -q --verify refs/tags/plan-freeze >/dev/null && [[ "${OPEN_TEST_WEEK:-}" != "yes" ]]; then
  echo "!! the plan-freeze tag does not exist; set OPEN_TEST_WEEK=yes only after the freeze"; exit 1
fi
# The raw data may sit one folder above the project folder (README.md, "Data"); build_data.py reads SLDS_PROJECT_DIR.
if [[ -z "${SLDS_PROJECT_DIR:-}" && ! -d data_raw && -d ../data_raw ]]; then
  SLDS_PROJECT_DIR="$(cd .. && pwd)"; export SLDS_PROJECT_DIR
fi
PY=.venv/bin/python; [[ -x $PY ]] || PY=../.venv/bin/python     # the project's Python (setup_env.sh)
mkdir -p work
echo "$(date -Is)  test week opened (tag: $(git tag -l plan-freeze | tr -d '\n' || true); OPEN_TEST_WEEK=${OPEN_TEST_WEEK:-})" >> results/TEST_OPENED.log
systemd-run --user --scope -q -p MemoryMax=14G -p MemorySwapMax=1G nice -n 10 \
  $PY analysis/build_data.py --now "2026-11-21 06:00" --out-root work/data_build \
  2>&1 | tee work/build_test_data.log
