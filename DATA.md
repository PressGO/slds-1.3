# Data sheet (data version 4)

This page answers the data documentation list of the project brief (section 3.2) in one place. Each answer names
the file that holds the detail. Numbers come from the build record (`docs/model_data/build_info.json`, built
18 Nov 2026) and from the Part 1 notebook (`notebooks/part1_data_collection_and_transformation.ipynb`).

## 1. Sources, access dates, licence, links

| Source | What we take from it | How it is retrieved | Access dates |
|---|---|---|---|
| LTA DataMall, Traffic Speed Bands (API User Guide v6.10, section 2.19): `https://datamall2.mytransport.sg/ltaodataservice/v4/TrafficSpeedBands` | a speed band (1 = 0-9 km/h ... 8 = 70 km/h or more) for each of about 144,000 road links, about every 5 minutes; road name, category and coordinates of each link | `analysis/lta_collector.py`, two collectors with two API keys, running without a break | source check 13 Oct 2026; collected from 16 Oct 2026 |
| LTA DataMall, other feeds (traffic incidents, VMS, estimated travel times, road works, road openings) and PUB flood alerts | saved for interpreting events; **never a model input** | the same collectors | from 16 Oct 2026 |
| NEA rainfall, 5-minute totals per station: `https://api-open.data.gov.sg/v2/real-time/api/rainfall` | rain at the station nearest to each link | `analysis/get_context_data.py`, one download per date | each night for the day before |
| MOM public holidays 2026 (data.gov.sg dataset `d_149b61ad0a22f61c09dc80f2df5bbec8`) | which days are public holidays | `analysis/get_context_data.py` | first on 13 Oct 2026; refreshed with each nightly run |
| MOE school terms and LTA F1 road closures | calendar columns kept for information | typed in from the official pages named in `analysis/get_context_data.py` | 13 Oct 2026 (MOE), 10 Oct 2026 (F1) |

**Licence.** Contains information from LTA DataMall and from NEA rainfall and MOM public holiday data accessed
from data.gov.sg, which are made available under the terms of the Singapore Open Data Licence version 1.0
(https://data.gov.sg/open-data-licence).

## 2. Unit of observation and target population

- **Unit:** one expressway link (one direction, about 140 m of road) at one LTA update (every 5 minutes).
- **Population:** the 2,598 links that LTA lists as expressway (road category 1: the 10 expressways and 2 short
  flyovers), from 06:00 to 22:00, Monday to Friday, without public holidays.
- **Outcome:** `y` = the link is unusually slow 15 minutes later. "Unusually slow" (`U`) = 2 or more bands below the
  link's normal level, now and 5 minutes ago. The normal level is the link's median band for that 15-minute slot
  over the train weekdays.

## 3. Inclusion and exclusion rules

| Rule | Value | Where |
|---|---|---|
| Links | road category 1, with a band at 90% or more of the updates of 19-23 Oct. All 2,598 pass | `docs/data_rules.md` rule 2 |
| Days | Monday to Friday without public holidays (Mon 9 Nov is out). Weekends and holidays are built too, but kept only in `extra/full_table.parquet` | rules 3-4 |
| Hours | 06:00 to 21:55 (192 updates a day) | rule 18 |
| Splits | train 16 Oct - 6 Nov (16 weekdays); validation 7 - 13 Nov (4 weekdays); test 14 - 20 Nov (5 weekdays) | rule 4 |
| Usable rows | the outcome, `U` and every core input are known. A missing update is reused for at most 5 minutes | rules 11, 19 |
| Held-out roads | AYE and CTE (689 links), drawn once with a fixed seed. They are never used to fit, tune or calibrate | `analysis/data_settings.py` |

Result: `train.parquet` has 8,048,388 usable rows (6,401,116 train and 1,647,272 validation) and 62 columns.

## 4. Data dictionary

`docs/model_data/README.md` explains every column ("The inputs" and "What we predict"). Step 6 of the Part 1
notebook prints the same dictionary from the data, with each column's type, range and number of missing values
(none in `train.parquet`).

## 5. How the table is built (joins, filters, derived variables)

Every step is a function in `analysis/data_steps.py`; `docs/data_rules.md` states each rule in words.

| Step | What happens | Rules |
|---|---|---|
| Clean the speed bands | rows of both collectors are stacked; a link and update fetched more than once keeps the earliest fetch; a band outside 1-8 is left empty | 1 |
| Link list | latest name, category and coordinates of each link, from the hourly snapshots | 2 |
| Neighbours | link B is downstream of link A when B starts within 5 m of where A ends | 13 |
| Joining roads | a non-expressway link that ends (or starts) within 5 m of an expressway link's start (or end) | 15 |
| Rain station | the nearest station that has readings in 80% or more of the 5-minute slots on every train day | 16 |
| Normal level | median band per link, day type and 15-minute slot, from the train days only, then frozen | 6 |
| Drop, low, U, y | drop = normal level - band; low = drop of 2 or more; U = low now and 5 minutes ago; y = U 15 minutes later | 7-10 |
| Inputs | the link's drops now and up to 30 minutes ago; the largest drop on the links just upstream and downstream, and on the joining roads; rain in the last 15 and 30 minutes; time of day; day of week | 11-17 |
| Files | usable rows of the population days go to `train.parquet`; everything else to `extra/` | 18-22 |

## 6. Quality checks

- **Missing data.** On the 29 train and validation days the median day has a band for 95.7% of the link-updates
  between 06:00 and 22:00. Two days are weak:
  - Fri 16 Oct (55%): collection started at 11:10.
  - Thu 12 Nov (91%): the second collector was down.

  Missing updates are never filled in beyond 5 minutes; rows that need one are left out.
- **Duplicates.** 89% of the kept link-updates were fetched more than once. The copies never disagree (0 conflicts
  in 22.3 million repeats).
- **Impossible values.** No band outside 1-8, no row without an update time, no negative rainfall.
- **Measurement.**
  - Bands are 10 km/h wide, and band 8 means "70 km/h or more".
  - LTA serves its pages from servers that are not in sync, so each row carries its own update time.
  - Our data arrive a median of 4 minutes after the update time.
- **The build checks itself.** 114 checks, all passed (`docs/model_data/build_info.json`). It stops at the first
  failed check.
- **Tests.** 25 unit tests of the steps on small made-up data (`analysis/test_data_steps.py`).
- **Independent checks.**
  - `analysis/verify_data.py` recomputes sample rows from the raw files in a different way.
  - The Part 1 notebook rebuilds all 29 days from the raw files and finds every row and column equal to the build's
    tables.

## 7. Snapshot, and how to recreate the data

- LTA serves only the current state, so **the raw files cannot be downloaded again**. They are archived every night
  to a Google Drive folder (`SLDS_1.3_raw`): one file per collector and day, with `MANIFEST.csv` and
  `SHA256SUMS.txt`. `analysis/verify_raw.py` checks a download and unpacks it.
- The model tables are on the Releases page of the repository (release `data-v4`, two zip files; see
  `docs/REPRODUCE.md`, "Data") and in the Drive folder `SLDS_1.3_processed`; their checksums are in
  `docs/model_data/SHA256SUMS.txt`.
- From the raw files, `./build_processed.sh --no-upload` recreates the tables from scratch: the same raw files always
  give the same tables.

## 8. Limitations

- **Coverage:** one season only, 16 Oct to 20 Nov 2026, school-term weekdays; 16 train days.
- **Proxy:** a speed band is LTA's estimate for a link, in 10 km/h steps. There are no traffic volumes. How LTA
  computes the bands is not published.
- **Label:**
  - "Unusual" is relative to a median of 16 days.
  - Short dips count as much as long slowdowns.
  - A link that is normally at band 1-2 cannot show a 2-band drop (0.6% of weekday cells).
  - A train day is part of its own normal level, so its labels are a little easier than on new days;
    `extra/train_lodo.parquet` exists to check this.
- **Sampling:** two collectors on one PC. A gap of both at once loses those updates for good.
- **Incidents** are not observed in the inputs. Accidents and breakdowns are saved only to interpret results.

## 9. Confidential or personal information

None. The data are speed bands of road links, rainfall at weather stations, and calendar dates. No person, vehicle
or device is identified. The API keys are read from a local file that is never committed (`.gitignore`), and they
are masked in every log.
