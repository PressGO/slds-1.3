"""get_context_data.py - SLDS 42.510 project 1.3: rainfall (NEA) and calendar (MOM, MOE, LTA F1) data.

Run any time; it only downloads what is missing. Standard library only (Python 3.9+).

    python analysis/get_context_data.py                      # 13 Oct 2026 up to yesterday
    python analysis/get_context_data.py --start 2026-10-13 --end 2026-11-27

1. NEA rainfall (data.gov.sg real-time API, 5-minute totals per station)
   https://api-open.data.gov.sg/v2/real-time/api/rainfall?date=YYYY-MM-DD (+ paginationToken)
   - Raw pages per day:  data_raw/nea_rainfall/rain_YYYYMMDD.jsonl.gz  (days already complete are skipped)
   - Tidy table:         data_processed/rainfall_5min.csv.gz   timestamp, station_id, rain_mm
   - Stations:           data_processed/rain_stations.csv      station_id, name, lat, lon, days_seen
   Rate limit without a key: 6 calls per 10 s, so the script waits 2 s between calls and backs off on HTTP 429.
   Optional key (higher limit): DATAGOVSG_API_KEY=... in .Renviron.

2. MOM public holidays 2026 (data.gov.sg dataset d_149b61ad0a22f61c09dc80f2df5bbec8)
   - Raw: data_raw/calendar/mom_public_holidays_2026.json

3. MOE school calendar 2026 and LTA F1 road closures: no API, so the dates are typed in below from
   the official pages (sources and access dates in MANUAL_SOURCES) and written with the holidays to
   - data_processed/calendar_2026.csv   one row per date, 1 Oct - 31 Dec 2026

All data: Singapore Open Data Licence v1.0 (NEA, MOM via data.gov.sg); MOE and LTA dates cited as facts.
AI disclosure: drafted with Claude (Anthropic) on 14 Oct 2026; log in AI_USE.md.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

RAIN_URL = "https://api-open.data.gov.sg/v2/real-time/api/rainfall"
HOLIDAY_URL = "https://data.gov.sg/api/action/datastore_search"
HOLIDAY_RESOURCE = "d_149b61ad0a22f61c09dc80f2df5bbec8"
PAUSE_S = 2.0          # between data.gov.sg calls (6 per 10 s without a key)
TIMEOUT_S = 60
TRIES = 5
# data.gov.sg's Cloudflare blocks Python's default "Python-urllib" agent (HTTP 403, error 1010)
USER_AGENT = "slds-1.3-context-data/1.0 (SUTD 42.510 course project)"
SGT = timezone(timedelta(hours=8))

# Typed in from official sources (no API). Update if the sources change.
MANUAL_SOURCES = {
    "moe": "MOE press release 'School Terms and Holidays for 2026', https://www.moe.gov.sg/news/press-releases/20250730-school-terms-and-holidays-for-2026 (accessed 13 Oct 2026)",
    "f1": "LTA OneMotoring 'Formula 1 Singapore Airlines Singapore Grand Prix 2026', https://onemotoring.lta.gov.sg/content/onemotoring/home/driving/formula-1-singapore-airlines-singapore-grand-prix-2026.html (accessed 10 Oct 2026)",
}
MOE_PERIODS = [  # primary and secondary schools, 2026
    ("vacation_term3_4", date(2026, 9, 5), date(2026, 9, 13)),
    ("term4", date(2026, 9, 14), date(2026, 11, 20)),
    ("vacation_year_end", date(2026, 11, 21), date(2026, 12, 31)),
]
OLEVEL_VENUE_LAST_DAY = date(2026, 10, 23)   # schools used as O-Level written-exam venues end term
JC1_TERM4_LAST_DAY = date(2026, 11, 27)      # JC Year 1 / MI Year 1 Term IV ends
F1_CLOSURE = (datetime(2026, 10, 7, 0, 1), datetime(2026, 10, 13, 5, 30))   # Marina Centre / Padang roads
CAL_START, CAL_END = date(2026, 10, 1), date(2026, 12, 31)


def project_dir() -> Path:
    env = os.environ.get("SLDS_PROJECT_DIR")
    return Path(env).resolve() if env else Path(__file__).resolve().parent.parent


def read_renviron(proj: Path, name: str) -> str:
    renv = proj / ".Renviron"
    if renv.exists():
        for line in renv.read_text(encoding="utf-8-sig").splitlines():
            if line.strip().startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get(name, "").strip()


def http_get(url: str, headers: dict[str, str]) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **headers})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


def get_json(url: str, headers: dict[str, str], getter: Callable = http_get,
             sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """GET with retries on connection errors, 429 and 5xx. Raises after the last attempt."""
    last = ""
    for attempt in range(1, TRIES + 1):
        try:
            status, body = getter(url, headers)
        except Exception as e:
            status, body = None, f"{type(e).__name__}: {e}"
        if status == 200:
            return {"body": body, "json": json.loads(body)}
        last = f"HTTP {status}: {' '.join(str(body).split())[:200]}"
        if status is not None and status not in (429,) and status < 500:
            break
        sleep(15 if status == 429 else 5 * attempt)
    raise RuntimeError(f"{url} failed: {last}")


def write_gz_lines(lines: list[str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".partial")
    with gzip.open(tmp, "wt", encoding="utf-8", newline="\n") as f:
        for line in lines:
            f.write(line + "\n")
    os.replace(tmp, path)


# ---- NEA rainfall ---------------------------------------------------------------------

def download_rain_day(day: date, headers: dict[str, str], getter: Callable = http_get,
                      sleep: Callable[[float], None] = time.sleep) -> list[str]:
    """All pages for one day as raw JSON lines."""
    lines, token, page = [], None, 1
    while True:
        q = {"date": day.isoformat()}
        if token:
            q["paginationToken"] = token
        url = RAIN_URL + "?" + urllib.parse.urlencode(q)
        res = get_json(url, headers, getter, sleep)
        js = res["json"]
        if js.get("code", 0) != 0:
            raise RuntimeError(f"rainfall {day}: API code {js.get('code')} {js.get('errorMsg')}")
        lines.append(json.dumps({"endpoint": "rainfall", "date": day.isoformat(), "page": page,
                                 "retrieved_at": datetime.now(SGT).strftime("%Y-%m-%dT%H:%M:%S%z"),
                                 "body": res["body"]}))
        token = (js.get("data") or {}).get("paginationToken")
        sleep(PAUSE_S)
        if not token:
            return lines
        page += 1


def rain_day_rows(path: Path) -> tuple[list[tuple[str, str, float | None]], dict[str, dict]]:
    rows, stations = [], {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            data = json.loads(json.loads(line)["body"]).get("data") or {}
            for s in data.get("stations") or []:
                loc = s.get("location") or {}
                stations[s["id"]] = {"name": s.get("name"), "lat": loc.get("latitude"), "lon": loc.get("longitude")}
            for r in data.get("readings") or []:
                for v in r.get("data") or []:
                    rows.append((r["timestamp"], v.get("stationId"), v.get("value")))
    return rows, stations


def update_rainfall(proj: Path, start: date, end: date, headers: dict[str, str],
                    getter: Callable = http_get, sleep: Callable[[float], None] = time.sleep) -> None:
    raw_dir = proj / "data_raw" / "nea_rainfall"
    today = datetime.now(SGT).date()
    d = start
    while d <= end:
        path = raw_dir / f"rain_{d:%Y%m%d}.jsonl.gz"
        if d >= today:
            print(f"rainfall {d}: skipped (day not finished)")
        elif path.exists():
            print(f"rainfall {d}: already downloaded")
        else:
            try:
                lines = download_rain_day(d, headers, getter, sleep)
                write_gz_lines(lines, path)
                n = len(rain_day_rows(path)[0])
                print(f"rainfall {d}: {len(lines)} page(s), {n:,} readings")
            except Exception as e:
                print(f"rainfall {d}: FAILED ({e}); rerun the script later to retry")
        d += timedelta(days=1)

    # Rebuild tidy outputs from every raw day file.
    all_rows, station_info, station_days = [], {}, {}
    for path in sorted(raw_dir.glob("rain_*.jsonl.gz")):
        rows, stations = rain_day_rows(path)
        all_rows.extend(rows)
        station_info.update(stations)
        for sid in {r[1] for r in rows}:
            station_days[sid] = station_days.get(sid, 0) + 1
    out_dir = proj / "data_processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    seen, tidy = set(), []
    for ts, sid, val in sorted(all_rows, key=lambda r: (r[0], r[1] or "")):
        if (ts, sid) in seen:      # pages can overlap: keep one reading per station and time
            continue
        seen.add((ts, sid))
        tidy.append(f"{ts},{sid},{'' if val is None else val}")
    write_gz_lines(["timestamp,station_id,rain_mm"] + tidy, out_dir / "rainfall_5min.csv.gz")
    with open(out_dir / "rain_stations.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["station_id", "name", "lat", "lon", "days_seen"])
        for sid in sorted(station_info):
            s = station_info[sid]
            w.writerow([sid, s["name"], s["lat"], s["lon"], station_days.get(sid, 0)])
    print(f"rainfall tidy table: {len(tidy):,} readings from {len(station_info)} stations")


# ---- Calendar -------------------------------------------------------------------------

def update_calendar(proj: Path, headers: dict[str, str], getter: Callable = http_get,
                    sleep: Callable[[float], None] = time.sleep) -> None:
    raw_path = proj / "data_raw" / "calendar" / "mom_public_holidays_2026.json"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    url = HOLIDAY_URL + "?" + urllib.parse.urlencode({"resource_id": HOLIDAY_RESOURCE, "limit": 100})
    try:
        res = get_json(url, headers, getter, sleep)
        raw_path.write_text(res["body"], encoding="utf-8")
        print("MOM public holidays: downloaded")
    except Exception as e:
        if not raw_path.exists():
            raise
        print(f"MOM public holidays: download failed ({e}); using the saved copy")
    records = json.loads(raw_path.read_text(encoding="utf-8"))["result"]["records"]
    holidays = {r["date"]: r["holiday"] for r in records}

    out = proj / "data_processed" / "calendar_2026.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "weekday", "is_weekend", "is_public_holiday", "holiday_name", "daytype",
                    "school_period", "olevel_venue_schools_ended", "jc1_in_term", "f1_closure_day"])
        d = CAL_START
        while d <= CAL_END:
            ph = d.isoformat() in holidays
            wd = d.weekday()
            daytype = "Sun/PH" if (ph or wd == 6) else "Sat" if wd == 5 else "Fri" if wd == 4 else "Mon-Thu"
            period = next((p for p, a, b in MOE_PERIODS if a <= d <= b), "")
            f1 = F1_CLOSURE[0].date() <= d <= F1_CLOSURE[1].date()
            w.writerow([d.isoformat(), d.strftime("%a"), wd >= 5, ph, holidays.get(d.isoformat(), ""), daytype,
                        period, d > OLEVEL_VENUE_LAST_DAY, d <= JC1_TERM4_LAST_DAY, f1])
            d += timedelta(days=1)
    (proj / "data_processed" / "calendar_sources.txt").write_text(
        "calendar_2026.csv sources\n"
        f"- Public holidays: MOM via data.gov.sg dataset {HOLIDAY_RESOURCE} (Singapore Open Data Licence v1.0)\n"
        f"- School periods: {MANUAL_SOURCES['moe']}\n- F1 closure: {MANUAL_SOURCES['f1']}\n", encoding="utf-8")
    print(f"calendar: {out} ({(CAL_END - CAL_START).days + 1} days, {len(holidays)} public holidays in 2026)")


def main(argv: list[str] | None = None) -> int:
    yesterday = datetime.now(SGT).date() - timedelta(days=1)
    ap = argparse.ArgumentParser(description="NEA rainfall + calendar data for SLDS project 1.3")
    ap.add_argument("--start", default="2026-10-13", help="first rainfall day (YYYY-MM-DD)")
    ap.add_argument("--end", default=yesterday.isoformat(), help="last rainfall day (YYYY-MM-DD)")
    ap.add_argument("--skip-rain", action="store_true")
    ap.add_argument("--skip-calendar", action="store_true")
    args = ap.parse_args(argv)
    proj = project_dir()
    key = read_renviron(proj, "DATAGOVSG_API_KEY")
    headers = {"accept": "application/json", **({"x-api-key": key} if key else {})}
    if not args.skip_calendar:
        update_calendar(proj, headers)
    if not args.skip_rain:
        update_rainfall(proj, date.fromisoformat(args.start), date.fromisoformat(args.end), headers)
    return 0


if __name__ == "__main__":
    sys.exit(main())
