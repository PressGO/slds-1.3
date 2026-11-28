"""settings.py - every setting of the modelling pipeline, in one place.

The design follows the submitted proposal: two baselines (B1 time-of-week rate, B2 last observation), lasso logistic
regression and a random forest; PR-AUC on the rows that are normal now; a split by time and two held-out roads. The
dated choices are in DECISIONS.md. Nothing here changes the model tables (data version 4).

AI disclosure: drafted with Claude (Anthropic) on 25 Nov 2026; log in AI_USE.md.
"""
from __future__ import annotations

import math
import os
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent         # modelling/
ROOT = HERE.parent                             # the project folder (the repository root)


def _data_root() -> Path:
    """The folder that holds data_processed/: $SLDS_PROJECT_DIR, the project folder, or the folder above it."""
    for p in (os.environ.get("SLDS_PROJECT_DIR"), ROOT, ROOT.parent):
        if p and (Path(p) / "data_processed").is_dir():
            return Path(p).resolve()
    raise FileNotFoundError("data_processed/ not found: see README.md (Data), or set SLDS_PROJECT_DIR")


PROJ = _data_root()

# ---- the model tables (data version 4; written by analysis/build_data.py) ----
DATA = PROJ / "data_processed" / "model"
TRAIN = DATA / "train.parquet"                 # split = train / validate; weekdays only
EXTRA = DATA / "extra"
FULL = EXTRA / "full_table.parquet"            # every row of the train and validate days (also unusable rows)
NORM = EXTRA / "norm.parquet"
LINKS = EXTRA / "links.parquet"
NEIGH = EXTRA / "neighbours.parquet"
INCIDENTS = EXTRA / "incidents.parquet"
LODO = EXTRA / "train_lodo.parquet"
PANEL = PROJ / "data_processed" / "clean" / "panel.parquet"
RAIN = PROJ / "data_processed" / "rainfall_5min.csv.gz"
STATIONS = PROJ / "data_processed" / "rain_stations.csv"
DATA_VERSION = "4"

# ---- outputs ----
RESULTS = ROOT / "results"                     # small records, kept with the code: tables and the freeze records
TABLES = RESULTS / "tables"
FIGS = ROOT / "figures" / "pipeline"      # the figures these scripts draw
WORKDIR = ROOT / "work"                        # large files, never committed (rebuilt by the scripts)
WORK = WORKDIR / "features"                    # engineered feature tables
MODELS = WORKDIR / "models"                    # fitted models
PREDS = WORKDIR / "preds"                      # saved scores
TEST_BUILD = WORKDIR / "data_build"            # --out-root of the test-week build (gated, see 10_test.py)
DRY_BUILD = WORKDIR / "data_dryrun"            # the validation week dressed as a test build (DRY_RUN=1, 10_test.py)
FREEZE = RESULTS / "freeze.json"               # written by 07 before the test week is ever opened

# ---- dates (proposal: train and validate up to 13 Nov; test 16-20 Nov) ----
TRAIN_DAYS = (date(2026, 10, 16), date(2026, 11, 6))
VAL_DAYS = (date(2026, 11, 7), date(2026, 11, 13))
TEST_DAYS = (date(2026, 11, 16), date(2026, 11, 20))
LAST_OPEN_DAY = VAL_DAYS[1]                    # nothing after this date is read before the freeze
FOLDS = [((date(2026, 10, 16), date(2026, 10, 23)), (date(2026, 10, 26), date(2026, 10, 30))),
         ((date(2026, 10, 16), date(2026, 10, 30)), (date(2026, 11, 2), date(2026, 11, 6)))]

# ---- label and horizons (fixed by the data build; read from the data, never recomputed differently) ----
HORIZON = 15
EXTRA_HORIZONS = (5, 10, 30)                   # 5 = the proposal's secondary analysis; 10, 30 = DECISIONS.md, 18 Nov
THRESHOLD = 2

# ---- scoring ----
SHARES = (0.005, 0.01, 0.02)                   # precision / recall at the top share of links at each update
SHARE_GRID = (0.0025, 0.005, 0.01, 0.02, 0.03, 0.05)   # the operating share is chosen on validation by best F1
BOOT_REPS = 2000
SEED = 20261125
TIE_SEED = 20261118                            # seed for random tie-breaks (fixed with the baselines, 18 Nov)
PEAK_SLOTS = set(range(28, 40)) | set(range(68, 80))   # 07:00-09:59 and 17:00-19:59 (fixed before any test run)

# ---- B1 (DECISIONS.md, 18 Nov) ----
B1_M_GRID = [0, 12, 48, 192, 768, math.inf]

# ---- feature screening (fixed before the screen is run) ----
# Groups are tried in this order: NORM, HOP, HIST, starting from the 53 build inputs (BASE). For each model
# family separately, a group is kept only when it raises that family's mean forward-chaining PR-AUC (2 folds)
# by at least MIN_GAIN over the set without it; otherwise the simpler set is kept. Fixed before the screen ran.
SCREEN_ORDER = ("NORM", "HOP", "HIST")
MIN_GAIN = 0.002
RF_SCREEN = dict(max_features=0.35, min_samples_leaf=80)   # one fixed forest for the screen (tuned later)
HOP_RINGS = ((0.0, 500.0), (500.0, 1500.0), (1500.0, 3000.0))   # path metres beyond the next link
HOP_LAGS = (0, 10)
QDIST_CAP = 3500.0                             # "no low link within 3 km" is coded as 3,500 m

# ---- M1: lasso logistic regression ----
LASSO_MULTS = (10, 30, 100, 300, 1000, 3000, 10000)   # (saga grid; replaced by LASSO_FRACS, see lassofit.py)
LASSO_MAX_ITER = 200
LASSO_TOL = 1e-4
# Penalty grid per row: lambda = frac x lambda_max of the final fit rows (lambda_max = every input is 0), from strong
# to weak; the same lambda in every fit (folds and final), so the penalty per row never changes with the row count.
LASSO_FRACS = (0.5, 0.2, 0.1, 0.03, 0.01, 0.003, 0.001, 0.0003, 0.0001)

# ---- M2: random forest ----
RF_NEG_KEEP = 0.10                             # keep 10% of the y = False fit rows (fixed seed); recalibrate later
# First grid: max_features (0.15, 0.35) x leaf (20, 80, 320); its best (0.35, 20) sat on the edge in both directions,
# so the grid was extended once, on the train-day folds only (25 Nov), to this final grid:
RF_GRID = [dict(max_features=mf, min_samples_leaf=leaf) for mf in (0.15, 0.35, 0.6) for leaf in (5, 20, 80, 320)]
RF_TREES_TUNE = 150
RF_TREES_FINAL = 400
RF_JOBS = 12                                   # 16 cores; the collectors keep the rest

MEM_CAP = "14G"                                # every heavy run: systemd-run --user --scope -p MemoryMax=14G
