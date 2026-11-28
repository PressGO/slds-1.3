"""02_features.py - engineered inputs (NORM and HOP groups, see features.py) for every weekday row of the train
and validation days, with independent checks. Writes fe_trainval.parquet and hop_pairs.parquet to
work/features/.

AI disclosure: drafted with Claude (Anthropic) on 25 Nov 2026; log in AI_USE.md.
"""
from __future__ import annotations

import random
from collections import deque
from datetime import timedelta

import numpy as np
import polars as pl

import features as F
import settings as S
from common import assert_closed, log, md_table, write_md

links = pl.read_parquet(S.LINKS).sort("LinkID")
neigh = pl.read_parquet(S.NEIGH)
norm_w = pl.read_parquet(S.NORM).filter(pl.col("daytype") == "weekday")
ids = links["LinkID"].to_list()

# ---- 1. pairs within 3 km along the network ----
pairs = F.hop_pairs(links, neigh)
pairs.write_parquet(S.WORK / "hop_pairs.parquet")
static = F.hop_static(pairs, ids)
ring_n = (pairs.with_columns(F.ring_of(pl.col("dist")).alias("ring"))
               .group_by("LinkID", "dir", "ring").len()
               .group_by("dir", "ring").agg(pl.col("len").median().alias("median_links"),
                                            pl.len().alias("links_with_ring")).sort("dir", "ring"))
log(f"hop pairs: {pairs.height:,}; next links (0 m): {pairs.filter(pl.col('dist') == 0).height:,} "
    f"(neighbour pairs in the data: {neigh.height:,} each way)")
assert pairs.filter((pl.col("dist") == 0) & (pl.col("dir") == "dn")).height == neigh.height

# ---- 2. dfill of every link at every time of the weekday train / validate days ----
full = (pl.scan_parquet(S.FULL).filter(pl.col("in_population"))
          .select("LinkID", "t", "date", "split", "use", "U", "f_d0", "f_d5", "f_d10", "f_dn_d0", "f_up_d0")
          .collect())
assert_closed(full)
days = sorted(full["date"].unique().to_list())
log(f"full table weekday rows: {full.height:,} on {len(days)} days")
assert full.height == len(days) * len(ids) * 192

parts = []
for d in days:
    fd = full.filter(pl.col("date") == d)
    hop = F.hop_day(F.dfill_series(fd), pairs)
    parts.append(F.hop_features(fd.select("LinkID", "t"), hop))
hopf = pl.concat(parts)
log(f"HOP features: {hopf.height:,} rows x {len(hopf.columns) - 2} columns")

normf = F.norm_features(full.select("LinkID", "t"), norm_w)
fe = (full.select("LinkID", "t").join(normf, on=["LinkID", "t"], how="left", maintain_order="left")
          .join(hopf, on=["LinkID", "t"], how="left", maintain_order="left")
          .join(static, on="LinkID", how="left", maintain_order="left")
          .sort("LinkID", "t"))
fe_cols = [c for c in fe.columns if c.startswith("fe_")]
assert fe.height == full.height and fe.select(pl.struct("LinkID", "t").is_duplicated().any()).item() is False
nulls = {c: n for c, n in zip(fe_cols, fe.select(pl.col(fe_cols).null_count()).row(0)) if n}
assert not nulls, f"engineered inputs with nulls: {nulls}"

# ---- 3. checks ----
chk = []
# (a) the band now is a whole band 1-8 on every usable row
u = full.join(fe.select("LinkID", "t", "fe_norm_p0"), on=["LinkID", "t"]).filter(pl.col("use"))
band = (u["fe_norm_p0"] - u["f_d0"]).to_numpy()
ok = bool(np.all((band >= 1) & (band <= 8) & (band == np.round(band))))
chk.append(["band now = fe_norm_p0 - f_d0 is a whole band 1-8 on every usable row", ok, f"{u.height:,} rows"])
assert ok
# (b) the next-link maximum from our dfill series equals the build's f_dn_d0 / f_up_d0 on usable rows
ser = pl.concat([F.dfill_series(full.filter(pl.col("date") == d)) for d in days])
for direction, col in (("dn", "f_dn_d0"), ("up", "f_up_d0")):
    nxt = (pairs.filter((pl.col("dist") == 0) & (pl.col("dir") == direction))
                .join(ser.rename({"LinkID": "other"}), on="other")
                .group_by("LinkID", "s").agg(pl.col("v").max().alias("mx")))
    cmp = (u.select("LinkID", "t", col).join(nxt.rename({"s": "t"}), on=["LinkID", "t"], how="left")
            .with_columns(pl.col("mx").fill_null(0.0)))
    bad = cmp.filter((pl.col(col) - pl.col("mx")).abs() > 1e-6).height
    chk.append([f"next-link maximum from our dfill series == the build's {col} (usable rows)", bad == 0, f"{bad} differ"])
    assert bad == 0, (direction, bad)
# (c) an independent recomputation of the HOP values for 400 random rows (plain Python, no polars joins)
length = dict(F.link_geometry(links).iter_rows())
down, up = {}, {}
for a, b in neigh.select("LinkID", "downstream").iter_rows():
    down.setdefault(a, []).append(b)
    up.setdefault(b, []).append(a)
sample = fe.select("LinkID", "t", *fe_cols).sample(400, seed=11)
need_s = pl.concat([sample.select((pl.col("t") - timedelta(minutes=lag)).alias("s")) for lag in S.HOP_LAGS]).unique()
vmap = {(l, s): v for l, s, v in ser.join(need_s, on="s").iter_rows()}


def reach(l, graph):
    """Shortest path metres by repeated relaxation (Bellman-Ford style, not Dijkstra)."""
    dist = {b: 0.0 for b in graph.get(l, []) if b != l}
    changed = True
    while changed:
        changed = False
        for b, d in list(dist.items()):
            for c in graph.get(b, []):
                nd = d + length[b]
                if c != l and nd <= 3000.0 and nd < dist.get(c, 1e18):
                    dist[c] = nd
                    changed = True
    return dist


rng = random.Random(7)
fe_d = {(r[0], r[1]): r for r in sample.iter_rows()}
cols_i = {c: i + 2 for i, c in enumerate(fe_cols)}
bad = 0
for (l, t), r in fe_d.items():
    for direction, graph in (("dn", down), ("up", up)):
        dist = reach(l, graph)
        for lag in S.HOP_LAGS:
            s = t - timedelta(minutes=lag)
            for k, (lo, hi) in enumerate(S.HOP_RINGS, start=1):
                vals = [vmap.get((b, s)) for b, d in dist.items() if lo < d <= hi]
                vals = [v for v in vals if v is not None]
                mx = max(vals) if vals else 0.0
                lw = (sum(v >= 2 for v in vals) / len(vals)) if vals else 0.0
                bad += abs(r[cols_i[f"fe_{direction}_r{k}_max{lag}"]] - mx) > 1e-6
                bad += abs(r[cols_i[f"fe_{direction}_r{k}_low{lag}"]] - lw) > 1e-6
            if direction == "dn" or lag == 0:
                qs = [d for b, d in dist.items() if (vmap.get((b, s)) is not None and vmap[(b, s)] >= 2)]
                q = min(qs) if qs else S.QDIST_CAP
                bad += abs(r[cols_i[f"fe_{direction}_q{lag}"]] - q) > 1e-3
chk.append(["HOP values recomputed independently for 400 random rows (Bellman-Ford paths, dict lookups)",
            bad == 0, f"{bad} values differ"])
assert bad == 0, bad
# (d) the normal level of a future slot: 300 random rows against norm.parquet directly
nd = {(l, s): v for l, s, v in norm_w.select("LinkID", "slot15", "norm_band").iter_rows()}
bad = 0
for l, t, *vals in fe.select("LinkID", "t", *[f"fe_norm_p{k}" for k in F.NORM_OFFSETS]).sample(300, seed=3).iter_rows():
    for k, v in zip(F.NORM_OFFSETS, vals):
        tk = t + timedelta(minutes=k)
        bad += abs(nd[(l, tk.hour * 4 + tk.minute // 15)] - v) > 1e-6
chk.append(["fe_norm_p{k} == norm.parquet at the slot of t + k (300 random rows x 6)", bad == 0, f"{bad} differ"])
assert bad == 0

fe.write_parquet(S.WORK / "fe_trainval.parquet")
log(f"written work/features/fe_trainval.parquet: {fe.height:,} rows, {len(fe_cols)} engineered columns")

lines = ["# Feature engineering: build and checks", "",
         f"{len(fe_cols)} engineered columns for {fe.height:,} weekday rows (20 days x 2,598 links x 192 updates).", "",
         "## Links in each ring (path distance beyond the next link)", ""]
lines += md_table([[r[0], f"({S.HOP_RINGS[r[1] - 1][0]:.0f}, {S.HOP_RINGS[r[1] - 1][1]:.0f}] m" if r[1] else "next link (0 m)",
                    r[2], f"{r[3]:,}"] for r in ring_n.iter_rows()], ["direction", "ring", "median links", "links with ring"])
lines += ["", "## Checks", ""] + md_table([[a, "OK" if b else "FAIL", c] for a, b, c in chk], ["check", "result", "detail"])
lines += ["", "## Columns", "", ", ".join(f"`{c}`" for c in fe_cols)]
write_md("02_features.md", lines)
