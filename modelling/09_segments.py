"""09_segments.py - 1 km segments (the proposal's secondary analysis): build (rules 26-32) on the train and validation
days, check, and score B1, B2, the lasso and the forest with the FROZEN settings. Writes work/features/seg*.parquet,
work/models/seg_*.pkl and results/freeze_segments.json (before any test-week data is opened).

Segments get the same model recipe as links, except the HOP group (segments are ~1 km long already; their
neighbours are the next segments) and the joining roads (rule 30: none).

AI disclosure: drafted with Claude (Anthropic) on 25 Nov 2026; log in AI_USE.md.
"""
from __future__ import annotations

import hashlib
import json
import math
import pickle
import random
import warnings
from datetime import date, datetime, timedelta

import numpy as np
import polars as pl
from lassofit import LassoLogit

import features as F
import segments as G
import settings as S
from common import ap, assert_closed, f4, log, md_table, prec_rec_at_share, write_md
from modeldata import Scaler, b1_encode, fit_forest, forest_score, lasso_matrix, tree_matrix, with_hist

FRZ = json.loads(S.FREEZE.read_text())
assert not (S.TEST_BUILD / "model" / "test.parquet").exists(), "segment models must be fitted before the test build"

links = pl.read_parquet(S.LINKS)
neigh = pl.read_parquet(S.NEIGH)
sl, segs, n_paths = G.paths_and_segments(links, neigh)
checks = []
checks.append(["every link on exactly one segment", sl["LinkID"].n_unique() == sl.height == links.height, f"{sl.height:,} links"])
checks.append(["paths = 87 and segments = 374 (the 18 Nov dry run)", (n_paths, segs.height) == (87, 374),
               f"{n_paths} paths, {segs.height} segments"])
checks.append(["every segment lies on one road", int(segs["n_roads"].max()) == 1, ""])
short = segs.filter(pl.col("length_m") < 500).height
checks.append(["segment length: median / 90th percentile / under 500 m", True,
               f"{segs['length_m'].median():.0f} m / {segs['length_m'].quantile(0.9):.0f} m / {short}"])
assert all(c[1] for c in checks), checks
cal = pl.read_csv(S.PROJ / "data_processed" / "calendar_2026.csv", try_parse_dates=True,
                  schema_overrides={"is_public_holiday": pl.Boolean})
holidays = set(cal.filter(pl.col("is_public_holiday"))["date"].to_list())
days = G.day_frame(S.TRAIN_DAYS[0], S.LAST_OPEN_DAY, holidays)
xw_ids = links["LinkID"].to_list()
panel = (pl.scan_parquet(S.PANEL).filter(pl.col("LinkID").is_in(xw_ids) & (pl.col("t").dt.date() <= S.LAST_OPEN_DAY))
           .select("LinkID", "t", "band").collect())
assert_closed(panel.with_columns(pl.col("t").dt.date().alias("date")))
sband = G.segment_band(panel, sl, segs)
norm = G.segment_norm(sband, days)
rain = G.read_rain(S.LAST_OPEN_DAY)
elig = G.eligible_stations(rain, days)
stations = pl.read_csv(S.STATIONS, schema_overrides={"station_id": pl.Utf8}).filter(pl.col("station_id").is_in(elig))
station = G.nearest(segs, stations)
pairs = G.segment_pairs(sl, neigh)
checks.append(["rain: eligible stations = 82 (build_info.json of data version 4)", len(elig) == 82, f"{len(elig)}"])
rows = G.segment_rows(sband, norm, segs, days, rain, station, pairs)
rows = rows.filter(pl.col("split").is_in(["train", "validate"]))
log(f"segment rows: {rows.height:,} (use {rows['use'].sum():,})")

# ---- independent spot checks (plain Python) ----
lens = dict(sl.select("LinkID", "length_m").iter_rows())
seg_of = {}
for l, s in sl.select("LinkID", "segment_id").iter_rows():
    seg_of.setdefault(s, []).append(l)
seglen = dict(segs.select("segment_id", "length_m").iter_rows())
smp = rows.filter(pl.col("use")).sample(300, seed=5)
pb = {(l, t): b for l, t, b in panel.join(smp.select(pl.col("t")).unique(), on="t").iter_rows()}
bad = 0
for sid, t, ib in smp.select("segment_id", "t", "info_band").iter_rows():
    got = [(lens[l], pb[(l, t)]) for l in seg_of[sid] if (l, t) in pb and pb[(l, t)] is not None]
    cover = sum(w for w, _ in got)
    want = sum(w * b for w, b in got) / cover if cover >= 0.8 * seglen[sid] else None
    bad += want is None or abs(want - ib) > 1e-9
checks.append(["segment band = length-weighted mean of captured link bands (300 random use rows)", bad == 0, f"{bad} differ"])
lag = rows.select("segment_id", (pl.col("t") + timedelta(minutes=5)).alias("t"), pl.col("f_d0").alias("prev"))
j = rows.filter(pl.col("use")).join(lag, on=["segment_id", "t"], how="inner")
bad = j.filter((pl.col("f_d5") - pl.col("prev")).abs() > 1e-9).height
checks.append(["f_d5 equals f_d0 of the same segment 5 min earlier (use rows with a row 5 min earlier)", bad == 0, f"{bad} differ"])
fut = rows.select("segment_id", (pl.col("t") - timedelta(minutes=15)).alias("t"), pl.col("U").alias("U15"))
j = rows.filter(pl.col("use")).join(fut, on=["segment_id", "t"], how="inner")
bad = j.filter(pl.col("y") != pl.col("U15")).height
checks.append(["y equals U of the same segment 15 min later", bad == 0, f"{bad} differ"])
nchk = norm.sample(500, seed=2)
tw = days.filter((pl.col("split") == "train") & (pl.col("daytype") == "weekday"))["date"].to_list()
sb_t = sband.filter(pl.col("t").dt.date().is_in(tw)).with_columns(
    (pl.col("t").dt.hour().cast(pl.Int16) * 4 + pl.col("t").dt.minute().cast(pl.Int16) // 15).alias("slot15"))
cells = sb_t.join(nchk.select("segment_id", "slot15"), on=["segment_id", "slot15"]).group_by("segment_id", "slot15").agg(pl.col("sband"))
med = {(s, k): float(np.median(v)) for s, k, v in cells.iter_rows()}
bad = sum(abs(med[(s, k)] - n) > 1e-9 for s, k, n in nchk.select("segment_id", "slot15", "norm").iter_rows())
checks.append(["segment normal level = numpy median of its train-weekday bands (500 cells)", bad == 0, f"{bad} differ"])
assert all(c[1] for c in checks), [c for c in checks if not c[1]]

segs.write_parquet(S.WORK / "segments.parquet")
sl.write_parquet(S.WORK / "segment_links.parquet")
norm.write_parquet(S.WORK / "segment_norm.parquet")
station.write_parquet(S.WORK / "segment_station.parquet")
pairs.write_parquet(S.WORK / "segment_pairs.parquet")
rows.write_parquet(S.WORK / "seg_trainval.parquet")

# ---------------------------------------------------------------- models with the frozen settings
d = (rows.filter(pl.col("use") & ~pl.col("U")).rename({"segment_id": "LinkID"}))
d = F.add_derived(G.segment_norm_features(d.rename({"LinkID": "segment_id"}), norm).rename({"segment_id": "LinkID"}), 15)
d = d.sort("LinkID", "t")
base_cols = G.segment_inputs()
groups = {"BASE": base_cols, "NORM": F.norm_group(15), "HIST": ["x_b1"], "HOP": []}
fit = d.filter((pl.col("split") == "train") & ~pl.col("heldout_road"))
val = d.filter(pl.col("split") == "validate")
fit_h, val_h = with_hist(fit, fit, lodo=True), with_hist(val, fit, lodo=False)

# B1: m by forward-chaining on the segment rows (the same procedure as for links)
from importlib import import_module
b03 = import_module("03_baselines")
best_m, cv_m = b03.choose_m(fit.with_columns(pl.col("f_slot15")))
s_b1 = b1_encode(val, fit, m=best_m)
res = {"B1": s_b1, "B2": val["f_d0"].to_numpy().astype(float)}
saved = {}


def keep(name: str, obj) -> None:
    p = S.MODELS / f"seg_{name}.pkl"
    with open(p, "wb") as fh:
        pickle.dump(obj, fh)
    saved[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()


keep("b1", {"m": best_m, "fit_rows": fit.select("LinkID", "f_slot15", "date", "heldout_road", "y")})
for fam, key in (("Lasso", "LR"), ("RF", "RF")):
    names = [n for n in FRZ["features"][key] if n != "HOP"]
    cols = [c for n in names for c in groups[n]]
    fr, vr = (fit_h, val_h) if "HIST" in names else (fit, val)
    if fam == "Lasso":
        X, xn = lasso_matrix(fr, cols)
        sc = Scaler(X)
        m = LassoLogit(FRZ["lasso"]["lambda_per_row"]).fit(sc(X), fr["y"].to_numpy())   # the frozen penalty per row
        Xv, _ = lasso_matrix(vr, cols)
        res[fam] = m.predict_proba(sc(Xv))[:, 1]
        keep("lasso", {"model": m, "mu": sc.mu, "sd": sc.sd, "cols": cols, "groups": names})
    else:
        rf = fit_forest(tree_matrix(fr, cols), fr["y"].to_numpy(), S.RF_TREES_FINAL, S.SEED, **FRZ["rf"]["params"])
        res[fam] = forest_score(rf, tree_matrix(vr, cols))
        keep("rf", {"model": rf, "cols": cols, "groups": names})
    log(f"segments {fam}: {' + '.join(names)} ({len(cols)} inputs)")

out_rows, js = [], {}
for name, held in (("training roads (main)", False), ("AYE + CTE (transfer)", True)):
    k = (val["heldout_road"] == held).to_numpy()
    v = val.filter(pl.Series(k))
    y, t = v["y"].to_numpy(), v["t"].to_numpy()
    for mname, s in res.items():
        a = ap(y, s[k])
        p1 = prec_rec_at_share(t, y, s[k], 0.01)[0]
        js[f"{mname}|{name}"] = {"pr_auc": a, "prec_1pct": p1, "rows": int(len(y)), "base_rate": float(y.mean())}
        out_rows.append([name, mname, f"{len(y):,}", f"{int(y.sum()):,}", f4(y.mean()), f4(a), f"{p1:.3f}"])
(S.TABLES / "09_segments.json").write_text(json.dumps({"m": best_m, "scores": js}, indent=2))
(S.RESULTS / "freeze_segments.json").write_text(json.dumps({
    "frozen_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    "statement": "Segment tables and models built from the train and validation days with the settings of freeze.json, "
                 "before any test-week data was opened.",
    "b1_m": best_m, "models_sha256": saved,
    "tables_sha256": {p: hashlib.sha256((S.WORK / p).read_bytes()).hexdigest()
                      for p in ("segments.parquet", "segment_links.parquet", "segment_norm.parquet", "segment_station.parquet",
                                "segment_pairs.parquet")}}, indent=2))

lines = ["# 1 km segments (docs/data_rules.md rules 26-32): build, checks and validation scores", "",
         f"{segs.height} segments on {n_paths} paths; rows: every segment x 5-min update, 06:00-22:00, weekdays of the "
         f"train and validation days ({rows.height:,} rows, {rows['use'].sum():,} usable).", "", "## Checks", ""]
lines += md_table([[a, "OK" if b else "FAIL", c] for a, b, c in checks], ["check", "result", "detail"])
lines += ["", f"B1 m chosen by forward-chaining on the segment rows: **{best_m}** "
              f"(fold means: {', '.join(f'{k}: {np.mean(v):.4f}' for k, v in cv_m.items())}).", "",
          "## Validation week (onset rows; models fitted on the train days with the frozen link settings)", ""]
lines += md_table(out_rows, ["rows", "model", "scored rows", "onsets", "base rate", "PR-AUC", "precision at 1%"])
write_md("09_segments.md", lines)
