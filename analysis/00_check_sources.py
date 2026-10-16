"""00_check_sources.py - SLDS 42.510 project 1.3: one-off check of the planned data sources.

Python port of 00_check_sources.R: same requests, same checks, same outputs.
Standard library only (Python 3.9+), like the collector.

For each source the script makes a few requests, saves every raw response
(gzipped) with retrieval metadata, and prints data-quality checks you can quote
as "evidence that the data are accessible" (Brief §6.1). It is a check, not the
collector. Run it once now, and again if an endpoint changes.

Setup
  Keys are read from .Renviron in the project folder (the same file the R scripts
  and the collector use), else from environment variables of the same name:
    LTA_ACCOUNT_KEY=<your LTA DataMall AccountKey>
    DATAGOVSG_API_KEY=<optional data.gov.sg key; raises rate limits>

Run from the project folder
  python3 analysis/00_check_sources.py      (or 00_check_sources_python.ipynb)

Outputs in data_raw/source_check/ (new files each run, nothing overwritten)
  raw/<source>/<run>_p<page>.json.gz   raw response bodies
  request_log_<run>.csv                one row per HTTP request
  summary_<run>.txt                    the checks printed at the end

Keys travel only in request headers. If a response echoes a key (LTA's
rate-limit errors do), it is replaced by <KEY> before anything is saved or printed.

Assumptions to confirm against LTA's API User Guide (the script reports any
mismatch instead of failing):
  - speed-band endpoint "v4/TrafficSpeedBands" and 500-record pages;
  - field names in EXPECTED_* below.

AI disclosure: ported from the R version with Claude (Anthropic) on 16 Oct 2026.
Log it in AI_USE.md and read every line before relying on it (Brief §5).
"""

# ---- Settings and shared helpers ----------------------------------------------------------

from __future__ import annotations

import csv
import gzip
import json
import os
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

SGT = timezone(timedelta(hours=8))  # Singapore: no daylight saving
sgt_today = datetime.now(SGT).date()

CONFIG = {
    "out_dir": Path("data_raw") / "source_check",
    "lta_base": "https://datamall2.mytransport.sg/ltaodataservice/",
    "lta_speed_path": "v4/TrafficSpeedBands",
    "lta_incidents_path": "TrafficIncidents",
    "rain_url": "https://api-open.data.gov.sg/v2/real-time/api/rainfall",
    # Yesterday tests day-level retrieval. 30 days back tests whether rainfall
    # for the whole study window can be backfilled after collection ends.
    "rain_past_dates": [(sgt_today - timedelta(days=d)).isoformat() for d in (1, 30)],
    "holiday_url": "https://data.gov.sg/api/action/datastore_search",
    "holiday_resource_id": "d_149b61ad0a22f61c09dc80f2df5bbec8",  # MOM "Public Holidays for 2026"
    "holiday_window": ("2026-10-01", "2026-12-31"),
    "lta_page_limit": 500,  # LTA returns at most this many records per call
    "max_pages": 400,       # safety stop for paging loops
    "pause_seconds": 2,     # data.gov.sg real-time API: 6 calls per 10 s without a key
    "timeout_seconds": 60,
    # data.gov.sg's Cloudflare blocks Python's default "Python-urllib" agent (HTTP 403, error 1010)
    "user_agent": "slds-1.3-source-check/1.0 (SUTD 42.510 course project)",
}

EXPECTED_SPEED_FIELDS = ["LinkID", "RoadName", "RoadCategory", "SpeedBand",
                         "MinimumSpeed", "MaximumSpeed",
                         "StartLon", "StartLat", "EndLon", "EndLat"]
EXPECTED_INCIDENT_FIELDS = ["Type", "Latitude", "Longitude", "Message"]

LOG_FIELDS = ["source", "run", "page", "retrieved_at_sgt", "url", "query", "http_status",
              "elapsed_s", "bytes", "server_date", "last_modified", "raw_file", "error"]
LOG: list[dict] = []
SECRETS: list[str] = []  # keys to mask in anything saved or printed


def now_sgt() -> str:
    t = datetime.now(SGT)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}" + t.strftime("%z")


def run_stamp() -> str:
    t = datetime.now(SGT)
    return t.strftime("%Y%m%d_%H%M%S.") + f"{t.microsecond // 1000:03d}"


def read_setting(name: str, proj: Path = Path(".")) -> str:
    """NAME=value from .Renviron in the project folder, else the environment variable NAME."""
    renv = proj / ".Renviron"
    if renv.exists():
        for line in renv.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get(name, "").strip()


def mask(text: str) -> str:
    for s in SECRETS:
        text = text.replace(s, "<KEY>")
    return text


def squish(x: Any) -> str:
    return " ".join(str(x).split())


# ---- HTTP requests and logging ---------------------------------------------------------

def http_get(url: str, headers: dict, query: dict) -> dict:
    """The only function that touches the network. HTTP error statuses are
    returned rather than raised, so every request can be logged."""
    if query:
        url = url + "?" + urllib.parse.urlencode(query)
    req = urllib.request.Request(url, headers={"User-Agent": CONFIG["user_agent"], **headers})
    t0 = time.time()
    try:
        resp = urllib.request.urlopen(req, timeout=CONFIG["timeout_seconds"])
    except urllib.error.HTTPError as e:
        resp = e
    with resp:
        body = resp.read()
        return {"status": resp.status, "body_raw": body,
                "elapsed": time.time() - t0, "server_date": resp.headers.get("date"),
                "last_modified": resp.headers.get("last-modified")}


def query_string(query: dict) -> str:
    return "&".join(f"{k}={v}" for k, v in query.items())


def logged_get(source: str, url: str, headers: Optional[dict] = None, query: Optional[dict] = None,
               page: int = 1, run: Optional[str] = None) -> dict:
    """Performs one request, saves the raw body and appends a row to the log.
    Headers (which carry the keys) are never written anywhere."""
    headers, query, run = headers or {}, query or {}, run or run_stamp()
    retrieved_at = now_sgt()
    try:
        res = http_get(url, headers, query)
        res["error"] = None
    except Exception as e:  # connection errors, timeouts, DNS
        res = {"status": None, "body_raw": b"", "elapsed": None, "server_date": None,
               "last_modified": None, "error": mask(f"{type(e).__name__}: {e}")}
    for s in SECRETS:
        res["body_raw"] = res["body_raw"].replace(s.encode(), b"<KEY>")
    res["body"] = None
    raw_file = None
    if res["body_raw"]:
        res["body"] = res["body_raw"].decode("utf-8", errors="replace")
        d = CONFIG["out_dir"] / "raw" / source
        d.mkdir(parents=True, exist_ok=True)
        raw_file = d / f"{run}_p{page:03d}.json.gz"
        with gzip.open(raw_file, "wb") as f:
            f.write(res["body_raw"])
    LOG.append({
        "source": source, "run": run, "page": page, "retrieved_at_sgt": retrieved_at,
        "url": url, "query": query_string(query),
        "http_status": res["status"],
        "elapsed_s": None if res["elapsed"] is None else round(res["elapsed"], 3),
        "bytes": len(res["body_raw"]), "server_date": res["server_date"],
        "last_modified": res["last_modified"], "raw_file": raw_file,
        "error": None if res["error"] is None else squish(res["error"]),
    })
    return res


def parse_json(res: dict) -> Any:
    try:
        return json.loads(res["body"])
    except (TypeError, ValueError):
        return None


def is_ok(res: dict) -> bool:
    return res["status"] == 200


HINTS = {
    400: "bad request: check the query parameters",
    401: "unauthorised: key missing, wrong, or not yet active",
    403: "forbidden: key not accepted for this endpoint",
    404: "not found: check the endpoint path against the current API guide",
    429: "rate limited: wait a minute and rerun, or add an API key",
}


def describe_failure(res: dict, what: str) -> str:
    if res["status"] is None:
        hint = "no response: check the connection; a restricted network may block the host"
    else:
        hint = HINTS.get(res["status"], "unexpected status")
    detail = res["body"] if res["body"] is not None else (res["error"] or "")
    detail = squish(detail)[:200]
    return f"FAILED {what}: HTTP {res['status'] or 'none'} ({hint}). {detail}"


# ---- Record helpers ----------------------------------------------------------------------
# A "table" here is a list of flat dicts (one per record), the Python stand-in for R's data frames.

def flatten(rec: dict, prefix: str = "") -> dict:
    """Nested objects become dotted columns, like jsonlite::flatten."""
    out = {}
    for k, v in rec.items():
        if isinstance(v, dict):
            out.update(flatten(v, f"{prefix}{k}."))
        else:
            out[prefix + k] = v
    return out


def columns(rows: list[dict]) -> list[str]:
    return list(dict.fromkeys(k for r in rows for k in r))


def fmt_num(x: Optional[float]) -> str:
    return "NA" if x is None else f"{x:g}"


def to_num(x: Any) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def to_int(x: Any) -> Optional[int]:
    v = to_num(x)
    return None if v is None else int(v)


def count_string(values: list) -> str:
    tab = Counter("NA" if v is None else str(v) for v in values)
    return "  ".join(f"{k}={n}" for k, n in sorted(tab.items()))


def field_check(found: list[str], expected: list[str]) -> list[str]:
    missing = [c for c in expected if c not in found]
    extra = [c for c in found if c not in expected]
    return [f"Expected fields missing: {', '.join(missing) or 'none'}",
            f"Fields not in the expected list: {', '.join(extra) or 'none'}"]


def missing_check(rows: list[dict]) -> str:
    bad = {}
    for c in columns(rows):
        n = sum(1 for r in rows if r.get(c) is None or (isinstance(r.get(c), str) and not r[c].strip()))
        if n:
            bad[c] = n
    if not bad:
        return "Missing or blank values: none"
    return "Missing or blank values: " + "  ".join(f"{k}={n}" for k, n in bad.items())


def parse_ts(x: str) -> Optional[datetime]:
    """'2026-10-09T23:55:00+08:00' -> datetime in Singapore time."""
    try:
        return datetime.fromisoformat(x).astimezone(SGT)
    except (TypeError, ValueError):
        return None


# ---- LTA DataMall: speed bands and incidents ---------------------------------------------

def first_record_id(value: list[dict]) -> str:
    """Identifies a page by its first record, to catch an endpoint that ignores $skip."""
    first = value[0]
    if "LinkID" in first:
        return str(first["LinkID"])
    return json.dumps(first, sort_keys=True)


def fetch_lta_all(source: str, path: str, key: str) -> dict:
    """Pages through an endpoint with $skip. A page shorter than the page limit,
    an empty page, or a page that repeats the previous one ends the loop."""
    base = CONFIG["lta_base"] + path
    headers = {"AccountKey": key, "accept": "application/json"}
    run = run_stamp()
    rows: list[dict] = []
    page, skip = 1, 0
    first_page_size = None
    prev_id = None
    top_keys = None
    hit_cap = repeated = False
    t0 = time.time()
    while True:
        url = base if skip == 0 else f"{base}?$skip={skip}"
        res = logged_get(source, url, headers, page=page, run=run)
        if not is_ok(res):
            return {"ok": False, "message": describe_failure(res, f"{source} request {page}")}
        js = parse_json(res)
        if not isinstance(js, dict):
            return {"ok": False, "message": f"FAILED {source} request {page}: response is not valid JSON"}
        top_keys = top_keys or list(js)
        value = js.get("value") or []
        n = len(value)
        if n == 0:
            break
        rid = first_record_id(value)
        if rid == prev_id:
            repeated = True
            break
        prev_id = rid
        rows.extend(flatten(r) for r in value)
        if first_page_size is None:
            first_page_size = n
        if n < CONFIG["lta_page_limit"]:
            break
        if page >= CONFIG["max_pages"]:
            hit_cap = True
            break
        skip += n
        page += 1
    return {"ok": True, "data": rows, "requests": page, "first_page_size": first_page_size,
            "elapsed": time.time() - t0, "top_keys": top_keys or [], "hit_cap": hit_cap,
            "repeated": repeated}


def paging_lines(r: dict) -> list[str]:
    out = [f"Response keys: {', '.join(r['top_keys'])}",
           f"Records: {len(r['data'])} from {r['requests']} request(s); first page "
           f"{r['first_page_size'] if r['first_page_size'] is not None else 'NA'} records; "
           f"paging took {r['elapsed']:.1f} s"]
    if r["repeated"]:
        out.append("WARNING: a page repeated the previous one, so the endpoint seems to ignore $skip; "
                   "check paging in the API guide.")
    if r["hit_cap"]:
        out.append("WARNING: stopped at max_pages; the snapshot may be incomplete.")
    if r["elapsed"] > 60:
        out.append("WARNING: paging took over a minute, so pages may straddle a 5-minute update.")
    return out


def check_speed_bands(sb: dict) -> list[str]:
    df = sb["data"]
    out = paging_lines(sb)
    if not df:
        return out + ["WARNING: no records returned."]
    cols = columns(df)
    out += field_check(cols, EXPECTED_SPEED_FIELDS)
    if "LinkID" in cols:
        ids = [r.get("LinkID") for r in df]
        out.append(f"Unique LinkIDs: {len(set(ids))}; duplicated LinkIDs: {len(ids) - len(set(ids))}")
    out.append(missing_check(df))
    if "SpeedBand" in cols:
        out.append("SpeedBand counts: " + count_string([r.get("SpeedBand") for r in df]))
    if "RoadCategory" in cols:
        out.append("RoadCategory counts: " + count_string([r.get("RoadCategory") for r in df]))
    if all(c in cols for c in ("SpeedBand", "MinimumSpeed", "MaximumSpeed")):
        combos = {(to_int(r.get("SpeedBand")), to_num(r.get("MinimumSpeed")), to_num(r.get("MaximumSpeed")))
                  for r in df}
        nan_last = lambda v: (v is None, v or 0)
        combos = sorted(combos, key=lambda c: tuple(nan_last(v) for v in c))
        shown = "  ".join(f"{fmt_num(b)}:[{fmt_num(lo)},{fmt_num(hi)}]" for b, lo, hi in combos[:20])
        more = f"  (+{len(combos) - 20} more combinations)" if len(combos) > 20 else ""
        out.append(f"Band -> km/h range in this pull: {shown}{more}")
    if all(c in cols for c in ("StartLat", "StartLon", "EndLat", "EndLon")):
        lat = [to_num(r.get(c)) for c in ("StartLat", "EndLat") for r in df]
        lon = [to_num(r.get(c)) for c in ("StartLon", "EndLon") for r in df]
        bad = sum(1 for a, o in zip(lat, lon)
                  if a is None or o is None or not (1.1 <= a <= 1.5) or not (103.5 <= o <= 104.1))
        out.append(f"Link endpoints unparseable or outside a Singapore bounding box: {bad} of {len(lat)}")
    return out


def check_incidents(inc: dict) -> list[str]:
    df = inc["data"]
    out = paging_lines(inc) + [f"Incidents listed right now: {len(df)}"]
    if not df:
        return out + ["No incidents at the moment, so field checks are skipped; rerun later."]
    cols = columns(df)
    out += field_check(cols, EXPECTED_INCIDENT_FIELDS) + [missing_check(df)]
    if "Type" in cols:
        out.append("Type counts: " + count_string([r.get("Type") for r in df]))
    if "Message" in cols:
        out.append("Example messages (the schema has no time field; check whether the text carries one):")
        out += ["  " + str(r.get("Message"))[:140] for r in df[:3]]
    return out


# ---- NEA rainfall (data.gov.sg) -------------------------------------------------------------

def flatten_readings(readings: list[dict]) -> list[dict]:
    """One row per station and reading time."""
    return [{"timestamp": rd.get("timestamp"), "stationId": d.get("stationId"), "value": d.get("value")}
            for rd in readings for d in (rd.get("data") or [])]


def fetch_rain(date: Optional[str] = None, key: str = "") -> dict:
    """date=None gives the latest reading; 'YYYY-MM-DD' gives that whole day,
    following paginationToken until the API stops returning one."""
    headers = {"accept": "application/json", **({"x-api-key": key} if key else {})}
    source = "rainfall_latest" if date is None else f"rainfall_{date}"
    run = run_stamp()
    page = 1
    token = None
    stations = None
    readings: list[dict] = []
    reading_type = unit = None
    while True:
        query = {}
        if date is not None:
            query["date"] = date
        if token:
            query["paginationToken"] = token
        res = logged_get(source, CONFIG["rain_url"], headers, query, page, run)
        if not is_ok(res):
            return {"ok": False, "message": describe_failure(res, f"{source} request {page}")}
        js = parse_json(res)
        if not isinstance(js, dict) or not js.get("data"):
            code = js.get("code", "?") if isinstance(js, dict) else "?"
            return {"ok": False, "message": f"FAILED {source} request {page}: unexpected response (code {code})"}
        d = js["data"]
        if stations is None and d.get("stations"):
            stations = [flatten(s) for s in d["stations"]]
        readings += flatten_readings(d.get("readings") or [])
        reading_type = d.get("readingType") or reading_type
        unit = d.get("readingUnit") or unit
        token = d.get("paginationToken")
        if not token or page >= CONFIG["max_pages"]:
            break
        page += 1
        time.sleep(CONFIG["pause_seconds"])
    return {"ok": True, "stations": stations, "readings": readings, "requests": page,
            "reading_type": reading_type, "unit": unit}


def check_rain(r: dict, date: Optional[str] = None) -> list[str]:
    label = "latest" if date is None else date
    st, rd = r["stations"] or [], r["readings"]
    out = [f"[{label}] {r['requests']} request(s); reading type: {r['reading_type'] or 'NA'}; "
           f"unit: {r['unit'] or 'NA'}; stations listed: {len(st)}"]
    if not rd:
        return out + [f"[{label}] WARNING: no readings returned"]
    ts = [t for t in (parse_ts(x) for x in {row["timestamp"] for row in rd}) if t is not None]
    if ts:
        out.append(f"[{label}] Distinct reading times: {len(ts)}, from {min(ts):%Y-%m-%d %H:%M} "
                   f"to {max(ts):%Y-%m-%d %H:%M}")
    if date is not None:
        start = datetime.fromisoformat(date).replace(tzinfo=SGT)
        day_slots = {start + timedelta(minutes=5 * i) for i in range(288)}
        off_day = sum(1 for t in ts if t.strftime("%Y-%m-%d") != date)
        out.append(f"[{label}] 5-minute slots missing from the day: {len(day_slots - set(ts))} of 288; "
                   f"readings dated another day: {off_day}")
    per_time = list(Counter(row["timestamp"] for row in rd).values())
    out.append(f"[{label}] Stations reporting per reading time: min {min(per_time)}, "
               f"median {statistics.median(per_time):g}, max {max(per_time)}")
    if st and "id" in st[0]:
        listed = {s.get("id") for s in st}
        reporting = {row["stationId"] for row in rd}
        out.append(f"[{label}] Station IDs in readings but not listed: {len(reporting - listed)}; "
                   f"listed but never reporting: {len(listed - reporting)}")
    v = [to_num(row["value"]) for row in rd]
    vals = [x for x in v if x is not None]
    if not vals:
        return out + [f"[{label}] WARNING: all values missing"]
    out.append(f"[{label}] Values: {len(v) - len(vals)} missing; range {min(vals):g} to {max(vals):g}; "
               f"{100 * sum(x == 0 for x in vals) / len(vals):.1f}% zero")
    return out


# ---- Public holidays (MOM via data.gov.sg) ------------------------------------------------

def check_holidays(key: str = "") -> list[str]:
    headers = {"accept": "application/json", **({"x-api-key": key} if key else {})}
    res = logged_get("public_holidays", CONFIG["holiday_url"], headers,
                     {"resource_id": CONFIG["holiday_resource_id"], "limit": 100})
    if not is_ok(res):
        return [describe_failure(res, "public holidays")]
    js = parse_json(res)
    recs = ((js or {}).get("result") or {}).get("records") or []
    if not recs or not all(c in recs[0] for c in ("date", "day", "holiday")):
        return ["FAILED public holidays: no records, or fields other than date/day/holiday"]
    lo, hi = CONFIG["holiday_window"]
    keep = [r for r in recs if lo <= str(r.get("date"))[:10] <= hi]
    return ([f"Records: {len(recs)}", f"Holidays from {lo} to {hi}:"] +
            ([f"  {r['date']} {r['day']}  {r['holiday']}" for r in keep] or ["  none"]))


# ---- Run all checks -----------------------------------------------------------------------

def main() -> dict:
    CONFIG["out_dir"].mkdir(parents=True, exist_ok=True)
    LOG.clear()
    run = run_stamp()
    lta_key = read_setting("LTA_ACCOUNT_KEY")
    dgs_key = read_setting("DATAGOVSG_API_KEY")
    SECRETS[:] = [k for k in (lta_key, dgs_key) if k]
    out = [f"Source check started {now_sgt()} (Singapore time)", ""]

    lta_sections = [
        ("LTA Traffic Speed Bands", "speed_bands", CONFIG["lta_speed_path"], check_speed_bands),
        ("LTA Traffic Incidents", "incidents", CONFIG["lta_incidents_path"], check_incidents),
    ]
    for title, source, path, check in lta_sections:
        out.append(f"== {title} ==")
        if not lta_key:
            out += ["SKIPPED: LTA_ACCOUNT_KEY is not set (see the setup notes at the top).", ""]
            continue
        r = fetch_lta_all(source, path, lta_key)
        out += (check(r) if r["ok"] else [r["message"]]) + [""]

    out.append("== NEA rainfall via data.gov.sg ==")
    for date in [None, *CONFIG["rain_past_dates"]]:
        r = fetch_rain(date, dgs_key)
        out += check_rain(r, date) if r["ok"] else [r["message"]]
        time.sleep(CONFIG["pause_seconds"])
    out += ["", "== Public holidays (MOM via data.gov.sg) =="] + check_holidays(dgs_key) + [""]

    log_file = CONFIG["out_dir"] / f"request_log_{run}.csv"
    summary_file = CONFIG["out_dir"] / f"summary_{run}.txt"
    with open(log_file, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS, quoting=csv.QUOTE_NONNUMERIC)
        w.writeheader()
        w.writerows({k: ("NA" if v is None else v) for k, v in row.items()} for row in LOG)
    n_failed = sum(1 for row in LOG if row["http_status"] != 200)
    out.append(f"Requests: {len(LOG)}, failed: {n_failed}. Log: {log_file}")
    out = [mask(line) for line in out]
    summary_file.write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))
    return {"summary": out, "log": LOG}


if __name__ == "__main__":
    main()
