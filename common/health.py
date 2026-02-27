"""
common.health
~~~~~~~~~~~~~
GET /health/ – lightweight liveness + readiness probe.

Returns:
    200  {"status": "ok",   "db": "ok"}    – everything healthy
    503  {"status": "degraded", "db": "error: <msg>"} – DB unreachable
"""
import structlog
from django.db import connection, OperationalError
from django.http import JsonResponse

logger = structlog.get_logger(__name__)


def health_check(request):
    """Return service health including database connectivity status."""
    db_status: str
    http_status: int

    try:
        connection.ensure_connection()
        db_status = "ok"
        http_status = 200
    except OperationalError as exc:
        db_status = f"error: {exc}"
        http_status = 503
        logger.error("health_check_db_failure", error=str(exc))

    payload = {
        "status": "ok" if http_status == 200 else "degraded",
        "db": db_status,
    }
    return JsonResponse(payload, status=http_status)
