"""modeldata.py - model rows, feature groups, the HIST encoding, the lasso and forest fitting helpers.

AI disclosure: drafted with Claude (Anthropic) on 25 Nov 2026; log in AI_USE.md.
"""
from __future__ import annotations

import math
import warnings

import numpy as np
import polars as pl
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.svm import l1_min_c

import features as F
import settings as S
from common import ID_COLS, assert_closed, base_inputs, between

B1_M = 48   # chosen by forward-chaining in 03_baselines.py


# ------------------------------------------------------------------------------------------------ rows

def load_rows(h: int = 15, splits=("train", "validate"), source=None, fe_path=None, label: str = "y",
              closed: bool = True) -> pl.DataFrame:
    """Onset rows (U == False) with the 53 build inputs, the engineered columns and the derived NORM inputs."""
    source = source or S.TRAIN
    fe_path = fe_path or (S.WORK / "fe_trainval.parquet")
    cols = ID_COLS + base_inputs()
    lf = pl.scan_parquet(source).filter(pl.col("split").is_in(list(splits)) & ~pl.col("U"))
    df = lf.select(cols).collect()
    if closed:
        assert_closed(df)
    fe = pl.scan_parquet(fe_path).join(df.lazy().select("LinkID", "t"), on=["LinkID", "t"], how="semi").collect()
    out = df.join(fe, on=["LinkID", "t"], how="left", maintain_order="left")
    assert out.height == df.height and out["fe_norm_p0"].null_count() == 0
    return F.add_derived(out, h).sort("LinkID", "t")


def rows_horizon(h: int, full_path=None, fe_path=None, splits=("train", "validate"), closed: bool = True,
                 onset_only: bool = True) -> pl.DataFrame:
    """Rows for horizon h from a full table: weekdays, inputs known, y_h known (U == False unless onset_only=False).

    For h = 15 these are exactly the rows of train.parquet / test.parquet (checked in 08 and 10)."""
    full_path = full_path or S.FULL
    fe_path = fe_path or (S.WORK / "fe_trainval.parquet")
    core = base_inputs(with_conn=False)
    lab = "y" if h == S.HORIZON else f"y_h{h}"
    cond = (pl.col("in_population") & pl.col("split").is_in(list(splits)) & pl.col(lab).is_not_null()
            & pl.col("U").is_not_null() & pl.all_horizontal([pl.col(c).is_not_null() for c in core]))
    if onset_only:
        cond = cond & ~pl.col("U")
    df = (pl.scan_parquet(full_path).filter(cond)
            .select([c for c in ID_COLS if c != "y"] + [pl.col(lab).alias("y")] + base_inputs()).collect())
    if closed:
        assert_closed(df)
    fe = pl.scan_parquet(fe_path).join(df.lazy().select("LinkID", "t"), on=["LinkID", "t"], how="semi").collect()
    out = df.join(fe, on=["LinkID", "t"], how="left", maintain_order="left")
    assert out.height == df.height and out["fe_norm_p0"].null_count() == 0
    return F.add_derived(out, h).sort("LinkID", "t")


def groups(cols: list[str], h: int = 15) -> dict[str, list[str]]:
    return {"BASE": [c for c in cols if c.startswith("f_")],
            "NORM": F.norm_group(h),
            "HOP": F.hop_columns(cols),
            "HIST": ["x_b1"]}


def feature_list(cols: list[str], names: tuple[str, ...], h: int = 15, drop: tuple[str, ...] = ()) -> list[str]:
    g = groups(cols, h)
    out = [c for n in names for c in g[n]]
    return [c for c in out if not c.startswith(drop)] if drop else out


# ------------------------------------------------------------------------------------------------ HIST

def b1_tables(fit: pl.DataFrame, label: str = "y"):
    """Counts per link x slot x day and per slot x day, from training-road rows only."""
    f = fit.filter(~pl.col("heldout_road"))
    cell = f.group_by("LinkID", "f_slot15", "date").agg(pl.col(label).sum().alias("on"), pl.len().alias("n"))
    slot = f.group_by("f_slot15", "date").agg(pl.col(label).sum().alias("son"), pl.len().alias("sn"))
    return cell, slot


def b1_encode(rows: pl.DataFrame, fit: pl.DataFrame, m: float = B1_M, label: str = "y", lodo: bool = False) -> np.ndarray:
    """The B1 rate as an input. lodo=True for the fit rows themselves: each day's value leaves that day out,
    so a row's own label never enters its own input. Held-out roads get the slot rate only."""
    cell, slot = b1_tables(fit, label)
    ctot = cell.group_by("LinkID", "f_slot15").agg(pl.col("on").sum().alias("on_t"), pl.col("n").sum().alias("n_t"))
    stot = slot.group_by("f_slot15").agg(pl.col("son").sum().alias("son_t"), pl.col("sn").sum().alias("sn_t"))
    j = (rows.select("LinkID", "f_slot15", "date", "heldout_road")
             .join(ctot, on=["LinkID", "f_slot15"], how="left", maintain_order="left")
             .join(stot, on="f_slot15", how="left", maintain_order="left"))
    if lodo:
        j = (j.join(cell, on=["LinkID", "f_slot15", "date"], how="left", maintain_order="left")
              .join(slot, on=["f_slot15", "date"], how="left", maintain_order="left"))
    else:
        j = j.with_columns(pl.lit(0).alias("on"), pl.lit(0).alias("n"), pl.lit(0).alias("son"), pl.lit(0).alias("sn"))
    j = j.with_columns(pl.col("on_t", "n_t", "son_t", "sn_t", "on", "n", "son", "sn").fill_null(0))
    on = (j["on_t"] - j["on"]).to_numpy().astype(float)
    n = (j["n_t"] - j["n"]).to_numpy().astype(float)
    p = ((j["son_t"] - j["son"]) / (j["sn_t"] - j["sn"])).to_numpy().astype(float)
    assert np.isfinite(p).all(), "a slot without a rate"
    s = (on + m * p) / (n + m)
    held = j["heldout_road"].to_numpy()
    s[held] = p[held]
    return s.astype(np.float32)


def with_hist(df: pl.DataFrame, fit: pl.DataFrame, lodo: bool, label: str = "y") -> pl.DataFrame:
    return df.with_columns(pl.Series("x_b1", b1_encode(df, fit, lodo=lodo, label=label)))


# ------------------------------------------------------------------------------------------------ matrices

class Scaler:
    """Mean and SD of the fit rows (float64 sums, column by column to keep memory low)."""

    def __init__(self, X: np.ndarray):
        self.mu = np.array([X[:, j].mean(dtype=np.float64) for j in range(X.shape[1])])
        sd = np.array([X[:, j].std(dtype=np.float64) for j in range(X.shape[1])])
        self.sd = np.where(sd > 0, sd, 1.0)

    def __call__(self, X: np.ndarray, inplace: bool = False) -> np.ndarray:
        """float32 result without float64 temporaries (saga keeps float32; lbfgs converts itself)."""
        Z = X if inplace else X.copy()
        Z -= self.mu.astype(np.float32)
        Z /= self.sd.astype(np.float32)
        return Z


def standardize(X: np.ndarray, mu: np.ndarray, sd: np.ndarray) -> np.ndarray:
    """In place, float32: (X - mu) / sd with a stored scaler (no float64 temporaries)."""
    X -= np.asarray(mu).astype(np.float32)
    X /= np.asarray(sd).astype(np.float32)
    return X


def _f32(df: pl.DataFrame, names: list[str]) -> np.ndarray:
    return df.select([pl.col(c).cast(pl.Float32) for c in names]).to_numpy()


def lasso_matrix(df: pl.DataFrame, cols: list[str]) -> tuple[np.ndarray, list[str]]:
    d, names = F.lasso_view(df, cols)
    X = _f32(d, names)
    assert X.dtype == np.float32
    return X, names


def tree_matrix(df: pl.DataFrame, cols: list[str]) -> np.ndarray:
    X = _f32(df, cols)
    assert X.dtype == np.float32
    return X


# ------------------------------------------------------------------------------------------------ fitting

def fit_logistic(Xs: np.ndarray, y: np.ndarray, C: float, l1: bool, warm=None):
    """l1=True: lasso (saga, intercept not penalised). l1=False: plain logistic regression (lbfgs, no penalty)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if l1:
            m = LogisticRegression(l1_ratio=1.0, solver="saga", C=C, max_iter=S.LASSO_MAX_ITER, tol=S.LASSO_TOL,
                                   warm_start=warm is not None, random_state=S.SEED)
            if warm is not None:
                m.coef_, m.intercept_ = warm.coef_.copy(), warm.intercept_.copy()
                m.classes_ = warm.classes_
        else:
            m = LogisticRegression(C=np.inf, solver="lbfgs", max_iter=2000, tol=1e-6)
        m.fit(Xs, y)
    return m


def c_for(lam_per_row: float, n: int) -> float:
    """Keep the penalty per row fixed across fits of different size: lambda = 1 / (C n)."""
    return 1.0 / (lam_per_row * n)


def neg_subsample(y: np.ndarray, keep: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return np.nonzero(y | (rng.random(len(y)) < keep))[0]


def fit_forest(X: np.ndarray, y: np.ndarray, trees: int, seed: int, **params) -> RandomForestClassifier:
    idx = neg_subsample(y, S.RF_NEG_KEEP, seed)
    rf = RandomForestClassifier(n_estimators=trees, n_jobs=S.RF_JOBS, random_state=seed, **params)
    rf.fit(X[idx], y[idx])
    return rf


def forest_score(rf: RandomForestClassifier, X: np.ndarray, chunk: int = 400_000) -> np.ndarray:
    return np.concatenate([rf.predict_proba(X[i:i + chunk])[:, 1] for i in range(0, len(X), chunk)])


def fold_frames(df: pl.DataFrame):
    """Forward-chaining folds inside the train days, training roads only (fit, check)."""
    tr = df.filter((pl.col("split") == "train") & ~pl.col("heldout_road"))
    for (a, b), (c, d) in S.FOLDS:
        yield tr.filter(between("date", a, b)), tr.filter(between("date", c, d))
