"""Client configuration: api_key resolution, auth header styles, custom
session support and the context manager."""
from unittest.mock import MagicMock

import pytest
import requests

from courtmesh import CourtMesh
from helpers import FakeResponse

TEST_API_KEY = "cm-" + "a" * 32 + "-abcd"


def test_requires_an_api_key(monkeypatch):
    monkeypatch.delenv("COURTMESH_API_KEY", raising=False)

    with pytest.raises(ValueError):
        CourtMesh(api_key=None)


def test_reads_api_key_from_environment_variable(monkeypatch):
    monkeypatch.setenv("COURTMESH_API_KEY", TEST_API_KEY)

    client = CourtMesh()
    try:
        assert client.api_key == TEST_API_KEY
    finally:
        client.close()


def test_explicit_api_key_wins_over_environment_variable(monkeypatch):
    monkeypatch.setenv("COURTMESH_API_KEY", "cm-" + "z" * 32 + "-9999")

    client = CourtMesh(api_key=TEST_API_KEY)
    try:
        assert client.api_key == TEST_API_KEY
    finally:
        client.close()


def test_rejects_unknown_auth_header_option():
    with pytest.raises(ValueError):
        CourtMesh(api_key=TEST_API_KEY, auth_header="bogus")


def test_default_base_url():
    client = CourtMesh(api_key=TEST_API_KEY)
    try:
        assert client.base_url == "https://research.courtmesh.ai/api/v1/prod"
    finally:
        client.close()


def test_custom_base_url_is_used_in_requests(make_client, envelope):
    client, mock_request = make_client(base_url="https://staging.example.com/api/v1/prod")
    mock_request.return_value = FakeResponse(200, envelope(data=["A"], meta={}))

    client.search_judges("a")

    method, url = mock_request.call_args.args
    assert url == "https://staging.example.com/api/v1/prod/judges/search"


def test_authorization_bearer_header_is_the_default(make_client, envelope):
    client, mock_request = make_client()
    mock_request.return_value = FakeResponse(200, envelope(data=[]))

    client.search_judges("x")

    headers = mock_request.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer {}".format(TEST_API_KEY)
    assert "X-API-Key" not in headers


def test_x_api_key_header_option(make_client, envelope):
    client, mock_request = make_client(auth_header="x-api-key")
    mock_request.return_value = FakeResponse(200, envelope(data=[]))

    client.search_judges("x")

    headers = mock_request.call_args.kwargs["headers"]
    assert headers["X-API-Key"] == TEST_API_KEY
    assert "Authorization" not in headers


def test_health_endpoint_sends_no_auth_header_at_all(make_client):
    client, mock_request = make_client()
    mock_request.return_value = FakeResponse(
        200, {"success": True, "status": "healthy", "version": "1.0.0", "timestamp": "2026-08-10T09:00:00.000Z"}
    )

    result = client.health()

    headers = mock_request.call_args.kwargs["headers"]
    assert "Authorization" not in headers
    assert "X-API-Key" not in headers
    assert result["status"] == "healthy"


def test_custom_session_is_used_for_requests():
    session = requests.Session()
    mock_request = MagicMock()
    session.request = mock_request
    mock_request.return_value = FakeResponse(
        200, {"success": True, "status": "healthy", "version": "1.0.0", "timestamp": "x"}
    )

    client = CourtMesh(api_key=TEST_API_KEY, session=session)
    assert client.session is session
    client.health()
    mock_request.assert_called_once()
    client.close()


def test_context_manager_closes_the_session():
    session = requests.Session()
    session.close = MagicMock()

    with CourtMesh(api_key=TEST_API_KEY, session=session):
        pass

    session.close.assert_called_once()
