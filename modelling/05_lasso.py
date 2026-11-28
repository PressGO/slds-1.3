"""05_lasso.py - M1, lasso logistic regression, on the inputs chosen in 04.

Solver: IRLS + coordinate descent (lassofit.py, the glmnet algorithm; checked against scikit-learn in
check_lassofit.py). saga needed its 200-epoch limit at almost every penalty on these 1.6-4.6 M rows.
Penalty per row fixed across fits: lambda = frac x lambda_max of the final fit rows, warm-started from strong to
weak. Chosen by the mean PR-AUC of the two forward-chaining folds (ties at 4 decimals: the stronger penalty).
Final fit on all train days (training roads); no refit on validation.

AI disclosure: drafted with Claude (Anthropic) on 25 Nov 2026; log in AI_USE.md.
"""
from __future__ import annotations

import json
import pickle

import numpy as np
import polars as pl

import settings as S
from common import ap, f4, log, md_table, write_md
from lassofit import LassoLogit, lambda_max
from modeldata import Scaler, feature_list, fit_logistic, fold_frames, lasso_matrix, load_rows, with_hist
from plotstyle import INK2, MUTED, SLOT, plt, save

names = tuple(json.loads((S.TABLES / "04_screen_chosen.json").read_text())["LR"])
df = load_rows(h=S.HORIZON)
cols = feature_list(df.columns, names)
log(f"lasso inputs: {' + '.join(names)} ({len(cols)} columns before the lasso view)")
fit_all = df.filter((pl.col("split") == "train") & ~pl.col("heldout_road"))
val = df.filter(pl.col("split") == "validate")
del df
if "HIST" in names:
    fit_all, val = with_hist(fit_all, fit_all, lodo=True), with_hist(val, fit_all, lodo=False)
Xf, xnames = lasso_matrix(fit_all, cols)
yf = fit_all["y"].to_numpy()
sc_all = Scaler(Xf)
Xfs = sc_all(Xf, inplace=True)
del Xf
n_all = len(yf)
lmax = lambda_max(Xfs, yf)
lams = {f: f * lmax for f in S.LASSO_FRACS}
log(f"final fit rows {n_all:,} x {Xfs.shape[1]} inputs; lambda_max {lmax:.3e}")


def path(Xs: np.ndarray, y: np.ndarray, Xc=None, yc=None, keep: bool = False):
    """Warm-started path from strong to weak penalty."""
    out, prev = {}, None
    for f in S.LASSO_FRACS:
        m = LassoLogit(lams[f]).fit(Xs, y, coef_init=None if prev is None else prev.coef_,
                                    intercept_init=None if prev is None else prev.intercept_)
        rec = {"nonzero": int((m.coef_ != 0).sum()), "iters": int(m.n_iter_[0]), "coef": m.coef_.ravel().copy(),
               "intercept": float(m.intercept_[0]), "objective": m.objective_}
        if Xc is not None:
            rec["ap"] = ap(yc, m.predict_proba(Xc)[:, 1])
        if keep:
            rec["model"] = m
        out[f] = rec
        prev = m
        log(f"   lambda_max x {f:<7} nonzero {rec['nonzero']:3d}  IRLS steps {rec['iters']:2d}"
            + (f"  PR-AUC {rec['ap']:.4f}" if "ap" in rec else ""))
    return out


# ---- forward-chaining folds ----
cv, plain = [], []
for k, (fit, chk) in enumerate(fold_frames(fit_all)):      # fit_all = train days, training roads
    if "HIST" in names:
        fit, chk = with_hist(fit, fit, lodo=True), with_hist(chk, fit, lodo=False)
    X1, _ = lasso_matrix(fit, cols)
    sc = Scaler(X1)
    X1 = sc(X1, inplace=True)
    X2, _ = lasso_matrix(chk, cols)
    X2 = sc(X2, inplace=True)
    y1, y2 = fit["y"].to_numpy(), chk["y"].to_numpy()
    log(f"fold {k + 1}: fit {len(y1):,} rows, check {len(y2):,}")
    cv.append(path(X1, y1, X2, y2))
    pm = fit_logistic(X1, y1, C=np.inf, l1=False)
    plain.append(ap(y2, pm.predict_proba(X2)[:, 1]))
    log(f"   plain logistic regression (scikit-learn lbfgs): PR-AUC {plain[-1]:.4f}")
    del X1, X2, fit, chk
del fit_all

mean_ap = {f: float(np.mean([cv[0][f]["ap"], cv[1][f]["ap"]])) for f in S.LASSO_FRACS}
best = max(S.LASSO_FRACS, key=lambda f: (round(mean_ap[f], 4), f))      # ties: the stronger penalty (larger lambda)
log(f"chosen penalty: lambda_max x {best} (lambda per row {lams[best]:.3e}), mean CV PR-AUC {mean_ap[best]:.4f}")

# ---- final path on all train days (training roads); M1 = the model at the chosen penalty ----
fin = path(Xfs, yf, keep=True)
m1 = fin[best]["model"]
p_fit = m1.predict_proba(Xfs)[:, 1]
log(f"mean predicted chance on the fit rows {p_fit.mean():.4f} vs base rate {yf.mean():.4f}")
pm_all = fit_logistic(Xfs, yf, C=np.inf, l1=False)
Xv, _ = lasso_matrix(val, cols)
Xvs = sc_all(Xv, inplace=True)
sv, sv_plain = m1.predict_proba(Xvs)[:, 1], pm_all.predict_proba(Xvs)[:, 1]
val.select("LinkID", "t", "date", "heldout_road", "y").with_columns(
    pl.Series("lasso", sv), pl.Series("lr_plain", sv_plain)).write_parquet(S.PREDS / "val_lasso.parquet")
with open(S.MODELS / "lasso.pkl", "wb") as fh:
    pickle.dump({"model": m1, "plain": pm_all, "mu": sc_all.mu, "sd": sc_all.sd, "cols": cols, "xnames": xnames,
                 "groups": names, "frac": best, "lambda_per_row": lams[best], "lambda_max": lmax, "n_fit": n_all}, fh)

# ---- tables and figures ----
lines = ["# M1: lasso logistic regression", "",
         f"Inputs: **{' + '.join(names)}**, lasso view ({len(xnames)} columns: f_slot15 as 16 hour groups, rain as "
         "log(1 + mm)), scaled with the mean and SD of each fit's rows. Solver: IRLS + coordinate descent "
         "(glmnet algorithm, `lassofit.py`; matches or beats scikit-learn's objective in `check_lassofit.md`); the "
         f"intercept is not penalised. Final fit rows: {n_all:,} (train days, training roads, normal now), "
         f"{int(yf.sum()):,} onsets. lambda_max = {lmax:.3e} per row.", "",
         "## Choosing the penalty (forward-chaining inside the train days)", ""]
rows = [[f"x {f}", f"{lams[f]:.2e}", cv[0][f]["nonzero"], cv[1][f]["nonzero"], f4(cv[0][f]["ap"]), f4(cv[1][f]["ap"]),
         ("**" + f4(mean_ap[f]) + "**") if f == best else f4(mean_ap[f])] for f in S.LASSO_FRACS]
rows.append(["no penalty (scikit-learn lbfgs)", "0", len(xnames), len(xnames), f4(plain[0]), f4(plain[1]), f4(np.mean(plain))])
lines += md_table(rows, ["lambda / lambda_max", "lambda per row", "inputs kept, fold 1", "fold 2", "PR-AUC fold 1",
                         "PR-AUC fold 2", "mean"])
lines += ["", f"Chosen: **lambda_max x {best}** (ties at 4 decimals go to the stronger penalty). On all train days it "
              f"keeps **{fin[best]['nonzero']} of {len(xnames)}** inputs. Mean predicted chance on the fit rows "
              f"{p_fit.mean():.4f} vs base rate {yf.mean():.4f}.", "",
          "## Order in which the inputs enter (path on all train days)", ""]
entered, seen = [], set()
for f in S.LASSO_FRACS:
    nz = [xnames[i] for i in np.nonzero(fin[f]["coef"])[0] if xnames[i] not in seen]
    seen |= set(nz)
    entered.append([f"x {f}", fin[f]["nonzero"], ", ".join(f"`{n}`" for n in nz) or "-"])
lines += md_table(entered, ["lambda / lambda_max", "inputs kept", "new inputs at this penalty"])
coef = fin[best]["coef"]
order = np.argsort(-np.abs(coef))
lines += ["", "## Standardised coefficients of M1 (largest 30 by size; per 1 SD of the input)", ""]
lines += md_table([[f"`{xnames[i]}`", f"{coef[i]:+.3f}"] for i in order[:30] if coef[i] != 0], ["input", "coefficient"])
lines += ["", f"Inputs set to exactly 0: {', '.join(f'`{xnames[i]}`' for i in np.nonzero(coef == 0)[0]) or 'none'}."]
main = ~val["heldout_road"].to_numpy()
yv = val["y"].to_numpy()
lines += ["", "## Validation week (scored in 07; quick look)", "",
          f"Training roads: PR-AUC M1 {ap(yv[main], sv[main]):.4f}, plain LR {ap(yv[main], sv_plain[main]):.4f}."]
write_md("05_lasso.md", lines)
(S.TABLES / "05_lasso.json").write_text(json.dumps({"frac": best, "lambda_per_row": lams[best], "lambda_max": lmax,
                                                    "mean_cv": {str(k): v for k, v in mean_ap.items()},
                                                    "plain_cv": plain, "nonzero": fin[best]["nonzero"]}))

top = order[:10]
fig, ax = plt.subplots(figsize=(9, 4.6))
xs = np.array(S.LASSO_FRACS, float)
pal = SLOT + [INK2, MUTED]
for j, i in enumerate(top):
    ax.plot(xs, [fin[f]["coef"][i] for f in S.LASSO_FRACS], color=pal[j % len(pal)], marker="o", markersize=4,
            label=xnames[i], linewidth=1.6)
ax.axvline(best, color=MUTED, linewidth=1)
ax.set_xscale("log")
ax.invert_xaxis()
ax.set_xlabel("lambda / lambda_max (weaker penalty to the right); line = chosen")
ax.set_ylabel("standardised coefficient")
ax.set_title("Lasso path on all train days: the 10 largest inputs of M1")
ax.legend(ncol=2, fontsize=8, loc="upper left", bbox_to_anchor=(1.0, 1.0))
save(fig, "m1_lasso_path.png")
