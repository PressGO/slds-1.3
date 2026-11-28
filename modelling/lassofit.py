"""lassofit.py - lasso logistic regression by IRLS + coordinate descent (the glmnet algorithm: Friedman, Hastie and
Tibshirani 2010, J. Stat. Software 33(1)), for many rows and ~100 inputs.

Objective (the same as scikit-learn's with C = 1 / (lam * n)):
    (1 / n) * sum_i s_i * [log(1 + exp(eta_i)) - y_i * eta_i]  +  lam * ||w||_1,   eta = b + X w,  n = sum_i s_i
The intercept b is not penalised. Each outer step solves the weighted least-squares approximation on the p x p
weighted Gram matrix (float64, built in chunks) by coordinate descent; a step that does not lower the objective is
halved (backtracking). Checked against scikit-learn's saga at a tight tolerance in check_lassofit.py.

AI disclosure: drafted with Claude (Anthropic) on 25 Nov 2026; log in AI_USE.md.
"""
from __future__ import annotations

import numpy as np

CHUNK = 400_000


def _eta(X: np.ndarray, w: np.ndarray, b: float) -> np.ndarray:
    out = np.empty(X.shape[0])
    w32 = w.astype(np.float64)
    for i in range(0, X.shape[0], CHUNK):
        out[i:i + CHUNK] = X[i:i + CHUNK].astype(np.float64) @ w32
    return out + b


def _objective(eta, y, s, n, w, lam):
    return float(np.sum(s * (np.logaddexp(0.0, eta) - y * eta)) / n + lam * np.abs(w).sum())


def _cd(G: np.ndarray, c: np.ndarray, lam: float, w: np.ndarray, tol: float = 1e-12, max_sweeps: int = 20000):
    """min 0.5 w'Gw - c'w + lam |w|_1 by cyclic coordinate descent (G positive semi-definite)."""
    d = np.diag(G).copy()
    Gw = G @ w
    for _ in range(max_sweeps):
        biggest = 0.0
        for j in range(len(c)):
            if d[j] <= 0:
                continue
            r = c[j] - Gw[j] + d[j] * w[j]
            new = np.sign(r) * max(abs(r) - lam, 0.0) / d[j]
            delta = new - w[j]
            if delta != 0.0:
                Gw += G[:, j] * delta
                w[j] = new
                biggest = max(biggest, abs(delta) * np.sqrt(d[j]))
        if biggest < tol:
            break
    return w


class LassoLogit:
    def __init__(self, lam: float, tol: float = 1e-9, max_iter: int = 60):
        self.lam, self.tol, self.max_iter = float(lam), tol, max_iter

    def fit(self, X: np.ndarray, y: np.ndarray, sample_weight=None, coef_init=None, intercept_init=None):
        y = np.asarray(y, np.float64)
        s = np.ones_like(y) if sample_weight is None else np.asarray(sample_weight, np.float64)
        n = s.sum()
        p = X.shape[1]
        w = np.zeros(p) if coef_init is None else np.array(coef_init, np.float64).ravel().copy()
        ybar = float((s * y).sum() / n)
        b = float(np.log(ybar / (1 - ybar))) if intercept_init is None else float(np.ravel(intercept_init)[0])
        eta = _eta(X, w, b)
        obj = _objective(eta, y, s, n, w, self.lam)
        self.path_obj_ = [obj]
        for it in range(1, self.max_iter + 1):
            pr = 1.0 / (1.0 + np.exp(-eta))
            Wt = s * np.maximum(pr * (1 - pr), 1e-6)
            z = eta + (y - pr) / np.maximum(pr * (1 - pr), 1e-6)
            G = np.zeros((p, p))
            xw = np.zeros(p)
            xz = np.zeros(p)
            for i in range(0, X.shape[0], CHUNK):
                Xc = X[i:i + CHUNK].astype(np.float64)
                wc = Wt[i:i + CHUNK]
                G += (Xc * wc[:, None]).T @ Xc
                xw += wc @ Xc
                xz += (wc * z[i:i + CHUNK]) @ Xc
            G /= n
            xw /= n
            xz /= n
            sW = Wt.sum() / n
            zbar = (Wt * z).sum() / n / sW
            xbar = xw / sW
            Gc = G - sW * np.outer(xbar, xbar)
            cc = xz - sW * xbar * zbar
            w_new = _cd(Gc, cc, self.lam, w.copy())
            b_new = zbar - xbar @ w_new
            step = 1.0
            while True:                               # backtracking: never accept a step that raises the objective
                w_try = w + step * (w_new - w)
                b_try = b + step * (b_new - b)
                eta_try = _eta(X, w_try, b_try)
                obj_try = _objective(eta_try, y, s, n, w_try, self.lam)
                if obj_try <= obj + 1e-15 or step < 1e-4:
                    break
                step /= 2
            change = max(np.abs(w_try - w).max(initial=0.0), abs(b_try - b))
            w, b, eta = w_try, b_try, eta_try
            done = abs(obj - obj_try) <= self.tol * max(1.0, abs(obj)) or change < 1e-7
            obj = obj_try
            self.path_obj_.append(obj)
            if done:
                break
        self.coef_ = w.reshape(1, -1)
        self.intercept_ = np.array([b])
        self.n_iter_ = np.array([it])
        self.objective_ = obj
        self.classes_ = np.array([False, True])
        return self

    def decision_function(self, X: np.ndarray) -> np.ndarray:
        return _eta(X, self.coef_.ravel(), float(self.intercept_[0]))

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        p1 = 1.0 / (1.0 + np.exp(-self.decision_function(X)))
        return np.column_stack([1 - p1, p1])


def lambda_max(X: np.ndarray, y: np.ndarray) -> float:
    """The smallest lambda at which every coefficient is 0 (intercept = logit of the mean)."""
    r = np.asarray(y, np.float64) - np.mean(y)
    g = np.zeros(X.shape[1])
    for i in range(0, X.shape[0], CHUNK):
        g += r[i:i + CHUNK] @ X[i:i + CHUNK].astype(np.float64)
    return float(np.abs(g).max() / X.shape[0])
