"""check_lassofit.py - the IRLS + coordinate-descent lasso (lassofit.py) against scikit-learn on 300,000 real fit rows
(train days 16-23 Oct, training roads, the 112 lasso inputs, scaled): saga run to a tight tolerance for two
penalties, lbfgs for no penalty, and sample weights. Writes results/tables/check_lassofit.md.

AI disclosure: drafted with Claude (Anthropic) on 25 Nov 2026; log in AI_USE.md.
"""
from __future__ import annotations

import json
import time
import warnings

import numpy as np
import polars as pl
from sklearn.linear_model import LogisticRegression

import settings as S
from common import log, md_table, write_md
from lassofit import LassoLogit, _eta, _objective, lambda_max
from modeldata import Scaler, feature_list, fold_frames, lasso_matrix, load_rows, with_hist

names = tuple(json.loads((S.TABLES / "04_screen_chosen.json").read_text())["LR"])
df = load_rows(h=S.HORIZON, splits=("train",))
cols = feature_list(df.columns, names)
fit, _ = next(fold_frames(df))
fit = with_hist(fit, fit, lodo=True).sample(300_000, seed=1)
X, xn = lasso_matrix(fit, cols)
X = Scaler(X)(X, inplace=True)
y = fit["y"].to_numpy()
n = len(y)
lmax = lambda_max(X, y)
log(f"{n:,} rows x {X.shape[1]} inputs, {int(y.sum()):,} onsets; lambda_max {lmax:.3e}")
rows = []


def obj(w, b, lam, s=None):
    s = np.ones(n) if s is None else s
    return _objective(_eta(X, w.ravel(), float(b[0])), y.astype(float), s, s.sum(), w.ravel(), lam)


for frac in (0.01, 0.001):
    lam = lmax * frac
    t0 = time.time()
    mine = LassoLogit(lam).fit(X, y)
    t1 = time.time()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sk = LogisticRegression(l1_ratio=1.0, solver="saga", C=1.0 / (lam * n), max_iter=5000, tol=1e-9).fit(X, y)
    t2 = time.time()
    o_m, o_s = obj(mine.coef_, mine.intercept_, lam), obj(sk.coef_, sk.intercept_, lam)
    rows.append([f"lambda_max x {frac}", f"{o_m:.8f}", f"{o_s:.8f}", f"{o_m - o_s:+.1e}",
                 f"{np.abs(mine.coef_ - sk.coef_).max():.1e}", f"{int((mine.coef_ != 0).sum())} / {int((sk.coef_ != 0).sum())}",
                 f"{mine.n_iter_[0]} IRLS, {t1 - t0:.0f} s", f"{sk.n_iter_[0]} epochs, {t2 - t1:.0f} s"])
    assert o_m <= o_s + 1e-7, (o_m, o_s)
    log(rows[-1])
mine = LassoLogit(0.0).fit(X, y)
sk = LogisticRegression(C=np.inf, solver="lbfgs", max_iter=5000, tol=1e-10).fit(X, y)
o_m, o_s = obj(mine.coef_, mine.intercept_, 0.0), obj(sk.coef_, sk.intercept_, 0.0)
pd = np.abs(mine.predict_proba(X)[:, 1] - sk.predict_proba(X)[:, 1]).max()
rows.append(["no penalty (vs lbfgs)", f"{o_m:.8f}", f"{o_s:.8f}", f"{o_m - o_s:+.1e}", f"predictions {pd:.1e}",
             "all / all", f"{mine.n_iter_[0]} IRLS", f"{sk.n_iter_[0]} iterations"])
assert o_m <= o_s + 1e-7
rng = np.random.default_rng(3)
sw = rng.integers(0, 3, n).astype(float)
lam = lmax * 0.003
mine = LassoLogit(lam).fit(X, y, sample_weight=sw)
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    sk = LogisticRegression(l1_ratio=1.0, solver="saga", C=1.0 / (lam * sw.sum()), max_iter=5000, tol=1e-9).fit(X, y, sample_weight=sw)
o_m, o_s = obj(mine.coef_, mine.intercept_, lam, sw), obj(sk.coef_, sk.intercept_, lam, sw)
rows.append(["lambda_max x 0.003, weights 0-2", f"{o_m:.8f}", f"{o_s:.8f}", f"{o_m - o_s:+.1e}",
             f"{np.abs(mine.coef_ - sk.coef_).max():.1e}", f"{int((mine.coef_ != 0).sum())} / {int((sk.coef_ != 0).sum())}",
             f"{mine.n_iter_[0]} IRLS", f"{sk.n_iter_[0]} epochs"])
assert o_m <= o_s + 1e-7
write_md("check_lassofit.md", ["# IRLS + coordinate descent vs scikit-learn (300,000 real fit rows, 112 inputs)", "",
                               "Objective = mean log-loss + lambda x L1 norm (lower is better). Our solver must reach at "
                               "least scikit-learn's objective (asserted).", ""]
         + md_table(rows, ["penalty", "objective (ours)", "objective (scikit-learn)", "difference", "largest coefficient gap",
                           "inputs kept (ours / sklearn)", "ours", "scikit-learn"]))
