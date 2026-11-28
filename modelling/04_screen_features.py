"""04_screen_features.py - which engineered groups to add, per model family, by forward-chaining inside the train
days (rule fixed in settings.py before this ran). Plain logistic regression stands in for the lasso here (with
4.6 M rows the penalty barely moves the score; the lasso path is tuned in 05). Train days only.

AI disclosure: drafted with Claude (Anthropic) on 25 Nov 2026; log in AI_USE.md.
"""
from __future__ import annotations

import itertools
import json

import numpy as np
import polars as pl

import settings as S
from common import ap, f4, log, md_table, write_md
from modeldata import (Scaler, feature_list, fit_forest, fit_logistic, fold_frames, forest_score, lasso_matrix,
                       load_rows, tree_matrix, with_hist)

df = load_rows(h=S.HORIZON, splits=("train",))
log(f"train onset rows: {df.height:,}")
folds = []
for fit, chk in fold_frames(df):
    folds.append((with_hist(fit, fit, lodo=True), with_hist(chk, fit, lodo=False)))
    log(f"fold: fit {fit.height:,} ({int(fit['y'].sum()):,} onsets), check {chk.height:,} ({int(chk['y'].sum()):,})")

subsets = [tuple(g for g, on in zip(S.SCREEN_ORDER, mask) if on)
           for mask in itertools.product([0, 1], repeat=len(S.SCREEN_ORDER))]
res: dict[tuple[str, tuple], list[float]] = {}
for sub in subsets:
    names = ("BASE",) + sub
    cols = feature_list(df.columns, names)
    for fam in ("LR", "RF"):
        aps = []
        for k, (fit, chk) in enumerate(folds):
            if fam == "LR":
                Xf, _ = lasso_matrix(fit, cols)
                sc = Scaler(Xf)
                m = fit_logistic(sc(Xf), fit["y"].to_numpy(), C=np.inf, l1=False)
                Xc, _ = lasso_matrix(chk, cols)
                s = m.predict_proba(sc(Xc))[:, 1]
            else:
                rf = fit_forest(tree_matrix(fit, cols), fit["y"].to_numpy(), S.RF_TREES_TUNE, S.SEED + k, **S.RF_SCREEN)
                s = forest_score(rf, tree_matrix(chk, cols))
                del rf
            aps.append(ap(chk["y"].to_numpy(), s))
        res[(fam, sub)] = aps
        log(f"{fam} {'+'.join(names):22s} {len(cols):3d} inputs  folds {aps[0]:.4f} {aps[1]:.4f}  mean {np.mean(aps):.4f}")

chosen = {}
for fam in ("LR", "RF"):
    cur: tuple = ()
    for g in S.SCREEN_ORDER:
        cand = tuple(x for x in S.SCREEN_ORDER if x in cur + (g,))
        gain = np.mean(res[(fam, cand)]) - np.mean(res[(fam, cur)])
        if gain >= S.MIN_GAIN:
            cur = cand
    chosen[fam] = ("BASE",) + cur
(S.TABLES / "04_screen_chosen.json").write_text(json.dumps({"LR": chosen["LR"], "RF": chosen["RF"]}))

rows = []
for sub in subsets:
    n = len(feature_list(df.columns, ("BASE",) + sub))
    lr, rf = res[("LR", sub)], res[("RF", sub)]
    rows.append(["+".join(("BASE",) + sub), n, f4(lr[0]), f4(lr[1]), f"**{f4(np.mean(lr))}**",
                 f4(rf[0]), f4(rf[1]), f"**{f4(np.mean(rf))}**"])
base_rates = [f4(chk["y"].mean()) for _, chk in folds]
lines = ["# Feature screen (forward-chaining inside the train days; training roads; onset rows)", "",
         f"Fold 1: fit 16-23 Oct, check 26-30 Oct (base rate {base_rates[0]}). "
         f"Fold 2: fit 16-30 Oct, check 2-6 Nov (base rate {base_rates[1]}).",
         f"LR = plain logistic regression on the lasso view (hour groups, log rain), scaled on the fit rows. "
         f"RF = {S.RF_TREES_TUNE} trees, {S.RF_SCREEN}, 10% of the y = False fit rows.", ""]
lines += md_table(rows, ["inputs", "n", "LR fold 1", "LR fold 2", "LR mean", "RF fold 1", "RF fold 2", "RF mean"])
lines += ["", f"Rule (fixed before the run): groups tried in the order {', '.join(S.SCREEN_ORDER)}; a group is kept "
              f"when it raises that family's mean by at least {S.MIN_GAIN}.", "",
          f"Chosen: lasso (M1) **{' + '.join(chosen['LR'])}**; random forest (M2) **{' + '.join(chosen['RF'])}**."]
write_md("04_screen.md", lines)
