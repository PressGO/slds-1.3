"""10_test.py - the ONE test run on Mon 16 - Fri 20 Nov 2026, with everything frozen (results/freeze*.json).

Gate: the frozen model files must match their hashes, and either the plan-freeze git tag exists or
OPEN_TEST_WEEK=yes is set (set it only after the freeze). Reads the test-week build of build_test_data.sh
(work/data_build/). Nothing is refitted; every result is kept, good or bad.

AI disclosure: drafted with Claude (Anthropic) on 25 Nov 2026; log in AI_USE.md.
"""
from __future__ import annotations

import hashlib
import json
import os
import pickle
import subprocess
from datetime import date, datetime, timedelta
from importlib import import_module
from pathlib import Path

import numpy as np
import polars as pl
from sklearn.metrics import precision_recall_curve

import features as F
import segments as G
import settings as S
from common import (DayBootstrap, alerts_at_share, ap, base_inputs, brier, ci, f4, log, md_table, prec_rec_at_share,
                    reliability, write_md)
from modeldata import b1_encode, forest_score, lasso_matrix, rows_horizon, standardize, tree_matrix
from plotstyle import INK2, MODEL_COLOR, MODEL_LABEL, MUTED, SLOT, plt, save

b03 = import_module("03_baselines")
# DRY_RUN=1: the same pipeline on the VALIDATION week dressed as a test build (work/data_dryrun/), to test this script.
# It must reproduce the validation scores of 03-07 exactly. It never touches the test week.
DRY = os.environ.get("DRY_RUN") == "1"
PRE = "dry_" if DRY else ""
DAYS = [date(2026, 11, d) for d in (range(10, 14) if DRY else range(16, 21))]
WANT_SPLIT = "validate" if DRY else "test"


def sha(p) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ================================================================ gate
FRZ = json.loads(S.FREEZE.read_text())
# The model files named in the freeze record are looked up by file name where the models are now (S.MODELS).
# The record gives each path as it was at the freeze, in another folder; the record itself is never edited.
frozen_models = {f: h for f, h in FRZ["files_sha256"].items() if Path(f).parent.name == "models"}
assert frozen_models, "the freeze record names no model file"
bad = [f for f, h in frozen_models.items() if sha(S.MODELS / Path(f).name) != h]
assert not bad, f"frozen model files changed after the freeze: {bad}"
addenda = {}
for name in ("freeze_secondary_base", "freeze_secondary_lasso", "freeze_secondary_rf", "freeze_segments"):
    p = S.RESULTS / f"{name}.json"
    if p.exists():
        a = json.loads(p.read_text())
        bad = [f for f, h in a["models_sha256"].items() if sha(S.MODELS / f) != h]
        assert not bad, f"{name}: models changed after their freeze: {bad}"
        addenda[name] = a["frozen_at"]
tag = subprocess.run(["git", "-C", str(S.ROOT), "tag", "-l", "plan-freeze"], capture_output=True, text=True).stdout.strip()
if not DRY and not tag and os.environ.get("OPEN_TEST_WEEK") != "yes":
    raise SystemExit("The plan-freeze tag does not exist. Set OPEN_TEST_WEEK=yes only after the freeze.")
TB = (S.DRY_BUILD / "model") if DRY else (S.TEST_BUILD / "model")
CLEAN_PANEL = S.PANEL if DRY else (S.TEST_BUILD / "clean" / "panel.parquet")
if DRY and not (TB / "test.parquet").exists():
    (TB / "extra").mkdir(parents=True, exist_ok=True)
    pl.scan_parquet(S.TRAIN).filter(pl.col("split") == "validate").with_columns(pl.lit("test").alias("split")) \
      .sink_parquet(TB / "test.parquet")
    pl.scan_parquet(S.FULL).filter(pl.col("split") == "validate").with_columns(pl.lit("test").alias("split")) \
      .sink_parquet(TB / "extra" / "test_full.parquet")
    import shutil
    shutil.copy2(S.TRAIN, TB / "train.parquet")
    for f in ("norm.parquet", "links.parquet", "neighbours.parquet", "connectors.parquet", "incidents.parquet", "build_info.json"):
        shutil.copy2(S.EXTRA / f, TB / "extra" / f)
assert (TB / "test.parquet").exists(), "run build_test_data.sh first"
log(f"gate passed: freeze {FRZ['frozen_at']}; addenda {addenda}; tag '{tag or 'none'}'")

# ================================================================ the test-week build: the same data as published?
info = json.loads((TB / "extra" / "build_info.json").read_text())
assert info["data_version"] == "4" and (DRY or info["built_as_of"] == "2026-11-21 06:00"), (info["data_version"], info["built_as_of"])
build_checks = []
a = pl.read_parquet(S.TRAIN).sort("LinkID", "t")
b = pl.read_parquet(TB / "train.parquet").sort("LinkID", "t")
same = a.equals(b)
build_checks.append(["train.parquet (train + validate rows) identical to the published file", same, f"{a.height:,} vs {b.height:,} rows"])
if not same and a.height == b.height and a.columns == b.columns:
    diff = [c for c in a.columns if not a[c].equals(b[c])]
    build_checks[-1][2] += f"; columns that differ: {diff}"
del a, b
for f in ("norm.parquet", "links.parquet", "neighbours.parquet", "connectors.parquet"):
    x, y_ = pl.read_parquet(S.EXTRA / f), pl.read_parquet(TB / "extra" / f)
    key = [c for c in ("LinkID", "daytype", "slot15", "downstream", "joins") if c in x.columns]
    cols = [c for c in x.columns if c not in ("first_seen", "last_seen", "n_snapshots", "n_attribute_versions",
                                              "presence_snapshots")]
    eq = x.select(cols).sort(key).equals(y_.select(cols).sort(key))
    build_checks.append([f"extra/{f} identical (frozen from the train days; registry counters ignored)", eq, ""])
assert all(c[1] for c in build_checks if "norm" in c[0]), "the normal level changed: stop"
test = pl.read_parquet(TB / "test.parquet")
tdays = sorted(test["date"].unique().to_list())
assert tdays == DAYS, tdays
build_checks.append([f"test.parquet holds {DAYS[0]:%a %d} - {DAYS[-1]:%a %d %b} only", True, f"{test.height:,} rows"])
log(f"test rows {test.height:,}; build checks: {[c[1] for c in build_checks]}")

# ================================================================ engineered inputs for the test week (as in 02)
links = pl.read_parquet(S.LINKS).sort("LinkID")
ids = links["LinkID"].to_list()
norm_w = pl.read_parquet(S.NORM).filter(pl.col("daytype") == "weekday")
pairs = pl.read_parquet(S.WORK / "hop_pairs.parquet")
full_t = (pl.scan_parquet(TB / "extra" / "test_full.parquet").filter(pl.col("in_population"))
            .select("LinkID", "t", "date", "use", "U", "f_d0", "f_d5", "f_d10", "f_dn_d0", "f_up_d0", "heldout_road").collect())
parts = []
for d in tdays:
    fd = full_t.filter(pl.col("date") == d)
    parts.append(F.hop_features(fd.select("LinkID", "t"), F.hop_day(F.dfill_series(fd), pairs)))
fe = (full_t.select("LinkID", "t").join(F.norm_features(full_t.select("LinkID", "t"), norm_w), on=["LinkID", "t"],
                                         how="left", maintain_order="left")
            .join(pl.concat(parts), on=["LinkID", "t"], how="left", maintain_order="left")
            .join(F.hop_static(pairs, ids), on="LinkID", how="left", maintain_order="left").sort("LinkID", "t"))
assert fe.height == len(tdays) * len(ids) * 192
ser = pl.concat([F.dfill_series(full_t.filter(pl.col("date") == d)) for d in tdays])
u = full_t.filter(pl.col("use"))
for direction, col in (("dn", "f_dn_d0"), ("up", "f_up_d0")):
    nxt = (pairs.filter((pl.col("dist") == 0) & (pl.col("dir") == direction)).join(ser.rename({"LinkID": "other"}), on="other")
                .group_by("LinkID", "s").agg(pl.col("v").max().alias("mx")))
    cmp = u.select("LinkID", "t", col).join(nxt.rename({"s": "t"}), on=["LinkID", "t"], how="left").with_columns(pl.col("mx").fill_null(0.0))
    nbad = cmp.filter((pl.col(col) - pl.col("mx")).abs() > 1e-6).height
    build_checks.append([f"test week: next-link maximum from our series == the build's {col}", nbad == 0, f"{nbad} differ"])
    assert nbad == 0
fe.write_parquet(S.WORK / f"{PRE}fe_test.parquet")


def test_rows(h: int = 15, onset_only: bool = True) -> pl.DataFrame:
    return rows_horizon(h, full_path=TB / "extra" / "test_full.parquet", fe_path=S.WORK / f"{PRE}fe_test.parquet",
                        splits=("test",), closed=False, onset_only=onset_only)


def hist_fit_rows(h: int) -> pl.DataFrame:
    """The train rows the HIST encoding counts (label y_h): train days, weekdays, normal now, inputs known."""
    lab = "y" if h == S.HORIZON else f"y_h{h}"
    core = base_inputs(with_conn=False)
    return (pl.scan_parquet(S.FULL)
              .filter(pl.col("in_population") & (pl.col("split") == "train") & (pl.col("U") == False)
                      & pl.col(lab).is_not_null() & pl.all_horizontal([pl.col(c).is_not_null() for c in core]))
              .select("LinkID", "f_slot15", "date", "heldout_road", pl.col(lab).alias("y")).collect())


main = test_rows(15)
assert main.height == test.filter(~pl.col("U")).height, (main.height, test.filter(~pl.col("U")).height)
fit15 = hist_fit_rows(15)
assert fit15.height == pl.scan_parquet(S.TRAIN).filter((pl.col("split") == "train") & ~pl.col("U")).select(pl.len()).collect().item()


def load(name: str):
    with open(S.MODELS / name, "rb") as fh:
        return pickle.load(fh)


LASSO, RF = load("lasso.pkl"), load("rf.pkl")
CELL, SLOTR = pl.read_parquet(S.MODELS / "b1_cell.parquet"), pl.read_parquet(S.MODELS / "b1_slot.parquet")


def score_lasso(obj, df: pl.DataFrame, fit_rows: pl.DataFrame) -> np.ndarray:
    if "x_b1" in obj["cols"]:
        df = df.with_columns(pl.Series("x_b1", b1_encode(df, fit_rows)))
    X, _ = lasso_matrix(df, obj["cols"])
    return obj["model"].predict_proba(standardize(X, obj["mu"], obj["sd"]))[:, 1]


def score_rf(obj, df: pl.DataFrame, fit_rows: pl.DataFrame) -> np.ndarray:
    if "x_b1" in obj["cols"]:
        df = df.with_columns(pl.Series("x_b1", b1_encode(df, fit_rows)))
    return forest_score(obj["model"], tree_matrix(df, obj["cols"]))


def main_scores(df: pl.DataFrame) -> dict[str, np.ndarray]:
    return {"B1": b03.score_b1(df, CELL, SLOTR, FRZ["B1"]["m"]), "B2": df["f_d0"].to_numpy().astype(float),
            "B2p": np.minimum(df["x_dpers10"].to_numpy(), df["x_dpers15"].to_numpy()).astype(float),
            "Lasso": score_lasso(LASSO, df, fit15), "RF": score_rf(RF, df, fit15)}


def logit(p):
    p = np.clip(np.asarray(p, float), 1e-7, 1 - 1e-7)
    return np.log(p / (1 - p))


def calibrated(name: str, p: np.ndarray) -> np.ndarray:
    a_, b_ = FRZ["calibration_platt_logit"][name]
    return 1 / (1 + np.exp(-(a_ + b_ * logit(p))))


sc = main_scores(main)
NAMES = ["B1", "B2", "B2p", "Lasso", "RF"]
if DRY:   # the test pipeline must give exactly the validation scores saved by 03, 05 and 06
    ref = (pl.read_parquet(S.PREDS / "val_baselines.parquet").select("LinkID", "t", "b1", "b2")
             .join(pl.read_parquet(S.PREDS / "val_lasso.parquet").select("LinkID", "t", "lasso"), on=["LinkID", "t"])
             .join(pl.read_parquet(S.PREDS / "val_rf.parquet").select("LinkID", "t", "rf_raw"), on=["LinkID", "t"]))
    cmp = main.select("LinkID", "t").with_columns([pl.Series(n, sc[n]) for n in NAMES]).join(ref, on=["LinkID", "t"])
    assert cmp.height == main.height, (cmp.height, main.height)
    for a_, b_ in (("B1", "b1"), ("B2", "b2"), ("Lasso", "lasso"), ("RF", "rf_raw")):
        gap = float((cmp[a_] - cmp[b_]).abs().max())
        build_checks.append([f"dry run: {a_} scores == the saved validation scores", gap < 1e-9, f"largest gap {gap:.1e}"])
        assert gap < 1e-9, (a_, gap)
    log("dry run: all four scores reproduce the saved validation scores exactly")
main.select("LinkID", "t", "date", "road", "heldout_road", "y", "f_slot15", "f_rain30", "f_d0").with_columns(
    [pl.Series(n, sc[n]) for n in NAMES]).write_parquet(S.PREDS / f"{PRE}test_scores.parquet")
log("test scores written")

# ================================================================ main score and transfer, with day-block bootstrap
lines = [("# DRY RUN on the validation week (tests 10_test.py; must match 03-07)" if DRY else
          "# THE TEST WEEK: Mon 16 - Fri 20 Nov 2026 (one run, frozen settings; data version 4)"), "",
         f"Frozen at {FRZ['frozen_at']} (results/freeze.json); secondary freezes: "
         + ", ".join(f"{k} {v}" for k, v in addenda.items()) + f". Plan-freeze tag: {tag or 'none (opened with OPEN_TEST_WEEK=yes)'}.",
         f"Build of the test week: `build_data.py --now '2026-11-21 06:00' --out-root work/data_build` "
         f"(git {info['git_commit']}, {sum(1 for c in info['checks'] if c['ok'])} of {len(info['checks'])} build checks OK).", "",
         "## Build checks", ""]
lines += md_table([[a_, "OK" if b_ else "DIFFERS", c_] for a_, b_, c_ in build_checks], ["check", "result", "detail"])
results = {}
day_idx = {d: i for i, d in enumerate(tdays)}


def evaluate(d: pl.DataFrame, s: dict[str, np.ndarray], label: str, boot: bool = True) -> list[list]:
    y = d["y"].to_numpy()
    di = d["date"].replace_strict(day_idx).to_numpy()
    bs = DayBootstrap(di, len(tdays)) if boot else None
    reps = {n: bs.replicate_aps(s[n], y) for n in s} if boot else {}
    rows = []
    for n in s:
        a_ = ap(y, s[n])
        r = {"pr_auc": a_, "base_rate": float(y.mean()), "rows": int(len(y)), "onsets": int(y.sum())}
        if boot:
            r["ci"] = ci(reps[n])
            for ref in ("B1", "B2"):
                if n != ref and ref in s:
                    r[f"minus_{ref}"] = a_ - ap(y, s[ref])
                    r[f"minus_{ref}_ci"] = ci(reps[n] - reps[ref])
            if n == "RF" and "Lasso" in s:
                r["minus_Lasso"] = a_ - ap(y, s["Lasso"])
                r["minus_Lasso_ci"] = ci(reps["RF"] - reps["Lasso"])
        results[f"{label}|{n}"] = r
        rows.append([MODEL_LABEL.get(n, n), f4(a_), "{:.4f} to {:.4f}".format(*r["ci"]) if boot else "",
                     "" if "minus_B2" not in r else "{:+.4f} ({:+.4f} to {:+.4f})".format(r["minus_B2"], *r["minus_B2_ci"]),
                     "" if "minus_B1" not in r else "{:+.4f} ({:+.4f} to {:+.4f})".format(r["minus_B1"], *r["minus_B1_ci"])])
    return rows


mk = ~main["heldout_road"].to_numpy()
mrows = main.filter(pl.Series(mk))
trows = main.filter(pl.Series(~mk))
s_main = {n: sc[n][mk] for n in NAMES}
s_tr = {n: sc[n][~mk] for n in NAMES}
y_m, y_t = mrows["y"].to_numpy(), trows["y"].to_numpy()
lines += ["", "## Primary result: PR-AUC on onset rows, training roads (1,909 links)", "",
          f"{len(y_m):,} rows, {int(y_m.sum()):,} onsets, base rate **{y_m.mean():.4f}** (the PR-AUC of a score that only "
          f"guesses). 95% intervals: day-block bootstrap over the 5 test days, {S.BOOT_REPS} draws, paired for differences.", ""]
lines += md_table(evaluate(mrows, s_main, "main"), ["model", "PR-AUC", "95% interval", "minus B2 (paired 95%)", "minus B1 (paired 95%)"])
r = results["main|RF"]
lines += ["", f"M2 minus M1: {r['minus_Lasso']:+.4f} (paired 95% {r['minus_Lasso_ci'][0]:+.4f} to {r['minus_Lasso_ci'][1]:+.4f}).", "",
          "## Transfer: AYE + CTE (689 links, never used to fit, tune or calibrate)", "",
          f"{len(y_t):,} rows, {int(y_t.sum()):,} onsets, base rate **{y_t.mean():.4f}**.", ""]
lines += md_table(evaluate(trows, s_tr, "transfer"), ["model", "PR-AUC", "95% interval", "minus B2 (paired 95%)", "minus B1 (paired 95%)"])
by_road = []
for road_ in sorted(trows["road"].unique().to_list()):
    k = (trows["road"] == road_).to_numpy()
    by_road.append([road_.title(), f"{int(k.sum()):,}", f4(y_t[k].mean())] + [f4(ap(y_t[k], s_tr[n][k])) for n in NAMES])
lines += ["", "By road:", ""] + md_table(by_road, ["road", "rows", "base rate", *[MODEL_LABEL[n] for n in NAMES]])

# ================================================================ alerts: precision / recall at shares; event level
share = FRZ["operating_share"]
shares = sorted(set(list(S.SHARES) + [share]))
pr_rows = []
for n in NAMES:
    vals = [prec_rec_at_share(mrows["t"].to_numpy(), y_m, s_main[n], q) for q in shares]
    results[f"main|{n}"]["at_share"] = {str(q): v[:2] for q, v in zip(shares, vals)}
    pr_rows.append([MODEL_LABEL[n]] + [f"{p:.3f} / {r_:.3f}" for p, r_, _ in vals])
lines += ["", f"## Precision / recall among the top share of links at each update (operating share {100 * share:g}%, set on validation)", ""]
lines += md_table(pr_rows, ["model", *[f"{100 * q:g}%" + (" (operating)" if q == share else "") for q in shares]])
fu = (pl.scan_parquet(TB / "extra" / "test_full.parquet").filter(pl.col("in_population") & ~pl.col("heldout_road"))
        .select("LinkID", "t", "U").collect())
prev = fu.select("LinkID", (pl.col("t") + timedelta(minutes=5)).alias("t"), pl.col("U").alias("U_prev"))
ep = fu.join(prev, on=["LinkID", "t"], how="left").filter(pl.col("U") & (pl.col("U_prev") == False)).select("LinkID", pl.col("t").alias("s"))
ev_rows = []
for n in NAMES:
    al = mrows.filter(pl.Series(alerts_at_share(mrows["t"].to_numpy(), s_main[n], share))).select("LinkID", "t", "y")
    hit = pl.concat([al.select("LinkID", (pl.col("t") + timedelta(minutes=k)).alias("s")) for k in (10, 15)]).unique()
    warned = ep.join(hit, on=["LinkID", "s"], how="semi").height / ep.height
    fa = al.filter(~pl.col("y")).height / (len(tdays) * 16)
    results[f"main|{n}"]["event"] = {"episodes": ep.height, "warned": warned, "false_alarms_per_hour": fa}
    ev_rows.append([MODEL_LABEL[n], f"{ep.height:,}", f"{warned:.1%}", f"{fa:,.0f}"])
lines += ["", f"## Event level at the operating share ({100 * share:g}%), training roads", "",
          "Episode start s: U(s) = 1 after U(s - 5) = 0. Warned = alerted at s - 15 or s - 10. False alarm = alert with y = 0.", ""]
lines += md_table(ev_rows, ["model", "episodes", "warned 10-15 min ahead", "false alarms per hour (1,909 links)"])

# ================================================================ calibration (frozen Platt maps)
cal_rows = []
for n in ("B1", "Lasso", "RF"):
    p = calibrated(n, s_main[n])
    results[f"main|{n}"]["brier"] = brier(y_m, p)
    cal_rows.append([MODEL_LABEL[n], f"{p.mean():.4f}", f"{y_m.mean():.4f}", f"{brier(y_m, p):.5f}",
                     f"{brier(y_m, np.full_like(p, y_m.mean())):.5f}"])
lines += ["", "## Calibration on the test week (maps frozen on validation)", ""]
lines += md_table(cal_rows, ["model", "mean predicted", "observed", "Brier", "Brier of the true base rate (hindsight)"])

# ================================================================ by day, subgroups, all rows
by_day = []
for d in tdays:
    k = (mrows["date"] == d).to_numpy()
    by_day.append([f"{d:%a %d %b}", f"{int(k.sum()):,}", f4(y_m[k].mean())] + [f4(ap(y_m[k], s_main[n][k])) for n in NAMES])
lines += ["", "## By day (training roads, PR-AUC)", ""] + md_table(by_day, ["day", "rows", "base rate", *[MODEL_LABEL[n] for n in NAMES]])
sub = []
peak = mrows["f_slot15"].is_in(sorted(S.PEAK_SLOTS)).to_numpy()
wet = (mrows["f_rain30"] > 0).to_numpy()
for lab_, k in (("peak (07:00-09:59, 17:00-19:59)", peak), ("off-peak", ~peak), ("rain in the last 30 min", wet), ("dry", ~wet)):
    sub.append([lab_, f"{int(k.sum()):,}", f4(y_m[k].mean())] + [f4(ap(y_m[k], s_main[n][k])) for n in NAMES])
for road_ in sorted(mrows["road"].unique().to_list()):
    k = (mrows["road"] == road_).to_numpy()
    if y_m[k].sum() >= 20:
        sub.append([road_.title(), f"{int(k.sum()):,}", f4(y_m[k].mean())] + [f4(ap(y_m[k], s_main[n][k])) for n in NAMES])
lines += ["", "## Subgroups (training roads; PR-AUC with each group's own base rate)", ""]
lines += md_table(sub, ["group", "rows", "base rate", *[MODEL_LABEL[n] for n in NAMES]])
allr = test_rows(15, onset_only=False)
sa = main_scores(allr)
ka = ~allr["heldout_road"].to_numpy()
ya = allr["y"].to_numpy()[ka]
lines += ["", "## PR-AUC on all rows (secondary metric: also rows already unusual now), training roads", ""]
lines += md_table([[MODEL_LABEL[n], f4(ap(ya, sa[n][ka]))] for n in NAMES], ["model", f"PR-AUC (base rate {ya.mean():.4f})"])
del allr, sa

# ================================================================ secondary analyses (frozen models)
sec_lines = ["", "## Secondary analyses (fixed in advance; frozen models)", ""]
hz = []
for h in (5, 10, 15, 30):
    d = main if h == 15 else test_rows(h)
    k = ~d["heldout_road"].to_numpy()
    y = d["y"].to_numpy()[k]
    if h == 15:
        s = {n: sc[n][k] for n in ("B1", "B2", "Lasso", "RF")}
    else:
        fr = hist_fit_rows(h)
        b1h = load(f"sec_base_b1_h{h}.pkl")
        s = {"B1": b03.score_b1(d, b1h["cell"], b1h["slot"], b1h["m"])[k], "B2": d["f_d0"].to_numpy()[k].astype(float)}
        if (S.MODELS / f"sec_lasso_h{h}.pkl").exists():
            s["Lasso"] = score_lasso(load(f"sec_lasso_h{h}.pkl"), d, fr)[k]
        if (S.MODELS / f"sec_rf_h{h}.pkl").exists():
            s["RF"] = score_rf(load(f"sec_rf_h{h}.pkl"), d, fr)[k]
    results[f"horizon{h}"] = {n: ap(y, v) for n, v in s.items()} | {"base_rate": float(y.mean())}
    hz.append([f"{h} min" + (" (main)" if h == 15 else ""), f"{len(y):,}", f4(y.mean())]
              + [f4(results[f"horizon{h}"].get(n, float("nan"))) for n in ("B1", "B2", "Lasso", "RF")])
sec_lines += ["### Horizon (training roads, PR-AUC)", ""] + md_table(hz, ["horizon", "rows", "base rate", "B1", "B2", "M1 lasso", "M2 forest"])
abl = []
for key, lab_ in (("no_conn", "without joining roads (f_conn_*)"), ("no_neighbours", "without neighbour inputs (f_up/f_dn and HOP)"),
                  ("no_conn_no_neighbours", "without both"), ("no_hist", "without HIST (the B1 rate as an input)"),
                  ("base53_trainnorm", "the 53 build inputs, normal level with the own day"),
                  ("base53_lodonorm", "the 53 build inputs, normal level without the own day (LODO)")):
    row = [lab_]
    for fam, f_ in (("lasso", score_lasso), ("rf", score_rf)):
        p = S.MODELS / f"sec_{fam}_{key}.pkl"
        if p.exists():
            v = f_(load(p.name), main, fit15)
            results[f"ablation|{key}|{fam}"] = {"main": ap(y_m, v[mk]), "transfer": ap(y_t, v[~mk])}
            row += [f4(ap(y_m, v[mk])), f4(ap(y_t, v[~mk]))]
        else:
            row += ["not run", "not run"]
    abl.append(row)
abl.insert(0, ["all chosen inputs (M1 / M2)", f4(results["main|Lasso"]["pr_auc"]), f4(results["transfer|Lasso"]["pr_auc"]),
               f4(results["main|RF"]["pr_auc"]), f4(results["transfer|RF"]["pr_auc"])])
sec_lines += ["", "### Inputs left out, and the leave-own-day-out normal level (PR-AUC)", ""]
sec_lines += md_table(abl, ["model inputs", "lasso: training roads", "lasso: AYE + CTE", "forest: training roads",
                            "forest: AYE + CTE"])

# ---- 1 km segments on the test week
if (S.RESULTS / "freeze_segments.json").exists():
    segs = pl.read_parquet(S.WORK / "segments.parquet")
    sl = pl.read_parquet(S.WORK / "segment_links.parquet")
    snorm = pl.read_parquet(S.WORK / "segment_norm.parquet")
    station = pl.read_parquet(S.WORK / "segment_station.parquet")
    spairs = pl.read_parquet(S.WORK / "segment_pairs.parquet")
    cal = pl.read_csv(S.PROJ / "data_processed" / "calendar_2026.csv", try_parse_dates=True,
                      schema_overrides={"is_public_holiday": pl.Boolean})
    hol = set(cal.filter(pl.col("is_public_holiday"))["date"].to_list())
    sdays = G.day_frame(DAYS[0], DAYS[-1], hol)
    pan = (pl.scan_parquet(CLEAN_PANEL)
             .filter(pl.col("LinkID").is_in(ids) & pl.col("t").dt.date().is_between(DAYS[0], DAYS[-1]))
             .select("LinkID", "t", "band").collect())
    srows = G.segment_rows(G.segment_band(pan, sl, segs), snorm, segs, sdays, G.read_rain(DAYS[-1]), station, spairs)
    sd = srows.filter(pl.col("use") & ~pl.col("U") & (pl.col("split") == WANT_SPLIT))
    sd = F.add_derived(G.segment_norm_features(sd, snorm).rename({"segment_id": "LinkID"}), 15).sort("LinkID", "t")
    b1s = load("seg_b1.pkl")
    s = {"B1": b1_encode(sd, b1s["fit_rows"], m=b1s["m"]), "B2": sd["f_d0"].to_numpy().astype(float)}
    s["Lasso"] = score_lasso(load("seg_lasso.pkl"), sd, b1s["fit_rows"])
    s["RF"] = score_rf(load("seg_rf.pkl"), sd, b1s["fit_rows"])
    seg_rows = []
    for lab_, held in (("training roads", False), ("AYE + CTE", True)):
        k = (sd["heldout_road"] == held).to_numpy()
        y = sd["y"].to_numpy()[k]
        results[f"segments|{lab_}"] = {n: ap(y, v[k]) for n, v in s.items()} | {"base_rate": float(y.mean()), "rows": int(len(y))}
        seg_rows.append([lab_, f"{len(y):,}", f"{int(y.sum()):,}", f4(y.mean())] + [f4(ap(y, s[n][k])) for n in ("B1", "B2", "Lasso", "RF")])
    sec_lines += ["", "### 1 km segments (374 segments; PR-AUC on segment onset rows)", ""]
    sec_lines += md_table(seg_rows, ["roads", "rows", "onsets", "base rate", "B1", "B2", "M1 lasso", "M2 forest"])
lines += sec_lines
write_md(f"{PRE}10_test.md", lines)
(S.TABLES / f"{PRE}10_test.json").write_text(json.dumps(results, indent=2, default=str))

# ================================================================ figures
fig, axs = plt.subplots(1, 2, figsize=(12, 4.4))
for n in NAMES:
    pr, rc, _ = precision_recall_curve(y_m, s_main[n])
    axs[0].plot(rc, pr, color=MODEL_COLOR[n], linewidth=1.8, label=f"{MODEL_LABEL[n]} ({results[f'main|{n}']['pr_auc']:.3f})")
axs[0].axhline(y_m.mean(), color=MUTED, linewidth=1)
axs[0].text(0.99, y_m.mean(), f"base rate {y_m.mean():.3f}", ha="right", va="bottom", fontsize=8, color=INK2)
axs[0].set_xlabel("recall")
axs[0].set_ylabel("precision")
axs[0].set_title("Test week, training roads: precision-recall (PR-AUC)")
axs[0].legend(fontsize=8)
for i, (lab_, key) in enumerate((("training roads", "main"), ("AYE + CTE (transfer)", "transfer"))):
    for j, n in enumerate(NAMES):
        r = results[f"{key}|{n}"]
        x = j + (i - 0.5) * 0.3
        axs[1].plot([x, x], r["ci"], color=MODEL_COLOR[n], linewidth=2, alpha=1 if i == 0 else 0.55)
        axs[1].plot([x], [r["pr_auc"]], marker="o" if i == 0 else "s", color=MODEL_COLOR[n], markersize=6,
                    markeredgecolor="#fcfcfb", markeredgewidth=1.5)
    axs[1].axhline(results[f"{key}|B2"]["base_rate"], color=MUTED, linewidth=1, linestyle="-" if i == 0 else ":")
axs[1].set_xticks(range(len(NAMES)))
axs[1].set_xticklabels([MODEL_LABEL[n].replace(" ", "\n", 1) for n in NAMES], fontsize=8)
axs[1].set_ylabel("PR-AUC with 95% day-bootstrap interval")
axs[1].set_title("Training roads (circles) vs AYE + CTE transfer (squares)")
axs[1].grid(axis="x", visible=False)
save(fig, f"{PRE}test_main.png")
fig, ax = plt.subplots(figsize=(8, 4))
for n in NAMES:
    ax.plot(range(len(tdays)), [ap(y_m[(mrows["date"] == d).to_numpy()], s_main[n][(mrows["date"] == d).to_numpy()]) for d in tdays],
            color=MODEL_COLOR[n], marker="o", markersize=5, label=MODEL_LABEL[n])
ax.set_xticks(range(len(tdays)))
ax.set_xticklabels([f"{d:%a %d %b}" for d in tdays])
ax.set_ylabel("PR-AUC (training roads)")
ax.set_title("Test week by day")
ax.legend(fontsize=8, ncol=2)
save(fig, f"{PRE}test_by_day.png")
fig, ax = plt.subplots(figsize=(5.6, 5))
mx = 0
for n in ("B1", "Lasso", "RF"):
    rr = reliability(y_m, calibrated(n, s_main[n]), bins=15)
    ax.plot(rr["mean_pred"], rr["observed"], color=MODEL_COLOR[n], marker="o", markersize=4, label=MODEL_LABEL[n])
    mx = max(mx, rr["mean_pred"].max(), rr["observed"].max())
ax.plot([0, mx], [0, mx], color=MUTED, linewidth=1)
ax.set_xlabel("predicted chance (calibration frozen on validation)")
ax.set_ylabel("observed onset rate")
ax.set_title("Reliability, test week (15 quantile bins)")
ax.legend(fontsize=8)
save(fig, f"{PRE}test_reliability.png")
log("test run complete")
