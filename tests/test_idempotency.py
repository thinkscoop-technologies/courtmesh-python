"""`Idempotency-Key` header behaviour: explicit keys, auto-generation when
`retry_posts` is in effect, `Idempotency-Replayed` -> `result.replayed`, and
the 409 `ConflictError` variants."""
import re

from courtmesh.errors import ConflictError
from helpers import FakeResponse

_UUID_V4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.IGNORECASE
)


def _analyze_body():
    return {"success": True, "data": {"message": "Analysis has been started", "status": "processing"}, "meta": {"responseTime": "10ms", "note": ""}}


def test_no_idempotency_key_sent_by_default(make_client):
    client, mock_request = make_client()
    mock_request.return_value = FakeResponse(202, _analyze_body())

    client.analyze_case("case1")

    headers = mock_request.call_args.kwargs["headers"]
    assert "Idempotency-Key" not in headers


def test_explicit_idempotency_key_sent_verbatim(make_client):
    client, mock_request = make_client()
    mock_request.return_value = FakeResponse(202, _analyze_body())

    client.analyze_case("case1", idempotency_key="my-key-123")

    headers = mock_request.call_args.kwargs["headers"]
    assert headers["Idempotency-Key"] == "my-key-123"


def test_auto_generates_uuid_v4_when_retry_posts_enabled_client_wide(make_client):
    client, mock_request = make_client(retry_posts=True)
    mock_request.return_value = FakeResponse(202, _analyze_body())

    client.analyze_case("case1")

    headers = mock_request.call_args.kwargs["headers"]
    assert _UUID_V4_RE.match(headers["Idempotency-Key"])


def test_auto_generates_uuid_v4_when_retry_posts_enabled_per_call(make_client):
    client, mock_request = make_client()
    mock_request.return_value = {
        "success": True,
        "data": {"requestId": "job1", "status": "completed"},
        "meta": {"liveFetch": False, "responseTime": "5ms"},
    }
    mock_request.return_value = FakeResponse(200, mock_request.return_value)

    client.request_timeline("case1", retry_posts=True)

    headers = mock_request.call_args.kwargs["headers"]
    assert _UUID_V4_RE.match(headers["Idempotency-Key"])


def test_screen_party_and_batch_and_analyze_consolidated_accept_idempotency_key(make_client, envelope):
    client, mock_request = make_client()

    mock_request.return_value = FakeResponse(
        200, envelope(data={"status": "success", "consolidatedAnalysis": {}}, meta={"responseTime": "1ms", "relatedCases": 0})
    )
    client.analyze_consolidated("case1", idempotency_key="k-consolidated")
    assert mock_request.call_args.kwargs["headers"]["Idempotency-Key"] == "k-consolidated"

    mock_request.return_value = FakeResponse(
        200,
        envelope(
            data={
                "query": {"name": "A", "entityType": "person", "purpose": "kyc"},
                "summary": {"matchCount": 0, "byBand": {"confirmed": 0, "probable": 0, "possible": 0, "unlikely": 0}, "highestBand": None, "verdict": "no_matches_found"},
                "matches": [],
                "relatedButUnverified": [],
                "coverage": {"exhaustive": True, "exhaustiveWithinFilters": True, "planClamped": False, "anyStrategyErrored": False, "strategiesRun": [], "someRecordsWithheld": False},
                "adjudicationsRun": 0,
                "notice": "n",
            },
            meta={"creditsCharged": 20, "adjudicated": False, "corpusAsOf": "2026-09-17"},
        ),
    )
    client.screen_party(name="A Very Uncommon Name", entityType="person", purpose="kyc", idempotency_key="k-screen")
    assert mock_request.call_args.kwargs["headers"]["Idempotency-Key"] == "k-screen"

    mock_request.return_value = FakeResponse(
        200,
        envelope(
            data={"results": [], "summary": {"items": 0, "matchesFound": 0, "noMatches": 0, "inconclusive": 0, "errors": 0}},
            meta={"creditsCharged": 0, "requestId": "req-1"},
        ),
    )
    client.screen_party_batch(items=[{"name": "A"}], purpose="kyc", idempotency_key="k-batch")
    assert mock_request.call_args.kwargs["headers"]["Idempotency-Key"] == "k-batch"


def test_idempotency_replayed_header_surfaces_as_result_replayed(make_client):
    client, mock_request = make_client()
    mock_request.return_value = FakeResponse(200, _analyze_body(), headers={"Idempotency-Replayed": "true"})

    result = client.analyze_case("case1", idempotency_key="dup-1")

    assert result.replayed is True


def test_replayed_is_none_when_header_absent(make_client):
    client, mock_request = make_client()
    mock_request.return_value = FakeResponse(200, _analyze_body())

    result = client.analyze_case("case1", idempotency_key="dup-1")

    assert result.replayed is None


def test_request_id_backfilled_from_header_when_body_has_none(make_client):
    client, mock_request = make_client()
    body = {"success": True, "status": "healthy", "version": "1.0.0", "timestamp": "2026-09-18T00:00:00.000Z"}
    mock_request.return_value = FakeResponse(200, body, headers={"X-Request-Id": "hdr-req-1"})

    result = client.health()

    assert result["requestId"] == "hdr-req-1"


def test_request_id_not_overwritten_when_body_already_has_one(make_client, envelope):
    client, mock_request = make_client()
    body = envelope(data={"userId": "u1", "name": None, "role": None})
    body["requestId"] = "body-req-1"
    mock_request.return_value = FakeResponse(200, body, headers={"X-Request-Id": "hdr-req-2"})

    result = client.me()

    assert result.request_id == "body-req-1"


def test_409_idempotency_key_reused_raises_conflict_error(make_client):
    client, mock_request = make_client()
    mock_request.return_value = FakeResponse(
        409,
        {
            "success": False,
            "error": "This Idempotency-Key was already used with a different request body.",
            "code": "IDEMPOTENCY_KEY_REUSED",
        },
    )

    try:
        client.analyze_case("case1", idempotency_key="dup-1")
        assert False, "expected ConflictError to be raised"
    except ConflictError as exc:
        assert exc.status_code == 409
        assert exc.code == "IDEMPOTENCY_KEY_REUSED"


def test_409_idempotency_in_progress_raises_conflict_error(make_client):
    client, mock_request = make_client()
    mock_request.return_value = FakeResponse(
        409,
        {
            "success": False,
            "error": "A request with this Idempotency-Key is still being processed.",
            "code": "IDEMPOTENCY_IN_PROGRESS",
        },
    )

    try:
        client.request_timeline("case1", idempotency_key="in-flight-1")
        assert False, "expected ConflictError to be raised"
    except ConflictError as exc:
        assert exc.code == "IDEMPOTENCY_IN_PROGRESS"
