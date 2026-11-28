"""14_validation_windows.py - did we cross-validate properly? The course notes (ch. 7.3) against what we did
(28 Nov).

The notes: random folds suit independent rows; for forecasting use rolling or forward validation (fit on the past,
check on later observations); pool the held-out errors (every row the same weight) or say that the parts are
averaged; refit all preprocessing inside each split; the one-standard-error rule prefers the simpler model when the
gain is within the noise.
What we did: forward validation with TWO windows inside the 16 train days (each adds a week), and the mean of the
two PR-AUCs. This check: no shuffled folds; the windowing method, adding two days at a time.

RULES, FIXED BEFORE THE RUN (28 Nov, before any result of this script was seen):
- W2 = the two frozen windows: fit 16-23 Oct -> check 26-30 Oct; fit 16-30 Oct -> check 2-6 Nov.
- W6 = an expanding window that adds 2 days at a time: start with the first 4 train days (16, 19, 20, 21 Oct), check
  on the next 2 train days, add them, repeat: 6 windows, check days 22-23 Oct | 26-27 Oct | 28-29 Oct |
  30 Oct + 2 Nov | 3-4 Nov | 5-6 Nov. Every day from 22 Oct to 6 Nov is checked once, always by a model fitted on
  earlier days only.
- Lasso: the frozen penalty grid (fractions of the frozen lambda_max, the same penalty per row in every fit), on W2
  and W6. For each: the mean of the window PR-AUCs (what we used), the pooled PR-AUC and the pooled deviance per row
  over all held-out rows (the notes' pooling), and the one-standard-error rule (the strongest penalty whose mean is
  within one standard error of the best mean).
- Forest (150 trees, every onset + 10% of the other fit rows): max_features sqrt(p) (the notes' starting point for
  classification), 0.35, 0.6 and all inputs (= bagging) with min_samples_leaf 20; 0.35 and 0.6 with leaf 80. On W6.
  On W2: sqrt(p) and bagging, and the 12 settings of the tuning grid again (the same forests as in
  06_random_forest.py: same rows, settings and seeds).
- In every window the scaling, HIST and the 10% subsample are refitted on that window's fit rows only.
Train days and training roads only. The validation week and the test week are NOT read.

Run (from modelling/, after 05 and 06; about 1 h 40 min):
    systemd-run --user --scope -q -p MemoryMax=14G nice -n 10 python 14_validation_windows.py

AI disclosure: drafted with Claude (Anthropic) on 28 Nov 2026; log in AI_USE.md.
"""
from __future__ import annotations

import json
import pickle
from datetime import date

import numpy as np
import polars as pl

import settings as S
from common import ap, between, log, md_table, write_md
from lassofit import LassoLogit
from modeldata import Scaler, feature_list, fit_forest, forest_score, lasso_matrix, load_rows, tree_matrix, with_hist
from plotstyle import INK2, MUTED, SLOT, plt, save

NAMES = tuple(json.loads((S.TABLES / "04_screen_chosen.json").read_text())["RF"])
LMAX = pickle.load(open(S.MODELS / "lasso.pkl", "rb"))["lambda_max"]
FRACS = S.LASSO_FRACS
LAMS = {f: f * LMAX for f in FRACS}
FROZEN_FRAC = 0.0003
D = lambda m, dd: date(2026, m, dd)
W2 = S.FOLDS
RF_W6 = [("sqrt", 20), (0.35, 20), (0.6, 20), (1.0, 20), (0.35, 80), (0.6, 80)]
RF_W2 = [("sqrt", 20), (1.0, 20)] + [(g["max_features"], g["min_samples_leaf"]) for g in S.RF_GRID]
RF_SHOW = [(0.35, 20), (0.6, 20)]
START_DAYS, STEP_DAYS = 4, 2

df = load_rows(h=S.HORIZON, splits=("train",))
fit_all = df.filter(~pl.col("heldout_road"))
del df
cols = feature_list(fit_all.columns, NAMES)
assert fit_all["date"].max() <= S.TRAIN_DAYS[1]
log(f"fit rows {fit_all.height:,} ({int(fit_all['y'].sum()):,} onsets), {len(cols)} inputs")
DAYS = sorted(fit_all["date"].unique().to_list())
assert len(DAYS) == 16
W6 = [((DAYS[0], DAYS[i - 1]), (DAYS[i], DAYS[i + STEP_DAYS - 1])) for i in range(START_DAYS, len(DAYS), STEP_DAYS)]
assert len(W6) == 6 and W6[-1][1][1] == DAYS[-1]


def frames(fit: pl.DataFrame, chk: pl.DataFrame):
    """HIST refitted inside the fold: own day left out for the fit rows; the check rows never inform it."""
    return with_hist(fit, fit, lodo=True), with_hist(chk, fit, lodo=False)


def lasso_path(fit, chk, fracs):
    X1, _ = lasso_matrix(fit, cols)
    sc = Scaler(X1)
    X1 = sc(X1, inplace=True)
    X2, _ = lasso_matrix(chk, cols)
    X2 = sc(X2, inplace=True)
    y1, y2 = fit["y"].to_numpy(), chk["y"].to_numpy()
    out, prev = {}, None
    for f in fracs:
        m = LassoLogit(LAMS[f]).fit(X1, y1, coef_init=None if prev is None else prev.coef_,
                                    intercept_init=None if prev is None else prev.intercept_)
        out[f] = (m.predict_proba(X2)[:, 1], int((m.coef_ != 0).sum()))
        prev = m
    return out


def forests(fit, chk, settings, k):
    X1, y1, X2 = tree_matrix(fit, cols), fit["y"].to_numpy(), tree_matrix(chk, cols)
    out = {}
    for mf, leaf in settings:
        rf = fit_forest(X1, y1, S.RF_TREES_TUNE, S.SEED + k, max_features=mf, min_samples_leaf=leaf)
        out[(mf, leaf)] = forest_score(rf, X2)
        del rf
    return out


def summarise(ys: list[np.ndarray], ps: list[np.ndarray]) -> dict:
    """Fold PR-AUCs, their mean and standard error, and the pooled PR-AUC / deviance over all held-out rows."""
    aps = [ap(y, p) for y, p in zip(ys, ps)]
    y, p = np.concatenate(ys), np.clip(np.concatenate(ps), 1e-12, 1 - 1e-12)
    dev = float(-2.0 * np.mean(np.where(y, np.log(p), np.log(1 - p))))
    return {"folds": aps, "mean": float(np.mean(aps)), "se": float(np.std(aps, ddof=1) / np.sqrt(len(aps))),
            "pooled": ap(y, p), "deviance": dev}


res: dict = {"lasso": {}, "forest": {}, "windows": {}}

for name, wins, rf_set in (("W6", W6, RF_W6), ("W2", W2, RF_W2)):
    ys, b2 = [], []
    lp, nz, fp = {f: [] for f in FRACS}, {f: [] for f in FRACS}, {s_: [] for s_ in rf_set}
    for k, ((a, b), (c, e)) in enumerate(wins):
        fit, chk = frames(fit_all.filter(between("date", a, b)), fit_all.filter(between("date", c, e)))
        ys.append(chk["y"].to_numpy())
        b2.append(ap(ys[-1], chk["f_d0"].to_numpy()))
        log(f"{name} window {k + 1}: fit {a:%d %b}-{b:%d %b} ({fit['date'].n_unique()} days, {fit.height:,} rows), "
            f"check {c:%d %b}-{e:%d %b} ({chk.height:,} rows, onset rate {ys[-1].mean():.4f})")
        for f, (p, n) in lasso_path(fit, chk, FRACS).items():
            lp[f].append(p)
            nz[f].append(n)
        log("   lasso path done")
        for s_, p in forests(fit, chk, rf_set, k).items():
            fp[s_].append(p)
            log(f"   forest {s_}: {ap(ys[-1], p):.4f}")
        del fit, chk
    res["lasso"][name] = {str(f): {**summarise(ys, lp[f]), "inputs": nz[f]} for f in FRACS}
    res["forest"][name] = {f"{s_[0]}|{s_[1]}": summarise(ys, fp[s_]) for s_ in rf_set}
    res["windows"][name] = {"fit_days": [int(sum(a <= d_ <= b for d_ in DAYS)) for (a, b), _ in wins],
                            "check": [f"{c:%d %b} - {e:%d %b}" for _, (c, e) in wins],
                            "check_rows": [len(y) for y in ys], "base_rates": [float(y.mean()) for y in ys], "b2": b2}
    del lp, fp
    (S.TABLES / "14_validation_windows.json").write_text(json.dumps(res, indent=1))


# ---------------------------------------------------------------- choices under each rule
def lasso_choices(r: dict) -> dict:
    fr = [float(f) for f in r]
    mean = {f: r[str(f)]["mean"] for f in fr}
    best = max(fr, key=lambda f: (round(mean[f], 4), f))
    return {"mean of the windows (ours)": best,
            "pooled PR-AUC": max(fr, key=lambda f: (round(r[str(f)]["pooled"], 4), f)),
            "pooled deviance": min(fr, key=lambda f: (round(r[str(f)]["deviance"], 6), -f)),
            "one-standard-error rule": max(f for f in fr if mean[f] >= mean[best] - r[str(best)]["se"])}


def rank_key(r: dict, key: str, what: str):
    mf, leaf = key.split("|")
    return (round(r[key][what], 4), int(leaf), -(0.1 if mf == "sqrt" else float(mf)))   # ties: larger leaf, smaller m


choice = {n: lasso_choices(res["lasso"][n]) for n in ("W2", "W6")}
w6_keys = [f"{s_[0]}|{s_[1]}" for s_ in RF_W6]
res["choices"] = {"lasso": choice,
                  "forest_W6_mean": max(w6_keys, key=lambda k_: rank_key(res["forest"]["W6"], k_, "mean")),
                  "forest_W6_pooled": max(w6_keys, key=lambda k_: rank_key(res["forest"]["W6"], k_, "pooled")),
                  "forest_W2_mean": max(res["forest"]["W2"], key=lambda k_: rank_key(res["forest"]["W2"], k_, "mean"))}
(S.TABLES / "14_validation_windows.json").write_text(json.dumps(res, indent=1))

# ---------------------------------------------------------------- tables
f4 = lambda x: "" if x is None else f"{x:.4f}"
lab = lambda k_: ("sqrt(p) = 9 inputs" if k_.startswith("sqrt") else "all 96 inputs (bagging)" if k_.startswith("1.0")
                  else f"max_features {k_.split('|')[0]}") + f", leaf {k_.split('|')[1]}"
lines = ["# Did we cross-validate properly? The windowing method, as taught, against what we did (28 Nov)", "",
         "Train days and training roads only; the validation and test weeks are not read. Rules fixed in the script "
         "header before the run. PR-AUC unless stated. Every model is fitted on earlier days only and checked on the "
         "days that follow (forward validation); nothing is shuffled.", "",
         "## 1. The windows", "",
         "W2 = the two frozen windows (each adds a week). W6 = an expanding window that starts with 4 days and adds 2 "
         "days at a time.", ""]
lines += md_table([[n, k + 1, res["windows"][n]["fit_days"][k], res["windows"][n]["check"][k],
                    f"{res['windows'][n]['check_rows'][k]:,}", f"{res['windows'][n]['base_rates'][k]:.4f}",
                    f4(res["windows"][n]["b2"][k])] for n in ("W2", "W6") for k in range(len(res["windows"][n]["check"]))],
                  ["scheme", "window", "fit days", "check days", "check rows", "onset rate", "B2 last observation"])
lines += ["", "## 2. The lasso penalty", ""]
for n in ("W2", "W6"):
    r = res["lasso"][n]
    lines += [f"**{n}**", ""]
    lines += md_table([[f"x {f}", " / ".join(str(i_) for i_ in r[str(f)]["inputs"]), f4(r[str(f)]["mean"]),
                        f"{r[str(f)]['se']:.4f}", f4(r[str(f)]["pooled"]), f"{r[str(f)]['deviance']:.5f}"] for f in FRACS],
                      ["lambda / lambda_max", "inputs kept per window", "mean of the window PR-AUCs", "standard error",
                       "pooled PR-AUC", "pooled deviance per row"])
    lines += ["", "Chosen: " + "; ".join(f"{k_}: **x {v:g}**" for k_, v in choice[n].items()) + ".", ""]
lines += ["## 3. The forest settings (150 trees)", ""]
lines += md_table([[lab(k_), f4(res["forest"]["W6"][k_]["mean"]), f"{res['forest']['W6'][k_]['se']:.4f}",
                    f4(res["forest"]["W6"][k_]["pooled"]), " ".join(f"{x:.3f}" for x in res["forest"]["W6"][k_]["folds"]),
                    f4(res["forest"]["W2"].get(k_, {}).get("mean"))] for k_ in w6_keys],
                  ["setting", "W6: mean of the windows", "standard error", "W6: pooled", "W6: the six windows",
                   "W2: mean of the windows"])
lines += ["", f"Best on W6 by the mean of the windows: **{lab(res['choices']['forest_W6_mean'])}**; by the pooled score: "
              f"**{lab(res['choices']['forest_W6_pooled'])}**. Best on W2 (the 12 frozen settings plus sqrt(p) and "
              f"bagging), by the mean: **{lab(res['choices']['forest_W2_mean'])}**.", "",
          "W2 for the 12 settings of the tuning grid repeats the forests of `06_random_forest.py` "
          "(the same rows, settings and seeds)."]
write_md("14_validation_windows.md", lines)

fig, ax = plt.subplots(figsize=(8.5, 3.8))
x = np.arange(len(W6))
ax.plot(x, res["windows"]["W6"]["b2"], color=INK2, marker="o", markersize=4, label="B2 last observation")
ax.plot(x, res["lasso"]["W6"][str(FROZEN_FRAC)]["folds"], color=SLOT[1], marker="o", markersize=4, label="lasso (frozen penalty)")
for s_, c_, ls in zip(RF_SHOW, (SLOT[0], SLOT[0]), ("-", "--")):
    ax.plot(x, res["forest"]["W6"][f"{s_[0]}|{s_[1]}"]["folds"], color=c_, linestyle=ls, marker="o", markersize=4,
            label=f"forest, max_features {s_[0]}")
ax.set_xticks(x)
ax.set_xticklabels([f"{n_} days\n-> {c_}" for n_, c_ in zip(res["windows"]["W6"]["fit_days"], res["windows"]["W6"]["check"])], fontsize=8)
ax.set_ylabel("PR-AUC on the check days")
ax.set_title("Expanding window, 2 days at a time: fit on the days so far, check on the next 2")
ax.legend(fontsize=8, ncol=2)
save(fig, "14_validation_windows.png")
log("done")
