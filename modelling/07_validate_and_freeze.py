"""07_validate_and_freeze.py - the validation week chooses the final model, calibrates, sets the alert share; then
everything is frozen (results/freeze.json, with file hashes) BEFORE the test week is opened.

Validation: Tue 10 - Fri 13 Nov (Mon 9 Nov is a public holiday). Main score: training roads; AYE + CTE separately.

AI disclosure: drafted with Claude (Anthropic) on 25 Nov 2026; log in AI_USE.md.
"""
from __future__ import annotations

import hashlib
import json
import math
import pickle
import subprocess
from datetime import datetime, timedelta

import numpy as np
import polars as pl
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_recall_curve

import settings as S
from common import (DayBootstrap, alerts_at_share, ap, assert_closed, brier, ci, f3, f4, log, md_table,
                    prec_rec_at_share, reliability, write_md)
from plotstyle import INK2, MODEL_COLOR, MODEL_LABEL, MUTED, plt, save

# ---------------------------------------------------------------- scores on the validation week
b = pl.read_parquet(S.PREDS / "val_baselines.parquet")
la = pl.read_parquet(S.PREDS / "val_lasso.parquet").select("LinkID", "t", "y", "lasso", "lr_plain")
rf = pl.read_parquet(S.PREDS / "val_rf.parquet").select("LinkID", "t", "y", "rf_raw")
v = (b.join(la, on=["LinkID", "t"], how="left", suffix="_la").join(rf, on=["LinkID", "t"], how="left", suffix="_rf")
      .sort("LinkID", "t"))
assert v.height == b.height and (v["y"] == v["y_la"]).all() and (v["y"] == v["y_rf"]).all()
assert_closed(v)
fe = (pl.scan_parquet(S.WORK / "fe_trainval.parquet").select("LinkID", "t", "fe_norm_p0", "fe_norm_p10", "fe_norm_p15")
        .join(v.lazy().select("LinkID", "t"), on=["LinkID", "t"], how="semi").collect())
v = v.join(fe, on=["LinkID", "t"], how="left", maintain_order="left").with_columns(
    pl.min_horizontal(pl.col("fe_norm_p10") - pl.col("fe_norm_p0") + pl.col("b2"),
                      pl.col("fe_norm_p15") - pl.col("fe_norm_p0") + pl.col("b2")).alias("b2p"))
MODELS = {"B1": "b1", "B2": "b2", "B2p": "b2p", "Lasso": "lasso", "RF": "rf_raw"}
PROB = ("B1", "Lasso", "RF")                    # scores that are chances (B2, B2p are drops in bands)
days = sorted(v["date"].unique().to_list())
v = v.with_columns(pl.col("date").replace_strict({d: i for i, d in enumerate(days)}).alias("di"))
main = v.filter(~pl.col("heldout_road"))
trans = v.filter(pl.col("heldout_road"))


def logit(p):
    p = np.clip(np.asarray(p, float), 1e-7, 1 - 1e-7)
    return np.log(p / (1 - p))


def platt_fit(p, y):
    m = LogisticRegression(C=np.inf, solver="lbfgs").fit(logit(p).reshape(-1, 1), y)
    return float(m.intercept_[0]), float(m.coef_[0, 0])


def platt_apply(p, ab):
    a, b_ = ab
    return 1 / (1 + np.exp(-(a + b_ * logit(p))))


# ---- calibration maps on the validation week (training roads); honest check by leave-one-day-out cross-fitting ----
calib, cal_rows = {}, []
for name in PROB:
    p, y, di = main[MODELS[name]].to_numpy(), main["y"].to_numpy(), main["di"].to_numpy()
    calib[name] = platt_fit(p, y)
    cross = np.empty_like(p, dtype=float)
    for d in range(len(days)):
        k = di == d
        cross[k] = platt_apply(p[k], platt_fit(p[~k], y[~k]))
    main = main.with_columns(pl.Series(f"{name}_cal", cross))
    cal_rows.append([MODEL_LABEL[name], f"{p.mean():.4f}", f"{cross.mean():.4f}", f"{y.mean():.4f}",
                     f"{brier(y, p):.5f}", f"{brier(y, cross):.5f}", f"{brier(y, np.full_like(p, y.mean())):.5f}",
                     f"a = {calib[name][0]:+.3f}, b = {calib[name][1]:.3f}"])

# ---------------------------------------------------------------- PR-AUC, precision at shares, per day
res_rows, share_tab = [], {}
for name, col in MODELS.items():
    for label_, d in (("training roads (main)", main), ("AYE + CTE (transfer)", trans)):
        y, s, t = d["y"].to_numpy(), d[col].to_numpy(), d["t"].to_numpy()
        pr = [prec_rec_at_share(t, y, s, q) for q in S.SHARE_GRID]
        share_tab[(name, label_)] = pr
        res_rows.append([MODEL_LABEL[name], label_, f4(y.mean()), f4(ap(y, s)),
                         *[f"{p:.3f} / {r:.3f}" for (p, r, _) in [pr[S.SHARE_GRID.index(q)] for q in S.SHARES]]])
ap_main = {n: ap(main["y"].to_numpy(), main[c].to_numpy()) for n, c in MODELS.items()}
final = max(("Lasso", "RF"), key=lambda n: ap_main[n])
f1 = {q: (2 * p * r / (p + r) if p + r else 0.0) for q, (p, r, _) in zip(S.SHARE_GRID, share_tab[(final, "training roads (main)")])}
share = min(S.SHARE_GRID, key=lambda q: (-round(f1[q], 4), q))
log(f"final model {final} (validation PR-AUC {ap_main[final]:.4f}); operating share {share:.2%} (F1 {f1[share]:.3f})")

per_day = []
for d_i, d in enumerate(days):
    k = main.filter(pl.col("di") == d_i)
    per_day.append([f"{d:%a %d %b}", f"{k.height:,}", f4(k["y"].mean())]
                   + [f4(ap(k["y"].to_numpy(), k[c].to_numpy())) for c in MODELS.values()])

# ---------------------------------------------------------------- day-block bootstrap (4 days: code test only)
bs = DayBootstrap(main["di"].to_numpy(), len(days))
boots = {n: bs.replicate_aps(main[c].to_numpy(), main["y"].to_numpy()) for n, c in MODELS.items()}
boot_rows = [[MODEL_LABEL[n], f4(ap_main[n]), "{:.4f} to {:.4f}".format(*ci(boots[n])),
              "" if n in ("B1", "B2") else "{:+.4f} ({:+.4f} to {:+.4f})".format(
                  ap_main[n] - ap_main["B2"], *ci(boots[n] - boots["B2"]))] for n in MODELS]

# ---------------------------------------------------------------- event level (warned >= 10 min ahead; false alarms per hour)
full_u = (pl.scan_parquet(S.FULL).filter(pl.col("in_population") & (pl.col("split") == "validate"))
            .select("LinkID", "t", "date", "U", "heldout_road").collect())
assert_closed(full_u)


def episodes(u: pl.DataFrame) -> pl.DataFrame:
    """Onsets: U(s) = True with U(s - 5) known False. One row per episode start (LinkID, s)."""
    prev = u.select("LinkID", (pl.col("t") + timedelta(minutes=5)).alias("t"), pl.col("U").alias("U_prev"))
    return (u.join(prev, on=["LinkID", "t"], how="left").filter(pl.col("U") & (pl.col("U_prev") == False))
             .select("LinkID", pl.col("t").alias("s"), "heldout_road"))


def event_level(d: pl.DataFrame, col: str, share_: float, ep: pl.DataFrame) -> tuple[float, float, int]:
    a = alerts_at_share(d["t"].to_numpy(), d[col].to_numpy(), share_)
    al = d.filter(pl.Series(a)).select("LinkID", "t", "y")
    hit = pl.concat([al.select("LinkID", (pl.col("t") + timedelta(minutes=k)).alias("s")) for k in (10, 15)]).unique()
    warned = ep.join(hit, on=["LinkID", "s"], how="semi").height
    hours = d["date"].n_unique() * 16
    return warned / max(1, ep.height), al.filter(~pl.col("y")).height / hours, ep.height


ep_main = episodes(full_u).filter(~pl.col("heldout_road"))
ev_rows = []
for n, c in MODELS.items():
    w, fa, ne = event_level(main, c, share, ep_main)
    ev_rows.append([MODEL_LABEL[n], f"{ne:,}", f"{w:.1%}", f"{fa:,.0f}"])

# ---------------------------------------------------------------- tables
lines = ["# Validation week: model choice, calibration, alert share (then frozen)", "",
         f"Validation days: {', '.join(f'{d:%a %d %b}' for d in days)} (Mon 9 Nov is a public holiday). "
         "Scored rows: normal now (U = False). M1 and M2 were fitted on the train days only (no refit). "
         "'band persistence' is a reference score, not one of the decided baselines: the drop the link would have "
         "at t + 10 and t + 15 if its band stayed the same (min of the two).", "",
         "## PR-AUC and precision / recall at the top share of links per update", ""]
lines += md_table(res_rows, ["model", "rows", "base rate", "PR-AUC",
                             *[f"precision / recall at {100 * q:g}%" for q in S.SHARES]])
lines += ["", f"**Final model: {MODEL_LABEL[final]}** (best validation PR-AUC on the training roads among M1 and M2).", "",
          "## Operating share (set on validation: best F1 of the final model)", ""]
lines += md_table([[f"{100 * q:g}%", f"{p:.3f}", f"{r:.3f}", f"{f1[q]:.3f}", f"{n_a / (len(days) * 192):.1f}"]
                   for q, (p, r, n_a) in zip(S.SHARE_GRID, share_tab[(final, "training roads (main)")])],
                  ["share", "precision", "recall", "F1", "alerts per update (1,909 links)"])
lines += ["", f"Chosen operating share: **{100 * share:g}%**.", "", "## Calibration (training roads)", "",
          "Platt map on the logit scale, fitted on the validation week. The 'cross-fitted' columns fit the map on 3 "
          "validation days and apply it to the 4th, so they are honest; the test week uses the map fitted on all 4.", ""]
lines += md_table(cal_rows, ["model", "mean raw", "mean cross-fitted", "observed", "Brier raw", "Brier cross-fitted",
                             "Brier of the base rate", "map"])
lines += ["", "## By day (training roads, PR-AUC)", ""]
lines += md_table(per_day, ["day", "rows", "base rate", *[MODEL_LABEL[n] for n in MODELS]])
lines += ["", "## Day-block bootstrap (4 days: tests the code only; too few days for a real interval)", ""]
lines += md_table(boot_rows, ["model", "PR-AUC", "95% interval", "minus B2 (paired interval)"])
lines += ["", f"## Event level at the operating share ({100 * share:g}%), training roads", "",
          "An episode starts at s when U(s) = 1 and U(s - 5) = 0. It is warned when the link was alerted at s - 15 or "
          "s - 10 (10-15 minutes ahead). A false alarm is an alert whose y is 0; per hour over the 1,909 links "
          "(16 hours a day).", ""]
lines += md_table(ev_rows, ["model", "episodes", "warned 10-15 min ahead", "false alarms per hour"])
write_md("07_validation.md", lines)

# ---------------------------------------------------------------- figures
fig, axs = plt.subplots(1, 2, figsize=(12, 4.4))
y = main["y"].to_numpy()
for n in ("B1", "B2", "B2p", "Lasso", "RF"):
    pr, rc, _ = precision_recall_curve(y, main[MODELS[n]].to_numpy())
    axs[0].plot(rc, pr, color=MODEL_COLOR[n], linewidth=1.8, label=f"{MODEL_LABEL[n]} ({ap_main[n]:.3f})")
axs[0].axhline(y.mean(), color=MUTED, linewidth=1)
axs[0].text(0.99, y.mean(), f"base rate {y.mean():.3f}", ha="right", va="bottom", fontsize=8, color=INK2)
axs[0].set_xlabel("recall")
axs[0].set_ylabel("precision")
axs[0].set_title("Precision-recall, validation week, training roads (PR-AUC)")
axs[0].legend(fontsize=8)
for n in ("B1", "B2", "B2p", "Lasso", "RF"):
    axs[1].plot([100 * q for q in S.SHARE_GRID], [p for p, _, _ in share_tab[(n, "training roads (main)")]],
                color=MODEL_COLOR[n], marker="o", markersize=4, label=MODEL_LABEL[n])
axs[1].axvline(100 * share, color=MUTED, linewidth=1)
axs[1].set_xscale("log")
axs[1].set_xticks([100 * q for q in S.SHARE_GRID])
axs[1].set_xticklabels([f"{100 * q:g}%" for q in S.SHARE_GRID])
axs[1].set_xlabel("alert share: top % of the links at each update (line = chosen)")
axs[1].set_ylabel("precision")
axs[1].set_title("Precision among the highest-ranked alerts")
save(fig, "val_pr_and_precision.png")

fig, ax = plt.subplots(figsize=(5.6, 5))
mx = 0
for n in PROB:
    r = reliability(main["y"].to_numpy(), main[f"{n}_cal"].to_numpy(), bins=15)
    ax.plot(r["mean_pred"], r["observed"], color=MODEL_COLOR[n], marker="o", markersize=4, label=MODEL_LABEL[n])
    mx = max(mx, r["mean_pred"].max(), r["observed"].max())
ax.plot([0, mx], [0, mx], color=MUTED, linewidth=1)
ax.set_xlabel("predicted chance (cross-fitted calibration)")
ax.set_ylabel("observed onset rate")
ax.set_title("Reliability, validation week (15 quantile bins)")
ax.legend(fontsize=8)
save(fig, "val_reliability.png")

# ---------------------------------------------------------------- FREEZE (before any test-week data is opened)
assert not (S.TEST_BUILD / "model" / "test.parquet").exists(), "the test-week build already exists: stop"


def sha(p) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


lasso_info = json.loads((S.TABLES / "05_lasso.json").read_text())
rf_info = json.loads((S.TABLES / "06_random_forest.json").read_text())
chosen = json.loads((S.TABLES / "04_screen_chosen.json").read_text())
freeze = {
    "frozen_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    "statement": "Written before any test-week (14-20 Nov) row, label or raw file was opened by this analysis.",
    "repo_head": subprocess.run(["git", "-C", str(S.ROOT), "rev-parse", "--short", "HEAD"], capture_output=True,
                                text=True).stdout.strip(),
    "data_version": S.DATA_VERSION,
    "train_parquet_sha256": sha(S.TRAIN),
    "scored_rows": "normal now (U = False); main = training roads (heldout_road = False); transfer = AYE + CTE",
    "B1": {"m": 48, "tables": "models/b1_cell.parquet, models/b1_slot.parquet (train days, training roads)"},
    "B2": "f_d0",
    "features": {"LR": chosen["LR"], "RF": chosen["RF"]},
    "lasso": {"frac_of_lambda_max": lasso_info["frac"], "lambda_per_row": lasso_info["lambda_per_row"],
              "solver": "IRLS + coordinate descent (lassofit.py)"},
    "rf": {"params": rf_info["params"], "trees": S.RF_TREES_FINAL, "neg_keep": S.RF_NEG_KEEP},
    "calibration_platt_logit": calib,
    "final_model": final,
    "operating_share": share,
    "report_shares": list(S.SHARES),
    "peak_slots": sorted(S.PEAK_SLOTS),
    "event_level": "episode start s: U(s)=1, U(s-5)=0 known; warned if alerted at s-15 or s-10; false alarm = alert with y=0",
    "bootstrap": {"reps": S.BOOT_REPS, "seed": S.SEED, "unit": "day", "paired": True},
    "files_sha256": {str(p.relative_to(S.ROOT)): sha(p) for p in sorted(list(S.HERE.glob("*.py")) + list(S.MODELS.glob("*")))},
}
S.FREEZE.write_text(json.dumps(freeze, indent=2))
log(f"FROZEN: {S.FREEZE.relative_to(S.ROOT)} at {freeze['frozen_at']}")
