"""Exception classes for the CourtMesh Python SDK.

Every exception carries the real HTTP status code, the human readable
message and the raw response body (when available), so callers can inspect
exactly what the server returned without re-parsing anything.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple, Type

try:
    from typing import Literal
except ImportError:  # pragma: no cover - Python 3.7/3.8 fallback, unused at runtime
    Literal = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Machine readable refusal codes, mirroring the research server's
# API_REFUSAL_CODES (server/config/api-tiers.ts), plus the handler-local
# codes used outside that table (CASE_RESTRICTED, PDF_NOT_STORED,
# CASE_NOT_FOUND, PARTY_SCREEN_SEARCH_DEGRADED, CURSOR_INVALID,
# PAGE_LIMIT_EXCEEDED, PAGINATION_DEPTH_EXCEEDED, the API_KEY_* auth codes,
# and the JSON/body-parser codes this SDK synthesises client side since the
# server itself attaches no `code` field to those).
# ---------------------------------------------------------------------------

if Literal is not None:
    ApiRefusalCode = Literal[
        "API_ENTERPRISE_ONLY",
        "API_NOT_AVAILABLE_ON_TRIAL",
        "API_NO_KEYS",
        "INSUFFICIENT_API_CREDITS",
        "FREE_TIER_AI_CAP_REACHED",
        "ENTITLEMENT_UNAVAILABLE",
        "API_KEY_LIMIT_REACHED",
        "API_TIER_NOT_ALLOWED",
        "PARTY_SCREEN_LIMIT_REACHED",
        "DISTINCT_NAMES_LIMIT_REACHED",
        "LIVE_FETCH_NOT_ALLOWED",
        "LIVE_FETCH_LIMIT_REACHED",
        "DISTINCT_CASES_LIMIT_REACHED",
        "PDF_LIMIT_REACHED",
        "TOO_MANY_KEYS_FROM_IP",
        "EMAIL_NOT_VERIFIED",
        "CONCURRENT_ANALYSIS_LIMIT",
        "REMOTE_FETCH_NOT_ALLOWED",
        "CURSOR_INVALID",
        "SEMANTIC_NOT_ALLOWED",
        "API_RATE_LIMIT_EXCEEDED",
        "RATE_LIMITED",
        "PAGE_LIMIT_EXCEEDED",
        "PAGINATION_DEPTH_EXCEEDED",
        "CASE_RESTRICTED",
        "PDF_NOT_STORED",
        "CASE_NOT_FOUND",
        "PARTY_SCREEN_SEARCH_DEGRADED",
        "API_KEY_MISSING",
        "API_KEY_INVALID_FORMAT",
        "API_KEY_INVALID",
        "API_KEY_REVOKED",
        "API_KEY_EXPIRED",
        "ORGANIZATION_DEACTIVATED",
        "ACCOUNT_STANDING_UNAVAILABLE",
        "IP_NOT_ALLOWED",
        "VALIDATION_ERROR",
        "MALFORMED_JSON",
        "PAYLOAD_TOO_LARGE",
        "IDEMPOTENCY_KEY_REUSED",
        "IDEMPOTENCY_IN_PROGRESS",
        "IDEMPOTENCY_KEY_INVALID",
    ]
else:  # pragma: no cover
    ApiRefusalCode = str  # type: ignore[assignment,misc]

#: Every known refusal code, as a tuple for membership testing
#: (``if exc.code in API_REFUSAL_CODES:``) without hand-typing string
#: literals. Kept in sync with `ApiRefusalCode` above.
API_REFUSAL_CODES: Tuple[str, ...] = (
    "API_ENTERPRISE_ONLY",
    "API_NOT_AVAILABLE_ON_TRIAL",
    "API_NO_KEYS",
    "INSUFFICIENT_API_CREDITS",
    "FREE_TIER_AI_CAP_REACHED",
    "ENTITLEMENT_UNAVAILABLE",
    "API_KEY_LIMIT_REACHED",
    "API_TIER_NOT_ALLOWED",
    "PARTY_SCREEN_LIMIT_REACHED",
    "DISTINCT_NAMES_LIMIT_REACHED",
    "LIVE_FETCH_NOT_ALLOWED",
    "LIVE_FETCH_LIMIT_REACHED",
    "DISTINCT_CASES_LIMIT_REACHED",
    "PDF_LIMIT_REACHED",
    "TOO_MANY_KEYS_FROM_IP",
    "EMAIL_NOT_VERIFIED",
    "CONCURRENT_ANALYSIS_LIMIT",
    "REMOTE_FETCH_NOT_ALLOWED",
    "CURSOR_INVALID",
    "SEMANTIC_NOT_ALLOWED",
    "API_RATE_LIMIT_EXCEEDED",
    "RATE_LIMITED",
    "PAGE_LIMIT_EXCEEDED",
    "PAGINATION_DEPTH_EXCEEDED",
    "CASE_RESTRICTED",
    "PDF_NOT_STORED",
    "CASE_NOT_FOUND",
    "PARTY_SCREEN_SEARCH_DEGRADED",
    "API_KEY_MISSING",
    "API_KEY_INVALID_FORMAT",
    "API_KEY_INVALID",
    "API_KEY_REVOKED",
    "API_KEY_EXPIRED",
    "ORGANIZATION_DEACTIVATED",
    "ACCOUNT_STANDING_UNAVAILABLE",
    "IP_NOT_ALLOWED",
    "VALIDATION_ERROR",
    "MALFORMED_JSON",
    "PAYLOAD_TOO_LARGE",
    "IDEMPOTENCY_KEY_REUSED",
    "IDEMPOTENCY_IN_PROGRESS",
    "IDEMPOTENCY_KEY_INVALID",
)

#: 429 codes safe to retry automatically. Never a daily/monthly cap code.
_RETRYABLE_429_CODES = frozenset({"RATE_LIMITED", "CONCURRENT_ANALYSIS_LIMIT"})

#: 429 codes that will not clear before their advertised delay, so retrying
#: them automatically is pointless (and can look like a hang).
_DAILY_CAP_429_CODES = frozenset(
    {
        "DISTINCT_NAMES_LIMIT_REACHED",
        "LIVE_FETCH_LIMIT_REACHED",
        "DISTINCT_CASES_LIMIT_REACHED",
        "PDF_LIMIT_REACHED",
        "TOO_MANY_KEYS_FROM_IP",
    }
)


def is_retryable_429_code(code: Optional[str]) -> bool:
    """Whether a 429 response's `code` is safe to retry automatically.

    `None` (no `code` field on the wire, the legacy/plain rate limiter) is
    treated as retryable. A known daily/monthly cap code never is.
    """
    if code is None:
        return True
    if code in _DAILY_CAP_429_CODES:
        return False
    return code in _RETRYABLE_429_CODES


class CourtMeshError(Exception):
    """Base class for every error this SDK raises.

    Attributes:
        message: human readable error message.
        status_code: the HTTP status code returned by the server, or None
            when the error happened before a response was received
            (for example a connection error).
        response_body: the parsed JSON response body, when one was
            available. May be a dict, a list, a string or None.
        code: the server's machine readable `code` field verbatim (see
            `ApiRefusalCode`/`API_REFUSAL_CODES`), when the server sent one.
            None on older server responses that carry no `code`.
        request_id: echoed from the response body's `requestId` field (sent
            once the API's request-id middleware ships) or, failing that,
            the `X-Request-Id` response header, when either is present.
    """

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response_body: Any = None,
        code: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.response_body = response_body
        self.code = code
        self.request_id = request_id

    def __str__(self) -> str:
        if self.status_code is not None:
            return "[{}] {}".format(self.status_code, self.message)
        return self.message

    def __repr__(self) -> str:
        return "{}(message={!r}, status_code={!r}, code={!r})".format(
            type(self).__name__, self.message, self.status_code, self.code
        )


class ValidationError(CourtMeshError):
    """HTTP 400. The request failed validation, an invalid pagination
    cursor (`code == "CURSOR_INVALID"`), or a per tier pagination cap
    (`code` in `("PAGE_LIMIT_EXCEEDED", "PAGINATION_DEPTH_EXCEEDED")`).

    Attributes:
        limit: populated for the two pagination cap codes above.
        tier: populated for the two pagination cap codes above.

    The two pagination cap codes' response body carries no `error`/`message`
    field of its own (`{"success": False, "code", "limit", "tier"}`); this
    SDK synthesises `message` for you in that case, see `_http.py`.
    """

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response_body: Any = None,
        code: Optional[str] = None,
        request_id: Optional[str] = None,
        limit: Optional[int] = None,
        tier: Optional[str] = None,
    ) -> None:
        super().__init__(
            message,
            status_code=status_code,
            response_body=response_body,
            code=code,
            request_id=request_id,
        )
        self.limit = limit
        self.tier = tier


class PayloadTooLargeError(ValidationError):
    """HTTP 413. The request body was larger than the server accepts. Not retried."""


class AuthenticationError(CourtMeshError):
    """HTTP 401. The API key is missing, malformed, unknown, revoked or
    expired. `code` is one of `API_KEY_MISSING`, `API_KEY_INVALID_FORMAT`,
    `API_KEY_INVALID`, `API_KEY_REVOKED`, `API_KEY_EXPIRED` when the server
    sends one.
    """


class InsufficientCreditsError(CourtMeshError):
    """HTTP 402. The account does not have enough API credits for this
    call.

    Applies to every priced endpoint (each one pre-flight reserves the
    charge before doing any work), not only `screen_party`.

    Attributes:
        required: credits required for this call.
        balance: credits currently available.
        shortfall: `required - balance`.
        wallet: always `"api_credits"` today.
        wallet_owner: `"user"` or `"org"`, whose wallet was charged against.
        top_up_url: a page to buy more credits. Mutually exclusive with
            `contact_admin`.
        contact_admin: True when this account cannot self serve a top up
            and must contact its admin instead.
    """

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response_body: Any = None,
        code: Optional[str] = None,
        request_id: Optional[str] = None,
        required: Optional[float] = None,
        balance: Optional[float] = None,
        shortfall: Optional[float] = None,
        top_up_url: Optional[str] = None,
        wallet: Optional[str] = None,
        wallet_owner: Optional[str] = None,
        contact_admin: Optional[bool] = None,
    ) -> None:
        super().__init__(
            message,
            status_code=status_code,
            response_body=response_body,
            code=code,
            request_id=request_id,
        )
        self.required = required
        self.balance = balance
        self.shortfall = shortfall
        self.top_up_url = top_up_url
        self.wallet = wallet
        self.wallet_owner = wallet_owner
        self.contact_admin = contact_admin


class PermissionDeniedError(CourtMeshError):
    """HTTP 403. The organization or account may not perform this request.

    This covers: organization deactivated, account suspended, billing
    inactive, account not found and plan limit reasons. When the server
    reports a plan limit, `response_body` also carries `callsToday` and
    `maxAllowed`. Tier/feature restrictions (Free tier calling an AI
    analysis endpoint, semantic search, a live/remote fetch, or
    `party/screen` past its free allowance, a trial account calling the API
    at all) instead carry `code` (for example `API_NOT_AVAILABLE_ON_TRIAL`,
    `API_TIER_NOT_ALLOWED`, `SEMANTIC_NOT_ALLOWED`, `LIVE_FETCH_NOT_ALLOWED`,
    `REMOTE_FETCH_NOT_ALLOWED`, `PARTY_SCREEN_LIMIT_REACHED`) and
    `response_body["upgradeUrl"]`.
    """


class NotFoundError(CourtMeshError):
    """HTTP 404. The case, analysis, PDF or timeline job does not exist.

    `code` is `CASE_NOT_FOUND` or `PDF_NOT_STORED` (no stored document; see
    `response_body["hint"]`) on the pdf endpoint.
    """


class ConflictError(CourtMeshError):
    """HTTP 409. An `Idempotency-Key` conflict.

    `code == "IDEMPOTENCY_KEY_REUSED"` when the same key was sent with a
    different request body than the one it was first used with, or
    `code == "IDEMPOTENCY_IN_PROGRESS"` when a request with this same key
    is still being processed concurrently (retry shortly). Only ever raised
    by `screen_party`, `screen_party_batch`, `analyze_case`,
    `analyze_consolidated` and `request_timeline`, the five methods that
    accept an `idempotency_key`.
    """


class RequestTimeoutError(CourtMeshError):
    """HTTP 408. The upstream OpenSearch query took too long, or the SDK's
    own client side timeout fired."""


class RateLimitError(CourtMeshError):
    """HTTP 429: the per key/IP rate limit (`code == "RATE_LIMITED"`), a
    concurrency cap (`"CONCURRENT_ANALYSIS_LIMIT"`), or a daily/monthly cap
    (`"DISTINCT_NAMES_LIMIT_REACHED"`, `"LIVE_FETCH_LIMIT_REACHED"`,
    `"DISTINCT_CASES_LIMIT_REACHED"`, `"PDF_LIMIT_REACHED"`,
    `"TOO_MANY_KEYS_FROM_IP"`). Only the first two are ever retried
    automatically, see `is_retryable_429_code`.

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
        code: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> None:
        super().__init__(
            message,
            status_code=status_code,
            response_body=response_body,
            code=code,
            request_id=request_id,
        )
        self.retry_after = retry_after
        self.reset_time = reset_time


class ServerError(CourtMeshError):
    """HTTP 500. Internal server error."""


class BadGatewayError(CourtMeshError):
    """HTTP 502. The server failed to connect to an upstream dependency, or
    `code == "PARTY_SCREEN_SEARCH_DEGRADED"` (the underlying case search
    itself errored and returned nothing usable, retry).
    """


class ServiceUnavailableError(CourtMeshError):
    """HTTP 503. Account standing could not be verified
    (`code == "ENTITLEMENT_UNAVAILABLE"`), or the service is otherwise
    unavailable. Safe to retry.
    """


STATUS_CODE_TO_EXCEPTION: Dict[int, Type[CourtMeshError]] = {
    400: ValidationError,
    401: AuthenticationError,
    402: InsufficientCreditsError,
    403: PermissionDeniedError,
    404: NotFoundError,
    409: ConflictError,
    408: RequestTimeoutError,
    413: PayloadTooLargeError,
    429: RateLimitError,
    500: ServerError,
    502: BadGatewayError,
    503: ServiceUnavailableError,
}


def _get(body: Any, key: str) -> Any:
    return body.get(key) if isinstance(body, dict) else None


def build_error(
    status_code: int,
    message: str,
    response_body: Any = None,
    retry_after: Optional[float] = None,
    reset_time: Optional[str] = None,
    code: Optional[str] = None,
    request_id: Optional[str] = None,
) -> CourtMeshError:
    """Build the exception instance matching a given HTTP status code.

    Status codes not in the mapping (for example 504, which the SDK retries
    but the spec does not name a dedicated class for) fall back to the base
    `CourtMeshError`. `code` and `request_id`, when not passed explicitly,
    are read from `response_body` for convenience.
    """
    if code is None:
        code = _get(response_body, "code")
    if request_id is None:
        request_id = _get(response_body, "requestId")

    exc_class = STATUS_CODE_TO_EXCEPTION.get(status_code, CourtMeshError)

    if exc_class is RateLimitError:
        return RateLimitError(
            message,
            status_code=status_code,
            response_body=response_body,
            retry_after=retry_after,
            reset_time=reset_time,
            code=code,
            request_id=request_id,
        )
    if exc_class is InsufficientCreditsError:
        return InsufficientCreditsError(
            message,
            status_code=status_code,
            response_body=response_body,
            code=code,
            request_id=request_id,
            required=_get(response_body, "required"),
            balance=_get(response_body, "balance"),
            shortfall=_get(response_body, "shortfall"),
            top_up_url=_get(response_body, "topUpUrl"),
            wallet=_get(response_body, "wallet"),
            wallet_owner=_get(response_body, "walletOwner"),
            contact_admin=_get(response_body, "contactAdmin"),
        )
    if exc_class is ValidationError or exc_class is PayloadTooLargeError:
        return exc_class(
            message,
            status_code=status_code,
            response_body=response_body,
            code=code,
            request_id=request_id,
            limit=_get(response_body, "limit"),
            tier=_get(response_body, "tier"),
        )
    return exc_class(
        message,
        status_code=status_code,
        response_body=response_body,
        code=code,
        request_id=request_id,
    )
