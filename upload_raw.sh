#!/usr/bin/env bash
# Nightly backup of the raw data to Google Drive (cron, 02:30 SGT). Never deletes or overwrites on Drive.
#   1. get_context_data.py  rainfall for any finished day still missing (yesterday, and earlier failures);
#                           up to RAIN_TRIES (4) tries, RAIN_WAIT (1200 s) apart, if data.gov.sg fails
#   2. archive_raw.py       stage archive_raw/ = the Drive folder: one tar per collector per finished day
#                           (lta_network/, lta_expressway/), nea_rainfall/, calendar/, lta_fetch_logs/,
#                           lta_source_check/, README.txt, MANIFEST.csv, SHA256SUMS.txt
#   3. rclone copy          tars and rainfall days with --immutable (an existing Drive file is never
#                           replaced), then the files that change (fetch logs, calendar), manifest files last
#   4. rclone check         every staged file matches Drive (MD5), else FAILED
# Pings HC_PING_URL3 (Healthchecks "SLDS upload") if it is set in .Renviron. Log: archive_raw/upload.log
# Remote: gdrive:SLDS_1.3_raw unless SLDS_REMOTE is set. Only rclone copy / check are used.
set -uo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
REMOTE=${SLDS_REMOTE:-gdrive:SLDS_1.3_raw}
RC=(rclone --checksum --bwlimit 4M --transfers 4 --retries 5 --low-level-retries 20 --stats-one-line --stats 0 -v)
mkdir -p archive_raw
exec >>archive_raw/upload.log 2>&1
exec 9>archive_raw/.upload.lock
flock -n 9 || { echo "$(date '+%F %T') another upload is running; exiting"; exit 0; }

echo "== $(date '+%F %T') start"
fail=0
step() { echo "-- $*"; nice -n 10 ionice -c3 "$@" || { echo "!! step failed: $*"; fail=1; }; }

command -v rclone >/dev/null || { echo "!! rclone is not installed"; fail=1; }
# data.gov.sg can be down for a while: retry the rainfall step, RAIN_WAIT seconds apart. A day still missing
# after the last try is picked up again the next night (the script downloads every missing day).
for try in $(seq 1 "${RAIN_TRIES:-4}"); do
  echo "-- get_context_data.py (try $try)"
  nice -n 10 python3 analysis/get_context_data.py && break
  if [ "$try" -ge "${RAIN_TRIES:-4}" ]; then echo "!! rainfall still failing after $try tries"; fail=1; break; fi
  echo "   rainfall failed; retrying in ${RAIN_WAIT:-1200} s"; sleep "${RAIN_WAIT:-1200}"
done
step python3 analysis/archive_raw.py
if [ $fail -eq 0 ]; then
  step "${RC[@]}" copy archive_raw "$REMOTE" --immutable \
    --include "/lta_network/*.tar" --include "/lta_expressway/*.tar" --include "/lta_source_check/*.tar" \
    --include "/nea_rainfall/*.jsonl.gz"
  step "${RC[@]}" copy archive_raw "$REMOTE" --include "/lta_fetch_logs/*.csv" --include "/calendar/*.json"
  step "${RC[@]}" copy archive_raw "$REMOTE" --include "/README.txt" --include "/MANIFEST.csv" --include "/SHA256SUMS.txt"
  step rclone check archive_raw "$REMOTE" --one-way --exclude "/upload.log" --exclude "/.upload.lock" --exclude "*.partial"
fi

url=$(grep -m1 '^HC_PING_URL3=' .Renviron 2>/dev/null | cut -d= -f2- | tr -d "\"' \r")
[ -n "$url" ] && curl -fsS -m 10 --retry 3 -o /dev/null "$url$([ $fail -ne 0 ] && echo /fail)"
if [ $fail -eq 0 ]; then echo "== $(date '+%F %T') OK"; else echo "== $(date '+%F %T') FAILED"; fi
exit $fail
