"""CNR lookup, watchlists, change feed, webhooks and the signature verifier."""
import json
import os

import pytest
from helpers import FakeResponse

from courtmesh import (
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ValidationError,
    WebhookSignatureError,
    assert_cnr,
    normalize_cnr,
    verify_webhook_signature,
)

BASE = "https://research.courtmesh.ai/api/v1/prod"
CNR = "DLHC010084212021"


def ok(data, **extra):
    body = {"success": True, "data": data}
    body.update(extra)
    return FakeResponse(200, body)


def page(data, next_cursor):
    return ok(data, pagination={"nextCursor": next_cursor, "hasMore": next_cursor is not None})


def call(mock_request, index=0):
    args, kwargs = mock_request.call_args_list[index]
    return args[0], args[1], kwargs


# -- normalize_cnr ---------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "DLHC010084212021",
        "  dlhc010084212021 ",
        "CNR: DLHC-01-008421-2021",
        "CNR DLHC01 008421 2021",
        "CNR NO DLHC010084212021",
        "cnr:dlhc/01/008421/2021",
        "DLHC.01.008421.2021",
    ],
)
def test_normalize_cnr_accepts_common_spellings(raw):
    assert normalize_cnr(raw) == CNR


def test_normalize_cnr_rejects_garbage():
    for bad in ("", "DLHC01008421202", "DLHC0100842120211", "1234567890123456", None, 42):
        assert normalize_cnr(bad) is None
    assert normalize_cnr("WBCHCA0113712023") == "WBCHCA0113712023"
    with pytest.raises(ValueError):
        assert_cnr("nope")
    assert assert_cnr("cnr: dlhc010084212021") == CNR


# -- get_case_by_cnr -------------------------------------------------------


def test_get_case_by_cnr_normalises_and_returns_found(make_client):
    client, mock = make_client()
    mock.return_value = ok({"cnr": CNR, "status": "found", "case": {"id": "c1"}, "requestId": None})
    res = client.get_case_by_cnr("CNR: DLHC-01-008421-2021")
    method, url, kwargs = call(mock)
    assert (method, url) == ("GET", BASE + "/cases/by-cnr/" + CNR)
    assert kwargs["params"] is None
    assert res.data["status"] == "found"


def test_get_case_by_cnr_fetch_and_pending(make_client):
    client, mock = make_client()
    mock.return_value = FakeResponse(202, {"success": True, "data": {"cnr": CNR, "status": "pending", "requestId": "r1"}})
    res = client.get_case_by_cnr(CNR, fetch=True)
    assert call(mock)[2]["params"] == {"fetch": "true"}
    assert res.data["status"] == "pending"
    assert res.data["requestId"] == "r1"


def test_get_case_by_cnr_default_sends_no_fetch_param(make_client):
    client, mock = make_client()
    mock.return_value = FakeResponse(202, {"success": True, "data": {"cnr": CNR, "status": "pending", "requestId": "r2"}})
    res = client.get_case_by_cnr(CNR)
    assert call(mock)[2]["params"] is None
    assert res.data["status"] == "pending"


def test_get_case_by_cnr_fetch_false_opts_out(make_client):
    client, mock = make_client()
    mock.return_value = FakeResponse(404, {"success": False, "error": "No such case", "code": "CASE_NOT_FOUND"})
    with pytest.raises(NotFoundError):
        client.get_case_by_cnr(CNR, fetch=False)
    assert call(mock)[2]["params"] == {"fetch": "false"}


def test_get_case_by_cnr_daily_check_cap_raises_rate_limit_without_retry(make_client):
    client, mock = make_client()
    mock.return_value = FakeResponse(
        429, {"success": False, "error": "Daily limit reached", "code": "LIVE_FETCH_LIMIT_REACHED", "retryAfter": 3600}
    )
    with pytest.raises(RateLimitError) as info:
        client.get_case_by_cnr(CNR)
    assert info.value.code == "LIVE_FETCH_LIMIT_REACHED"
    assert mock.call_count == 1


def test_get_case_by_cnr_fetch_true_on_tier_without_live_fetch_raises(make_client):
    client, mock = make_client()
    mock.return_value = FakeResponse(
        403, {"success": False, "error": "Not available on this plan", "code": "LIVE_FETCH_NOT_ALLOWED"}
    )
    with pytest.raises(PermissionDeniedError) as info:
        client.get_case_by_cnr(CNR, fetch=True)
    assert info.value.code == "LIVE_FETCH_NOT_ALLOWED"
    assert call(mock)[2]["params"] == {"fetch": "true"}


def test_get_case_by_cnr_not_found_raises(make_client):
    client, mock = make_client()
    mock.return_value = FakeResponse(404, {"success": False, "error": "No such case", "code": "CASE_NOT_FOUND"})
    with pytest.raises(NotFoundError) as info:
        client.get_case_by_cnr(CNR)
    assert info.value.code == "CASE_NOT_FOUND"


def test_get_case_by_cnr_invalid_passed_through_for_server_to_reject(make_client):
    client, mock = make_client()
    mock.return_value = FakeResponse(400, {"success": False, "error": "Invalid CNR", "code": "INVALID_CNR"})
    with pytest.raises(Exception) as info:
        client.get_case_by_cnr("nope")
    assert info.value.code == "INVALID_CNR"
    assert call(mock)[1] == BASE + "/cases/by-cnr/nope"


def test_search_cases_cnr_without_query(make_client):
    client, mock = make_client()
    mock.return_value = FakeResponse(200, {"success": True, "data": [], "meta": {}, "pagination": {"hasMore": False}})
    client.search_cases(cnr="cnr: dlhc010084212021")
    assert call(mock)[2]["json"] == {"cnr": CNR}


# -- watchlists --------------------------------------------------------------


def test_create_watchlist_normalises_items(make_client):
    client, mock = make_client()
    mock.return_value = ok({"id": "wl_1", "results": [{"cnr": CNR, "result": "watching"}]})
    res = client.create_watchlist("Loans", items=[{"cnr": "dlhc-010084-212021", "reference": "LOAN-42"}], metadata={"a": 1})
    method, url, kwargs = call(mock)
    assert (method, url) == ("POST", BASE + "/watchlists")
    assert kwargs["json"] == {"name": "Loans", "items": [{"cnr": CNR, "reference": "LOAN-42"}], "metadata": {"a": 1}}
    assert res.data["results"][0]["result"] == "watching"


def test_idempotency_key_only_when_in_effect(make_client):
    client, mock = make_client()
    mock.return_value = ok({"id": "wl_1"})
    client.create_watchlist("x")
    assert "Idempotency-Key" not in call(mock)[2]["headers"]
    client.create_watchlist("x", idempotency_key="my-key")
    assert call(mock, 1)[2]["headers"]["Idempotency-Key"] == "my-key"
    client2, mock2 = make_client(retry_posts=True)
    mock2.return_value = ok({"id": "wl_1"})
    client2.create_watchlist("x")
    assert len(call(mock2)[2]["headers"]["Idempotency-Key"]) == 36


def test_list_watchlists_and_iterator(make_client):
    client, mock = make_client()
    mock.side_effect = [page([{"id": "wl_1"}], "c2"), page([{"id": "wl_2"}], None)]
    ids = [w["id"] for w in client.iter_watchlists(limit=1)]
    assert ids == ["wl_1", "wl_2"]
    assert call(mock, 0)[2]["params"] == {"limit": 1}
    assert call(mock, 1)[2]["params"] == {"cursor": "c2", "limit": 1}
    mock.side_effect = None
    mock.return_value = page([{"id": "wl_1"}], "zz")
    result = client.list_watchlists(cursor="c1")
    assert result.next_cursor == "zz"
    assert result.data == [{"id": "wl_1"}]


def test_get_update_delete_watchlist(make_client):
    client, mock = make_client()
    mock.side_effect = [ok({"id": "wl_1", "name": "A"}), ok({"id": "wl_1", "name": "B"}), ok({"deleted": True})]
    client.get_watchlist("wl_1")
    updated = client.update_watchlist("wl_1", name="B", metadata={"t": 1})
    deleted = client.delete_watchlist("wl_1")
    assert call(mock, 0)[:2] == ("GET", BASE + "/watchlists/wl_1")
    assert call(mock, 1)[0] == "PATCH"
    assert call(mock, 1)[2]["json"] == {"name": "B", "metadata": {"t": 1}}
    assert updated.data["name"] == "B"
    assert call(mock, 2)[0] == "DELETE"
    assert deleted.data["deleted"] is True


def test_delete_tolerates_204_without_body(make_client):
    client, mock = make_client()
    mock.return_value = FakeResponse(204, None)
    assert client.delete_webhook("wh_1").data == {"deleted": True}


def test_add_and_list_and_remove_items(make_client):
    client, mock = make_client()
    mock.side_effect = [
        ok({"results": [{"cnr": CNR, "result": "pending"}, {"cnr": "BAD", "result": "invalid"}]}),
        page([{"cnr": CNR}], "n1"),
        page([{"cnr": "X"}], None),
        ok({"deleted": True}),
    ]
    added = client.add_watchlist_items("wl_1", [{"cnr": "DLHC010084212021"}, {"cnr": "BAD"}])
    assert call(mock, 0)[2]["json"] == {"items": [{"cnr": CNR}, {"cnr": "BAD"}]}
    assert added.data["results"][1]["result"] == "invalid"
    cnrs = [i["cnr"] for i in client.iter_watchlist_items("wl_1", status="pending", limit=50)]
    assert cnrs == [CNR, "X"]
    assert call(mock, 1)[2]["params"] == {"limit": 50, "status": "pending"}
    assert call(mock, 2)[2]["params"]["cursor"] == "n1"
    client.remove_watchlist_item("wl_1", "cnr dlhc010084212021")
    assert call(mock, 3)[:2] == ("DELETE", BASE + "/watchlists/wl_1/items/" + CNR)


# -- change feed --------------------------------------------------------------


def evt(i):
    return {"id": "evt_" + i, "type": "case.order_added", "createdAt": "t", "cnr": CNR, "watchlists": [], "data": {}}


def test_list_changes_params(make_client):
    client, mock = make_client()
    mock.return_value = page([evt("1")], "cur1")
    res = client.list_changes(
        since="2026-11-01T00:00:00Z", types=["case.order_added", "case.disposed"], cnr="dlhc010084212021", limit=100
    )
    assert call(mock)[:2] == ("GET", BASE + "/changes")
    assert call(mock)[2]["params"] == {
        "since": "2026-11-01T00:00:00Z",
        "types": "case.order_added,case.disposed",
        "cnr": CNR,
        "limit": 100,
    }
    assert res.next_cursor == "cur1"


def test_iter_changes_stops_at_first_empty_page(make_client):
    client, mock = make_client()
    mock.side_effect = [page([evt("1"), evt("2")], "cur1"), page([evt("3")], "cur2"), page([], "cur3")]
    ids = [e["id"] for e in client.iter_changes()]
    assert ids == ["evt_1", "evt_2", "evt_3"]
    assert mock.call_count == 3
    assert call(mock, 2)[2]["params"]["cursor"] == "cur2"


def test_iter_changes_stops_when_cursor_does_not_advance(make_client):
    client, mock = make_client()
    mock.side_effect = [page([evt("1")], "cur1"), page([evt("2")], "cur1")]
    assert [e["id"] for e in client.iter_changes()] == ["evt_1", "evt_2"]


def test_iter_changes_resumes_from_cursor_and_respects_max_pages(make_client):
    client, mock = make_client()
    mock.side_effect = [page([evt("1")], "cur1"), page([evt("2")], "cur2")]
    list(client.iter_changes(cursor="start", max_pages=2))
    assert call(mock, 0)[2]["params"]["cursor"] == "start"
    assert mock.call_count == 2


def test_watchlist_events(make_client):
    client, mock = make_client()
    mock.side_effect = [page([evt("1")], "c1"), page([], "c2")]
    ids = [e["id"] for e in client.iter_watchlist_events("wl_9", types="case.disposed")]
    assert ids == ["evt_1"]
    assert call(mock)[:2] == ("GET", BASE + "/watchlists/wl_9/events")
    assert call(mock)[2]["params"] == {"types": "case.disposed"}
    mock.side_effect = None
    mock.return_value = page([], "c")
    assert client.list_watchlist_events("wl_9").data == []


# -- webhooks ------------------------------------------------------------------


def test_create_webhook_returns_secret(make_client):
    client, mock = make_client()
    mock.return_value = ok({"id": "wh_1", "secret": "whsec_abc"})
    res = client.create_webhook("https://e.com/h", events=["case.disposed"], watchlist_ids=["wl_1"], description="d")
    assert call(mock)[:2] == ("POST", BASE + "/webhooks")
    assert call(mock)[2]["json"] == {
        "url": "https://e.com/h",
        "events": ["case.disposed"],
        "watchlistIds": ["wl_1"],
        "description": "d",
    }
    assert res.data["secret"] == "whsec_abc"


def test_webhook_crud(make_client):
    client, mock = make_client()
    mock.side_effect = [page([{"id": "wh_1"}], None), ok({"id": "wh_1"}), ok({"id": "wh_1", "enabled": True}), ok({"deleted": True})]
    assert [w["id"] for w in client.iter_webhooks()] == ["wh_1"]
    client.get_webhook("wh_1")
    updated = client.update_webhook("wh_1", enabled=True, url="https://e.com/new")
    client.delete_webhook("wh_1")
    assert call(mock, 2)[0] == "PATCH"
    assert call(mock, 2)[2]["json"] == {"url": "https://e.com/new", "enabled": True}
    assert updated.data["enabled"] is True
    assert call(mock, 3)[:2] == ("DELETE", BASE + "/webhooks/wh_1")


def test_rotate_test_deliveries_retry(make_client):
    client, mock = make_client()
    mock.side_effect = [
        ok({"id": "wh_1", "secret": "whsec_new"}),
        ok({"id": "whd_1", "status": "succeeded"}),
        page([{"id": "whd_1"}], "d2"),
        page([{"id": "whd_2"}], None),
        ok({"id": "whd_1", "status": "pending"}),
    ]
    assert client.rotate_webhook_secret("wh_1").data["secret"] == "whsec_new"
    assert call(mock, 0)[:2] == ("POST", BASE + "/webhooks/wh_1/rotate-secret")
    assert call(mock, 0)[2]["json"] is None
    assert client.test_webhook("wh_1").data["status"] == "succeeded"
    assert call(mock, 1)[1] == BASE + "/webhooks/wh_1/test"
    ids = [d["id"] for d in client.iter_webhook_deliveries("wh_1", limit=1)]
    assert ids == ["whd_1", "whd_2"]
    assert call(mock, 2)[1] == BASE + "/webhooks/wh_1/deliveries"
    retried = client.retry_webhook_delivery("wh_1", "whd_1")
    assert call(mock, 4)[:2] == ("POST", BASE + "/webhooks/wh_1/deliveries/whd_1/retry")
    assert retried.data["status"] == "pending"


def test_new_error_codes_surface(make_client):
    client, mock = make_client()
    mock.return_value = FakeResponse(403, {"success": False, "error": "cap", "code": "WEBHOOK_LIMIT_REACHED"})
    with pytest.raises(Exception) as info:
        client.create_webhook("https://x")
    assert info.value.code == "WEBHOOK_LIMIT_REACHED"


# -- HTTP layer ----------------------------------------------------------------


def test_delete_retried_by_default_but_patch_is_not(make_client, sleep_calls):
    client, mock = make_client()
    mock.side_effect = [FakeResponse(503, {"success": False, "error": "x"}), ok({"deleted": True})]
    client.delete_webhook("wh_1")
    assert mock.call_count == 2
    client2, mock2 = make_client()
    mock2.side_effect = [FakeResponse(503, {"success": False, "error": "x"}), ok({"id": "wh_1"})]
    with pytest.raises(Exception):
        client2.update_webhook("wh_1", enabled=False)
    assert mock2.call_count == 1


def test_user_agent_is_0_5_0(make_client):
    client, mock = make_client()
    mock.return_value = ok({"id": "wh_1"})
    client.get_webhook("wh_1")
    assert call(mock)[2]["headers"]["User-Agent"] == "courtmesh-python/0.5.0"


# -- verify_webhook_signature --------------------------------------------------

with open(os.path.join(os.path.dirname(__file__), "fixtures", "webhook-vector.json")) as _fh:
    VECTOR = json.load(_fh)

HEADER = "t={},v1={}".format(VECTOR["timestamp"], VECTOR["signature"])
NOW = VECTOR["timestamp"] + 10


def test_known_vector_valid():
    event = verify_webhook_signature(VECTOR["rawBody"], HEADER, VECTOR["secret"], now=NOW)
    assert event["id"] == "evt_01HTESTVECTOR"
    assert event["type"] == "case.hearing_date_changed"
    assert event["cnr"] == CNR


def test_bytes_body_valid():
    assert verify_webhook_signature(VECTOR["rawBody"].encode(), HEADER, VECTOR["secret"], now=NOW)["cnr"] == CNR


def test_tampered_body_rejected():
    with pytest.raises(WebhookSignatureError) as info:
        verify_webhook_signature(VECTOR["rawBody"].replace("2026-12-04", "2026-12-05"), HEADER, VECTOR["secret"], now=NOW)
    assert info.value.reason == "signature_mismatch"


def test_wrong_secret_and_tampered_signature_rejected():
    with pytest.raises(WebhookSignatureError):
        verify_webhook_signature(VECTOR["rawBody"], HEADER, "whsec_wrong", now=NOW)
    bad = "t={},v1={}".format(VECTOR["timestamp"], VECTOR["signature"][:-1] + "0")
    with pytest.raises(WebhookSignatureError):
        verify_webhook_signature(VECTOR["rawBody"], bad, VECTOR["secret"], now=NOW)


def test_tampered_timestamp_rejected():
    header = "t={},v1={}".format(VECTOR["timestamp"] + 1, VECTOR["signature"])
    with pytest.raises(WebhookSignatureError) as info:
        verify_webhook_signature(VECTOR["rawBody"], header, VECTOR["secret"], now=NOW)
    assert info.value.reason == "signature_mismatch"


def test_expired_and_future_timestamps_rejected_and_tolerance_honoured():
    with pytest.raises(WebhookSignatureError) as info:
        verify_webhook_signature(VECTOR["rawBody"], HEADER, VECTOR["secret"], now=VECTOR["timestamp"] + 301)
    assert info.value.reason == "timestamp_out_of_tolerance"
    with pytest.raises(WebhookSignatureError):
        verify_webhook_signature(VECTOR["rawBody"], HEADER, VECTOR["secret"], now=VECTOR["timestamp"] - 301)
    assert verify_webhook_signature(
        VECTOR["rawBody"], HEADER, VECTOR["secret"], tolerance_seconds=400, now=VECTOR["timestamp"] + 301
    )["id"]
    assert verify_webhook_signature(VECTOR["rawBody"], HEADER, VECTOR["secret"], now=VECTOR["timestamp"] + 300)["id"]


def test_dual_v1_during_rotation():
    dual = "t={},v1={},v1={}".format(VECTOR["timestamp"], VECTOR["rotatedSignature"], VECTOR["signature"])
    assert verify_webhook_signature(VECTOR["rawBody"], dual, VECTOR["secret"], now=NOW)["id"]
    assert verify_webhook_signature(VECTOR["rawBody"], dual, VECTOR["rotatedSecret"], now=NOW)["id"]
    assert verify_webhook_signature(VECTOR["rawBody"], dual, [VECTOR["rotatedSecret"], VECTOR["secret"]], now=NOW)["id"]
    with pytest.raises(WebhookSignatureError):
        verify_webhook_signature(VECTOR["rawBody"], dual, "whsec_other", now=NOW)


@pytest.mark.parametrize("header", [None, "", "garbage", "t=1790000000", "v1=abcd", "t=abc,v1=abcd", "t=1790000000,v1=zzzz"])
def test_missing_or_malformed_header(header):
    with pytest.raises(WebhookSignatureError) as info:
        verify_webhook_signature(VECTOR["rawBody"], header, VECTOR["secret"], now=NOW)
    assert info.value.reason in ("missing_header", "malformed_header")


def test_uses_system_clock_by_default():
    import hashlib
    import hmac
    import time

    t = int(time.time())
    body = json.dumps({"id": "evt_1", "type": "webhook.test"})
    sig = hmac.new(b"whsec_x", "{}.{}".format(t, body).encode(), hashlib.sha256).hexdigest()
    assert verify_webhook_signature(body, "t={},v1={}".format(t, sig), "whsec_x")["id"] == "evt_1"
    with pytest.raises(WebhookSignatureError):
        verify_webhook_signature(VECTOR["rawBody"], HEADER, VECTOR["secret"])


# -- final server behaviour -------------------------------------------------


def test_unavailable_item_has_null_case_fields(make_client):
    client, mock = make_client()
    item = {
        "cnr": CNR, "reference": "R1", "label": None, "status": "unavailable",
        "caseId": None, "court": None, "title": None, "lastCheckedAt": None,
        "lastChangedAt": None, "snapshot": None, "addedAt": "2026-11-02T00:00:00.000Z",
    }
    mock.return_value = page([item], None)
    res = client.list_watchlist_items("wl_1", status="unavailable")
    assert call(mock)[2]["params"]["status"] == "unavailable"
    assert res.data[0]["status"] == "unavailable"
    assert res.data[0]["snapshot"] is None


def test_cap_exceeded_and_cooldown_not_found_are_data(make_client):
    client, mock = make_client()
    mock.return_value = ok(
        {
            "results": [
                {"cnr": CNR, "result": "cap_exceeded", "message": "The daily limit for adding case numbers has been reached. It resets at midnight IST."},
                {"cnr": "DLHC010084212022", "result": "not_found", "message": "eCourts had no such case when we last looked. Try again tomorrow."},
            ],
            "itemCount": 3,
        }
    )
    res = client.add_watchlist_items("wl_1", [{"cnr": CNR}, {"cnr": "DLHC010084212022"}])
    assert [r["result"] for r in res.data["results"]] == ["cap_exceeded", "not_found"]


def test_fetch_true_in_cooldown_raises_not_found(make_client):
    client, mock = make_client()
    mock.return_value = FakeResponse(
        404, {"success": False, "error": "No case with this CNR was found.", "code": "CASE_NOT_FOUND", "cnr": CNR, "status": "not_found"}
    )
    with pytest.raises(NotFoundError) as info:
        client.get_case_by_cnr(CNR, fetch=True)
    assert info.value.code == "CASE_NOT_FOUND"


def test_query_validation_details_are_path_message_strings(make_client):
    client, mock = make_client()
    details = ["limit: limit cannot exceed 100."]
    mock.return_value = FakeResponse(
        400, {"success": False, "error": "Validation failed. Please check your request and try again.", "code": "VALIDATION_ERROR", "details": details}
    )
    with pytest.raises(ValidationError) as info:
        client.list_changes(limit=500)
    assert info.value.response_body["details"] == details
