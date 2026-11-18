#!/usr/bin/env bash
# Rebuild the model data from the raw files and share it on Google Drive. Run by hand on the Linux PC.
#   1. get_context_data.py    rainfall for any finished day still missing, calendar
#   2. test_data_steps.py     tests of every step on made-up data; stop if one fails
#   3. build_data.py          raw files -> data_processed/model/ (from scratch, with checks; memory capped
#                             at 14 GB so the collectors on this PC are never short of memory)
#   4. verify_data.py         independent recomputation of sample rows from the raw files; stop on any mismatch
#   5. rclone copy + check    data_processed/model/ -> Drive SLDS_1.3_processed. Nothing on Drive is deleted.
#                             test.parquet and extra/test_full.parquet only with SHARE_TEST=1 (after the freeze)
#   ./build_processed.sh              build, check and upload
#   ./build_processed.sh --no-upload  build and check only
#   BUILD_NOW="YYYY-MM-DD HH:MM" ./build_processed.sh   build as of that time: the same finished days as a build
#                                     made then (e.g. a README-only update; data files come out byte-identical)
# Log: data_processed/build.log. Remote: gdrive:SLDS_1.3_processed unless SLDS_PROCESSED_REMOTE is set.
set -euo pipefail
cd "$(dirname "$0")"
REMOTE=${SLDS_PROCESSED_REMOTE:-gdrive:SLDS_1.3_processed}
PY=.venv/bin/python
mkdir -p data_processed
exec > >(tee -a data_processed/build.log) 2>&1
exec 9>data_processed/.build.lock
flock -n 9 || { echo "another build is running; exiting"; exit 1; }

capped() {  # run with at most 14 GB of memory, if this session can create a systemd scope
  if systemd-run --user --scope -q -p MemoryMax=1G true 2>/dev/null; then
    systemd-run --user --scope -q -p MemoryMax=14G -p MemorySwapMax=1G nice -n 10 "$@"
  else
    echo "WARN: no memory cap (systemd-run --user not available here)"; nice -n 10 "$@"
  fi
}

echo "== $(date '+%F %T') start"
echo "-- get_context_data.py"; nice -n 10 python3 analysis/get_context_data.py
echo "-- test_data_steps.py"; "$PY" analysis/test_data_steps.py
[ -f analysis/verify_data.py ] || { echo "analysis/verify_data.py is missing: nothing is uploaded"; exit 1; }
NOW=(); [ -z "${BUILD_NOW:-}" ] || NOW=(--now "$BUILD_NOW")   # build and check the same days
echo "-- build_data.py${BUILD_NOW:+ (as of $BUILD_NOW)}"; capped "$PY" analysis/build_data.py "${NOW[@]}"
echo "-- verify_data.py"; capped "$PY" analysis/verify_data.py "${NOW[@]}"
if [ "${1:-}" != "--no-upload" ]; then
  echo "-- upload to $REMOTE"
  # the top of the Drive folder holds only README.md, train.parquet, test.parquet and extra/ (team decision 14 Nov)
  other=$(rclone lsf "$REMOTE" | grep -v -x -e 'README.md' -e 'train.parquet' -e 'test.parquet' -e 'extra/' || true)
  [ -z "$other" ] || { echo "Drive top level has other entries; move them to extra/old_versions/ first:"; echo "$other"; exit 1; }
  ex=(); [ "${SHARE_TEST:-0}" = 1 ] || ex=(--exclude "/test.parquet" --exclude "/extra/test_full.parquet")
  rclone copy data_processed/model "$REMOTE" "${ex[@]}" --checksum --retries 5 --stats-one-line --stats 0 -v
  rclone check data_processed/model "$REMOTE" "${ex[@]}" --one-way
  # files on Drive that this build does not make (old versions live in extra/old_versions/ on purpose)
  comm -13 <(cd data_processed/model && find . -type f | sed 's|^\./||' | sort) \
           <(rclone lsf -R --files-only "$REMOTE" | grep -v '^extra/old_versions/' | sort) \
    | grep -v -x -e 'test.parquet' -e 'extra/test_full.parquet' | sed 's/^/WARN: on Drive but not in this build: /' || true
fi
echo "== $(date '+%F %T') OK"
