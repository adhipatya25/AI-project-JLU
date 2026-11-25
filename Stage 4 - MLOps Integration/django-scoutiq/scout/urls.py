from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
# "api-" prefix: the router's auto-named routes (api-player-detail, ...) must not
# clash with the HTML page named "player-detail" below.
router.register(r"players", views.PlayerViewSet, basename="api-player")
router.register(r"predictions", views.PredictionViewSet, basename="api-prediction")

app_name = "scout"

urlpatterns = [
    path("", views.predict_view, name="predict"),
    path("history/", views.history_view, name="history"),
    path("players/<int:pk>/", views.player_detail_view, name="player-detail"),
    path("template.csv", views.template_csv_view, name="template-csv"),
    # JSON endpoints for the predict page (same shapes as the FastAPI service)
    path("ui/predict/", views.predict_api, name="predict-api"),
    path("ui/extract-report/", views.extract_report_api, name="extract-report-api"),
    path("ui/predict-from-report/", views.predict_from_report_api, name="predict-from-report-api"),
    path("ui/predict-from-csv/", views.predict_from_csv_api, name="predict-from-csv-api"),
    path("signup/", views.signup_view, name="signup"),
    path("api/", include(router.urls)),
]
