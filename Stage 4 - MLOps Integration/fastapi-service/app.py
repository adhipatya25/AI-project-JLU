from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pandas as pd
import hashlib
import joblib
import os
from pathlib import Path
import re
import io

# Create FastAPI application (v2: adds PDF report upload, original /predict untouched)
app = FastAPI(
    title="Football Player Potential API",
    description="Predict a player's future potential rating (manual form + PDF report upload)",
    version="2.0",
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


NUMERIC_FIELDS = [
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

CATEGORICAL_FIELDS = [
    "position",
    "sub_position",
    "foot",
    "competition_code",
    "confederation",
]

ALL_FIELDS = NUMERIC_FIELDS + CATEGORICAL_FIELDS

# Known vocabularies (must match train_model-2.py / frontend dropdowns)
SUB_POSITIONS = [
    "Centre-Forward", "Left Winger", "Right Winger", "Second Striker",
    "Attacking Midfield", "Central Midfield", "Defensive Midfield",
    "Left Midfield", "Right Midfield",
    "Centre-Back", "Left-Back", "Right-Back",
    "Goalkeeper",
]

COMPETITION_ALIASES = {
    "premier league": "premier-league",
    "laliga": "laliga",
    "la liga": "laliga",
    "serie a": "serie-a",
    "bundesliga": "bundesliga",
    "ligue 1": "ligue-1",
    "eredivisie": "eredivisie",
    "liga portugal": "liga-portugal",
    "major league soccer": "major-league-soccer",
    "mls": "major-league-soccer",
    "saudi pro league": "saudi-pro-league",
    "superliga": "superliga",
}


def _extract_pdf_text(raw: bytes) -> str:
    """Extract text from PDF bytes. Tries pdfplumber, falls back to pypdf."""
    # Try pdfplumber first (better tables)
    try:
        import pdfplumber
        text_parts = []
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            for page in pdf.pages:
                text_parts.append(page.extract_text() or "")
        text = "\n".join(text_parts).strip()
        if text:
            return text
    except ImportError:
        pass
    except Exception:
        pass
    # Fallback to pypdf
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        text = "\n".join([(p.extract_text() or "") for p in reader.pages]).strip()
        if text:
            return text
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="No PDF library installed. Run: pip install pdfplumber pypdf",
        )
    raise HTTPException(status_code=400, detail="Could not extract text from this PDF.")


def _number_after_label(head: str, label_pat: str, lo: float, hi: float, window: int = 80):
    """First number in [lo, hi] within `window` chars after a label.

    Handles both inline ("Height: 184 cm") and transposed PDF tables
    ("Strong foot Height Weight / 187 83 / Left cm kg").
    """
    m = re.search(label_pat, head, re.IGNORECASE)
    if not m:
        return None
    for num in re.finditer(r"(\d{2,4}(?:[,\.]\d+)?)", head[m.end():m.end() + window]):
        try:
            v = float(num.group(1).replace(",", ""))
        except ValueError:
            continue
        if lo <= v <= hi:
            return v
    return None


def parse_report_text(text: str) -> dict:
    """Best-effort regex extraction of the 14 model fields from report text.

    Returns dict with values or None where not found. Never raises —
    missing fields are left as None so the sklearn pipeline's
    SimpleImputer (median / most_frequent) can fill them.
    """
    t = text or ""
    out: dict = {k: None for k in ALL_FIELDS}

    # --- Section split: bio + career tables live BEFORE rankings/glossary.
    # Full-text search poisons bio fields (e.g. "goalkeeper" in the glossary
    # definitions) and match-by-match pages double-count career totals.
    pre_rank = re.split(r"PLAYER REPORT\s*RANKINGS", t, flags=re.IGNORECASE)[0]
    head = re.split(r"\bGLOSSARY\b", pre_rank, flags=re.IGNORECASE)[0]
    head_low = head.lower()
    # Position peer-group scope: rankings pages state it explicitly
    # ("Player rankings for central defenders ..."), glossary excluded.
    pos_scope = re.split(r"\bGLOSSARY\b", t, flags=re.IGNORECASE)[0]
    pos_scope_low = pos_scope.lower()
    # Career-history segment: a Wyscout report prints CAREER OVERVIEW (recent
    # seasons) then a second PROFILE table (complete history). Summing both
    # counts recent seasons twice, so take the text after the LAST profile
    # header. Single-table reports still work (only one header to split on).
    if re.search(r"\bPROFILE\b", head, re.IGNORECASE):
        career_seg = re.split(r"\bPROFILE\b", head, flags=re.IGNORECASE)[-1]
    else:
        career_seg = head

    # --- Height: "Height: 184 cm" or transposed table ("Height Weight / 187 83") ---
    out["height_in_cm"] = _number_after_label(head, r"height", 140, 210)

    # --- Foot: "Preferred Foot: Right" or transposed table ("Strong foot ... Left cm kg") ---
    m = re.search(r"(strong foot|preferred foot|dominant foot|\bfoot\b)", head, re.IGNORECASE)
    if m:
        w = re.search(r"\b(left|right|both)\b", head[m.end():m.end() + 80], re.IGNORECASE)
        if w:
            out["foot"] = w.group(1).lower()

    # --- Position (coarse). Primary signal: the rankings peer group
    #     ("Player rankings for central defenders ..."). Bio-text phrases are
    #     the fallback. Goalkeeper is checked last so glossary leftovers and
    #     generic mentions can never outrank an explicit outfield signal. ---
    group_m = re.search(r"rankings for ([\w\s/\-]+?) in ", pos_scope_low)
    group = group_m.group(1).strip() if group_m else ""
    if re.search(r"defender|centre-back|center-back|full.back|wing.back|\bback\b", group):
        out["position"] = "Defender"
    elif re.search(r"midfield", group):
        out["position"] = "Midfield"
    elif re.search(r"forward|striker|winger|\battack\b", group):
        out["position"] = "Attack"
    elif re.search(r"goalkeeper|goal keeper", group):
        out["position"] = "Goalkeeper"
    elif re.search(
        r"central defender|centre-back|center-back|left-back|right-back|full-back|wing-back|centre back|\bdefender\b",
        head_low,
    ):
        out["position"] = "Defender"
    elif re.search(r"midfield", head_low):
        out["position"] = "Midfield"
    elif re.search(r"centre-forward|second striker|striker|winger|\bforward\b|\battack\b", head_low):
        out["position"] = "Attack"
    elif re.search(r"goalkeeper|goal keeper", head_low):
        out["position"] = "Goalkeeper"

    # --- Sub-position (exact match from known list, head only) ---
    for sp in SUB_POSITIONS:
        if re.search(r"\b" + re.escape(sp) + r"\b", head, re.IGNORECASE):
            # keep the canonical casing from the list
            out["sub_position"] = sp
            break
    # Common Wyscout wording that is not in our list -> map it
    # (peer group first, then bio text)
    if out["sub_position"] is None:
        if re.search(r"central defender|centre.back", group):
            out["sub_position"] = "Centre-Back"
        elif re.search(r"left", group) and re.search(r"back|wingback|wing.back", group):
            out["sub_position"] = "Left-Back"
        elif re.search(r"right", group) and re.search(r"back|wingback|wing.back", group):
            out["sub_position"] = "Right-Back"
        elif re.search(r"central defender|centre back|centre-back", head_low):
            out["sub_position"] = "Centre-Back"
        elif re.search(r"left.back|left wing-back", head_low):
            out["sub_position"] = "Left-Back"
        elif re.search(r"right.back|right wing-back", head_low):
            out["sub_position"] = "Right-Back"

    # --- Competition code ---
    for alias, code in COMPETITION_ALIASES.items():
        if alias in head_low:
            out["competition_code"] = code
            break

    # --- Confederation heuristic (report rarely states it directly) ---
    if re.search(r"europa|europe|uefa|england|premier league|chelsea|bundesliga|serie a|laliga|ligue 1", head_low):
        out["confederation"] = "europa"
    elif re.search(r"amerika|americas|mls|brasil|brazil|argentina|liga mx|concacaf|conmebol", head_low):
        out["confederation"] = "amerika"
    elif re.search(r"asien|asia|afc|j1 league|k league", head_low):
        out["confederation"] = "asien"

    # --- Career table rows like: "Chelsea 608 6 / 6 1 / 0"
    #     (minutes, apps/starts, yellow/red). Summed over the career-history
    #     segment only — ranking/match pages would double-count. Caps summed
    #     over national-team rows; identical rows counted once.
    row_pat = re.compile(r"(\d{2,5})\s+(\d{1,3})\s*/\s*(\d{1,3})\s+(\d{1,3})\s*/\s*(\d{1,3})")
    minutes_total, apps_total, y_total, r_total = 0, 0, 0, 0
    nat_caps = 0
    hits = 0
    seen_rows = set()
    for line in career_seg.splitlines():
        mrow = row_pat.search(line)
        if mrow:
            try:
                mins, apps, _starts, yel, red = map(int, mrow.groups())
            except ValueError:
                continue
            # sanity guards: a row must look like (minutes, apps, cards) —
            # average minutes/appearance within [1, 130], cards <= apps.
            # (Deliberately allows whole-career total rows, not just seasons.)
            if not (1 <= apps <= 1000 and mins <= 60000):
                continue
            if mins < apps or mins / apps > 130:
                continue
            if yel > apps or red > apps or red > 30:
                continue
            norm = re.sub(r"\s+", " ", line.strip())
            if norm in seen_rows:  # identical line printed twice, count once
                continue
            seen_rows.add(norm)
            minutes_total += mins
            apps_total += apps
            y_total += yel
            r_total += red
            hits += 1
    # National-team rows can sit in either the overview or the history table
    seen_nat = set()
    for line in pre_rank.splitlines():
        for mrow in row_pat.finditer(line):
            if not re.search(r"england|national team|u21|u19|u18|u17", line[:mrow.start()], re.IGNORECASE):
                continue
            try:
                mins, apps, _starts, _yel, _red = map(int, mrow.groups())
            except ValueError:
                continue
            if mins < apps or (mins, apps) in seen_nat:
                continue
            seen_nat.add((mins, apps))
            nat_caps += apps
    if hits > 0:
        out["total_minutes"] = float(minutes_total)
        out["matches_played"] = float(apps_total)
        out["yellow_cards"] = float(y_total)
        out["red_cards"] = float(r_total)
        if nat_caps > 0:
            out["international_caps"] = float(nat_caps)

    # --- Market value: "€1,000,000" / "£600k" / "market value 500000" ---
    m = re.search(
        r"market value[^\d€£$]{0,20}[€£$]?\s*([\d,\.]+)\s*(m|million|k|thousand)?",
        t, re.IGNORECASE,
    )
    if not m:
        m = re.search(r"est\.?\s*value\s*[€£$]?\s*([\d,\.]+)\s*(m|million|k|thousand)?", t, re.IGNORECASE)
    if not m:
        m = re.search(r"[€]\s*([\d,\.]+)\s*(m|million|k|thousand)?", t)
    if m:
        try:
            num = float(m.group(1).replace(",", ""))
            mult = (m.group(2) or "").lower()
            if mult in ("m", "million"):
                num *= 1_000_000
            elif mult in ("k", "thousand"):
                num *= 1_000
            if 0 < num < 500_000_000:
                out["market_value_in_eur"] = num
        except ValueError:
            pass

    # --- Goals / assists (only if explicitly labeled; Wyscout defender rows use "-") ---
    m = re.search(r"total goals\s*[:\-]?\s*(\d+)", t, re.IGNORECASE)
    if m:
        out["total_goals"] = float(m.group(1))
    m = re.search(r"total assists\s*[:\-]?\s*(\d+)", t, re.IGNORECASE)
    if m:
        out["total_assists"] = float(m.group(1))

    return out


# Home endpoint
@app.get("/")
def home():
    return {
        "message": "Football Player Potential API is running! (v2 with PDF report upload)"
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


# Original prediction endpoint (unchanged)
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


# NEW: extract structured fields from an uploaded PDF report (no prediction)
@app.post("/extract-report")
async def extract_report(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a PDF file.")
    raw = await file.read()
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="PDF too large (max 10 MB).")
    text = _extract_pdf_text(raw)
    extracted = parse_report_text(text)
    missing = [k for k, v in extracted.items() if v is None]
    return {
        "filename": file.filename,
        "extracted": extracted,
        "missing": missing,
        "text_preview": text[:2000],
    }


# NEW: predict directly from an uploaded PDF report.
# Missing fields become NaN so the pipeline's SimpleImputer fills them
# (median / most_frequent from training). Response flags what was missing.
@app.post("/predict-from-report")
async def predict_from_report(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a PDF file.")
    raw = await file.read()
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="PDF too large (max 10 MB).")
    text = _extract_pdf_text(raw)
    extracted = parse_report_text(text)
    missing = [k for k, v in extracted.items() if v is None]

    row = {}
    for k in ALL_FIELDS:
        v = extracted.get(k)
        row[k] = v if v is not None else float("nan")

    player = pd.DataFrame([row])
    try:
        prediction = model.predict(player)[0]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Model failed on extracted data: {e}")

    return {
        "predicted_future_potential_rating": str(prediction),
        "extracted": extracted,
        "missing_fields_filled_by_model_median": missing,
        "warning": (
            "Partial extraction — verify highlighted fields before trusting this rating."
            if missing else "All fields extracted."
        ),
    }


# --- CSV template track (priority stakeholder path: exact 14 columns, no extraction loss) ---
TEMPLATE_COLUMNS = NUMERIC_FIELDS + CATEGORICAL_FIELDS

TEMPLATE_EXAMPLE = {
    "height_in_cm": 187,
    "international_caps": 6,
    "market_value_in_eur": 500000,
    "matches_played": 197,
    "total_minutes": 15223,
    "total_goals": 7,
    "total_assists": 4,
    "yellow_cards": 38,
    "red_cards": 2,
    "position": "Defender",
    "sub_position": "Centre-Back",
    "foot": "right",
    "competition_code": "liga-portugal",
    "confederation": "europa",
}


@app.get("/template-csv")
def template_csv():
    """Downloadable stakeholder template: exact header + one valid example row."""
    from fastapi.responses import Response

    guide = (
        "# ScoutIQ player template — one row per player, keep this header exactly as-is.\n"
        "# Fill every cell; numbers only in numeric columns.\n"
    )
    header = ",".join(TEMPLATE_COLUMNS)
    row = ",".join(str(TEMPLATE_EXAMPLE[c]) for c in TEMPLATE_COLUMNS)
    return Response(
        content=guide + header + "\n" + row + "\n",
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=player_template.csv"},
    )


@app.post("/predict-from-csv")
async def predict_from_csv(file: UploadFile = File(...)):
    """Batch prediction from an uploaded CSV built on the template."""
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a .csv file built on the template.")
    raw = await file.read()
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="CSV too large (max 5 MB).")
    try:
        text = raw.decode("utf-8-sig")  # utf-8-sig tolerates Excel's BOM
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8 encoded.")
    # Strip the #-comment guide lines the template ships with
    data_lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if not data_lines:
        raise HTTPException(status_code=400, detail="CSV is empty.")
    try:
        df = pd.read_csv(io.StringIO("\n".join(data_lines)))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse CSV: {e}")
    df.columns = [str(c).strip() for c in df.columns]
    missing_cols = [c for c in TEMPLATE_COLUMNS if c not in df.columns]
    if missing_cols:
        raise HTTPException(
            status_code=400,
            detail=f"Missing columns (download a fresh template): {', '.join(missing_cols)}",
        )
    if len(df) == 0:
        raise HTTPException(status_code=400, detail="CSV has a header but no player rows.")
    if len(df) > 500:
        raise HTTPException(status_code=400, detail="Max 500 players per upload.")
    try:
        preds = model.predict(df[TEMPLATE_COLUMNS])
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Model rejected the CSV data: {e}")
    return {
        "count": int(len(df)),
        "results": [
            {"row": i + 1, "predicted_future_potential_rating": str(p)}
            for i, p in enumerate(preds)
        ],
    }
