"""03_baselines.py - B1 (time-of-week onset rate) and B2 (last observation), as in DECISIONS.md (18 Nov).

Reproduces the baseline numbers of 18 Nov to 4 decimals (asserted), then saves the B1 tables and the
validation-week scores for the later scripts. Train and validation days only.

AI disclosure: drafted with Claude (Anthropic) on 25 Nov 2026; log in AI_USE.md.
"""
from __future__ import annotations

import math

import numpy as np
import polars as pl
from sklearn.metrics import average_precision_score

import settings as S
from common import (DayBootstrap, ap, between, f4, load_main, log, md_table, prec_rec_at_share, write_md)


def fit_b1(fit: pl.DataFrame, label: str = "y") -> tuple[pl.DataFrame, pl.DataFrame]:
    """Onset counts per link x slot and the slot rate, from rows of the training roads only."""
    fit = fit.filter(~pl.col("heldout_road"))
    cell = fit.group_by("LinkID", "f_slot15").agg(pl.col(label).sum().alias("on"), pl.len().alias("n"))
    slot = fit.group_by("f_slot15").agg((pl.col(label).sum() / pl.len()).alias("p"))
    return cell, slot


def score_b1(r: pl.DataFrame, cell: pl.DataFrame, slot: pl.DataFrame, m: float) -> np.ndarray:
    j = r.select("LinkID", "f_slot15", "heldout_road").join(slot, on="f_slot15", how="left") \
         .join(cell, on=["LinkID", "f_slot15"], how="left", maintain_order="left")
    assert j.height == r.height and j["p"].null_count() == 0, "a slot without a rate"
    on, n, p = j["on"].fill_null(0).to_numpy(), j["n"].fill_null(0).to_numpy(), j["p"].to_numpy()
    if math.isinf(m):
        s = p.astype(float).copy()
    else:
        with np.errstate(invalid="ignore", divide="ignore"):
            s = np.where(n + m > 0, (on + m * p) / (n + m), p)
    held = j["heldout_road"].to_numpy()
    s[held] = p[held]                                  # held-out roads: slot rate only
    return s


def choose_m(tr: pl.DataFrame, label: str = "y") -> tuple[float, dict]:
    cv = {}
    for m in S.B1_M_GRID:
        aps = []
        for (a, b), (c, d) in S.FOLDS:
            cell, slot = fit_b1(tr.filter(between("date", a, b)), label)
            chk = tr.filter(between("date", c, d))
            aps.append(ap(chk[label].to_numpy(), score_b1(chk, cell, slot, m)))
        cv[m] = aps
    best = max(S.B1_M_GRID, key=lambda m: (round(float(np.mean(cv[m])), 4), m))   # ties: the larger m
    return best, cv


if __name__ == "__main__":
    cols = ["LinkID", "heldout_road", "t", "date", "split", "y", "U", "f_d0", "f_slot15"]
    rows = load_main(cols)
    tr = rows.filter((pl.col("split") == "train") & ~pl.col("heldout_road"))
    log(f"onset rows: {rows.height:,}; fit rows (train days, training roads) {tr.height:,}, onsets {tr['y'].sum():,}")

    # ---- the row counts of the 18 Nov baseline run ----
    expect_rows = {"fit": (4_586_551, 46_422)}
    assert (tr.height, int(tr["y"].sum())) == expect_rows["fit"], (tr.height, tr["y"].sum())
    fold_counts = []
    for (a, b), (c, d) in S.FOLDS:
        f, k = tr.filter(between("date", a, b)), tr.filter(between("date", c, d))
        fold_counts.append((f.height, int(f["y"].sum()), k.height, int(k["y"].sum())))
    assert fold_counts == [(1_623_401, 10_146, 1_500_002, 14_649), (3_123_403, 24_795, 1_463_148, 21_627)], fold_counts

    # ---- B1: m by forward-chaining; B2 on the same folds ----
    best, cv = choose_m(tr)
    b2_cv = [ap(k["y"].to_numpy(), k["f_d0"].to_numpy()) for k in
             (tr.filter(between("date", c, d)) for _, (c, d) in S.FOLDS)]
    expect_cv = {0: (0.0292, 0.0475), 12: (0.0404, 0.0583), 48: (0.0404, 0.0595), 192: (0.0343, 0.0574),
                 768: (0.0233, 0.0424), math.inf: (0.0185, 0.0255)}
    for m, (e1, e2) in expect_cv.items():
        assert (round(cv[m][0], 4), round(cv[m][1], 4)) == (e1, e2), (m, cv[m])
    assert best == 48 and (round(b2_cv[0], 4), round(b2_cv[1], 4)) == (0.1423, 0.1693)
    log(f"B1 m = {best}; CV table and B2 folds reproduce the 18 Nov numbers")

    # ---- final B1 on all train days; validation scores ----
    cell, slot = fit_b1(rows.filter(pl.col("split") == "train"))
    cell.write_parquet(S.MODELS / "b1_cell.parquet")
    slot.write_parquet(S.MODELS / "b1_slot.parquet")
    val = rows.filter(pl.col("split") == "validate").sort("LinkID", "t")
    val = val.with_columns(pl.Series("b1", score_b1(val, cell, slot, best)),
                           pl.col("f_d0").cast(pl.Float64).alias("b2"))
    val.select("LinkID", "t", "date", "heldout_road", "y", "b1", "b2").write_parquet(S.PREDS / "val_baselines.parquet")

    expect_val = {False: (1_178_466, 13_883, 0.0688, 0.1284, [(0.106, 0.256), (0.092, 0.194), (0.079, 0.138)]),
                  True: (428_667, 6_430, 0.0232, 0.1431, [(0.019, 0.230), (0.018, 0.197), (0.017, 0.148)])}
    out_rows = []
    for held in (False, True):
        v = val.filter(pl.col("heldout_road") == held)
        y, t = v["y"].to_numpy(), v["t"].to_numpy()
        a1, a2 = ap(y, v["b1"].to_numpy()), ap(y, v["b2"].to_numpy())
        prec = [(prec_rec_at_share(t, y, v["b1"].to_numpy(), q)[0], prec_rec_at_share(t, y, v["b2"].to_numpy(), q)[0])
                for q in S.SHARES]
        n, on, e1, e2, ep = expect_val[held]
        assert (v.height, int(y.sum()), round(a1, 4), round(a2, 4)) == (n, on, e1, e2), (held, a1, a2)
        assert [(round(p1, 3), round(p2, 3)) for p1, p2 in prec] == ep, (held, prec)
        out_rows.append(["AYE + CTE (transfer)" if held else "training roads (main)", f"{v.height:,}",
                         f"{int(y.sum()):,}", f4(y.mean()), f4(a1), f4(a2),
                         *[f"{p1:.3f} / {p2:.3f}" for p1, p2 in prec]])
    log("validation numbers reproduce the 18 Nov numbers (rows, onsets, PR-AUC, precision at 0.5 / 1 / 2%)")

    # ---- the fast day-bootstrap AP equals scikit-learn's weighted AP ----
    v = val.filter(~pl.col("heldout_road"))
    days = sorted(v["date"].unique().to_list())
    di = v["date"].to_physical().to_numpy() - v["date"].to_physical().min()
    di = np.searchsorted(np.array(sorted(set(di))), di)
    bs = DayBootstrap(di, len(days), reps=6, seed=1)
    for s in (v["b1"].to_numpy(), v["b2"].to_numpy()):
        fast = bs.replicate_aps(s, v["y"].to_numpy())
        slow = [average_precision_score(v["y"].to_numpy(), s, sample_weight=c[di]) for c in bs.counts]
        assert np.allclose(fast, slow, atol=1e-12), (fast, slow)
    log("fast bootstrap AP == sklearn weighted AP on 6 replicates x 2 scores")

    lines = ["# Baselines B1 and B2 (train and validation days; data version 4)", "",
             "Reproduces the baseline numbers of 18 Nov exactly (asserted to 4 decimals in the script).", "",
             "## B1: m by forward-chaining inside the train days", ""]
    lines += md_table([["slot rate only" if math.isinf(m) else m, f4(a), f4(b), f4((a + b) / 2)]
                       for m, (a, b) in cv.items()], ["m", "fold 1", "fold 2", "mean"])
    lines += ["", f"Chosen m = **{best}**. B2 on the same folds: {f4(b2_cv[0])} and {f4(b2_cv[1])}.", "",
              "## Validation week (Tue 10 - Fri 13 Nov)", ""]
    lines += md_table(out_rows, ["Rows", "Scored rows", "Onsets", "Base rate", "B1 PR-AUC", "B2 PR-AUC",
                                 *[f"B1 / B2 precision at top {100 * q:g}%" for q in S.SHARES]])
    write_md("03_baselines.md", lines)
