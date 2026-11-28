"""12_figures.py - the result figures (precision-recall, calibration, intervals, horizons), redrawn from saved scores only (no model is fitted, nothing is frozen).

Validation week: always. Test week: once 10_test.py has written work/preds/test_scores.parquet.

AI disclosure: drafted with Claude (Anthropic) on 26 Nov 2026; log in AI_USE.md.
"""
from __future__ import annotations

import json
from datetime import date

import numpy as np
import polars as pl
from matplotlib.ticker import NullFormatter, NullLocator
from sklearn.metrics import precision_recall_curve

import settings as S
from common import ap, prec_rec_at_share
from plotstyle import INK2, MODEL_COLOR, MODEL_LABEL, MUTED, plt, save

FRZ = json.loads(S.FREEZE.read_text())
ORDER = ["B1", "B2", "B2p", "Lasso", "RF"]


def logit(p):
    p = np.clip(np.asarray(p, float), 1e-7, 1 - 1e-7)
    return np.log(p / (1 - p))


def calibrated(name, p):
    a, b = FRZ["calibration_platt_logit"][name]
    return 1 / (1 + np.exp(-(a + b * logit(p))))


def pr_figure(d: pl.DataFrame, scores: dict, week: str, fname: str) -> None:
    y, t = d["y"].to_numpy(), d["t"].to_numpy()
    fig, axs = plt.subplots(1, 2, figsize=(12.5, 4.6), gridspec_kw={"wspace": 0.28})
    for n in ORDER:
        pr, rc, _ = precision_recall_curve(y, scores[n])
        axs[0].plot(rc, pr, color=MODEL_COLOR[n], linewidth=1.8, label=f"{MODEL_LABEL[n]}  {ap(y, scores[n]):.3f}")
    axs[0].axhline(y.mean(), color=MUTED, linewidth=1)
    axs[0].text(0.98, y.mean() + 0.01, f"base rate {y.mean():.3f}", ha="right", va="bottom", fontsize=8, color=INK2)
    axs[0].set_xlabel("recall")
    axs[0].set_ylabel("precision")
    axs[0].set_title(f"Precision-recall, {week}\n(legend: PR-AUC)", fontsize=10)
    axs[0].legend(fontsize=8, loc="upper right")
    shares = list(S.SHARE_GRID)
    for n in ORDER:
        axs[1].plot([100 * q for q in shares], [prec_rec_at_share(t, y, scores[n], q)[0] for q in shares],
                    color=MODEL_COLOR[n], marker="o", markersize=4, label=MODEL_LABEL[n])
    axs[1].axvline(100 * FRZ["operating_share"], color=MUTED, linewidth=1)
    axs[1].set_xscale("log")
    axs[1].xaxis.set_minor_locator(NullLocator())
    axs[1].xaxis.set_minor_formatter(NullFormatter())
    axs[1].set_xticks([100 * q for q in shares])
    axs[1].set_xticklabels([f"{100 * q:g}%" for q in shares])
    axs[1].set_xlabel("alerts: top share of links at each update (line = operating share)")
    axs[1].set_ylabel("precision among the alerts")
    axs[1].set_title(f"Precision among the highest-ranked alerts, {week}", fontsize=10)
    save(fig, fname)


def reliability_figure(d: pl.DataFrame, probs: dict, week: str, fname: str, bins: int = 20) -> None:
    y = d["y"].to_numpy().astype(float)
    fig, ax = plt.subplots(figsize=(5.8, 5.2))
    lo = 1.0
    for n, p in probs.items():
        q = np.unique(np.quantile(p, np.linspace(0, 1, bins + 1)))
        b = np.clip(np.searchsorted(q, p, side="right") - 1, 0, len(q) - 2)
        mp = np.bincount(b, weights=p) / np.bincount(b)
        ob = np.bincount(b, weights=y) / np.bincount(b)
        k = ob > 0
        ax.plot(mp[k], ob[k], color=MODEL_COLOR[n], marker="o", markersize=4, label=MODEL_LABEL[n], linewidth=1.6)
        lo = min(lo, mp[k].min(), ob[k].min())
    ax.plot([lo, 1], [lo, 1], color=MUTED, linewidth=1)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("predicted chance (Platt map fitted on validation)")
    ax.set_ylabel("observed onset rate")
    ax.set_title(f"Reliability, {week} ({bins} equal-count bins)", fontsize=10)
    ax.legend(fontsize=8, loc="upper left")
    save(fig, fname)


# ---- validation week ----
b = pl.read_parquet(S.PREDS / "val_baselines.parquet")
v = (b.join(pl.read_parquet(S.PREDS / "val_lasso.parquet").select("LinkID", "t", "lasso"), on=["LinkID", "t"])
      .join(pl.read_parquet(S.PREDS / "val_rf.parquet").select("LinkID", "t", "rf_raw"), on=["LinkID", "t"])
      .join(pl.read_parquet(S.WORK / "fe_trainval.parquet", columns=["LinkID", "t", "fe_norm_p0", "fe_norm_p10", "fe_norm_p15"]),
            on=["LinkID", "t"], how="left")
      .filter(~pl.col("heldout_road")).sort("LinkID", "t"))
sv = {"B1": v["b1"].to_numpy(), "B2": v["b2"].to_numpy(),
      "B2p": np.minimum((v["fe_norm_p10"] - v["fe_norm_p0"] + v["b2"]).to_numpy(), (v["fe_norm_p15"] - v["fe_norm_p0"] + v["b2"]).to_numpy()),
      "Lasso": v["lasso"].to_numpy(), "RF": v["rf_raw"].to_numpy()}
pr_figure(v, sv, "validation week, training roads", "fig_val_pr.png")
reliability_figure(v, {n: calibrated(n, sv[n]) for n in ("B1", "Lasso", "RF")}, "validation week (in-sample map)",
                   "fig_val_reliability.png")

# ---- test week ----
tp = S.PREDS / "test_scores.parquet"
if tp.exists():
    t = pl.read_parquet(tp).filter(~pl.col("heldout_road")).sort("LinkID", "t")
    st = {n: t[n].to_numpy() for n in ORDER}
    pr_figure(t, st, "TEST week, training roads", "fig_test_pr.png")
    reliability_figure(t, {n: calibrated(n, st[n]) for n in ("B1", "Lasso", "RF")}, "TEST week (map frozen on validation)",
                       "fig_test_reliability.png")
    res = json.loads((S.TABLES / "10_test.json").read_text())
    short = {"B1": "B1\ntime of week", "B2": "B2\nlast obs.", "B2p": "band\npersistence", "Lasso": "M1\nlasso", "RF": "M2\nforest"}
    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    for i, (lab, key, mk) in enumerate((("training roads", "main", "o"), ("AYE + CTE (transfer)", "transfer", "s"))):
        for j, n in enumerate(ORDER):
            r = res[f"{key}|{n}"]
            x = j + (i - 0.5) * 0.28
            ax.plot([x, x], r["ci"], color=MODEL_COLOR[n], linewidth=2.2, alpha=1 if i == 0 else 0.55, solid_capstyle="butt")
            ax.plot([x], [r["pr_auc"]], marker=mk, color=MODEL_COLOR[n], markersize=7, markeredgecolor="#fcfcfb",
                    markeredgewidth=1.5, linestyle="none", label=lab if j == 0 else None)
        ax.axhline(res[f"{key}|B2"]["base_rate"], color=MUTED, linewidth=1)
    ax.text(len(ORDER) - 0.55, res["main|B2"]["base_rate"] + 0.006, "base rates", ha="right", fontsize=8, color=INK2)
    ax.set_xticks(range(len(ORDER)))
    ax.set_xticklabels([short[n] for n in ORDER], fontsize=9)
    ax.set_ylabel("PR-AUC, 95% day-block bootstrap interval")
    ax.set_title("TEST week: training roads (circles) and the held-out AYE + CTE (squares)", fontsize=10)
    leg = ax.legend(fontsize=8, loc="upper left")
    for h_ in leg.legend_handles:
        h_.set_color(INK2)
    ax.grid(axis="x", visible=False)
    save(fig, "fig_test_intervals.png")
    hs = [h for h in (5, 10, 15, 30) if f"horizon{h}" in res]
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    for n in ("B1", "B2", "Lasso", "RF"):
        ax.plot(hs, [res[f"horizon{h}"].get(n, np.nan) for h in hs], color=MODEL_COLOR[n], marker="o", markersize=5,
                label=MODEL_LABEL[n])
    ax.plot(hs, [res[f"horizon{h}"]["base_rate"] for h in hs], color=MUTED, linewidth=1, linestyle="-", label="base rate")
    ax.set_xticks(hs)
    ax.set_xticklabels([f"{h} min" for h in hs])
    ax.set_xlabel("horizon (15 min = the main question)")
    ax.set_ylabel("PR-AUC, test week, training roads")
    ax.set_title("How far ahead: PR-AUC by horizon (test week)", fontsize=10)
    ax.legend(fontsize=8)
    save(fig, "fig_test_horizons.png")
