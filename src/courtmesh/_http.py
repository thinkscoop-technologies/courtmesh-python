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

from .errors import CourtMeshError, build_error

DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 3

# Status codes the spec says to retry: 429 (rate limited) plus the three
# upstream connectivity failures 502, 503, 504.
_RETRYABLE_STATUS_CODES = frozenset({429, 502, 503, 504})
_MAX_BACKOFF_SECONDS = 30.0


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
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_retries = max_retries
        self.auth_header = auth_header

    def close(self) -> None:
        self.session.close()

    def _auth_headers(self) -> Dict[str, str]:
        if self.auth_header == "x-api-key":
            return {"X-API-Key": self.api_key}
        return {"Authorization": "Bearer {}".format(self.api_key)}

    def _retry_after_seconds(self, response: requests.Response) -> Optional[float]:
        """`Retry-After` header first, then the JSON body's `retryAfter`."""
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
    ) -> requests.Response:
        url = "{}{}".format(self.base_url, path)
        headers = {"Accept": "application/json"}
        if require_auth:
            headers.update(self._auth_headers())

        attempt = 0
        while True:
            try:
                response = self.session.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers=headers,
                    timeout=self.timeout,
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                attempt += 1
                if attempt > self.max_retries:
                    raise CourtMeshError(
                        "Connection error after {} attempt(s): {}".format(attempt, exc)
                    ) from exc
                time.sleep(self._backoff_seconds(attempt))
                continue

            if response.status_code in _RETRYABLE_STATUS_CODES and attempt < self.max_retries:
                attempt += 1
                if response.status_code == 429:
                    delay = self._retry_after_seconds(response)
                    if delay is None:
                        delay = self._backoff_seconds(attempt)
                else:
                    delay = self._backoff_seconds(attempt)
                time.sleep(delay)
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
        return body

    def _raise_error(self, response: requests.Response, body: Any) -> None:
        message: Optional[str] = None
        details = None
        if isinstance(body, dict):
            message = body.get("error") or body.get("message")
            details = body.get("details")
        if not message:
            message = response.reason or "HTTP {}".format(response.status_code)
        if details:
            if isinstance(details, list):
                message = "{} ({})".format(message, "; ".join(str(item) for item in details))
            else:
                message = "{} ({})".format(message, details)

        retry_after = None
        reset_time = None
        if response.status_code == 429:
            retry_after = self._retry_after_seconds(response)
            if isinstance(body, dict):
                reset_time = body.get("resetTime")

        raise build_error(
            response.status_code,
            message,
            response_body=body,
            retry_after=retry_after,
            reset_time=reset_time,
        )
