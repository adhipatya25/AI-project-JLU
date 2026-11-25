"""Prediction client: Django asks the FastAPI model service for every prediction.

Stage 4 integration: Django no longer loads a model.pkl of its own.
The FastAPI service (fastapi-service/) owns the Stage 3 Gradient Boosting
model; Django sends the 14 input fields to its /predict endpoint over HTTP
and stores the returned rating in the database.

The service address comes from settings.FASTAPI_URL
(default http://127.0.0.1:8000, override with the FASTAPI_URL env variable).
"""

import requests
from django.conf import settings

FEATURES = [
    "height_in_cm",
    "international_caps",
    "market_value_in_eur",
    "matches_played",
    "total_minutes",
    "total_goals",
    "total_assists",
    "yellow_cards",
    "red_cards",
    "position",
    "sub_position",
    "foot",
    "competition_code",
    "confederation",
]

NUMERIC_FEATURES = FEATURES[:9]

VALID_RATINGS = {"Outperforming", "Average", "Underperforming"}

TIMEOUT_SECONDS = 10


class PredictionServiceError(Exception):
    """The FastAPI model service could not be reached or gave a bad answer."""


def _base_url() -> str:
    return settings.FASTAPI_URL.rstrip("/")


def _payload(features: dict) -> dict:
    """Build the JSON body FastAPI's PlayerData schema expects."""
    body = {}
    for k in FEATURES:
        v = features[k]
        body[k] = float(v) if k in NUMERIC_FEATURES else str(v)
    return body


def predict_player(features: dict) -> str:
    """features: {14 field names} -> 'Outperforming' | 'Average' | 'Underperforming'."""
    return _post_for_rating("/predict", _payload(features))


def _post_for_rating(path: str, body: dict) -> str:
    """POST body to a FastAPI prediction endpoint and return the validated rating."""
    url = f"{_base_url()}{path}"
    try:
        response = requests.post(url, json=body, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise PredictionServiceError(
            f"Cannot reach the FastAPI model service at {_base_url()}. "
            "Start it with: uvicorn app:app --port 8000 (inside fastapi-service), then try again."
        ) from exc

    if response.status_code != 200:
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = response.text[:200]
        raise PredictionServiceError(
            f"The model service returned HTTP {response.status_code}: {detail}"
        )

    try:
        rating = response.json()["predicted_future_potential_rating"]
    except (ValueError, KeyError) as exc:
        raise PredictionServiceError("The model service sent an unreadable response.") from exc

    if rating not in VALID_RATINGS:
        raise PredictionServiceError(f"The model service returned an unknown rating: {rating!r}")
    return rating


def predict_partial(fields: dict) -> str:
    """Predict when some of the 14 fields are missing (None).

    Calls FastAPI /predict-partial; the model's own imputers fill the gaps.
    """
    body = {}
    for k in FEATURES:
        v = fields.get(k)
        if v is None or v == "":
            body[k] = None
        else:
            body[k] = float(v) if k in NUMERIC_FEATURES else str(v)
    return _post_for_rating("/predict-partial", body)


def service_health() -> dict | None:
    """Return FastAPI's /health JSON, or None when the service is down."""
    try:
        response = requests.get(f"{_base_url()}/health", timeout=3)
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError):
        return None
