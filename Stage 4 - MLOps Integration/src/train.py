"""Stage 2 of the pipeline: train the Gradient Boosting model and track it in MLflow.

- Same preprocessing, split and hyper-parameters as Stage 3 (params.yaml).
- Saves the pipeline to fastapi-service/model.pkl (the file FastAPI serves)
  and metrics to reports/metrics.json (DVC metrics).
- Logs params, metrics, the confusion matrix and the model to MLflow, registers
  it as "football-potential-gb" and moves the "champion" alias to the new
  version when it is at least as accurate as the current champion.

MLflow server address: MLFLOW_TRACKING_URI (default http://127.0.0.1:5000).
"""

import json
import os
import sys

import joblib
import mlflow
import mlflow.sklearn
import pandas as pd
import requests
import yaml
from mlflow import MlflowClient
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from common import (CATEGORICAL_FEATURES, CLASSES, MODEL_PATH, NUMERIC_FEATURES, REPORTS, ROOT,
                    load_data, load_params, split)

TRACKING_URI = os.environ.get("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000")


def build_model(p: dict) -> Pipeline:
    numeric = Pipeline([("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler())])
    categorical = Pipeline([
        ("imputer", SimpleImputer(strategy="most_frequent")),
        ("encoder", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
    ])
    pre = ColumnTransformer([
        ("numeric", numeric, NUMERIC_FEATURES),
        ("categorical", categorical, CATEGORICAL_FEATURES),
    ])
    gb = GradientBoostingClassifier(**{k: v for k, v in p.items() if k != "name"})
    return Pipeline([("preprocessor", pre), ("classifier", gb)])


def dvc_data_hash(params: dict) -> str:
    """md5 that DVC recorded for the dataset, so every MLflow run names its data version."""
    dvc_file = ROOT / (params["data"]["path"] + ".dvc")
    if not dvc_file.exists():
        return "untracked"
    return yaml.safe_load(dvc_file.read_text(encoding="utf-8"))["outs"][0]["md5"]


def check_server():
    if not TRACKING_URI.startswith("http"):
        return
    try:
        requests.get(TRACKING_URI.rstrip("/") + "/health", timeout=5).raise_for_status()
    except requests.RequestException:
        sys.exit(
            f"MLflow tracking server is not reachable at {TRACKING_URI}.\n"
            "Start it first (docker compose up mlflow, or see README), "
            "or set MLFLOW_TRACKING_URI."
        )


def main():
    params = load_params()
    check_server()

    df = load_data(params)
    X_train, X_test, y_train, y_test = split(df, params)

    model = build_model(params["model"])
    model.fit(X_train, y_train)
    y_pred = model.predict(X_test)

    metrics = {
        "accuracy": round(accuracy_score(y_test, y_pred), 4),
        "f1_weighted": round(f1_score(y_test, y_pred, average="weighted"), 4),
        "f1_macro": round(f1_score(y_test, y_pred, average="macro"), 4),
        "train_rows": int(len(X_train)),
        "test_rows": int(len(X_test)),
    }
    per_class = classification_report(y_test, y_pred, output_dict=True)
    for cls in CLASSES:
        metrics[f"recall_{cls}"] = round(per_class[cls]["recall"], 4)
    print("Test metrics:", json.dumps(metrics))

    # --- outputs DVC tracks ---
    joblib.dump(model, MODEL_PATH)
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    cm = pd.DataFrame(confusion_matrix(y_test, y_pred, labels=CLASSES),
                      index=[f"true_{c}" for c in CLASSES], columns=[f"pred_{c}" for c in CLASSES])
    cm.to_csv(REPORTS / "confusion_matrix.csv")
    print("Saved", MODEL_PATH.relative_to(ROOT))

    # --- MLflow tracking + registry ---
    mlflow.set_tracking_uri(TRACKING_URI)
    mlflow.set_experiment(params["mlflow"]["experiment"])
    registered = params["mlflow"]["registered_model"]
    with mlflow.start_run(run_name=f"gb-{dvc_data_hash(params)[:8]}") as run:
        mlflow.set_tags({
            "stage": "stage-4-pipeline",
            "dvc_data_md5": dvc_data_hash(params),
            "orchestrator": os.environ.get("PIPELINE_RUNNER", "manual / dvc repro"),
        })
        mlflow.log_params({f"model.{k}": v for k, v in params["model"].items()})
        mlflow.log_params({f"data.{k}": v for k, v in params["data"].items()})
        mlflow.log_metrics({k: v for k, v in metrics.items() if isinstance(v, float)})
        mlflow.log_artifact(str(REPORTS / "confusion_matrix.csv"))
        mlflow.log_dict(per_class, "classification_report.json")
        example = X_test.dropna().head(5)
        # MLflow 3 stores sklearn models with skops (safer than pickle) and asks which
        # non-default types to trust. We trained this model ourselves, so trusting the
        # tree storage of GradientBoosting and numpy dtypes is safe.
        info = mlflow.sklearn.log_model(
            sk_model=model, name="model", registered_model_name=registered, input_example=example,
            skops_trusted_types=["numpy.dtype", "sklearn.tree._tree.Tree"],
        )
        version = info.registered_model_version
        print(f"MLflow run {run.info.run_id} -> {registered} v{version}")

    client = MlflowClient()
    try:
        champion = client.get_model_version_by_alias(registered, "champion")
        champ_acc = client.get_run(champion.run_id).data.metrics.get("accuracy", 0.0)
    except Exception:  # no champion yet
        champion, champ_acc = None, -1.0
    if metrics["accuracy"] >= champ_acc:
        client.set_registered_model_alias(registered, "champion", version)
        print(f"Alias 'champion' -> v{version} (accuracy {metrics['accuracy']} >= {champ_acc})")
    else:
        print(f"Champion stays v{champion.version} ({champ_acc} > {metrics['accuracy']})")

    (REPORTS / "mlflow_run.json").write_text(json.dumps({
        "tracking_uri": TRACKING_URI, "run_id": run.info.run_id,
        "registered_model": registered, "version": int(version),
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
