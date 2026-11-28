"""13_leakage_checks.py - does any step use information it should not have? (26 Nov)

Checks, run on the train and validation days only. The test week is not read again: only the dates of the saved test
scores (work/preds/test_scores.parquet) are looked at. Nothing here is saved as a model or changes a frozen file.

A. The days stay apart
  A1 each split's rows lie on its own days
  A2 the forest was fitted on train-day rows only (each tree's bootstrap size = the subsampled train fit rows)
  A3 the lasso was fitted on train-day rows only (its stored scaling means = the means of the train fit rows)
  A4 frozen model files: hashes now vs results/freeze.json; every freeze before the test opening
     (the first line of results/TEST_OPENED.log starts with the time of the opening)
B. Every input is known at time t
  B1 NORM is the same on every day for a link and clock time (no day-specific information)
  B2 the normal level is the median of the TRAIN weekdays' bands only (recomputed from info_band)
  B3 HOP "10 min ago" values equal the "now" values at t - 10 (direction of the lag)
  B4 truncation test: HOP rebuilt from the rows up to a cut time equals the stored values (no later row used);
     a deliberately leaky version (value at t + 10) fails the same test, so the test can catch a leak
  B5 the label and the 1 km segment lags point the right way: y(t) = U(t + 15), segment f_d5(t) = f_d0(t - 5)
  B6 no single input gives the answer: PR-AUC of each input alone on the validation week
  B7 "band persistence says low at t + 10 and t + 15" against the answer
C. HIST (the B1 rate as an input) on the training rows leaves the row's own day out
  C1 how much that own-day shift reveals about the label on the fit rows
  C2 does it matter: forests on the two forward-chaining folds (train days only) with HIST as fitted (own day left
     out), HIST from past days only (no own-day information at all), and no HIST
D. Accuracy vs PR-AUC on the validation week: "always no slowdown" against the forest

Run (from modelling/, after 10_test.py; about 10 min):
    systemd-run --user --scope -q -p MemoryMax=14G nice -n 10 python 13_leakage_checks.py

AI disclosure: drafted with Claude (Anthropic) on 26 Nov 2026; log in AI_USE.md.
"""
from __future__ import annotations

import hashlib
import json
import pickle
from datetime import date, datetime, time, timedelta
from pathlib import Path

import numpy as np
import polars as pl
from sklearn.metrics import roc_auc_score

import features as F
import settings as S
from common import alerts_at_share, ap, log, md_table, write_md
from modeldata import (B1_M, Scaler, fit_forest, fold_frames, forest_score, lasso_matrix, load_rows, neg_subsample,
                       tree_matrix, with_hist)

R: list[list] = []          # summary rows: id, check, result, detail
OUT: dict = {}


def rec(cid: str, text: str, ok, detail: str) -> None:
    res = ok if isinstance(ok, str) else ("OK" if ok else "FAIL")
    R.append([cid, text, res, detail])
    log(f"{cid} {res}: {text} | {detail}")


def sha(p) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


HOP_PAIRS = ([(f"fe_{d}_r{k}_{m}0", f"fe_{d}_r{k}_{m}10") for d in ("dn", "up") for k in (1, 2, 3) for m in ("max", "low")]
             + [("fe_dn_q0", "fe_dn_q10")])
NORM_COLS = [f"fe_norm_p{k}" for k in F.NORM_OFFSETS]

# =========================================================================================== A1, A4 (no rows needed)
sp = (pl.scan_parquet(S.TRAIN).group_by("split")
        .agg(pl.col("date").min().alias("first"), pl.col("date").max().alias("last"),
             pl.col("date").n_unique().alias("days"), pl.len().alias("rows")).collect().sort("split"))
d = {r["split"]: r for r in sp.iter_rows(named=True)}
tdates = pl.read_parquet(S.PREDS / "test_scores.parquet", columns=["date"])["date"]
ok = (d["train"]["first"] >= S.TRAIN_DAYS[0] and d["train"]["last"] <= S.TRAIN_DAYS[1]
      and d["validate"]["first"] >= S.VAL_DAYS[0] and d["validate"]["last"] <= S.VAL_DAYS[1]
      and tdates.min() >= S.TEST_DAYS[0] and tdates.max() <= S.TEST_DAYS[1])
rec("A1", "each split's rows lie on its own days", ok,
    f"train {d['train']['first']} to {d['train']['last']} ({d['train']['days']} days); validate {d['validate']['first']} "
    f"to {d['validate']['last']} ({d['validate']['days']}); test scores {tdates.min()} to {tdates.max()} "
    f"({tdates.n_unique()} days); no day in two splits")

FRZ = json.loads(S.FREEZE.read_text())
frozen = datetime.fromisoformat(FRZ["frozen_at"])
opened = datetime.fromisoformat((S.RESULTS / "TEST_OPENED.log").read_text().split()[0])
# the model files named in the freeze record, looked up by file name where the models are now (as in 10_test.py)
model_bad = [f for f, h in FRZ["files_sha256"].items()
             if Path(f).parent.name == "models" and sha(S.MODELS / Path(f).name) != h]
sec_bad, sec_late = [], []
for name in ("freeze_secondary_base", "freeze_secondary_lasso", "freeze_secondary_rf", "freeze_segments"):
    a = json.loads((S.RESULTS / f"{name}.json").read_text())
    sec_bad += [f for f, h in a["models_sha256"].items() if sha(S.MODELS / f) != h]
    if datetime.fromisoformat(a["frozen_at"]) >= opened:
        sec_late.append(name)
rec("A4", "frozen model files unchanged since their freeze; every freeze before the test opening",
    not model_bad and not sec_bad and not sec_late and frozen < opened,
    f"main freeze {frozen:%d %b %H:%M}, test opened {opened:%d %b %H:%M}; main models changed: {model_bad or 'none'}; "
    f"secondary models changed: {sec_bad or 'none'}; secondary freezes after the opening: {sec_late or 'none'}")
# The freeze record also holds the hashes of the scripts as they were at the freeze. They were compared on 26 Nov,
# where the freeze was written. The scripts were then moved to this folder (paths and comments changed), so their
# hashes cannot be compared again: the finding of 26 Nov is kept as a fixed note.
rec("A4b", "code files changed after the main freeze (models unaffected; for the record)", "NOTE",
    "`08_secondary.py` (last changed 25 Nov 23:48, before the test opening); `10_test.py` (last changed 25 Nov 23:50, "
    "before the test opening)")

# =========================================================================================== B1-B5 (feature tables)
fe = pl.scan_parquet(S.WORK / "fe_trainval.parquet")
nu = (fe.select("LinkID", pl.col("t").dt.time().alias("tod"), *NORM_COLS)
        .group_by("LinkID", "tod").agg([pl.col(c).n_unique() for c in NORM_COLS])
        .select([pl.col(c).max() for c in NORM_COLS]).collect().row(0))
ndays = fe.select(pl.col("t").dt.date().n_unique()).collect().item()
rec("B1", "NORM inputs depend only on the link and the clock time (the same on every day)", max(nu) == 1,
    f"most distinct values of any NORM input for one link and clock time over the {ndays} days: {max(nu)}")

slot = (pl.col("t").dt.hour().cast(pl.Int16) * 4 + pl.col("t").dt.minute().cast(pl.Int16) // 15).alias("slot15")
nw = (pl.read_parquet(S.NORM).filter(pl.col("daytype") == "weekday")
        .select("LinkID", pl.col("slot15").cast(pl.Int16), "norm_band", "n_obs"))


def medians(splits: tuple) -> pl.DataFrame:
    return (pl.scan_parquet(S.FULL)
              .filter(pl.col("split").is_in(list(splits)) & (pl.col("daytype") == "weekday") & pl.col("info_band").is_not_null())
              .select("LinkID", slot, pl.col("info_band").cast(pl.Float64))
              .group_by("LinkID", "slot15").agg(pl.col("info_band").median().alias("m"), pl.len().alias("n")).collect())


cmp = nw.filter(pl.col("slot15").is_between(24, 87)).join(medians(("train",)), on=["LinkID", "slot15"], how="left")
bad_m = cmp.filter(((pl.col("m") - pl.col("norm_band")).abs() > 1e-9) | pl.col("m").is_null()).height
bad_n = cmp.filter(pl.col("n") != pl.col("n_obs")).height
alt = nw.filter(pl.col("slot15").is_between(24, 87)).join(medians(("train", "validate")), on=["LinkID", "slot15"], how="left")
alt_diff = alt.filter((pl.col("m") - pl.col("norm_band")).abs() > 1e-9).height
rec("B2", "the normal level is the median of the train weekdays' bands only", bad_m == 0 and bad_n == 0,
    f"{cmp.height:,} link x slot cells (06:00-21:59) recomputed: {bad_m} medians and {bad_n} counts differ; "
    f"with the validation days added, {alt_diff:,} cells ({alt_diff / alt.height:.0%}) would differ, so the check can "
    f"tell the two apart")
del cmp, alt

a = fe.select("LinkID", "t", *[c10 for _, c10 in HOP_PAIRS])
b = fe.select("LinkID", (pl.col("t") + timedelta(minutes=10)).alias("t"), *[pl.col(c0).alias(c0 + "_back") for c0, _ in HOP_PAIRS])
f_ = fe.select("LinkID", (pl.col("t") - timedelta(minutes=10)).alias("t"), *[pl.col(c0).alias(c0 + "_fwd") for c0, _ in HOP_PAIRS])
j = a.join(b, on=["LinkID", "t"], how="inner").join(f_, on=["LinkID", "t"], how="inner").collect()
bad_back = sum(j.filter((pl.col(c10) - pl.col(c0 + "_back")).abs() > 1e-6).height for c0, c10 in HOP_PAIRS)
diff_fwd = sum(j.filter((pl.col(c10) - pl.col(c0 + "_fwd")).abs() > 1e-6).height for c0, c10 in HOP_PAIRS)
rec("B3", "HOP '10 min ago' inputs equal the 'now' inputs at t - 10", bad_back == 0,
    f"{j.height:,} rows x {len(HOP_PAIRS)} inputs: {bad_back} differ from t - 10; {diff_fwd:,} would differ if the lag "
    f"pointed forward (t + 10)")
del a, b, f_, j

pairs = pl.read_parquet(S.WORK / "hop_pairs.parquet")
AUDIT_DAYS = [date(2026, 11, 4), date(2026, 11, 11), date(2026, 11, 13)]       # one train day, two validation days
CUTS = [time(7, 30), time(12, 0), time(17, 45)]
full = (pl.scan_parquet(S.FULL).filter(pl.col("in_population") & pl.col("date").is_in(AUDIT_DAYS))
          .select("LinkID", "t", "date", "f_d0", "f_d5", "f_d10").collect())
stored = fe.filter(pl.col("t").dt.date().is_in(AUDIT_DAYS)).collect()
hop_cols = None
bad_trunc, leak_caught, n_cmp = 0, 0, 0
for dd in AUDIT_DAYS:
    fd = full.filter(pl.col("date") == dd)
    hop_full = F.hop_day(F.dfill_series(fd), pairs)
    for cut_t in CUTS:
        cut = datetime.combine(dd, cut_t)
        ft = fd.filter(pl.col("t") <= cut)
        hop_t = F.hop_day(F.dfill_series(ft), pairs)
        feat = F.hop_features(ft.select("LinkID", "t"), hop_t)
        hop_cols = [c for c in feat.columns if c not in ("LinkID", "t")]
        st = (stored.filter((pl.col("t").dt.date() == dd) & (pl.col("t") <= cut))     # the same day only
                    .select("LinkID", "t", *[pl.col(c).alias(c + "_st") for c in hop_cols]))
        jj = feat.join(st, on=["LinkID", "t"], how="full", coalesce=True)
        n_cmp += jj.height * len(hop_cols)
        bad_trunc += sum(jj.filter(((pl.col(c) - pl.col(c + "_st")).abs() > 1e-6)
                                   | (pl.col(c).is_null() != pl.col(c + "_st").is_null())).height for c in hop_cols)
        # the leaky version: the value 10 minutes AFTER t
        lf = hop_full.select("LinkID", (pl.col("s") - timedelta(minutes=10)).alias("t"), pl.col("dn_r1_max").alias("lf"))
        lt = hop_t.select("LinkID", (pl.col("s") - timedelta(minutes=10)).alias("t"), pl.col("dn_r1_max").alias("lt"))
        lj = ft.select("LinkID", "t").join(lf, on=["LinkID", "t"], how="left").join(lt, on=["LinkID", "t"], how="left")
        leak_caught += lj.filter((pl.col("lf").is_null() != pl.col("lt").is_null())
                                 | ((pl.col("lf") - pl.col("lt")).abs() > 1e-6)).height
rec("B4", "truncation test: HOP rebuilt from the rows up to a cut time equals the stored inputs", bad_trunc == 0,
    f"{len(AUDIT_DAYS)} days (4 Nov train; 11, 13 Nov validation) x cuts {', '.join(c.strftime('%H:%M') for c in CUTS)}: "
    f"{n_cmp:,} values compared, {bad_trunc} differ. A deliberately leaky input (the value at t + 10) changes on "
    f"{leak_caught:,} rows under the same test, so a leak would have been caught")
del full, stored

lab = (pl.scan_parquet(S.FULL).filter(pl.col("date").is_in(AUDIT_DAYS)).select("LinkID", "t", "y", "U").collect())
lj = lab.select("LinkID", "t", "y").join(lab.select("LinkID", (pl.col("t") - timedelta(minutes=15)).alias("t"),
                                                    pl.col("U").alias("U15")), on=["LinkID", "t"], how="inner")
lj = lj.filter(pl.col("y").is_not_null() & pl.col("U15").is_not_null())
bad_lab = lj.filter(pl.col("y") != pl.col("U15")).height
sg = pl.read_parquet(S.WORK / "seg_trainval.parquet", columns=["segment_id", "t", "f_d0", "f_d5", "U", "y"])
sj = sg.select("segment_id", "t", "f_d5", "y").join(
    sg.select("segment_id", (pl.col("t") + timedelta(minutes=5)).alias("t"), pl.col("f_d0").alias("prev")),
    on=["segment_id", "t"], how="left").join(
    sg.select("segment_id", (pl.col("t") - timedelta(minutes=15)).alias("t"), pl.col("U").alias("U15")),
    on=["segment_id", "t"], how="left")
s_lag = sj.filter(pl.col("f_d5").is_not_null() & pl.col("prev").is_not_null())
s_lab = sj.filter(pl.col("y").is_not_null() & pl.col("U15").is_not_null())
bad_sl = s_lag.filter((pl.col("f_d5") - pl.col("prev")).abs() > 1e-9).height
bad_sy = s_lab.filter(pl.col("y") != pl.col("U15")).height
rec("B5", "the label looks 15 min ahead and the 1 km segment lags look back", bad_lab == 0 and bad_sl == 0 and bad_sy == 0,
    f"links (3 audit days): y(t) = U(t + 15) on {lj.height:,} rows, {bad_lab} differ; segments: f_d5(t) = f_d0(t - 5) "
    f"on {s_lag.height:,} rows ({bad_sl} differ), y(t) = U(t + 15) on {s_lab.height:,} rows ({bad_sy} differ)")
del lab, lj, sg, sj

# =========================================================================================== rows of the models
df = load_rows(h=S.HORIZON)
fit_all = df.filter((pl.col("split") == "train") & ~pl.col("heldout_road"))
val = df.filter(pl.col("split") == "validate")
del df

with open(S.MODELS / "rf.pkl", "rb") as fh:
    RFO = pickle.load(fh)
rf, cols = RFO["model"], RFO["cols"]
banned = [c for c in cols if c in ("y", "U", "date", "t", "split", "LinkID", "road", "heldout_road") or c.startswith(("y_", "info_"))]
y_fit = fit_all["y"].to_numpy()
idx = neg_subsample(y_fit, S.RF_NEG_KEEP, S.SEED)
roots = np.array([e.tree_.weighted_n_node_samples[0] for e in rf.estimators_])
frac1 = np.array([e.tree_.value[0][0][1] / e.tree_.value[0][0].sum() for e in rf.estimators_])
vm = val.filter(~pl.col("heldout_road"))["y"].to_numpy()
n_alt = len(idx) + int(vm.sum()) + round(S.RF_NEG_KEEP * (len(vm) - vm.sum()))
rec("A2", "the forest was fitted on train-day rows only (training roads)",
    bool(np.all(roots == len(idx))) and not banned and rf.n_features_in_ == len(cols),
    f"every one of the {len(roots)} trees drew {int(roots[0]):,} rows = the train fit rows after keeping 10% of the "
    f"y = False rows ({len(idx):,}); with the validation week added it would be about {n_alt:,}. Onset share in the "
    f"draws {frac1.mean():.4f} vs {y_fit[idx].mean():.4f} in the fit rows. Inputs: {len(cols)}, none of them a label, "
    f"date or link id")

with open(S.MODELS / "lasso.pkl", "rb") as fh:
    LO = pickle.load(fh)
fit_h = with_hist(fit_all, fit_all, lodo=True)
val_h = with_hist(val, fit_all, lodo=False)
X, _ = lasso_matrix(fit_h, LO["cols"])
mu = np.array([X[:, k].mean(dtype=np.float64) for k in range(X.shape[1])])
sum_fit = np.array([X[:, k].sum(dtype=np.float64) for k in range(X.shape[1])])
del X
Xv, _ = lasso_matrix(val_h.filter(~pl.col("heldout_road")), LO["cols"])
sum_val = np.array([Xv[:, k].sum(dtype=np.float64) for k in range(Xv.shape[1])])
mu_alt = (sum_fit + sum_val) / (len(y_fit) + len(Xv))
del Xv
dmu = float(np.max(np.abs(mu - LO["mu"]) / LO["sd"]))
dalt = float(np.max(np.abs(mu_alt - LO["mu"]) / LO["sd"]))
rec("A3", "the lasso was fitted on train-day rows only (training roads)", dmu < 1e-9 and LO["n_fit"] == len(y_fit),
    f"stored fit rows {LO['n_fit']:,} = {len(y_fit):,}; stored scaling means vs the train fit rows' means: largest "
    f"difference {dmu:.1e} SD; with the validation week added it would be {dalt:.3f} SD")

# ---- B6, B7 (validation week, training roads) ----
vmain = val_h.filter(~pl.col("heldout_road"))
Xm = tree_matrix(vmain, cols)
ym = vmain["y"].to_numpy()
single = sorted(((max(ap(ym, Xm[:, k]), ap(ym, -Xm[:, k])), c) for k, c in enumerate(cols)), reverse=True)
del Xm
rf_val = pl.read_parquet(S.PREDS / "val_rf.parquet").filter(~pl.col("heldout_road"))
ap_rf_val = ap(rf_val["y"].to_numpy(), rf_val["rf_raw"].to_numpy())
rec("B6", "no single input gives the answer (validation week, each input alone as a score)", single[0][0] < 0.5,
    f"best single inputs: " + ", ".join(f"`{c}` {v:.3f}" for v, c in single[:5])
    + f"; the forest {ap_rf_val:.3f}; base rate {ym.mean():.4f}")
OUT["single_input_pr_auc"] = [[c, v] for v, c in single]

lp = vmain["x_lowpers15"].to_numpy() == 1
rec("B7", "'band persistence says low at t + 10 and t + 15' is a forecast, not the answer", "NOTE",
    f"validation week, training roads: true on {lp.mean():.1%} of rows; the link really is unusually slow 15 min "
    f"later on {ym[lp].mean():.1%} of those (vs {ym[~lp].mean():.2%} otherwise); they hold {ym[lp].sum() / ym.sum():.1%} "
    f"of the onsets")
del vmain

# =========================================================================================== C. HIST
cellk = ["LinkID", "f_slot15"]
c1 = (fit_h.select(*cellk, "date", "y", "x_b1")
           .with_columns((pl.col("x_b1") - pl.col("x_b1").mean().over(cellk)).alias("centred"),
                         pl.col("y").sum().over(cellk).alias("cell_on"),
                         pl.col("y").sum().over([*cellk, "date"]).alias("day_on"))
           .filter(pl.col("cell_on") > 0))
yc = c1["y"].to_numpy()
auc_within = roc_auc_score(yc, -c1["centred"].to_numpy())
ap_within = ap(yc, -c1["centred"].to_numpy())
on_day = c1["day_on"].to_numpy() > 0
rec("C1", "HIST on the fit rows leaves the own day out, so within a link x slot it is LOWER on days with onsets", "NOTE",
    f"fit rows in cells with at least one onset ({c1.height:,} rows, base rate {yc.mean():.3f}): the within-cell "
    f"deviation of x_b1 ranks onsets with ROC-AUC {auc_within:.3f} (PR-AUC {ap_within:.3f}); rows on a day with an onset "
    f"in their cell have an onset rate of {yc[on_day].mean():.3f}. This is information about the row's own label, but "
    f"only usable by a model that can tell which link and slot a row is; validation and test rows never have it")
OUT["C1"] = {"rows": c1.height, "roc_auc_within": auc_within, "pr_auc_within": ap_within}
del c1, fit_h, val_h


def b1_past(rows: pl.DataFrame, fit: pl.DataFrame, m: float = B1_M) -> np.ndarray:
    """The B1 rate from fit days strictly BEFORE each row's day (ordered target statistic: no own-day information).
    NaN when there is no earlier day (the forest handles missing values)."""
    f = fit.filter(~pl.col("heldout_road"))
    cell = f.group_by("LinkID", "f_slot15", "date").agg(pl.col("y").sum().alias("on"), pl.len().alias("n"))
    sl = f.group_by("f_slot15", "date").agg(pl.col("y").sum().alias("son"), pl.len().alias("sn"))
    r = rows.select("LinkID", "f_slot15", "date").with_row_index("i")
    parts = []
    for dd in sorted(r["date"].unique().to_list()):
        pc = cell.filter(pl.col("date") < dd).group_by("LinkID", "f_slot15").agg(pl.col("on").sum(), pl.col("n").sum())
        ps = sl.filter(pl.col("date") < dd).group_by("f_slot15").agg(pl.col("son").sum(), pl.col("sn").sum())
        x = (r.filter(pl.col("date") == dd).join(pc, on=["LinkID", "f_slot15"], how="left")
              .join(ps, on="f_slot15", how="left")
              .with_columns(pl.col("on", "n").fill_null(0))
              .select("i", ((pl.col("on") + m * pl.col("son") / pl.col("sn")) / (pl.col("n") + m)).alias("x")))
        parts.append(x)
    return pl.concat(parts).sort("i")["x"].fill_null(float("nan")).to_numpy().astype(np.float32)


params = FRZ["rf"]["params"]
cv_cache = json.loads((S.TABLES / "06_rf_cv_cache.json").read_text())["results"]
cached = cv_cache[f"{float(params['max_features'])}|{int(params['min_samples_leaf'])}"]
cols_nohist = [c for c in cols if c != "x_b1"]
c2 = {"as fitted (own day left out)": [], "past days only (no own-day information)": [], "no HIST": []}
for k, (fit, chk) in enumerate(fold_frames(fit_all)):
    fa, ca = with_hist(fit, fit, lodo=True), with_hist(chk, fit, lodo=False)
    fb = fit.with_columns(pl.Series("x_b1", b1_past(fit, fit)))
    yk, yc_ = fit["y"].to_numpy(), chk["y"].to_numpy()
    for name, ffit, use_cols in (("as fitted (own day left out)", fa, cols), ("past days only (no own-day information)", fb, cols),
                                 ("no HIST", fa, cols_nohist)):
        m_ = fit_forest(tree_matrix(ffit, use_cols), yk, S.RF_TREES_TUNE, S.SEED + k, **params)
        c2[name].append(ap(yc_, forest_score(m_, tree_matrix(ca, use_cols))))
        del m_
        log(f"C2 fold {k + 1} {name}: {c2[name][-1]:.4f}")
    del fa, ca, fb
same = np.allclose(c2["as fitted (own day left out)"], cached, atol=1e-9)
rec("C2", "does the own-day trace in HIST change the fold scores? (forests on train days only)", "NOTE",
    "; ".join(f"{n}: folds {v[0]:.4f} / {v[1]:.4f}, mean {np.mean(v):.4f}" for n, v in c2.items())
    + f". 'As fitted' {'reproduces' if same else 'does NOT reproduce'} the tuning run in 06 ({cached[0]:.4f} / {cached[1]:.4f})")
OUT["C2"] = c2
del fit_all, val

# =========================================================================================== D. accuracy vs PR-AUC
yv = rf_val["y"].to_numpy().astype(bool)
sv = rf_val["rf_raw"].to_numpy()
tv = rf_val["t"].to_numpy()
base = yv.mean()
order = np.argsort(-sv, kind="mergesort")
tp = np.cumsum(yv[order])
k_ = np.arange(1, len(yv) + 1)
acc_all = (tp + (len(yv) - k_) - (yv.sum() - tp)) / len(yv)       # accuracy when the top k rows are called "slowdown"
best_k = int(np.argmax(acc_all))
a_, b_ = FRZ["calibration_platt_logit"]["RF"]
lg = np.log(np.clip(sv, 1e-7, 1 - 1e-7) / (1 - np.clip(sv, 1e-7, 1 - 1e-7)))     # as platt_apply in 07
pcal = 1 / (1 + np.exp(-(a_ + b_ * lg)))
drows = [["always 'no slowdown'", f"{1 - base:.2%}", "0", "-", "0%", f"{ap(yv, np.zeros(len(yv))):.4f}",
          f"{roc_auc_score(yv, np.zeros(len(yv))):.3f}"]]
for q in (0.005, 0.01, 0.02, 0.05):
    al = alerts_at_share(tv, sv, q)
    tpq = int((al & yv).sum())
    acc = 1 - ((al & ~yv).sum() + (~al & yv).sum()) / len(yv)
    drows.append([f"forest, top {q:.1%} of links per update", f"{acc:.2%}", f"{int(al.sum()):,}", f"{tpq / al.sum():.3f}",
                  f"{tpq / yv.sum():.1%}", f"{ap(yv, sv):.4f}", f"{roc_auc_score(yv, sv):.3f}"])
drows.append([f"forest, threshold with the best accuracy", f"{acc_all[best_k]:.2%}", f"{best_k + 1:,}",
              f"{tp[best_k] / (best_k + 1):.3f}", f"{tp[best_k] / yv.sum():.1%}", f"{ap(yv, sv):.4f}", f"{roc_auc_score(yv, sv):.3f}"])
OUT["D"] = {"base_rate": float(base), "always_no_accuracy": float(1 - base), "best_accuracy": float(acc_all[best_k]),
            "pr_auc_raw": ap(yv, sv), "pr_auc_calibrated": ap(yv, pcal)}
rec("D", "accuracy rewards 'always no'; PR-AUC does not, and it does not depend on a threshold", "NOTE",
    f"validation week, training roads (base rate {base:.4f}): 'always no' is {1 - base:.2%} accurate with PR-AUC "
    f"{ap(yv, np.zeros(len(yv))):.4f}; the forest's best possible accuracy is {acc_all[best_k]:.2%}; its PR-AUC is "
    f"{ap(yv, sv):.4f} raw and {ap(yv, pcal):.4f} after the frozen calibration map (a monotone map changes no ranking)")

# =========================================================================================== write
lines = ["# Leakage checks (26 Nov)", "",
         "Run on the train and validation days only; the test week was not read again (only the dates of the saved "
         "test scores). OK = passed, FAIL = failed, NOTE = a measurement to read, not a pass/fail check.", ""]
lines += md_table(R, ["#", "check", "result", "detail"])
lines += ["", "## D. Accuracy vs PR-AUC (validation week, training roads)", ""]
lines += md_table(drows, ["prediction", "accuracy", "rows called 'slowdown'", "precision", "onsets caught", "PR-AUC",
                          "ROC-AUC"])
lines += ["", "## B6. PR-AUC of each input alone (validation week, training roads; the better of +x and -x)", ""]
lines += md_table([[c, f"{v:.4f}"] for v, c in single[:15]], ["input", "PR-AUC alone"])
write_md("13_leakage_checks.md", lines)
(S.TABLES / "13_leakage_checks.json").write_text(json.dumps({"checks": R, **OUT}, indent=1, default=str))
