from typing import Any, Dict, Optional
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse


class AppException(Exception):
    """Base application exception."""

    def __init__(
        self,
        message: str,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        details: Optional[Any] = None,
    ):
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(message)


class NotFoundException(AppException):
    def __init__(self, message: str = "Resource not found", details: Optional[Any] = None):
        super().__init__(message, status_code=status.HTTP_404_NOT_FOUND, details=details)


class UnauthorizedException(AppException):
    def __init__(self, message: str = "Authentication required", details: Optional[Any] = None):
        super().__init__(message, status_code=status.HTTP_401_UNAUTHORIZED, details=details)


class ForbiddenException(AppException):
    def __init__(self, message: str = "Access forbidden", details: Optional[Any] = None):
        super().__init__(message, status_code=status.HTTP_403_FORBIDDEN, details=details)


class BadRequestException(AppException):
    def __init__(self, message: str = "Bad request", details: Optional[Any] = None):
        super().__init__(message, status_code=status.HTTP_400_BAD_REQUEST, details=details)


class ConflictException(AppException):
    def __init__(self, message: str = "Resource conflict", details: Optional[Any] = None):
        super().__init__(message, status_code=status.HTTP_409_CONFLICT, details=details)


class PayloadTooLargeException(AppException):
    def __init__(self, message: str = "File size exceeds allowed limit", details: Optional[Any] = None):
        super().__init__(message, status_code=getattr(status, "HTTP_413_CONTENT_TOO_LARGE", 413), details=details)


class UnsupportedMediaTypeException(AppException):
    def __init__(self, message: str = "Unsupported media type", details: Optional[Any] = None):
        super().__init__(message, status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, details=details)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
        content: Dict[str, Any] = {
            "detail": exc.message,
            "error": {
                "message": exc.message,
                "status_code": exc.status_code,
            },
        }
        if exc.details is not None:
            content["error"]["details"] = exc.details
        return JSONResponse(status_code=exc.status_code, content=content)
