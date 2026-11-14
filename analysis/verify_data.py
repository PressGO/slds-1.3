#!/usr/bin/env python3
"""verify_data.py - an independent check of the model tables (data version 3), straight from the raw files.

WHAT IT CHECKS
  A second implementation of the rules in docs/data_rules.md (rules 1-22; the rule numbers in the comments
  below are the numbers in that file). It recomputes samples of rows from the raw LTA files and compares every
  column. It never imports or reads the pipeline code (data_steps.py, build_data.py, ...) or its intermediate
  files (data_processed/clean/), so one mistake cannot hide behind the same mistake in the pipeline.

  1. extra/full_table.parquet: a sample (seed 20261114, --rows N, default 3000) of about 50% random usable rows
     (use TRUE), 20% onset positives (use, U FALSE, y TRUE), 15% unusable rows (use FALSE) and 15% rows on a
     Saturday, Sunday or public holiday. Plus corner-case rows (--corner-rows, default 100 for each rule) where
     rule 14 or 15 meets some, but not all, neighbours or joining roads unknown: a random sample almost never
     has them, so the script looks for them (seeded).
  2. extra/train_lodo.parquet (rule 22): a sample (--lodo-rows, default 500, spread evenly over all train days
     and so over all day types, about a quarter of them y TRUE), every column recomputed with the
     leave-own-day-out normal level of the link, its neighbours and its joining roads. And 3 whole train days
     (a weekday, a Saturday, a Sunday or holiday; seeded, never the half-collected first day): every link x
     5-min time, the use rows must be exactly the table's rows of that day, with the same y and U. The report
     also counts how many of these rows leaving the day out changes, so an OK means something.
  3. Link attributes from the raw registry snapshots: the 2,598 expressway links, their neighbours (rule 13),
     joining roads (rule 15) and rain station (rule 16). Compared in full with extra/links.parquet,
     extra/neighbours.parquet and extra/connectors.parquet (rounded as rule 21 says).
  4. The raw speed bands of every expressway link and joining road, from the CSV files of both collectors.
  5. Every column of every sampled row: exact for integers, booleans, strings, dates, times and rain (rule 16:
     whole tenths of a mm); other floats within 1e-6; null equals only null.
  6. Whole-table checks: (a) train.parquet = the use rows of full_table, value for value; (b) the links of
     full_table = the RoadCategory-1 links; (c) extra/norm.parquet for 50 sampled links and
     extra/connector_norm.parquet for their joining roads; (d) split and day type of every row, and every link
     x 5-min time 06:00-21:55 on every day; (e) rain totals never below 0, never in (0, 0.1) and always whole
     tenths (full_table and train_lodo); the table holds exactly the finished days (rule 18); train_lodo holds
     only train days; data_settings.py holds the same numbers as the rules (compared only, never used).

HOW TO RUN (it only reads; it writes nothing)
  cd /home/dev/slds-1.3 && systemd-run --user --scope -q -p MemoryMax=8G -p MemorySwapMax=1G \
      .venv/bin/python analysis/verify_data.py [--rows 3000] [--corner-rows 100] [--lodo-rows 500] [--workers 8]
  It takes about 5 minutes and under 4 GB of memory. The last line is "VERIFY: OK (...)" (exit code 0) or
  "VERIFY: FAILED (...)" (exit code 1). Above it: mismatches per column with up to 3 examples, what the
  sample covered, every other check, notes, and the working (my values and the raw rows) for the first
  mismatch of every mismatching column.

AI disclosure: written by Claude (Anthropic) on 14 Nov 2026 as an independent check, from the written rules only; log in AI_USE.md.
"""

import argparse
import csv
import glob
import gzip
import io
import itertools
import math
import os
import random
import resource
import sys
import time as wallclock
import warnings
from array import array
from collections import Counter, defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta, timezone

os.environ.setdefault("POLARS_MAX_THREADS", "8")   # leave CPU for the two data collectors
import polars as pl  # noqa: E402

warnings.filterwarnings("ignore", category=DeprecationWarning)

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
RULES_FILE = os.path.join(PROJECT, "docs", "data_rules.md")     # the rules this script checks
SPEED_DIRS = (os.path.join(PROJECT, "data_raw", "speedbands"),  # in this order: rule 1 tie-break
              os.path.join(PROJECT, "data_raw_expressway", "speedbands"))
REGISTRY_DIR = os.path.join(PROJECT, "data_raw", "speedbands_raw")
RAIN_FILE = os.path.join(PROJECT, "data_processed", "rainfall_5min.csv.gz")
STATIONS_FILE = os.path.join(PROJECT, "data_processed", "rain_stations.csv")
CALENDAR_FILE = os.path.join(PROJECT, "data_processed", "calendar_2026.csv")
MODEL = os.path.join(PROJECT, "data_processed", "model")
FULL = os.path.join(MODEL, "extra", "full_table.parquet")
TRAIN = os.path.join(MODEL, "train.parquet")
LODO = os.path.join(MODEL, "extra", "train_lodo.parquet")
TEST = os.path.join(MODEL, "test.parquet")
TEST_FULL = os.path.join(MODEL, "extra", "test_full.parquet")
NORM = os.path.join(MODEL, "extra", "norm.parquet")
CONN_NORM = os.path.join(MODEL, "extra", "connector_norm.parquet")
NEIGHBOURS = os.path.join(MODEL, "extra", "neighbours.parquet")
CONNECTORS = os.path.join(MODEL, "extra", "connectors.parquet")
LINKS = os.path.join(MODEL, "extra", "links.parquet")

# ---- the numbers of the rules, typed in from docs/data_rules.md (NOT taken from the pipeline) ----
SPLITS = (("train", date(2026, 10, 16), date(2026, 11, 8)),        # rule 4
          ("validate", date(2026, 11, 9), date(2026, 11, 15)),
          ("test", date(2026, 11, 16), date(2026, 11, 22)))
N_EXPRESSWAY = 2598                      # rule 2
EXPRESSWAY = "1"                         # rule 2: RoadCategory "1"
TOL_M = 5.0                              # rules 13 and 15: within 5 m
M_PER_DEG = 111320.0                     # rule 13
COS_REF = math.cos(math.radians(1.35))   # rule 13
EARTH_KM = 6371.0                        # rule 16
RAIN_MIN_READINGS = 231                  # rule 16: readings in >= 80% of the 288 five-minute slots of a day
LOW_FROM = 2                             # rule 8: low = deficit >= 2
LAGS = (0, 5, 10, 15, 20, 25, 30)        # rule 12 (minutes back)
LABELS = (("y", 15), ("y_h5", 5), ("y_h10", 10), ("y_h30", 30))            # rule 10 (minutes ahead)
RAIN = (("f_rain15", (5, 10, 15)), ("f_rain30", (5, 10, 15, 20, 25, 30)))  # rule 16 (minutes back)
FIRST_ROW, LAST_ROW = time(6, 0), time(21, 55)                             # rule 18
LATE_FILES = timedelta(hours=1)          # raw inputs: files fetched up to 01:00 after the last finished day
FINISHED_AFTER = timedelta(hours=2)      # rule 18: day D is finished at D+1 02:00 (and with its 23:55 rain)
DAYTYPES = ("weekday", "saturday", "sunday_or_holiday")                    # rule 3
WEEKDAY_COLS = ("f_mon", "f_tue", "f_wed", "f_thu", "f_fri", "f_sat", "f_sun")   # rule 17
ROAD_GROUPS = {"KALLANG PAYA LEBAR EXPRESSWAY TUNNEL": "KALLANG PAYA LEBAR EXPRESSWAY"}   # rule 20
KM_DECIMALS, GAP_DECIMALS = 3, 2         # rule 21: station_km to 3 decimals, gap_m to 2
EXACT_COLS = ("f_rain15", "f_rain30", "info_rain_mm")   # rule 16: rain is exact (whole tenths of a mm)
SEED = 20261114
FLOAT_TOL = 1e-6
STEP = timedelta(minutes=5)
PER_DAY = 288                            # 5-min steps in a day
SGT = timezone(timedelta(hours=8))
BASE = datetime(2026, 10, 16)            # first training day 00:00; the 5-min index s counts from here

HOLIDAYS = set()                         # public holidays (calendar_2026.csv), filled by load_calendar()
SCHOOL = {}                              # date -> school_period, for info_school_period (rule 20)
START = wallclock.time()


def log(msg):
    print(f"[{wallclock.time() - START:6.0f}s] {msg}", flush=True)


def full_files():
    """full_table.parquet, plus extra/test_full.parquet once the test week exists."""
    return [FULL] + ([TEST_FULL] if os.path.exists(TEST_FULL) else [])


def full_scan():
    return pl.scan_parquet(full_files())


# ======================================================================================================
# Small helpers: days, slots, the 5-min index, distances
# ======================================================================================================

def daytype(d):                          # rule 3
    if d in HOLIDAYS or d.weekday() == 6:
        return "sunday_or_holiday"
    if d.weekday() == 5:
        return "saturday"
    return "weekday"


def split_of(d):                         # rule 4
    for name, first, last in SPLITS:
        if first <= d <= last:
            return name
    return None


def slot15(t):                           # rule 5
    return t.hour * 4 + t.minute // 15


def tindex(t):
    """The 5-min index s of time t (counted from BASE)."""
    delta = t - BASE
    seconds = delta.days * 86400 + delta.seconds
    assert seconds % 300 == 0 and delta.microseconds == 0, t
    return seconds // 300


def time_of(s):
    return BASE + s * STEP


def median(values):                      # rule 6: an even count gives the mean of the two middle values
    v = sorted(values)
    n = len(v)
    if n == 0:
        return None
    m = n // 2
    return float(v[m]) if n % 2 else (v[m - 1] + v[m]) / 2


def flat_xy(lon, lat):                   # rule 13: metres on a flat grid
    return lon * M_PER_DEG * COS_REF, lat * M_PER_DEG


def flat_dist(p, q):                     # rule 13: Euclidean
    dx, dy = p[0] - q[0], p[1] - q[1]
    return math.sqrt(dx * dx + dy * dy)


def haversine_km(lat1, lon1, lat2, lon2):   # rule 16: great circle, R = 6371 km
    f1, f2 = math.radians(lat1), math.radians(lat2)
    df, dl = f2 - f1, math.radians(lon2 - lon1)
    a = math.sin(df / 2) ** 2 + math.cos(f1) * math.cos(f2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_KM * math.asin(math.sqrt(a))


def parse_local(text):
    """'2026-11-10T00:01:50+0800' or '2026-10-13T00:00:00+08:00' -> naive Singapore time (None if unreadable)."""
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S%z").astimezone(SGT).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def ordered_map(func, items, workers):
    """func(item) on a thread pool. Results come back in input order; at most 3 x workers wait (memory)."""
    items = iter(items)
    done = object()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        waiting = deque(pool.submit(func, x) for x in itertools.islice(items, 3 * workers))
        while waiting:
            result = waiting.popleft().result()
            nxt = next(items, done)
            if nxt is not done:
                waiting.append(pool.submit(func, nxt))
            yield result


def fmt(v):
    if isinstance(v, float):
        return f"{v:.6g}"
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    return "null" if v is None else str(v)


# ======================================================================================================
# Calendar, settings
# ======================================================================================================

def load_calendar():
    with open(CALENDAR_FILE, newline="") as fh:
        for row in csv.DictReader(fh):
            d = date.fromisoformat(row["date"])
            if row["is_public_holiday"].strip().lower() == "true":
                HOLIDAYS.add(d)
            SCHOOL[d] = row.get("school_period") or None


def check_settings():
    """The pipeline's settings file must hold the same numbers as the rules (a check; nothing is used)."""
    sys.path.insert(0, HERE)
    sys.dont_write_bytecode = True   # this script writes nothing, not even analysis/__pycache__/
    import data_settings as ds
    mine = {
        "SPLITS": {name: (a, b) for name, a, b in SPLITS},
        "EXPECTED_EXPRESSWAY_LINKS": N_EXPRESSWAY, "EXPRESSWAY_CATEGORY": int(EXPRESSWAY),
        "NEIGHBOUR_TOL_M": TOL_M, "CONNECTOR_TOL_M": TOL_M, "THRESHOLD": LOW_FROM, "CONSECUTIVE": 2,
        "HORIZON": 15, "EXTRA_HORIZONS": (5, 10, 30), "LAGS": LAGS, "CARRY_MAX": 5, "RAIN_LAG": 5,
        "RAIN_WINDOWS": {"f_rain15": 15, "f_rain30": 30}, "HOUR_FROM": 6, "HOUR_TO": 22, "STEP_MIN": 5,
        "LATE_ROWS_MIN": 60, "FINISHED_AFTER_H": 2, "DAYTYPES": DAYTYPES, "WEEKDAY_COLUMNS": WEEKDAY_COLS,
        "NORM_SPLIT": "train", "DATA_VERSION": "3", "ROAD_GROUPS": ROAD_GROUPS, "RAIN_STATION_MIN_SHARE": 0.80,
    }
    bad = [(k, v, getattr(ds, k, "<missing>")) for k, v in mine.items()
           if getattr(ds, k, "<missing>") != v and not (isinstance(v, tuple) and tuple(getattr(ds, k, ())) == v)]
    if math.ceil(getattr(ds, "RAIN_STATION_MIN_SHARE", 0) * PER_DAY) != RAIN_MIN_READINGS:
        bad.append(("RAIN_STATION_MIN_SHARE x 288", RAIN_MIN_READINGS, getattr(ds, "RAIN_STATION_MIN_SHARE", None)))
    return len(mine), bad


# ======================================================================================================
# Raw registry: link attributes (raw inputs + rule 2), neighbours (rule 13), joining roads (rule 15)
# ======================================================================================================

REG_FIELDS = ("RoadName", "RoadCategory", "StartLon", "StartLat", "EndLon", "EndLat")
REG_RECORD = pl.Struct({"LinkID": pl.String, **{f: pl.String for f in REG_FIELDS}})


def read_snapshot(path):
    """One snapshot file -> (path, pages, one row per record: retrieved_at, LinkID, the six attributes)."""
    with gzip.open(path, "rb") as fh:
        raw = fh.read()
    pages = pl.read_ndjson(io.BytesIO(raw), schema={"retrieved_at": pl.String, "body": pl.String})
    body = pl.col("body").str.json_decode(pl.Struct({"value": pl.List(REG_RECORD)}))
    records = (pages.select("retrieved_at", body.struct.field("value").alias("rec"))
               .explode("rec", empty_as_null=False).unnest("rec"))
    return path, pages.height, records


def read_registry(workers, last_day):
    """Raw inputs: each link's attributes from the latest snapshot (latest retrieved_at) among the snapshot
    files up to the last finished day (folder date <= last_day)."""
    files = sorted((p for p in glob.glob(os.path.join(REGISTRY_DIR, "*", "sbraw_*.jsonl.gz"))
                    if os.path.basename(os.path.dirname(p)) <= last_day.isoformat()),
                   key=os.path.basename, reverse=True)                   # newest first
    latest = {}                                                          # LinkID -> (retrieved, attributes)
    st = Counter(files=len(files))
    ties = []
    prev_oldest = None
    for path, n_pages, rec in ordered_map(read_snapshot, files, workers):
        st["pages"] += n_pages
        st["records"] += rec.height
        st["records without LinkID"] += rec["LinkID"].null_count()
        rec = rec.filter(pl.col("LinkID").is_not_null())
        when = {s: parse_local(s) for s in rec["retrieved_at"].unique().to_list()}
        if None in when.values():
            st["records with unreadable retrieved_at"] += rec.filter(
                pl.col("retrieved_at").is_in([s for s, w in when.items() if w is None])).height
            rec = rec.filter(pl.col("retrieved_at").is_in([s for s, w in when.items() if w is not None]))
            when = {s: w for s, w in when.items() if w is not None}
        if not when:
            continue
        newest, oldest = max(when.values()), min(when.values())
        st["newest retrieved_at"] = max(st["newest retrieved_at"] or newest, newest)
        in_order = prev_oldest is None or newest <= prev_oldest          # true when files really are newest first
        st["files out of time order"] += not in_order
        prev_oldest = oldest if prev_oldest is None else min(prev_oldest, oldest)
        ids = rec["LinkID"].to_list()
        idset = set(ids)
        st["files with a link twice"] += len(idset) != len(ids)
        if in_order and len(idset) == len(ids):
            new = idset.difference(latest)                               # links not yet seen in a newer file
            if not new:
                continue
            rows = [i for i, x in enumerate(ids) if x in new]
        else:
            rows = range(len(ids))                                       # general case: compare every record
        cols = {c: rec[c].to_list() for c in ("retrieved_at",) + REG_FIELDS}
        for i in rows:
            r = when[cols["retrieved_at"][i]]
            attrs = tuple(cols[f][i] for f in REG_FIELDS)
            cur = latest.get(ids[i])
            if cur is None or r > cur[0]:
                latest[ids[i]] = (r, attrs)
            elif r == cur[0] and attrs != cur[1]:
                ties.append((ids[i], r, cur[1], attrs))
    return latest, st, ties


class Link:
    __slots__ = ("id", "name", "category", "start_lon", "start_lat", "end_lon", "end_lat", "start", "end")

    def __init__(self, lid, attrs):
        self.id = lid
        self.name, self.category = attrs[0], attrs[1]
        self.start_lon, self.start_lat, self.end_lon, self.end_lat = (float(x) for x in attrs[2:6])
        self.start = flat_xy(self.start_lon, self.start_lat)
        self.end = flat_xy(self.end_lon, self.end_lat)


def grid_of(points):
    """Points in 5 m x 5 m cells, so that all points within 5 m are in the 3 x 3 cells around a point."""
    grid = defaultdict(list)
    for key, (x, y) in points:
        grid[(math.floor(x / TOL_M), math.floor(y / TOL_M))].append((key, x, y))
    return grid


def near(grid, p):
    cx, cy = math.floor(p[0] / TOL_M), math.floor(p[1] / TOL_M)
    for gx in (cx - 1, cx, cx + 1):
        for gy in (cy - 1, cy, cy + 1):
            for key, x, y in grid.get((gx, gy), ()):
                gap = flat_dist(p, (x, y))
                if gap <= TOL_M:
                    yield key, gap


def find_neighbours(links, expressway):
    """Rule 13: B is downstream of A when A's end point is within 5 m of B's start point (A != B)."""
    starts = grid_of((lid, links[lid].start) for lid in expressway)
    down, up = defaultdict(list), defaultdict(list)
    for a in expressway:
        for b, gap in near(starts, links[a].end):
            if b != a:
                down[a].append((b, gap))
                up[b].append((a, gap))
    return down, up


def find_joining_roads(links, expressway):
    """Rule 15: non-expressway C leads into l when C's end is within 5 m of l's start;
    out of l when C's start is within 5 m of l's end."""
    starts = grid_of((lid, links[lid].start) for lid in expressway)
    ends = grid_of((lid, links[lid].end) for lid in expressway)
    into, out_of = defaultdict(list), defaultdict(list)
    for cid, c in links.items():
        if c.category == EXPRESSWAY:
            continue
        for lid, gap in near(starts, c.end):
            into[lid].append((cid, gap))
        for lid, gap in near(ends, c.start):
            out_of[lid].append((cid, gap))
    return into, out_of


# ======================================================================================================
# Rain (rule 16)
# ======================================================================================================

def read_rain(train_days):
    readings = defaultdict(dict)       # station -> {time: mm}
    per_day = defaultdict(Counter)     # station -> date of the timestamp -> number of readings
    st = Counter()
    times = {}
    with gzip.open(RAIN_FILE, "rt", newline="") as fh:
        for row in csv.DictReader(fh):
            ts = row["timestamp"]
            t = times.get(ts)
            if t is None:
                t = times[ts] = parse_local(ts)
            try:
                mm = float(row["rain_mm"])
            except (TypeError, ValueError):
                mm = None
            if t is None or mm is None:
                st["unreadable rows"] += 1
                continue
            sid = row["station_id"]
            st["rows"] += 1
            if t in readings[sid]:
                st["same station and time twice"] += 1
            else:
                per_day[sid][t.date()] += 1
            st["readings below 0 or not whole tenths"] += mm < 0 or abs(mm * 10 - round(mm * 10)) > 1e-9
            readings[sid][t] = mm
    with open(STATIONS_FILE, newline="") as fh:
        stations = {row["station_id"]: (float(row["lat"]), float(row["lon"])) for row in csv.DictReader(fh)}
    # rule 16: eligible = 231 or more readings (by the date of the timestamp) on EVERY train day
    eligible = sorted(s for s in stations if all(per_day[s][d] >= RAIN_MIN_READINGS for d in train_days))
    return readings, stations, eligible, st


def nearest_station(link, stations, eligible):
    lat = (link.start_lat + link.end_lat) / 2
    lon = (link.start_lon + link.end_lon) / 2
    dists = sorted((haversine_km(lat, lon, *stations[s]), s) for s in eligible)
    tie = len(dists) > 1 and dists[1][0] - dists[0][0] < 1e-9
    return dists[0][1], dists[0][0], tie


def rain_total(readings):
    """Rule 16: the sum, exact. Readings are whole tenths of a mm, so add them as whole tenths."""
    return sum(round(mm * 10) for mm in readings) / 10


# ======================================================================================================
# Raw speed bands (rule 1)
# ======================================================================================================

SB_COLUMNS = ["retrieved_at", "last_updated", "LinkID", "SpeedBand"]
BAND_VALUE = {str(b): b for b in range(1, 9)}        # SpeedBand is 1-8
NO_ROW = 2**31 - 1                                   # "no row yet" in the retrieved-time arrays
BAD_TIME = -(2**40)
OUTSIDE, OFF_GRID, UNREADABLE = -1, -2, -3


def list_speed_files(until):
    """Every sb_*.csv.gz of both collectors fetched up to `until` (fetch time from the file name), in the
    order of rule 1's tie-break: earlier file name first, and data_raw before data_raw_expressway."""
    files, misplaced = [], 0
    for order, folder in enumerate(SPEED_DIRS):
        for path in glob.glob(os.path.join(folder, "*", "sb_*.csv.gz")):
            name = os.path.basename(path)
            fetched = datetime.strptime(name[3:18], "%Y%m%d_%H%M%S")
            misplaced += os.path.basename(os.path.dirname(path)) != fetched.strftime("%Y-%m-%d")
            if fetched <= until:
                files.append((name, order, fetched, path))
    files.sort()
    return [(fetched, path) for _, _, fetched, path in files], misplaced


def read_speed_file(path, wanted):
    """Polars only reads the CSV and keeps the rows of the wanted links; the rules are applied in Python."""
    try:
        df = pl.read_csv(path, infer_schema=False)        # every column as text
    except Exception as exc:                              # noqa: BLE001 - reported as an unreadable file
        return path, None, repr(exc)
    if df.columns != SB_COLUMNS:
        return path, None, f"unexpected columns {df.columns}"
    sub = df.filter(pl.col("LinkID").is_in(wanted))
    return path, df.height, (sub["retrieved_at"].to_list(), sub["last_updated"].to_list(),
                             sub["LinkID"].to_list(), sub["SpeedBand"].to_list())


class BandStore:
    """band(l, t) by rule 1: among all rows of both collectors with that LinkID and last_updated = t, the
    SpeedBand of the row with the earliest retrieved_at. Files come in tie-break order (list_speed_files), and
    on an equal retrieved_at the first row is kept. One array per link over the 5-min index."""

    def __init__(self, link_ids, n_steps):
        self.ids = list(link_ids)
        self.index = {lid: i for i, lid in enumerate(self.ids)}
        self.n = n_steps
        self.band = [bytearray(n_steps) for _ in self.ids]                # 0 = no row
        self.retr = [array("i", [NO_ROW]) * n_steps for _ in self.ids]    # seconds after BASE of the kept row
        self.off_grid = {}            # (link index, time) -> (retrieved, band): update times not on the 5-min grid
        self.retr_cache, self.time_cache, self.off_grid_time = {}, {}, {}
        self.stats = Counter()
        self.examples = defaultdict(list)

    def _update_index(self, text):
        try:
            t = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            return UNREADABLE
        delta = t - BASE
        seconds = delta.days * 86400 + delta.seconds
        if seconds % 300:
            self.off_grid_time[text] = t
            return OFF_GRID
        s = seconds // 300
        return s if 0 <= s < self.n else OUTSIDE

    def _retrieved(self, text):
        t = parse_local(text)
        return BAD_TIME if t is None else int((t - BASE).total_seconds())

    def _example(self, kind, item):
        if len(self.examples[kind]) < 5:
            self.examples[kind].append(item)

    def add(self, path, retrs, updates, ids, bands):
        index, B, R = self.index, self.band, self.retr
        rcache, tcache = self.retr_cache, self.time_cache
        kept = repeats = differ = ties = bad = outside = 0
        for r_text, u_text, lid, b_text in zip(retrs, updates, ids, bands):
            b = BAND_VALUE.get(b_text)
            r = rcache.get(r_text)
            if r is None:
                r = rcache[r_text] = self._retrieved(r_text)
            s = tcache.get(u_text)
            if s is None:
                s = tcache[u_text] = self._update_index(u_text)
            if b is None or r == BAD_TIME or s == UNREADABLE:
                bad += 1
                self._example("unreadable row", (path, r_text, u_text, lid, b_text))
                continue
            i = index[lid]
            if s < 0:
                if s == OUTSIDE:
                    outside += 1
                else:
                    self._add_off_grid(i, self.off_grid_time[u_text], r, b, path)
                continue
            rr, bb = R[i], B[i]
            old = rr[s]
            if old == NO_ROW:                       # first row for this link and update time
                bb[s] = b
                rr[s] = r
                kept += 1
                continue
            repeats += 1
            if bb[s] != b:
                differ += 1
                self._example("same link and update, different band", (lid, u_text, bb[s], old, b, r, path))
            if r < old:                             # rule 1: the earliest retrieved_at wins
                bb[s] = b
                rr[s] = r
            elif r == old and bb[s] != b:           # rule 1 tie: the earlier file (already kept) wins
                ties += 1
                self._example("same retrieved_at, different band", (lid, u_text, bb[s], b, path))
        st = self.stats
        st["rows of wanted links"] += kept + repeats + bad + outside
        st["link-updates kept"] += kept
        st["repeats (same link and update again)"] += repeats
        st["repeats with a different band"] += differ
        st["repeats with the same retrieved_at and a different band"] += ties
        st["unreadable rows (band not 1-8, bad time)"] += bad
        st["rows outside the time range"] += outside

    def _add_off_grid(self, i, t, r, b, path):
        self.stats["rows with an update time off the 5-min grid"] += 1
        self._example("update time off the 5-min grid", (self.ids[i], t, b, path))
        old = self.off_grid.get((i, t))
        if old is None or r < old[0]:
            self.off_grid[(i, t)] = (r, b)

    def band_at(self, i, s):
        if 0 <= s < self.n:
            b = self.band[i][s]
            return b if b else None
        return None

    def retrieved_at(self, i, s):
        if 0 <= s < self.n and self.retr[i][s] != NO_ROW:
            return BASE + timedelta(seconds=self.retr[i][s])
        return None

    def late_rows(self):
        """Kept bands whose earliest copy was fetched after D+1 01:00 (D = date of t), and the longest delay
        (seconds). A diagnostic only, so numpy is fine here."""
        import numpy as np
        late, longest = 0, 0
        for rr in self.retr:
            r = np.frombuffer(rr, dtype=np.int32).astype(np.int64)
            s = np.nonzero(r != NO_ROW)[0]
            if len(s):
                r = r[s]
                longest = max(longest, int((r - s * 300).max()))
                late += int((r > (s // PER_DAY + 1) * 86400 + 3600).sum())
        return late, longest


def read_speed_bands(files, wanted, workers, n_steps):
    store = BandStore(sorted(wanted), n_steps)
    wanted_list = sorted(wanted)
    unreadable = []
    rows_all = 0
    for k, (path, n_rows, payload) in enumerate(
            ordered_map(lambda fp: read_speed_file(fp[1], wanted_list), files, workers)):
        if n_rows is None:
            unreadable.append((path, payload))
            continue
        rows_all += n_rows
        store.add(path, *payload)
        if (k + 1) % 5000 == 0:
            log(f"  speed bands: {k + 1:,} of {len(files):,} files read")
    store.stats["rows read (all links)"] = rows_all
    return store, unreadable


# ======================================================================================================
# The rules on top of the bands (rules 6-12, and rule 22 with leave_out) and one full row (rules 13-20)
# ======================================================================================================

class Rules:
    """Rules 6-11 on top of the band store. With leave_out = d (rule 22), every normal level is the median
    over the train days of that day type except day d."""

    def __init__(self, store, train_days, leave_out=None):
        self.store = store
        self.leave_out = leave_out
        self.train_by_type = {dt: [d for d in train_days if daytype(d) == dt and d != leave_out] for dt in DAYTYPES}
        self.norms = {}
        self.off_grid_by_link = defaultdict(list)
        for (i, t), (r, b) in store.off_grid.items():
            self.off_grid_by_link[i].append((t, b))

    def norm_cell(self, i, dt, slot):
        """Rule 6: median of all bands of the link at times (any hour) on train days of that day type whose
        slot is `slot`. Returns (median, number of bands, number of days)."""
        key = (i, dt, slot)
        hit = self.norms.get(key)
        if hit is None:
            values, days = [], set()
            for d in self.train_by_type[dt]:
                first = (d - BASE.date()).days * PER_DAY + slot * 3      # the three 5-min times of the slot
                for s in (first, first + 1, first + 2):
                    b = self.store.band_at(i, s)
                    if b is not None:
                        values.append(b)
                        days.add(d)
            for t, b in self.off_grid_by_link.get(i, ()):                # update times off the grid (if any)
                if t.date() in self.train_by_type[dt] and slot15(t) == slot:
                    values.append(b)
                    days.add(t.date())
            hit = self.norms[key] = (median(values), len(values), len(days))
        return hit

    def norm_at(self, i, s):
        t = time_of(s)
        return self.norm_cell(i, daytype(t.date()), slot15(t))[0]

    def deficit(self, i, s):             # rule 7
        b = self.store.band_at(i, s)
        if b is None:
            return None
        n = self.norm_at(i, s)
        return None if n is None else n - b

    def low(self, i, s):                 # rule 8
        d = self.deficit(i, s)
        return None if d is None else d >= LOW_FROM

    def unusual(self, i, s):             # rule 9: U = low now AND low 5 min ago; null if either is unknown
        a, b = self.low(i, s), self.low(i, s - 1)
        return None if a is None or b is None else (a and b)

    def dfill(self, i, s):               # rule 11: d now, else d 5 min ago, else unknown
        d = self.deficit(i, s)
        return d if d is not None else self.deficit(i, s - 1)


class Context:
    """Everything one row needs."""

    def __init__(self, **kw):
        self.__dict__.update(kw)
        self._lodo = {}

    def lodo_rules(self, d):
        """Rule 22: the rules with day d left out of every normal level (one set per day, cached)."""
        if d not in self._lodo:
            self._lodo[d] = Rules(self.store, self.train_days, leave_out=d)
        return self._lodo[d]


def side_max(rules, index, others, s):
    """Rules 14 and 15: the largest known dfill among the other links; unknown if all are unknown."""
    known = [v for v in (rules.dfill(index[o], s) for o in others) if v is not None]
    return max(known) if known else None


def max_strict(rules, index, others, s):
    """NOT the rule; only to show what 'ignoring unknown values' changes: unknown as soon as one is unknown."""
    values = [rules.dfill(index[o], s) for o in others]
    return None if any(v is None for v in values) else max(values)


def compute_row(ctx, lid, t, rules=None, strict_conn=False, strict_nbr=False):
    R, idx = rules or ctx.rules, ctx.store.index
    i, s0, d0 = idx[lid], tindex(t), t.date()
    name = ctx.links[lid].name
    out = {"LinkID": lid, "t": t, "date": d0, "road": ROAD_GROUPS.get(name, name),   # rule 20
           "daytype": daytype(d0), "split": split_of(d0)}
    out["U"] = R.unusual(i, s0)                                           # rule 9
    for col, minutes in LABELS:                                           # rule 10
        out[col] = R.unusual(i, s0 + minutes // 5)
    filled = 0
    for k in LAGS:                                                        # rule 12
        s = s0 - k // 5
        v = R.dfill(i, s)
        out[f"f_d{k}"] = v
        filled += R.deficit(i, s) is None and v is not None
    out["f_n_filled"] = filled
    out["f_d_change15"] = None if out["f_d0"] is None or out["f_d15"] is None else out["f_d0"] - out["f_d15"]
    for side, others in (("up", [a for a, _ in ctx.up.get(lid, [])]), ("dn", [b for b, _ in ctx.down.get(lid, [])])):
        out[f"f_{side}_none"] = 0 if others else 1                       # rule 14
        for k in LAGS:
            out[f"f_{side}_d{k}"] = ((max_strict if strict_nbr else side_max)(R, idx, others, s0 - k // 5)
                                     if others else 0.0)
    for side, roads in (("in", ctx.into.get(lid, [])), ("out", ctx.out_of.get(lid, []))):
        others = [c for c, _ in roads]                                    # rule 15
        values = [(max_strict if strict_conn else side_max)(R, idx, others, s0 - k // 5) if others else 0.0
                  for k in LAGS]
        out[f"f_conn_{side}_none"] = 0 if others else 1
        out[f"f_conn_{side}_missing"] = 1 if others and any(v is None for v in values) else 0
        for k, v in zip(LAGS, values):
            out[f"f_conn_{side}_d{k}"] = 0.0 if v is None else v
    sid, km = ctx.station[lid]                                            # rule 16
    readings = ctx.readings.get(sid, {})
    for col, minutes in RAIN:
        got = [readings[t - timedelta(minutes=m)] for m in minutes if t - timedelta(minutes=m) in readings]
        out[col] = rain_total(got) if got else 0.0
        out[f"{col}_missing"] = 0 if got else 1
    out["f_slot15"] = slot15(t)                                           # rule 17
    for wd, col in enumerate(WEEKDAY_COLS):
        out[col] = 1 if d0.weekday() == wd else 0
    out["f_holiday"] = 1 if d0 in HOLIDAYS else 0
    needed = ([out[f"f_d{k}"] for k in LAGS] + [out["f_d_change15"], out["f_n_filled"]]
              + [out[f"f_{side}_d{k}"] for side in ("up", "dn") for k in LAGS]
              + [out["f_up_none"], out["f_dn_none"], out["f_rain15"], out["f_rain30"], out["f_rain15_missing"],
                 out["f_rain30_missing"], out["f_slot15"], out["f_holiday"]] + [out[c] for c in WEEKDAY_COLS])
    out["use"] = out["y"] is not None and out["U"] is not None and all(v is not None for v in needed)   # rule 19
    out["info_band"] = ctx.store.band_at(i, s0)                           # rule 20
    out["info_norm_band"] = R.norm_at(i, s0)
    out["info_deficit"] = R.deficit(i, s0)
    out["info_low"] = R.low(i, s0)
    out["info_rain_mm"] = readings.get(t)
    out["info_station_id"] = sid
    out["info_station_km"] = round(km, KM_DECIMALS)                       # rule 21
    out["info_school_period"] = SCHOOL.get(d0)
    out["info_retrieved"] = ctx.store.retrieved_at(i, s0)
    return out


# ======================================================================================================
# Comparison
# ======================================================================================================

def kind_of(col, dtype):
    if col in EXACT_COLS:
        return "exact float"
    if dtype in (pl.Float32, pl.Float64):
        return "float"
    if dtype == pl.Boolean:
        return "bool"
    if dtype.is_integer():
        return "int"
    return "exact"


def same(kind, mine, theirs):
    if mine is None or theirs is None:
        return mine is None and theirs is None            # null equals only null
    if kind == "float":
        return abs(float(mine) - float(theirs)) <= FLOAT_TOL
    if kind == "exact float":
        return float(mine) == float(theirs)
    if kind == "bool":
        return type(mine) is bool and mine == theirs
    if kind == "int":
        return type(mine) is int and mine == theirs
    return mine == theirs


class Check:
    def __init__(self, name, compared=0, mismatches=0, detail="", examples=None):
        self.name, self.compared, self.mismatches, self.detail = name, compared, mismatches, detail
        self.examples = examples or []


def compare_rows(rows, mine_rows, schema):
    """Every column of every row: {column: [(LinkID, t, mine, table), ...]} for the mismatches."""
    results = {}
    for col, dtype in schema.items():
        kind = kind_of(col, dtype)
        results[col] = [(row["LinkID"], row["t"], mine.get(col, "<not computed>"), row[col])
                        for row, mine in zip(rows, mine_rows)
                        if not same(kind, mine.get(col, "<not computed>"), row[col])]
    return results


def same_value(x, y):
    if x is None or y is None:
        return x is None and y is None
    if isinstance(x, float) or isinstance(y, float):
        return abs(x - y) <= FLOAT_TOL
    return x == y


def compare_maps(name, mine, theirs, what, fields=None):
    """Two dicts key -> value (a value or a tuple of values); report keys missing on either side and
    different values (floats within 1e-6). `fields` names the parts of a tuple, for the examples."""
    examples = []
    only_mine = sorted(set(mine) - set(theirs))
    only_theirs = sorted(set(theirs) - set(mine))
    differ = []
    for key in sorted(set(mine) & set(theirs)):
        a, b = mine[key], theirs[key]
        a_t, b_t = (a if isinstance(a, tuple) else (a,)), (b if isinstance(b, tuple) else (b,))
        if len(a_t) != len(b_t) or not all(same_value(x, y) for x, y in zip(a_t, b_t)):
            differ.append((key, a, b))
    for key in only_mine[:3]:
        examples.append(f"only mine: {key} {mine[key]}")
    for key in only_theirs[:3]:
        examples.append(f"only in the table: {key} {theirs[key]}")
    for key, a, b in differ[:3]:
        if fields and isinstance(a, tuple) and isinstance(b, tuple) and len(a) == len(b):
            parts = [f"{f} mine {x!r}, table {y!r}" for f, x, y in zip(fields, a, b) if not same_value(x, y)]
            examples.append(f"{key}: " + "; ".join(parts))
        else:
            examples.append(f"{key}: mine {a!r}, table {b!r}")
    n_bad = len(only_mine) + len(only_theirs) + len(differ)
    detail = (f"{len(set(mine) | set(theirs)):,} {what}; only mine {len(only_mine)}, only table "
              f"{len(only_theirs)}, different {len(differ)}")
    return Check(name, len(set(mine) | set(theirs)), n_bad, detail, examples)


# ======================================================================================================
# Whole-table checks
# ======================================================================================================

def check_use_rows(small_path, full_path):
    """(a) train.parquet (test.parquet) holds exactly the use rows of full_table (test_full), with identical
    values in its columns."""
    name = f"(a) {os.path.basename(small_path)} = use rows of {os.path.basename(full_path)}"
    if not (os.path.exists(small_path) and os.path.exists(full_path)):
        return Check(name, 0, 1, "one of the two files is missing")
    use = pl.scan_parquet(full_path).select("use").collect()["use"].fill_null(False)
    t_keys = pl.scan_parquet(small_path).select("LinkID", "t").collect()
    f_keys = pl.scan_parquet(full_path).select("LinkID", "t").collect().filter(use)
    order_t = order_f = None
    if not t_keys.equals(f_keys):                     # not in the same order: compare after sorting by key
        t_keys = t_keys.with_row_index("i").sort("LinkID", "t")
        f_keys = f_keys.with_row_index("i").sort("LinkID", "t")
        if not t_keys.select("LinkID", "t").equals(f_keys.select("LinkID", "t")):
            n_t, n_f = t_keys.height, f_keys.height
            both = t_keys.join(f_keys, on=["LinkID", "t"], how="inner").height
            return Check(name, max(n_t, n_f), n_t + n_f - 2 * both,
                         f"(LinkID, t) sets differ: {n_t:,} rows, use rows {n_f:,}, common {both:,}")
        order_t, order_f = t_keys["i"], f_keys["i"]
    t_schema = pl.read_parquet_schema(small_path)
    f_schema = pl.read_parquet_schema(full_path)
    bad, examples, compared = 0, [], 0
    for col, dtype in t_schema.items():
        if col not in f_schema or f_schema[col] != dtype:
            bad += 1
            examples.append(f"{col}: type {dtype} here, {f_schema.get(col)} in the full table")
            continue
        a = pl.scan_parquet(small_path).select(col).collect()[col]
        b = pl.scan_parquet(full_path).select(col).collect()[col].filter(use)
        if order_t is not None:
            a, b = a.gather(order_t), b.gather(order_f)
        n = int(a.ne_missing(b).sum())
        compared += a.len()
        if n:
            bad += n
            examples.append(f"{col}: {n:,} values differ")
    return Check(name, compared, bad,
                 f"{t_keys.height:,} rows x {len(t_schema)} columns; same (LinkID, t) set, order "
                 f"{'the same' if order_t is None else 'different (compared after sorting)'}", examples[:3])


def check_link_set(expressway):
    """(b) the links of full_table = the RoadCategory-1 links of the raw registry (2,598)."""
    ids = set(full_scan().select(pl.col("LinkID").unique()).collect()["LinkID"].to_list())
    only_t, only_m = sorted(ids - expressway), sorted(expressway - ids)
    bad = len(only_t) + len(only_m) + (len(expressway) != N_EXPRESSWAY)
    return Check("(b) links of full_table = RoadCategory-1 links", len(ids | expressway), bad,
                 f"table {len(ids):,}, registry {len(expressway):,} (rule 2: {N_EXPRESSWAY:,})",
                 [f"only in table: {x}" for x in only_t[:3]] + [f"only in registry: {x}" for x in only_m[:3]])


def check_norm_cells(rules, store, link_ids, path, name):
    """(c) every (daytype, slot15) cell of the given links in a norm table equals my median (rule 6)."""
    table = pl.read_parquet(path).filter(pl.col("LinkID").is_in(sorted(link_ids)))
    theirs = {(r["LinkID"], r["daytype"], r["slot15"]): (r["norm_band"], r["n_obs"], r["n_days"])
              for r in table.iter_rows(named=True)}
    mine = {}
    for lid in link_ids:
        for dt in DAYTYPES:
            for slot in range(96):
                m, n_obs, n_days = rules.norm_cell(store.index[lid], dt, slot)
                if m is not None:
                    mine[(lid, dt, slot)] = (m, n_obs, n_days)
    return compare_maps(name, mine, theirs, "cells (norm_band, n_obs, n_days)", ("norm_band", "n_obs", "n_days"))


def check_grid_and_days(expressway, days):
    """(d) split and day type of every row as its date implies; every link x 5-min time 06:00-21:55
    on every day covered (2,598 x 192 rows a day), no duplicates, and t on the date of the row."""
    lf = full_scan()
    examples, bad = [], 0
    combos = lf.group_by("date", "daytype", "split").agg(pl.len().alias("rows")).collect(engine="streaming")
    for d, dt, sp, n in combos.iter_rows():
        if dt != daytype(d) or sp != split_of(d):
            bad += n
            examples.append(f"{d}: table {dt}/{sp}, rules {daytype(d)}/{split_of(d)} ({n:,} rows)")
    wrong_date = lf.select((pl.col("t").dt.date() != pl.col("date")).sum()).collect(engine="streaming").item()
    bad += wrong_date
    if wrong_date:
        examples.append(f"{wrong_date:,} rows whose t is not on their date")
    per_day = dict(lf.group_by("date").agg(pl.len()).collect(engine="streaming").iter_rows())
    times = lf.select("date", "t").unique().collect(engine="streaming")
    times_by_day = defaultdict(set)
    for d, t in times.iter_rows():
        times_by_day[d].add(t)
    expected_per_day = N_EXPRESSWAY * 192
    for d in days:
        want = {datetime.combine(d, FIRST_ROW) + k * STEP for k in range(192)}
        assert max(want).time() == LAST_ROW
        if per_day.get(d, 0) != expected_per_day or times_by_day.get(d, set()) != want:
            bad += 1
            examples.append(f"{d}: {per_day.get(d, 0):,} rows (want {expected_per_day:,}), "
                            f"{len(times_by_day.get(d, ()))} times (want 192)")
    extra_days = sorted(set(per_day) - set(days))
    bad += len(extra_days)
    n_rows = lf.select(pl.len()).collect(engine="streaming").item()
    n_keys = lf.select(pl.struct("LinkID", "t").n_unique()).collect(engine="streaming").item()
    n_links = lf.select(pl.col("LinkID").n_unique()).collect(engine="streaming").item()
    if n_keys != n_rows:
        bad += n_rows - n_keys
        examples.append(f"{n_rows - n_keys:,} duplicate (LinkID, t)")
    if n_links != len(expressway):
        bad += 1
    # with the right row count per day, only valid times, only the 2,598 links and no duplicates,
    # every link x time is present (counting argument)
    return Check("(d) split, day type, every link x 06:00-21:55 time", n_rows, bad,
                 f"{len(days)} days x {expected_per_day:,} rows = {len(days) * expected_per_day:,}; "
                 f"table {n_rows:,} rows, {n_keys:,} distinct (LinkID, t)", examples[:3])


def check_rain_totals(paths):
    """(e) rule 16: a rain total is exact - never below 0, never in (0, 0.1), always a whole number of tenths
    (x == round(x, 1)), never null - over every row of the given files."""
    bad, compared, examples = 0, 0, []
    for path in paths:
        lf = pl.scan_parquet(path)
        for col in ("f_rain15", "f_rain30"):
            r = lf.select(pl.len().alias("rows"), (pl.col(col) < 0).sum().alias("below 0"),
                          ((pl.col(col) > 0) & (pl.col(col) < 0.1)).sum().alias("in (0, 0.1)"),
                          (pl.col(col) != pl.col(col).round(1)).sum().alias("not whole tenths"),
                          pl.col(col).is_null().sum().alias("null")).collect(engine="streaming").row(0, named=True)
            compared += r["rows"]
            n_bad = r["below 0"] + r["in (0, 0.1)"] + r["not whole tenths"] + r["null"]
            bad += n_bad
            if n_bad:
                examples.append(f"{os.path.basename(path)} {col}: {r}")
    return Check("(e) rain totals: never < 0, never in (0, 0.1), whole tenths", compared, bad,
                 "f_rain15 and f_rain30, every row of " + " and ".join(os.path.basename(p) for p in paths),
                 examples[:3])


def check_lodo_days(train_days):
    """train_lodo (rule 22) holds only train days (all of them), with split, day type and date as rules 3-4."""
    lf = pl.scan_parquet(LODO)
    combos = lf.group_by("date", "daytype", "split").agg(pl.len().alias("rows")).collect(engine="streaming")
    bad, examples = 0, []
    for d, dt, sp, n in combos.iter_rows():
        if d not in train_days or dt != daytype(d) or sp != "train":
            bad += n
            examples.append(f"{d}: {dt}/{sp} ({n:,} rows)")
    wrong_date = lf.select((pl.col("t").dt.date() != pl.col("date")).sum()).collect(engine="streaming").item()
    missing = sorted(set(train_days) - set(combos["date"].to_list()))
    bad += wrong_date + len(missing)
    if missing:
        examples.append(f"train days without rows: {missing[:3]}")
    return Check("train_lodo: only and all train days; split, day type", int(combos["rows"].sum()), bad,
                 f"{combos['date'].n_unique()} days (train days: {len(train_days)})", examples[:3])


# ======================================================================================================
# train_lodo (rule 22): a sample of rows, and whole days
# ======================================================================================================

def draw_lodo_sample(rng, total):
    """About `total` rows of train_lodo spread evenly over its days (so over every day type), about a quarter
    of each day's rows with y TRUE. The table's y is used only to choose rows."""
    keys = pl.scan_parquet(LODO).select(pl.col("t").dt.date().alias("day"), "y").with_row_index("row_nr").collect()
    days = sorted(keys["day"].unique().to_list())
    per_day = math.ceil(total / len(days))
    chosen = []
    for d in days:
        day = keys.filter(pl.col("day") == d)
        rows_y, rows_all = day.filter(pl.col("y"))["row_nr"], day["row_nr"]
        pick = {rows_y[p] for p in rng.sample(range(rows_y.len()), min(rows_y.len(), round(per_day / 4)))}
        for p in rng.sample(range(rows_all.len()), min(rows_all.len(), 2 * per_day)):
            if len(pick) >= per_day:
                break
            pick.add(rows_all[p])
        chosen.extend(sorted(pick))
    rows = (pl.scan_parquet(LODO).with_row_index("row_nr").filter(pl.col("row_nr").is_in(chosen))
            .collect(engine="streaming"))
    return rows


def lodo_whole_day(ctx, d, leave_out=True):
    """Rule 22 for every expressway link x 06:00-21:55 time of train day d: (use, y, U) with day d left out of
    every normal level. The same rules as compute_row, done for a whole day at once (it is much faster).
    leave_out=False gives the normal level of rule 6, only to count what leaving the day out changes."""
    R = Rules(ctx.store, ctx.train_days, leave_out=d if leave_out else None)
    idx = ctx.store.index
    first = (d - BASE.date()).days * PER_DAY + 72        # 06:00
    last = first + 191                                    # 21:55
    lo, hi = first - 7, last + 3                          # 05:25 (f_d30 may reuse it) .. 22:10 (y needs it)
    D = {lid: [R.deficit(idx[lid], s) for s in range(lo, hi + 1)] for lid in ctx.expressway}

    def fill(arr, k):                                     # rule 11 on the day's list of deficits
        v = arr[k]
        return v if v is not None else arr[k - 1]

    out = {}
    for lid, arr in D.items():
        sides = [[D[a] for a, _ in ctx.up.get(lid, [])], [D[b] for b, _ in ctx.down.get(lid, [])]]
        lows = [None if v is None else v >= LOW_FROM for v in arr]
        for s0 in range(first, last + 1):
            k = s0 - lo
            u = None if lows[k] is None or lows[k - 1] is None else (lows[k] and lows[k - 1])          # rule 9
            y = None if lows[k + 3] is None or lows[k + 2] is None else (lows[k + 3] and lows[k + 2])  # rule 10
            use = u is not None and y is not None and all(fill(arr, k - j) is not None for j in range(7))
            if use:                                       # rule 14: a side with links needs one known value
                use = not any(others and all(fill(o, k - j) is None for o in others)
                              for others in sides for j in range(7))
            out[(lid, time_of(s0))] = (use, y, u)         # rule 19 (rain, slot, day inputs are always known)
    return out


# ======================================================================================================
# Working for a mismatch: my values next to the raw rows
# ======================================================================================================

def raw_rows(files, lid, t_from, t_to):
    """Raw rows of one link with last_updated in [t_from, t_to], from files fetched in [t_from - 5 min, t_to + 3 h]."""
    lo, hi = t_from.strftime("%Y-%m-%d %H:%M:%S"), t_to.strftime("%Y-%m-%d %H:%M:%S")
    out = []
    for fetched, path in files:
        if t_from - STEP <= fetched <= t_to + timedelta(hours=3):
            df = pl.read_csv(path, infer_schema=False).filter(
                (pl.col("LinkID") == lid) & (pl.col("last_updated") >= lo) & (pl.col("last_updated") <= hi))
            for r in df.iter_rows():
                out.append(f"{os.path.relpath(path, PROJECT)}: {','.join(x or '' for x in r)}")
    return out


def explain(ctx, files, lid, t, col, rules=None):
    R, idx = rules or ctx.rules, ctx.store.index
    s0 = tindex(t)
    lodo = f" (normal level without {R.leave_out})" if R.leave_out else ""
    print(f"    working for {col} at LinkID {lid}, t {fmt(t)}{lodo}:")
    if col.startswith(("f_rain", "info_rain", "info_station")):     # rule 16: station and readings
        link = ctx.links[lid]
        lat, lon = (link.start_lat + link.end_lat) / 2, (link.start_lon + link.end_lon) / 2
        near3 = sorted((haversine_km(lat, lon, *ctx.stations[s]), s) for s in ctx.eligible)[:3]
        print(f"      link start ({link.start_lat}, {link.start_lon}) end ({link.end_lat}, {link.end_lon}), "
              f"midpoint ({lat:.7f}, {lon:.7f}); nearest eligible stations: "
              + ", ".join(f"{s} {ctx.stations[s]} {km:.9f} km" for km, s in near3))
        sid, km = ctx.station[lid]
        rd = ctx.readings.get(sid, {})
        print(f"      station {sid}: readings t-30..t: "
              + ", ".join(f"{(t - timedelta(minutes=m)):%H:%M}={fmt(rd.get(t - timedelta(minutes=m)))}"
                          for m in range(30, -5, -5)))
        return
    groups = [("link", [lid]), ("upstream", [a for a, _ in ctx.up.get(lid, [])]),
              ("downstream", [b for b, _ in ctx.down.get(lid, [])]),
              ("road into", [c for c, _ in ctx.into.get(lid, [])]),
              ("road out of", [c for c, _ in ctx.out_of.get(lid, [])])]
    for label, ids in groups:
        for o in ids:
            i = idx[o]
            cells = []
            for k in range(-7, 7):
                s = s0 + k
                b, n, d = ctx.store.band_at(i, s), R.norm_at(i, s), R.deficit(i, s)
                cells.append(f"{time_of(s):%H:%M} b={fmt(b)} n={fmt(n)} d={fmt(d)}")
            print(f"      {label} {o}: " + "; ".join(cells))
    lines = raw_rows(files, lid, t - timedelta(minutes=35), t + timedelta(minutes=30))
    print(f"      raw rows of {lid}, last_updated t-35 .. t+30 ({len(lines)} rows):")
    for line in lines[:60]:
        print(f"        {line}")


# ======================================================================================================
# Corner cases and coverage
# ======================================================================================================

def mixed_at_some_lag(rules, index, others, s0):
    """True when, at one of the lags, some (not all) of the other links have an unknown dfill."""
    for k in LAGS:
        vals = [rules.dfill(index[o], s0 - k // 5) for o in others]
        if any(v is None for v in vals) and any(v is not None for v in vals):
            return True
    return False


def find_corner_rows(ctx, cand14, cand15, days, per_rule):
    """Rows where rule 14 or rule 15 meets a mix of known and unknown values (some, not all, neighbours or
    joining roads unknown at one lag). The random sample has almost none, so look for them on purpose
    (seeded: random link and 5-min time, keep the hits)."""
    rng = random.Random(SEED + 15)
    found = {}
    for rule, cand, sides in ((14, cand14, (ctx.up, ctx.down)), (15, cand15, (ctx.into, ctx.out_of))):
        rows, tries = set(), 0
        while cand and len(rows) < per_rule and tries < 2000 * per_rule:
            tries += 1
            lid = rng.choice(cand)
            t = datetime.combine(rng.choice(days), FIRST_ROW) + rng.randrange(192) * STEP
            for side in sides:
                others = [o for o, _ in side.get(lid, [])]
                if len(others) > 1 and mixed_at_some_lag(ctx.rules, ctx.store.index, others, tindex(t)):
                    rows.add((lid, t))
                    break
        found[rule] = sorted(rows)
    return found


def coverage(ctx, mine_rows):
    """How many sampled rows tested each rule (by my values), so that an OK means something."""
    R, idx = ctx.rules, ctx.store.index
    c = Counter()
    for m in mine_rows:
        lid, s0 = m["LinkID"], tindex(m["t"])
        c[f"daytype {m['daytype']}"] += 1
        c[f"split {m['split']}"] += 1
        c["public holiday"] += m["f_holiday"] == 1
        c["use TRUE"] += m["use"] is True
        c["use FALSE"] += m["use"] is False
        c["U TRUE"] += m["U"] is True
        c["U null"] += m["U"] is None
        c["y TRUE"] += m["y"] is True
        c["y null"] += m["y"] is None
        c["no band at t"] += m["info_band"] is None
        c["normal level x.5 (even count)"] += m["info_norm_band"] is not None and m["info_norm_band"] % 1 != 0
        c["a reused value (f_n_filled > 0)"] += m["f_n_filled"] > 0
        c["an unknown f_d value"] += any(m[f"f_d{k}"] is None for k in LAGS)
        c["no upstream link"] += m["f_up_none"] == 1
        c["no downstream link"] += m["f_dn_none"] == 1
        c["an unknown neighbour value"] += any(m[f"f_{s}_d{k}"] is None for s in ("up", "dn") for k in LAGS)
        c["2+ neighbours on a side"] += len(ctx.up.get(lid, [])) > 1 or len(ctx.down.get(lid, [])) > 1
        c["some (not all) neighbours or roads unknown at a lag"] += any(
            mixed_at_some_lag(R, idx, [o for o, _ in side.get(lid, [])], s0)
            for side in (ctx.up, ctx.down, ctx.into, ctx.out_of))
        c["a road into the link"] += m["f_conn_in_none"] == 0
        c["a road out of the link"] += m["f_conn_out_none"] == 0
        c["f_conn_*_missing = 1"] += m["f_conn_in_missing"] == 1 or m["f_conn_out_missing"] == 1
        c["rain > 0 in 15 min"] += m["f_rain15"] > 0
        c["rain reading missing (f_rain30_missing = 1)"] += m["f_rain30_missing"] == 1
    return c


# ======================================================================================================
# Main
# ======================================================================================================

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--rows", type=int, default=3000, help="rows to sample from full_table (default 3000)")
    ap.add_argument("--corner-rows", type=int, default=100,
                    help="extra rows per corner case of rules 14 and 15 (default 100; 0 = none)")
    ap.add_argument("--lodo-rows", type=int, default=500, help="rows to sample from train_lodo (default 500)")
    ap.add_argument("--workers", type=int, default=8, help="threads that read files (default 8)")
    args = ap.parse_args()
    rng = random.Random(SEED)
    checks, notes = [], []
    if not os.path.exists(RULES_FILE):
        notes.append(f"{os.path.relpath(RULES_FILE, PROJECT)} not found: the rule numbers in this script refer to it")

    load_calendar()
    n_settings, bad_settings = check_settings()
    checks.append(Check("data_settings.py holds the numbers of the rules", n_settings, len(bad_settings),
                        "compared only; this script uses its own copy",
                        [f"{k}: rules {a}, settings {b}" for k, a, b in bad_settings[:3]]))

    # ---- 1. the tables, the days they cover, the sample of full_table ----
    keys = full_scan().select("LinkID", "t", "use", "U", "y").with_row_index("row_nr").collect()
    days = sorted(keys["t"].dt.date().unique().to_list())
    first_day, last_day = days[0], days[-1]
    assert first_day >= BASE.date(), "the table starts before the first training day"
    all_days = [first_day + timedelta(days=k) for k in range((last_day - first_day).days + 1)]
    train_days = [d for d in all_days if split_of(d) == "train"]
    log(f"full_table: {keys.height:,} rows, {len(days)} days {first_day} .. {last_day}")

    n = args.rows
    weekend_days = [d for d in days if d.weekday() >= 5 or d in HOLIDAYS]
    strata = [("onset positive (use, U FALSE, y TRUE)", round(0.20 * n),
               keys.filter(pl.col("use") & pl.col("U").eq(False) & pl.col("y"))),
              ("use FALSE", round(0.15 * n), keys.filter(pl.col("use").not_())),
              ("Saturday, Sunday or public holiday", round(0.15 * n),
               keys.filter(pl.col("t").dt.date().is_in(weekend_days))),
              ("random use TRUE", None, keys.filter(pl.col("use")))]
    chosen, counts = set(), []
    for label, k, frame in strata:
        k = n - len(chosen) if k is None else k
        rows = frame["row_nr"]
        picked = 0
        for p in rng.sample(range(rows.len()), min(rows.len(), k + len(chosen))):
            r = rows[p]
            if r not in chosen:
                chosen.add(r)
                picked += 1
                if picked == k:
                    break
        counts.append(f"{picked} {label}")
    del keys, strata
    sample = (full_scan().with_row_index("row_nr")
              .filter(pl.col("row_nr").is_in(sorted(chosen))).collect(engine="streaming"))
    schema = {c: d for c, d in sample.schema.items() if c != "row_nr"}
    sample_rows = sample.to_dicts()
    sample_links = sorted({r["LinkID"] for r in sample_rows})
    log(f"sample: {len(sample_rows):,} rows ({', '.join(counts)}), {len(sample_links):,} links")

    # ---- 2. registry: attributes, expressway links, neighbours, joining roads ----
    latest, reg_stats, reg_ties = read_registry(args.workers, last_day)
    links, bad_coords = {}, []
    for lid, (r, attrs) in latest.items():
        try:
            links[lid] = Link(lid, attrs)
        except (TypeError, ValueError):
            bad_coords.append(lid)
    expressway = {lid for lid, link in links.items() if link.category == EXPRESSWAY}
    log(f"registry: {reg_stats['files']} snapshot files up to {last_day}, {reg_stats['records']:,} records, "
        f"{len(latest):,} links, {len(expressway):,} expressway links (newest snapshot "
        f"{reg_stats['newest retrieved_at']})")
    for label, value in (("records without LinkID", reg_stats["records without LinkID"]),
                         ("records with unreadable retrieved_at", reg_stats["records with unreadable retrieved_at"]),
                         ("files out of time order", reg_stats["files out of time order"]),
                         ("files holding a link twice", reg_stats["files with a link twice"]),
                         ("links with two different records at the same retrieved_at", len(reg_ties)),
                         ("links whose coordinates do not parse", len(bad_coords))):
        if value:
            notes.append(f"registry: {value} {label}")

    down, up = find_neighbours(links, expressway)
    into, out_of = find_joining_roads(links, expressway)
    roads = {c for lst in itertools.chain(into.values(), out_of.values()) for c, _ in lst}
    log(f"neighbours: {sum(len(v) for v in down.values()):,} pairs; joining roads: {len(roads):,} roads, "
        f"{sum(len(v) for v in into.values()) + sum(len(v) for v in out_of.values()):,} pairs")

    # rule 21: gap_m rounded to 2 decimals
    nb_mine = {(a, b): round(gap, GAP_DECIMALS) for a, lst in down.items() for b, gap in lst}
    nb_tab = {(r[0], r[1]): r[2] for r in pl.read_parquet(NEIGHBOURS).select("LinkID", "downstream", "gap_m").iter_rows()}
    checks.append(compare_maps("neighbours.parquet (rules 13, 21), all pairs", nb_mine, nb_tab, "pairs (gap_m)"))
    cn_mine = {}
    for kind, table in (("into", into), ("out_of", out_of)):
        for lid, lst in table.items():
            for c, gap in lst:
                cn_mine[(c, lid, kind)] = (links[c].name, int(links[c].category), round(gap, GAP_DECIMALS))
    cn_tab = {(r["LinkID"], r["joins"], r["kind"]): (r["RoadName"], r["RoadCategory"], r["gap_m"])
              for r in pl.read_parquet(CONNECTORS).iter_rows(named=True)}
    checks.append(compare_maps("connectors.parquet (rules 15, 21), all pairs", cn_mine, cn_tab,
                               "pairs (RoadName, RoadCategory, gap_m)", ("RoadName", "RoadCategory", "gap_m")))

    # ---- 3. rain stations ----
    readings, stations, eligible, rain_stats = read_rain(train_days)
    station, ties = {}, 0
    for lid in expressway:
        sid, km, tie = nearest_station(links[lid], stations, eligible)
        station[lid] = (sid, km)
        ties += tie
    log(f"rain: {rain_stats['rows']:,} readings, {len(stations)} stations, {len(eligible)} with >= "
        f"{RAIN_MIN_READINGS} readings on every train day, {len(set(s for s, _ in station.values()))} used")
    if ties:
        notes.append(f"rain: {ties} links have two stations at the same distance")
    for label in ("unreadable rows", "same station and time twice", "readings below 0 or not whole tenths"):
        if rain_stats[label]:
            notes.append(f"rain: {rain_stats[label]} {label}")

    lk_cols = ["RoadName", "RoadCategory", "StartLon", "StartLat", "EndLon", "EndLat", "road", "n_downstream",
               "n_upstream", "n_roads_into", "n_roads_out_of", "station_id", "station_km"]
    lk_mine = {lid: (links[lid].name, int(links[lid].category), links[lid].start_lon, links[lid].start_lat,
                     links[lid].end_lon, links[lid].end_lat, ROAD_GROUPS.get(links[lid].name, links[lid].name),
                     len(down.get(lid, [])), len(up.get(lid, [])), len(into.get(lid, [])), len(out_of.get(lid, [])),
                     station[lid][0], round(station[lid][1], KM_DECIMALS)) for lid in expressway}
    lk_tab = {r[0]: tuple(r[1:]) for r in pl.read_parquet(LINKS).select(["LinkID"] + lk_cols).iter_rows()}
    checks.append(compare_maps(f"links.parquet ({len(lk_cols)} columns, rules 2, 13, 15, 16, 20, 21)", lk_mine,
                               lk_tab, "links (" + ", ".join(lk_cols) + ")", lk_cols))

    # ---- 4. raw speed bands: every expressway link and joining road (the whole-day checks need them all) ----
    norm_links = rng.sample(sample_links, min(50, len(sample_links)))
    cand14 = sorted(lid for lid in expressway if len(up.get(lid, [])) > 1 or len(down.get(lid, [])) > 1)
    cand15 = sorted(lid for lid in expressway if len(into.get(lid, [])) > 1 or len(out_of.get(lid, [])) > 1)
    if args.corner_rows <= 0:
        cand14, cand15 = [], []
    wanted = expressway | roads
    until = datetime.combine(last_day + timedelta(days=1), time(0, 0)) + LATE_FILES
    files, misplaced = list_speed_files(until)
    n_steps = tindex(until) + 1
    log(f"speed bands: reading {len(files):,} files fetched up to {until:%Y-%m-%d %H:%M} for {len(wanted):,} links")
    store, unreadable = read_speed_bands(files, wanted, args.workers, n_steps)
    st = store.stats
    log(f"speed bands: {st['rows read (all links)']:,} rows read, {st['rows of wanted links']:,} of the wanted links, "
        f"{st['link-updates kept']:,} link-updates kept, {st['repeats (same link and update again)']:,} repeats, "
        f"{st['repeats with a different band']:,} repeats with a different band")
    late, longest = store.late_rows()
    notes.append(f"speed bands: longest delay between update time and earliest fetch {longest / 60:.0f} min; "
                 f"kept bands first fetched after D+1 01:00: {late}")
    for label, value in st.items():
        if value and label not in ("rows read (all links)", "rows of wanted links", "link-updates kept",
                                   "repeats (same link and update again)"):
            notes.append(f"speed bands: {value:,} {label}; examples {store.examples}")
    if unreadable:
        notes.append(f"speed bands: {len(unreadable)} unreadable files, e.g. {unreadable[:2]}")
    if misplaced:
        notes.append(f"speed bands: {misplaced} files in a folder whose date is not the date in their name")

    # ---- 5. recompute every sampled row of full_table and compare every column ----
    rules = Rules(store, train_days)
    ctx = Context(rules=rules, store=store, links=links, up=up, down=down, into=into, out_of=out_of,
                  station=station, readings=readings, stations=stations, eligible=eligible,
                  train_days=train_days, expressway=sorted(expressway))
    mine_rows = [compute_row(ctx, r["LinkID"], r["t"]) for r in sample_rows]
    results = compare_rows(sample_rows, mine_rows, schema)
    log(f"compared {len(sample_rows):,} rows x {len(schema)} columns")

    # corner cases of rules 14 and 15 (some, not all, neighbours or joining roads unknown at a lag)
    corner = find_corner_rows(ctx, cand14, cand15, days, args.corner_rows)
    corner_rows, corner_mine, corner_teeth = [], [], {}
    for rule, keys_ in corner.items():
        if not keys_:
            continue
        part = (full_scan().filter(pl.col("LinkID").is_in(sorted({k[0] for k in keys_}))
                                   & pl.col("t").is_in(sorted({k[1] for k in keys_})))
                .collect(engine="streaming"))                # only these links and times (streaming: low memory)
        wanted_pairs = set(keys_)
        rows = [r for r in part.to_dicts() if (r["LinkID"], r["t"]) in wanted_pairs]
        mine = [compute_row(ctx, r["LinkID"], r["t"]) for r in rows]
        prefix = "f_conn_" if rule == 15 else ("f_up_", "f_dn_")
        corner_teeth[rule] = (len(rows), sum(
            any(alt[c] != m[c] for c in m if c.startswith(prefix) or c == "use")
            for m in mine for alt in [compute_row(ctx, m["LinkID"], m["t"], strict_conn=rule == 15,
                                                  strict_nbr=rule == 14)]))
        corner_rows += rows
        corner_mine += mine
    corner_results = compare_rows(corner_rows, corner_mine, schema)
    log(f"corner cases: {', '.join(f'rule {k}: {len(v)} rows' for k, v in corner.items())} "
        f"(links with 2+ neighbours: {len(cand14)}, with 2+ joining roads: {len(cand15)})")

    # ---- 6. train_lodo (rule 22): a sample of rows, and whole days ----
    lodo_rng = random.Random(SEED + 22)
    lodo_frame = draw_lodo_sample(lodo_rng, args.lodo_rows)
    lodo_schema = {c: d for c, d in lodo_frame.schema.items() if c != "row_nr"}
    lodo_rows = lodo_frame.to_dicts()
    lodo_mine = [compute_row(ctx, r["LinkID"], r["t"], rules=ctx.lodo_rules(r["t"].date())) for r in lodo_rows]
    lodo_results = compare_rows(lodo_rows, lodo_mine, lodo_schema)
    lodo_cov = Counter(r["daytype"] for r in lodo_rows)
    # does leaving the day out change anything in these rows? (else this check would prove little)
    lodo_teeth = sum(any(m[c] != reg[c] for c in lodo_schema) for m, reg in
                     zip(lodo_mine, (compute_row(ctx, r["LinkID"], r["t"]) for r in lodo_rows)))
    log(f"train_lodo sample: {len(lodo_rows)} rows over {len({r['t'].date() for r in lodo_rows})} days "
        f"({', '.join(f'{k} {v}' for k, v in sorted(lodo_cov.items()))}), y TRUE {sum(r['y'] is True for r in lodo_rows)}")
    # whole days: one of each day type, not the first train day (collection started at 11:20 that day)
    lodo_days = [lodo_rng.choice([d for d in train_days if daytype(d) == dt and d != train_days[0]]) for dt in DAYTYPES]
    sample_by_day = defaultdict(list)
    for r, m in zip(lodo_rows, lodo_mine):
        sample_by_day[r["t"].date()].append(m)
    for d in lodo_days:
        mine_day = lodo_whole_day(ctx, d)
        regular = lodo_whole_day(ctx, d, leave_out=False)
        day_teeth = sum(regular[key] != value for key, value in mine_day.items())
        del regular
        tab = pl.scan_parquet(LODO).filter(pl.col("t").dt.date() == d).select("LinkID", "t", "y", "U").collect()
        tab_rows = {(lid, t): (y, u) for lid, t, y, u in tab.iter_rows()}
        mine_use = {key for key, (use, _, _) in mine_day.items() if use}
        only_mine, only_tab = sorted(mine_use - tab_rows.keys()), sorted(tab_rows.keys() - mine_use)
        yu = [(key, mine_day[key][1:], v) for key, v in tab_rows.items() if key in mine_day and mine_day[key][1:] != v]
        # my own consistency: the whole-day shortcut must agree with compute_row on the sampled rows of that day
        own = sum(mine_day[(m["LinkID"], m["t"])] != (m["use"], m["y"], m["U"]) for m in sample_by_day[d]
                  if (m["LinkID"], m["t"]) in mine_day)
        examples = ([f"only mine: {k}" for k in only_mine[:2]] + [f"only in the table: {k}" for k in only_tab[:2]]
                    + [f"{k}: (y, U) mine {a}, table {b}" for k, a, b in yu[:2]])
        if own:
            examples.append(f"VERIFIER BUG: the whole-day shortcut disagrees with compute_row on {own} rows")
        checks.append(Check(f"(f) train_lodo {d} ({daytype(d)}): use rows, y, U", len(mine_day),
                            len(only_mine) + len(only_tab) + len(yu) + own,
                            f"every link x time: mine {len(mine_use):,} use rows, table {len(tab_rows):,}; only "
                            f"mine {len(only_mine)}, only table {len(only_tab)}, y/U differ {len(yu)}; leaving the "
                            f"day out changes (use, y, U) of {day_teeth:,} link-times", examples))
        log(f"train_lodo whole day {d} ({daytype(d)}): mine {len(mine_use):,} use rows, table {len(tab_rows):,}")
        del mine_day, tab, tab_rows, mine_use
    checks.append(check_lodo_days(train_days))

    # ---- 7. whole-table checks ----
    checks.append(check_norm_cells(rules, store, norm_links, NORM, "(c) norm.parquet, 50 sampled links"))
    conn_of_50 = sorted({c for lid in norm_links for c, _ in into.get(lid, []) + out_of.get(lid, [])})
    if conn_of_50:
        checks.append(check_norm_cells(rules, store, conn_of_50, CONN_NORM,
                                       f"(c) connector_norm.parquet, the {len(conn_of_50)} roads joining them"))
    cn_ids = set(pl.scan_parquet(CONN_NORM).select(pl.col("LinkID").unique()).collect()["LinkID"].to_list())
    checks.append(Check("connector_norm.parquet has exactly the joining roads", len(cn_ids | roads),
                        len(cn_ids ^ roads), f"table {len(cn_ids)}, mine {len(roads)}"))
    checks.append(check_use_rows(TRAIN, FULL))
    if os.path.exists(TEST) or os.path.exists(TEST_FULL):
        checks.append(check_use_rows(TEST, TEST_FULL))
    checks.append(check_link_set(expressway))
    checks.append(check_grid_and_days(expressway, all_days))
    checks.append(check_rain_totals(full_files() + [LODO]))
    # rule 18: day D is finished when the rainfall table has its 23:55 readings and it is D+1 02:00
    now = datetime.now()
    rain_2355 = {t.date() for rd in readings.values() for t in rd if t.hour == 23 and t.minute == 55}
    finished = [d for d in all_days + [last_day + timedelta(days=k) for k in range(1, 15)]
                if d in rain_2355 and now >= datetime.combine(d + timedelta(days=1), time(0, 0)) + FINISHED_AFTER]
    problems = ([f"finished but not in the table: {d}" for d in finished if d not in days]
                + [f"in the table but not finished: {d}" for d in days if d not in finished]
                + [f"missing day inside the range: {d}" for d in all_days if d not in days])
    checks.append(Check("table holds exactly the finished days (rule 18)", len(set(finished) | set(days)),
                        len(problems), f"table {first_day} .. {last_day}; finished now: "
                        f"{finished[0] if finished else '-'} .. {finished[-1] if finished else '-'}", problems[:3]))

    # ---- 8. report ----
    print()
    print("== Columns: mismatches per sample ==")
    print(f"{'column':<20} {'sample':>7} {'corner':>7} {'lodo':>6}  examples (LinkID, t, mine, table)")
    print(f"{'(rows compared)':<20} {len(sample_rows):>7,} {len(corner_rows):>7,} {len(lodo_rows):>6,}")
    total_bad, bad_cols, first_bad = 0, [], {}
    for col in schema:
        parts = [("", results[col]), ("corner ", corner_results.get(col, [])), ("lodo ", lodo_results.get(col))]
        counts_ = [len(b) if b is not None else None for _, b in parts]
        total_bad += sum(c for c in counts_ if c)
        ex = "; ".join(f"{tag}({lid}, {fmt(t)}, {fmt(a)}, {fmt(b)})" for tag, bad in parts if bad
                       for lid, t, a, b in bad[:3])
        print(f"{col:<20} {counts_[0]:>7} {counts_[1]:>7} {'-' if counts_[2] is None else counts_[2]:>6}  {ex}")
        if any(counts_):
            bad_cols.append(col)
            tag, bad = next((tag, bad) for tag, bad in parts if bad)
            first_bad[col] = (tag, bad[0])
    for rule, (n_rows, teeth) in corner_teeth.items():
        print(f"  corner rows for rule {rule}: {n_rows}; not ignoring unknown values would change {teeth} of them")
    print(f"  train_lodo rows: {len(lodo_rows)}; the normal level of rule 6 instead of rule 22 would change "
          f"{lodo_teeth} of them")

    print()
    print("== What the full_table sample covered (by my values) ==")
    items = sorted(coverage(ctx, mine_rows).items())
    for k in range(0, len(items), 3):
        print("  " + " | ".join(f"{label}: {value:,}" for label, value in items[k:k + 3]))

    print()
    print("== Other checks ==")
    print(f"{'check':<58} {'compared':>11} {'mismatches':>10}  detail")
    failed = 0
    for c in checks:
        print(f"{c.name:<58} {c.compared:>11,} {c.mismatches:>10,}  {c.detail}")
        for e in c.examples[:3]:
            print(f"{'':<82}e.g. {e}")
        failed += c.mismatches > 0

    conn_bad = {(lid, t) for c in bad_cols if c.startswith("f_conn_")
                for res in (results, corner_results) for lid, t, _, _ in res.get(c, [])}
    if conn_bad:
        table_rows = {(r["LinkID"], r["t"]): r for r in sample_rows + corner_rows}
        fixed = sum(all(same(kind_of(c, schema[c]), alt[c], table_rows[key][c]) for c in schema if c.startswith("f_conn_"))
                    for key in conn_bad if key in table_rows
                    for alt in [compute_row(ctx, key[0], key[1], strict_conn=True)])
        notes.append(f"f_conn_*: {fixed} of {len(conn_bad)} rows with a mismatch would match if unknown joining roads "
                     f"were NOT ignored (that is not rule 15)")

    if bad_cols:
        print()
        print("== Working for the first mismatch of each column (at most 10) ==")
        seen = set()
        for col in bad_cols:
            tag, (lid, t, a, b) = first_bad[col]
            if (tag, lid, t) in seen or len(seen) >= 10:
                print(f"  {col}: see above ({tag}LinkID {lid}, t {fmt(t)})" if (tag, lid, t) in seen else "")
                continue
            seen.add((tag, lid, t))
            print(f"  {col} ({tag or 'sample '}row): mine {fmt(a)}, table {fmt(b)}")
            explain(ctx, files, lid, t, col, ctx.lodo_rules(t.date()) if tag == "lodo " else None)

    print()
    print("== Notes ==")
    for msg in notes:
        print(f"- {msg}")
    print("- links.parquet columns not checked (not defined in the rules): first_seen, last_seen, n_snapshots, "
          "n_attribute_versions, n_categories, presence_snapshots, presence_week1, in_population")
    peak_gb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 ** 2
    print(f"- run time {wallclock.time() - START:.0f} s, peak memory {peak_gb:.2f} GB")
    print()
    main_rows = len(sample_rows) + len(corner_rows)
    what = (f"{main_rows:,} rows x {len(schema)} columns + {len(lodo_rows):,} train_lodo rows x {len(lodo_schema)} "
            f"columns compared")
    if total_bad == 0 and failed == 0:
        print(f"VERIFY: OK ({what}, 0 mismatches)")
        return 0
    print(f"VERIFY: FAILED ({what}; {total_bad:,} mismatches in {len(bad_cols)} columns; "
          f"{failed} of {len(checks)} other checks failed)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
