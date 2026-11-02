"""Client side helpers for CNR lookup, monitoring and webhooks.

Nothing here makes a network call: `normalize_cnr` canonicalises a CNR the
way the server does, and `verify_webhook_signature` checks the
`CourtMesh-Signature` header of a webhook delivery.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from typing import Any, Dict, List, Optional, Sequence, Union

# A canonical CNR is 16 characters: a 6 character establishment code that
# begins with a 2 letter state code (almost always 4 letters then 2 digits,
# for example "DLHC01"), 6 serial digits and a 4 digit year.
_CNR_PATTERN = re.compile(r"^[A-Z]{2}[A-Z0-9]{4}[0-9]{10}$")
_CNR_SEPARATORS = re.compile(r"[\s\-/.:]+")


def normalize_cnr(value: Any) -> Optional[str]:
    """Normalise a CNR the way the server does.

    Trims, uppercases, removes spaces, hyphens, slashes, dots and colons, and
    drops a leading ``CNR``, ``CNR:`` or ``CNR NO`` label. Returns the
    canonical 16 character form, or ``None`` when the input cannot be a CNR.
    The server is the authority; this lets you validate input before
    spending a request.

    >>> normalize_cnr("CNR: DLHC-01-008421-2021")
    'DLHC010084212021'
    """
    if not isinstance(value, str):
        return None
    text = _CNR_SEPARATORS.sub("", value.strip().upper())
    if not _CNR_PATTERN.match(text):
        if text.startswith("CNRNO"):
            text = text[5:]
        elif text.startswith("CNR"):
            text = text[3:]
    return text if _CNR_PATTERN.match(text) else None


def assert_cnr(value: Any) -> str:
    """Like `normalize_cnr` but raises `ValueError` for input that cannot be a CNR."""
    cnr = normalize_cnr(value)
    if cnr is None:
        raise ValueError("Not a valid CNR: expected 16 characters, for example DLHC010084212021.")
    return cnr


def cnr_for_request(value: Any) -> str:
    """Canonical CNR when the input normalises, else the trimmed input, so
    the server can answer ``INVALID_CNR`` itself."""
    return normalize_cnr(value) or str(value).strip()


class WebhookSignatureError(Exception):
    """Raised by `verify_webhook_signature` for any reason a delivery must not be trusted.

    ``reason`` is one of ``missing_header``, ``malformed_header``,
    ``timestamp_out_of_tolerance``, ``signature_mismatch`` or ``invalid_body``.
    """

    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


def verify_webhook_signature(
    raw_body: Union[str, bytes],
    header: Optional[str],
    secret: Union[str, Sequence[str]],
    tolerance_seconds: int = 300,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Verify the ``CourtMesh-Signature`` header and return the parsed event.

    Pass the RAW request body exactly as received (``bytes`` or ``str``),
    never a re-serialised object, or the signature will not match.

    The header looks like ``t=1790000000,v1=<hex>``. During a secret
    rotation it carries two ``v1=`` values (one per secret); a match on any
    of them is accepted. ``secret`` may be a string or, to cover your side of
    a rotation, a list of strings.

    Args:
        tolerance_seconds: maximum allowed difference between now and the
            signed timestamp. Default 300.
        now: current time in unix seconds. For tests; defaults to the clock.

    Raises:
        WebhookSignatureError: the delivery must not be trusted.
    """
    if not header:
        raise WebhookSignatureError("Missing CourtMesh-Signature header.", "missing_header")

    timestamp: Optional[int] = None
    signatures: List[str] = []
    for part in header.split(","):
        key, sep, value = part.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if key == "t":
            if value.isdigit() and value.isascii():
                timestamp = int(value)
        elif key == "v1" and re.fullmatch(r"[0-9a-fA-F]+", value):
            signatures.append(value.lower())
    if timestamp is None or not signatures:
        raise WebhookSignatureError("Malformed CourtMesh-Signature header.", "malformed_header")

    current = time.time() if now is None else now
    if abs(current - timestamp) > tolerance_seconds:
        raise WebhookSignatureError("Webhook timestamp is outside the allowed tolerance.", "timestamp_out_of_tolerance")

    body_bytes = raw_body.encode("utf-8") if isinstance(raw_body, str) else bytes(raw_body)
    signed_payload = "{}.".format(timestamp).encode("utf-8") + body_bytes
    secrets = [secret] if isinstance(secret, str) else list(secret)

    matched = False
    for candidate in secrets:
        expected = hmac.new(candidate.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
        for provided in signatures:
            if hmac.compare_digest(provided, expected):
                matched = True
    if not matched:
        raise WebhookSignatureError("Webhook signature does not match.", "signature_mismatch")

    try:
        event = json.loads(body_bytes.decode("utf-8"))
    except ValueError as exc:
        raise WebhookSignatureError("Webhook body is not valid JSON.", "invalid_body") from exc
    return event  # type: ignore[no-any-return]
