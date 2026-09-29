import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import AppException
from app.schemas.response import ApiResponse

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
        logger.warning("AppException: %s | path=%s", exc.message, request.url.path)
        response = ApiResponse.fail(
            code=exc.error_code,
            message=exc.message,
            details=exc.details,
            path=str(request.url.path),
        )
        return JSONResponse(status_code=exc.status_code, content=response.model_dump(mode="json"))

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        logger.warning("ValidationError: %s | path=%s", exc.errors(), request.url.path)
        response = ApiResponse.fail(
            code="VALIDATION_ERROR",
            message="Request validation failed",
            details={"errors": exc.errors()},
            path=str(request.url.path),
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=response.model_dump(mode="json"),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        response = ApiResponse.fail(
            code="HTTP_ERROR",
            message=str(exc.detail),
            path=str(request.url.path),
        )
        return JSONResponse(status_code=exc.status_code, content=response.model_dump(mode="json"))

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception | path=%s", request.url.path)
        response = ApiResponse.fail(
            code="INTERNAL_ERROR",
            message="An unexpected error occurred",
            path=str(request.url.path),
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=response.model_dump(mode="json"),
        )
