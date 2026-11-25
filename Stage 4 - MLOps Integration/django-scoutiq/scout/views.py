import json
from functools import wraps

from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from rest_framework import permissions, viewsets

from . import ml, pdfextract
from .forms import PlayerForm
from .models import POSITION_CHOICES, Player, Prediction
from .serializers import PlayerSerializer, PredictionSerializer


# ---------- HTML pages ----------

@login_required
def predict_view(request):
    """Single stakeholder page (same UI as the FastAPI frontend).

    The page talks to the JSON endpoints below with fetch(); each of them
    asks the FastAPI model service for the rating and stores the result.
    """
    return render(request, "scout/predict.html")


# ---------- JSON endpoints used by static/scout-predict.js ----------

def api_login_required(view):
    """Like login_required, but answers fetch() calls with JSON 401, not a redirect."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"detail": "Your session ended. Log in again, then retry."}, status=401)
        return view(request, *args, **kwargs)
    return wrapper


def _error(message, status=400):
    return JsonResponse({"detail": message}, status=status)


def _form_errors(form):
    return "; ".join(f"{f}: {', '.join(errs)}" for f, errs in form.errors.items())


def _store(form, user, rating):
    """Save Player + Prediction; return the ids the page links to."""
    player = form.save(commit=False)
    player.created_by = user
    player.save()
    prediction = Prediction.objects.create(player=player, predicted_rating=rating, predicted_by=user)
    return {
        "player_id": player.id,
        "prediction_id": prediction.id,
        "player_url": reverse("scout:player-detail", args=[player.id]),
    }


def _uploaded(request, ext, max_mb):
    """Return (file, None) or (None, error JsonResponse)."""
    upload = request.FILES.get("file")
    if not upload:
        return None, _error("Choose a file first, then try again.")
    if not upload.name.lower().endswith(ext):
        return None, _error(f"That file is not a {ext} file.")
    if upload.size > max_mb * 1024 * 1024:
        return None, _error(f"File too large (max {max_mb} MB).")
    return upload, None


def _read_pdf(upload):
    try:
        extracted = pdfextract.parse_report_text(pdfextract.extract_pdf_text(upload.read()))
    except Exception as e:  # unreadable / not really a PDF
        return None, _error(str(e) or "Could not read this PDF.")
    return extracted, None


@require_POST
@api_login_required
def predict_api(request):
    """Manual form -> FastAPI /predict -> stored Player + Prediction."""
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return _error("Request body must be JSON.")
    data["name"] = (str(data.get("name") or "").strip()
                    or f"Player #{Player.objects.count() + 1}")
    form = PlayerForm(data)
    if not form.is_valid():
        return _error(_form_errors(form))
    try:
        rating = ml.predict_player(form.to_features())
    except ml.PredictionServiceError as e:
        return _error(str(e), status=503)
    return JsonResponse({"predicted_future_potential_rating": rating,
                         **_store(form, request.user, rating)})


@require_POST
@api_login_required
def extract_report_api(request):
    """PDF -> the 14 fields (no prediction); the page pre-fills its form."""
    upload, err = _uploaded(request, ".pdf", 10)
    if err:
        return err
    extracted, err = _read_pdf(upload)
    if err:
        return err
    missing = [k for k, v in extracted.items() if v is None]
    return JsonResponse({"filename": upload.name, "extracted": extracted, "missing": missing})


@require_POST
@api_login_required
def predict_from_report_api(request):
    """PDF -> extract -> predict.

    All 14 fields found: FastAPI /predict, stored like a manual prediction.
    Some missing: FastAPI /predict-partial (model imputes them); not stored,
    because a Player record needs all 14 real values.
    """
    upload, err = _uploaded(request, ".pdf", 10)
    if err:
        return err
    extracted, err = _read_pdf(upload)
    if err:
        return err
    missing = [k for k, v in extracted.items() if v is None]
    form = PlayerForm({**extracted, "name": upload.name.rsplit(".", 1)[0][:120]})
    try:
        if not missing and form.is_valid():
            rating = ml.predict_player(form.to_features())
            saved = _store(form, request.user, rating)
            warning = "All fields extracted."
        else:
            rating = ml.predict_partial(extracted)
            saved = {}
            warning = ("Partial extraction — verify highlighted fields before trusting this rating. "
                       "Not saved to history: complete the form and predict to store it.")
    except ml.PredictionServiceError as e:
        return _error(str(e), status=503)
    return JsonResponse({
        "predicted_future_potential_rating": rating,
        "extracted": extracted,
        "missing_fields_filled_by_model_median": missing,
        "warning": warning,
        **saved,
    })


@require_POST
@api_login_required
def predict_from_csv_api(request):
    """Template CSV -> one stored Player + Prediction per valid row."""
    upload, err = _uploaded(request, ".csv", 5)
    if err:
        return err
    outcomes = handle_csv_upload(upload, request.user)
    if isinstance(outcomes, str):
        return _error(outcomes, status=503 if "model service" in outcomes else 400)
    for o in outcomes:
        if o["ok"]:
            o["player_url"] = reverse("scout:player-detail", args=[o["player_id"]])
    return JsonResponse({"count": len(outcomes), "results": outcomes})


@login_required
def history_view(request):
    """All stored predictions; server renders the shell, rows come from the API."""
    return render(request, "scout/history.html", {
        "positions": [c[0] for c in POSITION_CHOICES],
    })


@login_required
def player_detail_view(request, pk):
    player = get_object_or_404(
        Player.objects.prefetch_related("predictions"), pk=pk
    )
    return render(request, "scout/player_detail.html", {"player": player})


def handle_csv_upload(upload, user):
    """Parse a template-built CSV; store one Player + Prediction per valid row.

    Returns a list of per-row outcomes, or an error string on fatal failure.
    """
    import pandas as pd

    try:
        text = upload.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        return "CSV must be UTF-8 encoded."
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        return "CSV is empty."
    try:
        df = pd.read_csv(__import__("io").StringIO("\n".join(lines)))
    except Exception as e:
        return f"Could not parse CSV: {e}"
    df.columns = [str(c).strip() for c in df.columns]
    missing_cols = [c for c in ml.FEATURES if c not in df.columns]
    if missing_cols:
        return f"Missing columns (download a fresh template): {', '.join(missing_cols)}"
    if len(df) == 0:
        return "CSV has a header but no player rows."
    if len(df) > 500:
        return "Max 500 players per upload."
    outcomes = []
    for i, record in enumerate(df.to_dict("records"), start=1):
        name = record.get("name") or f"CSV Player #{i}"
        data = {"name": name}
        for col in ml.FEATURES:
            v = record.get(col)
            data[col] = None if (v is None or (isinstance(v, float) and pd.isna(v)) or v == "") else v
        form = PlayerForm(data)
        if not form.is_valid():
            outcomes.append({"row": i, "name": name, "ok": False, "error": "; ".join(
                f"{f}: {', '.join(e for e in errs)}" for f, errs in form.errors.items()
            )})
            continue
        try:
            rating = ml.predict_player(form.to_features())
        except ml.PredictionServiceError as e:
            stored = sum(1 for o in outcomes if o["ok"])
            return f"{e} (Stopped at row {i}; {stored} earlier row(s) were stored.)"
        player = form.save(commit=False)
        player.created_by = user
        player.save()
        Prediction.objects.create(player=player, predicted_rating=rating, predicted_by=user)
        outcomes.append({"row": i, "name": name, "ok": True, "rating": rating,
                         "player_id": player.id})
    return outcomes


def template_csv_view(request):
    """Downloadable stakeholder template: optional name + exact 14 columns."""
    header = "name," + ",".join(ml.FEATURES)
    example = ("Example Defender,187,6,500000,197,15223,7,4,38,2,"
               "Defender,Centre-Back,right,liga-portugal,europa")
    guide = ("# ScoutIQ player template — one row per player, keep this header exactly as-is.\n"
             "# 'name' is for your records only (the model uses the 14 numbers/fields after it).\n")
    content = guide + header + "\n" + example + "\n"
    response = HttpResponse(content, content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="player_template.csv"'
    return response


def signup_view(request):
    if request.user.is_authenticated:
        return redirect("scout:predict")
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            login(request, form.save())
            return redirect("scout:predict")
    else:
        form = UserCreationForm()
    return render(request, "registration/signup.html", {"form": form})


# ---------- REST API (faculty step 2: ViewSets + select_related) ----------

class PlayerViewSet(viewsets.ModelViewSet):
    queryset = Player.objects.all().order_by("-created_at")
    serializer_class = PlayerSerializer
    permission_classes = [permissions.IsAuthenticated]


class PredictionViewSet(viewsets.ModelViewSet):
    serializer_class = PredictionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = Prediction.objects.select_related("player", "predicted_by").order_by("-created_at")
        position = self.request.query_params.get("position")
        rating = self.request.query_params.get("rating")
        search = self.request.query_params.get("search")
        if position:
            qs = qs.filter(player__position=position)
        if rating:
            qs = qs.filter(predicted_rating=rating)
        if search:
            qs = qs.filter(player__name__icontains=search)
        return qs
