"""Exception classes for the CourtMesh Python SDK.

Every exception carries the real HTTP status code, the human readable
message and the raw response body (when available), so callers can inspect
exactly what the server returned without re-parsing anything.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Type


class CourtMeshError(Exception):
    """Base class for every error this SDK raises.

    Attributes:
        message: human readable error message.
        status_code: the HTTP status code returned by the server, or None
            when the error happened before a response was received
            (for example a connection error).
        response_body: the parsed JSON response body, when one was
            available. May be a dict, a list, a string or None.
    """

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response_body: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.response_body = response_body

    def __str__(self) -> str:
        if self.status_code is not None:
            return "[{}] {}".format(self.status_code, self.message)
        return self.message

    def __repr__(self) -> str:
        return "{}(message={!r}, status_code={!r})".format(
            type(self).__name__, self.message, self.status_code
        )


class ValidationError(CourtMeshError):
    """HTTP 400. The request failed zod validation or a manual check."""


class AuthenticationError(CourtMeshError):
    """HTTP 401. The API key is missing, malformed, unknown or deactivated."""


class PermissionDeniedError(CourtMeshError):
    """HTTP 403. The organization or account may not perform this request.

    This covers: organization deactivated, account suspended, billing
    inactive, account not found and plan limit reasons. When the server
    reports a plan limit, `response_body` also carries `callsToday` and
    `maxAllowed`.
    """


class NotFoundError(CourtMeshError):
    """HTTP 404. The case, analysis, PDF or timeline job does not exist."""


class RequestTimeoutError(CourtMeshError):
    """HTTP 408. The upstream OpenSearch query took too long."""


class RateLimitError(CourtMeshError):
    """HTTP 429. More than 10 requests per minute for this API key.

    Attributes:
        retry_after: seconds to wait before retrying, taken from the
            `Retry-After` response header first, then the JSON body's
            `retryAfter` field.
        reset_time: the ISO timestamp from the JSON body's `resetTime`
            field, when present.
    """

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response_body: Any = None,
        retry_after: Optional[float] = None,
        reset_time: Optional[str] = None,
    ) -> None:
        super().__init__(message, status_code=status_code, response_body=response_body)
        self.retry_after = retry_after
        self.reset_time = reset_time


class ServerError(CourtMeshError):
    """HTTP 500. Internal server error."""


class BadGatewayError(CourtMeshError):
    """HTTP 502. The server failed to connect to an upstream dependency."""


class ServiceUnavailableError(CourtMeshError):
    """HTTP 503. Account standing could not be verified, please retry."""


STATUS_CODE_TO_EXCEPTION: Dict[int, Type[CourtMeshError]] = {
    400: ValidationError,
    401: AuthenticationError,
    403: PermissionDeniedError,
    404: NotFoundError,
    408: RequestTimeoutError,
    429: RateLimitError,
    500: ServerError,
    502: BadGatewayError,
    503: ServiceUnavailableError,
}


def build_error(
    status_code: int,
    message: str,
    response_body: Any = None,
    retry_after: Optional[float] = None,
    reset_time: Optional[str] = None,
) -> CourtMeshError:
    """Build the exception instance matching a given HTTP status code.

    Status codes not in the mapping (for example 504, which the SDK retries
    but the spec does not name a dedicated class for) fall back to the base
    `CourtMeshError`.
    """
    exc_class = STATUS_CODE_TO_EXCEPTION.get(status_code, CourtMeshError)
    if exc_class is RateLimitError:
        return RateLimitError(
            message,
            status_code=status_code,
            response_body=response_body,
            retry_after=retry_after,
            reset_time=reset_time,
        )
    return exc_class(message, status_code=status_code, response_body=response_body)
