# MLflow tracking server + model registry (same MLflow version as the pipeline).
FROM python:3.13.5-slim
RUN pip install --no-cache-dir mlflow==3.16.1
EXPOSE 5000
# Runs, metrics and registry live in /mlflow/mlflow.db; model files in /mlflow/artifacts.
# --serve-artifacts: clients upload through the server, so Windows (dvc repro) and
# Linux (Airflow) clients can share one store without path problems.
CMD ["mlflow", "server", "--host", "0.0.0.0", "--port", "5000", \
     "--backend-store-uri", "sqlite:////mlflow/mlflow.db", \
     "--artifacts-destination", "/mlflow/artifacts", "--serve-artifacts", \
     "--allowed-hosts", "*"]
