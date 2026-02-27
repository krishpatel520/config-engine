"""
common.middleware
~~~~~~~~~~~~~~~~~
Structured JSON request-logging middleware powered by structlog.

Logs: method, path, status_code, duration_ms on every request/response cycle.
"""
import time

import structlog

logger = structlog.get_logger(__name__)


class StructuredLoggingMiddleware:
    """
    WSGI middleware that emits one structured log record per HTTP request.

    Log record fields:
        event       – "http_request"
        method      – HTTP verb (GET, POST, …)
        path        – URL path
        status      – HTTP response status code (int)
        duration_ms – Round-trip duration in milliseconds (float, 2 dp)
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.monotonic()
        response = self.get_response(request)
        duration_ms = round((time.monotonic() - start) * 1000, 2)

        logger.info(
            "http_request",
            method=request.method,
            path=request.get_full_path(),
            status=response.status_code,
            duration_ms=duration_ms,
        )
        return response
