"""Football Player Potential - end-to-end MLOps pipeline.

    check_data_version -> validate_data -> train_model -> monitor_model -> check_drift -> reload_fastapi

Airflow orchestrates; each ML step is a DVC stage (dvc.yaml), so unchanged steps
are skipped and every output is versioned. train_model logs to MLflow and updates
the "champion" model; monitor_model builds the Evidently reports; reload_fastapi
makes the running FastAPI service serve the freshly trained model.pkl.

Trigger it from the Airflow UI (http://localhost:8080). Tick "force_retrain" to
retrain even when data/params did not change.
"""

import json
import os
from datetime import datetime
from pathlib import Path

import requests
from airflow.providers.standard.operators.bash import BashOperator
from airflow.providers.standard.operators.python import PythonOperator
from airflow.sdk import DAG, Param

PROJECT = "/opt/project"
VENV_BIN = "/opt/airflow/mlops-venv/bin"
ENV = {
    "PATH": f"{VENV_BIN}:{os.environ.get('PATH', '')}",
    "MLFLOW_TRACKING_URI": os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000"),
    "PIPELINE_RUNNER": "airflow",
    "PYTHONUNBUFFERED": "1",
}
FASTAPI_URL = os.environ.get("FASTAPI_URL", "http://fastapi:8000")


def bash(task_id, command):
    return BashOperator(task_id=task_id, bash_command=command, cwd=PROJECT, env=ENV, append_env=True)


def check_drift():
    summary = json.loads(Path(PROJECT, "reports", "monitoring.json").read_text())
    print(json.dumps(summary, indent=2))
    if summary.get("drift_alert"):
        print("WARNING: data drift above threshold - review reports/data_drift.html")
    prod = summary.get("production", {})
    if prod.get("report"):
        print(f"Production drift on {prod['rows']} Django predictions: share {prod.get('drift_share')}")
    else:
        print(f"Production drift skipped: only {prod.get('rows', 0)} stored Django predictions")
    return summary


def reload_fastapi():
    try:
        r = requests.post(f"{FASTAPI_URL}/reload-model", timeout=30)
        r.raise_for_status()
    except requests.RequestException as exc:
        print(f"FastAPI not reachable at {FASTAPI_URL} ({exc}); it will load the new model on next start.")
        return None
    print("FastAPI now serves:", r.json())
    return r.json()


with DAG(
    dag_id="football_mlops_pipeline",
    description="DVC + MLflow + Evidently pipeline for the Stage 3 Gradient Boosting model",
    start_date=datetime(2026, 11, 1),
    schedule=None,
    catchup=False,
    tags=["stage-4", "mlops", "football"],
    params={"force_retrain": Param(False, type="boolean", description="Retrain even if nothing changed")},
) as dag:
    check_data_version = bash(
        "check_data_version",
        "dvc status data/football_players.csv.dvc && "
        "echo 'Dataset md5:' && grep 'md5' data/football_players.csv.dvc",
    )
    validate_data = bash("validate_data", "dvc repro --single-item validate_data")
    train_model = bash(
        "train_model",
        "dvc repro --single-item {{ '--force' if params.force_retrain else '' }} train && cat reports/metrics.json",
    )
    # monitoring always re-runs so it also picks up new predictions stored by Django
    monitor_model = bash("monitor_model", "dvc repro --single-item --force monitor")
    drift = PythonOperator(task_id="check_drift", python_callable=check_drift)
    reload = PythonOperator(task_id="reload_fastapi", python_callable=reload_fastapi)

    check_data_version >> validate_data >> train_model >> monitor_model >> drift >> reload
