"""build_model_data.py - SLDS 42.510 project 1.3: modelling tables (population, norm, labels, features, splits).

Reads data_processed/analysis_panel/, link_registry.parquet and rainfall_5min.csv.gz (from 04_process.ipynb and
get_context_data.py) and writes data_processed/model/, which build_processed.sh copies to the Google Drive folder
SLDS_1.3_processed. Everything is rebuilt from scratch on every run, so the same inputs give the same tables.

    .venv/bin/python analysis/build_model_data.py

Definitions: PROJECT_PLAN.md §4.2-4.5 and DECISIONS.md. Settings are the constants below; a change to any of
them is a decision and goes into DECISIONS.md first.

data_processed/model/ (= Drive SLDS_1.3_processed/):
    README.md            data dictionary and rules for using the files (written by this script)
    build_info.json      when and from what it was built: git commit, settings, input checksums, row counts
    SHA256SUMS.txt       checksums of every file here
    train.parquet        population rows 13 Oct - 6 Nov: keys, outcomes, features f_*, info_*
    train_dev.parquet    the same for DEV_LINKS links, for writing and debugging scripts quickly
    validate.parquet     population rows 7 - 13 Nov (finished days only)
    test_locked/test.parquet   population rows 14 - 20 Nov; read only by the final test script
    links.parquet        one row per expressway link: road, coordinates, rain station, presence, held-out road
    neighbours.parquet   link -> upstream / downstream link (end point meets start point)
    norm.parquet         frozen norm: median band per link x daytype x 15-min slot, training days only
    connectors.parquet   links that join an expressway link (into / out of it), from 04_process
    connector_norm.parquet   the same frozen norm for those links (for the f_conn_* inputs)
    days.csv             one row per collected day: split, in population, updates captured, rows
    incidents.parquet    copy of data_processed/incidents.parquet, for label audit and error analysis
docs/model_data/ (in git): copies of README.md, build_info.json, days.csv and SHA256SUMS.txt from the last build.
AI disclosure: drafted with Claude (Anthropic) on 10-11 Nov 2026; log in AI_USE.md.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import shutil
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import polars as pl

# ---- settings (PROJECT_PLAN §4.2-4.5, DECISIONS.md) ----
CATEGORIES = [1]                                   # RoadCategory 1 = expressways
SPLITS = {"train": (date(2026, 10, 13), date(2026, 11, 6)),
          "validate": (date(2026, 11, 7), date(2026, 11, 13)),
          "test": (date(2026, 11, 14), date(2026, 11, 20))}
DAYTYPES = ["Mon-Thu", "Fri"]                      # weekdays; public holidays are daytype "Sun/PH"
HOUR_FROM, HOUR_TO = 6, 22                         # population rows: 06:00 <= t < 22:00 (192 updates a day)
PRESENCE_DAYS = (date(2026, 10, 19), date(2026, 10, 23))   # first full collection week (16 Oct is a part day)
# keep links with a band in >= 90% of captured updates (supersedes 95%, DECISIONS.md 11 Nov: every link is at
# 94-97% because whole pages lag, so 95% dropped links at random; 90% still drops a LinkID that disappears)
PRESENCE_MIN = 0.90
THRESHOLD = 2                                      # unusual: deficit >= 2 bands ...
CONSECUTIVE = 2                                    # ... at t and t - 5 min
HORIZON = 15                                       # outcome y = U(t + 15 min)
EXTRA_HORIZONS = [5, 10, 30]                       # sensitivity outcomes y_h5, y_h10, y_h30
LAGS = [0, 5, 10, 15, 20, 25, 30]                  # deficit lags (minutes) for the link and its neighbours
CARRY_MAX = 15                                     # a missing deficit carries the last value at most 15 min
NEIGHBOUR_TOL_M = 5                                # end of one link within 5 m of the start of the next
RAIN_LAG = 5                                       # rain features use readings timestamped t - 5 or earlier
HELDOUT_N, HELDOUT_SEED = 2, 20261113              # whole roads held out for the transfer test
ROAD_GROUPS = {"KALLANG PAYA LEBAR EXPRESSWAY TUNNEL": "KALLANG PAYA LEBAR EXPRESSWAY"}
NEVER_HELD_OUT = {"ALJUNIED WEST FLYOVER", "KALLANG BAHRU FLYOVER"}   # 5-6 links each, not expressways
DEV_LINKS, DEV_SEED = 300, 1                       # train_dev.parquet: whole links, not held out
STEP = timedelta(minutes=5)                        # LTA update interval; t is on the 5-min grid

# Data version: bump DATA_VERSION and add a line here whenever a republish changes what the tables mean
# (a rule, setting or bug fix), not when new days are only added. Teammates compare it with their copy.
DATA_VERSION = "2"
DATA_CHANGES = [
    ("2", "2026-11-11", "Added f_conn_* inputs: links that join an expressway (slip roads, arterials, ...), so models "
                        "can be compared with and without them. Rows, labels and other columns unchanged."),
    ("1", "2026-11-11", "First release: 2,598 expressway links, strict label rule, own/neighbour/rain features, "
                        "held-out roads AYE + CTE (pending team confirmation)."),
]

SGT = timezone(timedelta(hours=8))
PROJ = Path(os.environ.get("SLDS_PROJECT_DIR") or Path(__file__).resolve().parent.parent)
SRC, OUT = PROJ / "data_processed", PROJ / "data_processed" / "model"
DOCS = PROJ / "docs" / "model_data"                # copy of README, build_info, days.csv, SHA256SUMS (in git)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_commit() -> str:
    try:
        c = subprocess.run(["git", "-C", str(PROJ), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(PROJ), "status", "--porcelain", "--", "analysis/build_model_data.py",
                                "04_process.ipynb"], capture_output=True, text=True).stdout.strip()
        return c + ("-modified" if dirty else "")
    except OSError:
        return "unknown"


def split_of(d: pl.Expr) -> pl.Expr:
    e = pl.lit(None, pl.Utf8)
    for name, (a, b) in reversed(SPLITS.items()):
        e = pl.when(d.is_between(a, b)).then(pl.lit(name)).otherwise(e)
    return e


def parse_sgt(col: pl.Expr) -> pl.Expr:
    """'2026-10-15T08:00:00+08:00' or '2026-10-15 08:00:00' -> naive Singapore time (as in 04_process)."""
    s = col.str.replace(r"(\+08:?00)$", "").str.replace("T", " ")
    return s.str.to_datetime("%Y-%m-%d %H:%M:%S", time_unit="us")


def check_inputs(day_files: list[Path], today: date) -> list[str]:
    """Finished days whose analysis_panel file is older than a raw speed-band file of that day (or the next
    day's first 15 minutes, which 04_process also reads), or older than the rainfall table."""
    stale = []
    rain_mtime = max((SRC / "rainfall_5min.csv.gz").stat().st_mtime, (SRC / "connector_links.parquet").stat().st_mtime)
    for f in day_files:
        day = date.fromisoformat(f.stem)
        if day >= today:
            continue
        nxt = day + timedelta(days=1)
        raw = [r for root in PROJ.glob("data_raw*") for r in (root / "speedbands" / str(day)).glob("sb_*.csv.gz")]
        raw += [r for root in PROJ.glob("data_raw*") for r in (root / "speedbands" / str(nxt)).glob(f"sb_{nxt:%Y%m%d}_00[01]*.csv.gz")]
        if any(r.stat().st_mtime > f.stat().st_mtime for r in raw) or rain_mtime > f.stat().st_mtime:
            stale.append(day.isoformat())
    return stale


def neighbour_pairs(links: pl.DataFrame) -> pl.DataFrame:
    """Downstream neighbours: links whose start point is within NEIGHBOUR_TOL_M of this link's end point."""
    xy = links.select([pl.col(c).cast(pl.Float64) for c in ["StartLat", "StartLon", "EndLat", "EndLon"]]).to_numpy()
    k, c = 111_320.0, np.cos(np.radians(1.35))     # metres per degree at Singapore's latitude
    start = np.c_[xy[:, 1] * k * c, xy[:, 0] * k]
    end = np.c_[xy[:, 3] * k * c, xy[:, 2] * k]
    d = np.sqrt(((end[:, None, :] - start[None, :, :]) ** 2).sum(-1))
    np.fill_diagonal(d, np.inf)
    i, j = np.nonzero(d <= NEIGHBOUR_TOL_M)
    ids = links["LinkID"].to_numpy()
    return (pl.DataFrame({"LinkID": ids[i], "downstream": ids[j], "gap_m": d[i, j].round(1)})
              .sort("LinkID", "downstream"))


def main() -> None:
    today = datetime.now(SGT).date()
    day_files = sorted((SRC / "analysis_panel").glob("*.parquet"))
    if not day_files:
        raise SystemExit("no finished days in data_processed/analysis_panel/; run 04_process.ipynb first")
    stale = check_inputs(day_files, today)
    if stale:
        raise SystemExit("analysis_panel is older than its raw data (run 04_process.ipynb or build_processed.sh): "
                         + ", ".join(stale))
    if OUT.exists():
        shutil.rmtree(OUT)                         # rebuilt from scratch: nothing stale survives
    (OUT / "test_locked").mkdir(parents=True)

    registry = pl.read_parquet(SRC / "link_registry.parquet").rename({"presence": "presence_hourly"})
    xw = registry.filter(pl.col("RoadCategory").cast(pl.Int64).is_in(CATEGORIES))
    # A day file holds what was retrieved that day, so updates at 23:50-23:55 fetched after midnight are in two
    # files (same band). Keep the earliest retrieval, as 04_process does within a day; only finished days of t.
    panel = (pl.scan_parquet(day_files)
               .join(xw.lazy().select("LinkID"), on="LinkID", how="semi")
               .filter(pl.col("date") < today)
               .sort("retrieved", "LinkID")
               .unique(subset=["LinkID", "t"], keep="first")
               .select("t", "date", "LinkID", "band", "rain_mm", "station_id", "station_km", "daytype", "weekday",
                       "slot15", "school_period", "olevel_venue_schools_ended", "t_from_retrieval")
               .with_columns(split_of(pl.col("date")).alias("split"))
               .collect())
    assert panel.select((pl.col("t").dt.minute() % 5 == 0) & (pl.col("t").dt.second() == 0)).to_series().all(), \
        "t is not on the 5-minute grid"
    assert panel.select(pl.struct("LinkID", "t").is_duplicated().any()).item() is False, "duplicate (LinkID, t)"
    in_window = pl.col("daytype").is_in(DAYTYPES) & pl.col("t").dt.hour().is_between(HOUR_FROM, HOUR_TO - 1)

    # Links that join an expressway link (slip roads, arterials, ...: connector_links.parquet from 04_process):
    # extra model inputs only, never rows to predict
    conn = pl.read_parquet(SRC / "connector_links.parquet")
    cpanel = (pl.scan_parquet(day_files)
                .join(conn.lazy().select("LinkID").unique(), on="LinkID", how="semi")
                .filter(pl.col("date") < today)
                .sort("retrieved", "LinkID")
                .unique(subset=["LinkID", "t"], keep="first")
                .select("t", "date", "LinkID", "band", "daytype", "slot15")
                .with_columns(split_of(pl.col("date")).alias("split"))
                .collect())

    # ---- population: links with a band in >= PRESENCE_MIN of the updates captured in the first full week ----
    week = panel.filter(in_window & pl.col("date").is_between(*PRESENCE_DAYS))
    n_updates = week["t"].n_unique()
    presence = (week.filter(pl.col("band").is_not_null()).group_by("LinkID").len()
                    .select("LinkID", (pl.col("len") / n_updates).alias("presence_week1")))
    nearest = panel.select("LinkID", "station_id", "station_km").unique("LinkID")
    links = (xw.join(presence, on="LinkID", how="left").join(nearest, on="LinkID", how="left")
               .with_columns(pl.col("presence_week1").fill_null(0.0))
               .with_columns((pl.col("presence_week1") >= PRESENCE_MIN).alias("in_population"),
                             pl.col("RoadName").replace(ROAD_GROUPS).alias("road"))
               .sort("LinkID"))

    # held-out roads for the transfer test: drawn once with a fixed seed from the expressways in the population
    roads = sorted(set(links.filter("in_population")["road"]) - NEVER_HELD_OUT)
    heldout = sorted(random.Random(HELDOUT_SEED).sample(roads, HELDOUT_N))
    links = links.with_columns(pl.col("road").is_in(heldout).alias("heldout_road"))
    keep = links.filter("in_population")
    pairs = neighbour_pairs(keep)

    # ---- norm: median band per link x daytype x 15-min slot, training weekdays only (all hours, so that the
    # lookups before 06:00 and after 22:00 also have a norm), then frozen ----
    def norm_of(p: pl.DataFrame) -> pl.DataFrame:
        return (p.filter((pl.col("split") == "train") & pl.col("daytype").is_in(DAYTYPES))
                 .group_by("LinkID", "daytype", "slot15")
                 .agg(pl.col("band").median().alias("norm_band"), pl.col("band").count().alias("n_obs"))
                 .sort("LinkID", "daytype", "slot15"))

    norm = norm_of(panel.join(keep.select("LinkID"), on="LinkID", how="semi"))
    cnorm = norm_of(cpanel)

    # ---- labels on every weekday row, before cutting to the window ----
    # low(t) = deficit >= THRESHOLD; U(s) = low at s, s-5, ... (CONSECUTIVE snapshots), known only when every
    # one of those snapshots was captured (DECISIONS.md 11 Nov). A rule that settles FALSE from one snapshot can
    # never settle TRUE that way, so dropping its nulls removed ~25% of onset positives and almost no negatives.
    # y_h = U(t + h) with the same rule.
    lab = (panel.join(keep.select("LinkID", "RoadName", "heldout_road"), on="LinkID", how="inner")
                .join(norm.select("LinkID", "daytype", "slot15", "norm_band"), on=["LinkID", "daytype", "slot15"], how="left")
                .with_columns((pl.col("norm_band") - pl.col("band")).alias("deficit"))
                .with_columns((pl.col("deficit") >= THRESHOLD).alias("low")))
    look = lab.select("LinkID", "t", "low", pl.col("band").is_not_null().alias("has_band"))

    def low_at(offset: timedelta, name: str) -> pl.LazyFrame:  # low(t + offset), keyed on t
        return look.lazy().select("LinkID", (pl.col("t") - offset).alias("t"), pl.col("low").alias(name))

    def u_at(lf: pl.LazyFrame, offset: timedelta, name: str) -> pl.LazyFrame:
        parts = [f"_{name}_{k}" for k in range(CONSECUTIVE)]
        for k, p in enumerate(parts):
            lf = lf.join(low_at(offset - STEP * k, p), on=["LinkID", "t"], how="left")
        u = pl.when(pl.any_horizontal([pl.col(p).is_null() for p in parts])).then(None).otherwise(pl.all_horizontal(parts))
        return lf.with_columns(u.alias(name)).drop(parts)

    lf = u_at(lab.lazy(), timedelta(0), "U")
    for h in [HORIZON, *EXTRA_HORIZONS]:
        lf = u_at(lf, timedelta(minutes=h), "y" if h == HORIZON else f"y_h{h}")
    lab = (lf.join(look.lazy().select("LinkID", (pl.col("t") + STEP).alias("t"), pl.col("has_band").alias("prev_has_band")),
                   on=["LinkID", "t"], how="left")
             .with_columns(pl.col("prev_has_band").fill_null(False).not_().alias("prev_missing"))
             .collect())
    rows = lab.filter(in_window & pl.col("split").is_not_null())

    # ---- features: only information available at t (PROJECT_PLAN §4.5) ----
    # Own deficit lags on a regular 5-min grid per link. A missing update carries the last deficit forward for at
    # most CARRY_MAX minutes (never interpolated, which would use the future); beyond that the lag is null.
    times = pl.DataFrame({"t": pl.datetime_range(lab["t"].min(), lab["t"].max(), STEP, eager=True, time_unit="us")})
    dcols = [f"d{m}" for m in LAGS]

    def deficit_lags(d: pl.DataFrame, ids: pl.DataFrame) -> pl.DataFrame:
        """d0 ... d30 per link and t from a frame of (LinkID, t, deficit)."""
        return (ids.join(times, how="cross")
                   .join(d.select("LinkID", "t", "deficit"), on=["LinkID", "t"], how="left")
                   .sort("LinkID", "t")
                   .with_columns(pl.col("deficit").forward_fill(limit=CARRY_MAX // 5).over("LinkID").alias("d"))
                   .with_columns([pl.col("d").shift(m // 5).over("LinkID").alias(f"d{m}") for m in LAGS])
                   .select("LinkID", "t", *dcols))

    grid = deficit_lags(lab, keep.select("LinkID"))
    rows = rows.join(grid.rename({c: f"f_{c}" for c in dcols}), on=["LinkID", "t"], how="left")

    # Neighbour deficits at the same lags: worst (largest) deficit over the upstream / downstream links
    need = rows.select("LinkID", "t")
    for side, a, b in (("dn", "LinkID", "downstream"), ("up", "downstream", "LinkID")):
        p = pairs.select(pl.col(a).alias("LinkID"), pl.col(b).alias("nbr"))
        agg = (need.join(p, on="LinkID", how="inner")
                   .join(grid.rename({"LinkID": "nbr"}), on=["nbr", "t"], how="left")
                   .group_by("LinkID", "t").agg([pl.col(c).max().alias(f"f_{side}_{c}") for c in dcols]))
        has = p.select("LinkID").unique().with_columns(pl.lit(0, pl.Int8).alias(f"f_{side}_none"))
        rows = (rows.join(agg, on=["LinkID", "t"], how="left").join(has, on="LinkID", how="left")
                    .with_columns(pl.col(f"f_{side}_none").fill_null(1))
                    .with_columns([pl.when(pl.col(f"f_{side}_none") == 1).then(0.0).otherwise(pl.col(f"f_{side}_{c}"))
                                     .alias(f"f_{side}_{c}") for c in dcols]))

    # Links joining the expressway (DECISIONS.md 11 Nov): the largest deficit over the links leading into
    # (f_conn_in_*) or out of (f_conn_out_*) this link, same lags and carry rule, against their own frozen norm.
    # No such link, or no value: 0 with a flag. They are not part of `use`, so models with and without these
    # inputs are fitted and scored on exactly the same rows.
    cdef = cpanel.join(cnorm.select("LinkID", "daytype", "slot15", "norm_band"), on=["LinkID", "daytype", "slot15"],
                       how="inner").with_columns((pl.col("norm_band") - pl.col("band")).alias("deficit"))
    cgrid = deficit_lags(cdef, conn.select("LinkID").unique().sort("LinkID"))
    for kind, side in (("into", "in"), ("out_of", "out")):
        p = conn.filter(pl.col("kind") == kind).select(pl.col("joins").alias("LinkID"), pl.col("LinkID").alias("nbr"))
        names = [f"f_conn_{side}_{c}" for c in dcols]
        agg = (need.join(p, on="LinkID", how="inner")
                   .join(cgrid.rename({"LinkID": "nbr"}), on=["nbr", "t"], how="left")
                   .group_by("LinkID", "t").agg([pl.col(c).max().alias(n) for c, n in zip(dcols, names)]))
        has = p.select("LinkID").unique().with_columns(pl.lit(0, pl.Int8).alias(f"f_conn_{side}_none"))
        rows = (rows.join(agg, on=["LinkID", "t"], how="left").join(has, on="LinkID", how="left")
                    .with_columns(pl.col(f"f_conn_{side}_none").fill_null(1))
                    .with_columns(((pl.col(f"f_conn_{side}_none") == 0)
                                   & pl.any_horizontal([pl.col(n).is_null() for n in names])).cast(pl.Int8)
                                  .alias(f"f_conn_{side}_missing"))
                    .with_columns([pl.col(n).fill_null(0.0) for n in names]))
    ccols = [f"f_conn_{s}_{c}" for s in ("in", "out") for c in dcols] + [
        f"f_conn_{s}_{x}" for s in ("in", "out") for x in ("none", "missing")]

    # Rain at the nearest station: totals of the readings timestamped t-5 ... t-15 (f_rain15) and t-5 ... t-30
    # (f_rain30). Missing readings are skipped; if all in a window are missing its total is 0 and its flag is 1.
    rain = (pl.read_csv(SRC / "rainfall_5min.csv.gz", schema_overrides={"station_id": pl.Utf8, "timestamp": pl.Utf8, "rain_mm": pl.Float64})
              .select(parse_sgt(pl.col("timestamp")).alias("t"), "station_id", "rain_mm"))
    stations = keep.select("station_id").unique()
    rgrid = (stations.join(pl.DataFrame({"t": pl.datetime_range(lab["t"].min() - timedelta(hours=1), lab["t"].max(), STEP,
                                                                eager=True, time_unit="us")}), how="cross")
                     .join(rain, on=["station_id", "t"], how="left")
                     .sort("station_id", "t")
                     .with_columns(pl.col("rain_mm").shift(RAIN_LAG // 5).over("station_id").alias("r"))
                     .with_columns(pl.col("r").rolling_sum(3, min_samples=1).over("station_id").alias("f_rain15"),
                                   pl.col("r").rolling_sum(6, min_samples=1).over("station_id").alias("f_rain30"))
                     .select("station_id", "t", "f_rain15", "f_rain30"))
    rows = (rows.join(rgrid, on=["station_id", "t"], how="left")
                .with_columns(pl.col("f_rain15").is_null().cast(pl.Int8).alias("f_rain15_missing"),
                              pl.col("f_rain30").is_null().cast(pl.Int8).alias("f_rain30_missing"))
                .with_columns(pl.col("f_rain15").fill_null(0.0), pl.col("f_rain30").fill_null(0.0)))

    rows = (rows.with_columns((pl.col("f_d0") - pl.col("f_d15")).alias("f_d_change15"),
                              pl.col("slot15").alias("f_slot15"),
                              (pl.col("daytype") == "Fri").cast(pl.Int8).alias("f_fri"),
                              pl.col("prev_missing").cast(pl.Int8).alias("f_prev_missing"))
                .sort("t", "LinkID"))
    fcols = ([f"f_{c}" for c in dcols] + ["f_d_change15"] + [f"f_{s}_{c}" for s in ("up", "dn") for c in dcols]
             + ["f_up_none", "f_dn_none", "f_rain15", "f_rain30", "f_rain15_missing", "f_rain30_missing",
                "f_slot15", "f_fri", "f_prev_missing"])
    ok = pl.all_horizontal([pl.col(c).is_not_null() for c in fcols])
    rows = rows.with_columns((ok & pl.col("y").is_not_null() & pl.col("U").is_not_null()).alias("use"))
    columns = (["t", "date", "LinkID", "RoadName", "daytype", "slot15", "heldout_road", "use",
                "y", *[f"y_h{h}" for h in EXTRA_HORIZONS], "U"] + fcols + ccols
               + [pl.col(c).alias(f"info_{c}") for c in ("band", "norm_band", "low", "rain_mm", "station_id", "station_km",
                                                         "weekday", "school_period", "olevel_venue_schools_ended", "t_from_retrieval")])

    # ---- write ----
    outputs = {}
    for name in SPLITS:
        part = rows.filter(pl.col("split") == name).select(columns)
        if part.height:
            path = OUT / ("test_locked/test.parquet" if name == "test" else f"{name}.parquet")
            part.write_parquet(path, statistics=False)
            outputs[name] = part.height
            if name == "train":
                cand = sorted(keep.filter(~pl.col("heldout_road"))["LinkID"].to_list())
                dev = sorted(random.Random(DEV_SEED).sample(cand, DEV_LINKS))
                part.filter(pl.col("LinkID").is_in(dev)).write_parquet(OUT / "train_dev.parquet", statistics=False)
                outputs["train_dev"] = part.filter(pl.col("LinkID").is_in(dev)).height
    links.write_parquet(OUT / "links.parquet", statistics=False)
    pairs.write_parquet(OUT / "neighbours.parquet", statistics=False)
    conn.sort("joins", "kind", "LinkID").write_parquet(OUT / "connectors.parquet", statistics=False)
    cnorm.write_parquet(OUT / "connector_norm.parquet", statistics=False)
    norm.write_parquet(OUT / "norm.parquet", statistics=False)
    if (SRC / "incidents.parquet").exists():
        shutil.copy2(SRC / "incidents.parquet", OUT / "incidents.parquet")

    days = (panel.group_by("date").agg(
                pl.col("split").first(), pl.col("daytype").first(),
                pl.col("t").filter(pl.col("t").dt.hour().is_between(HOUR_FROM, HOUR_TO - 1)).n_unique().alias("updates_06_22"))
            .join(rows.group_by("date").agg(pl.len().alias("rows"), pl.col("y").is_not_null().mean().round(4).alias("share_y_known"),
                                            pl.col("use").mean().round(4).alias("share_use")),
                  on="date", how="left")
            .with_columns((pl.col("daytype").is_in(DAYTYPES) & pl.col("split").is_not_null()).alias("in_population"),
                          pl.col("rows").fill_null(0))
            .sort("date"))
    days.write_csv(OUT / "days.csv")

    # label summary for train and validate only: test-week label statistics stay unseen until the final test
    summary = {}
    for name in ("train", "validate"):
        r = rows.filter((pl.col("split") == name) & pl.col("use"))
        if r.height:
            onset = r.filter(~pl.col("U"))
            summary[name] = {"use_rows": r.height, "days": r["date"].n_unique(),
                             "prevalence_U": round(r["U"].mean(), 4), "prevalence_y": round(r["y"].mean(), 4),
                             "onset_rows": onset.height, "onset_rows_y1": int(onset["y"].sum()),
                             "prevalence_y_onset": round(onset["y"].mean(), 4)}
    info = {"data_version": DATA_VERSION,
            "built_at": datetime.now(SGT).isoformat(timespec="seconds"), "git_commit": git_commit(),
            "polars": pl.__version__,
            "settings": {"categories": CATEGORIES, "splits": {k: [str(a), str(b)] for k, (a, b) in SPLITS.items()},
                         "daytypes": DAYTYPES, "hours": [HOUR_FROM, HOUR_TO], "presence_days": [str(d) for d in PRESENCE_DAYS],
                         "presence_min": PRESENCE_MIN, "threshold": THRESHOLD, "consecutive": CONSECUTIVE,
                         "horizon_min": HORIZON, "extra_horizons_min": EXTRA_HORIZONS, "lags_min": LAGS,
                         "carry_max_min": CARRY_MAX, "neighbour_tol_m": NEIGHBOUR_TOL_M, "rain_lag_min": RAIN_LAG,
                         "heldout_n": HELDOUT_N, "heldout_seed": HELDOUT_SEED, "dev_links": DEV_LINKS, "dev_seed": DEV_SEED},
            "links": {"expressway": xw.height, "in_population": keep.height, "presence_updates": n_updates,
                      "neighbour_pairs": pairs.height, "heldout_roads": heldout,
                      "connector_links": conn["LinkID"].n_unique(), "connector_pairs": conn.height,
                      "links_with_connector": conn["joins"].n_unique(),
                      "heldout_links": keep.filter("heldout_road").height},
            "rows": outputs, "label_summary": summary,
            "inputs": {f"analysis_panel/{f.name}": sha256(f) for f in day_files}
                      | {n: sha256(SRC / n) for n in ("link_registry.parquet", "rainfall_5min.csv.gz")}}
    (OUT / "build_info.json").write_text(json.dumps(info, indent=2) + "\n")
    (OUT / "README.md").write_text(readme(info, days))
    files = sorted(p for p in OUT.rglob("*") if p.is_file() and p.name != "SHA256SUMS.txt")
    (OUT / "SHA256SUMS.txt").write_text("".join(f"{sha256(p)}  {p.relative_to(OUT).as_posix()}\n" for p in files))
    # the documentation (not the data) goes into the repo, so the dictionary and checksums are versioned in git
    DOCS.mkdir(parents=True, exist_ok=True)
    for name in ("README.md", "build_info.json", "days.csv", "SHA256SUMS.txt"):
        shutil.copy2(OUT / name, DOCS / name)

    print(json.dumps({k: info[k] for k in ("links", "rows", "label_summary")}, indent=1))
    print(f"written to {OUT}")


def readme(info: dict, days: pl.DataFrame) -> str:
    s, lk = info["settings"], info["links"]
    split_days = days.filter("in_population").group_by("split").agg(pl.col("date").min().alias("a"), pl.col("date").max().alias("b"), pl.len())
    have = "\n".join(f"  - `{r['split']}`: {r['len']} weekday{'s' if r['len'] != 1 else ''}, {r['a']} to {r['b']}"
                     for r in split_days.sort("a").iter_rows(named=True))
    lags = ", ".join(str(m) for m in s["lags_min"])
    changes = "\n".join(f"- v{v} ({d}): {text}" for v, d, text in reversed(DATA_CHANGES))
    return f"""# SLDS 1.3 modelling tables (data version {info['data_version']})

Built {info['built_at']} from git commit `{info['git_commit']}` by `analysis/build_model_data.py`
(run through `build_processed.sh`). Every file is rebuilt from the raw data on each run, so rerunning on the same
raw data gives the same tables. New days are added as collection goes on (same version); a change of rule, setting
or a bug fix raises the version. Check `build_info.json` (`data_version`, `built_at`) against your copy.

## Changes

{changes}

## Getting the data

Download the files from the Google Drive folder `SLDS_1.3_processed` into `data_processed/model/` in your copy of
the repo, keeping `test_locked/` out of it until the test week. Then check them:
`sha256sum -c --ignore-missing SHA256SUMS.txt` (Linux/macOS; Windows: `Get-FileHash <file> -Algorithm SHA256` and compare).
Only `train_dev.parquet` (~9 MB) is needed to start writing scripts; `train.parquet` is ~70 MB.
Settings, input checksums and row counts: `build_info.json`.

## Quick start (R)

```r
library(arrow); library(dplyr)
tr <- read_parquet("data_processed/model/train_dev.parquet")   # small; switch to train.parquet for real fits
tr <- tr |> filter(use, !heldout_road)                          # usable rows, held-out roads kept out
x  <- tr |> select(starts_with("f_"))                           # every model input, no NAs
x0 <- tr |> select(starts_with("f_"), -starts_with("f_conn_"))  # the same without the joining roads
y  <- tr$y                                                      # outcome: unusual 15 min later
onset <- !tr$U                                                  # primary metric: rows normal now
```

Both models use the same rows and the same `f_*` columns:

- **Elastic net (`glmnet`)**: `as.matrix(x)`. Treat `f_slot15` as time of day in the model, e.g. a natural spline
  or hour dummies, rather than a straight line. `glmnet` standardises on the training data by default.
- **Random forest (`ranger`)**: use `x` as is. For full-size fits, subsample negatives with a fixed seed and
  recalibrate probabilities on the validation week afterwards (PROJECT_PLAN §4.6).
- **Baselines**: B1 = training rate of `U` per `LinkID` x `slot15` x `daytype`; B2 = `f_d0` (current deficit).

## Rules

- **Never open `test_locked/`** until the analysis plan is frozen. Only the final test script reads it
  (PROJECT_PLAN §6, item 7). It is not uploaded to Drive until then. EDA and tuning use `train`; model choice and calibration use `validate`.
- **Held-out roads** ({', '.join(r.title() for r in lk['heldout_roads'])}; {lk['heldout_links']} links, `heldout_road`): never
  used for training or tuning; evaluated on the test week for the transfer check.
- **Use `info_*` columns only for EDA and error analysis**, never as model inputs: `info_rain_mm` is not lagged
  and `info_norm_band` / `info_low` are part of the label.
- **The norm is frozen** (training days only). Don't recompute it on validate or test rows.
- **Filter on `use`**: TRUE when `y` and `U` are known and every `f_*` is present. Report how many rows it drops.
- **Rows exist only for captured updates.** About 5% of link x update pairs are missing (whole LTA pages lag), so
  a day has fewer than 192 rows per link. Never shift by row to get "the previous update"; use the `f_*` lags.
- **Training labels are slightly optimistic**: the norm includes the training days themselves (as the plan
  specifies), so the training rate of `U` is a little lower than on new days. Calibrate on `validate`.

## Population

- Links: RoadCategory {s['categories']} (expressways), {lk['expressway']:,} in the registry; **{lk['in_population']:,}** kept, those
  with a band in at least {s['presence_min']:.0%} of the {lk['presence_updates']} updates captured from
  {s['presence_days'][0]} to {s['presence_days'][1]} (06:00-22:00), see `links.parquet`.
- Time: weekdays except public holidays (daytype {' or '.join(s['daytypes'])}), {s['hours'][0]:02d}:00 <= t < {s['hours'][1]:02d}:00.
  Days in these files:
{have}
- Collection on the Linux PC starts 16 Oct 11:10 (the desktop's 13-16 Oct data is not used, DECISIONS.md 24 Oct),
  so training has {split_days.filter(pl.col('split') == 'train')['len'].sum()} weekdays, not 19, and only 4 Fridays (16 Oct is a part day). The Friday norm
  therefore rests on about 10 snapshots per link and slot against about 35 for Mon-Thu (`n_obs` in `norm.parquet`).

## Label (PROJECT_PLAN §4.2, DECISIONS.md 13 Oct)

- norm = median band for the link, day type and 15-minute slot over the training weekdays (`norm.parquet`, with `n_obs`).
- deficit = norm - band; low = deficit >= {s['threshold']}.
- `U` = low at `t` and at the previous update ({s['consecutive']} consecutive snapshots). `U` is null if either
  snapshot was not captured, so a missing snapshot hides positives and negatives alike (DECISIONS.md 11 Nov).
- `y` = `U` at `t + {s['horizon_min']} min` (same rule). `y_h5`, `y_h10`, `y_h30`: other horizons (sensitivity).

## Features (all known at time `t`)

- `f_d0` ... `f_d30`: the link's own deficit at `t`, `t - 5`, ..., `t - 30` min. A missing update carries the last
  value forward for at most {s['carry_max_min']} min (never interpolated), so a lag can be up to {s['carry_max_min']} min older than
  its name; `f_prev_missing` = 1 if there was no update at `t - 5`. `f_d_change15` = `f_d0 - f_d15`.
- `f_up_d0` ... `f_up_d30`, `f_dn_d0` ... `f_dn_d30`: the largest deficit among the upstream / downstream links at
  the same lags. Neighbours: a link's end point within {s['neighbour_tol_m']} m of another's start point
  (`neighbours.parquet`, {lk['neighbour_pairs']:,} pairs). `f_up_none` / `f_dn_none` = 1 if the link has none (values then 0).
- `f_rain15`, `f_rain30`: rainfall (mm) at the nearest NEA station over the 15 / 30 min ending at `t - {s['rain_lag_min']}`
  (allowance for publication lag). `f_rain15_missing` / `f_rain30_missing` = 1 if the station had no reading in
  that window (its total is then 0).
- `f_slot15` (15-minute slot of the day; 24-87 for 06:00-22:00), `f_fri` (1 = Friday).
- `f_conn_in_d0` ... `f_conn_in_d30`, `f_conn_out_d0` ... `f_conn_out_d30`: the largest deficit among the roads that
  lead into / out of this link (slip roads, arterials, ...; {lk['connector_links']} links joining {lk['links_with_connector']} expressway links,
  `connectors.parquet`), against their own frozen norm (`connector_norm.parquet`), same lags and carry rule.
  `f_conn_in_none` / `f_conn_out_none` = 1 if the link has none; `f_conn_in_missing` / `f_conn_out_missing` = 1 if one
  lag had no value. Values are then 0. These inputs are optional: compare models with and without them.

## Other columns

| Column | Meaning |
|---|---|
| `t` | LTA update time (Singapore time, no zone), on the 5-minute grid |
| `date`, `daytype`, `slot15` | date, `Mon-Thu` / `Fri`, 15-minute slot (for folds, B1 and the day bootstrap) |
| `LinkID`, `RoadName` | LTA link and its road |
| `heldout_road`, `use` | see Rules |
| `info_band` | speed band 1-8 (8 = 70 km/h or more) |
| `info_norm_band`, `info_low` | frozen norm (may end in .5) and low at `t` |
| `info_rain_mm` | NEA reading timestamped `t` (5 min ending at `t`); not lagged |
| `info_station_id`, `info_station_km` | nearest rain station and its distance from the link midpoint |
| `info_weekday`, `info_school_period`, `info_olevel_venue_schools_ended` | calendar (1 = Monday; drift check before/after 23 Oct) |
| `info_t_from_retrieval` | `t` is our retrieval time because LTA gave none |

Other files: `links.parquet` (coordinates, `road`, `presence_week1`, `in_population`, `heldout_road`),
`neighbours.parquet`, `norm.parquet`, `connectors.parquet` (`LinkID` of the joining road, `joins` = expressway link,
`kind` = into / out_of, its road name and category), `connector_norm.parquet`, `days.csv` (per day: `updates_06_22` of 192, `rows`, `share_use`),
`incidents.parquet` (for label audit and error analysis; as a predictor only with incidents reported before `t`,
never "Heavy Traffic").

Contains information from LTA DataMall, NEA and MOM accessed from data.gov.sg, made available under the
Singapore Open Data Licence version 1.0 (https://data.gov.sg/open-data-licence).
"""


if __name__ == "__main__":
    main()
