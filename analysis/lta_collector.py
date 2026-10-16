"""lta_collector.py - SLDS 42.510 project 1.3: 24/7 collector for LTA DataMall traffic feeds.

Runs continuously until stopped. Standard library only (Python 3.9+).

    python analysis/lta_collector.py           # run forever (Ctrl+C to stop)
    python analysis/lta_collector.py --once    # one pass of every feed, then exit (testing)
    python analysis/lta_collector.py --mode expressway --key-name LTA_ACCOUNT_KEY2 --hc-name HC_PING_URL2

Modes
  full (default)  everything below, saved in data_raw/.
  expressway      speed bands only, for the expressway links (RoadCategory 1), saved in
                  data_raw_expressway/ with its own lock, log, state and status. A full fetch maps
                  which pages hold expressway links (58 of 288 on 16 Oct); after that only those
                  pages are fetched, every --every seconds (default 120), and only pages whose
                  lastUpdatedTime changed are saved. Because LTA's pages lag each other by minutes,
                  this catches updates that one fetch per update misses. The map is rebuilt every
                  6 hours and whenever an expressway link is missing from the mapped pages.
                  Use a second key: LTA's rate limit (about 4,000 calls an hour) is per key.

What it collects (LTA DataMall API User Guide v6.10)
  Traffic Speed Bands (2.19)   whole network (~144k links). Probed every minute; when LTA's
                               lastUpdatedTime changes (about every 5 min) all ~290 pages are
                               fetched in parallel (6 threads, ~10 s) and saved.
  Traffic Incidents (2.18)     every 2 min, saved when the content changes
  VMS / EMAS (2.20)            every 2 min, saved when the content changes
  Est. Travel Times (2.13)     every 5 min, saved when the content changes
  Approved Road Works (2.16)   once a day
  Planned Road Openings (2.15) once a day

Reliability
  - Every request: timeout, up to 4 attempts with back-off on connection errors, 429 and 5xx,
    except LTA's rate-limit fault (HTTP 500 "Rate limit quota violation"), which is not retried.
  - Rate limit: LTA's quota on a key resets at the top of each hour. After a rate-limit fault
    the speed bands are not probed again until just after the next full hour.
  - A speed-band snapshot is saved only if every page arrived. Pages nearly always carry two
    or three lastUpdatedTime values, scattered across the pages, because LTA serves them from
    several servers that are not in sync (a page can even step back to the previous update).
    Refetching does not give a clean snapshot, so such snapshots are saved and logged as
    ok_flagged with each row's own last_updated, and are not refetched (refetching used up the
    hourly quota within minutes). A fetch starts only when page 1's time is newer than the
    last fetched one, so a page stepping back does not trigger a new fetch.
  - Files are written to a temporary name and renamed, so a crash never leaves half a file.
  - One failing feed never stops the others; errors are logged and retried on the next cycle.
  - Only one copy can run (operating-system file lock, released automatically if it dies).
    A Windows scheduled task started every 10 minutes therefore acts as a watchdog: it
    restarts the collector after a crash or reboot and exits at once if it is already running.
  - Heartbeat and counters in data_raw/collector_status.json; daily log files in data_raw/logs/.
  - Freeze guard: if the main loop stops ticking for 20 minutes (e.g. a hung network call), the
    collector exits on purpose so the watchdog task (or systemd) can start a fresh copy.

Alerts (optional, recommended)
  Put HC_PING_URL=https://hc-ping.com/<your-check-uuid> in .Renviron. The collector then pings
  Healthchecks.io after every saved speed-band snapshot and sends a /fail ping after 10 failed
  checks in a row or a freeze. Healthchecks.io e-mails you when pings stop arriving, which also
  covers the PC being asleep, switched off or offline (cases the collector cannot report itself).

Output (under the project folder; never edit data_raw/)
  data_raw/speedbands/YYYY-MM-DD/sb_<time>.csv.gz            retrieved_at,last_updated,LinkID,SpeedBand
  data_raw/speedbands_raw/YYYY-MM-DD/sbraw_<date>_<HHMM>.jsonl.gz  full raw responses, hourly
  data_raw/feeds/<feed>/YYYY-MM-DD/<feed>_<time>.jsonl.gz    raw responses, when changed
  data_raw/daily_feeds/daily_<date>.jsonl.gz                 road works + road openings
  data_raw/log_speedbands.csv   one row per speed-band fetch
  data_raw/log_feeds.csv        one row per feed poll (lets you rebuild what was live when)
Raw files are JSON Lines, one line per API response; "body" holds the response text exactly.

The key is read from .Renviron in the project folder (LTA_ACCOUNT_KEY=...), the same file
the R scripts use. It is sent only in the request header and never written to disk.

AI disclosure: drafted with Claude (Anthropic) on 14 Oct 2026; log in AI_USE.md.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import logging
import logging.handlers
import os
import signal
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

# ---- Settings -------------------------------------------------------------------------

BASE_URL = "https://datamall2.mytransport.sg/ltaodataservice/"
SPEED_PATH = "v4/TrafficSpeedBands"
FEEDS = {  # name: (path, poll interval in seconds)
    "incidents": ("TrafficIncidents", 120),
    "vms": ("VMS", 120),
    "travel_times": ("EstTravelTimes", 300),
}
DAILY_FEEDS = {"roadworks": "RoadWorks", "road_openings": "RoadOpenings"}
DAILY_AFTER_HOUR = 0          # daily feeds fetched on the first check after 00:10
DAILY_AFTER_MINUTE = 10
DAILY_CHECK_EVERY_S = 600

PROBE_EVERY_S = 60            # how often to check lastUpdatedTime of the speed bands
RAW_EVERY_MIN = 60            # full raw snapshot interval (set 5 to keep every update raw)
WORKERS = 6                   # parallel page requests during a speed-band fetch
PAGE_SIZE = 500               # LTA returns at most 500 records per call
MAX_PAGES = 400               # safety stop (~290 pages expected)
TIMEOUT_S = 30
BACKOFF_S = (2, 5, 15)        # waits between the 4 attempts of one request
HEARTBEAT_EVERY_S = 30
STALL_LIMIT_S = 1200          # freeze guard: exit if the loop has not ticked for 20 minutes
FAIL_ALERT_AFTER = 10         # consecutive failed speed-band checks before a /fail ping
EXPRESS_EVERY_S = 120         # expressway mode: seconds between fetches of the mapped pages
EXPRESS_CATEGORY = "1"        # RoadCategory of expressways (API guide 2.19)
MAP_MAX_AGE_S = 6 * 3600      # expressway mode: rebuild the page map with a full fetch this often

SGT = timezone(timedelta(hours=8))   # Singapore: no daylight saving
SB_LOG_FIELDS = ["retrieved_at", "last_updated", "status", "pages", "records", "seconds",
                 "saved_compact", "saved_raw", "message"]
FEED_LOG_FIELDS = ["retrieved_at", "feed", "status", "records", "content_hash", "saved", "message"]

log = logging.getLogger("lta_collector")


# ---- Small helpers ----------------------------------------------------------------------

def now_sgt() -> datetime:
    return datetime.now(SGT)


def iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%S%z")


def project_dir() -> Path:
    env = os.environ.get("SLDS_PROJECT_DIR")
    return Path(env).resolve() if env else Path(__file__).resolve().parent.parent


def read_setting(proj: Path, name: str) -> str:
    """NAME=value from .Renviron in the project folder, else the environment variable NAME."""
    renv = proj / ".Renviron"
    if renv.exists():
        for line in renv.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get(name, "").strip()


def read_key(proj: Path) -> str:
    return read_setting(proj, "LTA_ACCOUNT_KEY")


class Pinger:
    """Healthchecks.io pings in a background thread; never blocks or crashes the collector."""

    def __init__(self, url: str):
        self.url = url.rstrip("/")

    def ping(self, suffix: str = "", message: str = "") -> None:
        if not self.url:
            return
        def send():
            try:
                data = message.encode("utf-8")[:10000] if message else None
                urllib.request.urlopen(urllib.request.Request(self.url + suffix, data=data), timeout=10).read()
            except Exception as e:
                log.warning("alert ping failed: %s", e)
        threading.Thread(target=send, daemon=True).start()


def write_gz_lines(lines: list[str], path: Path) -> None:
    """Atomic write: temporary file, then rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".partial")
    with gzip.open(tmp, "wt", encoding="utf-8", newline="\n") as f:
        for line in lines:
            f.write(line + "\n")
    os.replace(tmp, path)


def write_json_atomic(obj: dict, path: Path) -> None:
    tmp = path.with_name(path.name + ".partial")
    tmp.write_text(json.dumps(obj, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, path)


def append_csv(path: Path, fields: list[str], row: dict) -> None:
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, quoting=csv.QUOTE_NONNUMERIC)
        if new:
            w.writeheader()
        out = {}
        for k in fields:
            v = row.get(k)
            out[k] = "NA" if v is None else ("TRUE" if v is True else "FALSE" if v is False else v)
        w.writerow(out)


def raw_line(endpoint: str, retrieved_at: str, page: int, body: str) -> str:
    return json.dumps({"endpoint": endpoint, "retrieved_at": retrieved_at, "page": page, "body": body})


# ---- HTTP -------------------------------------------------------------------------------

def http_get(url: str, key: str) -> tuple[int, str]:
    """One GET. Returns (status, body); HTTP errors are returned, not raised.
    LTA error bodies can echo the key (e.g. rate-limit faults), so it is masked before logging."""
    req = urllib.request.Request(url, headers={"AccountKey": key, "accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return e.code, body.replace(key, "<KEY>") if key else body


class Fetcher:
    """Requests with retries; http_get is injectable for testing."""

    def __init__(self, key: str, getter: Callable[[str, str], tuple[int, str]] = http_get,
                 sleep: Callable[[float], None] = time.sleep):
        self.key, self.getter, self.sleep = key, getter, sleep

    def get(self, url: str) -> dict[str, Any]:
        last: dict[str, Any] = {"status": None, "body": None, "error": "not attempted"}
        for attempt in range(len(BACKOFF_S) + 1):
            try:
                status, body = self.getter(url, self.key)
                res = {"status": status, "body": body, "error": None}
            except Exception as e:  # connection errors, timeouts, DNS
                res = {"status": None, "body": None, "error": f"{type(e).__name__}: {e}"}
            if res["status"] == 200:
                return res
            last = res
            retryable = (res["status"] is None or res["status"] == 429 or res["status"] >= 500) \
                and not is_rate_limited(res)
            if not retryable or attempt == len(BACKOFF_S):
                break
            self.sleep(BACKOFF_S[attempt])
        return last

    def page(self, path: str, skip: int) -> dict[str, Any]:
        url = BASE_URL + path + (f"?$skip={skip}" if skip else "")
        res = self.get(url)
        out = {"skip": skip, "ok": False, "body": res.get("body"), "status": res.get("status"),
               "error": res.get("error"), "value": [], "last_updated": None}
        if res["status"] != 200:
            return out
        try:
            js = json.loads(res["body"])
        except json.JSONDecodeError:
            out["error"] = "invalid JSON"
            return out
        out.update(ok=True, value=js.get("value") or [], last_updated=js.get("lastUpdatedTime"))
        return out


def is_rate_limited(res: dict) -> bool:
    """LTA reports an exhausted quota as HTTP 500 with a 'Rate limit quota violation' fault."""
    return "Rate limit quota violation" in (res.get("body") or "")


def is_newer(lu: Optional[str], seen: Optional[str]) -> bool:
    """True if the probe's lastUpdatedTime is newer than the last one fetched.
    LTA serves pages from several servers that are not in sync, so page 1 can step back to the
    previous update (seen 16 Oct: a page went 12:00 -> 11:55); a step back is not a new update.
    A step back of more than an hour is accepted, in case LTA's clock or the state file is off."""
    if not lu or not seen:
        return True
    try:
        new, old = (datetime.strptime(s, "%Y-%m-%d %H:%M:%S") for s in (lu, seen))
    except ValueError:
        return lu != seen
    return new > old or new < old - timedelta(hours=1)


def seconds_to_next_hour(margin_s: int = 30) -> int:
    t = now_sgt()
    return (59 - t.minute) * 60 + (60 - t.second) + margin_s


def describe(p: dict) -> str:
    detail = " ".join(str(p.get("error") or p.get("body") or "").split())[:160]
    return f"skip={p['skip']} HTTP {p.get('status') or 'none'} {detail}"


# ---- Speed bands --------------------------------------------------------------------------

def fetch_speedbands(f: Fetcher, pool: ThreadPoolExecutor, first: Optional[dict] = None) -> dict[str, Any]:
    """All pages of the speed bands, requested in parallel waves until a short page."""
    first = first or f.page(SPEED_PATH, 0)
    if not first["ok"]:
        return {"ok": False, "pages": [], "message": "page 1 failed: " + describe(first)}
    pages = [first]
    if len(first["value"]) < PAGE_SIZE:
        return {"ok": True, "pages": pages, "message": ""}
    next_skip = PAGE_SIZE
    while True:
        wave = [next_skip + i * PAGE_SIZE for i in range(WORKERS * 2)]
        results = list(pool.map(lambda s: f.page(SPEED_PATH, s), wave))
        bad = [r for r in results if not r["ok"]]
        if bad:
            return {"ok": False, "pages": pages, "message": f"{len(bad)} page(s) failed, e.g. " + describe(bad[0])}
        done = False
        for r in results:
            pages.append(r)
            if len(r["value"]) < PAGE_SIZE:
                done = True
                break
        if done:
            break
        if len(pages) >= MAX_PAGES:
            return {"ok": False, "pages": pages, "message": f"stopped at MAX_PAGES={MAX_PAGES}"}
        next_skip = wave[-1] + PAGE_SIZE
    pages = [p for p in pages if p["value"]] or pages[:1]
    return {"ok": True, "pages": pages, "message": ""}


def check_snapshot(pages: list[dict]) -> tuple[list[str], int, str]:
    """Returns (distinct lastUpdatedTime values, records, problem or '')."""
    lus = sorted({p["last_updated"] for p in pages if p["last_updated"]})
    ids = [r.get("LinkID") for p in pages for r in p["value"]]
    if len(ids) != len(set(ids)):
        return lus, len(ids), f"{len(ids) - len(set(ids))} duplicated LinkIDs"
    if len(lus) > 1:
        return lus, len(ids), "pages carry different lastUpdatedTime values"
    return lus, len(ids), ""


# ---- Collector ------------------------------------------------------------------------------

class Collector:
    def __init__(self, proj: Path, fetcher: Fetcher, pinger: Optional["Pinger"] = None,
                 exit_fn: Callable[[int], None] = os._exit, raw_dir: Optional[Path] = None,
                 mode: str = "full", every: int = EXPRESS_EVERY_S):
        self.proj, self.f = proj, fetcher
        self.pinger = pinger or Pinger("")
        self.exit_fn = exit_fn
        self.mode, self.every = mode, every
        self.consecutive_failures = 0
        self.sb_rate_limited = False
        self.last_tick = time.time()
        self.raw = raw_dir or proj / "data_raw"
        self.raw.mkdir(parents=True, exist_ok=True)
        self.state_path = self.raw / "collector_state.json"
        self.status_path = self.raw / "collector_status.json"
        self.state = self._load_state()
        self.pool = ThreadPoolExecutor(max_workers=WORKERS)
        self.stop = threading.Event()
        t = time.time()
        if mode == "expressway":  # the full-mode collector already polls the other feeds
            self.next_due = {"speedbands": t}
        else:
            self.next_due = {"speedbands": t, "daily": t, **{k: t for k in FEEDS}}
        self.status: dict[str, Any] = {"pid": os.getpid(), "started": iso(now_sgt()), "today": {},
                                       "last_error": None}

    def _load_state(self) -> dict:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return {"sb_last_updated": None, "feed_hash": {}}

    def _save_state(self) -> None:
        write_json_atomic(self.state, self.state_path)

    def _count(self, key: str) -> None:
        day = now_sgt().strftime("%Y-%m-%d")
        if self.status["today"].get("date") != day:
            self.status["today"] = {"date": day}
        self.status["today"][key] = self.status["today"].get(key, 0) + 1

    def heartbeat(self) -> None:
        self.status["last_heartbeat"] = iso(now_sgt())
        self.status["sb_last_updated"] = self.state.get("sb_last_updated")
        try:
            write_json_atomic(self.status, self.status_path)
        except OSError as e:
            log.error("cannot write status file: %s", e)

    # -- speed bands
    def write_compact(self, t0: datetime, pages: list[dict]) -> int:
        """retrieved_at,last_updated,LinkID,SpeedBand rows for these pages; returns the row count."""
        retrieved_at = iso(t0)
        rows = ["retrieved_at,last_updated,LinkID,SpeedBand"]
        for p in pages:
            plu = p["last_updated"] or ""
            rows.extend(f"{retrieved_at},{plu},{r.get('LinkID')},{r.get('SpeedBand')}" for r in p["value"])
        write_gz_lines(rows, self.raw / "speedbands" / t0.strftime("%Y-%m-%d") /
                       f"sb_{t0.strftime('%Y%m%d_%H%M%S')}.csv.gz")
        return len(rows) - 1

    def write_raw_hourly(self, t0: datetime, pages: list[dict]) -> bool:
        """Full raw responses, at most one file per RAW_EVERY_MIN slot; True if written."""
        slot = ((t0.hour * 60 + t0.minute) // RAW_EVERY_MIN) * RAW_EVERY_MIN
        raw_path = (self.raw / "speedbands_raw" / t0.strftime("%Y-%m-%d") /
                    f"sbraw_{t0.strftime('%Y%m%d')}_{slot // 60:02d}{slot % 60:02d}.jsonl.gz")
        if raw_path.exists():
            return False
        write_gz_lines([raw_line("TrafficSpeedBands", iso(t0), i + 1, p["body"])
                        for i, p in enumerate(pages)], raw_path)
        return True

    def job_speedbands(self) -> None:
        if self.mode == "expressway":
            return self.job_expressway()
        t0 = now_sgt()
        self.sb_rate_limited = False
        probe = self.f.page(SPEED_PATH, 0)
        if not probe["ok"]:
            self.sb_rate_limited = is_rate_limited(probe)
            self._sb_log(t0, None, "probe_failed", 0, 0, False, False, describe(probe))
            if probe.get("status") in (401, 403):
                log.error("LTA rejected the key (HTTP %s): check LTA_ACCOUNT_KEY in .Renviron", probe["status"])
            return
        lu = probe["last_updated"]
        if not is_newer(lu, self.state.get("sb_last_updated")):
            return  # nothing new; no log row for unchanged probes
        result = fetch_speedbands(self.f, self.pool, first=probe)
        if not result["ok"]:
            self.sb_rate_limited = "Rate limit quota violation" in result["message"]
            self._sb_log(t0, lu, "fetch_failed", len(result["pages"]), 0, False, False, result["message"])
            return
        lus, n, problem = check_snapshot(result["pages"])
        lu_str = lus[0] if len(lus) == 1 else (lu or "")
        self.write_compact(t0, result["pages"])
        saved_raw = self.write_raw_hourly(t0, result["pages"])
        # remember the probe page's time, which is what the next probe is compared with
        self.state["sb_last_updated"] = lu or lu_str
        self._save_state()
        status = "ok" if not problem else "ok_flagged"
        self._sb_log(t0, lu_str, status, len(result["pages"]), n, True, saved_raw, problem)
        self._count("speedband_snapshots")
        log.info("speed bands %s: %d records, %d pages, %.1f s %s", lu_str, n, len(result["pages"]),
                 (now_sgt() - t0).total_seconds(), problem)

    # -- expressway mode
    def need_map(self) -> bool:
        built = self.state.get("xw_map_time")
        return not self.state.get("xw_pages") or not built or time.time() - built > MAP_MAX_AGE_S

    def rebuild_map(self, t0: datetime) -> None:
        """Full fetch: save it, and record which pages hold expressway links."""
        result = fetch_speedbands(self.f, self.pool)
        if not result["ok"]:
            self.sb_rate_limited = "Rate limit quota violation" in result["message"]
            self._sb_log(t0, None, "fetch_failed", len(result["pages"]), 0, False, False,
                         "page map: " + result["message"])
            return
        pages = result["pages"]
        links = {p["skip"]: [str(r.get("LinkID")) for r in p["value"]
                             if str(r.get("RoadCategory")) == EXPRESS_CATEGORY] for p in pages}
        self.state["xw_pages"] = sorted(s for s, ids in links.items() if ids)
        self.state["xw_links"] = sorted(i for ids in links.values() for i in ids)
        self.state["xw_map_time"] = time.time()
        self.state["xw_page_lu"] = {str(p["skip"]): p["last_updated"] for p in pages if links[p["skip"]]}
        self._save_state()
        n = self.write_compact(t0, pages)
        saved_raw = self.write_raw_hourly(t0, pages)
        lus, _, problem = check_snapshot(pages)
        msg = (f"page map rebuilt: {len(self.state['xw_links'])} expressway links on "
               f"{len(self.state['xw_pages'])} of {len(pages)} pages")
        self._sb_log(t0, lus[-1] if lus else None, "ok" if not problem else "ok_flagged",
                     len(pages), n, True, saved_raw, msg)
        log.info(msg)

    def job_expressway(self) -> None:
        t0 = now_sgt()
        self.sb_rate_limited = False
        if self.need_map():
            return self.rebuild_map(t0)
        results = list(self.pool.map(lambda s: self.f.page(SPEED_PATH, s), self.state["xw_pages"]))
        bad = [r for r in results if not r["ok"]]
        if bad:
            self.sb_rate_limited = any(is_rate_limited(r) for r in bad)
            self._sb_log(t0, None, "fetch_failed", len(results) - len(bad), 0, False, False,
                         f"{len(bad)} page(s) failed, e.g. " + describe(bad[0]))
            return
        # save only pages whose time changed since this page was last read; a page that steps back
        # to an older update is saved again, which processing removes as a duplicate (LinkID, time)
        seen = self.state.setdefault("xw_page_lu", {})
        changed = [p for p in results if seen.get(str(p["skip"])) != p["last_updated"]]
        seen.update({str(p["skip"]): p["last_updated"] for p in results})
        n = self.write_compact(t0, changed) if changed else 0
        found = {str(r.get("LinkID")) for p in results for r in p["value"]
                 if str(r.get("RoadCategory")) == EXPRESS_CATEGORY}
        missing = set(self.state["xw_links"]) - found
        msg = f"{len(changed)} of {len(results)} pages changed"
        if missing:  # LTA added or removed links, so the pages shifted: full fetch next time
            self.state["xw_map_time"] = None
            msg += f"; {len(missing)} expressway links not on the mapped pages, page map will be rebuilt"
            log.warning(msg)
        self._save_state()
        lus = sorted({p["last_updated"] for p in results if p["last_updated"]})
        self._sb_log(t0, lus[-1] if lus else None, "ok_flagged" if missing else "ok",
                     len(results), n, bool(changed), False, msg)
        if changed:
            self._count("expressway_pages_saved")

    def _sb_log(self, t0, lu, status, pages, records, saved, saved_raw, message) -> None:
        if status not in ("ok", "ok_flagged"):
            log.warning("speed bands %s: %s", status, message)
            self.status["last_error"] = f"{iso(t0)} speedbands {status}: {message}"
            self._count("speedband_failures")
            self.consecutive_failures += 1
            if self.consecutive_failures == FAIL_ALERT_AFTER or (
                    self.consecutive_failures > FAIL_ALERT_AFTER and self.consecutive_failures % 60 == 0):
                self.pinger.ping("/fail", f"{self.consecutive_failures} failed speed-band checks in a row. "
                                          f"Last: {status}: {message}")
        else:
            self.consecutive_failures = 0
            self.pinger.ping("", f"snapshot {lu}: {records} records")
        append_csv(self.raw / "log_speedbands.csv", SB_LOG_FIELDS, {
            "retrieved_at": iso(t0), "last_updated": lu, "status": status, "pages": pages,
            "records": records, "seconds": round((now_sgt() - t0).total_seconds(), 1),
            "saved_compact": saved, "saved_raw": saved_raw, "message": message})

    # -- small feeds
    def fetch_feed(self, path: str) -> dict[str, Any]:
        pages, skip = [], 0
        while True:
            p = self.f.page(path, skip)
            if not p["ok"]:
                return {"ok": False, "pages": pages, "message": describe(p)}
            pages.append(p)
            if len(p["value"]) < PAGE_SIZE or len(pages) >= MAX_PAGES:
                return {"ok": True, "pages": pages, "message": ""}
            skip += PAGE_SIZE

    def job_feed(self, name: str) -> None:
        path = FEEDS[name][0]
        t0 = now_sgt()
        res = self.fetch_feed(path)
        row = {"retrieved_at": iso(t0), "feed": name, "status": "ok" if res["ok"] else "failed",
               "records": sum(len(p["value"]) for p in res["pages"]), "saved": False, "message": res["message"]}
        if res["ok"]:
            content = json.dumps([r for p in res["pages"] for r in p["value"]], sort_keys=True)
            h = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
            row["content_hash"] = h
            if h != self.state["feed_hash"].get(name):
                day, stamp = t0.strftime("%Y-%m-%d"), t0.strftime("%Y%m%d_%H%M%S")
                write_gz_lines([raw_line(path, iso(t0), i + 1, p["body"]) for i, p in enumerate(res["pages"])],
                               self.raw / "feeds" / name / day / f"{name}_{stamp}.jsonl.gz")
                self.state["feed_hash"][name] = h
                self._save_state()
                row["saved"] = True
                self._count(f"{name}_saved")
        else:
            log.warning("feed %s failed: %s", name, res["message"])
            self.status["last_error"] = f"{iso(t0)} {name}: {res['message']}"
        append_csv(self.raw / "log_feeds.csv", FEED_LOG_FIELDS, row)

    # -- daily feeds
    def job_daily(self) -> None:
        t0 = now_sgt()
        path = self.raw / "daily_feeds" / f"daily_{t0.strftime('%Y%m%d')}.jsonl.gz"
        if path.exists() or (t0.hour, t0.minute) < (DAILY_AFTER_HOUR, DAILY_AFTER_MINUTE):
            return
        lines, ok = [], True
        for name, p in DAILY_FEEDS.items():
            res = self.fetch_feed(p)
            ok = ok and res["ok"]
            lines.extend(raw_line(p, iso(t0), i + 1, pg["body"]) for i, pg in enumerate(res["pages"]))
            append_csv(self.raw / "log_feeds.csv", FEED_LOG_FIELDS, {
                "retrieved_at": iso(t0), "feed": name, "status": "ok" if res["ok"] else "failed",
                "records": sum(len(pg["value"]) for pg in res["pages"]), "saved": res["ok"],
                "message": res["message"]})
        if ok:
            write_gz_lines(lines, path)
            log.info("daily feeds saved")

    # -- scheduling
    def run_job(self, name: str) -> None:
        try:
            if name == "speedbands":
                self.job_speedbands()
            elif name == "daily":
                self.job_daily()
            else:
                self.job_feed(name)
        except Exception as e:  # never let one job stop the collector
            log.exception("job %s crashed: %s", name, e)
            self.status["last_error"] = f"{iso(now_sgt())} {name} crashed: {type(e).__name__}: {e}"

    def interval(self, name: str) -> int:
        if name == "speedbands":
            if self.sb_rate_limited:
                wait = seconds_to_next_hour()
                log.warning("LTA rate limit reached: next speed-band probe in %d s (after the hour)", wait)
                return wait
            return self.every if self.mode == "expressway" else PROBE_EVERY_S
        if name == "daily":
            return DAILY_CHECK_EVERY_S
        return FEEDS[name][1]

    def run_once(self) -> None:
        for name in self.next_due:
            self.run_job(name)
        self.heartbeat()

    def _freeze_guard(self) -> None:
        while not self.stop.wait(30):
            stalled = time.time() - self.last_tick
            if stalled > STALL_LIMIT_S:
                log.critical("main loop has not ticked for %.0f s: exiting so a fresh copy is started", stalled)
                self.pinger.ping("/fail", f"collector frozen for {stalled:.0f} s; restarting")
                time.sleep(2)  # let the ping and log line go out
                self.exit_fn(3)
                return

    def run_forever(self) -> None:
        log.info("collector started (pid %s) in %s", os.getpid(), self.proj)
        threading.Thread(target=self._freeze_guard, daemon=True).start()
        last_beat = 0.0
        while not self.stop.is_set():
            self.last_tick = time.time()
            t = time.time()
            for name, due in sorted(self.next_due.items(), key=lambda kv: kv[1]):
                if t >= due and not self.stop.is_set():
                    self.run_job(name)
                    # schedule from now: after a sleep/hibernate the job runs once, not many times
                    self.next_due[name] = time.time() + self.interval(name)
            if time.time() - last_beat >= HEARTBEAT_EVERY_S:
                self.heartbeat()
                last_beat = time.time()
            self.stop.wait(1.0)
        self.heartbeat()
        self.pool.shutdown(wait=False)
        log.info("collector stopped")


# ---- Single instance + logging --------------------------------------------------------

def acquire_lock(path: Path):
    """Exclusive OS lock on a file; returns the open handle, or None if another copy holds it.
    The OS releases the lock automatically when the process ends, even after a crash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+")
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh


def setup_logging(raw: Path, verbose: bool) -> None:
    log_dir = raw / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.TimedRotatingFileHandler(log_dir / "collector.log", when="midnight",
                                                        backupCount=0, encoding="utf-8")
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handler.setFormatter(fmt)
    log.setLevel(logging.INFO)
    log.handlers = [handler]
    if verbose and sys.stdout is not None:
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(fmt)
        log.addHandler(console)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="24/7 LTA DataMall collector (SLDS project 1.3)")
    ap.add_argument("--once", action="store_true", help="collect every feed once, then exit")
    ap.add_argument("--mode", choices=["full", "expressway"], default="full",
                    help="full: every feed (default); expressway: expressway speed-band pages only")
    ap.add_argument("--key-name", default="LTA_ACCOUNT_KEY", help="name of the key in .Renviron")
    ap.add_argument("--hc-name", default="HC_PING_URL", help="name of the Healthchecks URL in .Renviron")
    ap.add_argument("--data-dir", default=None,
                    help="output folder in the project (default data_raw, or data_raw_expressway)")
    ap.add_argument("--every", type=int, default=EXPRESS_EVERY_S,
                    help="expressway mode: seconds between fetches (default %(default)s)")
    args = ap.parse_args(argv)

    proj = project_dir()
    raw = proj / (args.data_dir or ("data_raw_expressway" if args.mode == "expressway" else "data_raw"))
    setup_logging(raw, verbose=True)
    lock = acquire_lock(raw / "collector.lock")
    if lock is None:
        print("Collector already running; nothing to do.")
        return 0
    key = read_setting(proj, args.key_name)
    if not key:
        log.error("%s not found in %s", args.key_name, proj / ".Renviron")
        return 1
    hc_url = read_setting(proj, args.hc_name)
    if not hc_url:
        log.info("no %s in .Renviron: alerts are off", args.hc_name)
    log.info("mode %s, key %s, output %s", args.mode, args.key_name, raw)
    c = Collector(proj, Fetcher(key), Pinger(hc_url), raw_dir=raw, mode=args.mode, every=args.every)

    def stop_handler(signum, frame):
        log.info("stop signal received")
        c.stop.set()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, stop_handler)
        except (ValueError, OSError):
            pass

    if args.once:
        c.run_once()
        c.pool.shutdown(wait=True)
        if hc_url:
            time.sleep(3)  # let the background alert ping finish before exiting
        print(json.dumps(c.status, indent=1, default=str))
    else:
        c.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
