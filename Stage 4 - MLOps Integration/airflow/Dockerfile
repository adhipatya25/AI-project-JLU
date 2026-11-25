# Airflow (same 3.3.2 image as the Airflow demo) + a separate virtualenv with the
# project's ML/MLOps tools. Tasks call /opt/mlops-venv/bin/python, so the pipeline's
# scikit-learn / MLflow / Evidently / DVC versions never clash with Airflow's own.
FROM apache/airflow:3.3.2

USER root
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

USER airflow
COPY requirements-mlops.txt /tmp/requirements-mlops.txt
RUN python -m venv /opt/airflow/mlops-venv \
    && /opt/airflow/mlops-venv/bin/pip install --no-cache-dir -r /tmp/requirements-mlops.txt
# The project folder is a bind mount owned by another user: let git/DVC use it.
RUN git config --global --add safe.directory '*'
