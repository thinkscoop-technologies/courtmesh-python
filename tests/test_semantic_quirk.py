"""The semantic search transport quirk: the handler used to call
`res.writeHead(200, ...)` before doing any real work, so failures after that
point still arrived with HTTP 200 and `{"success": false, "error": "..."}`.
The server sends a proper non-200 status for this today, so these fixtures
exercise a defensive fallback that should never trigger against the live
server, not documented current behaviour. The SDK still checks `success`
explicitly and raises, as a belt-and-braces guard."""
import pytest

from courtmesh.errors import CourtMeshError
from helpers import FakeResponse


@pytest.mark.parametrize(
    "error_message",
    [
        "Failed to generate query embedding",
        "Vector search failed",
        "Failed to fetch results from search API",
    ],
)
def test_semantic_search_raises_on_success_false_with_http_200(make_client, error_message):
    client, mock_request = make_client()
    mock_request.return_value = FakeResponse(200, {"success": False, "error": error_message})

    with pytest.raises(CourtMeshError) as excinfo:
        client.semantic_search(query="privacy law")

    assert error_message in str(excinfo.value)
    # HTTP status really was 200, the SDK still had to raise.
    assert excinfo.value.status_code == 200


def test_semantic_search_fallback_mode_returns_raw_opensearch_hits(make_client, envelope):
    client, mock_request = make_client()
    body = envelope(
        data=[{"_id": "1", "title": "Fallback hit"}],
        meta={"query": "ab", "responseTime": "1ms", "fallbackMode": "opensearch"},
        pagination={"page": 1, "limit": 20, "total": 1, "totalPages": 1, "hasMore": False},
    )
    mock_request.return_value = FakeResponse(200, body)

    result = client.semantic_search(query="ab")

    assert result.meta["fallbackMode"] == "opensearch"
    assert result.data[0]["title"] == "Fallback hit"


def test_semantic_search_no_results_carries_message(make_client, envelope):
    client, mock_request = make_client()
    body = envelope(
        data=[],
        meta={"query": "very obscure query", "responseTime": "1ms", "message": "No similar cases found."},
        pagination={"page": 1, "limit": 20, "total": 0, "totalPages": 0, "hasMore": False},
    )
    mock_request.return_value = FakeResponse(200, body)

    result = client.semantic_search(query="very obscure query")

    assert result.data == []
    assert result.meta["message"] == "No similar cases found."
    assert "searchType" not in result.meta


def test_semantic_search_403_before_headers_sent_is_a_normal_error(make_client):
    client, mock_request = make_client()
    mock_request.return_value = FakeResponse(403, {"success": False, "error": "Billing is inactive for this account"})

    with pytest.raises(CourtMeshError) as excinfo:
        client.semantic_search(query="right to privacy")

    assert excinfo.value.status_code == 403
