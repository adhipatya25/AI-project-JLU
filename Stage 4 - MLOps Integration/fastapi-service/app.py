from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pandas as pd
import hashlib
import joblib
import os
from pathlib import Path

# Create FastAPI application
app = FastAPI(
    title="Football Player Potential API",
    description="Predict a player's future potential rating",
    version="1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load the Stage 3 final model: a full sklearn Pipeline
# (ColumnTransformer preprocessing + GradientBoostingClassifier, 93.59% test accuracy).
# The DVC "train" stage writes this file; MODEL_PATH can override the location. Default is
# model.pkl next to this file, so the app works no matter which folder you start it from.
MODEL_PATH = Path(os.environ.get("MODEL_PATH", Path(__file__).resolve().parent / "model.pkl"))


def _load_model():
    """Load model.pkl and remember which file version is being served."""
    m = joblib.load(MODEL_PATH)
    name = type(m.steps[-1][1]).__name__ if hasattr(m, "steps") else type(m).__name__
    return m, name, hashlib.md5(MODEL_PATH.read_bytes()).hexdigest()


model, MODEL_NAME, MODEL_MD5 = _load_model()


# Define the input fields
class PlayerData(BaseModel):
    height_in_cm: float
    international_caps: float
    market_value_in_eur: float
    matches_played: float
    total_minutes: float
    total_goals: float
    total_assists: float
    yellow_cards: float
    red_cards: float

    position: str
    sub_position: str
    foot: str
    competition_code: str
    confederation: str


# Home endpoint
@app.get("/")
def home():
    return {
        "message": "Football Player Potential API is running!"
    }


# Health endpoint: Django, Docker and Airflow use this to check the model service is up
@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": MODEL_NAME,
        "model_file": MODEL_PATH.name,
        "model_md5": MODEL_MD5,
        "classes": [str(c) for c in model.classes_],
    }


# Airflow calls this after the pipeline retrains, so the new model.pkl is served
# without restarting the container.
@app.post("/reload-model")
def reload_model():
    global model, MODEL_NAME, MODEL_MD5
    model, MODEL_NAME, MODEL_MD5 = _load_model()
    return health()


# Prediction endpoint
@app.post("/predict")
def predict_player(data: PlayerData):
    # Convert input into a DataFrame with the expected columns
    player = pd.DataFrame([data.model_dump()])

    # Predict the player's potential rating
    prediction = model.predict(player)[0]

    return {
        "predicted_future_potential_rating": str(prediction)
    }


# Partial input (used by Django's "Predict directly from PDF" when a report misses
# some fields). Missing values become NaN and the pipeline's SimpleImputer fills
# them with the training median / most frequent value.
class PartialPlayerData(BaseModel):
    height_in_cm: float | None = None
    international_caps: float | None = None
    market_value_in_eur: float | None = None
    matches_played: float | None = None
    total_minutes: float | None = None
    total_goals: float | None = None
    total_assists: float | None = None
    yellow_cards: float | None = None
    red_cards: float | None = None

    position: str | None = None
    sub_position: str | None = None
    foot: str | None = None
    competition_code: str | None = None
    confederation: str | None = None


@app.post("/predict-partial")
def predict_partial(data: PartialPlayerData):
    row = {k: (v if v is not None else float("nan")) for k, v in data.model_dump().items()}
    prediction = model.predict(pd.DataFrame([row]))[0]
    missing = [k for k, v in data.model_dump().items() if v is None]
    return {
        "predicted_future_potential_rating": str(prediction),
        "missing_fields_filled_by_model": missing,
    }
