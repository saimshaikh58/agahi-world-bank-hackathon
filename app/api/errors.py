"""One error shape for every API failure."""
from __future__ import annotations

from fastapi.responses import JSONResponse


class ApiError(Exception):
    """Raise to return {"error": {"code", "message"}} with a status code."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def error_response(status: int, code: str, message: str) -> JSONResponse:
    """Build the standard error JSON."""
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)
