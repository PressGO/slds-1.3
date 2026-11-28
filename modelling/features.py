"""features.py - feature engineering, shared by the train/validate build (02) and the test build (10).

All engineered inputs are known at time t and use training-day information only:

NORM  (the link's own frozen normal level; rule 6 of docs/data_rules.md, train days only)
      fe_norm_p{k}  normal level at the slot of t + k min, k = 0, 5, 10, 15, 25, 30. The norm of a FUTURE slot is
                    fixed in advance, so it is known at t. With the band now (= fe_norm_p0 - f_d0) it gives the
                    drop the link would have at t + k if its band stayed the same ("band persistence").
HOP   (neighbours' speed bands beyond the next link; congestion spreads upstream from a queue downstream)
      for rings of path distance beyond the next link, (0, 500], (500, 1500], (1500, 3000] m, downstream and
      upstream: the largest drop and the share of links with a drop >= 2, now and 10 min ago; the distance to
      the nearest downstream link with a drop >= 2 (queue tail), now and 10 min ago, and how far it moved.
      The values are the reused-at-most-5-min drops (dfill) of the other links, exactly as f_dn_* / f_up_* use.
HIST  (the B1 rate as an input; target encoding, computed per fold in the model scripts, never here)

AI disclosure: drafted with Claude (Anthropic) on 25 Nov 2026; log in AI_USE.md.
"""
from __future__ import annotations

import heapq
import math
from datetime import timedelta

import numpy as np
import polars as pl

import settings as S

M_PER_DEG = 111_320.0
COS_LAT = math.cos(math.radians(1.35))
NORM_OFFSETS = (0, 5, 10, 15, 25, 30)
RINGS = S.HOP_RINGS


def link_geometry(links: pl.DataFrame) -> pl.DataFrame:
    """Length (m) of each expressway link on the flat grid of rule 13."""
    xs = links["StartLon"].to_numpy() * M_PER_DEG * COS_LAT
    ys = links["StartLat"].to_numpy() * M_PER_DEG
    xe = links["EndLon"].to_numpy() * M_PER_DEG * COS_LAT
    ye = links["EndLat"].to_numpy() * M_PER_DEG
    return links.select("LinkID").with_columns(pl.Series("length_m", np.hypot(xe - xs, ye - ys)))


def hop_pairs(links: pl.DataFrame, neigh: pl.DataFrame, max_m: float = RINGS[-1][1]) -> pl.DataFrame:
    """(LinkID, other, dir, dist) for every link reachable within max_m of path distance.

    dist = summed length of the links strictly between LinkID and other (the next link is at 0 m).
    Shortest path (Dijkstra) when the network branches; a link never pairs with itself.
    """
    length = dict(link_geometry(links).iter_rows())
    down: dict[str, list[str]] = {}
    up: dict[str, list[str]] = {}
    for a, b in neigh.select("LinkID", "downstream").iter_rows():
        down.setdefault(a, []).append(b)
        up.setdefault(b, []).append(a)
    out = []
    for direction, graph in (("dn", down), ("up", up)):
        for l in links["LinkID"].to_list():
            best: dict[str, float] = {}
            heap = [(0.0, b) for b in graph.get(l, [])]
            heapq.heapify(heap)
            while heap:
                d, b = heapq.heappop(heap)
                if b == l or b in best or d > max_m:
                    continue
                best[b] = d
                for c in graph.get(b, []):
                    if c not in best:
                        heapq.heappush(heap, (d + length[b], c))
            out += [(l, b, direction, d) for b, d in best.items()]
    return pl.DataFrame(out, schema={"LinkID": pl.Utf8, "other": pl.Utf8, "dir": pl.Utf8, "dist": pl.Float64},
                        orient="row")


def ring_of(dist: pl.Expr) -> pl.Expr:
    e = pl.lit(None, pl.Int8)
    for i, (lo, hi) in reversed(list(enumerate(RINGS))):
        e = pl.when((dist > lo) & (dist <= hi)).then(pl.lit(i + 1, pl.Int8)).otherwise(e)
    return e


def hop_static(pairs: pl.DataFrame, ids: list[str]) -> pl.DataFrame:
    """1 = the link has no link in that ring (its ring values are then 0)."""
    have = (pairs.with_columns(ring_of(pl.col("dist")).alias("ring")).filter(pl.col("ring").is_not_null())
                 .group_by("LinkID", "dir", "ring").len())
    out = pl.DataFrame({"LinkID": ids})
    for direction in ("dn", "up"):
        for r in range(1, len(RINGS) + 1):
            h = have.filter((pl.col("dir") == direction) & (pl.col("ring") == r)).select("LinkID", pl.lit(0, pl.Int8).alias("x"))
            out = out.join(h, on="LinkID", how="left").with_columns(
                pl.col("x").fill_null(1).cast(pl.Int8).alias(f"fe_{direction}_r{r}_none")).drop("x")
    return out


def dfill_series(full_day: pl.DataFrame) -> pl.DataFrame:
    """dfill(link, s) for s = 05:50 ... 21:55 of one day, from the full table (f_d0 = dfill(l, t))."""
    now = full_day.select("LinkID", pl.col("t").alias("s"), pl.col("f_d0").alias("v"))
    first = full_day.filter((pl.col("t").dt.hour() == S_HOUR_FROM) & (pl.col("t").dt.minute() == 0))
    early = [first.select("LinkID", (pl.col("t") - timedelta(minutes=k)).alias("s"), pl.col(f"f_d{k}").alias("v"))
             for k in (5, 10)]
    return pl.concat([now, *early])


S_HOUR_FROM = 6


def hop_day(series: pl.DataFrame, pairs: pl.DataFrame) -> pl.DataFrame:
    """Ring aggregates and queue distances at every s of one day: one row per (LinkID, s)."""
    p = pairs.with_columns(ring_of(pl.col("dist")).alias("ring"))
    j = p.join(series.rename({"LinkID": "other"}), on="other", how="inner")
    known = j.filter(pl.col("v").is_not_null())
    rings = (known.filter(pl.col("ring").is_not_null())
                  .group_by("LinkID", "s", "dir", "ring")
                  .agg(pl.col("v").max().alias("max"), (pl.col("v") >= S.THRESHOLD).mean().alias("low")))
    wide = []
    for direction in ("dn", "up"):
        for r in range(1, len(RINGS) + 1):
            wide.append(rings.filter((pl.col("dir") == direction) & (pl.col("ring") == r))
                             .select("LinkID", "s", pl.col("max").alias(f"{direction}_r{r}_max"),
                                     pl.col("low").alias(f"{direction}_r{r}_low")))
    q = (known.filter(pl.col("v") >= S.THRESHOLD).group_by("LinkID", "s", "dir").agg(pl.col("dist").min().alias("q")))
    keys = series.select("LinkID", "s").unique()
    out = keys
    for w in wide:
        out = out.join(w, on=["LinkID", "s"], how="left")
    for direction in ("dn", "up"):
        out = out.join(q.filter(pl.col("dir") == direction).select("LinkID", "s", pl.col("q").alias(f"{direction}_q")),
                       on=["LinkID", "s"], how="left")
    vals = [c for c in out.columns if c not in ("LinkID", "s")]
    return out.with_columns([pl.col(c).fill_null(S.QDIST_CAP if c.endswith("_q") else 0.0).cast(pl.Float32)
                             for c in vals])


def hop_features(rows: pl.DataFrame, hop: pl.DataFrame) -> pl.DataFrame:
    """Attach lag-0 and lag-10 ring values and the queue distances to rows (LinkID, t)."""
    vals = [c for c in hop.columns if c not in ("LinkID", "s")]
    out = rows.select("LinkID", "t")
    for lag in S.HOP_LAGS:
        h = hop.select("LinkID", (pl.col("s") + timedelta(minutes=lag)).alias("t"),
                       *[pl.col(c).alias(f"fe_{c}{lag}") for c in vals
                         if not c.endswith("_q") or c.startswith("dn") or lag == 0])
        out = out.join(h, on=["LinkID", "t"], how="left", maintain_order="left")
    out = out.with_columns((pl.col("fe_dn_q10") - pl.col("fe_dn_q0")).alias("fe_dn_qmove"))
    return out


def norm_features(rows: pl.DataFrame, norm_weekday: pl.DataFrame) -> pl.DataFrame:
    """fe_norm_p{k}: the weekday normal level at the slot of t + k min (known in advance)."""
    out = rows.select("LinkID", "t")
    nw = norm_weekday.select("LinkID", pl.col("slot15").cast(pl.Int16), pl.col("norm_band").cast(pl.Float32))
    for k in NORM_OFFSETS:
        tk = pl.col("t") + timedelta(minutes=k)
        out = (out.with_columns((tk.dt.hour().cast(pl.Int16) * 4 + tk.dt.minute().cast(pl.Int16) // 15).alias("slot15"))
                  .join(nw, on=["LinkID", "slot15"], how="left", maintain_order="left")
                  .rename({"norm_band": f"fe_norm_p{k}"}).drop("slot15"))
    return out


# ---------------------------------------------------------------------------------------- model matrices

BASE_ALL: list[str] = []          # filled by the model scripts from the data (53 f_ columns)
HOP_COLS: list[str] = []


def hop_columns(fe_cols: list[str]) -> list[str]:
    return [c for c in fe_cols if c.startswith(("fe_dn_", "fe_up_"))]


def norm_group(h: int = 15) -> list[str]:
    return ["x_band0", "fe_norm_p0", f"x_dnorm{h}", f"x_dpers{h}", f"x_dpers{h - 5}", f"x_lowpers{h}", "x_low0", "x_low5"]


def add_derived(df: pl.DataFrame, h: int = 15) -> pl.DataFrame:
    """Derived NORM inputs for horizon h, plus the threshold indicators."""
    band0 = pl.col("fe_norm_p0") - pl.col("f_d0")
    dp = lambda k: (pl.col(f"fe_norm_p{k}") - band0) if k > 0 else pl.col("f_d0")
    return df.with_columns(
        band0.alias("x_band0"),
        (pl.col(f"fe_norm_p{h}") - pl.col("fe_norm_p0")).alias(f"x_dnorm{h}"),
        dp(h).alias(f"x_dpers{h}"),
        dp(h - 5).alias(f"x_dpers{h - 5}"),
        ((dp(h) >= S.THRESHOLD) & (dp(h - 5) >= S.THRESHOLD)).cast(pl.Float32).alias(f"x_lowpers{h}"),
        (pl.col("f_d0") >= S.THRESHOLD).cast(pl.Float32).alias("x_low0"),
        (pl.col("f_d5") >= S.THRESHOLD).cast(pl.Float32).alias("x_low5"),
    )


def lasso_view(df: pl.DataFrame, cols: list[str]) -> tuple[pl.DataFrame, list[str]]:
    """For the lasso: f_slot15 -> 16 hour groups (06-21), rain -> log(1 + mm). Trees use the raw columns."""
    out_cols, exprs = [], []
    for c in cols:
        if c == "f_slot15":
            for hh in range(6, 22):
                n = f"x_hour{hh:02d}"
                exprs.append(((pl.col("f_slot15") // 4) == hh).cast(pl.Float32).alias(n))
                out_cols.append(n)
        elif c in ("f_rain15", "f_rain30"):
            exprs.append(pl.col(c).log1p().cast(pl.Float32).alias(f"x_log_{c[2:]}"))
            out_cols.append(f"x_log_{c[2:]}")
        else:
            out_cols.append(c)
    return df.with_columns(exprs), out_cols
