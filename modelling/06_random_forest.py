"""06_random_forest.py - M2, random forest, on the inputs chosen in 04 for the forest.

Fit rows: train days, training roads, normal now; 10% of the y = False rows kept (fixed seed), every onset kept.
Tuned by the same forward-chaining folds (max_features x min_samples_leaf; ties at 4 decimals go to the larger
leaf, then the smaller max_features). The probabilities are recalibrated on the validation week in 07.

AI disclosure: drafted with Claude (Anthropic) on 25 Nov 2026; log in AI_USE.md.
"""
from __future__ import annotations

import json
import pickle

import numpy as np
import polars as pl

import settings as S
from common import ap, f4, log, md_table, write_md
from modeldata import feature_list, fit_forest, fold_frames, forest_score, load_rows, tree_matrix, with_hist
from plotstyle import INK2, MUTED, SLOT, plt, save

names = tuple(json.loads((S.TABLES / "04_screen_chosen.json").read_text())["RF"])
df = load_rows(h=S.HORIZON)
cols = feature_list(df.columns, names)
log(f"forest inputs: {' + '.join(names)} ({len(cols)} columns)")

fit_all = df.filter((pl.col("split") == "train") & ~pl.col("heldout_road"))
val = df.filter(pl.col("split") == "validate")
del df
folds = []
for fit, chk in fold_frames(fit_all):
    if "HIST" in names:
        fit, chk = with_hist(fit, fit, lodo=True), with_hist(chk, fit, lodo=False)
    folds.append((tree_matrix(fit, cols), fit["y"].to_numpy(), tree_matrix(chk, cols), chk["y"].to_numpy()))

cache_p = S.TABLES / "06_rf_cv_cache.json"
cache = json.loads(cache_p.read_text()) if cache_p.exists() else {"trees": S.RF_TREES_TUNE, "results": {}}
assert cache["trees"] == S.RF_TREES_TUNE
res = {}
for g in S.RF_GRID:
    key = (g["max_features"], g["min_samples_leaf"])
    ck = f"{float(key[0])}|{int(key[1])}"
    if ck in cache["results"]:                     # same code, data and seeds: computed in an earlier run
        res[key] = cache["results"][ck]
        log(f"max_features {key[0]:.2f} min_samples_leaf {key[1]:4d}: folds {res[key][0]:.4f} {res[key][1]:.4f} "
            f"mean {np.mean(res[key]):.4f} (cached)")
        continue
    aps = []
    for k, (X1, y1, X2, y2) in enumerate(folds):
        rf = fit_forest(X1, y1, S.RF_TREES_TUNE, S.SEED + k, **g)
        aps.append(ap(y2, forest_score(rf, X2)))
        del rf
    res[key] = aps
    cache["results"][ck] = aps
    cache_p.write_text(json.dumps(cache, indent=2))
    log(f"max_features {key[0]:.2f} min_samples_leaf {key[1]:4d}: folds {aps[0]:.4f} {aps[1]:.4f} mean {np.mean(aps):.4f}")
best = max(res, key=lambda k: (round(float(np.mean(res[k])), 4), k[1], -k[0]))
params = {"max_features": best[0], "min_samples_leaf": best[1]}
log(f"chosen {params}")
del folds

if "HIST" in names:
    fit_all, val = with_hist(fit_all, fit_all, lodo=True), with_hist(val, fit_all, lodo=False)
X, y = tree_matrix(fit_all, cols), fit_all["y"].to_numpy()
rf = fit_forest(X, y, S.RF_TREES_FINAL, S.SEED, **params)
del X
Xv = tree_matrix(val, cols)
sv = forest_score(rf, Xv)
val.select("LinkID", "t", "date", "heldout_road", "y").with_columns(pl.Series("rf_raw", sv)) \
   .write_parquet(S.PREDS / "val_rf.parquet")
with open(S.MODELS / "rf.pkl", "wb") as fh:
    pickle.dump({"model": rf, "cols": cols, "groups": names, "params": params, "trees": S.RF_TREES_FINAL,
                 "neg_keep": S.RF_NEG_KEEP}, fh)
main = ~val["heldout_road"].to_numpy()
yv = val["y"].to_numpy()
log(f"validation PR-AUC (training roads) {ap(yv[main], sv[main]):.4f}; AYE + CTE {ap(yv[~main], sv[~main]):.4f}")

# ---- grouped permutation importance on the validation week (training roads; 400k-row sample, 2 repeats) ----
rng = np.random.default_rng(S.SEED)
idx = np.sort(rng.choice(np.nonzero(main)[0], 400_000, replace=False))
Xs, ys = Xv[idx], yv[idx]
base = ap(ys, forest_score(rf, Xs))


def grp(c: str) -> str:
    if c.startswith("f_conn_"):
        return "joining roads (f_conn_*)"
    if c.startswith(("f_up_", "f_dn_")):
        return "next links (f_up_*, f_dn_*)"
    if c.startswith(("fe_dn_q",)):
        return "HOP: queue distance downstream"
    if c.startswith("fe_dn_"):
        return "HOP: downstream rings"
    if c.startswith(("fe_up_",)):
        return "HOP: upstream rings"
    if c.startswith(("f_d", "f_n_filled")):
        return "own drops (f_d*)"
    if c.startswith("f_rain"):
        return "rain"
    if c == "f_slot15":
        return "time of day"
    if c in ("f_mon", "f_tue", "f_wed", "f_thu", "f_fri"):
        return "day of week"
    if c == "x_b1":
        return "HIST: B1 rate"
    return "NORM: normal level ahead"


gmap: dict[str, list[int]] = {}
for i, c in enumerate(cols):
    gmap.setdefault(grp(c), []).append(i)
imp = []
for g, ii in gmap.items():
    drops = []
    for r in range(2):
        Xp = Xs.copy()
        perm = np.random.default_rng(S.SEED + r).permutation(len(Xp))
        Xp[:, ii] = Xs[perm][:, ii]           # permute the whole group together (rows stay intact otherwise)
        drops.append(base - ap(ys, forest_score(rf, Xp)))
    imp.append((g, len(ii), float(np.mean(drops))))
    log(f"   permutation: {g:34s} drop {np.mean(drops):.4f}")
imp.sort(key=lambda r: -r[2])

lines = ["# M2: random forest", "",
         f"Inputs: **{' + '.join(names)}** ({len(cols)} columns, raw scale). Fit rows: train days, training roads, "
         f"normal now; {S.RF_NEG_KEEP:.0%} of the y = False rows kept with a fixed seed, every onset kept. "
         f"{S.RF_TREES_TUNE} trees while tuning, {S.RF_TREES_FINAL} in the final forest.", "",
         "## Tuning (forward-chaining inside the train days)", ""]
lines += md_table([[k[0], k[1], f4(a[0]), f4(a[1]), ("**" + f4(np.mean(a)) + "**") if k == best else f4(np.mean(a))]
                   for k, a in sorted(res.items())], ["max_features", "min_samples_leaf", "fold 1", "fold 2", "mean"])
lines += ["", f"Chosen: **{params}**.", "",
          "## Grouped permutation importance (validation week, training roads, 400,000-row sample, 2 repeats)", "",
          f"PR-AUC of the sample with nothing permuted: {base:.4f}. Each group's columns are shuffled together.", ""]
lines += md_table([[g, n, f4(d)] for g, n, d in imp], ["input group", "columns", "PR-AUC drop"])
write_md("06_random_forest.md", lines)
(S.TABLES / "06_random_forest.json").write_text(json.dumps({"params": params, "cv": {str(k): v for k, v in res.items()},
                                                            "importance": imp}))

fig, ax = plt.subplots(figsize=(8, 4.4))
ax.barh(range(len(imp))[::-1], [d for _, _, d in imp], color=SLOT[0], height=0.6)
ax.set_yticks(range(len(imp))[::-1])
ax.set_yticklabels([g for g, _, _ in imp], fontsize=8)
for i, (_, _, d) in zip(range(len(imp))[::-1], imp):
    ax.text(max(d, 0), i, f"  {d:.3f}", va="center", fontsize=8, color=INK2)
ax.set_xlabel("drop in validation PR-AUC when the group is shuffled")
ax.set_title("M2 random forest: which inputs it relies on")
ax.grid(axis="y", visible=False)
save(fig, "m2_rf_importance.png")
