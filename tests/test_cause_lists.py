"""Cause list calls: listings, matter listings, court list and the watched CNR check."""
import pytest
from helpers import FakeResponse

from courtmesh import (
    COURT_KEY_PATTERN,
    BadGatewayError,
    NotFoundError,
    PermissionDeniedError,
    ServiceUnavailableError,
    ValidationError,
)

BASE = "https://research.courtmesh.ai/api/v1/prod"
MATTER = "66f1a2b3c4d5e6f7a8b9c0d1"
COURT_KEY = "DC:99:1:9900001:1:1"
CNR = "ZZAB010000012024"


def listing(listing_id):
    return {
        "id": listing_id,
        "matterId": MATTER,
        "matterTitle": "Alpha Finance Ltd v. Beta Traders",
        "date": "2026-11-05",
        "courtKey": COURT_KEY,
        "court": {"kind": "DC", "name": "District Court, Example City", "courtNo": "1", "judges": ["Sh. A. Example"], "designation": None},
        "item": "1",
        "section": "Urgent Cases",
        "purpose": "REPLY",
        "listType": "civil",
        "stage": None,
        "caseText": "CMA/1/2024",
        "matchedBy": "cnr",
        "relation": None,
        "fetchedAt": "2026-11-04T15:30:12.000Z",
        "firstSeenAt": "2026-11-04T15:31:02.000Z",
    }


def page(ids, number, has_more):
    return FakeResponse(
        200,
        {
            "success": True,
            "data": [listing(i) for i in ids],
            "meta": {"creditsCharged": 1, "metered": True},
            "pagination": {"page": number, "limit": 2, "total": 3, "totalPages": 2, "hasMore": has_more},
        },
    )


def _distinct(n):
    return ["ZZAB01{:06d}2024".format(i + 1) for i in range(n)]


def call(mock_request, index=0):
    args, kwargs = mock_request.call_args_list[index]
    return args[0], args[1], kwargs


OUTAGE = {
    "success": False,
    "code": "UPSTREAM_UNAVAILABLE",
    "message": "Cause lists are temporarily unavailable. Please retry shortly. You have not been charged.",
}

EMPTY_CHECK = {
    "success": True,
    "data": {"results": [], "summary": {"listed": 0, "noEntryFound": 0, "listNotRead": 0, "cannotCheck": 0, "notWatched": 0}},
}


# -- list_cause_listings / iter_cause_listings -----------------------------


def test_list_cause_listings_sends_range_page_and_limit(make_client):
    client, mock = make_client()
    mock.return_value = page(["a"], 2, False)
    res = client.list_cause_listings(from_date="2026-11-05", to_date="2026-11-12", page=2, limit=20)
    method, url, kwargs = call(mock)
    assert (method, url) == ("GET", BASE + "/cause-lists/listings")
    assert kwargs["params"] == {"from": "2026-11-05", "to": "2026-11-12", "page": 2, "limit": 20}
    assert res.pagination["hasMore"] is False
    assert res.has_more is False
    assert res.data[0]["matchedBy"] == "cnr"
    assert res.meta["creditsCharged"] == 1


def test_list_cause_listings_without_options_sends_no_params(make_client):
    client, mock = make_client()
    mock.return_value = page([], 1, False)
    client.list_cause_listings()
    assert call(mock)[2]["params"] is None


@pytest.mark.parametrize(
    "kwargs,detail",
    [
        ({"from_date": "2026-11-05"}, "Send both from and to, or neither."),
        ({"from_date": "2026-11-05", "to_date": "2026-11-01"}, "to cannot be before from."),
        ({"from_date": "2026-11-01", "to_date": "2026-12-05"}, "from and to can be at most 31 days apart."),
        ({"from_date": "2026-02-30", "to_date": "2026-03-01"}, "from: from must be a real date written YYYY-MM-DD."),
        ({"from_date": "2026-11-0٥", "to_date": "2026-11-06"}, "from: from must be a real date written YYYY-MM-DD."),
    ],
)
def test_list_cause_listings_refuses_bad_ranges_before_any_request(make_client, kwargs, detail):
    client, mock = make_client()
    with pytest.raises(ValidationError) as info:
        client.list_cause_listings(**kwargs)
    assert detail in str(info.value)
    assert info.value.code == "VALIDATION_ERROR"
    assert mock.call_count == 0


def test_list_cause_listings_allows_exactly_31_days(make_client):
    client, mock = make_client()
    mock.return_value = page([], 1, False)
    client.list_cause_listings(from_date="2026-11-01", to_date="2026-12-02")
    assert mock.call_count == 1


def test_iter_cause_listings_walks_pages_from_1_until_has_more_is_false(make_client):
    client, mock = make_client()
    mock.side_effect = [page(["a", "b"], 1, True), page(["c"], 2, False)]
    ids = [item["id"] for item in client.iter_cause_listings(limit=2)]
    assert ids == ["a", "b", "c"]
    assert [call(mock, i)[2]["params"]["page"] for i in range(2)] == [1, 2]


def test_iter_cause_listings_stops_on_an_empty_page(make_client):
    client, mock = make_client()
    mock.side_effect = [page([], 1, True)]
    assert list(client.iter_cause_listings()) == []
    assert mock.call_count == 1


def test_iter_cause_listings_honours_max_pages(make_client):
    client, mock = make_client()
    mock.side_effect = [page(["a"], 1, True), page(["b"], 2, True)]
    assert [i["id"] for i in client.iter_cause_listings(max_pages=1)] == ["a"]
    assert mock.call_count == 1


# -- list_matter_cause_listings ----------------------------------------------


def test_list_matter_cause_listings_calls_the_matter_path(make_client):
    client, mock = make_client()
    mock.return_value = FakeResponse(
        200,
        {
            "success": True,
            "data": {"matter": {"id": MATTER, "title": "T", "courtKey": COURT_KEY}, "listings": [listing("a")]},
            "meta": {"creditsCharged": 1, "metered": True},
        },
    )
    res = client.list_matter_cause_listings(MATTER, from_date="2026-11-05", to_date="2026-11-06")
    method, url, kwargs = call(mock)
    assert (method, url) == ("GET", BASE + "/matters/" + MATTER + "/cause-listings")
    assert kwargs["params"] == {"from": "2026-11-05", "to": "2026-11-06"}
    assert res.data["matter"]["courtKey"] == COURT_KEY
    assert len(res.data["listings"]) == 1


@pytest.mark.parametrize(
    "bad",
    ["", "abc", "66f1a2b3c4d5e6f7a8b9c0d", "66f1a2b3c4d5e6f7a8b9c0d1x", "66f1a2b3c4d5e6f7a8b9c0g1", "../cases", "66f1a2b3c4d5e6f7a8b9c0d1\n", None, 12],
)
def test_list_matter_cause_listings_refuses_bad_matter_ids(make_client, bad):
    client, mock = make_client()
    with pytest.raises(ValidationError) as info:
        client.list_matter_cause_listings(bad)
    assert "matterId: matterId must be a 24 character hexadecimal id." in str(info.value)
    assert mock.call_count == 0


def test_list_matter_cause_listings_unknown_matter_is_not_found(make_client):
    client, mock = make_client()
    mock.return_value = FakeResponse(404, {"success": False, "code": "MATTER_NOT_FOUND", "message": "Matter not found."})
    with pytest.raises(NotFoundError) as info:
        client.list_matter_cause_listings(MATTER)
    assert info.value.code == "MATTER_NOT_FOUND"


# -- get_court_cause_list ----------------------------------------------------


def test_get_court_cause_list_returns_a_free_unavailable_list_as_data(make_client):
    client, mock = make_client()
    mock.return_value = FakeResponse(
        200,
        {
            "success": True,
            "data": {"courtKey": COURT_KEY, "date": "2026-11-05", "status": "unavailable", "complete": False, "fetchedAt": None, "court": None, "rows": []},
            "meta": {"creditsCharged": 0, "metered": True},
        },
    )
    res = client.get_court_cause_list(COURT_KEY, "2026-11-05")
    method, url, kwargs = call(mock)
    assert (method, url) == ("GET", BASE + "/cause-lists/court")
    assert kwargs["params"] == {"courtKey": COURT_KEY, "date": "2026-11-05"}
    assert res.data["status"] == "unavailable"
    assert res.meta["creditsCharged"] == 0


@pytest.mark.parametrize("key", ["SC", "HC:99:2", "DC:99:1:9900001:1:1", "DC:1:2:3:4:5"])
def test_court_key_pattern_accepts(key):
    assert COURT_KEY_PATTERN.fullmatch(key)


@pytest.mark.parametrize(
    "key",
    ["", "sc", "SC:1", "HC:1", "HC:1234:2", "DC:99:1:9900001:1", "DC:99:1:9900001:1:1:9", "DC:a:1:2:3:4", "HC:99:2\nSC", "SC ", "HC:١:2", None],
)
def test_get_court_cause_list_refuses_bad_court_keys_before_any_request(make_client, key):
    client, mock = make_client()
    with pytest.raises(ValidationError) as info:
        client.get_court_cause_list(key, "2026-11-05")
    assert "courtKey: courtKey is not a valid court key." in str(info.value)
    assert mock.call_count == 0


def test_get_court_cause_list_refuses_a_bad_date(make_client):
    client, mock = make_client()
    with pytest.raises(ValidationError) as info:
        client.get_court_cause_list("SC", "05-11-2026")
    assert "date: date must be a real date written YYYY-MM-DD." in str(info.value)
    assert mock.call_count == 0


def test_cause_lists_not_enabled_is_permission_denied(make_client):
    client, mock = make_client()
    mock.return_value = FakeResponse(
        403, {"success": False, "code": "CAUSE_LISTS_NOT_ENABLED", "message": "This account does not have access to cause lists."}
    )
    with pytest.raises(PermissionDeniedError) as info:
        client.get_court_cause_list("SC", "2026-11-05")
    assert info.value.code == "CAUSE_LISTS_NOT_ENABLED"


# -- 502 UPSTREAM_UNAVAILABLE -------------------------------------------------


def test_get_is_retried_on_502_then_raised_as_bad_gateway(make_client):
    client, mock = make_client(max_retries=1)
    mock.side_effect = [FakeResponse(502, OUTAGE), FakeResponse(502, OUTAGE)]
    with pytest.raises(BadGatewayError) as info:
        client.list_cause_listings()
    assert info.value.code == "UPSTREAM_UNAVAILABLE"
    assert mock.call_count == 2


def test_get_recovers_when_the_retry_succeeds(make_client):
    client, mock = make_client(max_retries=1)
    mock.side_effect = [FakeResponse(502, OUTAGE), page(["a"], 1, False)]
    assert len(client.list_cause_listings().data) == 1
    assert mock.call_count == 2


def test_check_post_is_not_retried_by_default(make_client):
    client, mock = make_client(max_retries=2)
    mock.side_effect = [FakeResponse(502, OUTAGE), FakeResponse(502, OUTAGE)]
    with pytest.raises(BadGatewayError):
        client.check_cause_lists([CNR])
    assert mock.call_count == 1


def test_check_post_is_retried_with_the_same_idempotency_key_when_retry_posts_is_on(make_client):
    client, mock = make_client(max_retries=2, retry_posts=True)
    mock.side_effect = [FakeResponse(502, OUTAGE), FakeResponse(200, EMPTY_CHECK)]
    client.check_cause_lists([CNR])
    assert mock.call_count == 2
    first = call(mock, 0)[2]["headers"]["Idempotency-Key"]
    assert first
    assert call(mock, 1)[2]["headers"]["Idempotency-Key"] == first


# -- check_cause_lists --------------------------------------------------------

CHECK_BODY = {
    "success": True,
    "data": {
        "results": [
            {
                "cnr": CNR,
                "status": "listed",
                "reason": None,
                "courtKey": COURT_KEY,
                "dates": [{"date": "2026-11-05", "status": "ok", "complete": True, "fetchedAt": "2026-11-04T15:30:12.000Z"}],
                "listings": [
                    {"date": "2026-11-05", "courtKey": COURT_KEY, "court": None, "item": "1", "section": "Urgent Cases", "purpose": "REPLY", "listType": "civil", "stage": None, "caseText": "CMA/1/2024", "matchedBy": "cnr", "relation": None, "fetchedAt": "2026-11-04T15:30:12.000Z"}
                ],
            },
            {"cnr": "ZZAB010000022024", "status": "no_entry_found", "reason": None, "courtKey": "HC:99:1", "dates": [{"date": "2026-11-05", "status": "partial", "complete": False, "fetchedAt": None}], "listings": []},
            {"cnr": "ZZAB010000032024", "status": "not_watched", "reason": None, "courtKey": None, "dates": [], "listings": []},
        ],
        "summary": {"listed": 1, "noEntryFound": 1, "listNotRead": 0, "cannotCheck": 0, "notWatched": 1},
        "from": "2026-11-05",
        "to": "2026-11-06",
    },
    "meta": {"creditsCharged": 2, "metered": True},
}


def test_check_posts_normalised_cnrs_and_returns_statuses_unchanged(make_client):
    client, mock = make_client()
    mock.return_value = FakeResponse(200, CHECK_BODY)
    res = client.check_cause_lists(["cnr: zzab-01-000001-2024", "ZZAB010000022024"], from_date="2026-11-05", to_date="2026-11-06")
    method, url, kwargs = call(mock)
    assert (method, url) == ("POST", BASE + "/cause-lists/check")
    assert kwargs["json"] == {"cnrs": [CNR, "ZZAB010000022024"], "from": "2026-11-05", "to": "2026-11-06"}
    assert [r["status"] for r in res.data["results"]] == ["listed", "no_entry_found", "not_watched"]
    assert res.data["summary"]["noEntryFound"] == 1
    assert (res.data["from"], res.data["to"]) == ("2026-11-05", "2026-11-06")
    assert res.meta["creditsCharged"] == 2


def test_check_omits_dates_when_not_given(make_client):
    client, mock = make_client()
    mock.return_value = FakeResponse(200, CHECK_BODY)
    client.check_cause_lists([CNR])
    assert call(mock)[2]["json"] == {"cnrs": [CNR]}


def test_check_sends_an_idempotency_key_only_when_asked_or_retry_posts_is_on(make_client):
    client, mock = make_client()
    mock.return_value = FakeResponse(200, CHECK_BODY)
    client.check_cause_lists([CNR])
    assert "Idempotency-Key" not in (call(mock)[2].get("headers") or {})
    client.check_cause_lists([CNR], idempotency_key="check-1")
    assert call(mock, 1)[2]["headers"]["Idempotency-Key"] == "check-1"


@pytest.mark.parametrize(
    "kwargs,detail",
    [
        ({"cnrs": []}, "cnrs: send between 1 and 100 CNRs."),
        ({"cnrs": [CNR] * 101}, "cnrs: send between 1 and 100 CNRs."),
        ({"cnrs": CNR}, "cnrs: send between 1 and 100 CNRs."),
        ({"cnrs": [CNR], "to_date": "2026-11-06"}, "Send both from and to, or neither."),
        ({"cnrs": [CNR], "from_date": "2026-11-01", "to_date": "2026-11-09"}, "from and to can be at most 7 days apart."),
    ],
)
def test_check_refuses_bad_bodies_before_any_request(make_client, kwargs, detail):
    client, mock = make_client()
    with pytest.raises(ValidationError) as info:
        client.check_cause_lists(**kwargs)
    assert detail in str(info.value)
    assert mock.call_count == 0


LIMIT = "A call can cover at most 300 CNR and date pairs. This one asks for 38 CNRs over 8 dates; send fewer CNRs or a shorter date range."


@pytest.mark.parametrize(
    "count,from_date,to_date",
    [(38, "2026-11-01", "2026-11-08"), (76, "2026-11-01", "2026-11-04")],
)
def test_check_refuses_more_than_300_cnrs_times_dates_before_any_request(make_client, count, from_date, to_date):
    client, mock = make_client()
    with pytest.raises(ValidationError) as info:
        client.check_cause_lists(_distinct(count), from_date=from_date, to_date=to_date)
    assert "at most 300 CNR and date pairs" in str(info.value)
    assert mock.call_count == 0


def test_check_counts_the_default_range_as_2_dates_and_the_limit_message(make_client):
    client, mock = make_client()
    with pytest.raises(ValidationError) as info:
        client.check_cause_lists(_distinct(38), from_date="2026-11-01", to_date="2026-11-08")
    assert LIMIT in str(info.value)
    mock.return_value = FakeResponse(200, CHECK_BODY)
    client.check_cause_lists(_distinct(100))  # 100 x 2 = 200
    client.check_cause_lists(_distinct(100), from_date="2026-11-01", to_date="2026-11-03")  # 100 x 3 = 300
    client.check_cause_lists(_distinct(37), from_date="2026-11-01", to_date="2026-11-08")  # 37 x 8 = 296
    assert mock.call_count == 3


def test_check_removes_repeats_before_counting(make_client):
    # 38 entries with one repeat (in another spelling) over 8 dates is 37 distinct CNRs: 296 pairs.
    client, mock = make_client()
    mock.return_value = FakeResponse(200, CHECK_BODY)
    cnrs = _distinct(37) + ["zzab-01-000001-2024"]
    client.check_cause_lists(cnrs, from_date="2026-11-01", to_date="2026-11-08")
    assert mock.call_count == 1


def test_settlement_unconfirmed_is_never_retried_even_with_retry_posts(make_client):
    client, mock = make_client(max_retries=3, retry_posts=True)
    message = "We could not confirm the credit charge for this call, so no results were returned. Please check your usage before retrying."
    body = {"success": False, "code": "SETTLEMENT_UNCONFIRMED", "message": message, "error": message}
    mock.side_effect = [FakeResponse(503, body), FakeResponse(200, EMPTY_CHECK)]
    with pytest.raises(ServiceUnavailableError) as info:
        client.check_cause_lists([CNR])
    assert info.value.code == "SETTLEMENT_UNCONFIRMED"
    assert mock.call_count == 1


def test_other_503_is_still_retried_with_retry_posts(make_client):
    client, mock = make_client(max_retries=3, retry_posts=True)
    entitlement = {"success": False, "error": "Unable to verify API entitlement. Please retry.", "code": "ENTITLEMENT_UNAVAILABLE"}
    mock.side_effect = [FakeResponse(503, entitlement), FakeResponse(200, EMPTY_CHECK)]
    client.check_cause_lists([CNR])
    assert mock.call_count == 2
