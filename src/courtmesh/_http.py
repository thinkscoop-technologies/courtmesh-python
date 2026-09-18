"""Low level HTTP transport for the CourtMesh SDK.

Handles retries with exponential backoff plus jitter, rate limit aware
delays and turning error response bodies into the right `CourtMeshError`
subclass. This module has no knowledge of individual endpoints, that
lives in `client.py`.
"""
from __future__ import annotations

import random
import time
from typing import Any, Dict, Optional

import requests

from .errors import CourtMeshError, RateLimitError, build_error, is_retryable_429_code

DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_MAX_RETRY_AFTER_SECONDS = 60.0

# Status codes retried automatically: 429 (subject to its own code, see
# is_retryable_429_code and R2) plus the three upstream connectivity
# failures 502, 503, 504. For a POST, the 5xx ones (and a network level
# failure) are retried only when retry_posts is True, see R3 below.
_RETRYABLE_5XX_STATUS_CODES = frozenset({502, 503, 504})
_MAX_BACKOFF_SECONDS = 30.0


def _synthesize_message_from_code(code: str, body: Any) -> str:
    """A human message for a body that carries a machine `code` but no
    `error`/`message` field of its own - today only the two tier pagination
    caps, whose response is deliberately
    `{"success": False, "code", "limit", "tier"}`.
    """
    limit = body.get("limit") if isinstance(body, dict) else None
    tier = body.get("tier") if isinstance(body, dict) else None
    if code == "PAGE_LIMIT_EXCEEDED":
        return "Requested page size{} exceeds the maximum for the{} tier.".format(
            " ({})".format(limit) if limit is not None else "",
            " {}".format(tier) if tier else "",
        )
    if code == "PAGINATION_DEPTH_EXCEEDED":
        return "This query has paged deeper than the{} tier allows. Narrow the query instead of paging further.".format(
            " {}".format(tier) if tier else ""
        )
    return "Request refused with code {}.".format(code)


class HTTPTransport:
    """Wraps a `requests.Session` with retry, backoff and auth logic."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        session: Optional[requests.Session] = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        auth_header: str = "authorization",
        retry_posts: bool = False,
        max_retry_after_seconds: float = DEFAULT_MAX_RETRY_AFTER_SECONDS,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_retries = max_retries
        self.auth_header = auth_header
        self.retry_posts = retry_posts
        self.max_retry_after_seconds = max_retry_after_seconds

    def close(self) -> None:
        self.session.close()

    def _auth_headers(self) -> Dict[str, str]:
        if self.auth_header == "x-api-key":
            return {"X-API-Key": self.api_key}
        return {"Authorization": "Bearer {}".format(self.api_key)}

    def _advertised_retry_after_seconds(self, response: requests.Response) -> Optional[float]:
        """`Retry-After` header first, then the JSON body's `retryAfter`.
        `None` means the server did not tell us how long to wait.
        """
        header_value = response.headers.get("Retry-After")
        if header_value:
            try:
                return float(header_value)
            except (TypeError, ValueError):
                pass
        try:
            body = response.json()
        except ValueError:
            body = None
        if isinstance(body, dict):
            retry_after = body.get("retryAfter")
            if isinstance(retry_after, (int, float)):
                return float(retry_after)
        return None

    def _backoff_seconds(self, attempt: int) -> float:
        """Exponential backoff with jitter, capped at 30 seconds."""
        base = min(_MAX_BACKOFF_SECONDS, 0.5 * (2 ** (attempt - 1)))
        return base + random.uniform(0, base * 0.5)

    def request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        require_auth: bool = True,
        timeout: Optional[float] = None,
        retry_posts: Optional[bool] = None,
        idempotency_key: Optional[str] = None,
    ) -> requests.Response:
        """Issue one request, retrying per the rules documented on
        `CourtMesh.__init__`.

        Args:
            timeout: overrides the transport's own default for this one
                call (used by callers with a longer per endpoint default,
                e.g. semantic search).
            retry_posts: overrides `self.retry_posts` for this one call.
            idempotency_key: sent as the `Idempotency-Key` header when
                given. Stable across every retry attempt of this same call.
        """
        url = "{}{}".format(self.base_url, path)
        headers = {"Accept": "application/json"}
        if require_auth:
            headers.update(self._auth_headers())
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        effective_timeout = self.timeout if timeout is None else timeout
        effective_retry_posts = self.retry_posts if retry_posts is None else retry_posts
        # R3: a POST is only retried after it has reached the network (a
        # connection/timeout error, or a 502/503/504 response) when this
        # call, or the client, opted in. A 429 is not gated by this - see
        # below, it is a pre-flight refusal, not evidence the request was
        # ever processed.
        can_retry_after_dispatch = method.upper() == "GET" or effective_retry_posts

        attempt = 0
        while True:
            try:
                response = self.session.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers=headers,
                    timeout=effective_timeout,
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                attempt += 1
                if attempt > self.max_retries or not can_retry_after_dispatch:
                    raise CourtMeshError(
                        "Connection error after {} attempt(s): {}".format(attempt, exc)
                    ) from exc
                time.sleep(self._backoff_seconds(attempt))
                continue

            if response.status_code == 429:
                try:
                    body = response.json()
                except ValueError:
                    body = None
                code = body.get("code") if isinstance(body, dict) else None
                advertised = self._advertised_retry_after_seconds(response)
                retryable_code = is_retryable_429_code(code)
                cap_exceeded = advertised is not None and advertised > self.max_retry_after_seconds

                if retryable_code and cap_exceeded:
                    # R1: do not sleep for longer than max_retry_after_seconds.
                    # Raise immediately instead, with the real (uncapped)
                    # delay attached so the caller can decide for itself
                    # whether to wait that long.
                    self._raise_error(response, body, retry_after_override=advertised)

                if retryable_code and attempt < self.max_retries:
                    attempt += 1
                    delay = advertised if advertised is not None else self._backoff_seconds(attempt)
                    time.sleep(delay)
                    continue

                # Not a retryable code (a daily/monthly cap, R2) or attempts
                # are exhausted: fall through to parse_envelope's raise.
                return response

            if (
                response.status_code in _RETRYABLE_5XX_STATUS_CODES
                and attempt < self.max_retries
                and can_retry_after_dispatch
            ):
                attempt += 1
                time.sleep(self._backoff_seconds(attempt))
                continue

            return response

    def parse_envelope(self, response: requests.Response) -> Any:
        """Parse the JSON body and raise on HTTP error status codes.

        Returns the parsed body as is (envelope dict, or for /health the
        bare, non-enveloped dict). Does not check `success` on 2xx
        responses, that quirk is specific to the semantic search endpoint
        and is handled in `client.py`.
        """
        try:
            body = response.json()
        except ValueError:
            body = None

        if response.status_code >= 400:
            self._raise_error(response, body)

        if body is None:
            raise CourtMeshError(
                "Response body was not valid JSON.",
                status_code=response.status_code,
            )

        if isinstance(body, dict):
            # Backfill requestId from the X-Request-Id header for every
            # success response that does not already carry one somewhere in
            # its body (some endpoints, e.g. GET /usage, set their own
            # meta["requestId"] directly - both can coexist).
            if "requestId" not in body:
                header_request_id = response.headers.get("X-Request-Id")
                if header_request_id:
                    body["requestId"] = header_request_id
            # Only the five idempotency-key-aware POST methods ever receive
            # this header, so this is a no-op on every other endpoint.
            replayed_header = response.headers.get("Idempotency-Replayed")
            if replayed_header and replayed_header.lower() == "true":
                body["replayed"] = True

        return body

    def _raise_error(self, response: requests.Response, body: Any, retry_after_override: Optional[float] = None) -> None:
        message: Optional[str] = None
        details = None
        code: Optional[str] = None
        if isinstance(body, dict):
            message = body.get("error") or body.get("message")
            details = body.get("details")
            code = body.get("code")
        # Falls back to the machine `code` when the body carries no
        # human message at all (PAGE_LIMIT_EXCEEDED/PAGINATION_DEPTH_EXCEEDED
        # send `{"success": False, "code", "limit", "tier"}` and nothing
        # else) before falling back to the bare HTTP reason phrase.
        if not message and code:
            message = _synthesize_message_from_code(code, body)
        if not message:
            message = response.reason or "HTTP {}".format(response.status_code)
        if details:
            if isinstance(details, list):
                message = "{} ({})".format(message, "; ".join(str(item) for item in details))
            else:
                message = "{} ({})".format(message, details)

        retry_after = retry_after_override
        reset_time = None
        if response.status_code == 429:
            if retry_after is None:
                retry_after = self._advertised_retry_after_seconds(response)
            if isinstance(body, dict):
                reset_time = body.get("resetTime")

        request_id = response.headers.get("X-Request-Id")

        raise build_error(
            response.status_code,
            message,
            response_body=body,
            retry_after=retry_after,
            reset_time=reset_time,
            code=code,
            request_id=(body.get("requestId") if isinstance(body, dict) else None) or request_id,
        )
