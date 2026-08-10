"""Both pagination shapes, plus the `iter_search_cases` / `iter_semantic_search`
generators."""
from helpers import FakeResponse


# -- shapes -------------------------------------------------------------------


def test_search_cases_pagination_shape(make_client, envelope):
    client, mock_request = make_client()
    body = envelope(
        data=[{"_id": "1", "title": "A"}],
        meta={"query": "x", "filters": {}, "responseTime": "2ms"},
        pagination={"total": 1234, "hasMore": True, "page": 1, "limit": 20, "nextCursor": [12.34, "68f0..."]},
    )
    mock_request.return_value = FakeResponse(200, body)

    result = client.search_cases(query="x")

    assert result.pagination["total"] == 1234
    assert result.pagination["hasMore"] is True
    assert result.pagination["page"] == 1
    assert result.pagination["nextCursor"] == [12.34, "68f0..."]
    assert "totalPages" not in result.pagination


def test_search_cases_pagination_cursor_mode_omits_page(make_client, envelope):
    client, mock_request = make_client()
    body = envelope(
        data=[{"_id": "9"}],
        meta={},
        pagination={"total": 10, "hasMore": False, "limit": 20, "nextCursor": None},
    )
    mock_request.return_value = FakeResponse(200, body)

    result = client.search_cases(query="x", searchAfter='[12.34,"68f0..."]')

    assert "page" not in result.pagination
    assert result.pagination["nextCursor"] is None


def test_semantic_search_pagination_shape(make_client, envelope):
    client, mock_request = make_client()
    body = envelope(
        data=[{"id": "1", "similarity": 0.9}],
        meta={"query": "x", "appliedFilters": {}, "responseTime": "5ms", "searchType": "semantic"},
        pagination={"page": 1, "limit": 20, "total": 41, "totalPages": 3, "hasMore": True},
    )
    mock_request.return_value = FakeResponse(200, body)

    result = client.semantic_search(query="right to privacy")

    assert result.pagination["totalPages"] == 3
    assert result.pagination["page"] == 1
    assert "nextCursor" not in result.pagination


# -- iter_search_cases ----------------------------------------------------------


def test_iter_search_cases_walks_pages_until_has_more_false(make_client, envelope):
    client, mock_request = make_client()
    page1 = envelope(data=[{"_id": "1"}, {"_id": "2"}], meta={}, pagination={"total": 3, "hasMore": True, "page": 1, "limit": 2})
    page2 = envelope(data=[{"_id": "3"}], meta={}, pagination={"total": 3, "hasMore": False, "page": 2, "limit": 2})
    mock_request.side_effect = [FakeResponse(200, page1), FakeResponse(200, page2)]

    items = list(client.iter_search_cases("x", limit=2))

    assert [item["_id"] for item in items] == ["1", "2", "3"]
    assert mock_request.call_count == 2


def test_iter_search_cases_stops_on_empty_page(make_client, envelope):
    client, mock_request = make_client()
    page1 = envelope(data=[{"_id": "1"}], meta={}, pagination={"total": 1, "hasMore": True, "page": 1, "limit": 20})
    page2 = envelope(data=[], meta={}, pagination={"total": 1, "hasMore": True, "page": 2, "limit": 20})
    mock_request.side_effect = [FakeResponse(200, page1), FakeResponse(200, page2)]

    items = list(client.iter_search_cases("x"))

    assert len(items) == 1
    assert mock_request.call_count == 2


def test_iter_search_cases_max_pages_guards_against_runaway_has_more(make_client, envelope):
    client, mock_request = make_client()
    # A server bug that always reports hasMore=True would loop forever
    # without a cap, max_pages is the caller-facing guard for that.
    page = envelope(data=[{"_id": "1"}], meta={}, pagination={"total": 1_000_000, "hasMore": True, "page": 1, "limit": 1})
    mock_request.return_value = FakeResponse(200, page)

    items = list(client.iter_search_cases("x", limit=1, max_pages=3))

    assert len(items) == 3
    assert mock_request.call_count == 3


# -- iter_semantic_search ---------------------------------------------------------


def test_iter_semantic_search_walks_pages_until_has_more_false(make_client, envelope):
    client, mock_request = make_client()
    page1 = envelope(data=[{"id": "1"}], meta={}, pagination={"page": 1, "limit": 1, "total": 2, "totalPages": 2, "hasMore": True})
    page2 = envelope(data=[{"id": "2"}], meta={}, pagination={"page": 2, "limit": 1, "total": 2, "totalPages": 2, "hasMore": False})
    mock_request.side_effect = [FakeResponse(200, page1), FakeResponse(200, page2)]

    items = list(client.iter_semantic_search("x", limit=1))

    assert [item["id"] for item in items] == ["1", "2"]
    assert mock_request.call_count == 2


def test_iter_semantic_search_stops_on_empty_page(make_client, envelope):
    client, mock_request = make_client()
    page1 = envelope(data=[{"id": "1"}], meta={}, pagination={"page": 1, "limit": 20, "total": 1, "totalPages": 1, "hasMore": True})
    page2 = envelope(data=[], meta={}, pagination={"page": 2, "limit": 20, "total": 1, "totalPages": 1, "hasMore": True})
    mock_request.side_effect = [FakeResponse(200, page1), FakeResponse(200, page2)]

    items = list(client.iter_semantic_search("x"))

    assert len(items) == 1
    assert mock_request.call_count == 2
