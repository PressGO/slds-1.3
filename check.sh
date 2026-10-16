#!/usr/bin/env bash
# Daily health check for both LTA collectors on the Linux PC. Read-only.
#   lta-collector             whole network + other feeds, key LTA_ACCOUNT_KEY   -> data_raw/
#   lta-collector-expressway  expressway pages only,      key LTA_ACCOUNT_KEY2  -> data_raw_expressway/
cd "$(dirname "$0")"
for pair in "lta-collector:data_raw" "lta-collector-expressway:data_raw_expressway"; do
  svc=${pair%%:*}; dir=${pair#*:}
  echo "== $svc ($dir) =="
  echo "Service: $(systemctl is-active "$svc")"
  [ -f "$dir/collector_status.json" ] || { echo "No status file yet."; echo; continue; }
  echo "Files saved today: $(ls "$dir/speedbands/$(date +%F)" 2>/dev/null | wc -l)"
  python3 - "$dir" <<'PY'
import json, sys, datetime as dt
s = json.load(open(sys.argv[1] + "/collector_status.json"))
beat = dt.datetime.strptime(s["last_heartbeat"], "%Y-%m-%dT%H:%M:%S%z")
age = (dt.datetime.now(dt.timezone.utc) - beat).total_seconds() / 60
print(f"Heartbeat: {age:.1f} min ago ({'OK' if age < 2 else 'PROBLEM'})")
print("Started:", s.get("started"), "| Today:", s.get("today"))
print("Last error:", s.get("last_error"))
PY
  echo "Last hour of speed-band fetches (status counts):"
  awk -F, -v since="\"$(date -d '1 hour ago' +%Y-%m-%dT%H:%M)" 'NR>1 && $1 >= since {print $3}' "$dir/log_speedbands.csv" 2>/dev/null | sort | uniq -c
  echo
done
du -sh data_raw data_raw_expressway 2>/dev/null
sensors 2>/dev/null | grep -iE 'package|tctl|core 0' | head -3
