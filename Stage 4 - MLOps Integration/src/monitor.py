"""Stage 3 of the pipeline: Evidently AI monitoring reports.

1. reports/data_quality.html     - summary of every column in the dataset
2. reports/data_drift.html       - training split (reference) vs test split (current)
3. reports/model_performance.html - classification quality of model.pkl on the test split
4. reports/production_drift.html - training data vs the players Django users actually
                                   sent for prediction (only when enough are stored)
plus reports/monitoring.json, a small summary DVC tracks as metrics and Airflow reads.
"""

import json
import sqlite3

import joblib
import pandas as pd
from evidently import DataDefinition, Dataset, MulticlassClassification, Report
from evidently.presets import ClassificationPreset, DataDriftPreset, DataSummaryPreset

from common import (CATEGORICAL_FEATURES, DJANGO_DB, FEATURES, MODEL_PATH, NUMERIC_FEATURES, REPORTS,
                    load_data, load_params, split)


def definition(with_labels: bool = False) -> DataDefinition:
    extra = {}
    if with_labels:
        extra["classification"] = [MulticlassClassification(target="target", prediction_labels="prediction")]
    return DataDefinition(numerical_columns=NUMERIC_FEATURES, categorical_columns=CATEGORICAL_FEATURES, **extra)


def drift_numbers(snapshot) -> dict:
    """Pull 'drifted columns count/share' out of an Evidently result."""
    for m in snapshot.dict()["metrics"]:
        if m.get("metric_name", "").startswith("DriftedColumnsCount"):
            return {"drifted_columns": int(m["value"]["count"]), "drift_share": round(float(m["value"]["share"]), 4)}
    return {"drifted_columns": None, "drift_share": None}


def production_inputs() -> pd.DataFrame:
    """Player rows stored by Django (what real users asked the model about)."""
    if not DJANGO_DB.exists():
        return pd.DataFrame(columns=FEATURES)
    with sqlite3.connect(DJANGO_DB) as con:
        try:
            return pd.read_sql_query(f"SELECT {', '.join(FEATURES)} FROM scout_player", con)
        except Exception:
            return pd.DataFrame(columns=FEATURES)


def main():
    params = load_params()
    mon = params["monitoring"]
    target = params["data"]["target"]
    REPORTS.mkdir(exist_ok=True)

    df = load_data(params)
    X_train, X_test, y_train, y_test = split(df, params)

    # 1. data quality of the whole dataset
    full = Dataset.from_pandas(df[FEATURES], data_definition=definition())
    Report([DataSummaryPreset()]).run(full, None).save_html(str(REPORTS / "data_quality.html"))

    # 2. drift: training split vs test split
    ref = Dataset.from_pandas(X_train, data_definition=definition())
    cur = Dataset.from_pandas(X_test, data_definition=definition())
    drift = Report([DataDriftPreset()]).run(cur, ref)
    drift.save_html(str(REPORTS / "data_drift.html"))
    split_drift = drift_numbers(drift)

    # 3. model performance on the held-out split
    model = joblib.load(MODEL_PATH)
    labelled = X_test.assign(target=y_test.values, prediction=model.predict(X_test))
    perf = Report([ClassificationPreset()]).run(
        Dataset.from_pandas(labelled, data_definition=definition(with_labels=True)), None)
    perf.save_html(str(REPORTS / "model_performance.html"))

    # 4. production drift (Django inputs) when there is enough of it
    prod = production_inputs()
    prod_drift = {"rows": int(len(prod)), "report": None}
    if len(prod) >= mon["min_production_rows"]:
        pr = Report([DataDriftPreset()]).run(
            Dataset.from_pandas(prod[FEATURES], data_definition=definition()), ref)
        pr.save_html(str(REPORTS / "production_drift.html"))
        prod_drift.update(drift_numbers(pr), report="reports/production_drift.html")

    summary = {
        "reference_rows": int(len(X_train)),
        "current_rows": int(len(X_test)),
        **split_drift,
        "drift_alert": bool(split_drift["drift_share"] is not None
                            and split_drift["drift_share"] > mon["drift_share_threshold"]),
        "production": prod_drift,
        "target": target,
    }
    (REPORTS / "monitoring.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    if summary["drift_alert"]:
        print(f"WARNING: drift share above {mon['drift_share_threshold']}")


if __name__ == "__main__":
    main()
