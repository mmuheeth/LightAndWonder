from datetime import datetime, timezone
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict | None = None


class ResponseMeta(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    path: str | None = None


class ApiResponse(BaseModel, Generic[T]):
    """Global envelope for every API response, success or failure."""

    success: bool
    data: T | None = None
    error: ErrorDetail | None = None
    meta: ResponseMeta = Field(default_factory=ResponseMeta)

    @classmethod
    def ok(cls, data: T | None = None, path: str | None = None) -> "ApiResponse[T]":
        return cls(success=True, data=data, error=None, meta=ResponseMeta(path=path))

    @classmethod
    def fail(
        cls,
        code: str,
        message: str,
        details: dict | None = None,
        path: str | None = None,
    ) -> "ApiResponse[None]":
        return cls(
            success=False,
            data=None,
            error=ErrorDetail(code=code, message=message, details=details),
            meta=ResponseMeta(path=path),
        )
