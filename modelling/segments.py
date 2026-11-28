"""segments.py - 1 km segments, docs/data_rules.md rules 26-32 (the proposal's secondary analysis, fixed in advance).

paths_and_segments()  rules 26-27: paths between splits and merges, cut into ~1 km segments by where links start
segment_rows()        rules 28-31: segment band, normal level (train weekdays, frozen), drop, U, y, inputs, use

AI disclosure: drafted with Claude (Anthropic) on 25 Nov 2026; log in AI_USE.md.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta

import numpy as np
import polars as pl

import settings as S

M_PER_DEG = 111_320.0
COS_LAT = math.cos(math.radians(1.35))
LAGS = (0, 5, 10, 15, 20, 25, 30)


def _xy(lon, lat):
    return np.asarray(lon) * M_PER_DEG * COS_LAT, np.asarray(lat) * M_PER_DEG


def paths_and_segments(links: pl.DataFrame, neigh: pl.DataFrame):
    """Rule 26 with the closed-chain case handled explicitly, then rule 27."""
    road = dict(links.select("LinkID", "road").iter_rows())
    xs, ys = _xy(links["StartLon"], links["StartLat"])
    xe, ye = _xy(links["EndLon"], links["EndLat"])
    length = dict(zip(links["LinkID"].to_list(), np.hypot(xe - xs, ye - ys)))
    same = [(a, b) for a, b in neigh.select("LinkID", "downstream").iter_rows() if road[a] == road[b]]
    n_down, n_up = {}, {}
    for a, b in same:
        n_down[a] = n_down.get(a, 0) + 1
        n_up[b] = n_up.get(b, 0) + 1
    nxt = {a: b for a, b in same if n_down[a] == 1 and n_up[b] == 1}
    prv = {b: a for a, b in nxt.items()}
    ids = sorted(links["LinkID"].to_list())
    seen, paths = set(), []
    for start in ids:                                    # paths with a first link (no link continues into it)
        if start in prv or start in seen:
            continue
        chain, l = [], start
        while l is not None and l not in seen:
            chain.append(l)
            seen.add(l)
            l = nxt.get(l)
        paths.append(chain)
    for start in ids:                                    # closed chains: start at the smallest LinkID (text order)
        if start in seen:
            continue
        chain, l = [], start
        while l is not None and l not in seen:
            chain.append(l)
            seen.add(l)
            l = nxt.get(l)
        paths.append(chain)
    rows = []
    for chain in paths:
        pid, s, nums = chain[0], 0.0, []
        for l in chain:
            nums.append(int(math.floor(s / 1000.0)))
            s += length[l]
        seg_len: dict[int, float] = {}
        for l, n in zip(chain, nums):
            seg_len[n] = seg_len.get(n, 0.0) + length[l]
        last = max(nums)
        if last > 0 and seg_len[last] < 500.0:
            nums = [n if n < last else last - 1 for n in nums]
        for pos, (l, n) in enumerate(zip(chain, nums)):
            rows.append((l, f"{pid}-{n}", pid, n, pos, length[l]))
    sl = pl.DataFrame(rows, schema={"LinkID": pl.Utf8, "segment_id": pl.Utf8, "path_id": pl.Utf8, "number": pl.Int32,
                                    "position": pl.Int32, "length_m": pl.Float64}, orient="row")
    mid = links.select("LinkID", ((pl.col("StartLat") + pl.col("EndLat")) / 2).alias("mlat"),
                       ((pl.col("StartLon") + pl.col("EndLon")) / 2).alias("mlon"), "road", "heldout_road")
    segs = (sl.join(mid, on="LinkID")
              .group_by("segment_id", "path_id", "number")
              .agg(pl.col("road").unique().alias("roads"), pl.col("heldout_road").first(), pl.len().alias("n_links"),
                   pl.col("length_m").sum().alias("length_m"),
                   ((pl.col("mlat") * pl.col("length_m")).sum() / pl.col("length_m").sum()).alias("mid_lat"),
                   ((pl.col("mlon") * pl.col("length_m")).sum() / pl.col("length_m").sum()).alias("mid_lon"))
              .with_columns(pl.col("roads").list.first().alias("road"), pl.col("roads").list.len().alias("n_roads"))
              .drop("roads").sort("segment_id"))
    return sl, segs, len(paths)


# ------------------------------------------------------------------------------------------------ days and rain

def day_frame(first: date, last: date, holidays: set[date]) -> pl.DataFrame:
    d = pl.DataFrame({"date": pl.date_range(first, last, "1d", eager=True)})
    return d.with_columns(
        pl.when(pl.col("date").is_in(sorted(holidays)) | (pl.col("date").dt.weekday() == 7)).then(pl.lit("sunday_or_holiday"))
          .when(pl.col("date").dt.weekday() == 6).then(pl.lit("saturday")).otherwise(pl.lit("weekday")).alias("daytype"),
        pl.when(pl.col("date").is_between(*S.TRAIN_DAYS)).then(pl.lit("train"))
          .when(pl.col("date").is_between(*S.VAL_DAYS)).then(pl.lit("validate"))
          .when(pl.col("date").is_between(date(2026, 11, 14), S.TEST_DAYS[1])).then(pl.lit("test"))
          .otherwise(pl.lit(None)).alias("split"))


def read_rain(last: date) -> pl.DataFrame:
    r = pl.read_csv(S.RAIN, schema_overrides={"station_id": pl.Utf8, "timestamp": pl.Utf8, "rain_mm": pl.Float64})
    r = r.select(pl.col("timestamp").str.slice(0, 19).str.strptime(pl.Datetime("us"), "%Y-%m-%dT%H:%M:%S").alias("t"),
                 "station_id", (pl.col("rain_mm") * 10).round().cast(pl.Int64).alias("tenths"))
    return r.filter(pl.col("t").dt.date() <= last)


def eligible_stations(rain: pl.DataFrame, days: pl.DataFrame) -> list[str]:
    """Rule 16: readings in >= 80% of the 288 slots (231 or more) on EVERY train day (any day type)."""
    tdays = days.filter(pl.col("split") == "train")["date"].to_list()
    per = (rain.filter(pl.col("t").dt.date().is_in(tdays)).group_by("station_id", pl.col("t").dt.date().alias("d")).len()
               .filter(pl.col("len") >= 231).group_by("station_id").len())
    return sorted(per.filter(pl.col("len") == len(tdays))["station_id"].to_list())


def nearest(segs: pl.DataFrame, stations: pl.DataFrame) -> pl.DataFrame:
    st = stations.sort("station_id")
    la1, lo1 = np.radians(segs["mid_lat"].to_numpy())[:, None], np.radians(segs["mid_lon"].to_numpy())[:, None]
    la2, lo2 = np.radians(st["lat"].to_numpy())[None, :], np.radians(st["lon"].to_numpy())[None, :]
    a = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    dkm = 6371.0 * 2 * np.arcsin(np.sqrt(a))
    k = dkm.argmin(axis=1)
    return pl.DataFrame({"segment_id": segs["segment_id"], "station_id": st["station_id"].to_numpy()[k],
                         "station_km": dkm[np.arange(len(k)), k]})


# ------------------------------------------------------------------------------------------------ rows

def segment_band(panel: pl.DataFrame, sl: pl.DataFrame, segs: pl.DataFrame) -> pl.DataFrame:
    """Rule 28: length-weighted mean of the captured link bands when they cover >= 80% of the segment's length."""
    j = panel.select("LinkID", "t", "band").filter(pl.col("band").is_not_null()).join(
        sl.select("LinkID", "segment_id", "length_m"), on="LinkID")
    g = j.group_by("segment_id", "t").agg((pl.col("band").cast(pl.Float64) * pl.col("length_m")).sum().alias("lb"),
                                          pl.col("length_m").sum().alias("lc"))
    g = g.join(segs.select("segment_id", pl.col("length_m").alias("seg_len")), on="segment_id")
    return g.filter(pl.col("lc") >= 0.8 * pl.col("seg_len")).select("segment_id", "t", (pl.col("lb") / pl.col("lc")).alias("sband"))


def segment_norm(sband: pl.DataFrame, days: pl.DataFrame) -> pl.DataFrame:
    """Rule 29: median segment band over the train days of the day type (weekday here) and 15-min slot."""
    tw = days.filter((pl.col("split") == "train") & (pl.col("daytype") == "weekday"))["date"].to_list()
    return (sband.filter(pl.col("t").dt.date().is_in(tw))
                 .group_by("segment_id", (pl.col("t").dt.hour().cast(pl.Int16) * 4 + pl.col("t").dt.minute().cast(pl.Int16) // 15).alias("slot15"))
                 .agg(pl.col("sband").median().alias("norm"), pl.len().alias("n_obs")))


def segment_rows(sband: pl.DataFrame, norm: pl.DataFrame, segs: pl.DataFrame, days: pl.DataFrame,
                 rain: pl.DataFrame, station: pl.DataFrame, pairs: pl.DataFrame) -> pl.DataFrame:
    """Rules 29-31 on a complete 5-min grid of the population days in `days`; returns every row with `use`."""
    pdays = days.filter(pl.col("daytype") == "weekday")["date"].to_list()
    grid_t = pl.concat([pl.datetime_range(datetime.combine(d, datetime.min.time()),
                                          datetime.combine(d, datetime.min.time()) + timedelta(hours=23, minutes=55),
                                          "5m", eager=True, time_unit="us").to_frame("t") for d in pdays])
    g = (segs.select("segment_id").join(grid_t, how="cross")
             .join(sband, on=["segment_id", "t"], how="left")
             .with_columns((pl.col("t").dt.hour().cast(pl.Int16) * 4 + pl.col("t").dt.minute().cast(pl.Int16) // 15).alias("slot15"))
             .join(norm.select("segment_id", "slot15", "norm"), on=["segment_id", "slot15"], how="left")
             .sort("segment_id", "t")
             .with_columns((pl.col("norm") - pl.col("sband")).alias("d")))
    # the grid is complete within each day, and a day's rows never need another day (06:00-21:55 +- 30 min)
    over = ["segment_id", pl.col("t").dt.date()]
    g = g.with_columns((pl.col("d") >= S.THRESHOLD).alias("low"))
    g = g.with_columns(pl.col("low").shift(1).over(over).alias("_low_prev"))
    g = g.with_columns(pl.when(pl.col("low").is_null() | pl.col("_low_prev").is_null()).then(None)   # rule 9: unknown
                         .otherwise(pl.col("low") & pl.col("_low_prev")).alias("U")).drop("_low_prev")
    g = g.with_columns(pl.coalesce(pl.col("d"), pl.col("d").shift(1).over(over)).alias("dfill"))
    g = g.with_columns([pl.col("U").shift(-k // 5).over(over).alias("y" if k == 15 else f"y_h{k}") for k in (5, 10, 15, 30)]
                       + [pl.col("dfill").shift(k // 5).over(over).alias(f"f_d{k}") for k in LAGS]
                       + [(pl.col("d").shift(k // 5).over(over).is_null() & pl.col("dfill").shift(k // 5).over(over).is_not_null())
                          .cast(pl.Int8).alias(f"_filled{k}") for k in LAGS])
    g = g.with_columns(pl.sum_horizontal([pl.col(f"_filled{k}") for k in LAGS]).cast(pl.Int8).alias("f_n_filled"),
                       (pl.col("f_d0") - pl.col("f_d15")).alias("f_d_change15")).drop([f"_filled{k}" for k in LAGS])
    # neighbouring segments (rule 30 via rule 14): largest dfill over the downstream / upstream segments
    lagged = g.select("segment_id", "t", *[f"f_d{k}" for k in LAGS])
    for side, a, b in (("dn", "segment_id", "downstream"), ("up", "downstream", "segment_id")):
        p = pairs.select(pl.col(a).alias("segment_id"), pl.col(b).alias("other"))
        has = p.select("segment_id").unique().with_columns(pl.lit(0, pl.Int8).alias(f"f_{side}_none"))
        mx = (p.join(lagged.rename({"segment_id": "other"}), on="other")
               .group_by("segment_id", "t").agg([pl.col(f"f_d{k}").max().alias(f"f_{side}_d{k}") for k in LAGS]))
        g = (g.join(has, on="segment_id", how="left").with_columns(pl.col(f"f_{side}_none").fill_null(1))
              .join(mx, on=["segment_id", "t"], how="left")
              .with_columns([pl.when(pl.col(f"f_{side}_none") == 1).then(0.0).otherwise(pl.col(f"f_{side}_d{k}"))
                             .alias(f"f_{side}_d{k}") for k in LAGS]))
    # rain (rule 16 windows at t-5 ... t-30, exact tenths)
    st = station.select("segment_id", "station_id")
    tt = g.select("segment_id", "t").join(st, on="segment_id")
    rk = rain.select("station_id", "t", "tenths")
    for name, w in (("f_rain15", 15), ("f_rain30", 30)):
        parts = [tt.join(rk.with_columns((pl.col("t") + timedelta(minutes=k)).alias("t")), on=["station_id", "t"], how="left")
                   .select("segment_id", "t", pl.col("tenths").alias(f"r{k}")) for k in range(5, w + 1, 5)]
        acc = parts[0]
        for p_ in parts[1:]:
            acc = acc.join(p_, on=["segment_id", "t"])
        rc = [c for c in acc.columns if c.startswith("r")]
        acc = acc.select("segment_id", "t", (pl.sum_horizontal(rc) / 10.0).alias(name),
                         pl.all_horizontal([pl.col(c).is_null() for c in rc]).cast(pl.Int8).alias(f"{name}_missing"))
        g = g.join(acc, on=["segment_id", "t"], how="left")
        g = g.with_columns(pl.when(pl.col(f"{name}_missing") == 1).then(0.0).otherwise(pl.col(name)).alias(name))
    # calendar, rows of the day window, split, road
    wd = pl.col("t").dt.weekday()
    g = (g.filter((pl.col("t").dt.hour() >= 6) & (pl.col("t").dt.hour() < 22))
          .with_columns(pl.col("slot15").alias("f_slot15"),
                        *[(wd == i + 1).cast(pl.Int8).alias(n) for i, n in enumerate(["f_mon", "f_tue", "f_wed", "f_thu", "f_fri"])],
                        pl.col("t").dt.date().alias("date"))
          .join(days.select("date", "split"), on="date", how="left")
          .join(segs.select("segment_id", "road", "heldout_road"), on="segment_id", how="left"))
    inputs = segment_inputs()
    g = g.with_columns((pl.col("y").is_not_null() & pl.col("U").is_not_null()
                        & pl.all_horizontal([pl.col(c).is_not_null() for c in inputs])).alias("use"))
    return g.select("segment_id", "road", "heldout_road", "t", "date", "split", "use", "U", "y", "y_h5", "y_h10", "y_h30",
                    pl.col("sband").alias("info_band"), pl.col("norm").alias("info_norm"), *inputs).sort("segment_id", "t")


def segment_inputs() -> list[str]:
    return ([f"f_d{k}" for k in LAGS] + ["f_d_change15", "f_n_filled"] + [f"f_up_d{k}" for k in LAGS]
            + [f"f_dn_d{k}" for k in LAGS] + ["f_up_none", "f_dn_none", "f_rain15", "f_rain30", "f_rain15_missing",
                                                "f_rain30_missing", "f_slot15", "f_mon", "f_tue", "f_wed", "f_thu", "f_fri"])


def segment_pairs(sl: pl.DataFrame, neigh: pl.DataFrame) -> pl.DataFrame:
    """Rule 30: segment B is downstream of segment A when some link of A has a downstream link in B, B != A."""
    m = sl.select("LinkID", "segment_id")
    return (neigh.select("LinkID", "downstream").join(m, on="LinkID")
                 .join(m.rename({"LinkID": "downstream", "segment_id": "downstream_seg"}), on="downstream")
                 .filter(pl.col("segment_id") != pl.col("downstream_seg"))
                 .select("segment_id", pl.col("downstream_seg").alias("downstream")).unique().sort("segment_id", "downstream"))


def segment_norm_features(rows: pl.DataFrame, norm: pl.DataFrame, offsets=(0, 5, 10, 15, 25, 30)) -> pl.DataFrame:
    """fe_norm_p{k} for segments: the segment's normal level at the slot of t + k (known in advance)."""
    out = rows
    for k in offsets:
        tk = pl.col("t") + timedelta(minutes=k)
        out = (out.with_columns((tk.dt.hour().cast(pl.Int16) * 4 + tk.dt.minute().cast(pl.Int16) // 15).alias("_s"))
                  .join(norm.select("segment_id", pl.col("slot15").alias("_s"), pl.col("norm").cast(pl.Float32).alias(f"fe_norm_p{k}")),
                        on=["segment_id", "_s"], how="left", maintain_order="left").drop("_s"))
    return out
