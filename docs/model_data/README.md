# SLDS 1.3 modelling tables (data version 2)

Built 2026-11-11T23:46:26+08:00 from git commit `470df0c-modified` by `analysis/build_model_data.py`
(run through `build_processed.sh`). Every file is rebuilt from the raw data on each run, so rerunning on the same
raw data gives the same tables. New days are added as collection goes on (same version); a change of rule, setting
or a bug fix raises the version. Check `build_info.json` (`data_version`, `built_at`) against your copy.

## Changes

- v1 (2026-11-11): First release: 2,598 expressway links, strict label rule, own/neighbour/rain features, held-out roads AYE + CTE (pending team confirmation).
- v2 (2026-11-11): Added f_conn_* inputs: links that join an expressway (slip roads, arterials, ...), so models can be compared with and without them. Rows, labels and other columns unchanged.

## Getting the data

Download the files from the Google Drive folder `SLDS_1.3_processed` into `data_processed/model/` in your copy of
the repo, keeping `test_locked/` out of it until the test week. Then check them:
`sha256sum -c --ignore-missing SHA256SUMS.txt` (Linux/macOS; Windows: `Get-FileHash <file> -Algorithm SHA256` and compare).
Only `train_dev.parquet` (~9 MB) is needed to start writing scripts; `train.parquet` is ~70 MB.
Settings, input checksums and row counts: `build_info.json`.

## Quick start (R)

```r
library(arrow); library(dplyr)
tr <- read_parquet("data_processed/model/train_dev.parquet")   # small; switch to train.parquet for real fits
tr <- tr |> filter(use, !heldout_road)                          # usable rows, held-out roads kept out
x  <- tr |> select(starts_with("f_"))                           # every model input, no NAs
x0 <- tr |> select(starts_with("f_"), -starts_with("f_conn_"))  # the same without the joining roads
y  <- tr$y                                                      # outcome: unusual 15 min later
onset <- !tr$U                                                  # primary metric: rows normal now
```

Both models use the same rows and the same `f_*` columns:

- **Elastic net (`glmnet`)**: `as.matrix(x)`. Treat `f_slot15` as time of day in the model, e.g. a natural spline
  or hour dummies, rather than a straight line. `glmnet` standardises on the training data by default.
- **Random forest (`ranger`)**: use `x` as is. For full-size fits, subsample negatives with a fixed seed and
  recalibrate probabilities on the validation week afterwards (PROJECT_PLAN §4.6).
- **Baselines**: B1 = training rate of `U` per `LinkID` x `slot15` x `daytype`; B2 = `f_d0` (current deficit).

## Rules

- **Never open `test_locked/`** until the analysis plan is frozen. Only the final test script reads it
  (PROJECT_PLAN §6, item 7). It is not uploaded to Drive until then. EDA and tuning use `train`; model choice and calibration use `validate`.
- **Held-out roads** (Ayer Rajah Expressway, Central Expressway; 689 links, `heldout_road`): never
  used for training or tuning; evaluated on the test week for the transfer check.
- **Use `info_*` columns only for EDA and error analysis**, never as model inputs: `info_rain_mm` is not lagged
  and `info_norm_band` / `info_low` are part of the label.
- **The norm is frozen** (training days only). Don't recompute it on validate or test rows.
- **Filter on `use`**: TRUE when `y` and `U` are known and every `f_*` is present. Report how many rows it drops.
- **Rows exist only for captured updates.** About 5% of link x update pairs are missing (whole LTA pages lag), so
  a day has fewer than 192 rows per link. Never shift by row to get "the previous update"; use the `f_*` lags.
- **Training labels are slightly optimistic**: the norm includes the training days themselves (as the plan
  specifies), so the training rate of `U` is a little lower than on new days. Calibrate on `validate`.

## Population

- Links: RoadCategory [1] (expressways), 2,598 in the registry; **2,598** kept, those
  with a band in at least 90% of the 960 updates captured from
  2026-10-19 to 2026-10-23 (06:00-22:00), see `links.parquet`.
- Time: weekdays except public holidays (daytype Mon-Thu or Fri), 06:00 <= t < 22:00.
  Days in these files:
  - `train`: 16 weekdays, 2026-10-16 to 2026-11-06
  - `validate`: 1 weekday, 2026-11-10 to 2026-11-10
- Collection on the Linux PC starts 16 Oct 11:10 (the desktop's 13-16 Oct data is not used, DECISIONS.md 24 Oct),
  so training has 16 weekdays, not 19, and only 4 Fridays (16 Oct is a part day). The Friday norm
  therefore rests on about 10 snapshots per link and slot against about 35 for Mon-Thu (`n_obs` in `norm.parquet`).

## Label (PROJECT_PLAN §4.2, DECISIONS.md 13 Oct)

- norm = median band for the link, day type and 15-minute slot over the training weekdays (`norm.parquet`, with `n_obs`).
- deficit = norm - band; low = deficit >= 2.
- `U` = low at `t` and at the previous update (2 consecutive snapshots). `U` is null if either
  snapshot was not captured, so a missing snapshot hides positives and negatives alike (DECISIONS.md 11 Nov).
- `y` = `U` at `t + 15 min` (same rule). `y_h5`, `y_h10`, `y_h30`: other horizons (sensitivity).

## Features (all known at time `t`)

- `f_d0` ... `f_d30`: the link's own deficit at `t`, `t - 5`, ..., `t - 30` min. A missing update carries the last
  value forward for at most 15 min (never interpolated), so a lag can be up to 15 min older than
  its name; `f_prev_missing` = 1 if there was no update at `t - 5`. `f_d_change15` = `f_d0 - f_d15`.
- `f_up_d0` ... `f_up_d30`, `f_dn_d0` ... `f_dn_d30`: the largest deficit among the upstream / downstream links at
  the same lags. Neighbours: a link's end point within 5 m of another's start point
  (`neighbours.parquet`, 2,596 pairs). `f_up_none` / `f_dn_none` = 1 if the link has none (values then 0).
- `f_rain15`, `f_rain30`: rainfall (mm) at the nearest NEA station over the 15 / 30 min ending at `t - 5`
  (allowance for publication lag). `f_rain15_missing` / `f_rain30_missing` = 1 if the station had no reading in
  that window (its total is then 0).
- `f_slot15` (15-minute slot of the day; 24-87 for 06:00-22:00), `f_fri` (1 = Friday).
- `f_conn_in_d0` ... `f_conn_in_d30`, `f_conn_out_d0` ... `f_conn_out_d30`: the largest deficit among the roads that
  lead into / out of this link (slip roads, arterials, ...; 621 links joining 559 expressway links,
  `connectors.parquet`), against their own frozen norm (`connector_norm.parquet`), same lags and carry rule.
  `f_conn_in_none` / `f_conn_out_none` = 1 if the link has none; `f_conn_in_missing` / `f_conn_out_missing` = 1 if one
  lag had no value. Values are then 0. These inputs are optional: compare models with and without them.

## Other columns

| Column | Meaning |
|---|---|
| `t` | LTA update time (Singapore time, no zone), on the 5-minute grid |
| `date`, `daytype`, `slot15` | date, `Mon-Thu` / `Fri`, 15-minute slot (for folds, B1 and the day bootstrap) |
| `LinkID`, `RoadName` | LTA link and its road |
| `heldout_road`, `use` | see Rules |
| `info_band` | speed band 1-8 (8 = 70 km/h or more) |
| `info_norm_band`, `info_low` | frozen norm (may end in .5) and low at `t` |
| `info_rain_mm` | NEA reading timestamped `t` (5 min ending at `t`); not lagged |
| `info_station_id`, `info_station_km` | nearest rain station and its distance from the link midpoint |
| `info_weekday`, `info_school_period`, `info_olevel_venue_schools_ended` | calendar (1 = Monday; drift check before/after 23 Oct) |
| `info_t_from_retrieval` | `t` is our retrieval time because LTA gave none |

Other files: `links.parquet` (coordinates, `road`, `presence_week1`, `in_population`, `heldout_road`),
`neighbours.parquet`, `norm.parquet`, `connectors.parquet` (`LinkID` of the joining road, `joins` = expressway link,
`kind` = into / out_of, its road name and category), `connector_norm.parquet`, `days.csv` (per day: `updates_06_22` of 192, `rows`, `share_use`),
`incidents.parquet` (for label audit and error analysis; as a predictor only with incidents reported before `t`,
never "Heavy Traffic").

Contains information from LTA DataMall, NEA and MOM accessed from data.gov.sg, made available under the
Singapore Open Data Licence version 1.0 (https://data.gov.sg/open-data-licence).
