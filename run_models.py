"""Train the Project 1.3 traffic-onset models.

The script deliberately keeps the modelling contract narrow: the only model
inputs are the 53 columns whose names start with ``f_``.  Held-out roads are
removed before any fit, mapping, calibration, or model comparison.
"""

from __future__ import annotations

import argparse
import random
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


SEED = 20261124
EXPECTED_FEATURE_COUNT = 53

# scikit-learn 1.8 warns that the explicitly requested elastic-net penalty
# will be deprecated, although it remains the required estimator here.
warnings.filterwarnings(
    "ignore",
    message="'penalty' was deprecated in version 1.8",
    category=FutureWarning,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data",
        type=Path,
        default=None,
        help="Parquet input; defaults to extra/train_sample.parquet, then train.parquet.",
    )
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--trees", type=int, default=400)
    parser.add_argument(
        "--max-rows",
        type=int,
        default=None,
        help="Optional deterministic row cap for a quick smoke test; default uses all rows.",
    )
    return parser.parse_args()


def find_data(project_root: Path, requested: Path | None) -> Path:
    if requested is not None:
        path = requested if requested.is_absolute() else project_root / requested
        if not path.exists():
            raise FileNotFoundError(f"Input parquet does not exist: {path}")
        return path
    candidates = [
        project_root / "data_processed/model/extra/train_sample.parquet",
        project_root / "data_processed/model/train.parquet",
    ]
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError("Could not find train_sample.parquet or train.parquet")


def as_bool(series: pd.Series) -> pd.Series:
    """Normalize bool-like parquet columns without changing their semantics."""
    if pd.api.types.is_bool_dtype(series):
        return series.astype(bool)
    values = series.astype(str).str.strip().str.lower()
    return values.map({"true": True, "false": False, "1": True, "0": False}).astype(bool)


def pr_auc_onset(frame: pd.DataFrame, scores: np.ndarray) -> float:
    onset = ~as_bool(frame["U"])
    y = frame.loc[onset, "y"].astype(bool).to_numpy()
    if y.size == 0 or np.unique(y).size < 2:
        raise ValueError("Validation Onset subset must contain both y classes for PR-AUC")
    return float(average_precision_score(y, np.asarray(scores)[onset]))


def b1_time_rate(train: pd.DataFrame, valid: pd.DataFrame) -> np.ndarray:
    """Historical y rate for LinkID x time slot, with train-rate fallback."""
    keys = ["LinkID", "f_slot15"]
    work = train.assign(y_bool=train["y"].astype(bool))
    rates = work.groupby(keys, dropna=False)["y_bool"].mean()
    global_rate = float(work["y_bool"].mean())
    valid_keys = pd.MultiIndex.from_frame(valid[keys])
    scores = rates.reindex(valid_keys).to_numpy(dtype=float)
    return np.nan_to_num(scores, nan=global_rate)


def b2_drop_now(train: pd.DataFrame, valid: pd.DataFrame) -> np.ndarray:
    median = float(pd.to_numeric(train["f_d0"], errors="coerce").median())
    return pd.to_numeric(valid["f_d0"], errors="coerce").fillna(median).to_numpy(dtype=float)


def make_logistic(feature_names: list[str]) -> Pipeline:
    categorical = ["f_slot15"]
    numeric = [name for name in feature_names if name not in categorical]
    prep = ColumnTransformer(
        [
            (
                "numeric",
                Pipeline(
                    [("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())]
                ),
                numeric,
            ),
            (
                "slot15",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="most_frequent")),
                        ("onehot", OneHotEncoder(handle_unknown="ignore")),
                    ]
                ),
                categorical,
            ),
        ]
    )
    return Pipeline(
        [
            ("preprocess", prep),
            (
                "model",
                LogisticRegression(
                    penalty="elasticnet",
                    solver="saga",
                    l1_ratio=0.5,
                    C=1.0,
                    max_iter=1000,
                    random_state=SEED,
                ),
            ),
        ]
    )


def downsample_false(train: pd.DataFrame, seed: int) -> pd.DataFrame:
    y = train["y"].astype(bool)
    positives = train.loc[y]
    negatives = train.loc[~y]
    if positives.empty or negatives.empty:
        raise ValueError("Train must contain both y classes")
    n_false = min(len(negatives), len(positives))
    sampled_false = negatives.sample(n=n_false, random_state=seed)
    return pd.concat([positives, sampled_false], ignore_index=True).sample(
        frac=1.0, random_state=seed
    )


def calibrate_sigmoid(raw_scores: np.ndarray, valid: pd.DataFrame) -> np.ndarray:
    """Calibrate RF scores on Validate using a fixed sigmoid calibration model."""
    calibrator = LogisticRegression(solver="lbfgs", random_state=SEED)
    calibrator.fit(np.asarray(raw_scores).reshape(-1, 1), valid["y"].astype(bool))
    return calibrator.predict_proba(np.asarray(raw_scores).reshape(-1, 1))[:, 1]


def main() -> None:
    args = parse_args()
    random.seed(args.seed)
    np.random.seed(args.seed)
    project_root = Path(__file__).resolve().parent
    data_path = find_data(project_root, args.data)
    data = pd.read_parquet(data_path)
    if args.max_rows is not None:
        if args.max_rows < 1:
            raise ValueError("--max-rows must be positive")
        data = data.sample(n=min(args.max_rows, len(data)), random_state=args.seed)

    feature_names = [name for name in data.columns if name.startswith("f_")]
    if len(feature_names) != EXPECTED_FEATURE_COUNT:
        raise ValueError(
            f"Expected exactly {EXPECTED_FEATURE_COUNT} f_ features, found {len(feature_names)}: "
            f"{feature_names}"
        )
    required = {"LinkID", "split", "heldout_road", "y", "U", *feature_names}
    missing = required.difference(data.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    # This filter happens before every downstream operation, including B1's map.
    data = data.loc[~as_bool(data["heldout_road"])].copy()
    train = data.loc[data["split"].astype(str).eq("train")].copy()
    valid = data.loc[data["split"].astype(str).eq("validate")].copy()
    if train.empty or valid.empty:
        raise ValueError("Both train and validate splits are required")

    results: list[dict[str, object]] = []
    scores = {
        "B1_time_of_day_rate": b1_time_rate(train, valid),
        "B2_drop_now": b2_drop_now(train, valid),
    }

    logistic = make_logistic(feature_names)
    logistic.fit(train[feature_names], train["y"].astype(bool))
    scores["M1_logistic_elasticnet"] = logistic.predict_proba(valid[feature_names])[:, 1]

    balanced_train = downsample_false(train, args.seed)
    forest = Pipeline(
        [
            ("impute", SimpleImputer(strategy="median")),
            (
                "model",
                RandomForestClassifier(
                    n_estimators=args.trees,
                    class_weight=None,
                    n_jobs=-1,
                    random_state=args.seed,
                    min_samples_leaf=2,
                ),
            ),
        ]
    )
    forest.fit(balanced_train[feature_names], balanced_train["y"].astype(bool))
    raw_rf = forest.predict_proba(valid[feature_names])[:, 1]
    scores["M2_random_forest_calibrated"] = calibrate_sigmoid(raw_rf, valid)

    for model, score in scores.items():
        results.append(
            {
                "model": model,
                "pr_auc_onset": pr_auc_onset(valid, score),
                "n_train": len(train),
                "n_train_rf": len(balanced_train) if model.startswith("M2") else np.nan,
                "n_validate_onset": int((~as_bool(valid["U"])).sum()),
                "data_file": str(data_path.relative_to(project_root)),
                "seed": args.seed,
            }
        )

    report = pd.DataFrame(results).sort_values("pr_auc_onset", ascending=False)
    print(report.to_string(index=False))
    print("\nBaseline comparison (M1/M2 > both B1/B2):")
    baseline_max = report.loc[report["model"].isin(["B1_time_of_day_rate", "B2_drop_now"]), "pr_auc_onset"].max()
    for model in ["M1_logistic_elasticnet", "M2_random_forest_calibrated"]:
        value = float(report.loc[report["model"].eq(model), "pr_auc_onset"].iloc[0])
        print(f"{model}: {'YES' if value > baseline_max else 'NO'} (PR-AUC={value:.6f}; best baseline={baseline_max:.6f})")


if __name__ == "__main__":
    main()
