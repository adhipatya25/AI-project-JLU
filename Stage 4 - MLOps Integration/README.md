# Stage 4 - MLOps Integration

Football Player Future Potential Rating, built around the **Stage 3 final model**
(scikit-learn Pipeline + GradientBoostingClassifier, **93.59%** test accuracy,
classes Average / Outperforming / Underperforming, 14 input features).

## How the pieces connect

```
data/football_players.csv  (versioned by DVC)
        │
        ▼   dvc.yaml  (dvc repro)          ┌──────────────► MLflow  :5000
 validate_data ──► train ──► monitor       │  runs, metrics, model registry
                    │  │        │          │  (football-potential-gb, alias "champion")
                    │  └────────┼──────────┘
                    │           └──► Evidently reports  (reports/*.html)
                    ▼
     fastapi-service/model.pkl ──► FastAPI :8000 ◄── HTTP ── Django ScoutIQ :8001 ◄── browser
                                     ▲  POST /reload-model
 Airflow :8080  (runs the DVC stages above, then reloads FastAPI)
 Docker Compose runs MLflow, FastAPI, Django and Airflow as containers.
```

| Folder / file | What it is |
|---|---|
| `data/football_players.csv` (+ `.dvc`) | Dataset, tracked by DVC (md5 `5ae876a2…`) |
| `params.yaml` | Split, Gradient Boosting hyper-parameters, MLflow names, monitoring thresholds |
| `dvc.yaml`, `dvc.lock` | Pipeline `validate_data → train → monitor` and the recorded state of every input/output |
| `src/validate_data.py` | Schema / label / value checks → `reports/data_validation.json` |
| `src/train.py` | Trains, writes `fastapi-service/model.pkl` + `reports/metrics.json`, logs to MLflow, registers the model |
| `src/monitor.py` | Evidently: data quality, drift, model performance, production drift (Django inputs) |
| `fastapi-service/` | Model service: `/predict`, `/predict-partial`, `/health`, `/reload-model`, PDF/CSV endpoints; `frontend/` = standalone UI |
| `django-scoutiq/` | ScoutIQ web app (same UI). No model of its own - calls FastAPI and stores every prediction |
| `airflow/` | Airflow image (+ ML tool venv) and the DAG `football_mlops_pipeline` |
| `docker-compose.yml`, `docker/` | All services as containers |
| `reports/` | Pipeline outputs (JSON metrics + Evidently HTML) |

## After cloning from GitHub

The dataset and `model.pkl` are versioned by DVC, not stored in Git (no DVC remote is set up).
Restore them from Stage 3 - they are the same files - then let DVC check and rebuild:

```powershell
Copy-Item "..\Stage 3\football_players.csv" "data\football_players.csv"
python -m venv venv; venv\Scripts\pip install -r requirements-mlops.txt
docker compose up -d mlflow
venv\Scripts\dvc repro      # retrains the identical model into fastapi-service\model.pkl
```

## Run it with Docker (recommended)

Start Docker Desktop, then in this folder:

```powershell
docker compose up -d --build
```

| Open | What you see |
|---|---|
| http://localhost:8001 | Django ScoutIQ - sign up / log in, predict, history (sidebar shows "FastAPI online") |
| http://localhost:8000/docs | FastAPI endpoints; `/health` shows which model file is served (`model_md5`) |
| http://localhost:5000 | MLflow - experiment `football-player-potential`, Models → `football-potential-gb` |

Add Airflow (bigger image, first build takes a few minutes):

```powershell
docker compose --profile pipeline up -d --build
```

Open http://localhost:8080 (no login in this local setup), DAG **football_mlops_pipeline** → Trigger.
Tick **force_retrain** to retrain even when nothing changed. Tasks:
`check_data_version → validate_data → train_model → monitor_model → check_drift → reload_fastapi`.

Stop everything: `docker compose --profile pipeline down`

## Run the pipeline yourself (DVC + MLflow + Evidently)

MLflow must be running (`docker compose up -d mlflow`). Then:

```powershell
venv\Scripts\activate
dvc repro            # runs only the stages whose code, data or params changed
dvc metrics show     # accuracy, drift share, validation results
dvc dag              # the pipeline graph
```

Open `reports\data_quality.html`, `reports\data_drift.html`, `reports\model_performance.html` in a browser.
Try it: change `n_estimators` in `params.yaml`, run `dvc repro` → only `train` and `monitor` re-run,
and MLflow shows a new run and model version ("champion" only moves if accuracy is not worse).

First-time setup of the tool environment: `python -m venv venv` then
`venv\Scripts\pip install -r requirements-mlops.txt`.

## Run without Docker (native)

```powershell
# terminal 1 - FastAPI
cd fastapi-service; .\venv\Scripts\python.exe -m uvicorn app:app --port 8000
# terminal 2 - Django
cd django-scoutiq; .\venv\Scripts\python.exe manage.py runserver 8001
```

Native and Docker Django share `django-scoutiq\db.sqlite3` - run one of them at a time.

## Checks

- `cd django-scoutiq; .\venv\Scripts\python.exe manage.py test scout` → 11 tests (2 live ones need FastAPI on :8000)
- The DVC-trained model gives identical predictions to `Stage 3\model.pkl` on all 50,149 rows.

## 5-minute faculty demo

1. `docker compose --profile pipeline up -d` → `docker compose ps` (Docker: 4 containers).
2. Django :8001 → load the "Outperforming example" → predict → open the player record and the history page (Django → FastAPI).
3. Airflow :8080 → trigger the DAG with force_retrain → all tasks green (Airflow → DVC → MLflow → Evidently → FastAPI reload).
4. MLflow :5000 → the new run (tag `orchestrator=airflow`), metrics, model version + "champion" alias.
5. `reports\data_drift.html` / `model_performance.html` (Evidently) and `dvc metrics show` / `dvc dag` (DVC).

## Known limits (local demo, not production)

- Django runs the dev server with `DEBUG=True` and the default secret key; Airflow runs in `standalone` mode with no login.
- DVC has no remote storage configured and nothing is committed to Git yet - commit `dvc.lock`, `*.dvc`, `params.yaml` to record versions.
- The drift report compares the training split with the test split (same source), so it is a baseline. Real drift needs new data;
  the production-drift report starts once Django has stored 200+ predictions.
- FastAPI serves `model.pkl` written by the pipeline; the MLflow registry holds the same model as a tracked record.
