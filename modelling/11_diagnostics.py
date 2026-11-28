"""11_diagnostics.py - interpretation and failure cases.

A. Lasso coefficient bootstrap: resample the 16 train days (day blocks, with replacement), refit M1 at its frozen
   penalty, count how often each input is kept. Train days only.
B. Failure cases on the validation week (and the test week once 10_test.py has run): which onsets the final
   model catches at the operating share, split by incidents (rules 23-25 of docs/data_rules.md: incidents only
   interpret events, never inputs), by the drop now, and by a queue downstream; what the top false alarms are.

AI disclosure: drafted with Claude (Anthropic) on 25 Nov 2026; log in AI_USE.md.
"""
from __future__ import annotations

import json
import math
import pickle
import warnings
from datetime import timedelta

import numpy as np
import polars as pl
from lassofit import LassoLogit

import features as F
import settings as S
from common import alerts_at_share, ap, f4, log, md_table, write_md
from modeldata import lasso_matrix, load_rows, standardize, with_hist
from plotstyle import INK2, MODEL_COLOR, MODEL_LABEL, MUTED, SLOT, plt, save

FRZ = json.loads(S.FREEZE.read_text())
lines = ["# Diagnostics: lasso stability and failure cases", ""]

# ================================================================ A. lasso coefficient bootstrap (train days only)
with open(S.MODELS / "lasso.pkl", "rb") as fh:
    L = pickle.load(fh)
df = load_rows(h=S.HORIZON, splits=("train",))
fit = df.filter(~pl.col("heldout_road"))
if "x_b1" in L["cols"]:
    fit = with_hist(fit, fit, lodo=True)
X, xn = lasso_matrix(fit, L["cols"])
Xs = standardize(X, L["mu"], L["sd"])
del df
y = fit["y"].to_numpy()
days = sorted(fit["date"].unique().to_list())
di = fit["date"].replace_strict({d: i for i, d in enumerate(days)}).to_numpy()
R = 20
rng = np.random.default_rng(S.SEED)
coefs = []
for r in range(R):
    w = np.bincount(rng.integers(0, len(days), len(days)), minlength=len(days)).astype(np.float64)[di]
    m = LassoLogit(L["lambda_per_row"]).fit(Xs, y, sample_weight=w, coef_init=L["model"].coef_,
                                            intercept_init=L["model"].intercept_)
    coefs.append(m.coef_.ravel().copy())
    log(f"bootstrap {r + 1}/{R}: {int((m.coef_ != 0).sum())} inputs kept")
coefs = np.array(coefs)
keep = (coefs != 0).mean(axis=0)
c0 = L["model"].coef_.ravel()
order = np.argsort(-np.abs(c0))
lines += ["## A. Lasso coefficient bootstrap (16 train days resampled as blocks; 20 refits at the frozen penalty)", "",
          "The x_b1 input keeps its original leave-own-day-out values in every refit (an approximation).", ""]
lines += md_table([[f"`{xn[i]}`", f"{c0[i]:+.3f}", f"{keep[i]:.0%}", f"{np.quantile(coefs[:, i], 0.05):+.3f} to "
                    f"{np.quantile(coefs[:, i], 0.95):+.3f}"] for i in order[:40]],
                  ["input", "M1 coefficient", "kept in refits", "90% range"])
unstable = [xn[i] for i in range(len(xn)) if 0.2 <= keep[i] <= 0.8]
lines += ["", f"Inputs kept in 20-80% of the refits (unstable choice): {', '.join(f'`{u}`' for u in unstable) or 'none'}.", ""]
del Xs, fit
(S.TABLES / "11_lasso_bootstrap.json").write_text(json.dumps({"names": xn, "coef": c0.tolist(), "keep": keep.tolist()}))

# ================================================================ B. failure cases
INC_ORDER = ["Accident", "Vehicle breakdown", "Obstacle", "Unattended Vehicle", "Road Block", "Roadwork", "Miscellaneous",
             "Heavy Traffic"]
M_PER_DEG, COS = 111_320.0, math.cos(math.radians(1.35))


def inc_link_pairs(inc: pl.DataFrame, links: pl.DataFrame, within: float = 1000.0) -> pl.DataFrame:
    """Rule 24: point-to-segment distance on the flat grid, clamped at the link's ends; pairs within 1 km."""
    ax, ay = links["StartLon"].to_numpy() * M_PER_DEG * COS, links["StartLat"].to_numpy() * M_PER_DEG
    bx, by = links["EndLon"].to_numpy() * M_PER_DEG * COS, links["EndLat"].to_numpy() * M_PER_DEG
    px, py = inc["lon"].to_numpy() * M_PER_DEG * COS, inc["lat"].to_numpy() * M_PER_DEG
    out = []
    for k in range(0, len(px), 500):
        qx, qy = px[k:k + 500, None], py[k:k + 500, None]
        dx, dy = bx - ax, by - ay
        L2 = np.where(dx * dx + dy * dy > 0, dx * dx + dy * dy, 1.0)
        tt = np.clip(((qx - ax) * dx + (qy - ay) * dy) / L2, 0, 1)
        dist = np.hypot(qx - (ax + tt * dx), qy - (ay + tt * dy))
        ii, jj = np.nonzero(dist <= within)
        out.append(pl.DataFrame({"ep": ii + k, "LinkID": links["LinkID"].to_numpy()[jj], "dist": dist[ii, jj]}))
    return pl.concat(out)


def incident_info(rows: pl.DataFrame, inc: pl.DataFrame, links: pl.DataFrame) -> pl.DataFrame:
    """info_inc_1km (listed at t within 1 km) and info_inc_next15_1km (start in (t, t + 15] within 1 km)."""
    inc = inc.with_row_index("ep").with_columns(pl.coalesce("reported", "first_seen").alias("start"))
    pairs = inc_link_pairs(inc, links).join(inc.select(pl.col("ep").cast(pl.Int64), "type", "first_seen",
                                                       "last_seen_before", "start"), on="ep")
    j = rows.select("LinkID", "t").join(pairs, on="LinkID")
    rank = {t_: i for i, t_ in enumerate(INC_ORDER)}
    pick = lambda e: e.sort_by(pl.col("type").replace_strict(rank, default=99), pl.col("type")).first()
    listed = (j.filter((pl.col("first_seen") <= pl.col("t")) & (pl.col("last_seen_before").is_null() | (pl.col("t") < pl.col("last_seen_before"))))
               .group_by("LinkID", "t").agg(pick(pl.col("type")).alias("inc_listed")))
    nxt = (j.filter((pl.col("start") > pl.col("t")) & (pl.col("start") <= pl.col("t") + timedelta(minutes=15)))
             .group_by("LinkID", "t").agg(pick(pl.col("type")).alias("inc_next15")))
    return rows.join(listed, on=["LinkID", "t"], how="left").join(nxt, on=["LinkID", "t"], how="left")


links = pl.read_parquet(S.LINKS)
final = FRZ["final_model"]
share = FRZ["operating_share"]
weeks = [("validation week", S.PREDS / "val_rf.parquet" if final == "RF" else S.PREDS / "val_lasso.parquet",
          "rf_raw" if final == "RF" else "lasso", S.INCIDENTS, S.WORK / "fe_trainval.parquet", S.TRAIN)]
if (S.PREDS / "test_scores.parquet").exists():
    weeks.append(("test week", S.PREDS / "test_scores.parquet", final, S.TEST_BUILD / "model" / "extra" / "incidents.parquet",
                  S.WORK / "fe_test.parquet", S.TEST_BUILD / "model" / "test.parquet"))
for wk, pred_path, col, inc_path, fe_path, src in weeks:
    p = pl.read_parquet(pred_path).filter(~pl.col("heldout_road")).sort("LinkID", "t")
    base = (pl.scan_parquet(src).filter(~pl.col("U") & ~pl.col("heldout_road")).select("LinkID", "t", "f_d0", "f_slot15")
              .collect())
    fe = pl.scan_parquet(fe_path).select("LinkID", "t", "fe_dn_q0", "fe_norm_p0", "fe_norm_p10", "fe_norm_p15").collect()
    d = (p.select("LinkID", "t", "y", pl.col(col).alias("score")).join(base, on=["LinkID", "t"], how="left", maintain_order="left")
          .join(fe, on=["LinkID", "t"], how="left", maintain_order="left"))
    assert d["f_d0"].null_count() == 0 and d["fe_dn_q0"].null_count() == 0
    d = d.with_columns(pl.Series("alert", alerts_at_share(d["t"].to_numpy(), d["score"].to_numpy(), share)),
                       (pl.min_horizontal(pl.col("fe_norm_p10"), pl.col("fe_norm_p15")) - pl.col("fe_norm_p0") + pl.col("f_d0") >= 2)
                       .alias("pers"))
    inc = pl.read_parquet(inc_path)
    pos = incident_info(d.filter(pl.col("y")), inc, links)
    grp = (pos.with_columns(
        pl.when(pl.col("inc_next15").is_not_null()).then(pl.lit("incident starts inside the 15-min window"))
          .when(pl.col("inc_listed").is_not_null()).then(pl.lit("incident already listed at t (within 1 km)"))
          .otherwise(pl.lit("no incident within 1 km")).alias("incident"),
        pl.when(pl.col("f_d0") >= 2).then(pl.lit("already low now (not yet 2 updates)"))
          .when(pl.col("f_d0") > 0).then(pl.lit("a little slower than normal (0 < drop < 2)"))
          .otherwise(pl.lit("at or above normal (drop <= 0)")).alias("drop_now"),
        pl.when(pl.col("fe_dn_q0") <= 500).then(pl.lit("low link <= 500 m downstream"))
          .when(pl.col("fe_dn_q0") <= 3000).then(pl.lit("low link 0.5-3 km downstream"))
          .otherwise(pl.lit("no low link within 3 km downstream")).alias("queue"),
        pl.when(pl.col("pers")).then(pl.lit("yes: the usual level rises ahead while the band is already low"))
          .otherwise(pl.lit("no: a new slowdown")).alias("band_persistence")))
    lines += [f"## B. Failure cases, {wk} (training roads; {MODEL_LABEL[final]} at the operating share {100 * share:g}%)", "",
              f"{pos.height:,} onsets; caught (alerted at t, 15 min ahead): {pos['alert'].mean():.1%}.", ""]
    for key, title in (("incident", "by incident"), ("drop_now", "by the drop now"), ("queue", "by a queue downstream"),
                       ("band_persistence", "by 'band persistence says unusual' (the same band would be low at t+10 and t+15)")):
        g = grp.group_by(key).agg(pl.len().alias("onsets"), pl.col("alert").mean().alias("caught")).sort("onsets", descending=True)
        lines += [f"Onsets {title}:", ""] + md_table([[r[key], f"{r['onsets']:,}", f"{r['onsets'] / pos.height:.1%}",
                                                       f"{r['caught']:.1%}"] for r in g.iter_rows(named=True)],
                                                      [key.replace("_", " "), "onsets", "share", "caught"]) + [""]
    typ = (grp.filter(pl.col("inc_next15").is_not_null()).group_by("inc_next15")
              .agg(pl.len().alias("onsets"), pl.col("alert").mean().alias("caught")).sort("onsets", descending=True))
    lines += ["Incidents starting inside the window, by type:", ""] + md_table(
        [[r["inc_next15"], f"{r['onsets']:,}", f"{r['caught']:.1%}"] for r in typ.iter_rows(named=True)],
        ["type", "onsets", "caught"]) + [""]
    fa = d.filter(pl.col("alert") & ~pl.col("y"))
    fa_g = (fa.with_columns(pl.when(pl.col("f_d0") >= 2).then(pl.lit("low now, recovered within 15 min"))
                              .when(pl.col("pers")).then(pl.lit("normal level rises ahead (band persistence says low)"))
                              .when(pl.col("fe_dn_q0") <= 500).then(pl.lit("queue <= 500 m downstream did not arrive"))
                              .otherwise(pl.lit("other")).alias("why"))
              .group_by("why").agg(pl.len().alias("alerts")).sort("alerts", descending=True))
    lines += [f"False alarms ({fa.height:,} alerts with y = 0, {fa.height / max(1, d['alert'].sum()):.1%} of alerts), by situation:", ""]
    lines += md_table([[r["why"], f"{r['alerts']:,}", f"{r['alerts'] / fa.height:.1%}"] for r in fa_g.iter_rows(named=True)],
                      ["situation at t", "false alarms", "share"]) + [""]
    hr = (d.group_by((pl.col("f_slot15") // 4).alias("hour"))
           .agg(pl.col("y").sum().alias("onsets"), (pl.col("alert") & pl.col("y")).sum().alias("caught"),
                pl.col("alert").sum().alias("alerts")).sort("hour"))
    fig, ax = plt.subplots(figsize=(8, 3.6))
    ax.plot(hr["hour"], hr["caught"] / hr["onsets"], color=SLOT[0], marker="o", markersize=4, label="share of onsets caught (recall)")
    ax.plot(hr["hour"], hr["caught"] / hr["alerts"], color=SLOT[1], marker="o", markersize=4, label="share of alerts right (precision)")
    ax.set_xlabel("hour of day")
    ax.set_xticks(range(6, 22, 2))
    ax.set_ylim(0, 1)
    ax.set_title(f"{MODEL_LABEL[final]} at {100 * share:g}% alerts, {wk}, by hour")
    ax.legend(fontsize=8)
    save(fig, f"diag_by_hour_{'test' if wk.startswith('test') else 'val'}.png")
    log(f"{wk}: done")
write_md("11_diagnostics.md", lines)
