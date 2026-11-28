"""common.py - shared helpers of the modelling pipeline: loading with test-week guards, metrics, bootstrap.

AI disclosure: drafted with Claude (Anthropic) on 25 Nov 2026; log in AI_USE.md.
"""
from __future__ import annotations

import json
import math
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl
from sklearn.metrics import average_precision_score

import settings as S

for d in (S.WORK, S.TABLES, S.FIGS, S.MODELS, S.PREDS):
    d.mkdir(parents=True, exist_ok=True)

T0 = time.time()


def log(msg: str) -> None:
    print(f"[{time.time() - T0:7.1f}s] {msg}", flush=True)


# ------------------------------------------------------------------------------------------------ guards

def assert_closed(df: pl.DataFrame, col: str = "date") -> None:
    """Before the freeze nothing after 13 Nov may be read (proposal: test 16-20 Nov stays untouched)."""
    if df.height:
        last = df[col].max()
        last = last.date() if isinstance(last, datetime) else last
        assert last <= S.LAST_OPEN_DAY, f"test-week rows seen ({last}); stop"


def freeze_exists() -> bool:
    return S.FREEZE.exists()


# ------------------------------------------------------------------------------------------------ loading

ID_COLS = ["LinkID", "road", "heldout_road", "t", "date", "split", "y", "U"]


def base_inputs(with_conn: bool = True) -> list[str]:
    names = pl.read_parquet_schema(S.TRAIN)
    cols = [c for c in names if c.startswith("f_")]
    return cols if with_conn else [c for c in cols if not c.startswith("f_conn_")]


def load_main(cols: list[str] | None = None, splits=("train", "validate"), onset_only: bool = True) -> pl.DataFrame:
    lf = pl.scan_parquet(S.TRAIN).filter(pl.col("split").is_in(list(splits)))
    if onset_only:
        lf = lf.filter(~pl.col("U"))
    if cols is not None:
        lf = lf.select(list(dict.fromkeys(cols)))
    df = lf.collect()
    assert_closed(df)
    return df


def between(col: str, a: date, b: date) -> pl.Expr:
    return pl.col(col).is_between(a, b)


# ------------------------------------------------------------------------------------------------ metrics

def ap(y: np.ndarray, s: np.ndarray) -> float:
    """PR-AUC = average precision (scikit-learn)."""
    return float(average_precision_score(y, s))


def brier(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((np.asarray(p, float) - np.asarray(y, float)) ** 2))


def alerts_at_share(t: np.ndarray, s: np.ndarray, share: float, seed: int = S.TIE_SEED) -> np.ndarray:
    """At each update t, alert on the top ceil(n_t * share) scored links; ties broken at random (fixed seed).

    Rows must be in the order (LinkID, t) for the tie draw to reproduce the 18 Nov baseline numbers exactly
    (asserted in 03_baselines.py).
    """
    rng = np.random.default_rng(seed)
    d = (pl.DataFrame({"t": t, "s": np.asarray(s, float), "tie": rng.random(len(t)),
                       "i": np.arange(len(t), dtype=np.int64)})
         .sort(["t", "s", "tie"], descending=[False, True, True])
         .with_columns(pl.int_range(pl.len()).over("t").alias("rank"), pl.len().over("t").alias("n_t")))
    hit = d.filter(pl.col("rank") < (pl.col("n_t") * share).ceil())["i"].to_numpy()
    out = np.zeros(len(t), dtype=bool)
    out[hit] = True
    return out


def prec_rec_at_share(t, y, s, share, seed=S.TIE_SEED) -> tuple[float, float, int]:
    a = alerts_at_share(t, s, share, seed)
    y = np.asarray(y, bool)
    tp = int((a & y).sum())
    return tp / max(1, int(a.sum())), tp / max(1, int(y.sum())), int(a.sum())


class DayBootstrap:
    """Day-block bootstrap of PR-AUC with one sort per score: weights = how often each day is drawn.

    ap_weighted reproduces sklearn's average_precision_score(y, s, sample_weight=w) (checked in 03_baselines.py).
    """

    def __init__(self, day_index: np.ndarray, n_days: int, reps: int = S.BOOT_REPS, seed: int = S.SEED):
        rng = np.random.default_rng(seed)
        self.counts = np.stack([np.bincount(rng.integers(0, n_days, n_days), minlength=n_days)
                                for _ in range(reps)]).astype(np.float64)
        self.day = day_index

    @staticmethod
    def prep(s: np.ndarray, y: np.ndarray, day: np.ndarray):
        order = np.argsort(-np.asarray(s, float), kind="mergesort")
        ss = np.asarray(s, float)[order]
        ends = np.r_[np.nonzero(np.diff(ss))[0], len(ss) - 1]
        return np.asarray(y, float)[order], day[order], ends

    @staticmethod
    def ap_weighted(ys: np.ndarray, ws: np.ndarray, ends: np.ndarray) -> float:
        tp = np.cumsum(ws * ys)[ends]
        fp = np.cumsum(ws * (1.0 - ys))[ends]
        if tp[-1] <= 0:
            return float("nan")
        prec = np.divide(tp, tp + fp, out=np.zeros_like(tp), where=(tp + fp) > 0)
        rec = tp / tp[-1]
        return float(np.sum(np.diff(np.r_[0.0, rec]) * prec))

    def replicate_aps(self, s: np.ndarray, y: np.ndarray) -> np.ndarray:
        ys, ds, ends = self.prep(s, y, self.day)
        return np.array([self.ap_weighted(ys, c[ds], ends) for c in self.counts])


def ci(a: np.ndarray, level: float = 0.95) -> tuple[float, float]:
    a = a[np.isfinite(a)]
    lo, hi = np.quantile(a, [(1 - level) / 2, 1 - (1 - level) / 2])
    return float(lo), float(hi)


def reliability(y: np.ndarray, p: np.ndarray, bins: int = 15) -> pl.DataFrame:
    """Quantile bins of the predicted chance: mean predicted vs observed rate."""
    q = np.unique(np.quantile(p, np.linspace(0, 1, bins + 1)))
    b = np.clip(np.searchsorted(q, p, side="right") - 1, 0, len(q) - 2)
    return (pl.DataFrame({"b": b, "p": p, "y": np.asarray(y, float)})
            .group_by("b").agg(pl.col("p").mean().alias("mean_pred"), pl.col("y").mean().alias("observed"),
                               pl.len().alias("rows")).sort("b"))


# ------------------------------------------------------------------------------------------------ output

def md_table(rows: list[list], header: list[str]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(x) for x in r) + " |" for r in rows]
    return out


def write_md(name: str, lines: list[str]) -> Path:
    p = S.TABLES / name
    p.write_text("\n".join(lines) + "\n")
    log(f"written {p.relative_to(S.ROOT)}")
    return p


def save_json(name: str, obj) -> Path:
    p = S.TABLES / name
    p.write_text(json.dumps(obj, indent=2, default=str))
    return p


def f4(x: float) -> str:
    return "nan" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.4f}"


def f3(x: float) -> str:
    return f"{x:.3f}"
