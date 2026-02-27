"""
common.exceptions
~~~~~~~~~~~~~~~~~
Centralised DRF exception handler and custom exception classes.
"""
import structlog
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = structlog.get_logger(__name__)


class AppError(Exception):
    """Base application error.  Subclass to define domain-specific errors."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    default_code: str = "error"
    default_detail: str = "An error occurred."

    def __init__(self, detail: str | None = None, code: str | None = None) -> None:
        self.detail = detail or self.default_detail
        self.code = code or self.default_code

    def __str__(self) -> str:
        return self.detail


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    default_code = "not_found"
    default_detail = "The requested resource was not found."


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    default_code = "conflict"
    default_detail = "A resource conflict occurred."


class ValidationError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_code = "validation_error"
    default_detail = "Validation failed."


class PermissionDeniedError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    default_code = "permission_denied"
    default_detail = "You do not have permission to perform this action."


def custom_exception_handler(exc: Exception, context: dict) -> Response | None:
    """
    Global DRF exception handler.
    Converts AppError subclasses to JSON responses and delegates everything
    else to the default DRF handler so standard DRF exceptions still work.
    """
    if isinstance(exc, AppError):
        logger.warning(
            "app_error",
            code=exc.code,
            detail=exc.detail,
            status_code=exc.status_code,
        )
        return Response(
            {"code": exc.code, "detail": exc.detail},
            status=exc.status_code,
        )

    response = drf_exception_handler(exc, context)
    if response is not None:
        logger.warning(
            "drf_error",
            detail=response.data,
            status_code=response.status_code,
        )
    else:
        logger.exception("unhandled_exception", exc_info=exc)

    return response
