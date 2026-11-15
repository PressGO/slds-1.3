# The rules behind the model tables (data version 4)

These are the rules the model tables follow, written so that someone can recompute any row without reading the
pipeline code. `analysis/verify_data.py` does exactly that for a sample of rows, straight from the raw files; it
was written from this text only. The pipeline itself is `analysis/build_data.py` with `analysis/data_steps.py`;
the numbers are in `analysis/data_settings.py`, and why each rule was chosen is in `DECISIONS.md`.

All times are Singapore local time without a zone. "5 min" steps: LTA updates every 5 minutes, at :00, :05, ...

## Raw inputs (read only)

- Speed bands, two collectors: `data_raw/speedbands/<YYYY-MM-DD>/sb_<YYYYMMDD>_<HHMMSS>.csv.gz` and
  `data_raw_expressway/speedbands/<YYYY-MM-DD>/sb_<YYYYMMDD>_<HHMMSS>.csv.gz`. CSV columns: `retrieved_at`
  (our fetch time, e.g. `2026-11-10T00:01:50+0800`), `last_updated` (LTA's update time of that row, e.g.
  `2026-11-10 00:00:00`; this is the row's time t), `LinkID` (string), `SpeedBand` (1-8). The folder date and
  file name give the fetch date and time. A row with time t can be in a file fetched up to ~40 min later, so
  rows of day D can sit in files of day D+1. Files fetched up to 01:00 after the last finished day are read.
- Link attributes: `data_raw/speedbands_raw/<YYYY-MM-DD>/sbraw_*.jsonl.gz` up to the last finished day, one JSON
  object per line (`retrieved_at`, `page`, `body`); `body` is a JSON string whose `value` is a list of records
  with `LinkID`, `RoadName`, `RoadCategory` (string, "1" = expressway), `StartLon`, `StartLat`, `EndLon`, `EndLat`
  (strings). Each link's attributes come from the latest of those snapshots (latest `retrieved_at`).
- Rain: `data_processed/rainfall_5min.csv.gz` (`timestamp` like `2026-10-13T00:00:00+08:00`, `station_id`,
  `rain_mm` = rain in the 5 minutes ending at timestamp). Stations: `data_processed/rain_stations.csv`
  (`station_id`, `lat`, `lon`). Calendar: `data_processed/calendar_2026.csv` (`date`, `is_public_holiday`).

## Definitions

1. **Band** of link l at time t: from every speed-band row of both collectors with that LinkID and
   `last_updated` = t. If there are several, take the one with the earliest `retrieved_at` (a tie goes to the
   earlier file name, `data_raw` before `data_raw_expressway`; the copies have never disagreed).
2. **Expressway links**: RoadCategory 1. There must be 2,598; all of them are in the tables.
2a. **Held-out roads** (the proposal's transfer check): take the `road` values (rule 20) of the expressway links,
   without ALJUNIED WEST FLYOVER and KALLANG BAHRU FLYOVER, as a list sorted alphabetically (10 roads), and draw
   2 with Python's `random.Random(20261113).sample(that_list, 2)`. This gives AYER RAJAH EXPRESSWAY and CENTRAL
   EXPRESSWAY. `heldout_road` = TRUE for every link on those roads (689 links), else FALSE.
3. **Day type** of a date: `sunday_or_holiday` if it is a public holiday or a Sunday; `saturday` if Saturday;
   else `weekday`.
4. **Split** by the date of t: `train` 2026-10-16 to 2026-11-06; `validate` 2026-11-07 to 2026-11-13;
   `test` 2026-11-14 to 2026-11-20 (the proposal's split; its train starts 13 Oct, our data 16 Oct).
4a. **Population days** (the proposal's days): `in_population` = TRUE when the day type is `weekday` (Monday to
   Friday and not a public holiday), else FALSE.
5. **Slot** of t: hour * 4 + minute // 15 (0-95).
6. **Normal level** norm(l, daytype, slot) = median of all bands of link l at the times t (any hour of the day)
   whose date is a train day of that day type and whose slot is that slot. Median of an even count = mean of
   the two middle values.
7. **Deficit** (the drop) d(l, t) = norm(l, daytype(date of t), slot(t)) - band(l, t). Unknown if the band at t
   is missing or the norm is missing.
8. **low**(l, t) = d(l, t) >= 2 (unknown if d unknown).
9. **U**(l, t) = low(l, t) AND low(l, t - 5 min). Null (unknown) if either is unknown.
10. **y**(l, t) = U(l, t + 15 min). In the full table also `y_h5`, `y_h10`, `y_h30` = U at t + 5, 10, 30 min.
11. **Reused value** dfill(l, s) = d(l, s) if known; else d(l, s - 5 min) if known; else unknown.
    (A missing update reuses the previous update's value, never more than 5 minutes old.)
12. **f_d{k}**(l, t) = dfill(l, t - k min), k = 0, 5, 10, 15, 20, 25, 30. **f_n_filled** = how many of those 7
    have d unknown but dfill known. **f_d_change15** = f_d0 - f_d15.
13. **Neighbours** among expressway links: B is downstream of A when the distance from A's end point to B's
    start point is <= 5 m (A != B). Distance in metres on a flat grid: x = lon * 111320 * cos(1.35 degrees),
    y = lat * 111320; Euclidean.
14. **f_dn_d{k}**(l, t) = the largest dfill(B, t - k) over the downstream neighbours B of l, ignoring unknown
    values; unknown if all are unknown. **f_up_d{k}**: the same over the upstream neighbours (links A that have
    l downstream). If l has no neighbour on that side: f_dn_none / f_up_none = 1 and the 7 values are 0;
    otherwise the flag is 0.
15. **Joining roads**: a non-expressway link C leads `into` expressway link l if C's end point is within 5 m of
    l's start point; `out_of` l if C's start point is within 5 m of l's end point (same distance as 13).
    Their own normal level and deficit are defined as in 6-7, from their own bands, and dfill as in 11.
    **f_conn_in_d{k}**(l, t) = the largest dfill(C, t - k) over the `into` roads C, ignoring unknown values;
    unknown if all are unknown. If l has none: f_conn_in_none = 1 and the values are 0. If it has some and at
    least one of the 7 values is unknown: f_conn_in_missing = 1 and the unknown values are 0 (else
    f_conn_in_missing = 0). The same for `out`.
16. **Rain station** of a link: the station nearest to the link's midpoint ((StartLat + EndLat) / 2,
    (StartLon + EndLon) / 2) by great-circle (haversine) distance with R = 6371 km, among the stations that have
    readings in at least 80% of the 288 five-minute slots (231 or more readings, each counted on the date of its
    timestamp) on EVERY train day. **f_rain15**(l, t) = sum of that station's readings with timestamps
    t - 5, t - 10, t - 15 min (missing readings skipped); **f_rain30** = readings at t - 5 ... t - 30 (6).
    If all readings in a window are missing: the total is 0 and f_rain15_missing / f_rain30_missing = 1.
    Rain totals are exact: a window with no rain is exactly 0.0, and every total is a whole number of tenths
    of a mm.
17. **f_slot15** = slot(t). **f_mon** ... **f_sun** = one-hot of the weekday of t. **f_holiday** = 1 on a
    public holiday. The main files (train.parquet, test.parquet, train_lodo.parquet) leave out f_sat, f_sun and
    f_holiday (always 0 on population days); the full tables keep them.
18. **Rows** (of the full tables): every expressway link x every t from 06:00 to 21:55 on every finished day of
    the splits, every day of the week. A day is finished when
    the rainfall table has at least one reading timestamped 23:55 that day and it is 02:00 the next day. Rows exist also when the update is
    missing.
19. **use** = y known AND U known AND every one of these known: f_d0 ... f_d30, f_d_change15, f_n_filled,
    f_up_d*, f_dn_d*, f_up_none, f_dn_none, rain inputs and flags, f_slot15, f_mon ... f_sun, f_holiday.
    (The f_conn_* inputs are not required.)
20. **Files** in `data_processed/model/`: `train.parquet` = the rows with `use` AND `in_population` of the train
    and validate days, with LinkID, road, heldout_road, t, date, daytype, split, y, U and the f_ columns (without
    the three of rule 17); `extra/full_table.parquet` = every row of those days (all days of the week) with
    the same columns plus `in_population`, `use`, `y_h*`, f_sat, f_sun, f_holiday and `info_*` columns
    (`info_band` = band at t, `info_norm_band`, `info_deficit` = d at t, `info_low`, `info_rain_mm` = the
    reading at t, `info_station_id`, `info_station_km`, `info_school_period` = the calendar's school period,
    `info_retrieved` = the `retrieved_at` of the band chosen by rule 1); `test.parquet` and `extra/test_full.parquet`
    the same for the test days once they exist;
    `extra/norm.parquet` (LinkID, daytype, slot15, norm_band, n_obs = bands in the median, n_days = train days
    with a band in the cell); `extra/connector_norm.parquet` (the same for the joining roads);
    `extra/neighbours.parquet` (LinkID, downstream, gap_m); `extra/connectors.parquet` (LinkID = joining road,
    joins = expressway link, kind = into / out_of); `extra/links.parquet` (one row per expressway link, with
    station_id, station_km and heldout_road); `road` = RoadName, with the KPE tunnel counted as KPE.
21. **Rounding in the output tables**: `station_km` and `info_station_km` are rounded to 3 decimals and `gap_m`
    (in neighbours.parquet and connectors.parquet) to 2 decimals.
22. **extra/train_lodo.parquet**: the train days that are population days (rule 4a) again, same columns as
    train.parquet, but for a row on train day d every normal level (of the link, its neighbours and its joining
    roads) is the median over the train days of that day type EXCEPT d (rules 6 and 15 with day d left out).
    Everything else (rules 7-19) is the same, computed with that normal level. It holds the rows with use ==
    TRUE of those days under that rule.
