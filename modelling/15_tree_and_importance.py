"""15_tree_and_importance.py - the course's tree tools on our data (notes ch. 9): one decision tree with
cost-complexity pruning, chosen by forward (windowing) validation and the one-standard-error rule; the forest's
out-of-bag error; and variable importance, i.e. a ranking of the inputs (28 Nov).

RULES, FIXED BEFORE THE RUN (28 Nov, before any result of this script was seen):
- Tree: CART (Gini), min_samples_leaf 20, on every onset + 10% of the other fit rows (as the forest), 96 inputs.
- Candidate sizes: 16 values of the cost-complexity alpha from the pruning path of the tree grown on all train rows
  (log-spaced along the path, from the full tree down to a stump).
- Chosen by the windowing validation W6 of 14_validation_windows.py (start with 4 train days, add 2 days at a
  time, check on the next 2): in each window the tree is grown and pruned on that window's fit rows only.
  Criterion: the mean PR-AUC over the 6 windows. Two rules, as in the notes: the minimum-error rule (best mean;
  ties to the smaller tree) and the one-standard-error rule (the smallest tree whose mean is within one standard
  error of the best).
- The two chosen trees are refitted on all train rows and scored on the validation week, next to the frozen forest.
- Ranking of the inputs of the frozen forest: impurity-based importance (mean decrease in Gini) and permutation
  importance (drop in validation PR-AUC when one input is shuffled: 300,000 validation rows of the training roads,
  one shuffle per input, fixed seed). And the 15 largest lasso coefficients, with their odds ratios.
- Out-of-bag error: a forest of 50 trees with the frozen settings (max_features 0.6, leaf 20) on the forest's fit
  rows: PR-AUC on its fit rows, out of bag, and on the validation week (sampled like the fit rows). First run on
  27 Nov; repeated here with the same rows and seed so that this script stands alone.
Train and validation days only; the test week is not read.

Run (from modelling/, after 06; about 50 min):
    systemd-run --user --scope -q -p MemoryMax=14G nice -n 10 python 15_tree_and_importance.py

AI disclosure: drafted with Claude (Anthropic) on 28 Nov 2026; log in AI_USE.md.
"""
from __future__ import annotations

import json
import pickle

import numpy as np
import polars as pl
from scipy.stats import spearmanr
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score
from sklearn.tree import DecisionTreeClassifier, export_text

import settings as S
from common import ap, between, log, md_table, write_md
from modeldata import feature_list, forest_score, load_rows, neg_subsample, tree_matrix, with_hist
from plotstyle import INK2, MUTED, SLOT, plt, save

NAMES = tuple(json.loads((S.TABLES / "04_screen_chosen.json").read_text())["RF"])
LEAF, N_ALPHA, START_DAYS, STEP_DAYS = 20, 16, 4, 2
OOB_TREES = 50

df = load_rows(h=S.HORIZON)
fit_all = df.filter((pl.col("split") == "train") & ~pl.col("heldout_road"))
val = df.filter(pl.col("split") == "validate")
del df
raw_fit = fit_all
fit_all, val = with_hist(fit_all, fit_all, lodo=True), with_hist(val, fit_all, lodo=False)
cols = feature_list(fit_all.columns, NAMES)
DAYS = sorted(fit_all["date"].unique().to_list())
W6 = [((DAYS[0], DAYS[i - 1]), (DAYS[i], DAYS[i + STEP_DAYS - 1])) for i in range(START_DAYS, len(DAYS), STEP_DAYS)]
assert len(DAYS) == 16 and len(W6) == 6 and val["date"].max() <= S.LAST_OPEN_DAY

# ---------------------------------------------------------------- 1. the pruning path on all train rows
X, y = tree_matrix(fit_all, cols), fit_all["y"].to_numpy()
idx = neg_subsample(y, S.RF_NEG_KEEP, S.SEED)
Xs, ys = X[idx], y[idx]
del X
tree = lambda a: DecisionTreeClassifier(min_samples_leaf=LEAF, random_state=S.SEED, ccp_alpha=float(a))
path = tree(0.0).cost_complexity_pruning_path(Xs, ys)
alphas_all = np.unique(path.ccp_alphas)
pos = np.unique(np.round(np.geomspace(1, len(alphas_all) - 1, N_ALPHA)).astype(int))
alphas = np.sort(alphas_all[len(alphas_all) - 1 - pos])            # from the full tree (alpha 0) to a stump
log(f"tree fit rows {len(ys):,} ({int(ys.sum()):,} onsets); pruning path {len(alphas_all):,} steps; {len(alphas)} candidates")

# ---------------------------------------------------------------- 2. windowing validation
cv = {float(a): [] for a in alphas}
for k, ((a0, b0), (c0, e0)) in enumerate(W6):
    fit, chk = raw_fit.filter(between("date", a0, b0)), raw_fit.filter(between("date", c0, e0))
    fit, chk = with_hist(fit, fit, lodo=True), with_hist(chk, fit, lodo=False)
    X1, y1, X2, y2 = tree_matrix(fit, cols), fit["y"].to_numpy(), tree_matrix(chk, cols), chk["y"].to_numpy()
    i1 = neg_subsample(y1, S.RF_NEG_KEEP, S.SEED + k)
    Xa, ya = X1[i1], y1[i1]
    for a in alphas:
        t = tree(a).fit(Xa, ya)
        cv[float(a)].append(ap(y2, t.predict_proba(X2)[:, 1]))
    log(f"window {k + 1}: fit {a0:%d %b}-{b0:%d %b} ({len(i1):,} rows used), check {c0:%d %b}-{e0:%d %b}: "
        f"full tree {cv[float(alphas[0])][-1]:.4f}, best {max(v[-1] for v in cv.values()):.4f}")
    del fit, chk, X1, X2
mean = {a: float(np.mean(v)) for a, v in cv.items()}
se = {a: float(np.std(v, ddof=1) / np.sqrt(len(v))) for a, v in cv.items()}
a_min = max(cv, key=lambda a: (round(mean[a], 4), a))                 # ties: the larger alpha = the smaller tree
a_1se = max(a for a in cv if mean[a] >= mean[a_min] - se[a_min])

# ---------------------------------------------------------------- 3. the candidates and the two chosen trees, on all train rows
Xv, yv = tree_matrix(val, cols), val["y"].to_numpy()
main = ~val["heldout_road"].to_numpy()
rows, fitted = [], {}
for a in alphas:
    t = tree(a).fit(Xs, ys)
    rows.append({"alpha": float(a), "leaves": int(t.get_n_leaves()), "depth": int(t.get_depth()),
                 "train": ap(ys, t.predict_proba(Xs)[:, 1]), "cv": mean[float(a)], "se": se[float(a)],
                 "windows": cv[float(a)]})
    if float(a) in (a_min, a_1se):
        fitted[float(a)] = t
log(f"minimum-error rule: alpha {a_min:.3e}; one-standard-error rule: alpha {a_1se:.3e}")
rf = pickle.load(open(S.MODELS / "rf.pkl", "rb"))
assert rf["cols"] == cols
s_rf = forest_score(rf["model"], Xv)
scores = {"tree_min": fitted[a_min].predict_proba(Xv)[:, 1], "tree_1se": fitted[a_1se].predict_proba(Xv)[:, 1], "rf": s_rf}
val.select("LinkID", "t", "heldout_road", "y").with_columns(
    pl.Series("tree_min", scores["tree_min"]), pl.Series("tree_1se", scores["tree_1se"])
).write_parquet(S.PREDS / "val_tree.parquet")
vres = {n: {"main": ap(yv[main], s[main]), "transfer": ap(yv[~main], s[~main]),
            "roc_main": float(roc_auc_score(yv[main], s[main]))} for n, s in scores.items()}
assert abs(vres["rf"]["main"] - 0.3482) < 5e-4, vres["rf"]

# ---------------------------------------------------------------- 3b. out-of-bag check (a small forest)
oob_rf = RandomForestClassifier(n_estimators=OOB_TREES, max_features=0.6, min_samples_leaf=LEAF, n_jobs=S.RF_JOBS,
                                random_state=S.SEED, oob_score=True).fit(Xs, ys)
oob_p = oob_rf.oob_decision_function_[:, 1]
seen = np.isfinite(oob_p)                                 # rows that at least one tree left out
vi = np.nonzero(main)[0]
vi = vi[neg_subsample(yv[vi], S.RF_NEG_KEEP, S.SEED)]    # training roads, sampled like the fit rows
oob = {"train_ap": ap(ys, forest_score(oob_rf, Xs)), "oob_ap": ap(ys[seen], oob_p[seen]),
       "val_ap": ap(yv[vi], forest_score(oob_rf, Xv[vi]))}
del oob_rf
log(f"out-of-bag check: fit rows {oob['train_ap']:.4f}, out of bag {oob['oob_ap']:.4f}, validation {oob['val_ap']:.4f}")

# ---------------------------------------------------------------- 4. ranking of the inputs (frozen forest)
model = rf["model"]
gini = model.feature_importances_
rng = np.random.default_rng(S.SEED)
sample = np.sort(rng.choice(np.nonzero(main)[0], 300_000, replace=False))
Xp, yp = Xv[sample].copy(), yv[sample]
base = ap(yp, forest_score(model, Xp))
perm = np.zeros(len(cols))
for j in range(len(cols)):
    keep = Xp[:, j].copy()
    Xp[:, j] = keep[np.random.default_rng(S.SEED + 1 + j).permutation(len(keep))]
    perm[j] = base - ap(yp, forest_score(model, Xp))
    Xp[:, j] = keep
log(f"permutation importance done (base PR-AUC of the sample {base:.4f})")
rho = float(spearmanr(gini, perm).statistic)
r_gini, r_perm = np.argsort(-gini), np.argsort(-perm)
rank_g = {int(j): i + 1 for i, j in enumerate(r_gini)}
rank_p = {int(j): i + 1 for i, j in enumerate(r_perm)}


def group(c: str) -> str:
    if c.startswith("f_conn_"):
        return "joining roads"
    if c.startswith(("f_up_", "f_dn_")):
        return "next links"
    if c.startswith("fe_dn_q"):
        return "HOP: queue distance downstream"
    if c.startswith("fe_dn_"):
        return "HOP: downstream rings"
    if c.startswith("fe_up_"):
        return "HOP: upstream rings"
    if c.startswith(("f_d", "f_n_filled")):
        return "own drops"
    if c.startswith("f_rain"):
        return "rain"
    if c == "f_slot15":
        return "time of day"
    if c in ("f_mon", "f_tue", "f_wed", "f_thu", "f_fri"):
        return "day of week"
    return "HIST: usual onset rate" if c == "x_b1" else "NORM: normal level ahead"


gsum: dict[str, list[float]] = {}
for j, c in enumerate(cols):
    g = gsum.setdefault(group(c), [0.0, 0.0, 0])
    g[0] += float(gini[j])
    g[1] += float(perm[j])
    g[2] += 1

lasso = pickle.load(open(S.MODELS / "lasso.pkl", "rb"))
coef = lasso["model"].coef_.ravel()

out = {"alphas": rows, "alpha_min": a_min, "alpha_1se": a_1se, "validation": vres, "spearman": rho,
       "importance": [{"input": c, "gini": float(gini[j]), "perm": float(perm[j])} for j, c in enumerate(cols)],
       "perm_base": base}
(S.TABLES / "15_tree_and_importance.json").write_text(json.dumps(out, indent=1))

# ---------------------------------------------------------------- tables
by_a = {r["alpha"]: r for r in rows}
mark = lambda a: " (minimum error)" if a == a_min else " (one standard error)" if a == a_1se else ""
lines = ["# The course's tree tools on our data: pruning, out-of-bag error, ranking the inputs (28 Nov)", "",
         "Train and validation days only; the test week is not read. Rules fixed in the script header before the run.", "",
         "## 1. One decision tree, pruned by cost-complexity", "",
         f"CART (Gini, min_samples_leaf {LEAF}) on every onset + 10% of the other fit rows ({len(ys):,} rows), the 96 "
         f"inputs. The pruning path of the tree grown on all train rows has {len(alphas_all):,} steps; "
         f"{len(alphas)} sizes were compared. Each size was scored by the windowing validation (6 windows, adding 2 "
         "days at a time), growing and pruning inside each window. 'Train' is the PR-AUC on the tree's own fit rows.", ""]
lines += md_table([[f"{r['alpha']:.2e}", f"{r['leaves']:,}", r["depth"], f"{r['train']:.4f}",
                    f"**{r['cv']:.4f}**" if r["alpha"] in (a_min, a_1se) else f"{r['cv']:.4f}", f"{r['se']:.4f}",
                    " ".join(f"{x:.3f}" for x in r["windows"]) + mark(r["alpha"])] for r in rows],
                  ["alpha", "leaves (all train rows)", "depth", "train", "windowing mean", "standard error", "the six windows"])
lines += ["", f"- **Minimum-error rule:** alpha {a_min:.2e}, {by_a[a_min]['leaves']:,} leaves, mean {mean[a_min]:.4f} "
              f"(standard error {se[a_min]:.4f}).",
          f"- **One-standard-error rule:** alpha {a_1se:.2e}, {by_a[a_1se]['leaves']:,} leaves, mean {mean[a_1se]:.4f}: "
          "the smallest tree within one standard error of the best.",
          f"- The unpruned tree ({rows[0]['leaves']:,} leaves) scores {rows[0]['train']:.4f} on its own fit rows but "
          f"{rows[0]['cv']:.4f} on later days: it overfits.", "",
          "## 2. The pruned trees against the forest (validation week)", ""]
lines += md_table([[lab, f"{by_a[a]['leaves']:,}" if a is not None else "400 trees", f"{vres[n]['main']:.4f}",
                    f"{vres[n]['transfer']:.4f}", f"{vres[n]['roc_main']:.3f}"]
                   for lab, n, a in (("pruned tree, minimum-error rule", "tree_min", a_min),
                                     ("pruned tree, one-standard-error rule", "tree_1se", a_1se),
                                     ("random forest (frozen)", "rf", None))],
                  ["model", "leaves", "PR-AUC, training roads", "PR-AUC, AYE + CTE", "ROC-AUC, training roads"])
t1 = fitted[a_1se]
used = sorted({cols[i] for i in t1.tree_.feature if i >= 0})
lines += ["", f"The one-standard-error tree uses {len(used)} of the 96 inputs: {', '.join(f'`{c}`' for c in used)}.", "",
          "Its first splits (a row goes left when the condition holds; `class` is the majority class in the node, on "
          "the fit rows, where 10% of the other rows are kept):", "", "```",
          export_text(t1, feature_names=cols, max_depth=3, decimals=2).rstrip(), "```", "",
          "## 3. Out-of-bag error", "",
          f"A forest of {OOB_TREES} trees with the frozen settings (max_features 0.6, leaf {LEAF}), fitted on the same "
          "rows as the tree (every onset + 10% of the other rows; the validation rows are sampled the same way, so the "
          "level is not comparable with the tables above): PR-AUC on the fit rows "
          f"{oob['train_ap']:.3f}, out of bag {oob['oob_ap']:.3f}, on the validation week {oob['val_ap']:.3f}. The "
          "out-of-bag score is too optimistic here: a row left out of a tree still has its neighbours in time (the "
          "same link, 5 minutes apart) inside that tree's sample. The notes warn that ordinary row-level resampling "
          "assumes independent rows. Forward validation by whole days does not have this problem.", "",
          "## 4. Ranking the inputs (frozen forest)", "",
          f"Two measures, as in the notes. Impurity: the mean decrease in Gini over the forest's splits (sums to 1). "
          f"Permutation: the drop in validation PR-AUC when one input is shuffled (sample PR-AUC {base:.4f}). "
          f"Spearman correlation of the two rankings over the 96 inputs: {rho:.2f}.", ""]
lines += md_table([[i + 1, f"`{cols[j]}`", group(cols[j]), f"{perm[j]:.4f}", f"{gini[j]:.4f}", rank_g[int(j)]]
                   for i, j in enumerate(r_perm[:20])],
                  ["rank (permutation)", "input", "group", "permutation importance", "impurity importance", "rank (impurity)"])
lines += ["", "Top 10 by impurity: " + ", ".join(f"`{cols[j]}` ({gini[j]:.3f}; permutation rank {rank_p[int(j)]})"
                                                   for j in r_gini[:10]) + ".", "",
          "By group (importance summed over the group's inputs; shuffling one input at a time understates a group "
          "whose inputs can stand in for each other):", ""]
lines += md_table([[g, v[2], f"{v[0]:.3f}", f"{v[1]:.4f}"] for g, v in sorted(gsum.items(), key=lambda kv: -kv[1][0])],
                  ["group", "inputs", "impurity importance (sum)", "permutation importance (sum of single shuffles)"])
order = np.argsort(-np.abs(coef))[:15]
lines += ["", "## 5. Ranking by the lasso (frozen M1)", "",
          "Standardised coefficients: one standard deviation more of the input multiplies the odds of an onset by "
          "the odds ratio, the other inputs held fixed.", ""]
lines += md_table([[i + 1, f"`{lasso['xnames'][j]}`", f"{coef[j]:+.3f}", f"{np.exp(coef[j]):.2f}"] for i, j in enumerate(order)],
                  ["rank", "input", "coefficient per 1 SD", "odds ratio per 1 SD"])
write_md("15_tree_and_importance.md", lines)

fig, axs = plt.subplots(1, 2, figsize=(13, 4.2))
lv = np.array([r["leaves"] for r in rows])
axs[0].plot(lv, [r["train"] for r in rows], color=MUTED, marker="o", markersize=3, label="train (the tree's own fit rows)")
axs[0].errorbar(lv, [r["cv"] for r in rows], yerr=[r["se"] for r in rows], color=SLOT[0], marker="o", markersize=3,
                capsize=2, label="windowing validation (mean of 6, +/- 1 SE)")
for a, c, lab in ((a_min, SLOT[1], "minimum error"), (a_1se, SLOT[2], "one standard error")):
    axs[0].scatter([by_a[a]["leaves"]], [by_a[a]["cv"]], color=c, s=60, zorder=3, label=f"{lab}: {by_a[a]['leaves']:,} leaves")
axs[0].set_xscale("log")
axs[0].set_xlabel("leaves of the tree (log scale)")
axs[0].set_ylabel("PR-AUC")
axs[0].set_title("Pruning one tree: bigger fits the train rows, not later days")
axs[0].legend(fontsize=8)
top = r_perm[:15][::-1]
axs[1].barh(range(len(top)), perm[top], color=SLOT[0], height=0.6)
axs[1].set_yticks(range(len(top)))
axs[1].set_yticklabels([cols[j] for j in top], fontsize=8)
for i, j in enumerate(top):
    axs[1].text(perm[j], i, f"  impurity rank {rank_g[int(j)]}", va="center", fontsize=7, color=INK2)
axs[1].set_xlabel("permutation importance (drop in validation PR-AUC)")
axs[1].set_title("The forest's 15 most important inputs")
axs[1].set_xlim(0, perm[top].max() * 1.35)
axs[1].grid(axis="y", visible=False)
save(fig, "15_tree_and_importance.png")
log("done")
