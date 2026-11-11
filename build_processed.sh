#!/usr/bin/env bash
# Rebuild the processed data from data_raw*/ and share the modelling tables on Google Drive. Run by hand.
#   1. get_context_data.py        rainfall for any finished day still missing, calendar
#   2. 04_process.ipynb           raw -> data_processed/ (registry, panel, analysis_panel, incidents), run
#                                 headless; a day is redone whenever its inputs are newer than its output
#   3. build_model_data.py        data_processed/ -> data_processed/model/ (population, norm, labels, splits),
#                                 rebuilt from scratch each run
#   4. rclone copy + check        data_processed/model/ -> Drive SLDS_1.3_processed (changed files are
#                                 replaced, nothing is deleted); test_locked/ only with SHARE_TEST=1
#   ./build_processed.sh              build and upload
#   ./build_processed.sh --no-upload  build only
# Log: data_processed/build.log. Remote: gdrive:SLDS_1.3_processed unless SLDS_PROCESSED_REMOTE is set.
set -euo pipefail
cd "$(dirname "$0")"
REMOTE=${SLDS_PROCESSED_REMOTE:-gdrive:SLDS_1.3_processed}
PY=.venv/bin/python
mkdir -p data_processed
exec > >(tee -a data_processed/build.log) 2>&1
exec 9>data_processed/.build.lock
flock -n 9 || { echo "another build is running; exiting"; exit 1; }

echo "== $(date '+%F %T') start"
echo "-- get_context_data.py"; nice -n 10 python3 analysis/get_context_data.py
echo "-- 04_process.ipynb"
run=$(mktemp -d)
trap 'rm -rf "$run"' EXIT
nice -n 10 .venv/bin/jupyter nbconvert --to notebook --execute --ExecutePreprocessor.timeout=-1 \
  04_process.ipynb --output-dir "$run" --output 04_process_run.ipynb
echo "-- build_model_data.py"; nice -n 10 "$PY" analysis/build_model_data.py
if [ "${1:-}" != "--no-upload" ]; then
  echo "-- upload to $REMOTE"
  # test_locked/ stays on this PC until the plan is frozen; set SHARE_TEST=1 to upload it at test time
  ex=(); [ "${SHARE_TEST:-0}" = 1 ] || ex=(--exclude "/test_locked/**")
  rclone copy data_processed/model "$REMOTE" "${ex[@]}" --checksum --retries 5 --stats-one-line --stats 0 -v
  rclone check data_processed/model "$REMOTE" "${ex[@]}" --one-way
fi
echo "== $(date '+%F %T') OK"
