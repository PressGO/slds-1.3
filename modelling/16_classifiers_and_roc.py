"""16_classifiers_and_roc.py - the course's classification tools on our data (notes ch. 4, 6, 7): logistic
regression's quality of fit (deviance, AIC), ridge and elastic net against the lasso, LDA and QDA, and for every
score the ROC curve, AUC and confusion matrix; thresholds from unequal costs (28 Nov).

RULES, FIXED BEFORE THE RUN (28 Nov, before any result of this script was seen):
- Quality of fit: plain logistic regression (no penalty) on all train rows (training roads) for the nested input sets
  BASE, + NORM, + HOP, + HIST: null and residual deviance, AIC = deviance + 2 x (independent columns + 1); on the
  validation week the deviance per row, PR-AUC and ROC-AUC.
- Penalties, on the windowing validation W6 (4 train days, then 2 days at a time): ridge with lambda2 = 1e-1, 1e-2,
  1e-4 per row; elastic net with equal lasso and ridge parts, each at lambda / lambda_max = 0.1, 0.01, 0.0003.
  Same solver family as the lasso (IRLS; coordinate descent or a direct solve). Lasso: 14_validation_windows.py.
- LDA and QDA on the lasso view of the 96 inputs (scaled; the reference hour and day columns dropped): class means and
  covariances from every onset + 10% of the other fit rows, class priors from all fit rows. QDA with reg_param 0.01
  (some inputs are constant or collinear inside a class). W6, then all train rows -> the validation week.
- ROC, AUC and confusion matrices on the validation week (training roads) for B1, B2, lasso, forest, the two pruned
  trees of 15_tree_and_importance.py, LDA and QDA: at the top 2% of links per update (our operating rule); and for
  the forest's calibrated probability (cross-fitted by day) at the thresholds 1 / (1 + r), which minimise the
  expected cost when a missed onset costs r false alarms (r = 1 is the 0-1 loss, threshold 0.5; then r = 5, 10,
  20, 50).
Train and validation days only; the test week is not read.

Run (from modelling/, after 14 and 15; about 10 min):
    systemd-run --user --scope -q -p MemoryMax=14G nice -n 10 python 16_classifiers_and_roc.py

AI disclosure: drafted with Claude (Anthropic) on 28 Nov 2026; log in AI_USE.md.
"""
from __future__ import annotations

import json
import pickle
import warnings

import numpy as np
import polars as pl
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis, QuadraticDiscriminantAnalysis
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, roc_curve

import settings as S
from common import alerts_at_share, ap, between, log, md_table, write_md
from lassofit import CHUNK, _eta
from modeldata import Scaler, feature_list, fit_logistic, lasso_matrix, load_rows, neg_subsample, with_hist
from plotstyle import INK2, MUTED, SLOT, plt, save

NAMES = tuple(json.loads((S.TABLES / "04_screen_chosen.json").read_text())["RF"])
LASSO = pickle.load(open(S.MODELS / "lasso.pkl", "rb"))
LMAX = LASSO["lambda_max"]
RIDGE = (1e-1, 1e-2, 1e-4)
ENET = (0.1, 0.01, 0.0003)
START_DAYS, STEP_DAYS, SHARE = 4, 2, 0.02
COSTS = (1, 5, 10, 20, 50)

df = load_rows(h=S.HORIZON)
raw_fit = df.filter((pl.col("split") == "train") & ~pl.col("heldout_road"))
val = df.filter(pl.col("split") == "validate")
del df
fit_all, val = with_hist(raw_fit, raw_fit, lodo=True), with_hist(val, raw_fit, lodo=False)
cols = feature_list(fit_all.columns, NAMES)
DAYS = sorted(fit_all["date"].unique().to_list())
W6 = [((DAYS[0], DAYS[i - 1]), (DAYS[i], DAYS[i + STEP_DAYS - 1])) for i in range(START_DAYS, len(DAYS), STEP_DAYS)]
assert len(DAYS) == 16 and len(W6) == 6 and val["date"].max() <= S.LAST_OPEN_DAY
yf, yv = fit_all["y"].to_numpy(), val["y"].to_numpy()
main = ~val["heldout_road"].to_numpy()
log(f"fit rows {len(yf):,}; validation rows {len(yv):,} ({int(main.sum()):,} on the training roads)")


def loglik(y: np.ndarray, p: np.ndarray) -> float:
    p = np.clip(p, 1e-15, 1 - 1e-15)
    return float(np.sum(np.where(y, np.log(p), np.log(1 - p))))


def proba(m, X: np.ndarray) -> np.ndarray:
    return np.concatenate([m.predict_proba(X[i:i + CHUNK])[:, 1] for i in range(0, len(X), CHUNK)])


# ---------------------------------------------------------------- A. quality of fit: deviance and AIC
n, ybar = len(yf), float(yf.mean())
null_dev = -2.0 * n * (ybar * np.log(ybar) + (1 - ybar) * np.log(1 - ybar))
nv = int(main.sum())
yb_v = float(yv[main].mean())
fit_rows = []
for names in (("BASE",), ("BASE", "NORM"), ("BASE", "NORM", "HOP"), ("BASE", "NORM", "HOP", "HIST")):
    c = feature_list(fit_all.columns, names)
    Xf, xn = lasso_matrix(fit_all, c)
    sc = Scaler(Xf)
    Xf = sc(Xf, inplace=True)
    G = np.zeros((Xf.shape[1], Xf.shape[1]))
    for i in range(0, n, CHUNK):
        Xc = Xf[i:i + CHUNK].astype(np.float64)
        G += Xc.T @ Xc
    ev = np.linalg.eigvalsh(G / n)
    rank = int((ev > 1e-6 * ev.max()).sum())
    m = fit_logistic(Xf, yf, C=np.inf, l1=False)
    dev = -2.0 * loglik(yf, proba(m, Xf))
    Xv, _ = lasso_matrix(val, c)
    pv = proba(m, sc(Xv, inplace=True))[main]
    fit_rows.append({"inputs": " + ".join(names), "columns": Xf.shape[1], "k": rank + 1, "deviance": dev,
                     "aic": dev + 2 * (rank + 1), "val_dev": -2.0 * loglik(yv[main], pv) / nv,
                     "val_ap": ap(yv[main], pv), "val_roc": float(roc_auc_score(yv[main], pv))})
    log(f"logistic {fit_rows[-1]['inputs']}: deviance {dev:,.0f}, AIC {fit_rows[-1]['aic']:,.0f}, "
        f"validation PR-AUC {fit_rows[-1]['val_ap']:.4f}")
    if len(names) == 4:                                   # the frozen lasso on the same rows and columns
        assert xn == LASSO["xnames"]
        pl_ = LASSO["model"].predict_proba(Xf)[:, 1]
        lasso_fit = {"deviance": -2.0 * loglik(yf, pl_), "nonzero": int((LASSO["model"].coef_ != 0).sum())}
    del Xf, Xv
val_null_dev = -2.0 * (yb_v * np.log(yb_v) + (1 - yb_v) * np.log(1 - yb_v))


# ---------------------------------------------------------------- B. ridge and elastic net on the windows
class ENLogit:
    """Logistic regression with the penalty l1 * |w|_1 + (l2 / 2) * |w|^2 per row (intercept not penalised), by the
    same IRLS scheme as lassofit.LassoLogit; the inner problem by coordinate descent, or a direct solve when l1 = 0."""

    def __init__(self, l1: float, l2: float, tol: float = 1e-9, max_iter: int = 60):
        self.l1, self.l2, self.tol, self.max_iter = float(l1), float(l2), tol, max_iter

    def _obj(self, eta, y, n_, w):
        return float(np.sum(np.logaddexp(0.0, eta) - y * eta) / n_ + self.l1 * np.abs(w).sum()
                     + 0.5 * self.l2 * float(w @ w))

    def _inner(self, G, c, w):
        if self.l1 == 0.0:
            return np.linalg.solve(G + self.l2 * np.eye(len(c)), c)
        d = np.diag(G).copy()
        Gw = G @ w
        for _ in range(20000):
            biggest = 0.0
            for j in range(len(c)):
                den = d[j] + self.l2
                if den <= 0:
                    continue
                r = c[j] - Gw[j] + d[j] * w[j]
                new = np.sign(r) * max(abs(r) - self.l1, 0.0) / den
                delta = new - w[j]
                if delta != 0.0:
                    Gw += G[:, j] * delta
                    w[j] = new
                    biggest = max(biggest, abs(delta) * np.sqrt(den))
            if biggest < 1e-12:
                break
        return w

    def fit(self, X, y, coef_init=None, intercept_init=None):
        y = np.asarray(y, np.float64)
        n_, p = len(y), X.shape[1]
        w = np.zeros(p) if coef_init is None else np.array(coef_init, np.float64).ravel().copy()
        yb = float(y.mean())
        b = float(np.log(yb / (1 - yb))) if intercept_init is None else float(intercept_init)
        eta = _eta(X, w, b)
        obj = self._obj(eta, y, n_, w)
        for _ in range(self.max_iter):
            pr = 1.0 / (1.0 + np.exp(-eta))
            v = np.maximum(pr * (1 - pr), 1e-6)
            z = eta + (y - pr) / v
            G, xw, xz = np.zeros((p, p)), np.zeros(p), np.zeros(p)
            for i in range(0, n_, CHUNK):
                Xc, vc = X[i:i + CHUNK].astype(np.float64), v[i:i + CHUNK]
                G += (Xc * vc[:, None]).T @ Xc
                xw += vc @ Xc
                xz += (vc * z[i:i + CHUNK]) @ Xc
            G, xw, xz = G / n_, xw / n_, xz / n_
            sw = v.sum() / n_
            zbar, xbar = (v * z).sum() / n_ / sw, xw / sw
            w_new = self._inner(G - sw * np.outer(xbar, xbar), xz - sw * xbar * zbar, w.copy())
            b_new = zbar - xbar @ w_new
            step = 1.0
            while True:                                   # never accept a step that raises the objective
                w_try, b_try = w + step * (w_new - w), b + step * (b_new - b)
                eta_try = _eta(X, w_try, b_try)
                obj_try = self._obj(eta_try, y, n_, w_try)
                if obj_try <= obj + 1e-15 or step < 1e-4:
                    break
                step /= 2
            change = max(np.abs(w_try - w).max(initial=0.0), abs(b_try - b))
            w, b, eta = w_try, b_try, eta_try
            done = abs(obj - obj_try) <= self.tol * max(1.0, abs(obj)) or change < 1e-7
            obj = obj_try
            if done:
                break
        self.coef_, self.intercept_ = w, b
        return self

    def predict(self, X):
        return 1.0 / (1.0 + np.exp(-_eta(X, self.coef_, self.intercept_)))


def lda_qda(fit: pl.DataFrame, seed: int):
    """Class means and covariances from every onset + 10% of the other fit rows; priors from all fit rows."""
    X1, xn = lasso_matrix(fit, cols)
    sc = Scaler(X1)
    X1 = sc(X1, inplace=True)
    keep = [i for i, name in enumerate(xn) if name not in ("x_hour06", "f_mon")]
    y1 = fit["y"].to_numpy()
    pri = [1.0 - float(y1.mean()), float(y1.mean())]
    i1 = neg_subsample(y1, S.RF_NEG_KEEP, seed)
    Xa, ya = X1[i1][:, keep].astype(np.float64), y1[i1]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        lda = LinearDiscriminantAnalysis(solver="lsqr", priors=pri).fit(Xa, ya)
        qda = QuadraticDiscriminantAnalysis(priors=pri, reg_param=0.01).fit(Xa, ya)

    def score(frame: pl.DataFrame):
        X2, _ = lasso_matrix(frame, cols)
        X2 = sc(X2, inplace=True)
        out = {"lda": [], "qda": []}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for i in range(0, len(X2), CHUNK):
                Xc = X2[i:i + CHUNK][:, keep].astype(np.float64)
                out["lda"].append(lda.predict_proba(Xc)[:, 1])
                out["qda"].append(qda.predict_proba(Xc)[:, 1])
        return {k_: np.nan_to_num(np.concatenate(v), nan=0.0) for k_, v in out.items()}
    return score


win: dict[str, list] = {}
ys_w = []
for k, ((a0, b0), (c0, e0)) in enumerate(W6):
    fit, chk = raw_fit.filter(between("date", a0, b0)), raw_fit.filter(between("date", c0, e0))
    fit, chk = with_hist(fit, fit, lodo=True), with_hist(chk, fit, lodo=False)
    y1, y2 = fit["y"].to_numpy(), chk["y"].to_numpy()
    ys_w.append(y2)
    X1, _ = lasso_matrix(fit, cols)
    sc = Scaler(X1)
    X1 = sc(X1, inplace=True)
    X2, _ = lasso_matrix(chk, cols)
    X2 = sc(X2, inplace=True)
    prev = None
    for l2 in RIDGE:                                      # strong to weak, warm-started
        prev = ENLogit(0.0, l2).fit(X1, y1, None if prev is None else prev.coef_, None if prev is None else prev.intercept_)
        win.setdefault(f"ridge|{l2:g}", []).append(prev.predict(X2))
    prev = None
    for f in ENET:
        prev = ENLogit(f * LMAX, f * LMAX).fit(X1, y1, None if prev is None else prev.coef_, None if prev is None else prev.intercept_)
        win.setdefault(f"enet|{f:g}", []).append(prev.predict(X2))
        win.setdefault(f"enet_nz|{f:g}", []).append(int((prev.coef_ != 0).sum()))
    del X1, X2
    for name, p in lda_qda(fit, S.SEED + k)(chk).items():
        win.setdefault(name, []).append(p)
    log(f"window {k + 1}: ridge 1e-4 {ap(y2, win['ridge|0.0001'][-1]):.4f}, elastic net x0.0003 "
        f"{ap(y2, win['enet|0.0003'][-1]):.4f}, LDA {ap(y2, win['lda'][-1]):.4f}, QDA {ap(y2, win['qda'][-1]):.4f}")
    del fit, chk


def wsum(key: str) -> dict:
    aps = [ap(y, p) for y, p in zip(ys_w, win[key])]
    return {"windows": aps, "mean": float(np.mean(aps)), "se": float(np.std(aps, ddof=1) / np.sqrt(len(aps))),
            "pooled": ap(np.concatenate(ys_w), np.concatenate(win[key]))}


pen = {k_: wsum(k_) for k_ in win if not k_.startswith("enet_nz")}
for f in ENET:
    pen[f"enet|{f:g}"]["inputs"] = win[f"enet_nz|{f:g}"]
cv14 = S.TABLES / "14_validation_windows.json"
lasso_w6 = json.loads(cv14.read_text()).get("lasso", {}).get("W6") if cv14.exists() else None

# ---------------------------------------------------------------- C. LDA and QDA on all train rows -> validation week
final_da = lda_qda(fit_all, S.SEED)(val)
log(f"LDA validation PR-AUC {ap(yv[main], final_da['lda'][main]):.4f}; QDA {ap(yv[main], final_da['qda'][main]):.4f}")

# ---------------------------------------------------------------- D. ROC, AUC, confusion matrices (validation week)
v = val.select("LinkID", "t", "date", "heldout_road", "y").with_columns(
    pl.Series("lda", final_da["lda"]), pl.Series("qda", final_da["qda"]))
for fname, pick in (("val_baselines", ["b1", "b2"]), ("val_lasso", ["lasso"]), ("val_rf", ["rf_raw"]),
                    ("val_tree", ["tree_min", "tree_1se"])):
    v = v.join(pl.read_parquet(S.PREDS / f"{fname}.parquet").select("LinkID", "t", *pick), on=["LinkID", "t"],
               how="left", maintain_order="left")
v.select("LinkID", "t", "heldout_road", "y", "lda", "qda").write_parquet(S.PREDS / "val_lda_qda.parquet")
m_ = v.filter(~pl.col("heldout_road"))
SC = {"B1 time-of-week rate": "b1", "B2 last observation": "b2", "pruned tree (one-standard-error rule)": "tree_1se",
      "pruned tree (minimum-error rule)": "tree_min", "LDA": "lda", "QDA": "qda", "M1 lasso": "lasso",
      "M2 random forest": "rf_raw"}
assert all(m_[c].null_count() == 0 for c in SC.values()), {c: m_[c].null_count() for c in SC.values()}
y, t = m_["y"].to_numpy(), m_["t"].to_numpy()
vdays = sorted(m_["date"].unique().to_list())
di = m_["date"].replace_strict({d_: i for i, d_ in enumerate(vdays)}, return_dtype=pl.Int64).to_numpy()
N, P = len(y), int(y.sum())
perf = {}
for lab, c in SC.items():
    s = m_[c].to_numpy().astype(float)
    a = alerts_at_share(t, s, SHARE)
    tp, fp = int((a & y).sum()), int((a & ~y).sum())
    fn, tn = P - tp, N - P - fp
    perf[lab] = {"pr_auc": ap(y, s), "roc_auc": float(roc_auc_score(y, s)),
                 "roc_days": [float(roc_auc_score(y[di == i], s[di == i])) for i in range(len(vdays))],
                 "tp": tp, "fp": fp, "fn": fn, "tn": tn, "sens": tp / P, "spec": tn / (N - P),
                 "prec": tp / max(1, tp + fp), "acc": (tp + tn) / N}
    log(f"{lab}: PR-AUC {perf[lab]['pr_auc']:.4f}, ROC-AUC {perf[lab]['roc_auc']:.4f}")


def logit(p):
    p = np.clip(np.asarray(p, float), 1e-7, 1 - 1e-7)
    return np.log(p / (1 - p))


rf_raw = m_["rf_raw"].to_numpy()
p_cal = np.empty(N)
for i in range(len(vdays)):                               # the Platt map fitted on 3 days, applied to the 4th
    k_ = di == i
    mm = LogisticRegression(C=np.inf, solver="lbfgs").fit(logit(rf_raw[~k_]).reshape(-1, 1), y[~k_])
    p_cal[k_] = mm.predict_proba(logit(rf_raw[k_]).reshape(-1, 1))[:, 1]
rf2 = perf["M2 random forest"]
cost_rows = []
for r in COSTS:
    thr = 1.0 / (1.0 + r)
    a = p_cal > thr
    tp, fp = int((a & y).sum()), int((a & ~y).sum())
    fn = P - tp
    cost_rows.append({"r": r, "threshold": thr, "alerts": int(a.sum()), "per_update": a.sum() / (len(vdays) * 192),
                      "tp": tp, "fp": fp, "fn": fn, "sens": tp / P, "spec": (N - P - fp) / (N - P),
                      "prec": tp / max(1, tp + fp), "cost": (fp + r * fn) / N * 1000,
                      "cost_never": r * P / N * 1000, "cost_share": (rf2["fp"] + r * rf2["fn"]) / N * 1000})

out = {"fit": fit_rows, "null_deviance": null_dev, "lasso_fit": lasso_fit, "penalties": pen, "perf": perf,
       "costs": cost_rows, "val_null_dev_per_row": val_null_dev}
(S.TABLES / "16_classifiers_and_roc.json").write_text(json.dumps(out, indent=1))

# ---------------------------------------------------------------- tables
lines = ["# The course's classification tools on our data (28 Nov)", "",
         "Train and validation days only; the test week is not read. Rules fixed in the script header before the run.", "",
         "## 1. Logistic regression: quality of fit (deviance and AIC)", "",
         f"Plain logistic regression (no penalty) on the {n:,} train rows of the training roads. Null deviance (intercept "
         f"only): {null_dev:,.0f}. AIC = residual deviance + 2 x (independent columns + 1); smaller is better. "
         f"Validation deviance per row of the intercept-only model: {val_null_dev:.5f}.", ""]
lines += md_table([[r["inputs"], r["columns"], r["k"], f"{r['deviance']:,.0f}", f"{1 - r['deviance'] / null_dev:.1%}",
                    f"{r['aic']:,.0f}", f"{r['val_dev']:.5f}", f"{r['val_ap']:.4f}", f"{r['val_roc']:.3f}"] for r in fit_rows],
                  ["inputs", "columns", "parameters", "residual deviance", "deviance explained", "AIC",
                   "validation deviance per row", "validation PR-AUC", "validation ROC-AUC"])
lines += ["", f"The frozen lasso (M1) on the same rows: residual deviance {lasso_fit['deviance']:,.0f} with "
              f"{lasso_fit['nonzero']} non-zero coefficients, against {fit_rows[-1]['deviance']:,.0f} for the unpenalised "
              "fit: with 4.6 M rows the penalty costs almost nothing in fit.",
          "The rows are not independent (a link's updates 5 minutes apart), so the deviance and AIC differences are "
          "far larger than what a formal test could trust; the held-out columns are the evidence we rely on.", "",
          "## 2. Lasso, ridge and elastic net (windowing validation W6: 4 days, then 2 days at a time)", ""]
prow = []
if lasso_w6:
    for f in (0.1, 0.01, 0.001, 0.0003):
        r = lasso_w6[str(f)]
        prow.append([f"lasso, lambda / lambda_max = {f:g}", " / ".join(str(i) for i in r["inputs"]), f"{r['mean']:.4f}",
                     f"{r['se']:.4f}", f"{r['pooled']:.4f}"])
for f in ENET:
    r = pen[f"enet|{f:g}"]
    prow.append([f"elastic net, each part = {f:g}", " / ".join(str(i) for i in r["inputs"]), f"{r['mean']:.4f}",
                 f"{r['se']:.4f}", f"{r['pooled']:.4f}"])
for l2 in RIDGE:
    r = pen[f"ridge|{l2:g}"]
    prow.append([f"ridge, lambda2 = {l2:g}", "all", f"{r['mean']:.4f}", f"{r['se']:.4f}", f"{r['pooled']:.4f}"])
for k_, lab in (("lda", "LDA"), ("qda", "QDA (reg_param 0.01)")):
    prow.append([lab, "all", f"{pen[k_]['mean']:.4f}", f"{pen[k_]['se']:.4f}", f"{pen[k_]['pooled']:.4f}"])
lines += md_table(prow, ["model", "inputs kept per window", "mean of the 6 windows", "standard error", "pooled PR-AUC"])
lines += ["", "## 3. Every score on the validation week: PR-AUC, ROC-AUC, and the confusion matrix at our operating rule", "",
          f"Training roads: {N:,} rows that are normal now, {P:,} onsets (onset rate {P / N:.4f}). Alerts = the top 2% of "
          "links at each update. Sensitivity = share of onsets alerted (recall); specificity = share of non-onsets "
          "not alerted; accuracy = share of rows classified correctly. A rule that never alerts has accuracy "
          f"{1 - P / N:.4f}.", ""]
lines += md_table([[lab, f"{p['pr_auc']:.4f}", f"{p['roc_auc']:.3f} ({min(p['roc_days']):.3f}-{max(p['roc_days']):.3f})",
                    f"{p['tp']:,}", f"{p['fp']:,}", f"{p['fn']:,}", f"{p['tn']:,}", f"{p['sens']:.3f}", f"{p['spec']:.4f}",
                    f"{p['prec']:.3f}", f"{p['acc']:.4f}"] for lab, p in perf.items()],
                  ["score", "PR-AUC", "ROC-AUC (lowest-highest day)", "TP", "FP", "FN", "TN", "sensitivity",
                   "specificity", "precision", "accuracy"])
lines += ["", "## 4. Thresholds from unequal costs (the forest's calibrated probability)", "",
          "If a missed onset costs r false alarms, the expected cost is lowest when we alert on p > 1 / (1 + r) "
          "(notes, section 4.5). r = 1 is the 0-1 loss with the threshold 0.5. Probabilities: the forest's, "
          "calibrated on 3 validation days and applied to the 4th. Cost = (false alarms + r x missed onsets) per "
          "1,000 rows.", ""]
lines += md_table([[r["r"], f"{r['threshold']:.3f}", f"{r['alerts']:,}", f"{r['per_update']:.1f}", f"{r['sens']:.3f}",
                    f"{r['spec']:.4f}", f"{r['prec']:.3f}", f"{r['cost']:.2f}", f"{r['cost_share']:.2f}",
                    f"{r['cost_never']:.2f}"] for r in cost_rows],
                  ["r", "threshold", "alerts", "alerts per update", "sensitivity", "specificity", "precision",
                   "cost with this threshold", "cost of the top-2% rule", "cost of never alerting"])
write_md("16_classifiers_and_roc.md", lines)

# ---------------------------------------------------------------- figure
PAL = {"b1": MUTED, "b2": INK2, "tree_1se": SLOT[3], "lda": SLOT[4], "qda": SLOT[5], "lasso": SLOT[1], "rf_raw": SLOT[0]}
fig, axs = plt.subplots(1, 2, figsize=(13, 4.6))
for lab, c in SC.items():
    if c == "tree_min":
        continue
    fpr, tpr, _ = roc_curve(y, m_[c].to_numpy().astype(float))
    for ax in axs:
        ax.plot(fpr, tpr, color=PAL[c], linewidth=1.5, label=f"{lab} ({perf[lab]['roc_auc']:.3f})")
for ax in axs:
    ax.plot([0, 1], [0, 1], color=MUTED, linestyle=":", linewidth=1)
    ax.set_xlabel("false positive rate (1 - specificity)")
    ax.set_ylabel("true positive rate (sensitivity)")
axs[0].set_title("ROC curves, validation week (AUC in brackets)")
axs[0].legend(fontsize=8, loc="lower right")
axs[1].set_xlim(0, 0.05)
axs[1].set_ylim(0, 0.7)
axs[1].scatter([1 - rf2["spec"]], [rf2["sens"]], color=SLOT[0], s=40, zorder=3)
axs[1].annotate("forest, top 2% of links", (1 - rf2["spec"], rf2["sens"]), textcoords="offset points", xytext=(8, -4), fontsize=8)
axs[1].set_title("The same curves where the alerts are (false positive rate under 5%)")
save(fig, "16_roc.png")
log("done")
