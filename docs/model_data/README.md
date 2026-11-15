# SLDS 1.3 model data (data version 4)

Built 2026-11-15 09:04 (git `79393d2-modified`) by `analysis/build_data.py`, from
the raw LTA files. Days 2026-10-16 to 2026-11-14. New days are added with the
same version number. A change of rule raises the version (see "Changes" at the end).

## What is in this folder

| File | What it is |
|---|---|
| `train.parquet` | The rows to train on: 6,401,116 rows with `split = "train"` and 1,647,272 with `split = "validate"`. Weekdays only (Monday to Friday, no public holidays), as in our proposal. Only usable rows, only the columns models need. |
| `test.parquet` | The test week (Mon 16 to Fri 20 Nov). Added after the test week ends and the plan is frozen. Do not open it before then. |
| `README.md` | This file. |
| `extra/` | Everything else. You do not need it to train a model. |

In `extra/`:

| File | What it is |
|---|---|
| `train_sample.parquet` | The `train.parquet` rows of 300 links that are not on a held-out road (926,876 rows). Use it to test your code fast. |
| `train_lodo.parquet` | The `train` days again, but each day's normal level is built without that day. Same columns as `train.parquet`. For the plan's leave-own-day-out check (see "Good to know"). |
| `full_table.parquet` | Every row of the train and validate days, for exploring: every day of the week (`in_population` = FALSE on Saturdays, Sundays and public holidays), also the rows we cannot use (`use` = FALSE), with `y_h5`, `y_h10`, `y_h30` (the answer 5, 10, 30 minutes ahead), `f_sat`, `f_sun`, `f_holiday` and `info_` columns. |
| `test_full.parquet` | The same for the test week (later). |
| `links.parquet` | One row per link: road, held-out road or not, coordinates, rain station, number of neighbours and joining roads. |
| `neighbours.parquet`, `connectors.parquet` | Which link follows which; which roads join which link. |
| `norm.parquet`, `connector_norm.parquet` | The normal levels (`n_obs` = how many bands each median uses). |
| `days.csv` | One row per day: in the proposal's days or not, updates captured, usable rows, rain coverage. |
| `incidents.parquet` | LTA incident messages (accidents, breakdowns), for checking errors. Not an input. |
| `build_info.json`, `SHA256SUMS.txt` | How the files were built (every check and its result) and their checksums. |

## Quick start (R)

`train.parquet` has 8,048,388 rows and needs about 3 GB of memory in R. Start with
`extra/train_sample.parquet`. For the full data, read only the columns you need.

```r
library(arrow); library(dplyr)
d   <- read_parquet("extra/train_sample.parquet")   # later: read_parquet("train.parquet")
d   <- d |> filter(!heldout_road)          # AYE and CTE: only for the transfer check in the test week
fit <- d |> filter(split == "train")       # fit and tune the models on these rows
val <- d |> filter(split == "validate")    # choose the final model and calibrate on these rows
x   <- fit |> select(starts_with("f_"))                            # all inputs, no missing values
x0  <- fit |> select(starts_with("f_"), -starts_with("f_conn_"))   # the same without the joining roads
y   <- fit$y                               # TRUE = unusual 15 minutes later
onset <- !fit$U                            # the main score uses these rows: normal now
```

## One row

One row is one link (about 140 m of road, one direction) at one LTA update `t` (every 5 minutes), from
06:00 to 22:00, Monday to Friday except public holidays (our proposal's days). There are
2,598 links: the 10 expressways, plus 2 short flyovers (Aljunied West, Kallang Bahru) that LTA also lists as
expressway. Column `road` has 12 values.

| Split | Dates | Weekdays used | Use |
|---|---|---|---|
| `train` | Fri 16 Oct to Fri 06 Nov | 16 | fit and tune the models; the normal level comes from these days only |
| `validate` | Sat 07 Nov to Fri 13 Nov | 4 | choose the final model, calibrate, set the alert budget k |
| `test` | Sat 14 Nov to Fri 20 Nov (not finished yet) | 0 | final test, once, after the plan is frozen |

Our proposal's training period starts on Tue 13 Oct, but our data starts on Fri 16 Oct (collection from 11:10
that day). Mon 9 Nov (the Deepavali holiday) is not used.

## Held-out roads (transfer check)

`heldout_road` = TRUE for the 689 links of the Ayer Rajah Expressway and Central Expressway. They were drawn at random with
a fixed seed before any model was fitted (the same draw as data versions 1 and 2). Never use their rows to fit,
tune, choose or calibrate a model. In the test week, score them on their own: does a model trained on the other
roads work on roads it has never seen?

## What we predict

```
time:     t-30   t-25   t-20   t-15   t-10   t-5    t   |  t+5    t+10   t+15
inputs:   f_d30  f_d25  f_d20  f_d15  f_d10  f_d5  f_d0 |
U (now):                                    low    low  |
y:                                                      |         low    low
```

- **Normal level** (`extra/norm.parquet`): the median speed band of the link for that 15-minute slot and day
  type, from the `train` days only. It never changes after that. The main files hold weekdays only, so they use
  the `weekday` level (Monday to Friday). The `saturday` and `sunday_or_holiday` levels are only for the extra
  rows in `extra/full_table.parquet`.
- **Drop** = normal level minus the speed band. A drop of 2 means 2 bands (20 km/h) slower than normal. It goes
  from -7 to 7, can end in .5, and is below 0 when traffic is faster than normal.
- **Low** = a drop of 2 or more.
- **`U`** (unusual now) = low now and 5 minutes ago. `U` is unknown when either update is missing; those rows
  are not in `train.parquet`.
- **`y`** (the answer) = `U` 15 minutes later. In `train`, 2.3% of rows are TRUE.
- **Main score**: PR-AUC on the rows that are normal now (`U == FALSE`), in the test week. On those rows only
  1.0% (train) and 1.3% (validate) become unusual. That is also the PR-AUC of a model that guesses.

## The inputs (`f_` columns, all known at time `t`)

| Columns | Meaning |
|---|---|
| `f_d0`, `f_d5`, `f_d10`, `f_d15`, `f_d20`, `f_d25`, `f_d30` | the link's drop now, 5, 10, ... 30 minutes ago |
| `f_d_change15` | `f_d0 - f_d15`: is the drop growing? |
| `f_n_filled` | how many of the 7 drops above reused the update 5 minutes before (because the real one was missing) |
| `f_up_d0` ... `f_up_d30` | the biggest drop among the links just before this one (upstream), same times |
| `f_dn_d0` ... `f_dn_d30` | the same for the links just after it (downstream); slowdowns move backwards |
| `f_up_none`, `f_dn_none` | 1 = the link has no link before / after it (its values are then 0) |
| `f_rain15`, `f_rain30` | rain (mm) at the nearest station in the 15 / 30 minutes up to 5 minutes ago (0 = no rain) |
| `f_rain15_missing`, `f_rain30_missing` | 1 = the station had no reading at all in that time (the value is then 0) |
| `f_slot15` | time of day in 15-minute slots: 24 = 06:00-06:14, ..., 87 = 21:45-21:59 |
| `f_mon` ... `f_fri` | day of the week, one-hot (exactly one is 1) |
| `f_conn_in_d0` ... `f_conn_in_d30` | the biggest drop among the roads leading into the link (slip roads, main roads), against their own normal level |
| `f_conn_out_d0` ... `f_conn_out_d30` | the same for the roads leading out of it |
| `f_conn_in_none`, `f_conn_out_none` | 1 = no such road (values then 0) |
| `f_conn_in_missing`, `f_conn_out_missing` | 1 = a road exists but a value was missing (then 0) |

The `f_conn_` inputs are extra: train every model with and without them (`x` and `x0` above), on the same rows.

Other columns: `LinkID`, `road`, `heldout_road`, `t` (Singapore time), `date`, `daytype` (always `weekday`
here), `split`, `y`, `U`. Rows are in the order split, link, time.

## Rules

- Use only the `f_` columns as inputs. Never use `y`, `U`, `split`, `heldout_road` or anything from `extra/` as an input.
- Never fit, tune, choose or calibrate on rows with `heldout_road == TRUE`.
- Fit on `split == "train"`. Tune by forward-chaining inside the train days: fit on earlier days, check on
  later days, never the other way round. Use `split == "validate"` to choose the final model, calibrate and set
  the alert budget *k*. Do not open `test.parquet` before the plan is frozen.
- Do not take "the row above" as the previous update. Use `f_d5`, `f_d10`, ...
- Set a random seed. For `glmnet`, treat `f_slot15` as a curve or as hour groups, not a straight line. For
  `ranger` on all rows, you may use fewer FALSE rows (fixed seed) and then calibrate on `validate`.
- Write the data version (4) next to every result.

## Good to know

- A neighbour's or joining road's value can also be a reused one (at most 5 minutes old), like `f_d5` ... `f_d30`.
- A rain total skips missing readings; the `_missing` flag is 1 only when all readings in the window are missing.
- In `train.parquet`, a train day is one of the days its own normal level is built from, so its labels are a
  little easier than on new days. `extra/train_lodo.parquet` has the same days with a normal level built without
  that day: share of `U` 2.3% in `train`, 2.4% in `train_lodo`, 2.4% in `validate`.
  Fit a model on both and compare the validation scores (PROJECT_PLAN §4.9).
- Our data arrives a median of 4 minutes after `t`. A warning 15 minutes ahead of `t` gives about 11 minutes in practice.
- Days with fewer usable rows (see `extra/days.csv`): Fri 16 Oct (collection started 11:10) and Thu 12 Nov (our
  second collector was down from 10:12 to 14 Nov 17:15).

## Changes

- **v4** (2026-11-14):
  - Back to the approved proposal. The main files (train.parquet, test.parquet) hold weekdays only: Monday to Friday, no public holidays. Weekend and holiday rows are only in extra/full_table.parquet (in_population = FALSE).
  - Splits as in the proposal: train 16 Oct - 6 Nov (the proposal says 13 Oct; our data starts 16 Oct), validate 7 - 13 Nov, test 14 - 20 Nov. For weekday rows the normal level, labels and inputs are the same as in v3.
  - Held-out roads again: AYE and CTE (column heldout_road; the same seeded draw as v1 and v2). Never fit, tune or calibrate on them; score them in the test week.
  - Rain: station S35 now has readings in at least 80% of the slots on every training day, so 73 links (PIE, AYE) take their rain from it.
  - f_sat, f_sun and f_holiday are not in the main files (always 0 there); extra/full_table.parquet still has them.
- **v3** (2026-11-14):
  - New program, built straight from the raw files: build_data.py replaces 04_process.ipynb and build_model_data.py.
  - Weekends and public holidays are now in. Normal level per day type: weekday, saturday, sunday_or_holiday.
  - New inputs f_mon ... f_sun and f_holiday (f_fri is gone).
  - A missing update is reused for at most 5 minutes (was 15). f_n_filled counts reused values. f_prev_missing is gone (it was always 0 on usable rows).
  - No roads are held out. Splits: train 16 Oct - 8 Nov, validate 9 - 15 Nov, test 16 - 22 Nov.
  - Rain comes from the nearest station with readings in at least 80% of the 5-minute slots on every training day, and the rain totals are exact (0 means no rain).
  - New folder layout: README.md, train.parquet and test.parquet on top, the rest in extra/. New: extra/train_lodo.parquet for the plan's leave-own-day-out check.
- **v2** (2026-11-11): Added f_conn_* inputs: links that join an expressway (slip roads, arterials, ...), so models can be compared with and without them. Rows, labels and other columns unchanged.
- **v1** (2026-11-11): First release: 2,598 expressway links, strict label rule, own/neighbour/rain features, held-out roads AYE + CTE (pending team confirmation).

## Check your download

Inside the folder with the files: `sha256sum -c --ignore-missing extra/SHA256SUMS.txt` (every file says OK).
The same list is in git: `docs/model_data/SHA256SUMS.txt`. On Windows: `Get-FileHash <file> -Algorithm SHA256`.

Contains information from LTA DataMall, NEA and MOM, accessed from data.gov.sg and made available under the
Singapore Open Data Licence version 1.0 (https://data.gov.sg/open-data-licence).
