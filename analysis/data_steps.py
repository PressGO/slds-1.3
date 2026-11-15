"""data_steps.py - the steps that turn the raw LTA files into the model tables (data version 4).

Each function takes tables and returns tables; only the read_* functions touch files, and nothing here writes.
build_data.py runs the steps in order and checks every result; test_data_steps.py tests each step on small
made-up data with known answers; verify_data.py recomputes sample rows from the raw files in a different way.
Settings and the decisions behind them: data_settings.py, DECISIONS.md, PROJECT_PLAN.md §4.

AI disclosure: drafted with Claude (Anthropic) on 14 Nov 2026; log in AI_USE.md.
"""

from __future__ import annotations

import gzip
import json
import random
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl

import data_settings as S

STEP = timedelta(minutes=S.STEP_MIN)
COORDS = ["StartLon", "StartLat", "EndLon", "EndLat"]
DCOLS = [f"d{m}" for m in S.LAGS]                       # lag names: d0 = now, d5 = 5 min ago, ...


# ----------------------------------------------------------------------------------------------------------
# Time
# ----------------------------------------------------------------------------------------------------------

def parse_sgt(col: pl.Expr) -> pl.Expr:
    """'2026-11-10T00:01:50+0800', '...+08:00' or '2026-11-10 00:00:00' -> naive Singapore time; else null."""
    s = col.str.replace(r"(\+08:?00)$", "").str.replace("T", " ")
    return pl.coalesce(s.str.to_datetime("%Y-%m-%d %H:%M:%S", strict=False, time_unit="us"),
                       s.str.to_datetime("%Y-%m-%d %H:%M:%S%.f", strict=False, time_unit="us"),
                       s.str.to_datetime("%Y-%m-%d %H:%M", strict=False, time_unit="us"))


def slot15(t: pl.Expr) -> pl.Expr:
    """15-minute slot of the day: 0 = 00:00-00:14, ..., 24 = 06:00-06:14, ..., 95 = 23:45-23:59."""
    return (t.dt.hour().cast(pl.Int16) * 4 + t.dt.minute().cast(pl.Int16) // 15).cast(pl.Int16)


def file_time(path: Path) -> datetime | None:
    """Retrieval time from a collector file name: sb_20261110_000150.csv.gz, sbraw_20261110_0000.jsonl.gz,
    incidents_20261114_182431.jsonl.gz."""
    m = re.search(r"_(\d{8})_(\d{4,6})\.", path.name)
    if not m:
        return None
    hms = m.group(2).ljust(6, "0")
    return datetime.strptime(m.group(1) + hms, "%Y%m%d%H%M%S")


# ----------------------------------------------------------------------------------------------------------
# Days: day type and split
# ----------------------------------------------------------------------------------------------------------

def split_of(d: pl.Expr) -> pl.Expr:
    """train / validate / test by the date of t (data_settings.SPLITS); null outside them."""
    e = pl.lit(None, pl.Utf8)
    for name, (a, b) in reversed(list(S.SPLITS.items())):
        e = pl.when(d.is_between(a, b)).then(pl.lit(name)).otherwise(e)
    return e


def day_table(first: date, last: date, holidays: set[date]) -> pl.DataFrame:
    """One row per date: weekday (1 = Monday), is_holiday, daytype, split, in_population (the proposal's days:
    day type in POPULATION_DAYTYPES, i.e. Monday to Friday and not a public holiday)."""
    days = pl.DataFrame({"date": pl.date_range(first, last, "1d", eager=True)})
    return (days.with_columns(pl.col("date").dt.weekday().cast(pl.Int8).alias("weekday"),
                              pl.col("date").is_in(sorted(holidays)).alias("is_holiday"))
                .with_columns(pl.when(pl.col("is_holiday") | (pl.col("weekday") == 7)).then(pl.lit("sunday_or_holiday"))
                                .when(pl.col("weekday") == 6).then(pl.lit("saturday"))
                                .otherwise(pl.lit("weekday")).alias("daytype"),
                              split_of(pl.col("date")).alias("split"))
                .with_columns(pl.col("daytype").is_in(list(S.POPULATION_DAYTYPES)).alias("in_population")))


def heldout_roads(roads: list[str]) -> list[str]:
    """The roads held out for the transfer check: HELDOUT_N of the roads (without NEVER_HELD_OUT), drawn with
    HELDOUT_SEED from the sorted list, so the order of the input never matters. The same draw as data v1-v2."""
    pool = sorted(set(roads) - set(S.NEVER_HELD_OUT))
    return sorted(random.Random(S.HELDOUT_SEED).sample(pool, S.HELDOUT_N))


# ----------------------------------------------------------------------------------------------------------
# Speed bands: raw rows -> one row per link and LTA update
# ----------------------------------------------------------------------------------------------------------

SB_SCHEMA = {"retrieved_at": pl.Utf8, "last_updated": pl.Utf8, "LinkID": pl.Utf8, "SpeedBand": pl.Int64}


def read_speedband_file(path: Path, keep_ids: list[str], file_no: int) -> pl.DataFrame:
    """One compact collector file (retrieved_at, last_updated, LinkID, SpeedBand), only the links in keep_ids.
    Times are parsed here; a time that cannot be parsed stays null and is counted by clean_speedbands."""
    df = pl.read_csv(path, schema=SB_SCHEMA).with_row_index("row_no")
    return (df.filter(pl.col("LinkID").is_in(keep_ids))
              .select(parse_sgt(pl.col("retrieved_at")).alias("retrieved"),
                      parse_sgt(pl.col("last_updated")).alias("t"),
                      "LinkID", "SpeedBand", pl.lit(file_no, pl.Int32).alias("file_no"), "row_no"))


def clean_speedbands(raw: pl.DataFrame) -> tuple[pl.DataFrame, dict]:
    """raw: retrieved, t, LinkID, SpeedBand, file_no, row_no (several collectors and fetches mixed).
    Returns one row per (LinkID, t): t = LTA's update time for the row, band = SpeedBand if 1-8 (else null),
    retrieved = when we first fetched it. A link and update fetched more than once (both collectors, or a page
    fetched again) keeps the earliest fetch; 'conflicts' counts those whose bands disagree (expected 0)."""
    stats = {"rows_read": raw.height,
             "no_update_time": int(raw["t"].null_count()),
             "no_retrieval_time": int(raw["retrieved"].null_count()),
             "band_outside_1_8": int(raw.filter(~pl.col("SpeedBand").is_between(1, 8)).height)}
    df = (raw.filter(pl.col("t").is_not_null())
             .with_columns(pl.when(pl.col("SpeedBand").is_between(1, 8)).then(pl.col("SpeedBand"))
                             .cast(pl.Int8).alias("band")))
    groups = df.group_by("LinkID", "t").agg(pl.len().alias("n"), pl.col("band").n_unique().alias("n_bands"))
    stats["link_updates_fetched_twice_or_more"] = int(groups.filter(pl.col("n") > 1).height)
    stats["conflicts"] = int(groups.filter(pl.col("n_bands") > 1).height)
    panel = (df.sort("retrieved", "file_no", "row_no", nulls_last=True)
               .unique(["LinkID", "t"], keep="first", maintain_order=True)
               .select("t", "LinkID", "band", "retrieved")
               .sort("t", "LinkID"))
    stats["rows_kept"] = panel.height
    return panel, stats


# ----------------------------------------------------------------------------------------------------------
# Link registry (from the hourly raw JSON snapshots of the whole network)
# ----------------------------------------------------------------------------------------------------------

_RECORD = pl.Struct({"LinkID": pl.Utf8, "RoadName": pl.Utf8, "RoadCategory": pl.Utf8,
                     **{c: pl.Utf8 for c in COORDS}})
_BODY = pl.Struct({"lastUpdatedTime": pl.Utf8, "value": pl.List(_RECORD)})


def read_registry_file(path: Path, file_no: int) -> pl.DataFrame:
    """One raw snapshot file (one JSON page per line) -> one row per link record with its attributes."""
    lines = pl.read_ndjson(path, schema={"endpoint": pl.Utf8, "retrieved_at": pl.Utf8, "page": pl.Int64,
                                         "body": pl.Utf8})
    return (lines.with_columns(pl.col("body").str.json_decode(_BODY).struct.field("value").alias("v"))
                 .select(parse_sgt(pl.col("retrieved_at")).alias("retrieved"), "page", "v")
                 .explode("v", empty_as_null=False).unnest("v")
                 .with_columns(pl.lit(file_no, pl.Int32).alias("file_no")))


def registry_versions(snaps: pl.DataFrame) -> pl.DataFrame:
    """snaps: retrieved, file_no, LinkID, RoadName, RoadCategory, StartLon ... EndLat (strings from LTA), for
    a batch of snapshot files. One row per link and attribute version (name, category, coordinates) with
    when it was first and last seen and in how many of the batch's files. Batches are combined by
    build_registry, so the files never have to be in memory at once."""
    s = snaps.with_columns(pl.col("RoadCategory").cast(pl.Int64, strict=False),
                           *[pl.col(c).cast(pl.Float64, strict=False) for c in COORDS])
    return (s.group_by("LinkID", "RoadName", "RoadCategory", *COORDS)
             .agg(pl.col("retrieved").min().alias("first_seen"), pl.col("retrieved").max().alias("last_seen"),
                  pl.col("file_no").n_unique().alias("n_files")))


def build_registry(versions: pl.DataFrame, n_files: int) -> pl.DataFrame:
    """versions: registry_versions() of every batch, stacked. One row per link: its latest attributes, when
    first and last seen, in how many snapshot files, how many attribute versions and road categories it had."""
    attrs = ["RoadName", "RoadCategory", *COORDS]
    v = (versions.group_by("LinkID", *attrs)
                 .agg(pl.col("first_seen").min(), pl.col("last_seen").max(), pl.col("n_files").sum()))
    latest = (v.sort("LinkID", "last_seen", *attrs, nulls_last=True)
               .group_by("LinkID", maintain_order=True).agg([pl.col(c).last() for c in attrs]))
    per_link = v.group_by("LinkID").agg(pl.col("first_seen").min(), pl.col("last_seen").max(),
                                        pl.col("n_files").sum().alias("n_snapshots"),
                                        pl.len().alias("n_attribute_versions"),
                                        pl.col("RoadCategory").n_unique().alias("n_categories"))
    return (latest.join(per_link, on="LinkID")
                  .with_columns((pl.col("n_snapshots") / n_files).alias("presence_snapshots"))
                  .sort("LinkID"))


# ----------------------------------------------------------------------------------------------------------
# Geometry: neighbours and joining roads
# ----------------------------------------------------------------------------------------------------------

M_PER_DEG = 111_320.0
COS_LAT = float(np.cos(np.radians(1.35)))                # Singapore's latitude


def xy_m(lon, lat) -> np.ndarray:
    """Degrees -> metres on a flat local grid (error < 0.1% over Singapore; distances here are 0-5 m)."""
    return np.c_[np.asarray(lon, dtype=float) * M_PER_DEG * COS_LAT, np.asarray(lat, dtype=float) * M_PER_DEG]


def close_pairs(a: np.ndarray, b: np.ndarray, tol: float, chunk: int = 4000):
    """All (i, j, distance) with |a_i - b_j| <= tol metres."""
    ii, jj, dd = [np.empty(0, int)], [np.empty(0, int)], [np.empty(0)]
    for s in range(0, len(a), chunk):
        d = np.sqrt(((a[s:s + chunk, None, :] - b[None, :, :]) ** 2).sum(-1))
        i, j = np.nonzero(d <= tol)
        ii.append(i + s), jj.append(j), dd.append(d[i, j])
    return np.concatenate(ii), np.concatenate(jj), np.concatenate(dd)


def neighbour_pairs(links: pl.DataFrame) -> pl.DataFrame:
    """Downstream neighbours among the given links: B is downstream of A when B starts within NEIGHBOUR_TOL_M
    of where A ends (a link is never its own neighbour)."""
    end, start = xy_m(links["EndLon"], links["EndLat"]), xy_m(links["StartLon"], links["StartLat"])
    i, j, d = close_pairs(end, start, S.NEIGHBOUR_TOL_M)
    ids = links["LinkID"].to_numpy()
    keep = i != j
    return (pl.DataFrame({"LinkID": ids[i[keep]], "downstream": ids[j[keep]], "gap_m": d[keep].round(2)})
              .sort("LinkID", "downstream"))


def connector_pairs(registry: pl.DataFrame, xw_ids: list[str]) -> pl.DataFrame:
    """Roads that join an expressway link: a non-expressway link whose end is within CONNECTOR_TOL_M of the
    expressway link's start leads 'into' it; one whose start is within CONNECTOR_TOL_M of its end leads
    'out_of' it. One row per (joining link, expressway link, kind)."""
    xw = registry.filter(pl.col("LinkID").is_in(xw_ids))
    other = registry.filter(~pl.col("LinkID").is_in(xw_ids)).drop_nulls(COORDS)
    parts = []
    for kind, a, b in (("into", xy_m(other["EndLon"], other["EndLat"]), xy_m(xw["StartLon"], xw["StartLat"])),
                       ("out_of", xy_m(other["StartLon"], other["StartLat"]), xy_m(xw["EndLon"], xw["EndLat"]))):
        i, j, d = close_pairs(a, b, S.CONNECTOR_TOL_M)
        parts.append(pl.DataFrame({"LinkID": other["LinkID"].to_numpy()[i], "joins": xw["LinkID"].to_numpy()[j],
                                   "kind": [kind] * len(i), "gap_m": d.round(2)},
                                  schema={"LinkID": pl.Utf8, "joins": pl.Utf8, "kind": pl.Utf8, "gap_m": pl.Float64}))
    return (pl.concat(parts)
              .join(other.select("LinkID", "RoadName", "RoadCategory"), on="LinkID", how="left")
              .select("LinkID", "joins", "kind", "RoadName", "RoadCategory", "gap_m")
              .sort("joins", "kind", "LinkID"))


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


def nearest_station(links: pl.DataFrame, stations: pl.DataFrame) -> pl.DataFrame:
    """Nearest rain station to each link's midpoint (ties: the first station_id in sorted order)."""
    st = stations.sort("station_id")
    mid_lat = ((links["StartLat"] + links["EndLat"]) / 2).to_numpy()[:, None]
    mid_lon = ((links["StartLon"] + links["EndLon"]) / 2).to_numpy()[:, None]
    d = haversine_km(mid_lat, mid_lon, st["lat"].to_numpy()[None, :], st["lon"].to_numpy()[None, :])
    k = d.argmin(axis=1)
    return pl.DataFrame({"LinkID": links["LinkID"], "station_id": st["station_id"].to_numpy()[k],
                         "station_km": d[np.arange(len(k)), k].round(3)})


# ----------------------------------------------------------------------------------------------------------
# Population and normal level
# ----------------------------------------------------------------------------------------------------------

def in_hours(t: pl.Expr) -> pl.Expr:
    return t.dt.hour().is_between(S.HOUR_FROM, S.HOUR_TO - 1)


def presence_week1(panel: pl.DataFrame, ids: list[str]) -> tuple[pl.DataFrame, int]:
    """Share of the update times captured in PRESENCE_DAYS (06:00-22:00) at which each link has a band, and
    the number of update times captured."""
    week = panel.filter(pl.col("LinkID").is_in(ids) & pl.col("t").dt.date().is_between(*S.PRESENCE_DAYS)
                        & in_hours(pl.col("t")))
    n_updates = week["t"].n_unique()
    got = week.filter(pl.col("band").is_not_null()).group_by("LinkID").agg(pl.col("t").n_unique().alias("n"))
    return (pl.DataFrame({"LinkID": ids}).join(got, on="LinkID", how="left")
              .select("LinkID", (pl.col("n").fill_null(0) / n_updates).alias("presence_week1"))
              .sort("LinkID")), n_updates


def normal_level(panel: pl.DataFrame, days: pl.DataFrame) -> pl.DataFrame:
    """Median band per link x day type x 15-min slot over the NORM_SPLIT days, all hours (so the look-backs
    before 06:00 and the look-aheads after 22:00 have a level too); n_obs = bands it is the median of."""
    return (panel.filter(pl.col("band").is_not_null())
                 .with_columns(pl.col("t").dt.date().alias("date"), slot15(pl.col("t")).alias("slot15"))
                 .join(days.select("date", "daytype", "split"), on="date", how="inner")
                 .filter(pl.col("split") == S.NORM_SPLIT)
                 .group_by("LinkID", "daytype", "slot15")
                 .agg(pl.col("band").median().alias("norm_band"), pl.len().alias("n_obs"),
                      pl.col("date").n_unique().alias("n_days"))
                 .sort("LinkID", "daytype", "slot15"))


# ----------------------------------------------------------------------------------------------------------
# Regular 5-minute grid: deficit, label, look-backs
# ----------------------------------------------------------------------------------------------------------

def deficit_grid(panel: pl.DataFrame, norm: pl.DataFrame, days: pl.DataFrame, ids: list[str],
                 t_from: datetime, t_to: datetime) -> pl.DataFrame:
    """Every link x every 5-min time from t_from to t_to (missing updates included as empty rows), sorted by
    link and time, so a shift of k rows within a link is exactly k x 5 min.
    deficit = normal level - band (null if either is missing); dfill = deficit, or if missing the value
    5 min earlier (at most CARRY_MAX min, never the future); filled = dfill came from an earlier update."""
    times = pl.DataFrame({"t": pl.datetime_range(t_from, t_to, STEP, eager=True, time_unit="us")})
    g = (pl.DataFrame({"LinkID": sorted(ids)}).join(times, how="cross")
           .join(panel.select("LinkID", "t", "band", *(["retrieved"] if "retrieved" in panel.columns else [])),
                 on=["LinkID", "t"], how="left")
           .with_columns(pl.col("t").dt.date().alias("date"), slot15(pl.col("t")).alias("slot15"))
           .join(days.select("date", "daytype"), on="date", how="left")
           .join(norm.select("LinkID", "daytype", "slot15", "norm_band"), on=["LinkID", "daytype", "slot15"],
                 how="left")
           .sort("LinkID", "t")
           .with_columns((pl.col("norm_band").cast(pl.Float32) - pl.col("band").cast(pl.Float32)).alias("deficit")))
    g = g.with_columns(pl.col("deficit").forward_fill(limit=S.CARRY_MAX // S.STEP_MIN).over("LinkID").alias("dfill"))
    return g.with_columns((pl.col("deficit").is_null() & pl.col("dfill").is_not_null()).alias("filled"))


def add_labels(g: pl.DataFrame) -> pl.DataFrame:
    """low = deficit >= THRESHOLD. U = low at t and at the CONSECUTIVE - 1 updates before it; null when any of
    those updates is missing (strict rule, DECISIONS.md 11 Nov). y = U at t + HORIZON; y_h* = other horizons.
    Uses the deficit as captured, never the reused (filled) value."""
    low = pl.col("deficit") >= S.THRESHOLD
    g = g.with_columns(low.alias("low"))
    parts = [pl.col("low").shift(k).over("LinkID") for k in range(S.CONSECUTIVE)]
    u = pl.when(pl.any_horizontal([p.is_null() for p in parts])).then(None).otherwise(pl.all_horizontal(parts))
    g = g.with_columns(u.alias("U"))
    shifts = {"y": S.HORIZON, **{f"y_h{h}": h for h in S.EXTRA_HORIZONS}}
    return g.with_columns([pl.col("U").shift(-(m // S.STEP_MIN)).over("LinkID").alias(n) for n, m in shifts.items()])


def add_lags(g: pl.DataFrame, prefix: str = "") -> pl.DataFrame:
    """{prefix}d0 ... {prefix}d30: dfill at t, t - 5, ..., t - 30; {prefix}n_filled: how many of them were
    reused from an earlier update."""
    g = g.with_columns([pl.col("dfill").shift(m // S.STEP_MIN).over("LinkID").alias(f"{prefix}{c}")
                        for m, c in zip(S.LAGS, DCOLS)])
    filled = [pl.col("filled").shift(m // S.STEP_MIN).over("LinkID").fill_null(False).cast(pl.Int8) for m in S.LAGS]
    return g.with_columns(pl.sum_horizontal(filled).cast(pl.Int8).alias(f"{prefix}n_filled"))


def worst_of(keys: pl.DataFrame, pairs: pl.DataFrame, lagged: pl.DataFrame, names: list[str]) -> pl.DataFrame:
    """For each (LinkID, t) in keys: the largest of the related links' look-back values at the same t.
    pairs: LinkID -> nbr. lagged: nbr, t and the columns DCOLS. Returns LinkID, t, names (null if the link
    has related links but none had a value)."""
    p = pairs.filter(pl.col("LinkID").is_in(keys["LinkID"].unique().to_list()))
    lag = lagged.filter(pl.col("nbr").is_in(p["nbr"].unique().to_list()))   # only the links needed (memory)
    return (keys.join(p, on="LinkID", how="inner")
                .join(lag, on=["nbr", "t"], how="left")
                .group_by("LinkID", "t")
                .agg([pl.col(c).max().alias(n) for c, n in zip(DCOLS, names)]))


def neighbour_inputs(rows: pl.DataFrame, pairs: pl.DataFrame, lagged: pl.DataFrame) -> pl.DataFrame:
    """f_up_d* / f_dn_d*: the worst deficit among the links just upstream / downstream. A link with none on a
    side gets f_up_none / f_dn_none = 1 and 0 for the values; a link with some but no value stays null."""
    keys = rows.select("LinkID", "t")
    for side, a, b in (("dn", "LinkID", "downstream"), ("up", "downstream", "LinkID")):
        p = pairs.select(pl.col(a).alias("LinkID"), pl.col(b).alias("nbr"))
        names = [f"f_{side}_{c}" for c in DCOLS]
        agg = worst_of(keys, p, lagged, names)
        has = p.select("LinkID").unique().with_columns(pl.lit(0, pl.Int8).alias(f"f_{side}_none"))
        rows = (rows.join(agg, on=["LinkID", "t"], how="left").join(has, on="LinkID", how="left")
                    .with_columns(pl.col(f"f_{side}_none").fill_null(1).cast(pl.Int8))
                    .with_columns([pl.when(pl.col(f"f_{side}_none") == 1).then(pl.lit(0.0, pl.Float32))
                                     .otherwise(pl.col(n)).cast(pl.Float32).alias(n) for n in names]))
    return rows


def connector_inputs(rows: pl.DataFrame, conn: pl.DataFrame, clagged: pl.DataFrame) -> pl.DataFrame:
    """f_conn_in_d* / f_conn_out_d*: the worst deficit among the roads leading into / out of the link, against
    their own normal level. No such road: *_none = 1; a road but a missing value: *_missing = 1. Values are
    then 0. Not required for `use`, so models with and without them use the same rows."""
    keys = rows.select("LinkID", "t")
    for kind, side in (("into", "in"), ("out_of", "out")):
        p = conn.filter(pl.col("kind") == kind).select(pl.col("joins").alias("LinkID"), pl.col("LinkID").alias("nbr")).unique()
        names = [f"f_conn_{side}_{c}" for c in DCOLS]
        agg = worst_of(keys, p, clagged, names)
        has = p.select("LinkID").unique().with_columns(pl.lit(0, pl.Int8).alias(f"f_conn_{side}_none"))
        rows = (rows.join(agg, on=["LinkID", "t"], how="left").join(has, on="LinkID", how="left")
                    .with_columns(pl.col(f"f_conn_{side}_none").fill_null(1).cast(pl.Int8))
                    .with_columns(((pl.col(f"f_conn_{side}_none") == 0)
                                   & pl.any_horizontal([pl.col(n).is_null() for n in names])).cast(pl.Int8)
                                  .alias(f"f_conn_{side}_missing"))
                    .with_columns([pl.col(n).fill_null(0.0).cast(pl.Float32) for n in names]))
    return rows


def rain_inputs(rain: pl.DataFrame, station_ids: list[str], t_from: datetime, t_to: datetime) -> pl.DataFrame:
    """Per station and 5-min time t: total rain over the readings timestamped t - RAIN_LAG back to
    t - window (f_rain15: t-5, t-10, t-15; f_rain30: t-5 ... t-30). A missing reading is skipped; when all
    in a window are missing the total is 0 and its *_missing flag is 1. Summed in whole tenths of a mm (NEA
    readings are multiples of 0.1 mm), so a dry window is exactly 0, never a rounding leftover like 1e-16."""
    times = pl.DataFrame({"t": pl.datetime_range(t_from - timedelta(hours=1), t_to, STEP, eager=True, time_unit="us")})
    g = (pl.DataFrame({"station_id": sorted(station_ids)}).join(times, how="cross")
           .join(rain.select("station_id", "t", "rain_mm"), on=["station_id", "t"], how="left")
           .sort("station_id", "t")
           .with_columns((pl.col("rain_mm") * 10).round().cast(pl.Int64)
                         .shift(S.RAIN_LAG // S.STEP_MIN).over("station_id").alias("r10")))
    g = g.with_columns([pl.col("r10").rolling_sum(w // S.STEP_MIN, min_samples=1).over("station_id").alias(n)
                        for n, w in S.RAIN_WINDOWS.items()])
    g = g.with_columns([pl.col(n).is_null().cast(pl.Int8).alias(f"{n}_missing") for n in S.RAIN_WINDOWS])
    # tenths -> mm with numpy: its division is exact (6 / 10 = 0.6), while polars divides by multiplying with
    # 0.1, which gives 0.6000000000000001
    g = g.with_columns([pl.Series(n, g[n].fill_null(0).to_numpy() / 10.0) for n in S.RAIN_WINDOWS])
    return g.select("station_id", "t", *S.RAIN_WINDOWS, *[f"{n}_missing" for n in S.RAIN_WINDOWS])


def calendar_inputs(rows: pl.DataFrame) -> pl.DataFrame:
    """f_slot15 (time of day), f_mon ... f_sun (one-hot day of the week), f_holiday (public holiday).
    rows need t, weekday (1 = Monday) and is_holiday."""
    return rows.with_columns(slot15(pl.col("t")).alias("f_slot15"),
                             *[(pl.col("weekday") == k + 1).cast(pl.Int8).alias(c) for k, c in enumerate(S.WEEKDAY_COLUMNS)],
                             pl.col("is_holiday").cast(pl.Int8).alias("f_holiday"))


BASE_COLS = ["LinkID", "t", "date", "band", "norm_band", "deficit", "low", "U", "y",
             *[f"y_h{h}" for h in S.EXTRA_HORIZONS], *[f"f_{c}" for c in DCOLS], "f_n_filled"]


def base_rows(panel: pl.DataFrame, norm: pl.DataFrame, days: pl.DataFrame, ids: list[str], t_from: datetime,
              t_to: datetime, window_dates: list[date]) -> pl.DataFrame:
    """Labels and the link's own look-backs on the 5-min grid from t_from to t_to, kept for the rows
    06:00-22:00 of window_dates (look-backs reach 05:30 and labels 22:30 of the same day)."""
    g = add_lags(add_labels(deficit_grid(panel, norm, days, ids, t_from, t_to)), prefix="f_")
    cols = BASE_COLS + (["retrieved"] if "retrieved" in g.columns else [])
    return g.filter(in_hours(pl.col("t")) & pl.col("date").is_in(window_dates)).select(cols)


def lag_table(rows: pl.DataFrame, prefix: str = "f_") -> pl.DataFrame:
    """nbr, t, d0 ... d30 from rows with {prefix}d0 ...: the look-up table for neighbours or joining roads."""
    return rows.select(pl.col("LinkID").alias("nbr"), "t", *[pl.col(f"{prefix}{c}").alias(c) for c in DCOLS])


def assemble(base: pl.DataFrame, pairs: pl.DataFrame, lagged: pl.DataFrame, conn: pl.DataFrame,
             clagged: pl.DataFrame, near: pl.DataFrame, rin: pl.DataFrame, rain_now: pl.DataFrame,
             days: pl.DataFrame, road: pl.DataFrame, school: pl.DataFrame) -> pl.DataFrame:
    """All inputs and `use` for base rows: day columns, neighbours, joining roads, rain, calendar.
    days: date, weekday, is_holiday, daytype, split. Sorted by link and time."""
    r = (base.join(days, on="date", how="left")
             .with_columns((pl.col("f_d0") - pl.col("f_d15")).alias("f_d_change15")))
    r = neighbour_inputs(r, pairs, lagged)
    r = connector_inputs(r, conn, clagged)
    r = (r.join(near, on="LinkID", how="left").join(rin, on=["station_id", "t"], how="left")
          .join(rain_now, on=["station_id", "t"], how="left"))
    r = calendar_inputs(r)
    core = core_input_columns()
    r = r.with_columns((pl.col("y").is_not_null() & pl.col("U").is_not_null()
                        & pl.all_horizontal([pl.col(c).is_not_null() for c in core])).alias("use"),
                       pl.col("norm_band").cast(pl.Float32))
    return r.join(road, on="LinkID", how="left").join(school, on="date", how="left").sort("LinkID", "t")


def core_input_columns() -> list[str]:
    """The f_ columns every usable row must have (the joining-road inputs f_conn_* are extra)."""
    return ([f"f_{c}" for c in DCOLS] + ["f_d_change15", "f_n_filled"]
            + [f"f_{s}_{c}" for s in ("up", "dn") for c in DCOLS] + ["f_up_none", "f_dn_none"]
            + list(S.RAIN_WINDOWS) + [f"{n}_missing" for n in S.RAIN_WINDOWS]
            + ["f_slot15", *S.WEEKDAY_COLUMNS, "f_holiday"])


def model_input_columns() -> list[str]:
    """The core inputs in the main files: without NOT_IN_MAIN_FILES (always 0 on the population's days)."""
    return [c for c in core_input_columns() if c not in S.NOT_IN_MAIN_FILES]


def connector_input_columns() -> list[str]:
    return ([f"f_conn_{s}_{c}" for s in ("in", "out") for c in DCOLS]
            + [f"f_conn_{s}_{x}" for s in ("in", "out") for x in ("none", "missing")])


# ----------------------------------------------------------------------------------------------------------
# Incidents (for checking labels and explaining errors; not a model input)
# ----------------------------------------------------------------------------------------------------------

_INC = pl.Struct({"value": pl.List(pl.Struct({"Type": pl.Utf8, "Latitude": pl.Float64, "Longitude": pl.Float64,
                                              "Message": pl.Utf8}))})


def read_incident_file(path: Path, snap_no: int) -> pl.DataFrame:
    """One saved incidents snapshot (pages as JSON lines) -> snap_no, retrieved, one row per incident.
    An empty file gives one row with Type null (a snapshot without incidents), so it never stops a build."""
    lines = pl.read_ndjson(path, schema={"endpoint": pl.Utf8, "retrieved_at": pl.Utf8, "page": pl.Int64,
                                         "body": pl.Utf8})
    if lines.height == 0:
        return pl.DataFrame({"retrieved": [file_time(path)], "Type": [None], "Latitude": [None], "Longitude": [None],
                             "Message": [None], "snap_no": [snap_no]},
                            schema={"retrieved": pl.Datetime("us"), "Type": pl.Utf8, "Latitude": pl.Float64,
                                    "Longitude": pl.Float64, "Message": pl.Utf8, "snap_no": pl.Int32})
    return (lines.with_columns(pl.col("body").str.json_decode(_INC).struct.field("value").alias("v"))
                 .select(parse_sgt(pl.col("retrieved_at")).alias("retrieved"), "v")
                 .explode("v", empty_as_null=True).unnest("v")
                 .with_columns(pl.lit(snap_no, pl.Int32).alias("snap_no")))


def incident_episodes(snaps: pl.DataFrame) -> pl.DataFrame:
    """snaps: snap_no (0, 1, 2, ... one per saved snapshot), retrieved, Type, Latitude, Longitude, Message;
    a snapshot with no incidents has one row with Type null. An incident is listed from the snapshot where it
    appears (first_seen) to the first later snapshot without it (last_seen_before; null if still listed at
    the end). 'reported' is the time at the start of LTA's message, e.g. '(14/11)18:19 ...'."""
    times = snaps.group_by("snap_no").agg(pl.col("retrieved").first()).sort("snap_no")
    last_snap = int(times["snap_no"].max())
    inc = (snaps.filter(pl.col("Type").is_not_null())
                .unique(["snap_no", "Type", "Message", "Latitude", "Longitude"])
                .sort("Type", "Message", "Latitude", "Longitude", "snap_no", nulls_last=True))
    key = ["Type", "Message", "Latitude", "Longitude"]
    ep = (inc.with_columns((pl.col("snap_no") - pl.int_range(pl.len()).over(key)).alias("run"))
             .group_by(*key, "run")
             .agg(pl.col("snap_no").min().alias("a"), pl.col("snap_no").max().alias("b"))
             .with_columns(pl.when(pl.col("b") < last_snap).then(pl.col("b") + 1).alias("gone"))
             .join(times.rename({"snap_no": "a", "retrieved": "first_seen"}), on="a", how="left")
             .join(times.rename({"snap_no": "gone", "retrieved": "last_seen_before"}), on="gone", how="left"))
    year = pl.col("first_seen").dt.year().cast(pl.Utf8)
    m = pl.col("Message").str.extract_groups(r"^\((\d{1,2})/(\d{1,2})\)(\d{1,2}):(\d{2})")
    reported = pl.concat_str([year, m.struct.field("2").str.zfill(2), m.struct.field("1").str.zfill(2),
                              m.struct.field("3").str.zfill(2), m.struct.field("4")], separator="-")
    return (ep.with_columns(reported.str.to_datetime("%Y-%m-%d-%H-%M", strict=False, time_unit="us").alias("reported"))
              .select(pl.col("Type").alias("type"), pl.col("Message").alias("message"),
                      pl.col("Latitude").alias("lat"), pl.col("Longitude").alias("lon"),
                      "first_seen", "last_seen_before", "reported")
              .sort("first_seen", "type", "message", "lat", "lon"))


def read_json_lines_count(path: Path) -> int:
    """Pages in a raw snapshot file (for the registry check: a full network snapshot has 288)."""
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return sum(1 for _ in f)


def to_json(obj) -> str:
    return json.dumps(obj, indent=2, default=str) + "\n"
