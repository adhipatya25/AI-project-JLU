# FastAPI model service (serves the Stage 3 Gradient Boosting model).
# Same Python + scikit-learn versions as training, so model.pkl unpickles safely.
FROM python:3.13.5-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py app-2.py player_template.csv model.pkl ./

# docker-compose mounts the project's fastapi-service folder at /models and sets
# MODEL_PATH=/models/model.pkl, so a model retrained by DVC/Airflow is picked up
# by POST /reload-model. Without the mount, the copy baked into the image is used.
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["uvicorn", "app-2:app", "--host", "0.0.0.0", "--port", "8000"]
