# Django ScoutIQ web app. Has no model: it calls the FastAPI service (FASTAPI_URL).
FROM python:3.13.5-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8001
# Create/upgrade the SQLite tables, then serve (dev server is fine for this demo).
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py runserver 0.0.0.0:8001"]
