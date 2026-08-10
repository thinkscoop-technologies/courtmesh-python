"""Error class mapping, both at the `build_error` unit level and via real
client calls that receive each status code."""
import pytest

from courtmesh.errors import (
    AuthenticationError,
    BadGatewayError,
    CourtMeshError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    RequestTimeoutError,
    ServerError,
    ServiceUnavailableError,
    ValidationError,
    build_error,
)
from helpers import FakeResponse

STATUS_TO_CLASS = [
    (400, ValidationError),
    (401, AuthenticationError),
    (403, PermissionDeniedError),
    (404, NotFoundError),
    (408, RequestTimeoutError),
    (429, RateLimitError),
    (500, ServerError),
    (502, BadGatewayError),
    (503, ServiceUnavailableError),
]


@pytest.mark.parametrize("status_code,expected_cls", STATUS_TO_CLASS)
def test_build_error_maps_status_code(status_code, expected_cls):
    exc = build_error(status_code, "boom", response_body={"error": "boom"})

    assert isinstance(exc, expected_cls)
    assert isinstance(exc, CourtMeshError)
    assert exc.status_code == status_code
    assert exc.message == "boom"
    assert exc.response_body == {"error": "boom"}
    assert str(exc) == "[{}] boom".format(status_code)


def test_build_error_unmapped_status_falls_back_to_base_class():
    exc = build_error(504, "gateway timeout")

    assert type(exc) is CourtMeshError


def test_build_error_rate_limit_carries_retry_after_and_reset_time():
    exc = build_error(429, "Too many requests", retry_after=12.0, reset_time="2026-08-10T09:15:00.000Z")

    assert isinstance(exc, RateLimitError)
    assert exc.retry_after == 12.0
    assert exc.reset_time == "2026-08-10T09:15:00.000Z"


@pytest.mark.parametrize("status_code,expected_cls", STATUS_TO_CLASS)
def test_client_raises_mapped_error_for_enveloped_body(make_client, status_code, expected_cls):
    client, mock_request = make_client(max_retries=0)
    mock_request.return_value = FakeResponse(status_code, {"success": False, "error": "handler error message"})

    with pytest.raises(expected_cls) as excinfo:
        client.get_case("1")

    assert excinfo.value.status_code == status_code
    assert "handler error message" in str(excinfo.value)


def test_client_raises_authentication_error_for_bare_auth_body(make_client):
    client, mock_request = make_client()
    mock_request.return_value = FakeResponse(401, {"error": "Invalid API key"})

    with pytest.raises(AuthenticationError) as excinfo:
        client.get_case("1")

    assert "Invalid API key" in str(excinfo.value)


def test_client_raises_validation_error_with_details_appended(make_client):
    client, mock_request = make_client()
    body = {
        "success": False,
        "error": "Validation failed. Please check your request and try again.",
        "details": ["query: Search query cannot be empty. Please provide a search term."],
    }
    mock_request.return_value = FakeResponse(400, body)

    with pytest.raises(ValidationError) as excinfo:
        client.search_cases(query="")

    assert "Search query cannot be empty" in str(excinfo.value)
    assert excinfo.value.response_body == body


def test_permission_denied_error_carries_plan_limit_body(make_client):
    client, mock_request = make_client()
    body = {"success": False, "error": "Daily call limit reached", "callsToday": 500, "maxAllowed": 500}
    mock_request.return_value = FakeResponse(403, body)

    with pytest.raises(PermissionDeniedError) as excinfo:
        client.get_case("1")

    assert excinfo.value.response_body["callsToday"] == 500
    assert excinfo.value.response_body["maxAllowed"] == 500


def test_request_timeout_error(make_client):
    client, mock_request = make_client()
    mock_request.return_value = FakeResponse(408, {"success": False, "error": "Request timeout - OpenSearch query took too long"})

    with pytest.raises(RequestTimeoutError):
        client.search_cases(query="x")
