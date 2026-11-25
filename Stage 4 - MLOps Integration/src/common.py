"""Shared helpers for the Stage 4 pipeline (paths, params, data loading, split)."""

from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"
MODEL_PATH = ROOT / "fastapi-service" / "model.pkl"   # the file FastAPI serves
DJANGO_DB = ROOT / "django-scoutiq" / "db.sqlite3"

NUMERIC_FEATURES = [
    "height_in_cm",
    "international_caps",
    "market_value_in_eur",
    "matches_played",
    "total_minutes",
    "total_goals",
    "total_assists",
    "yellow_cards",
    "red_cards",
]
CATEGORICAL_FEATURES = ["position", "sub_position", "foot", "competition_code", "confederation"]
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES
CLASSES = ["Average", "Outperforming", "Underperforming"]


def load_params() -> dict:
    with open(ROOT / "params.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_data(params: dict) -> pd.DataFrame:
    df = pd.read_csv(ROOT / params["data"]["path"])
    # Stage 3 cleaning step: the text placeholder "Missing" means unknown position
    df["position"] = df["position"].replace("Missing", np.nan)
    return df


def split(df: pd.DataFrame, params: dict):
    """Same stratified 80/20 split as the Stage 3 notebook."""
    d = params["data"]
    return train_test_split(
        df[FEATURES], df[d["target"]],
        test_size=d["test_size"], random_state=d["random_state"], stratify=df[d["target"]],
    )
