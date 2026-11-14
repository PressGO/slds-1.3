"""data_settings.py - every setting of the data pipeline (data version 3), in one place.

Each value is a decision. Change one only after a dated entry in DECISIONS.md (and CHANGELOG.md on the
Linux PC), then raise DATA_VERSION and add a line to DATA_CHANGES. Used by build_data.py, data_steps.py and
verify_data.py.
"""

from datetime import date

# ---- data version: raise it when a rule, setting or bug fix changes what the tables mean ----
# (not when new days are only added). Teammates compare it with their copy (README.md, build_info.json).
DATA_VERSION = "3"
DATA_CHANGES = [  # newest first; a list = one bullet each in README.md
    ("3", "2026-11-14", [
        "New program, built straight from the raw files: build_data.py replaces 04_process.ipynb and "
        "build_model_data.py.",
        "Weekends and public holidays are now in. Normal level per day type: weekday, saturday, sunday_or_holiday.",
        "New inputs f_mon ... f_sun and f_holiday (f_fri is gone).",
        "A missing update is reused for at most 5 minutes (was 15). f_n_filled counts reused values. "
        "f_prev_missing is gone (it was always 0 on usable rows).",
        "No roads are held out. Splits: train 16 Oct - 8 Nov, validate 9 - 15 Nov, test 16 - 22 Nov.",
        "Rain comes from the nearest station with readings in at least 80% of the 5-minute slots on every "
        "training day, and the rain totals are exact (0 means no rain).",
        "New folder layout: README.md, train.parquet and test.parquet on top, the rest in extra/. New: "
        "extra/train_lodo.parquet for the plan's leave-own-day-out check.",
    ]),
    ("2", "2026-11-11", "Added f_conn_* inputs: links that join an expressway (slip roads, arterials, ...), so "
                        "models can be compared with and without them. Rows, labels and other columns unchanged."),
    ("1", "2026-11-11", "First release: 2,598 expressway links, strict label rule, own/neighbour/rain features, "
                        "held-out roads AYE + CTE (pending team confirmation)."),
]

# ---- raw data (DECISIONS.md 16 Oct, 24 Oct) ----
# Both collectors on the Linux PC. The desktop's 14-16 Oct copy is not used (DECISIONS.md 24 Oct).
SPEED_SOURCES = ("data_raw", "data_raw_expressway")   # each has speedbands/<date>/sb_*.csv.gz
REGISTRY_SOURCE = "data_raw"                          # speedbands_raw/<date>/sbraw_*.jsonl.gz: hourly full snapshots
INCIDENT_SOURCE = "data_raw"                          # feeds/incidents/<date>/incidents_*.jsonl.gz
LATE_ROWS_MIN = 60    # read files retrieved up to 60 min after midnight: an update can arrive up to ~40 min late
FINISHED_AFTER_H = 2  # day D is finished at D+1 02:00 (all late rows are in) and when its rainfall is downloaded
BAD_ROWS_MAX_SHARE = 0.001  # rows without LTA's time (dropped) or with a band outside 1-8 (band empty): the build
                            # goes on below 0.1% of rows read and stops above it

# ---- links (DECISIONS.md 14 Oct, 11 Nov) ----
EXPRESSWAY_CATEGORY = 1                 # LTA RoadCategory 1 = expressways
EXPECTED_EXPRESSWAY_LINKS = 2598        # [L] in DECISIONS.md; the build stops if the registry differs
PRESENCE_DAYS = (date(2026, 10, 19), date(2026, 10, 23))   # first full week of collection
PRESENCE_MIN = 0.90                     # keep links with a band at >= 90% of the updates captured then
ROAD_GROUPS = {"KALLANG PAYA LEBAR EXPRESSWAY TUNNEL": "KALLANG PAYA LEBAR EXPRESSWAY"}
NEIGHBOUR_TOL_M = 5                     # B is downstream of A when B starts within 5 m of where A ends
CONNECTOR_TOL_M = 5                     # a road joins an expressway link within 5 m (end -> start, end -> start)

# ---- rows (DECISIONS.md 14 Nov) ----
HOUR_FROM, HOUR_TO = 6, 22              # rows: 06:00 <= t < 22:00 (192 updates a day), every day
SPLITS = {                              # by the date of t
    "train": (date(2026, 10, 16), date(2026, 11, 8)),
    "validate": (date(2026, 11, 9), date(2026, 11, 15)),
    "test": (date(2026, 11, 16), date(2026, 11, 22)),
}
NORM_SPLIT = "train"                    # the normal level is built from these days only, then frozen
DAYTYPES = ("weekday", "saturday", "sunday_or_holiday")   # Mon-Fri / Sat / Sun or public holiday

# ---- label (DECISIONS.md 13 Oct, 11 Nov) ----
THRESHOLD = 2                           # low: normal level - band >= 2 bands
CONSECUTIVE = 2                         # unusual (U): low at t and at t - 5 min; null if either is unknown
HORIZON = 15                            # y = U(t + 15 min)
EXTRA_HORIZONS = (5, 10, 30)            # y_h5, y_h10, y_h30 (sensitivity; in extra/full_table.parquet)

# ---- inputs (DECISIONS.md 11 Nov, 14 Nov) ----
STEP_MIN = 5                            # LTA updates every 5 min; t is on this grid
LAGS = (0, 5, 10, 15, 20, 25, 30)       # minutes back for the link, its neighbours and joining roads
CARRY_MAX = 5                           # a missing update reuses the last value for at most 5 min
RAIN_LAG = 5                            # rain inputs use readings timestamped t - 5 min or earlier
RAIN_WINDOWS = {"f_rain15": 15, "f_rain30": 30}   # total rain over the 15 / 30 min ending at t - 5
RAIN_STATION_MIN_SHARE = 0.80   # a link's station: the nearest one with readings in >= 80% of the 5-min slots on
                                # every training day (81 of 90 stations; a typical station-day has ~91%)
RAIN_DAY_MIN_SHARE = 0.80       # every finished day needs readings in >= 80% of the used stations' 5-min slots,
                                # else the build stops (a partly downloaded rainfall day)
WEEKDAY_COLUMNS = ("f_mon", "f_tue", "f_wed", "f_thu", "f_fri", "f_sat", "f_sun")   # one-hot, Monday first

# ---- files ----
SAMPLE_LINKS, SAMPLE_SEED = 300, 1      # extra/train_sample.parquet: 300 whole links, for testing code
SHARE_TEST_ENV = "SHARE_TEST"           # test files go to Drive only when SHARE_TEST=1 (after the plan freeze)
