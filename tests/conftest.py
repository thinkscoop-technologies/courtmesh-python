from unittest.mock import MagicMock

import pytest
import requests

from courtmesh import CourtMesh

TEST_API_KEY = "cm-" + "a" * 32 + "-abcd"


@pytest.fixture(autouse=True)
def _sleep_recorder(monkeypatch):
    """Replace `time.sleep` everywhere the transport uses it, so retry
    tests run instantly instead of waiting on real backoff delays. The
    recorded delays are exposed to tests that want to assert on them via
    the `sleep_calls` fixture below.
    """
    calls = []
    monkeypatch.setattr("courtmesh._http.time.sleep", calls.append)
    return calls


@pytest.fixture
def sleep_calls(_sleep_recorder):
    return _sleep_recorder


@pytest.fixture
def make_client():
    """Factory fixture: `client, mock_request = make_client()`.

    `mock_request` is the mocked `session.request` callable, set its
    `return_value` or `side_effect` per test. No real network call is ever
    made.
    """

    def _make(max_retries=3, **kwargs):
        session = requests.Session()
        client = CourtMesh(
            api_key=TEST_API_KEY,
            session=session,
            max_retries=max_retries,
            **kwargs,
        )
        mock_request = MagicMock()
        session.request = mock_request
        return client, mock_request

    return _make


@pytest.fixture
def envelope():
    """Build a `{"success": ..., "data": ..., "meta": ..., "pagination": ...}`
    envelope body, omitting keys that were not supplied.
    """

    def _envelope(data=None, meta=None, pagination=None, success=True, error=None, details=None):
        body = {"success": success}
        if data is not None:
            body["data"] = data
        if meta is not None:
            body["meta"] = meta
        if pagination is not None:
            body["pagination"] = pagination
        if error is not None:
            body["error"] = error
        if details is not None:
            body["details"] = details
        return body

    return _envelope
