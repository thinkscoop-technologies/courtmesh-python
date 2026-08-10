"""Retry with exponential backoff plus jitter: 429 honouring `Retry-After`
first then the JSON `retryAfter`, 502/503/504 and connection errors."""
import requests

from courtmesh.errors import CourtMeshError, RateLimitError
from helpers import FakeResponse


def test_429_retries_and_prefers_retry_after_header_over_json_body(make_client, envelope, sleep_calls):
    client, mock_request = make_client(max_retries=3)
    success_body = envelope(
        data=[{"title": "Case A"}],
        meta={"query": "x", "filters": {}, "responseTime": "1ms"},
        pagination={"total": 1, "hasMore": False, "page": 1, "limit": 20, "nextCursor": None},
    )
    mock_request.side_effect = [
        FakeResponse(
            429,
            {
                "error": "Rate limit exceeded",
                "message": "Too many requests. Maximum 10 requests per minute allowed.",
                "retryAfter": 37,
                "resetTime": "2026-08-10T09:15:00.000Z",
            },
            headers={"Retry-After": "5"},
        ),
        FakeResponse(200, success_body),
    ]

    result = client.search_cases(query="privacy")

    assert result.data[0]["title"] == "Case A"
    assert mock_request.call_count == 2
    assert sleep_calls == [5.0]


def test_429_falls_back_to_json_retry_after_when_no_header(make_client, envelope, sleep_calls):
    client, mock_request = make_client(max_retries=3)
    success_body = envelope(data=[], meta={}, pagination={"total": 0, "hasMore": False, "limit": 20})
    mock_request.side_effect = [
        FakeResponse(429, {"error": "Rate limit exceeded", "retryAfter": 12}, headers={}),
        FakeResponse(200, success_body),
    ]

    client.search_cases(query="privacy")

    assert sleep_calls == [12.0]


def test_429_exhausts_retries_and_raises_rate_limit_error(make_client):
    client, mock_request = make_client(max_retries=2)
    body = {
        "error": "Rate limit exceeded",
        "message": "Too many requests. Maximum 10 requests per minute allowed.",
        "retryAfter": 3,
        "resetTime": "2026-08-10T09:15:00.000Z",
    }
    mock_request.return_value = FakeResponse(429, body, headers={})

    try:
        client.search_cases(query="privacy")
        assert False, "expected RateLimitError to be raised"
    except RateLimitError as exc:
        assert exc.status_code == 429
        assert exc.retry_after == 3.0
        assert exc.reset_time == "2026-08-10T09:15:00.000Z"

    # initial attempt + 2 retries = 3 calls
    assert mock_request.call_count == 3


def test_502_503_504_are_retried_then_succeed(make_client, envelope):
    client, mock_request = make_client(max_retries=3)
    success_body = envelope(data={"id": "1"}, meta={"responseTime": "1ms", "note": ""})
    mock_request.side_effect = [
        FakeResponse(502, {"error": "Failed to connect"}),
        FakeResponse(503, {"error": "Unable to verify account standing. Please retry."}),
        FakeResponse(504, {"error": "Gateway timeout"}),
        FakeResponse(200, success_body),
    ]

    result = client.get_case("abc123")

    assert result.data["id"] == "1"
    assert mock_request.call_count == 4


def test_connection_error_is_retried_then_succeeds(make_client, envelope):
    client, mock_request = make_client(max_retries=2)
    success_body = envelope(data={"success": True, "status": "healthy", "version": "1.0.0", "timestamp": "x"})
    mock_request.side_effect = [requests.ConnectionError("boom"), FakeResponse(200, success_body)]

    result = client.get_case("abc123")

    assert mock_request.call_count == 2
    assert result.data["status"] == "healthy"


def test_connection_error_exhausts_retries_and_raises(make_client):
    client, mock_request = make_client(max_retries=1)
    mock_request.side_effect = requests.ConnectionError("boom")

    try:
        client.get_case("abc123")
        assert False, "expected CourtMeshError to be raised"
    except CourtMeshError as exc:
        assert exc.status_code is None
        assert "boom" in str(exc)

    assert mock_request.call_count == 2  # initial attempt + 1 retry
