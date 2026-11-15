# data_settings.R - every setting of the data pipeline (data version 4), in one place.
#
# The R version of analysis/data_settings.py, with the same values. The Python build
# (analysis/build_data.py) makes the team's data; this R version rebuilds the same tables for
# the submission, and R/compare_with_python.R checks that both give the same values.
# Each value is a decision (DECISIONS.md). Change it in both languages, never in one only.
#
# AI disclosure: translated from the Python version with Claude (Anthropic) on 15 Nov 2026; log in AI_USE.md.

DATA_VERSION <- "4"

# ---- raw data (DECISIONS.md 16 Oct, 24 Oct) ----
SPEED_SOURCES   <- c("data_raw", "data_raw_expressway")  # each has speedbands/<date>/sb_*.csv.gz
REGISTRY_SOURCE <- "data_raw"                            # speedbands_raw/<date>/sbraw_*.jsonl.gz
INCIDENT_SOURCE <- "data_raw"                            # feeds/incidents/<date>/incidents_*.jsonl.gz
LATE_ROWS_MIN   <- 60     # read files retrieved up to 60 min after midnight (late updates)
FINISHED_AFTER_H <- 2     # day D is finished at D+1 02:00 and when its rainfall is downloaded
BAD_ROWS_MAX_SHARE <- 0.001

# ---- links (DECISIONS.md 14 Oct, 11 Nov) ----
EXPRESSWAY_CATEGORY <- 1L
EXPECTED_EXPRESSWAY_LINKS <- 2598L
PRESENCE_DAYS <- as.IDate(c("2026-10-19", "2026-10-23"))   # first full week of collection
PRESENCE_MIN  <- 0.90
ROAD_GROUPS   <- c("KALLANG PAYA LEBAR EXPRESSWAY TUNNEL" = "KALLANG PAYA LEBAR EXPRESSWAY")
# Held-out roads: drawn once (11 Nov, before any model) with Python's random.Random(20261113).sample() over the
# sorted road names without the two flyovers (analysis/data_steps.py, heldout_roads). R's random numbers differ
# from Python's, so R uses the result of that draw instead of drawing again.
HELDOUT_SEED  <- 20261113L
EXPECTED_HELDOUT <- c("AYER RAJAH EXPRESSWAY", "CENTRAL EXPRESSWAY")
NEVER_HELD_OUT <- c("ALJUNIED WEST FLYOVER", "KALLANG BAHRU FLYOVER")
NEIGHBOUR_TOL_M <- 5      # B is downstream of A when B starts within 5 m of where A ends
CONNECTOR_TOL_M <- 5      # a road joins an expressway link within 5 m

# ---- rows (DECISIONS.md 14 Nov: back to the proposal) ----
HOUR_FROM <- 6L; HOUR_TO <- 22L                          # rows 06:00 <= t < 22:00
SPLITS <- list(train    = as.IDate(c("2026-10-16", "2026-11-06")),
               validate = as.IDate(c("2026-11-07", "2026-11-13")),
               test     = as.IDate(c("2026-11-14", "2026-11-20")))
POPULATION_DAYTYPES <- "weekday"                         # Mon-Fri, no public holidays
NOT_IN_MAIN_FILES <- c("f_sat", "f_sun", "f_holiday")    # always 0 on population days
NORM_SPLIT <- "train"
DAYTYPES <- c("weekday", "saturday", "sunday_or_holiday")

# ---- label (DECISIONS.md 13 Oct, 11 Nov) ----
THRESHOLD   <- 2          # low: normal level - band >= 2 bands
CONSECUTIVE <- 2L         # U: low at t and at t - 5 min; NA if either is unknown
HORIZON     <- 15L        # y = U(t + 15 min)
EXTRA_HORIZONS <- c(5L, 10L, 30L)

# ---- inputs (DECISIONS.md 11 Nov, 14 Nov) ----
STEP_MIN  <- 5L
LAGS      <- c(0L, 5L, 10L, 15L, 20L, 25L, 30L)
CARRY_MAX <- 5L           # a missing update reuses the last value for at most 5 min
RAIN_LAG  <- 5L
RAIN_WINDOWS <- c(f_rain15 = 15L, f_rain30 = 30L)
RAIN_STATION_MIN_SHARE <- 0.80
RAIN_DAY_MIN_SHARE     <- 0.80
WEEKDAY_COLUMNS <- c("f_mon", "f_tue", "f_wed", "f_thu", "f_fri", "f_sat", "f_sun")

LINK_CHUNK <- 650L        # links per pass over the 5-min grid (memory)
