"""Coverage for the 2026-09-18 API parity pass: cursor field, refresh,
allowRemoteFetch, the retry policy changes (R1-R4), the widened error
attributes (code, request_id, wallet/wallet_owner/contact_admin), and the
semantic search caseNumber/judgeName narrowing.
"""
import pytest

from courtmesh import API_REFUSAL_CODES
from courtmesh.errors import (
    InsufficientCreditsError,
    PayloadTooLargeError,
    RateLimitError,
    ValidationError,
    is_retryable_429_code,
)
from helpers import FakeResponse


# -- cursor / refresh / allowRemoteFetch request fields ----------------------


def test_search_cases_sends_cursor(make_client, envelope):
    client, mock_request = make_client()
    body = envelope(data=[], meta={}, pagination={"total": 0, "hasMore": False, "limit": 20, "nextCursor": None})
    mock_request.return_value = FakeResponse(200, body)

    client.search_cases(query="x", cursor="a.signed.cursor")

    sent_body = mock_request.call_args.kwargs["json"]
    assert sent_body["cursor"] == "a.signed.cursor"
    assert "searchAfter" not in sent_body


def test_request_timeline_sends_refresh_only_when_true(make_client, envelope):
    client, mock_request = make_client()
    body = envelope(data={"requestId": "job-1", "status": "pending"}, meta={"liveFetch": False, "responseTime": "1ms"})
    mock_request.return_value = FakeResponse(200, body)

    client.request_timeline("64f0abc0000000000000001")
    assert mock_request.call_args.kwargs["json"] == {"case_id": "64f0abc0000000000000001"}

    client.request_timeline("64f0abc0000000000000001", refresh=True)
    assert mock_request.call_args.kwargs["json"] == {"case_id": "64f0abc0000000000000001", "refresh": True}


def test_request_timeline_surfaces_live_fetch_and_supported_flag(make_client, envelope):
    client, mock_request = make_client()
    body = envelope(
        data={"requestId": "job-2", "status": "completed", "liveFetchSupported": False},
        meta={"liveFetch": True, "responseTime": "500ms"},
    )
    mock_request.return_value = FakeResponse(200, body)

    result = client.request_timeline("64f0abc0000000000000001", refresh=True)

    assert result.meta["liveFetch"] is True
    assert result.data["liveFetchSupported"] is False


def test_analyze_case_sends_allow_remote_fetch_only_when_true(make_client, envelope):
    client, mock_request = make_client()
    body = envelope(data={"message": "Analysis has been started", "status": "processing"}, meta={"responseTime": "1ms", "note": ""})
    mock_request.return_value = FakeResponse(202, body)

    client.analyze_case("1")
    assert mock_request.call_args.kwargs["json"] == {"force": False}

    client.analyze_case("1", allow_remote_fetch=True)
    assert mock_request.call_args.kwargs["json"] == {"force": False, "allowRemoteFetch": True}


# -- semantic search caseNumber / judgeName narrowing -------------------------


def test_semantic_search_rejects_non_digit_case_number(make_client):
    client, _ = make_client()
    with pytest.raises(ValueError):
        client.semantic_search(query="right to privacy", caseNumber="WP(C) 123/2024")


def test_semantic_search_accepts_digit_only_case_number(make_client, envelope):
    client, mock_request = make_client()
    body = envelope(data=[], meta={"query": "x", "responseTime": "1ms", "message": "No similar cases found."}, pagination={"page": 1, "limit": 20, "total": 0, "totalPages": 0, "hasMore": False})
    mock_request.return_value = FakeResponse(200, body)

    client.semantic_search(query="right to privacy", caseNumber="1234")

    sent_body = mock_request.call_args.kwargs["json"]
    assert sent_body["caseNumber"] == "1234"


def test_semantic_search_judge_aliases_collapse_to_single_judge_name(make_client, envelope):
    client, mock_request = make_client()
    body = envelope(data=[], meta={"query": "x", "responseTime": "1ms", "message": "No similar cases found."}, pagination={"page": 1, "limit": 20, "total": 0, "totalPages": 0, "hasMore": False})
    mock_request.return_value = FakeResponse(200, body)

    client.semantic_search(query="right to privacy", judges="Justice X")

    sent_body = mock_request.call_args.kwargs["json"]
    assert sent_body["judgeName"] == "Justice X"
    assert "judges" not in sent_body
    assert "judge" not in sent_body


# -- error attribute widening: code, request_id, wallet, contact_admin -------


def test_error_exposes_code_and_request_id(make_client):
    client, mock_request = make_client(max_retries=0)
    mock_request.return_value = FakeResponse(
        403,
        {"success": False, "error": "Semantic search is not available on this tier.", "code": "SEMANTIC_NOT_ALLOWED", "requestId": "req-abc"},
    )

    with pytest.raises(Exception) as excinfo:
        client.get_case("1")

    assert excinfo.value.code == "SEMANTIC_NOT_ALLOWED"
    assert excinfo.value.request_id == "req-abc"


def test_error_request_id_falls_back_to_header(make_client):
    client, mock_request = make_client(max_retries=0)
    mock_request.return_value = FakeResponse(
        500,
        {"success": False, "error": "boom"},
        headers={"X-Request-Id": "hdr-req-1"},
    )

    with pytest.raises(Exception) as excinfo:
        client.get_case("1")

    assert excinfo.value.request_id == "hdr-req-1"


def test_insufficient_credits_error_exposes_wallet_and_contact_admin(make_client):
    client, mock_request = make_client(max_retries=0)
    body = {
        "success": False,
        "error": "Insufficient API credits",
        "code": "INSUFFICIENT_API_CREDITS",
        "required": 100,
        "balance": 10,
        "shortfall": 90,
        "wallet": "api_credits",
        "walletOwner": "org",
        "contactAdmin": True,
    }
    mock_request.return_value = FakeResponse(402, body)

    with pytest.raises(InsufficientCreditsError) as excinfo:
        client.screen_party(name="Acme", entityType="company", purpose="kyc")

    assert excinfo.value.wallet == "api_credits"
    assert excinfo.value.wallet_owner == "org"
    assert excinfo.value.contact_admin is True
    assert excinfo.value.top_up_url is None


def test_payload_too_large_error(make_client):
    client, mock_request = make_client(max_retries=0)
    mock_request.return_value = FakeResponse(413, {"message": "request entity too large"})

    with pytest.raises(PayloadTooLargeError) as excinfo:
        client.search_cases(query="x")

    assert excinfo.value.status_code == 413


def test_validation_error_synthesizes_message_for_page_limit_exceeded(make_client):
    client, mock_request = make_client(max_retries=0)
    mock_request.return_value = FakeResponse(400, {"success": False, "code": "PAGE_LIMIT_EXCEEDED", "limit": 500, "tier": "free"})

    with pytest.raises(ValidationError) as excinfo:
        client.search_cases(query="x", limit=500)

    assert excinfo.value.code == "PAGE_LIMIT_EXCEEDED"
    assert excinfo.value.limit == 500
    assert excinfo.value.tier == "free"
    assert len(excinfo.value.message) > 0


def test_validation_error_for_cursor_invalid(make_client):
    client, mock_request = make_client(max_retries=0)
    mock_request.return_value = FakeResponse(
        400,
        {"success": False, "code": "CURSOR_INVALID", "message": "This pagination cursor is invalid or expired."},
    )

    with pytest.raises(ValidationError) as excinfo:
        client.search_cases(query="x", cursor="bogus")

    assert excinfo.value.code == "CURSOR_INVALID"


# -- API_REFUSAL_CODES mirroring ---------------------------------------------


def test_api_refusal_codes_covers_handler_local_and_auth_codes():
    for expected in (
        "CASE_RESTRICTED",
        "PDF_NOT_STORED",
        "CASE_NOT_FOUND",
        "PARTY_SCREEN_SEARCH_DEGRADED",
        "ENTITLEMENT_UNAVAILABLE",
        "CURSOR_INVALID",
        "PAGE_LIMIT_EXCEEDED",
        "PAGINATION_DEPTH_EXCEEDED",
        "TOO_MANY_KEYS_FROM_IP",
        "DISTINCT_CASES_LIMIT_REACHED",
        "PDF_LIMIT_REACHED",
        "CONCURRENT_ANALYSIS_LIMIT",
        "REMOTE_FETCH_NOT_ALLOWED",
        "EMAIL_NOT_VERIFIED",
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
        "INSUFFICIENT_API_CREDITS",
    ):
        assert expected in API_REFUSAL_CODES


# -- R1/R2/R3 retry policy ----------------------------------------------------


def test_r1_raises_immediately_without_sleeping_when_delay_exceeds_cap(make_client, sleep_calls):
    client, mock_request = make_client(max_retries=3)
    mock_request.return_value = FakeResponse(429, {"error": "Rate limit exceeded", "code": "RATE_LIMITED", "retryAfter": 86400})

    with pytest.raises(RateLimitError) as excinfo:
        client.get_case("1")

    assert excinfo.value.retry_after == 86400
    assert sleep_calls == []
    assert mock_request.call_count == 1


def test_r1_max_retry_after_seconds_is_configurable(make_client, sleep_calls):
    client, mock_request = make_client(max_retries=3, max_retry_after_seconds=5)
    mock_request.return_value = FakeResponse(429, {"error": "Rate limit exceeded", "code": "RATE_LIMITED", "retryAfter": 10})

    with pytest.raises(RateLimitError):
        client.get_case("1")

    assert sleep_calls == []
    assert mock_request.call_count == 1


def test_r2_never_retries_a_daily_cap_code(make_client, sleep_calls):
    client, mock_request = make_client(max_retries=3)
    mock_request.return_value = FakeResponse(429, {"error": "limit reached", "code": "DISTINCT_CASES_LIMIT_REACHED", "retryAfter": 5})

    with pytest.raises(RateLimitError):
        client.get_case("1")

    assert sleep_calls == []
    assert mock_request.call_count == 1


def test_r2_still_retries_concurrent_analysis_limit(make_client, envelope):
    client, mock_request = make_client(max_retries=1)
    success_body = envelope(data={"id": "1"}, meta={"responseTime": "1ms", "note": ""})
    mock_request.side_effect = [
        FakeResponse(429, {"error": "busy", "code": "CONCURRENT_ANALYSIS_LIMIT", "retryAfter": 0}),
        FakeResponse(200, success_body),
    ]

    result = client.get_case("1")

    assert result.data["id"] == "1"
    assert mock_request.call_count == 2


def test_r3_does_not_retry_post_on_502_by_default(make_client):
    client, mock_request = make_client(max_retries=2)
    mock_request.return_value = FakeResponse(502, {"success": False, "error": "bad gateway"})

    with pytest.raises(Exception):
        client.search_cases(query="x")

    assert mock_request.call_count == 1


def test_r3_retries_post_on_502_with_retry_posts_true(make_client, envelope):
    client, mock_request = make_client(max_retries=1, retry_posts=True)
    success_body = envelope(data=[], meta={}, pagination={"total": 0, "hasMore": False, "limit": 20})
    mock_request.side_effect = [
        FakeResponse(502, {"success": False, "error": "bad gateway"}),
        FakeResponse(200, success_body),
    ]

    result = client.search_cases(query="x")

    assert result.data == []
    assert mock_request.call_count == 2


def test_r3_per_call_retry_posts_override(make_client, envelope):
    client, mock_request = make_client(max_retries=1, retry_posts=False)
    success_body = envelope(data=[], meta={}, pagination={"total": 0, "hasMore": False, "limit": 20})
    mock_request.side_effect = [
        FakeResponse(502, {"success": False, "error": "bad gateway"}),
        FakeResponse(200, success_body),
    ]

    result = client.search_cases(query="x", retry_posts=True)

    assert result.data == []
    assert mock_request.call_count == 2


def test_is_retryable_429_code():
    assert is_retryable_429_code(None) is True
    assert is_retryable_429_code("RATE_LIMITED") is True
    assert is_retryable_429_code("CONCURRENT_ANALYSIS_LIMIT") is True
    assert is_retryable_429_code("DISTINCT_NAMES_LIMIT_REACHED") is False
    assert is_retryable_429_code("LIVE_FETCH_LIMIT_REACHED") is False
    assert is_retryable_429_code("PDF_LIMIT_REACHED") is False


# -- Timeouts ------------------------------------------------------------------


def test_per_endpoint_default_timeouts_are_applied(make_client, envelope):
    client, mock_request = make_client()
    mock_request.return_value = FakeResponse(
        200,
        envelope(data=[], meta={"query": "x", "responseTime": "1ms", "message": "No similar cases found."}, pagination={"page": 1, "limit": 20, "total": 0, "totalPages": 0, "hasMore": False}),
    )

    client.semantic_search(query="right to privacy")

    assert mock_request.call_args.kwargs["timeout"] == 630.0


def test_per_call_timeout_override(make_client, envelope):
    client, mock_request = make_client()
    mock_request.return_value = FakeResponse(
        200,
        envelope(data=[], meta={"query": "x", "responseTime": "1ms", "message": "No similar cases found."}, pagination={"page": 1, "limit": 20, "total": 0, "totalPages": 0, "hasMore": False}),
    )

    client.semantic_search(query="right to privacy", timeout=12.5)

    assert mock_request.call_args.kwargs["timeout"] == 12.5
