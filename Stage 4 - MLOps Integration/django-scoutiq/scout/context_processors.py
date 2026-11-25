from . import ml


def model_service(request):
    """Sidebar status: FastAPI /health JSON when online, {} when offline."""
    if not request.user.is_authenticated:
        return {"model_service": None}
    return {"model_service": ml.service_health() or {}}
