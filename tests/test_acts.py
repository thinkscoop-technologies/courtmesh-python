"""Acts and sections endpoints (0.6.0): URLs, path encoding, query params,
parsed responses and error mapping."""
import pytest
from helpers import FakeResponse

from courtmesh import API_REFUSAL_CODES, BadGatewayError, NotFoundError, PermissionDeniedError, ValidationError

BASE = "https://research.courtmesh.ai/api/v1/prod"
SLUG = "indian-penal-code-1860"
ACT = {"slug": SLUG, "title": "The Indian Penal Code, 1860", "repealed": True, "repealNote": "Repealed by the Bharatiya Nyaya Sanhita, 2023"}
PAGE = {"page": 1, "limit": 20, "total": 1, "totalPages": 1, "hasMore": False}


def ok(data, **extra):
    body = {"success": True, "data": data}
    body.update(extra)
    return FakeResponse(200, body)


def call(mock_request, index=0):
    args, kwargs = mock_request.call_args_list[index]
    return args[0], args[1], kwargs


def test_search_acts_sends_params_and_parses_page(make_client):
    client, mock = make_client()
    mock.return_value = ok([ACT], meta={"creditsCharged": 1, "weakMatch": False}, pagination=PAGE)

    result = client.search_acts(
        "penal code", doc_class="act", jurisdiction="central", year_from=1800, year_to=1900, page=2, limit=5
    )

    method, url, kwargs = call(mock)
    assert (method, url) == ("GET", BASE + "/acts/search")
    assert kwargs["params"] == {
        "q": "penal code", "docClass": "act", "jurisdiction": "central",
        "yearFrom": 1800, "yearTo": 1900, "page": 2, "limit": 5,
    }
    assert result.data[0]["repealed"] is True
    assert result.meta["weakMatch"] is False
    assert result.pagination["total"] == 1


def test_search_acts_omits_unset_params(make_client):
    client, mock = make_client()
    mock.return_value = ok([], pagination=PAGE)
    client.search_acts("x y")
    assert call(mock)[2]["params"] == {"q": "x y"}


def test_search_acts_missing_scope_is_permission_error(make_client):
    client, mock = make_client(max_retries=0)
    mock.return_value = FakeResponse(403, {"success": False, "error": "Key lacks scope", "code": "INSUFFICIENT_SCOPE"})
    with pytest.raises(PermissionDeniedError):
        client.search_acts("ipc")


def test_resolve_act(make_client):
    client, mock = make_client()
    mock.return_value = ok({"query": "IPC", "matches": [{"act": ACT, "matchedBy": "short_form"}]})
    result = client.resolve_act("IPC")
    assert call(mock)[1] == BASE + "/acts/resolve"
    assert call(mock)[2]["params"] == {"q": "IPC"}
    assert result.data["matches"][0]["matchedBy"] == "short_form"


def test_get_act_encodes_slug(make_client):
    client, mock = make_client()
    mock.return_value = ok(dict(ACT, textSource="sections", sectionCount=511))
    result = client.get_act("a/b c?d")
    assert call(mock)[1] == BASE + "/acts/a%2Fb%20c%3Fd"
    assert result.data["sectionCount"] == 511


def test_get_act_404_is_act_not_found(make_client):
    client, mock = make_client(max_retries=0)
    mock.return_value = FakeResponse(404, {"success": False, "error": "No published act matches this slug.", "code": "ACT_NOT_FOUND"})
    with pytest.raises(NotFoundError) as excinfo:
        client.get_act("nope")
    assert excinfo.value.code == "ACT_NOT_FOUND"
    assert "ACT_NOT_FOUND" in API_REFUSAL_CODES


def test_get_act_history(make_client):
    client, mock = make_client()
    history = {
        "slug": SLUG,
        "succession": [{"note": "Repealed", "bySlug": "bharatiya-nyaya-sanhita-2023"}],
        "amendments": [], "stateAmendments": [], "editions": [], "instruments": [], "instrumentCounts": {},
    }
    mock.return_value = ok(history)
    result = client.get_act_history(SLUG)
    assert call(mock)[1] == BASE + "/acts/" + SLUG + "/history"
    assert result.data["succession"][0]["bySlug"] == "bharatiya-nyaya-sanhita-2023"


def test_get_act_history_404(make_client):
    client, mock = make_client(max_retries=0)
    mock.return_value = FakeResponse(404, {"success": False, "error": "x", "code": "ACT_NOT_FOUND"})
    with pytest.raises(NotFoundError) as excinfo:
        client.get_act_history("nope")
    assert excinfo.value.code == "ACT_NOT_FOUND"


def test_list_act_sections(make_client):
    client, mock = make_client()
    entry = {"actSlug": SLUG, "slug": "section-302", "partType": "section", "number": "302", "heading": "Punishment for murder"}
    mock.return_value = ok([entry], pagination=PAGE)
    result = client.list_act_sections(SLUG, page=3, limit=50)
    assert call(mock)[1] == BASE + "/acts/" + SLUG + "/sections"
    assert call(mock)[2]["params"] == {"page": 3, "limit": 50}
    assert result.data[0]["number"] == "302"
    assert result.pagination["hasMore"] is False


def test_get_act_section_encodes_both_segments(make_client):
    client, mock = make_client()
    mock.return_value = ok({"actSlug": "my act", "slug": "s", "actTitle": "T", "actRepealed": True, "text": "t", "blocks": [], "amendments": []})
    result = client.get_act_section("my act", "section 498a/x")
    assert call(mock)[1] == BASE + "/acts/my%20act/sections/section%20498a%2Fx"
    assert result.data["actRepealed"] is True


def test_get_act_section_404_is_section_not_found(make_client):
    client, mock = make_client(max_retries=0)
    mock.return_value = FakeResponse(404, {"success": False, "error": "No published provision matches this act and section.", "code": "SECTION_NOT_FOUND"})
    with pytest.raises(NotFoundError) as excinfo:
        client.get_act_section(SLUG, "section-9999")
    assert excinfo.value.code == "SECTION_NOT_FOUND"
    assert "SECTION_NOT_FOUND" in API_REFUSAL_CODES


def _citing(ids):
    return {
        "section": {"actSlug": SLUG, "slug": "section-302", "number": "302"},
        "listAvailable": True, "note": "Not an exhaustive list.", "total": 3, "totalIsLowerBound": False,
        "cases": [{"id": i, "title": "State v. Example"} for i in ids],
    }


def test_list_section_citing_cases(make_client):
    client, mock = make_client()
    mock.return_value = ok(
        _citing(["a"]),
        meta={"someRecordsWithheld": True},
        pagination={"limit": 1, "hasMore": True, "nextCursor": "c2"},
    )
    result = client.list_section_citing_cases(SLUG, "section-302", cursor="c1", limit=1)
    assert call(mock)[1] == BASE + "/acts/" + SLUG + "/sections/section-302/citing-cases"
    assert call(mock)[2]["params"] == {"cursor": "c1", "limit": 1}
    assert result.data["cases"][0]["id"] == "a"
    assert result.data["listAvailable"] is True
    assert result.meta["someRecordsWithheld"] is True
    assert result.next_cursor == "c2"


def test_iter_section_citing_cases_walks_cursors(make_client):
    client, mock = make_client()
    mock.side_effect = [
        ok(_citing(["a", "b"]), pagination={"limit": 2, "hasMore": True, "nextCursor": "c2"}),
        ok(_citing(["c"]), pagination={"limit": 2, "hasMore": False, "nextCursor": None}),
    ]
    ids = [c["id"] for c in client.iter_section_citing_cases(SLUG, "section-302", limit=2)]
    assert ids == ["a", "b", "c"]
    assert mock.call_count == 2
    assert call(mock, 1)[2]["params"] == {"cursor": "c2", "limit": 2}


def test_citing_cases_bad_cursor_and_unknown_section(make_client):
    client, mock = make_client(max_retries=0)
    mock.return_value = FakeResponse(400, {"success": False, "code": "CURSOR_INVALID", "message": "bad cursor"})
    with pytest.raises(ValidationError) as excinfo:
        client.list_section_citing_cases(SLUG, "section-302", cursor="zzz")
    assert excinfo.value.code == "CURSOR_INVALID"

    mock.return_value = FakeResponse(404, {"success": False, "error": "x", "code": "SECTION_NOT_FOUND"})
    with pytest.raises(NotFoundError) as excinfo:
        client.list_section_citing_cases(SLUG, "nope")
    assert excinfo.value.code == "SECTION_NOT_FOUND"


def test_citing_cases_502_upstream_unavailable(make_client):
    client, mock = make_client(max_retries=0)
    mock.return_value = FakeResponse(502, {"success": False, "error": "Citing judgments are temporarily unavailable.", "code": "UPSTREAM_UNAVAILABLE"})
    with pytest.raises(BadGatewayError) as excinfo:
        client.list_section_citing_cases(SLUG, "section-302")
    assert excinfo.value.code == "UPSTREAM_UNAVAILABLE"


def test_search_sections(make_client):
    client, mock = make_client()
    row = {"actSlug": SLUG, "slug": "section-498a", "number": "498A", "actRepealed": True, "snippet": "Husband or relative..."}
    mock.return_value = ok([row], pagination=PAGE)
    result = client.search_sections("cruelty", act=SLUG, number="498A", limit=10)
    assert call(mock)[1] == BASE + "/sections/search"
    assert call(mock)[2]["params"] == {"q": "cruelty", "act": SLUG, "number": "498A", "limit": 10}
    assert "Husband" in result.data[0]["snippet"]


def test_lookup_section_keeps_ambiguity(make_client):
    client, mock = make_client()
    row = {"actSlug": SLUG, "slug": "section-498a", "number": "498A", "actRepealed": True}
    mock.return_value = ok({"query": "s.498A", "matches": [{"section": row, "matchedBy": "number_only", "ambiguous": True}]})
    result = client.lookup_section("s.498A")
    assert call(mock)[1] == BASE + "/sections/lookup"
    assert call(mock)[2]["params"] == {"q": "s.498A"}
    assert result.data["matches"][0]["ambiguous"] is True
