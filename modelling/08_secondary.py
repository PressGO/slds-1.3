"""08_secondary.py - the secondary checks fixed on 18 Nov, with the FROZEN settings (refit on the train days only):

  horizons   5 min (the proposal's secondary analysis), 10 and 30 min   (y_h5, y_h10, y_h30 of the full table)
  ablations  without the joining roads (f_conn_*); without every neighbour input (f_up_*, f_dn_*, HOP); without both
  lodo       the 53 build inputs fitted on train.parquet vs on extra/train_lodo.parquet (normal level built
             without the row's own day), both scored on the same validation rows

    python 08_secondary.py --family lasso|rf|base       (base = B1 and B2 for the horizons; fast)

Scores on the validation week go to results/tables/08_secondary_<family>.json; fitted models to work/models/sec_*.pkl,
recorded with their hashes in results/freeze_secondary_<family>.json before any test-week data is opened.

AI disclosure: drafted with Claude (Anthropic) on 25 Nov 2026; log in AI_USE.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pickle
import warnings
from datetime import datetime

import numpy as np
import polars as pl
from lassofit import LassoLogit

import features as F
import settings as S
from common import ID_COLS, ap, assert_closed, base_inputs, log, prec_rec_at_share
from modeldata import (B1_M, Scaler, b1_encode, feature_list, fit_forest, forest_score, lasso_matrix, load_rows,
                       rows_horizon, standardize, tree_matrix, with_hist)

ap_ = argparse.ArgumentParser()
ap_.add_argument("--family", required=True, choices=["lasso", "rf", "base"])
FAM = ap_.parse_args().family
FRZ = json.loads(S.FREEZE.read_text())
assert not (S.TEST_BUILD / "model" / "test.parquet").exists(), "secondary models must be fitted before the test build"
CORE = base_inputs(with_conn=False)


def rows_h(h: int) -> pl.DataFrame:
    return rows_horizon(h)


def split(df: pl.DataFrame, names: tuple, label_note: str = ""):
    fit = df.filter((pl.col("split") == "train") & ~pl.col("heldout_road"))
    val = df.filter(pl.col("split") == "validate")
    if "HIST" in names:
        fit, val = with_hist(fit, fit, lodo=True), with_hist(val, fit, lodo=False)
    return fit, val


def scores(val: pl.DataFrame, s: np.ndarray) -> dict:
    out = {}
    for name, held in (("main", False), ("transfer", True)):
        k = (val["heldout_road"] == held).to_numpy()
        d = val.filter(pl.Series(k))
        y = d["y"].to_numpy()
        out[name] = {"rows": int(len(y)), "base_rate": float(y.mean()), "pr_auc": ap(y, s[k]),
                     "prec_1pct": prec_rec_at_share(d["t"].to_numpy(), y, s[k], 0.01)[0]}
    return out


def fit_lasso(fit: pl.DataFrame, cols: list[str]):
    X, xn = lasso_matrix(fit, cols)
    sc = Scaler(X)
    Xs = sc(X, inplace=True)
    del X
    y = fit["y"].to_numpy()
    m = LassoLogit(FRZ["lasso"]["lambda_per_row"]).fit(Xs, y)       # the frozen penalty per row
    return {"model": m, "mu": sc.mu, "sd": sc.sd, "cols": cols, "xnames": xn, "nonzero": int((m.coef_ != 0).sum()),
            "iters": int(m.n_iter_[0])}


def score_lasso(obj, df: pl.DataFrame) -> np.ndarray:
    X, _ = lasso_matrix(df, obj["cols"])
    return obj["model"].predict_proba(standardize(X, obj["mu"], obj["sd"]))[:, 1]


def fit_rf(fit: pl.DataFrame, cols: list[str]):
    rf = fit_forest(tree_matrix(fit, cols), fit["y"].to_numpy(), S.RF_TREES_FINAL, S.SEED, **FRZ["rf"]["params"])
    return {"model": rf, "cols": cols}


def score_rf(obj, df: pl.DataFrame) -> np.ndarray:
    return forest_score(obj["model"], tree_matrix(df, obj["cols"]))


FIT = {"lasso": (fit_lasso, score_lasso), "rf": (fit_rf, score_rf)}
names = tuple(FRZ["features"]["LR" if FAM == "lasso" else "RF"]) if FAM != "base" else ()
results, saved = {}, {}


def save_model(key: str, obj) -> None:
    p = S.MODELS / f"sec_{FAM}_{key}.pkl"
    with open(p, "wb") as fh:
        pickle.dump(obj, fh)
    saved[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()


# ---------------------------------------------------------------- horizons
for h in (5, 10, 15, 30):
    df = rows_h(h)
    if h == S.HORIZON:   # the 15-min rows from the full table must be exactly the onset rows of train.parquet
        n_main = pl.scan_parquet(S.TRAIN).filter(~pl.col("U")).select(pl.len()).collect().item()
        assert df.height == n_main, (df.height, n_main)
        if FAM != "base":
            continue
    if FAM == "base":
        fit = df.filter((pl.col("split") == "train") & ~pl.col("heldout_road"))
        val = df.filter(pl.col("split") == "validate")
        results[f"h{h}"] = {"B1": scores(val, b1_encode(val, fit, m=B1_M)), "B2": scores(val, val["f_d0"].to_numpy())}
        b1_tables = fit.group_by("LinkID", "f_slot15").agg(pl.col("y").sum().alias("on"), pl.len().alias("n"))
        b1_slot = fit.group_by("f_slot15").agg((pl.col("y").sum() / pl.len()).alias("p"))
        save_model(f"b1_h{h}", {"cell": b1_tables, "slot": b1_slot, "m": B1_M})
        log(f"h{h}: B1 {results[f'h{h}']['B1']['main']['pr_auc']:.4f}  B2 {results[f'h{h}']['B2']['main']['pr_auc']:.4f}"
            f"  base rate {results[f'h{h}']['B2']['main']['base_rate']:.4f}")
        del df, fit, val                     # free this horizon's rows before the next one loads (OOM on 25 Nov)
        continue
    cols = feature_list(df.columns, names, h=h)
    fit, val = split(df, names)
    del df
    f, s = FIT[FAM]
    obj = f(fit, cols)
    obj["horizon"] = h
    results[f"h{h}"] = scores(val, s(obj, val))
    save_model(f"h{h}", obj)
    log(f"h{h}: {FAM} main PR-AUC {results[f'h{h}']['main']['pr_auc']:.4f} (base rate {results[f'h{h}']['main']['base_rate']:.4f})")
    del fit, val, obj

if FAM != "base":
    # ------------------------------------------------------------ ablations at 15 min
    df = load_rows(h=S.HORIZON)
    full_cols = feature_list(df.columns, names)
    fit, val = split(df, names)
    del df
    neighbour = ("f_up_", "f_dn_", "fe_dn_", "fe_up_")
    variants = {"no_conn": ("f_conn_",), "no_neighbours": neighbour, "no_conn_no_neighbours": ("f_conn_",) + neighbour,
                "no_hist": ("x_b1",)}   # no_hist: AYE and CTE only ever see the slot rate in x_b1 (transfer check)
    f, s = FIT[FAM]
    for key, drop in variants.items():
        cols = [c for c in full_cols if not c.startswith(drop)]
        obj = f(fit, cols)
        results[key] = scores(val, s(obj, val))
        results[key]["n_inputs"] = len(cols)
        save_model(key, obj)
        log(f"{key}: {len(cols)} inputs, main PR-AUC {results[key]['main']['pr_auc']:.4f}")
        del obj
    # ------------------------------------------------------------ leave-own-day-out normal level (the 53 build inputs)
    base_cols = base_inputs()
    for key, src in (("base53_trainnorm", S.TRAIN), ("base53_lodonorm", S.LODO)):
        tr = (pl.scan_parquet(src).filter((pl.col("split") == "train") & ~pl.col("U") & ~pl.col("heldout_road"))
                .select(ID_COLS + base_cols).collect().sort("LinkID", "t"))
        assert_closed(tr)
        obj = f(tr, base_cols)
        results[key] = scores(val, s(obj, val))
        results[key]["fit_rows"], results[key]["fit_onsets"] = tr.height, int(tr["y"].sum())
        save_model(key, obj)
        log(f"{key}: fit rows {tr.height:,} ({int(tr['y'].sum()):,} onsets), main PR-AUC {results[key]['main']['pr_auc']:.4f}")
        del obj, tr

(S.TABLES / f"08_secondary_{FAM}.json").write_text(json.dumps(results, indent=2))
(S.RESULTS / f"freeze_secondary_{FAM}.json").write_text(json.dumps({
    "frozen_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    "statement": "Secondary models fitted on the train days with the settings of freeze.json, before any test-week data was opened.",
    "models_sha256": saved}, indent=2))
log("done")
