"""01_eda.py - exploratory analysis, on the train and validation days only (never the test week).

Figures in figures/pipeline/eda_*.png, numbers in results/tables/01_eda.md.

AI disclosure: drafted with Claude (Anthropic) on 25 Nov 2026; log in AI_USE.md.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import polars as pl

import features as F
import settings as S
from common import assert_closed, f3, f4, log, md_table, write_md
from plotstyle import (BLUES, INK2, MUTED, SLOT, SURFACE, hour_ticks, plt, save)

lines = ["# Exploratory analysis (train and validation days; data version 4)", ""]
links = pl.read_parquet(S.LINKS)
ids = links["LinkID"].to_list()

# ---------------------------------------------------------------- 1. collection completeness (every day, every hour)
panel = (pl.scan_parquet(S.PANEL).filter(pl.col("LinkID").is_in(ids))
           .filter(pl.col("t").dt.date() <= S.LAST_OPEN_DAY)
           .group_by(pl.col("t").dt.date().alias("date"), pl.col("t").dt.hour().alias("hour")).len().collect())
assert_closed(panel)
days_all = [S.TRAIN_DAYS[0] + timedelta(days=i) for i in range((S.LAST_OPEN_DAY - S.TRAIN_DAYS[0]).days + 1)]
grid = np.full((len(days_all), 24), np.nan)
for d, h, n in panel.iter_rows():
    grid[days_all.index(d), h] = n / (len(ids) * 12)
fig, ax = plt.subplots(figsize=(9, 6.2))
im = ax.imshow(grid, aspect="auto", cmap=BLUES, vmin=0, vmax=1, interpolation="nearest")
ax.set_yticks(range(len(days_all)))
ax.set_yticklabels([f"{d:%a %d %b}" for d in days_all], fontsize=7)
ax.set_xticks(range(0, 24, 2))
ax.set_xticklabels([f"{h:02d}" for h in range(0, 24, 2)])
ax.set_xlabel("hour of day")
ax.grid(False)
ax.axvspan(5.5, 21.5, ymin=0, ymax=1, facecolor="none", edgecolor=INK2, linewidth=1)
cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
cb.set_label("share of the 2,598 links' 5-min updates captured")
ax.set_title("Collection completeness: expressway links captured per hour (box = 06:00-22:00 used)")
save(fig, "eda_01_completeness.png")
in_win = grid[:, 6:22]
lines += ["## 1. Collection completeness", "",
          f"Share of the 2,598 expressway links' updates captured, 06:00-22:00, 16 Oct-13 Nov: median hour "
          f"{np.nanmedian(in_win):.3f}, lowest hour {np.nanmin(in_win):.3f} "
          f"({days_all[int(np.nanargmin(in_win) // 16)]:%a %d %b}). Thu 12 Nov is low because the second collector "
          f"was down (`DATA.md`, section 6).", ""]

# ---------------------------------------------------------------- weekday rows of the full table (train, validate)
full = (pl.scan_parquet(S.FULL).filter(pl.col("in_population"))
          .select("LinkID", "road", "heldout_road", "t", "date", "split", "use", "U", "y", "info_band",
                  "info_norm_band", "info_deficit", "f_d0", "f_d5", "f_slot15", "f_rain30", "f_rain30_missing")
          .collect())
assert_closed(full)
tr = full.filter(pl.col("split") == "train")

# ---------------------------------------------------------------- 2. recurring vs unusual slow traffic
slow = (tr.filter(pl.col("info_band").is_not_null())
          .group_by(pl.col("t").dt.hour().alias("hour"))
          .agg(pl.len().alias("n"),
               ((pl.col("info_band") <= 3) & (pl.col("info_deficit") < 2)).sum().alias("recurring"),
               ((pl.col("info_band") <= 3) & (pl.col("info_deficit") >= 2)).sum().alias("unusual"))
          .sort("hour"))
h = slow["hour"].to_numpy()
rec = (slow["recurring"] / slow["n"]).to_numpy()
unu = (slow["unusual"] / slow["n"]).to_numpy()
fig, axs = plt.subplots(2, 1, figsize=(8.5, 6), sharex=True, gridspec_kw={"height_ratios": [3, 2]})
axs[0].bar(h, rec, width=0.7, color=MUTED, label="slow and normal for that link and time (recurring)",
           edgecolor=SURFACE, linewidth=1)
axs[0].bar(h, unu, bottom=rec, width=0.7, color=SLOT[1], label="slow and >= 2 bands below normal (unusual)",
           edgecolor=SURFACE, linewidth=1)
axs[0].set_ylabel("share of link-updates\nwith band <= 3 (< 30 km/h)")
axs[0].legend(loc="upper left")
axs[0].set_title("Most slow traffic is the usual rush hour, not an unusual event (train weekdays)")
axs[1].plot(h, unu / (rec + unu), color=SLOT[1], marker="o", markersize=4)
axs[1].set_ylabel("unusual share\nof slow updates")
axs[1].set_xlabel("hour of day")
axs[1].set_xticks(range(6, 22, 2))
save(fig, "eda_02_recurring_vs_unusual.png")
tot_slow = slow["recurring"].sum() + slow["unusual"].sum()
lines += ["## 2. Recurring vs unusual slow traffic (train weekdays)", "",
          f"Of all captured link-updates with band <= 3 (< 30 km/h), {slow['unusual'].sum() / tot_slow:.1%} are "
          f"unusual (>= 2 bands below that link's normal level) and {slow['recurring'].sum() / tot_slow:.1%} are "
          "recurring. A plain 'slow traffic' detector would mostly rediscover rush hour.", ""]

# ---------------------------------------------------------------- 3. normal-level curves for four example links
norm_w = pl.read_parquet(S.NORM).filter(pl.col("daytype") == "weekday")
prof = norm_w.filter(pl.col("slot15").is_between(24, 87)).group_by("LinkID").agg(
    pl.col("norm_band").min().alias("mn"),
    pl.col("norm_band").filter(pl.col("slot15").is_between(28, 39)).min().alias("am"),
    pl.col("norm_band").filter(pl.col("slot15").is_between(68, 79)).min().alias("pm"),
    pl.col("norm_band").max().alias("mx")).join(links.select("LinkID", "road"), on="LinkID")
free = prof.filter(pl.col("mx") >= 6)                  # links that are fast at some time of day
pick = [free.sort(["am", "LinkID"]).row(0, named=True), free.sort(["pm", "LinkID"]).row(0, named=True),
        prof.filter(pl.col("mn") >= 7).sort("LinkID").row(0, named=True),
        prof.filter(pl.col("mx") <= 2).sort("LinkID").row(0, named=True)]
titles = ["deepest morning dip", "deepest evening dip", "free flow all day", "floor effect: normal level <= 2"]
floor = norm_w.filter(pl.col("slot15").is_between(24, 87))
floor_cells = floor.filter(pl.col("norm_band") <= 2).height / floor.height
floor_links = prof.filter(pl.col("mx") <= 2).height
day = date(2026, 11, 10)
fig, axs = plt.subplots(2, 2, figsize=(10, 6), sharex=True, sharey=True)
for ax, p, ttl in zip(axs.ravel(), pick, titles):
    n = norm_w.filter((pl.col("LinkID") == p["LinkID"]) & pl.col("slot15").is_between(24, 87)).sort("slot15")
    b = full.filter((pl.col("LinkID") == p["LinkID"]) & (pl.col("date") == day)).sort("t")
    x = (b["t"].dt.hour() * 4 + b["t"].dt.minute() / 15).to_numpy()
    ax.step(x, b["info_band"].to_numpy(), where="post", color=MUTED, linewidth=1.2, label=f"band, Tue 10 Nov")
    ax.plot(n["slot15"].to_numpy() + 0.5, n["norm_band"].to_numpy(), color=SLOT[0], label="normal level (train weekdays)")
    ax.set_title(f"{ttl}: {p['road'].title()} ({p['LinkID']})", fontsize=9)
    hour_ticks(ax, every=4)
    ax.set_ylim(0.5, 8.5)
axs[0, 0].set_ylabel("speed band (1 = 0-9 km/h, 8 = 70+)")
axs[1, 0].set_ylabel("speed band")
hnd, lab_ = axs[0, 0].get_legend_handles_labels()
fig.legend(hnd, lab_, loc="upper right", ncol=2, bbox_to_anchor=(0.98, 1.0))
fig.suptitle("The normal level absorbs each link's recurring peaks", x=0.07, ha="left", fontweight="bold")
save(fig, "eda_03_norm_examples.png")
lines += ["## 2b. The floor effect", "",
          f"{floor_cells:.1%} of the weekday link x 15-min cells (06:00-22:00) have a normal level of band 1 or 2, "
          f"where a drop of 2 bands is impossible, and {floor_links} links sit at band <= 2 all day. Unusual events "
          "inside heavy recurring congestion are invisible to this label (`DATA.md`, section 8).", ""]

# ---------------------------------------------------------------- 4. class balance by hour; 5. by road
use = full.filter(pl.col("use"))
byh = (use.group_by("split", (pl.col("f_slot15") // 4).alias("hour"))
          .agg(pl.col("U").mean().alias("share_U"), pl.col("y").filter(~pl.col("U")).mean().alias("onset_rate"))
          .sort("split", "hour"))
fig, axs = plt.subplots(1, 2, figsize=(11, 3.8))
for sp, c in (("train", SLOT[0]), ("validate", SLOT[1])):
    d = byh.filter(pl.col("split") == sp)
    axs[0].plot(d["hour"], d["share_U"], color=c, marker="o", markersize=4, label=sp)
    axs[1].plot(d["hour"], d["onset_rate"], color=c, marker="o", markersize=4, label=sp)
axs[0].set_title("Unusual now (U), share of usable rows")
axs[1].set_title("Onset rate: P(unusual in 15 min | normal now)")
for ax in axs:
    ax.set_xlabel("hour of day")
    ax.set_xticks(range(6, 22, 2))
axs[0].legend()
save(fig, "eda_04_prevalence_by_hour.png")

road = (use.filter(~pl.col("U")).group_by("road", "heldout_road", "split")
           .agg(pl.col("y").mean().alias("rate"), pl.len().alias("rows"), pl.col("y").sum().alias("onsets"))
           .sort("road"))
rt = road.filter(pl.col("split") == "train").sort("rate")
fig, ax = plt.subplots(figsize=(8, 4.2))
cols = [MUTED if hr else SLOT[0] for hr in rt["heldout_road"]]
ax.barh(range(rt.height), rt["rate"].to_numpy(), color=cols, height=0.6)
ax.set_yticks(range(rt.height))
ax.set_yticklabels([r.title().replace("Expressway", "Expwy") for r in rt["road"]])
for i, (v, n) in enumerate(zip(rt["rate"], rt["onsets"])):
    ax.text(v, i, f"  {v:.2%} ({n:,})", va="center", fontsize=8, color=INK2)
ax.set_xlabel("onset rate on train weekdays (onsets in brackets)")
ax.set_title("Onset rate by road (grey = held-out roads AYE and CTE, never used to fit)")
ax.set_xlim(0, rt["rate"].max() * 1.35)
ax.grid(axis="y", visible=False)
save(fig, "eda_05_onset_by_road.png")

# ---------------------------------------------------------------- 6. episodes (effective sample size)
ep = (full.sort("LinkID", "t")
          .with_columns(pl.col("U").cast(pl.Int8).fill_null(-1).alias("st"))
          .with_columns(pl.col("st").shift(1).over("LinkID", "date").alias("prev_st"))
          .with_columns((pl.col("st") != pl.col("prev_st")).fill_null(True).cast(pl.Int32)
                        .cum_sum().over("LinkID", "date").alias("run"))
          .group_by("LinkID", "date", "run")
          .agg(pl.col("st").first(), pl.col("prev_st").first(), pl.len().alias("updates"),
               pl.col("split").first(), pl.col("heldout_road").first())
          .filter(pl.col("st") == 1))
ep_known = ep.filter(pl.col("prev_st") == 0)          # a real onset: normal just before
dur = ep_known.filter(pl.col("split") == "train")["updates"].to_numpy() * 5
fig, ax = plt.subplots(figsize=(8, 3.6))
bins = np.arange(5, 125, 5)
ax.hist(np.clip(dur, 5, 120), bins=np.r_[bins, 125] - 2.5, color=SLOT[0], edgecolor=SURFACE, linewidth=1)
ax.set_yscale("log")
ax.set_xlabel("episode length in minutes (runs of U = 1; 120 = 120 or more)")
ax.set_ylabel("episodes (log scale)")
ax.set_title(f"Unusual episodes on train weekdays: median {np.median(dur):.0f} min, "
             f"{(dur >= 30).mean():.0%} last 30 min or more")
save(fig, "eda_06_episode_durations.png")
ep_tab = (ep_known.group_by("split", "heldout_road").agg(pl.len().alias("episodes"),
                                                          (pl.col("updates") * 5).median().alias("median_min"))
                  .sort("split", "heldout_road"))
lines += ["## 3. Class balance and the effective sample size", ""]
lines += md_table([[r["split"], "AYE + CTE" if r["heldout_road"] else "training roads", f"{r['episodes']:,}",
                    f"{r['median_min']:.0f}"] for r in ep_tab.iter_rows(named=True)],
                  ["split", "roads", "onset episodes (normal just before)", "median length (min)"])
lines += ["", "Rows are strongly autocorrelated, so what limits precision is the number of episodes and of days, "
              "not the 8 M rows.", ""]
lines += md_table([[r["road"].title(), "yes" if r["heldout_road"] else "", r["split"], f"{r['rows']:,}",
                    f"{r['onsets']:,}", f4(r["rate"])] for r in road.sort("road", "split").iter_rows(named=True)],
                  ["road", "held out", "split", "onset rows", "onsets", "onset rate"])
lines += [""]

# ---------------------------------------------------------------- 7. dependence: autocorrelation and downstream lead
d = full.filter(pl.col("info_deficit").is_not_null()).select("LinkID", "t", pl.col("info_deficit").alias("d"))


def corr(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.corrcoef(a, b)[0, 1])


acf = []
for k in range(1, 13):
    j = d.join(d.select("LinkID", (pl.col("t") + timedelta(minutes=5 * k)).alias("t"), pl.col("d").alias("dk")),
               on=["LinkID", "t"])
    acf.append(corr(j["d"].to_numpy(), j["dk"].to_numpy()))
nb = pl.read_parquet(S.NEIGH)
xc = {}
for k in range(-6, 7):
    j = (nb.select("LinkID", "downstream").join(d, on="LinkID")
           .join(d.select(pl.col("LinkID").alias("downstream"), (pl.col("t") + timedelta(minutes=5 * k)).alias("t"),
                          pl.col("d").alias("dd")), on=["downstream", "t"]))
    xc[5 * k] = corr(j["d"].to_numpy(), j["dd"].to_numpy())
fig, axs = plt.subplots(1, 2, figsize=(11, 3.8))
axs[0].plot([5 * k for k in range(1, 13)], acf, color=SLOT[0], marker="o", markersize=4)
axs[0].set_title("Autocorrelation of a link's drop")
axs[0].set_xlabel("lag (minutes)")
axs[0].set_ylim(0, 1)
ks = sorted(xc)
axs[1].plot(ks, [xc[k] for k in ks], color=SLOT[0], marker="o", markersize=4)
axs[1].axvline(0, color=MUTED, linewidth=1)
axs[1].set_title("Link now vs its downstream link k minutes earlier")
axs[1].set_xlabel("k (minutes; > 0 = downstream link earlier)")
save(fig, "eda_07_dependence.png")
lines += ["## 4. Dependence", "", "Autocorrelation of the drop (pooled over links): "
          + ", ".join(f"{5 * k} min {a:.2f}" for k, a in zip(range(1, 13), acf) if k in (1, 3, 6, 12)) + ".",
          "Correlation of a link's drop now with its downstream link's drop k minutes earlier: "
          + ", ".join(f"k = {k}: {xc[k]:.3f}" for k in (-15, -5, 0, 5, 15)) + ". "
          + ("The downstream link leads (queues spill back upstream)." if xc[5] > xc[-5] else
             "No clear lead of the downstream link."), ""]

# ---------------------------------------------------------------- 8. rain (association only)
rain = (use.filter(~pl.col("U") & (pl.col("split") == "train"))
           .with_columns(pl.when(pl.col("f_rain30_missing") == 1).then(pl.lit("no reading"))
                         .when(pl.col("f_rain30") == 0).then(pl.lit("dry"))
                         .when(pl.col("f_rain30") <= 1).then(pl.lit("0.1-1 mm"))
                         .when(pl.col("f_rain30") <= 5).then(pl.lit("1-5 mm"))
                         .otherwise(pl.lit("> 5 mm")).alias("rain"))
           .group_by("rain").agg(pl.len().alias("rows"), pl.col("y").sum().alias("onsets"),
                                 pl.col("y").mean().alias("rate")))
order = ["dry", "0.1-1 mm", "1-5 mm", "> 5 mm", "no reading"]
rain = rain.with_columns(pl.col("rain").replace_strict({k: i for i, k in enumerate(order)}).alias("o")).sort("o")
fig, ax = plt.subplots(figsize=(7, 3.5))
ax.bar(range(rain.height), rain["rate"].to_numpy(), width=0.55, color=SLOT[0])
ax.set_xticks(range(rain.height))
ax.set_xticklabels([f"{r}\n{n:,} rows" for r, n in zip(rain["rain"], rain["rows"])], fontsize=8)
for i, v in enumerate(rain["rate"]):
    ax.text(i, v, f"{v:.2%}", ha="center", va="bottom", fontsize=8, color=INK2)
ax.set_ylabel("onset rate")
ax.set_title("Onset rate by rain in the last 30 min at the link's station (train weekdays)")
ax.grid(axis="x", visible=False)
save(fig, "eda_08_rain.png")
lines += ["## 5. Rain (association, not cause)", ""]
lines += md_table([[r["rain"], f"{r['rows']:,}", f"{r['onsets']:,}", f4(r["rate"])] for r in rain.iter_rows(named=True)],
                  ["rain in last 30 min", "onset rows", "onsets", "onset rate"])
lines += [""]

# ---------------------------------------------------------------- 9. drift: weekday profiles before / after 23 Oct
prof = (full.filter(pl.col("info_band").is_not_null())
            .with_columns(pl.when(pl.col("date") <= date(2026, 10, 23)).then(pl.lit("16-23 Oct (train)"))
                          .when(pl.col("date") <= S.TRAIN_DAYS[1]).then(pl.lit("26 Oct-6 Nov (train)"))
                          .otherwise(pl.lit("10-13 Nov (validate)")).alias("period"))
            .group_by("period", "f_slot15").agg(pl.col("info_band").mean().alias("band"),
                                                pl.col("info_deficit").mean().alias("drop"))
            .sort("period", "f_slot15"))
fig, axs = plt.subplots(1, 2, figsize=(11, 3.8))
for (per, c) in (("16-23 Oct (train)", MUTED), ("26 Oct-6 Nov (train)", SLOT[0]), ("10-13 Nov (validate)", SLOT[1])):
    p = prof.filter(pl.col("period") == per)
    axs[0].plot(p["f_slot15"], p["band"], color=c, label=per, linewidth=1.6)
    axs[1].plot(p["f_slot15"], p["drop"], color=c, label=per, linewidth=1.6)
axs[0].set_title("Mean speed band, all links")
axs[1].set_title("Mean drop below the normal level")
for ax in axs:
    hour_ticks(ax)
axs[0].legend(loc="lower left")
save(fig, "eda_09_drift.png")
mean_drop = (full.filter(pl.col("info_deficit").is_not_null()).group_by("split")
                 .agg(pl.col("info_deficit").mean().alias("m"), (pl.col("info_deficit") >= 2).mean().alias("low")))
lines += ["## 6. Drift across the weeks", ""]
lines += md_table([[r["split"], f3(r["m"]), f4(r["low"])] for r in mean_drop.sort("split").iter_rows(named=True)],
                  ["split", "mean drop (bands)", "share low (drop >= 2)"])
lines += ["", "The validation week runs a little below the training norm; part of that is the norm being built from "
              "the train days themselves (see the leave-own-day-out check).", ""]

# ---------------------------------------------------------------- 10. precursors of onsets: why the engineered inputs
fe = pl.read_parquet(S.WORK / "fe_trainval.parquet", columns=["LinkID", "t", "fe_norm_p0", "fe_norm_p10",
                                                                 "fe_norm_p15", "fe_dn_q0"])
on = (use.filter(~pl.col("U") & (pl.col("split") == "train") & ~pl.col("heldout_road"))
         .select("LinkID", "t", "y", "f_d0", "f_d5").join(fe, on=["LinkID", "t"], how="left"))
on = F.add_derived(on, 15)
d0 = (on.with_columns(pl.col("f_d0").clip(-2, 2).alias("d0b")).group_by("d0b")
        .agg(pl.len().alias("rows"), pl.col("y").sum().alias("onsets"), pl.col("y").mean().alias("rate")).sort("d0b"))
lp = on.group_by("x_lowpers15").agg(pl.len().alias("rows"), pl.col("y").sum().alias("onsets"),
                                    pl.col("y").mean().alias("rate")).sort("x_lowpers15")
qb = (on.with_columns(pl.when(pl.col("fe_dn_q0") == 0).then(pl.lit("next link"))
                        .when(pl.col("fe_dn_q0") <= 500).then(pl.lit("<= 500 m"))
                        .when(pl.col("fe_dn_q0") <= 1500).then(pl.lit("500-1,500 m"))
                        .when(pl.col("fe_dn_q0") <= 3000).then(pl.lit("1.5-3 km"))
                        .otherwise(pl.lit("none within 3 km")).alias("q"))
        .group_by("q").agg(pl.len().alias("rows"), pl.col("y").sum().alias("onsets"), pl.col("y").mean().alias("rate")))
qorder = ["next link", "<= 500 m", "500-1,500 m", "1.5-3 km", "none within 3 km"]
qb = qb.with_columns(pl.col("q").replace_strict({k: i for i, k in enumerate(qorder)}).alias("o")).sort("o")
fig, axs = plt.subplots(1, 3, figsize=(13, 3.8))
lab = [f"{v:g}" if -2 < v < 2 else ("<= -2" if v <= -2 else ">= 2") for v in d0["d0b"]]
axs[0].bar(range(d0.height), d0["rate"].to_numpy(), color=SLOT[0], width=0.6)
axs[0].set_xticks(range(d0.height))
axs[0].set_xticklabels(lab, fontsize=8)
axs[0].set_title("By the drop now (f_d0)", fontsize=10)
axs[0].set_xlabel("drop now (bands)")
axs[0].set_ylabel("onset rate")
axs[1].bar([0, 1], lp["rate"].to_numpy(), color=SLOT[0], width=0.5)
axs[1].set_xticks([0, 1])
axs[1].set_xticklabels(["no", "yes"])
axs[1].set_title("If the band stays: low at t+10 and t+15?", fontsize=10)
axs[1].set_xlabel("band persistence says unusual")
axs[2].bar(range(qb.height), qb["rate"].to_numpy(), color=SLOT[0], width=0.6)
axs[2].set_xticks(range(qb.height))
axs[2].set_xticklabels(qorder, fontsize=8, rotation=15)
axs[2].set_title("By the nearest low link downstream", fontsize=10)
for ax in axs:
    ax.grid(axis="x", visible=False)
fig.suptitle("Onset rate on train weekdays (training roads, normal now)", x=0.07, y=1.03, ha="left", fontweight="bold")
save(fig, "eda_10_precursors.png")
share_le0 = on.filter(pl.col("y") & (pl.col("f_d0") <= 0)).height / on["y"].sum()
lines += ["## 7. What comes before an onset (train weekdays, training roads, normal now)", "",
          f"{share_le0:.1%} of onsets start from a link at or above its normal level (f_d0 <= 0): last observation "
          "alone cannot rank those.", ""]
lines += md_table([[l, f"{r['rows']:,}", f"{r['onsets']:,}", f4(r["rate"])] for l, r in zip(lab, d0.iter_rows(named=True))],
                  ["drop now", "rows", "onsets", "onset rate"])
lines += [""] + md_table([["yes" if r["x_lowpers15"] else "no", f"{r['rows']:,}", f"{r['onsets']:,}", f4(r["rate"])]
                          for r in lp.iter_rows(named=True)],
                         ["band persistence predicts unusual at t+15", "rows", "onsets", "onset rate"])
lines += [""] + md_table([[r["q"], f"{r['rows']:,}", f"{r['onsets']:,}", f4(r["rate"])] for r in qb.iter_rows(named=True)],
                         ["nearest low link downstream", "rows", "onsets", "onset rate"])
write_md("01_eda.md", lines)
