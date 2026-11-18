"""build_data.py - SLDS 42.510 project 1.3: raw LTA files -> model tables (data version 4).

    .venv/bin/python analysis/build_data.py          (./build_processed.sh runs this, checks it and uploads)

Reads only the raw collector folders (data_raw/, data_raw_expressway/) and the rainfall and calendar tables that
get_context_data.py downloads. Everything is rebuilt from scratch on every run (no cache), so the same raw files
always give the same tables. Every step is checked; a failed check stops the build with "CHECK FAILED". Files are
written to model.tmp/ and clean.tmp/ and only swapped in when everything has passed, so a failed or killed build
leaves the last good tables in place. Only finished days are used (a day is finished at 02:00 the next day, once
its rainfall is downloaded), so rerunning on the same day gives the same files.

Writes
  data_processed/model/      the copy on Google Drive (SLDS_1.3_processed):
      README.md              what every column means, rules, quick start (written by this script)
      train.parquet          usable rows of the train and validate days (column split), model columns only, only
                             the proposal's days (Mon-Fri, no public holiday); held-out roads flagged (heldout_road)
      test.parquet           the same for the test days (once they exist; on Drive only after the freeze)
      extra/                 everything else (see README.md)
  data_processed/clean/      link registry and the cleaned speed-band panel (all hours), local only
  docs/model_data/           README.md, build_info.json, days.csv, SHA256SUMS.txt (versioned in git)

Settings: data_settings.py. Steps: data_steps.py (tested in test_data_steps.py). Independent check of sample
rows from the raw files: verify_data.py.
AI disclosure: drafted with Claude (Anthropic) on 14 Nov 2026; log in AI_USE.md.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import random
import resource
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # data_settings, data_steps (also under python -I)

import numpy as np   # noqa: E402
import polars as pl  # noqa: E402

import data_settings as S  # noqa: E402
import data_steps as D     # noqa: E402

SGT = timezone(timedelta(hours=8))
PROJ = Path(os.environ.get("SLDS_PROJECT_DIR") or Path(__file__).resolve().parent.parent)
PROC = PROJ / "data_processed"
OUT, CLEAN, DOCS = PROC / "model", PROC / "clean", PROJ / "docs" / "model_data"
TMP_OUT, TMP_CLEAN = PROC / "model.tmp", PROC / "clean.tmp"
CODE_FILES = ["analysis/data_settings.py", "analysis/data_steps.py", "analysis/build_data.py",
              "analysis/test_data_steps.py"]
LINK_CHUNK = 650          # links per pass over the 5-min grid (keeps memory low next to the collectors)
TEXT = ("road", "daytype", "split", "info_station_id", "info_school_period")   # Enum in memory, text in files


class Checks:
    """Every check is printed, kept for build_info.json, and stops the build when it fails."""

    def __init__(self) -> None:
        self.items: list[dict] = []

    def __call__(self, name: str, ok, detail="") -> None:
        ok = bool(ok)
        self.items.append({"check": name, "ok": ok, "detail": str(detail)})
        print(f"  {'ok  ' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail != "" else ""), flush=True)
        if not ok:
            raise SystemExit(f"CHECK FAILED: {name} [{detail}]. The tables in data_processed/model/ were not changed.")


def log(msg: str) -> None:
    print(f"[{datetime.now(SGT):%H:%M:%S}] {msg}", flush=True)


def peak_mb() -> int:
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def digest_files(files: list[Path]) -> dict:
    """One fingerprint for a set of raw files: sha256 over 'path size sha256' lines, in path order."""
    with ThreadPoolExecutor(8) as ex:
        sums = list(ex.map(sha256, files))
    lines = "".join(f"{f.relative_to(PROJ).as_posix()} {f.stat().st_size} {s}\n" for f, s in zip(files, sums))
    return {"files": len(files), "bytes": sum(f.stat().st_size for f in files),
            "digest": hashlib.sha256(lines.encode()).hexdigest()}


def git_commit() -> str:
    try:
        c = subprocess.run(["git", "-C", str(PROJ), "rev-parse", "--short", "HEAD"], capture_output=True,
                           text=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(PROJ), "status", "--porcelain", "--", *CODE_FILES],
                               capture_output=True, text=True).stdout.strip()
        return c + ("-modified" if dirty else "")
    except OSError:
        return "unknown"


def folder_date(p: Path) -> date | None:
    try:
        return date.fromisoformat(p.parent.name)
    except ValueError:
        return None


def jsonable(v):
    if isinstance(v, date):
        return str(v)
    if isinstance(v, (tuple, list)):
        return [jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): jsonable(x) for k, x in v.items()}
    return v


def settings_dict() -> dict:
    return {k: jsonable(v) for k, v in vars(S).items() if k.isupper() and k != "DATA_CHANGES"}


def swap_in(tmp: Path, final: Path) -> None:
    """Replace final by tmp; the old folder is removed only after the new one is in place."""
    old = final.with_name(final.name + ".old")
    if old.exists():
        shutil.rmtree(old)
    if final.exists():
        final.rename(old)
    tmp.rename(final)
    if old.exists():
        shutil.rmtree(old)


def row_problems(rows: pl.DataFrame, pairs: pl.DataFrame, holidays: set[date], conn: pl.DataFrame,
                 clagged: pl.DataFrame) -> list[tuple[str, int, str]]:
    """The checks every finished table of rows must pass: (name, number of bad rows, detail).
    Each reads only the columns it needs. Time joins (not row shifts) test that every look-back and the label
    sit at the right time; links with a single neighbour or joining road test the neighbour inputs at t."""
    core, extra_in = D.core_input_columns(), D.connector_input_columns()
    use = pl.col("use")

    def n_bad(*conds) -> int:
        return rows.lazy().filter(*conds).select(pl.len()).collect().item()

    out = [("one row per link and time", int(rows.select(pl.struct("LinkID", "t").is_duplicated().sum()).item()), ""),
           ("every row has its split, day type, road and both flags",
            n_bad(pl.any_horizontal(pl.col("split", "daytype", "road", "in_population", "heldout_road").is_null())), ""),
           ("use rows: no input, y or U missing",
            n_bad(use, pl.any_horizontal([pl.col(c).is_null() for c in core + extra_in + ["y", "U"]])), ""),
           ("use rows: band captured now, and f_d0 is the real drop now (never reused)",
            n_bad(use, pl.col("band").is_null() | (pl.col("f_d0") != pl.col("deficit"))), "")]
    k = rows.select("LinkID", "t", "U", "deficit")
    prev = k.select("LinkID", (pl.col("t") + D.STEP).alias("t"), pl.col("deficit").alias("prev"))
    j = k.join(prev, on=["LinkID", "t"], how="inner")
    out.append(("U is null exactly when the drop now or 5 min ago is missing",
                j.filter(pl.col("U").is_null() != (pl.col("deficit").is_null() | pl.col("prev").is_null())).height,
                f"{j.height:,} pairs"))
    ahead = k.select("LinkID", (pl.col("t") - timedelta(minutes=S.HORIZON)).alias("t"), pl.col("U").alias("ahead"))
    j = rows.select("LinkID", "t", "y").join(ahead, on=["LinkID", "t"], how="inner")
    out.append(("y equals U 15 min later (time join)", j.filter(pl.col("y").ne_missing(pl.col("ahead"))).height,
                f"{j.height:,} pairs"))
    del k, prev, ahead, j
    for col, m in (("f_d", 5), ("f_d", 15), ("f_d", 30), ("f_up_d", 5), ("f_up_d", 30), ("f_dn_d", 5),
                   ("f_dn_d", 30), ("f_conn_in_d", 5), ("f_conn_in_d", 30), ("f_conn_out_d", 5), ("f_conn_out_d", 30)):
        back = rows.select("LinkID", (pl.col("t") + timedelta(minutes=m)).alias("t"), pl.col(f"{col}0").alias("back"))
        j = rows.select("LinkID", "t", f"{col}{m}").join(back, on=["LinkID", "t"], how="inner")
        out.append((f"{col}{m} equals {col}0 {m} min earlier (time join)",
                    j.filter(pl.col(f"{col}{m}").ne_missing(pl.col("back"))).height, f"{j.height:,} pairs"))
    own = rows.select(pl.col("LinkID").alias("nbr"), "t", pl.col("f_d0").alias("theirs"))
    for side, a, b in (("dn", "LinkID", "downstream"), ("up", "downstream", "LinkID")):
        one = (pairs.group_by(a).agg(pl.len().alias("n"), pl.col(b).first().alias("nbr"))
                    .filter(pl.col("n") == 1).select(pl.col(a).alias("LinkID"), "nbr"))
        j = rows.select("LinkID", "t", f"f_{side}_d0").join(one, on="LinkID").join(own, on=["nbr", "t"], how="left")
        out.append((f"f_{side}_d0 = the f_d0 of the only {'downstream' if side == 'dn' else 'upstream'} link at the same t",
                    j.filter(pl.col(f"f_{side}_d0").ne_missing(pl.col("theirs"))).height, f"{j.height:,} rows"))
    for kind, side in (("into", "in"), ("out_of", "out")):
        one = (conn.filter(pl.col("kind") == kind).group_by("joins").agg(pl.len().alias("n"), pl.col("LinkID").first().alias("nbr"))
                   .filter(pl.col("n") == 1).select(pl.col("joins").alias("LinkID"), "nbr"))
        j = (rows.select("LinkID", "t", f"f_conn_{side}_d0").join(one, on="LinkID")
                 .join(clagged.select("nbr", "t", "d0"), on=["nbr", "t"], how="left"))
        out.append((f"f_conn_{side}_d0 = the drop of the only joining road at the same t (0 if missing)",
                    j.filter(pl.col(f"f_conn_{side}_d0") != pl.col("d0").fill_null(0)).height, f"{j.height:,} rows"))
    expect_day = (pl.when(pl.col("is_holiday") | (pl.col("weekday") == 7)).then(pl.lit("sunday_or_holiday"))
                    .when(pl.col("weekday") == 6).then(pl.lit("saturday")).otherwise(pl.lit("weekday")))
    in_split = pl.lit(False)
    for sp, (a, b) in S.SPLITS.items():
        in_split = in_split | ((pl.col("split").cast(pl.Utf8) == sp) & pl.col("date").is_between(a, b))
    # a rain total is 0 or at least one tenth of a mm (no rounding leftovers), and always a whole number of tenths
    exact = [(pl.col(c) < 0) | ((pl.col(c) > 0) & (pl.col(c) < 0.1 - 1e-9))
             | ((pl.col(c) * 10 - (pl.col(c) * 10).round()).abs() > 1e-9) for c in S.RAIN_WINDOWS]
    out += [("low = drop >= 2", n_bad(pl.col("low").ne_missing(pl.col("deficit") >= S.THRESHOLD)), ""),
            ("f_n_filled is 0-7, and 0-5 on use rows (now and 5 min ago are never reused there)",
             n_bad(~pl.col("f_n_filled").is_between(0, 7) | (use & (pl.col("f_n_filled") > 5))), ""),
            ("exactly one of f_mon ... f_sun is 1", n_bad(pl.sum_horizontal(S.WEEKDAY_COLUMNS) != 1), ""),
            ("f_holiday matches the public-holiday list",
             n_bad(pl.col("f_holiday") != pl.col("date").is_in(sorted(holidays)).cast(pl.Int8)), ""),
            ("day type matches weekday and holiday", n_bad(pl.col("daytype").cast(pl.Utf8) != expect_day), ""),
            ("in_population = Monday to Friday and not a public holiday",
             n_bad(pl.col("in_population") != ((pl.col("weekday") <= 5) & ~pl.col("is_holiday"))), ""),
            ("heldout_road = the road is one of the held-out roads (AYE, CTE)",
             n_bad(pl.col("heldout_road") != pl.col("road").cast(pl.Utf8).is_in(list(S.EXPECTED_HELDOUT))), ""),
            ("f_slot15 is 24-87 (06:00-22:00)", n_bad(~pl.col("f_slot15").is_between(24, 87)), ""),
            ("rain totals are 0 or whole tenths of a mm (no leftovers below 0.1 mm, never below 0)",
             n_bad(pl.any_horizontal(exact)), ""),
            ("rain over 15 min <= rain over 30 min", n_bad(pl.col("f_rain15") > pl.col("f_rain30")), ""),
            ("rain missing flag = 1 only with a total of 0",
             n_bad(pl.any_horizontal([(pl.col(f"{c}_missing") == 1) & (pl.col(c) != 0) for c in S.RAIN_WINDOWS])), ""),
            ("split matches the date", n_bad(~in_split), "")]
    return out


def label_summary(r: pl.DataFrame) -> dict:
    """Shares of U and y on the rows of the main files (usable, population days), overall and on the rows that
    are normal now (the scoring rows)."""
    r = r.lazy().filter(pl.col("use") & pl.col("in_population")).select("date", "U", "y").collect()
    onset = r.filter(~pl.col("U"))
    return {"days": r["date"].n_unique(), "use_rows": r.height, "share_U": round(r["U"].mean(), 4),
            "share_y": round(r["y"].mean(), 4), "onset_rows": onset.height,
            "onset_rows_y_true": int(onset["y"].sum()), "share_y_onset": round(onset["y"].mean(), 4)}


# ----------------------------------------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--now", help="build as if it were this time, 'YYYY-MM-DD HH:MM' (to rebuild an earlier state)")
    ap.add_argument("--out-root", help="write model/, clean/ and the docs copy under this folder instead (test builds)")
    args = ap.parse_args()
    global OUT, CLEAN, DOCS, TMP_OUT, TMP_CLEAN
    if args.out_root:
        root = Path(args.out_root).resolve()
        OUT, CLEAN, DOCS = root / "model", root / "clean", root / "docs_model_data"
        TMP_OUT, TMP_CLEAN = root / "model.tmp", root / "clean.tmp"
    now = datetime.strptime(args.now, "%Y-%m-%d %H:%M") if args.now else datetime.now(SGT).replace(tzinfo=None)
    t_start = time.time()
    check = Checks()
    log(f"build_data.py, data version {S.DATA_VERSION}, as of {now:%Y-%m-%d %H:%M}")
    for tmp in (TMP_OUT, TMP_CLEAN):             # leftovers of a failed run
        if tmp.exists():
            shutil.rmtree(tmp)
    (TMP_OUT / "extra").mkdir(parents=True)
    TMP_CLEAN.mkdir(parents=True)

    # ---- 1. calendar, rainfall, finished days ----
    log("1. calendar and rainfall (from get_context_data.py)")
    cal = pl.read_csv(PROC / "calendar_2026.csv", try_parse_dates=True,
                      schema_overrides={"is_public_holiday": pl.Boolean})
    check("calendar: one row per date", not cal["date"].is_duplicated().any())
    holidays = set(cal.filter(pl.col("is_public_holiday"))["date"].to_list())
    check("calendar: Deepavali (Sun 8 Nov) and its holiday (Mon 9 Nov) are public holidays",
          {date(2026, 11, 8), date(2026, 11, 9)} <= holidays, sorted(str(d) for d in holidays if d.month in (10, 11, 12)))
    rain_raw = pl.read_csv(PROC / "rainfall_5min.csv.gz",
                           schema_overrides={"station_id": pl.Utf8, "timestamp": pl.Utf8, "rain_mm": pl.Float64})
    rain = rain_raw.select(D.parse_sgt(pl.col("timestamp")).alias("t"), "station_id", "rain_mm")
    del rain_raw
    check("rainfall: every timestamp parses", rain["t"].null_count() == 0, f"{rain['t'].null_count()} not parsed")
    check("rainfall: one reading per station and time", not rain.select(pl.struct("station_id", "t").is_duplicated().any()).item())
    tenths = pl.col("rain_mm") * 10
    check("rainfall: readings are >= 0 mm and whole tenths of a mm",
          rain.filter((pl.col("rain_mm") < 0) | ((tenths - tenths.round()).abs() > 1e-9)).height == 0)
    check("rainfall: times on the 5-min grid", rain.filter(pl.col("t").dt.minute() % 5 != 0).height == 0)
    stations = pl.read_csv(PROC / "rain_stations.csv", schema_overrides={"station_id": pl.Utf8})

    first_day = S.SPLITS["train"][0]
    last_planned = max(b for _, b in S.SPLITS.values())
    rain_last = rain.filter(pl.col("t").dt.hour() == 23, pl.col("t").dt.minute() == 55)["t"].max().date()
    finished_by_clock = (now - timedelta(hours=S.FINISHED_AFTER_H)).date() - timedelta(days=1)
    cutoff = min(finished_by_clock, rain_last, last_planned)
    check("at least the first training day is finished", cutoff >= first_day, f"cutoff {cutoff}")
    days = D.day_table(first_day, cutoff, holidays)
    log(f"   finished days {first_day} to {cutoff} (clock allows {finished_by_clock}, rainfall to {rain_last})")
    check("calendar covers every day", set(days["date"].to_list()) <= set(cal["date"].to_list()))

    # ---- 2. link registry from the hourly raw snapshots, one day at a time ----
    log("2. link registry (raw JSON snapshots of the whole network)")
    reg_files = sorted(f for f in (PROJ / S.REGISTRY_SOURCE / "speedbands_raw").glob("*/sbraw_*.jsonl.gz")
                       if (folder_date(f) or date.max) <= cutoff)
    check("registry: raw snapshot files found", len(reg_files) > 0, len(reg_files))
    versions, pages, no_id = [], [], 0
    by_day: dict[date, list[Path]] = {}
    for f in reg_files:
        by_day.setdefault(folder_date(f), []).append(f)
    first_no = 0
    for day_files in by_day.values():           # ~3.5 M records a day; only the attribute versions are kept
        with ThreadPoolExecutor(8) as ex:
            snaps = pl.concat(list(ex.map(D.read_registry_file, day_files,
                                          range(first_no, first_no + len(day_files)))))
        first_no += len(day_files)
        pages.append(snaps.group_by("file_no").agg(pl.col("page").n_unique().alias("pages")))
        no_id += snaps["LinkID"].null_count()
        versions.append(D.registry_versions(snaps))
        del snaps
    pages = pl.concat(pages)
    full = pages.filter(pl.col("pages") == 288).height
    check("registry: every snapshot file read", pages.height == len(reg_files), pages.height)
    check("registry: >= 95% of snapshot files have all 288 pages", full >= 0.95 * len(reg_files), f"{full} of {len(reg_files)}")
    check("registry: every record has a LinkID", no_id == 0)
    registry = D.build_registry(pl.concat(versions), len(reg_files))
    del versions
    check("registry: coordinates parse for every link", registry.select(pl.any_horizontal(pl.col(D.COORDS).is_null()).sum()).item() == 0)
    xw = registry.filter(pl.col("RoadCategory") == S.EXPRESSWAY_CATEGORY)
    xw_ids = sorted(xw["LinkID"].to_list())
    check("registry: expressway links = the 2,598 in DECISIONS.md (if LTA changed its links, that needs a decision)",
          len(xw_ids) == S.EXPECTED_EXPRESSWAY_LINKS, len(xw_ids))
    check("registry: no expressway link changed road category", xw.filter(pl.col("n_categories") > 1).height == 0)
    check("registry: expressway links whose name or coordinates changed (latest used)", True,
          xw.filter(pl.col("n_attribute_versions") > 1).height)
    log(f"   {registry.height:,} links in {len(reg_files)} snapshots; {len(xw_ids):,} expressway")

    # ---- 3. roads that join the expressway links ----
    log("3. roads joining the expressway links")
    conn = D.connector_pairs(registry, xw_ids)
    conn_ids = sorted(conn["LinkID"].unique().to_list())
    check("joining roads: none is an expressway link", not set(conn_ids) & set(xw_ids))
    check("joining roads: every gap <= tolerance", conn.filter(pl.col("gap_m") > S.CONNECTOR_TOL_M).height == 0)
    log(f"   {len(conn_ids)} joining links, {conn.height} pairs, serving {conn['joins'].n_unique()} expressway links")

    # ---- 4. speed bands: both collectors -> one row per link and LTA update ----
    log("4. speed bands from both collectors")
    late_limit = datetime.combine(cutoff + timedelta(days=1), datetime.min.time()) + timedelta(minutes=S.LATE_ROWS_MIN)
    sb_files = []
    for src in S.SPEED_SOURCES:
        for f in (PROJ / src / "speedbands").glob("*/sb_*.csv.gz"):
            ft, fd = D.file_time(f), folder_date(f)
            if ft is not None and fd is not None and fd <= cutoff + timedelta(days=1) and ft <= late_limit:
                sb_files.append((ft, src, f.name, f))
    sb_files.sort()
    check("speed bands: files found in both collector folders",
          all(any(s == src for _, s, _, _ in sb_files) for src in S.SPEED_SOURCES), len(sb_files))
    keep_ids = xw_ids + conn_ids
    by_fetch_day: dict[date, list] = {}
    for item in sb_files:
        by_fetch_day.setdefault(item[0].date(), []).append(item)
    parts, sb_stats, lag, over_midnight, file_no = [], {}, 0, 0, 0
    for items in by_fetch_day.values():          # one fetch day at a time keeps memory low ...
        with ThreadPoolExecutor(8) as ex:
            raw = pl.concat(list(ex.map(lambda a: D.read_speedband_file(a[1][3], keep_ids, a[0]),
                                        enumerate(items, start=file_no))))
        file_no += len(items)
        lag = max(lag, raw.select((pl.col("retrieved") - pl.col("t")).dt.total_minutes().max()).item() or 0)
        late = raw.filter(pl.col("retrieved").dt.date() > pl.col("t").dt.date())   # a day's rows fetched after midnight
        if late.height:
            over_midnight = max(over_midnight, late.select(
                (pl.col("retrieved") - pl.col("retrieved").dt.truncate("1d")).dt.total_minutes().max()).item())
        part, st = D.clean_speedbands(raw)
        del raw, late
        for k, v in st.items():
            sb_stats[k] = sb_stats.get(k, 0) + v
        parts.append(part)
    stacked = pl.concat(parts)                   # ... then the same rule across fetch days (rows just after midnight)
    del parts
    panel, st2 = D.clean_speedbands(stacked.select(
        "retrieved", "t", "LinkID", pl.col("band").cast(pl.Int64).alias("SpeedBand"),
        pl.lit(0, pl.Int32).alias("file_no"), pl.int_range(pl.len(), dtype=pl.UInt32).alias("row_no")))
    del stacked
    sb_stats["conflicts"] += st2["conflicts"]
    sb_stats["link_updates_fetched_twice_or_more"] += st2["link_updates_fetched_twice_or_more"]
    sb_stats["rows_kept"] = st2["rows_kept"]
    sb_stats["longest_fetch_delay_min"], sb_stats["latest_after_midnight_min"] = lag, over_midnight
    panel = panel.filter(pl.col("t").dt.date().is_between(first_day, cutoff))
    sb_stats["rows_in_finished_days"] = panel.height
    bad_max = int(S.BAD_ROWS_MAX_SHARE * sb_stats["rows_read"])
    check("speed bands: rows without LTA's update time (dropped) at most 0.1%", sb_stats["no_update_time"] <= bad_max,
          sb_stats["no_update_time"])
    check("speed bands: every row has a retrieval time", sb_stats["no_retrieval_time"] == 0)
    check("speed bands: SpeedBand outside 1-8 (band left empty) at most 0.1%", sb_stats["band_outside_1_8"] <= bad_max,
          sb_stats["band_outside_1_8"])
    check("speed bands: a link and update fetched twice never disagree", sb_stats["conflicts"] == 0,
          f"{sb_stats['conflicts']} conflicts in {sb_stats['link_updates_fetched_twice_or_more']:,} repeats")
    check("speed bands: rows of a day fetched after midnight all arrive within the late-file window",
          over_midnight <= S.LATE_ROWS_MIN, f"latest {over_midnight} min after midnight; longest delay overall {lag} min")
    check("panel: one row per link and update", not panel.select(pl.struct("LinkID", "t").is_duplicated().any()).item())
    check("panel: every update time on the 5-min grid",
          panel.filter((pl.col("t").dt.minute() % 5 != 0) | (pl.col("t").dt.second() != 0)).height == 0)
    per_day = panel.group_by(pl.col("t").dt.date().alias("date")).agg(pl.col("t").n_unique().alias("updates"))
    check("panel: every finished day has data", per_day.height == days.height, f"{per_day.height} of {days.height} days")
    log(f"   {len(sb_files):,} files, {sb_stats['rows_read']:,} rows read, {panel.height:,} kept "
        f"({sb_stats['link_updates_fetched_twice_or_more']:,} fetched more than once)")

    # ---- 5. population, neighbours, rain stations ----
    log("5. population, neighbours, rain stations")
    pres, n_week_updates = D.presence_week1(panel, xw_ids)
    links = (xw.join(pres, on="LinkID", how="left")
               .with_columns((pl.col("presence_week1") >= S.PRESENCE_MIN).alias("in_population"),
                             pl.col("RoadName").replace(S.ROAD_GROUPS).alias("road")))
    pop = links.filter("in_population").sort("LinkID")
    pop_ids = pop["LinkID"].to_list()
    check("population: every expressway link kept (presence >= 90%)", len(pop_ids) == S.EXPECTED_EXPRESSWAY_LINKS,
          f"{len(pop_ids)}; presence {links['presence_week1'].min():.3f}-{links['presence_week1'].max():.3f} "
          f"of {n_week_updates} updates")
    held = D.heldout_roads(pop["road"].unique().to_list())
    links = links.with_columns((pl.col("in_population") & pl.col("road").is_in(held)).alias("heldout_road"))
    n_held = links.filter("heldout_road").height
    check("held-out roads: the seeded draw gives AYE and CTE, as in data versions 1-2",
          tuple(held) == S.EXPECTED_HELDOUT, f"{held}, {n_held} links")
    pairs = D.neighbour_pairs(pop)
    check("neighbours: every gap <= tolerance", pairs.filter(pl.col("gap_m") > S.NEIGHBOUR_TOL_M).height == 0)
    check("neighbours: no link is its own neighbour", pairs.filter(pl.col("LinkID") == pl.col("downstream")).height == 0)

    # rain station: the nearest one with readings in >= RAIN_STATION_MIN_SHARE of the 5-min slots on every
    # training day (decided from training days only, so it stays the same as new days are added)
    train_days = days.filter(pl.col("split") == "train")["date"].to_list()
    per_station = (rain.filter(pl.col("t").dt.date().is_in(train_days))
                       .group_by("station_id", pl.col("t").dt.date().alias("d")).len()
                       .filter(pl.col("len") >= S.RAIN_STATION_MIN_SHARE * 288)
                       .group_by("station_id").len())
    good = sorted(per_station.filter(pl.col("len") == len(train_days))["station_id"].to_list())
    check("rain: stations with readings in >= 80% of slots on every training day", len(good) >= 30,
          f"{len(good)} of {stations.height}")
    near = D.nearest_station(pop, stations.filter(pl.col("station_id").is_in(good)))
    used = sorted(near["station_id"].unique().to_list())
    check("rain: every link has a station within 10 km", near["station_km"].max() <= 10, f"max {near['station_km'].max()} km")
    cov = (rain.filter(pl.col("station_id").is_in(used))
               .group_by(pl.col("t").dt.date().alias("date")).len()
               .with_columns((pl.col("len") / (len(used) * 288)).alias("share")))
    cov = days.select("date").join(cov, on="date", how="left").with_columns(pl.col("share").fill_null(0.0))
    low_days = cov.filter(pl.col("share") < S.RAIN_DAY_MIN_SHARE)
    check("rain: every finished day has readings in >= 80% of the used stations' slots (else re-download that day)",
          low_days.height == 0,
          f"lowest {cov['share'].min():.3f}" + (f"; low: {[str(x) for x in low_days['date']]}" if low_days.height else ""))
    links = (links.join(near, on="LinkID", how="left")
                  .join(pairs.group_by("LinkID").len().rename({"len": "n_downstream"}), on="LinkID", how="left")
                  .join(pairs.group_by("downstream").len().rename({"downstream": "LinkID", "len": "n_upstream"}),
                        on="LinkID", how="left")
                  .join(conn.filter(pl.col("kind") == "into").group_by("joins").len()
                            .rename({"joins": "LinkID", "len": "n_roads_into"}), on="LinkID", how="left")
                  .join(conn.filter(pl.col("kind") == "out_of").group_by("joins").len()
                            .rename({"joins": "LinkID", "len": "n_roads_out_of"}), on="LinkID", how="left")
                  .with_columns(pl.col("n_downstream", "n_upstream", "n_roads_into", "n_roads_out_of").fill_null(0))
                  .sort("LinkID"))
    updates_06_22 = (panel.filter(pl.col("LinkID").is_in(pop_ids) & D.in_hours(pl.col("t")))
                          .group_by(pl.col("t").dt.date().alias("date")).agg(pl.col("t").n_unique().alias("updates_06_22")))
    registry.write_parquet(TMP_CLEAN / "link_registry.parquet")
    panel.write_parquet(TMP_CLEAN / "panel.parquet")

    # ---- 6. normal level, frozen from the training days ----
    log("6. normal level per link x day type x 15-min slot (training days only)")
    pxw = panel.filter(pl.col("LinkID").is_in(pop_ids))
    pcn = panel.filter(pl.col("LinkID").is_in(conn_ids))
    del panel
    norm, cnorm = D.normal_level(pxw, days), D.normal_level(pcn, days)
    n_train_by_type = days.filter(pl.col("split") == S.NORM_SPLIT).group_by("daytype").len()
    check("norm: built from training days only (n_days <= training days of that type)",
          norm.join(n_train_by_type, on="daytype").filter(pl.col("n_days") > pl.col("len")).height == 0,
          dict(n_train_by_type.sort("daytype").iter_rows()))
    check("norm: every value between 1 and 8", norm.filter(~pl.col("norm_band").is_between(1, 8)).height == 0)
    need = (pl.DataFrame({"LinkID": pop_ids}).join(pl.DataFrame({"daytype": list(S.DAYTYPES)}), how="cross")
              .join(pl.DataFrame({"slot15": pl.int_range(22, 91, eager=True).cast(pl.Int16)}), how="cross"))
    gaps = need.join(norm, on=["LinkID", "daytype", "slot15"], how="anti").height
    check("norm: link x day type x slot cells missing for 05:30-22:44 (rows there get no label)",
          gaps <= 0.001 * need.height, f"{gaps} of {need.height:,}")
    recheck = (pxw.with_columns(pl.col("t").dt.date().alias("date"), D.slot15(pl.col("t")).alias("slot15"))
                  .join(days.filter(pl.col("split") == "train").select("date", "daytype"), on="date")
                  .filter(pl.col("band").is_not_null())
                  .group_by("LinkID", "daytype", "slot15").agg(pl.col("band").sort().alias("b"))
                  .sort("LinkID", "daytype", "slot15"))
    sample = recheck.sample(2000, seed=7).join(norm, on=["LinkID", "daytype", "slot15"])
    check("norm: 2,000 cells recomputed with numpy give the same median",
          np.array_equal(np.array([float(np.median(b)) for b in sample["b"].to_list()]), sample["norm_band"].to_numpy()))
    del recheck, sample

    # ---- 7. labels and inputs on the regular 5-min grid, a chunk of links at a time ----
    log("7. labels and inputs on the 5-min grid")
    t_from = datetime.combine(first_day, datetime.min.time())
    t_to = datetime.combine(cutoff, datetime.min.time()) + timedelta(hours=23, minutes=55)
    window_days = days.filter(pl.col("split").is_not_null())
    wdates = window_days["date"].to_list()
    base_parts = []
    for i in range(0, len(pop_ids), LINK_CHUNK):
        ids = pop_ids[i:i + LINK_CHUNK]
        base_parts.append(D.base_rows(pxw.filter(pl.col("LinkID").is_in(ids)), norm, days, ids, t_from, t_to, wdates))
    base = pl.concat(base_parts)
    del base_parts
    check("rows: one per link and 5-min time, 06:00-22:00, finished days",
          base.height == len(pop_ids) * len(wdates) * (S.HOUR_TO - S.HOUR_FROM) * 12, f"{base.height:,}")
    win = D.in_hours(pl.col("t")) & pl.col("date").is_in(wdates)
    clagged = D.lag_table(D.add_lags(D.deficit_grid(pcn, cnorm, days, conn_ids, t_from, t_to), prefix="c_").filter(win),
                          prefix="c_")
    lagged = D.lag_table(base)
    rin = D.rain_inputs(rain, used, t_from, t_to)
    rain_now = rain.filter(pl.col("station_id").is_in(used)).rename({"rain_mm": "rain_now"})
    e_station = pl.Enum(used)
    wd = window_days.select("date", "weekday", "is_holiday", pl.col("daytype").cast(pl.Enum(list(S.DAYTYPES))),
                            pl.col("split").cast(pl.Enum(list(S.SPLITS))), "in_population")
    road = links.select("LinkID", pl.col("road").cast(pl.Enum(sorted(links["road"].unique().to_list()))),
                        "heldout_road")
    school = cal.select(pl.col("date").cast(pl.Date),
                        pl.col("school_period").cast(pl.Enum(sorted(cal["school_period"].drop_nulls().unique().to_list()))))
    parts: dict[str, list] = {sp: [] for sp in S.SPLITS}
    for i in range(0, len(pop_ids), LINK_CHUNK):
        r = D.assemble(base.filter(pl.col("LinkID").is_in(pop_ids[i:i + LINK_CHUNK])), pairs, lagged, conn, clagged,
                       near, rin, rain_now, wd, road, school).with_columns(pl.col("station_id").cast(e_station))
        for sp in S.SPLITS:                        # one table per split: no full copy is ever filtered later
            p = r.filter(pl.col("split") == sp)
            if p.height:
                parts[sp].append(p)
        del r
    by_split = {sp: pl.concat(v) for sp, v in parts.items() if v}
    rows = pl.concat(list(by_split.values()), rechunk=False)   # all splits, for the checks (no copy)
    check("rows: the input steps kept every row (no join added or lost one)", rows.height == base.height,
          f"{rows.height:,}")
    del parts, base, lagged

    # ---- 8. checks on the finished rows ----
    log("8. checks on the rows (one day at a time: no check crosses midnight, and memory stays low)")
    bad_total: dict[str, int] = {}
    for sp, frame in by_split.items():
        for d in frame["date"].unique().sort().to_list():
            for name, bad, _ in row_problems(frame.filter(pl.col("date") == d), pairs, holidays, conn, clagged):
                bad_total[name] = bad_total.get(name, 0) + bad
    for name, bad in bad_total.items():
        check(f"rows: {name}", bad == 0, f"{len(wdates)} days" if bad == 0 else f"{bad:,} bad")
    summary = {sp: label_summary(by_split[sp]) for sp in ("train", "validate") if sp in by_split}
    check("labels: share of unusual rows (U) in train is 0.5%-10%", 0.005 <= summary["train"]["share_U"] <= 0.10,
          summary["train"]["share_U"])
    inc_files = sorted(f for f in (PROJ / S.INCIDENT_SOURCE / "feeds" / "incidents").glob("*/incidents_*.jsonl.gz")
                       if (folder_date(f) or date.max) <= cutoff)
    with ThreadPoolExecutor(8) as ex:
        isnaps = pl.concat(list(ex.map(D.read_incident_file, inc_files, range(len(inc_files)))), how="vertical_relaxed")
    check("incidents: read every saved snapshot", isnaps["snap_no"].n_unique() == len(inc_files), len(inc_files))
    incidents = D.incident_episodes(isnaps)
    del isnaps

    # ---- 9. write the main tables (rows in order: split, link, time) ----
    log("9. writing the main tables")
    core, extra_in, model_in = D.core_input_columns(), D.connector_input_columns(), D.model_input_columns()
    main_cols = ["LinkID", "road", "heldout_road", "t", "date", "daytype", "split", "y", "U"] + model_in + extra_in
    info = {"band": "info_band", "norm_band": "info_norm_band", "deficit": "info_deficit", "low": "info_low",
            "rain_now": "info_rain_mm", "station_id": "info_station_id", "station_km": "info_station_km",
            "school_period": "info_school_period", "retrieved": "info_retrieved"}
    full_cols = (["LinkID", "road", "heldout_road", "t", "date", "daytype", "split", "in_population", "use", "y",
                  *[f"y_h{h}" for h in S.EXTRA_HORIZONS], "U"] + core + extra_in
                 + [pl.col(a).alias(b) for a, b in info.items()])

    def table(df: pl.DataFrame, cond, cols) -> pl.LazyFrame:
        lf = (df.lazy() if cond is None else df.lazy().filter(cond)).select(cols)
        names = lf.collect_schema().names()
        return lf.with_columns([pl.col(c).cast(pl.Utf8) for c in TEXT if c in names])

    n: dict = {}
    use = pl.col("use")
    keep = use & pl.col("in_population")         # the main files: usable rows of the proposal's days
    tv = pl.concat([by_split[sp] for sp in ("train", "validate") if sp in by_split], rechunk=False)
    table(tv, None, full_cols).sink_parquet(TMP_OUT / "extra" / "full_table.parquet")
    table(tv, keep, main_cols).sink_parquet(TMP_OUT / "train.parquet")
    n["extra/full_table.parquet"] = tv.height
    n["train.parquet"] = {sp: summary[sp]["use_rows"] for sp in summary}
    free_ids = sorted(links.filter(pl.col("in_population") & ~pl.col("heldout_road"))["LinkID"].to_list())
    sample_ids = sorted(random.Random(S.SAMPLE_SEED).sample(free_ids, S.SAMPLE_LINKS))
    smp = table(tv, keep & pl.col("LinkID").is_in(sample_ids), main_cols).collect()
    smp.write_parquet(TMP_OUT / "extra" / "train_sample.parquet")
    n["extra/train_sample.parquet"] = smp.height
    del smp
    if "test" in by_split:
        table(by_split["test"], keep, main_cols).sink_parquet(TMP_OUT / "test.parquet")
        table(by_split["test"], None, full_cols).sink_parquet(TMP_OUT / "extra" / "test_full.parquet")
        n["test.parquet"] = by_split["test"].lazy().filter(keep).select(pl.len()).collect().item()
        n["extra/test_full.parquet"] = by_split["test"].height
    rdays = (rows.lazy().group_by("date")
                 .agg(pl.len().alias("rows"), pl.col("band").is_not_null().mean().alias("share_captured"),
                      use.sum().alias("use_rows"), use.mean().alias("share_use"),
                      pl.col("f_rain15_missing").mean().alias("share_rain_missing")).collect())
    del rows, tv, by_split
    for f, expect in (("train.parquet", sum(n["train.parquet"].values())),
                      ("extra/full_table.parquet", n["extra/full_table.parquet"])):
        lf = pl.scan_parquet(TMP_OUT / f)
        check(f"written: {f} holds every row once", lf.select(pl.len()).collect().item() == expect
              and not lf.select(pl.struct("LinkID", "t").is_duplicated().any()).collect().item(), f"{expect:,} rows")
    tdays = set(pl.scan_parquet(TMP_OUT / "train.parquet").select(pl.col("date").unique()).collect()["date"].to_list())
    want = set(days.filter(pl.col("in_population") & pl.col("split").is_in(["train", "validate"]))["date"].to_list())
    check("written: train.parquet holds exactly the proposal's days (Mon-Fri, no public holiday) of train and validate",
          tdays == want, f"{len(tdays)} days; only in file {sorted(tdays - want)}, missing {sorted(want - tdays)}")
    check("written: train.parquet has none of " + ", ".join(S.NOT_IN_MAIN_FILES),
          not set(S.NOT_IN_MAIN_FILES) & set(pl.read_parquet_schema(TMP_OUT / "train.parquet")))
    links.write_parquet(TMP_OUT / "extra" / "links.parquet")
    pairs.write_parquet(TMP_OUT / "extra" / "neighbours.parquet")
    conn.write_parquet(TMP_OUT / "extra" / "connectors.parquet")
    norm.write_parquet(TMP_OUT / "extra" / "norm.parquet")
    cnorm.write_parquet(TMP_OUT / "extra" / "connector_norm.parquet")
    incidents.write_parquet(TMP_OUT / "extra" / "incidents.parquet")
    n["extra/incidents.parquet"] = incidents.height

    # ---- 10. the train days again, each with a normal level built without that day ----
    # PROJECT_PLAN §4.9 sensitivity check: in train.parquet a train day is part of its own normal level (1 of the
    # 16 weekdays), which makes its labels a little easier. Same columns and days as the train rows of train.parquet.
    log("10. leave-own-day-out version of the train days")
    lodo_days = days.filter((pl.col("split") == "train") & pl.col("in_population"))["date"].to_list()
    lodo_dir = TMP_OUT / "lodo_parts"
    lodo_dir.mkdir()
    bad_total = {}
    excl_bad, lodo_sum = 0, []
    pxw = pxw.with_columns(pl.col("t").dt.date().alias("date"))
    pcn = pcn.with_columns(pl.col("t").dt.date().alias("date"))
    for d in lodo_days:
        days_d = days.with_columns(pl.when(pl.col("date") == d).then(None).otherwise(pl.col("split")).alias("split"))
        norm_d, cnorm_d = D.normal_level(pxw.drop("date"), days_d), D.normal_level(pcn.drop("date"), days_d)
        dt = days.filter(pl.col("date") == d)["daytype"].item()
        had = (pxw.filter((pl.col("date") == d) & pl.col("band").is_not_null())
                  .group_by("LinkID", D.slot15(pl.col("t")).alias("slot15")).agg(pl.lit(1).alias("had")))
        cmp = (norm.filter(pl.col("daytype") == dt).join(had, on=["LinkID", "slot15"], how="left")
                   .with_columns((pl.col("n_days") - pl.col("had").fill_null(0)).alias("expect"))
                   .join(norm_d.filter(pl.col("daytype") == dt).select("LinkID", "slot15", pl.col("n_days").alias("got")),
                         on=["LinkID", "slot15"], how="left"))
        excl_bad += cmp.filter(pl.col("got").fill_null(0) != pl.col("expect")).height
        t0 = datetime.combine(d, datetime.min.time())
        t1 = t0 + timedelta(hours=23, minutes=55)
        b = D.base_rows(pxw.filter(pl.col("date") == d).drop("date"), norm_d, days, pop_ids, t0, t1, [d])
        cl = D.lag_table(D.add_lags(D.deficit_grid(pcn.filter(pl.col("date") == d).drop("date"), cnorm_d, days,
                                                   conn_ids, t0, t1), prefix="c_").filter(D.in_hours(pl.col("t"))),
                         prefix="c_")
        r = D.assemble(b, pairs, D.lag_table(b), conn, cl, near, rin, rain_now, wd, road, school)
        for name, bad, _ in row_problems(r, pairs, holidays, conn, cl):
            bad_total[name] = bad_total.get(name, 0) + bad
        lodo_sum.append(r.lazy().filter(keep).select("date", "U", "y").collect())
        table(r, keep, main_cols).sink_parquet(lodo_dir / f"{d}.parquet")
        del b, cl, r
    check("lodo: each day's normal level leaves out exactly that day", excl_bad == 0, f"{excl_bad} cells differ")
    for name, bad in bad_total.items():
        check(f"lodo rows: {name}", bad == 0, f"{len(lodo_days)} days" if bad == 0 else f"{bad:,} bad")
    pl.scan_parquet(sorted(lodo_dir.glob("*.parquet"))).sink_parquet(TMP_OUT / "extra" / "train_lodo.parquet")
    shutil.rmtree(lodo_dir)
    lodo = pl.concat(lodo_sum)
    onset = lodo.filter(~pl.col("U"))
    summary["train_lodo"] = {"days": lodo["date"].n_unique(), "use_rows": lodo.height,
                             "share_U": round(lodo["U"].mean(), 4), "share_y": round(lodo["y"].mean(), 4),
                             "onset_rows": onset.height, "onset_rows_y_true": int(onset["y"].sum()),
                             "share_y_onset": round(onset["y"].mean(), 4)}
    n["extra/train_lodo.parquet"] = lodo.height
    check("written: train_lodo.parquet holds every usable row once",
          pl.scan_parquet(TMP_OUT / "extra" / "train_lodo.parquet").select(pl.len()).collect().item() == lodo.height,
          f"{lodo.height:,} rows")
    del lodo, onset, lodo_sum, pxw, pcn

    # ---- 11. days.csv, build_info.json, README.md, checksums; then swap the new tables in ----
    log("11. build record, README, checksums")
    dtab = (days.join(per_day, on="date", how="left").join(updates_06_22, on="date", how="left")
                .join(rdays, on="date", how="left").join(cov.select("date", pl.col("share").alias("share_rain_readings")),
                                                         on="date", how="left")
                .with_columns(pl.col("date").dt.strftime("%a").alias("day"),
                              pl.col("share_captured", "share_use", "share_rain_missing", "share_rain_readings").round(4))
                .select("date", "day", "daytype", "is_holiday", "split", "in_population", "updates", "updates_06_22", "rows",
                        "share_captured", "use_rows", "share_use", "share_rain_missing", "share_rain_readings")
                .sort("date"))
    dtab.write_csv(TMP_OUT / "extra" / "days.csv")
    info_json = {
        "data_version": S.DATA_VERSION, "built_at": datetime.now(SGT).isoformat(timespec="seconds"),
        "built_as_of": f"{now:%Y-%m-%d %H:%M}", "git_commit": git_commit(),
        "code_sha256": {f: sha256(PROJ / f) for f in CODE_FILES},
        "software": {"python": platform.python_version(), "polars": pl.__version__, "numpy": np.__version__},
        "days": {"first": str(first_day), "last_finished": str(cutoff),
                 "by_split": {s: dtab.filter(pl.col("split") == s).height for s in S.SPLITS},
                 "population_by_split": {s: dtab.filter((pl.col("split") == s) & pl.col("in_population")).height
                                         for s in S.SPLITS}},
        "links": {"registry": registry.height, "expressway": len(xw_ids), "in_population": len(pop_ids),
                  "roads": links["road"].n_unique(), "presence_week1_updates": n_week_updates,
                  "heldout_roads": held, "heldout_links": n_held,
                  "neighbour_pairs": pairs.height, "joining_roads": len(conn_ids), "joining_pairs": conn.height,
                  "expressway_links_with_joining_road": conn["joins"].n_unique(),
                  "rain_stations_eligible": len(good), "rain_stations_used": len(used)},
        "speed_band_cleaning": sb_stats, "rows": n, "label_summary": summary,
        "settings": settings_dict(),
        "inputs": {"speed_band_files": digest_files([a[3] for a in sb_files]),
                   "registry_files": digest_files(reg_files), "incident_files": digest_files(inc_files),
                   **{name: sha256(PROC / name) for name in ("rainfall_5min.csv.gz", "rain_stations.csv", "calendar_2026.csv")}},
        "checks": check.items, "peak_memory_mb": peak_mb(), "seconds": round(time.time() - t_start),
    }
    (TMP_OUT / "extra" / "build_info.json").write_text(D.to_json(info_json))
    (TMP_OUT / "README.md").write_text(readme(info_json, dtab))
    files = sorted(p for p in TMP_OUT.rglob("*") if p.is_file() and p.name != "SHA256SUMS.txt")
    (TMP_OUT / "extra" / "SHA256SUMS.txt").write_text(
        "".join(f"{sha256(p)}  {p.relative_to(TMP_OUT).as_posix()}\n" for p in files))
    swap_in(TMP_OUT, OUT)
    swap_in(TMP_CLEAN, CLEAN)
    DOCS.mkdir(parents=True, exist_ok=True)
    for old in DOCS.iterdir():
        if old.is_file():
            old.unlink()
    for src, name in ((OUT / "README.md", "README.md"), (OUT / "extra" / "build_info.json", "build_info.json"),
                      (OUT / "extra" / "days.csv", "days.csv"), (OUT / "extra" / "SHA256SUMS.txt", "SHA256SUMS.txt")):
        shutil.copy2(src, DOCS / name)
    log(f"done in {time.time() - t_start:.0f} s, peak memory {peak_mb():,} MB: {len(check.items)} checks passed; rows {n}")


# ----------------------------------------------------------------------------------------------------------

def readme(info: dict, days: pl.DataFrame) -> str:
    st, lk, n, ls = info["settings"], info["links"], info["rows"], info["label_summary"]
    tr = n.get("train.parquet", {})
    val = ls.get("validate", {})
    spans = []
    for s in S.SPLITS:
        a, b = S.SPLITS[s]
        d = days.filter((pl.col("split") == s) & pl.col("in_population"))
        use_for = {"train": "fit and tune the models; the normal level comes from these days only",
                   "validate": "choose the final model, calibrate, set the alert budget",
                   "test": "final test, once, after the plan is frozen"}[s]
        all_d = days.filter(pl.col("split") == s)
        so_far = "" if all_d.height and all_d["date"].max() == b else " (not finished yet)"
        hol = all_d.filter(pl.col("is_holiday") & (pl.col("date").dt.weekday() <= 5))["date"].to_list()
        used = str(d.height) + (f" ({', '.join(f'{x:%a %d %b}' for x in hol)} "
                                f"{'is a public holiday' if len(hol) == 1 else 'are public holidays'})" if hol else "")
        if so_far:   # say which weekdays the split will have once it is finished
            wk = [x for x in (a + timedelta(days=i) for i in range((b - a).days + 1)) if x.weekday() < 5]
            used += f" so far; {wk[0]:%a %d} to {wk[-1]:%a %d %b} when finished"
        spans.append(f"| `{s}` | {a:%a %d %b} to {b:%a %d %b}{so_far} | {used} | {use_for} |")
    changes = []
    for v, d, text in S.DATA_CHANGES:
        if isinstance(text, list):
            changes.append(f"- **v{v}** ({d}):\n" + "\n".join(f"  - {x}" for x in text))
        else:
            changes.append(f"- **v{v}** ({d}): {text}")
    lag_names = ", ".join(f"`f_d{m}`" for m in S.LAGS)
    held = " and ".join(r.title() for r in lk["heldout_roads"])
    gb = round(sum(tr.values()) * 300 / 1e9, 1)   # pandas 3.1: 2.39 GB for the 8.05 M rows of data version 4

    def pct(x) -> str:
        return f"{100 * x:.1f}%" if x is not None else "-"

    return f"""# SLDS 1.3 model data (data version {info['data_version']})

Built {info['built_at'][:16].replace('T', ' ')} (git `{info['git_commit']}`) by `analysis/build_data.py`, from
the raw LTA files. Days {info['days']['first']} to {info['days']['last_finished']}. New days are added with the
same version number. A change of rule raises the version (see "Changes" at the end).

## What is in this folder

| File | What it is |
|---|---|
| `train.parquet` | The rows to train on: {tr.get('train', 0):,} rows with `split = "train"` and {tr.get('validate', 0):,} with `split = "validate"`. Weekdays only (Monday to Friday, no public holidays), as in our proposal. Only usable rows, only the columns models need. |
| `test.parquet` | The weekdays of the test week, Mon 16 to Fri 20 Nov (the test week runs from Sat 14 to Fri 20 Nov; its Saturday and Sunday are only in `extra/test_full.parquet`). Added after the test week ends and the plan is frozen. Do not open it before then. |
| `README.md` | This file. |
| `extra/` | Everything else. You do not need it to train a model. |

In `extra/`:

| File | What it is |
|---|---|
| `train_sample.parquet` | The `train.parquet` rows of {S.SAMPLE_LINKS} links that are not on a held-out road ({n.get('extra/train_sample.parquet', 0):,} rows). Use it to test your code fast. |
| `train_lodo.parquet` | The `train` days again, but each day's normal level is built without that day. Same columns as `train.parquet`. For the plan's leave-own-day-out check (see "Good to know"). |
| `full_table.parquet` | Every row of the train and validate days, for exploring: every day of the week (`in_population` = False on Saturdays, Sundays and public holidays), also the rows we cannot use (`use` = False), with `y_h5`, `y_h10`, `y_h30` (the answer 5, 10, 30 minutes ahead), `f_sat`, `f_sun`, `f_holiday` and `info_` columns. |
| `test_full.parquet` | The same for the test week (later). |
| `links.parquet` | One row per link: road, held-out road or not, coordinates, rain station, number of neighbours and joining roads. |
| `neighbours.parquet`, `connectors.parquet` | Which link follows which; which roads join which link. |
| `norm.parquet`, `connector_norm.parquet` | The normal levels (`n_obs` = how many bands each median uses). |
| `days.csv` | One row per day: in the proposal's days or not, updates captured, usable rows, rain coverage. |
| `incidents.parquet` | LTA incident messages (accidents, breakdowns), for checking errors. Not an input. |
| `build_info.json`, `SHA256SUMS.txt` | How the files were built (every check and its result) and their checksums. |

## Quick start (Python)

`train.parquet` has {sum(tr.values()):,} rows and takes about {gb} GB of memory in pandas (more while it loads).
Start with `extra/train_sample.parquet`. For the full data, read only the columns you need (`columns=[...]`).
pandas needs `pyarrow` to read `.parquet` files (both are in `requirements.txt`).

```python
import pandas as pd
d   = pd.read_parquet("extra/train_sample.parquet")   # later: pd.read_parquet("train.parquet")
d   = d[~d["heldout_road"]]          # AYE and CTE: only for the transfer check in the test week
fit = d[d["split"] == "train"]       # fit and tune the models on these rows
val = d[d["split"] == "validate"]    # choose the final model and calibrate on these rows
inputs  = [c for c in d.columns if c.startswith("f_")]            # all inputs, no missing values
inputs0 = [c for c in inputs if not c.startswith("f_conn_")]      # the same without the joining roads
X = fit[inputs].to_numpy("float32")  # one row per link and time, one column per input
y = fit["y"].to_numpy()              # True = unusual 15 minutes later
onset = ~fit["U"].to_numpy()         # the main score uses these rows: normal now
```

polars works too: `pl.read_parquet(...)`, with the same column names.

## One row

One row is one link (about 140 m of road, one direction) at one LTA update `t` (every 5 minutes), from
{st['HOUR_FROM']:02d}:00 to {st['HOUR_TO']:02d}:00, Monday to Friday except public holidays (our proposal's days). There are
{lk['in_population']:,} links: the 10 expressways, plus 2 short flyovers (Aljunied West, Kallang Bahru) that LTA also lists as
expressway. Column `road` has {lk['roads']} values.

| Split | Dates | Weekdays used | Use |
|---|---|---|---|
{chr(10).join(spans)}

Our data starts on Fri 16 Oct (collection from 11:10 that day). Mon 9 Nov (the Deepavali holiday) is not used.

## Held-out roads (transfer check)

`heldout_road` = True for the {lk['heldout_links']:,} links of the {held}. They were drawn at random with
a fixed seed before any model was fitted (the same draw as data versions 1 and 2). Never use their rows to fit,
tune, choose or calibrate a model. In the test week, score them on their own: does a model trained on the other
roads work on roads it has never seen?

## What we predict

```
time:     t-30   t-25   t-20   t-15   t-10   t-5    t   |  t+5    t+10   t+15
inputs:   f_d30  f_d25  f_d20  f_d15  f_d10  f_d5  f_d0 |
U (now):                                    low    low  |
y:                                                      |         low    low
```

- **Normal level** (`extra/norm.parquet`): the median speed band of the link for that 15-minute slot and day
  type, from the `train` days only. It never changes after that. The main files hold weekdays only, so they use
  the `weekday` level (Monday to Friday). The `saturday` and `sunday_or_holiday` levels are only for the extra
  rows in `extra/full_table.parquet`.
- **Drop** = normal level minus the speed band. A drop of 2 means 2 bands (20 km/h) slower than normal. It goes
  from -7 to 7, can end in .5, and is below 0 when traffic is faster than normal.
- **Low** = a drop of {st['THRESHOLD']} or more.
- **`U`** (unusual now) = low now and 5 minutes ago. `U` is unknown when either update is missing; those rows
  are not in `train.parquet`.
- **`y`** (the answer) = `U` 15 minutes later. In `train`, {pct(ls['train']['share_y'])} of rows are True.
- **Main score**: PR-AUC on the rows that are normal now (`U == False`) in the test week, on the training roads
  (`heldout_road == False`). AYE and CTE get a score of their own (the transfer check). Of the rows that are normal
  now, {pct(ls['train']['share_y_onset'])} (train) and {pct(val.get('share_y_onset'))} (validate) become unusual 15 minutes later (all roads together).
  That share is also the PR-AUC of a model that only guesses.

## The inputs (`f_` columns, all known at time `t`)

| Columns | Meaning |
|---|---|
| {lag_names} | the link's drop now, 5, 10, ... 30 minutes ago |
| `f_d_change15` | `f_d0 - f_d15`: is the drop growing? |
| `f_n_filled` | how many of the 7 drops above reused the update 5 minutes before (because the real one was missing) |
| `f_up_d0` ... `f_up_d30` | the biggest drop among the links just before this one (upstream), same times |
| `f_dn_d0` ... `f_dn_d30` | the same for the links just after it (downstream); slowdowns move backwards |
| `f_up_none`, `f_dn_none` | 1 = the link has no link before / after it (its values are then 0) |
| `f_rain15`, `f_rain30` | rain (mm) at the nearest station in the 15 / 30 minutes up to 5 minutes ago (0 = no rain) |
| `f_rain15_missing`, `f_rain30_missing` | 1 = the station had no reading at all in that time (the value is then 0) |
| `f_slot15` | time of day in 15-minute slots: 24 = 06:00-06:14, ..., 87 = 21:45-21:59 |
| `f_mon` ... `f_fri` | day of the week, one-hot (exactly one is 1) |
| `f_conn_in_d0` ... `f_conn_in_d30` | the biggest drop among the roads leading into the link (slip roads, main roads), against their own normal level |
| `f_conn_out_d0` ... `f_conn_out_d30` | the same for the roads leading out of it |
| `f_conn_in_none`, `f_conn_out_none` | 1 = no such road (values then 0) |
| `f_conn_in_missing`, `f_conn_out_missing` | 1 = a road exists but a value was missing (then 0) |

The `f_conn_` inputs are extra: train every model with and without them (`inputs` and `inputs0` above), on the same rows.

Other columns: `LinkID`, `road`, `heldout_road`, `t` (Singapore time), `date`, `daytype` (always `weekday`
here), `split`, `y`, `U`. Rows are in the order split, link, time.

## Rules

- Use only the `f_` columns as inputs. Never use `y`, `U`, `split`, `heldout_road` or anything from `extra/` as an input.
- Never fit, tune, choose or calibrate on rows with `heldout_road == True`.
- Fit on `split == "train"`. Tune by forward-chaining inside the train days: fit on earlier days, check on
  later days, never the other way round. For example, with whole weeks: fit on 16-23 Oct and check on 26-30 Oct;
  then fit on 16-30 Oct and check on 2-6 Nov. Use `split == "validate"` to choose the final model, calibrate and
  set the alert budget (the share of links to alert on at each update). Do not open `test.parquet` before the plan
  is frozen.
- Do not take "the row above" as the previous update. Use `f_d5`, `f_d10`, ...
- Set a random seed. For the lasso logistic regression, scale the inputs with the mean and standard deviation of the
  rows you fit on, and treat `f_slot15` as a curve or as hour groups, not a straight line. For the random forest
  on all rows, you may keep fewer False rows (fixed seed) and then calibrate on `validate` (calibrate = adjust the
  predicted chances so that they match how often slowdowns really happen).
- Write the data version ({info['data_version']}) next to every result.

## Good to know

- A neighbour's or joining road's value can also be a reused one (at most 5 minutes old), like `f_d5` ... `f_d30`.
- A rain total skips missing readings; the `_missing` flag is 1 only when all readings in the window are missing.
- In `train.parquet`, a train day is one of the days its own normal level is built from, so its labels are a
  little easier than on new days. `extra/train_lodo.parquet` has the same days with a normal level built without
  that day: share of `U` {pct(ls['train']['share_U'])} in `train`, {pct(ls['train_lodo']['share_U'])} in `train_lodo`, {pct(val.get('share_U'))} in `validate`.
  Fit a model on both and compare the validation scores (PROJECT_PLAN §4.9).
- Our data arrives a median of 4 minutes after `t`. A warning 15 minutes ahead of `t` gives about 11 minutes in practice.
- Days with fewer usable rows (see `extra/days.csv`): Fri 16 Oct (collection started 11:10) and Thu 12 Nov (our
  second collector was down from 10:12 to 14 Nov 17:15).

## Changes

{chr(10).join(changes)}

## Check your download

Inside the folder with the files: `sha256sum -c --ignore-missing extra/SHA256SUMS.txt` (every file says OK).
The same list is in git: `docs/model_data/SHA256SUMS.txt`. On Windows: `Get-FileHash <file> -Algorithm SHA256`.

Contains information from LTA DataMall, NEA and MOM, accessed from data.gov.sg and made available under the
Singapore Open Data Licence version 1.0 (https://data.gov.sg/open-data-licence).
"""


if __name__ == "__main__":
    main()
