"""API 1.8.0 additions: party profile (quick and full mode), deleting the
key's own audit activity, and the new optional response fields."""
import inspect
import re
from datetime import datetime, timedelta, timezone

import pytest
import requests

from courtmesh import (
    API_REFUSAL_CODES,
    BadGatewayError,
    CaseDetails,
    CaseDocumentRow,
    CaseDocuments,
    ChangeEvent,
    ConflictError,
    CourtMesh,
    CourtMeshError,
    InsufficientCreditsError,
    NotFoundError,
    PartyScreenMatch,
    PermissionDeniedError,
    RateLimitError,
    ServerError,
    ServiceUnavailableError,
    ValidationError,
)
from courtmesh.models import CaseListItem, SemanticSearchResultItem
from helpers import FakeResponse

BASE = "https://research.courtmesh.ai/api/v1/prod"
CNR = "ZZAB010000012024"
PPR_ID = "ppr_" + "0123456789abcdef" * 2
_UUID_V4_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.IGNORECASE)


def ok(data, status=200, **extra):
    body = {"success": True, "data": data}
    body.update(extra)
    return FakeResponse(status, body)


def refusal(status, code, **extra):
    body = {"success": False, "code": code, "error": "Refused.", "message": "Refused."}
    body.update(extra)
    return FakeResponse(status, body)


def call(mock_request, index=0):
    args, kwargs = mock_request.call_args_list[index]
    return args[0], args[1], kwargs


QUICK_PROFILE = {
    "subject": {"name": "Acme Example Traders Private Limited", "entityType": "company"},
    "verdict": "identity_found",
    "summary": "One identity at confirmed confidence with 1 case.",
    "identities": [
        {
            "confidence": "confirmed",
            "why": ["The CIN you gave is recorded in 1 case of this group."],
            "caseCount": 1,
            "profile": {"pending": 1, "disposed": 0},
            "cases": [
                {
                    "caseId": "000000000000000000000011",
                    "court": "NCLT",
                    "courtType": "Tribunal",
                    "bench": "New Delhi",
                    "partyRole": "respondent",
                    "status": "pending",
                    "decisionDate": None,
                    "confidence": "confirmed",
                    "courtRecordActs": [{"act": "EXAMPLE ACT", "sections": ["7"]}],
                    "documents": [
                        {
                            "documentId": "00000000000000000000001a",
                            "kind": "order",
                            "date": "2026-11-04",
                            "links": {"text": "/cases/000000000000000000000011/orders/00000000000000000000001a/text", "pdf": None},
                        }
                    ],
                }
            ],
        }
    ],
    "possibleOtherPeople": [],
    "relatedButUnverified": [],
    "notes": [],
}

QUICK_META = {
    "creditsCharged": 100,
    "metered": True,
    "creditsBreakdown": {
        "searches": {"count": 5, "credits": 5},
        "caseRecords": {"count": 1, "credits": 1},
        "documentLists": {"count": 1, "credits": 1},
        "minimumCharge": {"credits": 93},
    },
    "adjudicated": False,
    "corpusAsOf": "2026-11-10T09:30:00.000Z",
}


def _profile_kwargs(**extra):
    kwargs = dict(name="Acme Example Traders Private Limited", entityType="company", purpose="due_diligence")
    kwargs.update(extra)
    return kwargs


# -- POST /party/profile: request shape ----------------------------------------


def test_build_party_profile_sends_required_fields_only_by_default(make_client):
    client, mock = make_client()
    mock.return_value = ok(QUICK_PROFILE, meta=QUICK_META)

    result = client.build_party_profile(**_profile_kwargs())

    method, url, kwargs = call(mock)
    assert (method, url) == ("POST", BASE + "/party/profile")
    assert kwargs["json"] == {
        "name": "Acme Example Traders Private Limited",
        "entityType": "company",
        "purpose": "due_diligence",
    }
    assert kwargs["params"] is None
    assert kwargs["timeout"] == 90.0
    assert "Idempotency-Key" not in kwargs["headers"]
    assert result.data["verdict"] == "identity_found"
    assert result.data["identities"][0]["cases"][0]["bench"] == "New Delhi"
    assert result.meta["creditsBreakdown"]["minimumCharge"] == {"credits": 93}
    assert result.replayed is None


def test_build_party_profile_sends_every_optional_field(make_client):
    client, mock = make_client()
    mock.return_value = ok(
        {"requestId": PPR_ID, "mode": "full", "status": "queued", "statusUrl": "/api/v1/prod/party/profile/" + PPR_ID, "maxCredits": 150},
        status=202,
    )

    client.build_party_profile(
        name="Ravi Example Kumar",
        entityType="person",
        purpose="bgv",
        aliases=["R. E. Kumar"],
        identifiers={"pan": "ZZZZZ0000Z"},
        address={"state": "Example State", "city": "Example City"},
        knownPersons=["Mohan Example Kumar"],
        court=["High Court of Example"],
        since="2020-01-01",
        limit=40,
        adjudicate=True,
        displayThreshold=0.5,
        minConfidence="probable",
        include=("documents", "acts", "fir", "status", "summary"),
        allowUnconfirmedPrimary=False,
        mode="full",
        maxCredits=150,
        webhook={"url": "https://hooks.example.com/courtmesh", "headers": {"Authorization": "Bearer example"}},
        timeout=12.5,
    )

    kwargs = call(mock)[2]
    assert kwargs["json"] == {
        "name": "Ravi Example Kumar",
        "entityType": "person",
        "purpose": "bgv",
        "aliases": ["R. E. Kumar"],
        "identifiers": {"pan": "ZZZZZ0000Z"},
        "address": {"state": "Example State", "city": "Example City"},
        "knownPersons": ["Mohan Example Kumar"],
        "court": ["High Court of Example"],
        "since": "2020-01-01",
        "limit": 40,
        "adjudicate": True,
        "displayThreshold": 0.5,
        "minConfidence": "probable",
        "include": ["documents", "acts", "fir", "status", "summary"],
        "allowUnconfirmedPrimary": False,
        "mode": "full",
        "maxCredits": 150,
        "webhook": {"url": "https://hooks.example.com/courtmesh", "headers": {"Authorization": "Bearer example"}},
    }
    assert kwargs["timeout"] == 12.5


def test_build_party_profile_full_mode_returns_accepted_answer(make_client):
    client, mock = make_client()
    mock.return_value = ok(
        {
            "requestId": PPR_ID,
            "mode": "full",
            "status": "queued",
            "statusUrl": "/api/v1/prod/party/profile/" + PPR_ID,
            "maxCredits": 1000,
            "webhook": {"signingSecret": "whsec_example", "note": "Shown once."},
        },
        status=202,
        meta={"creditsCharged": 0, "metered": True},
    )

    result = client.build_party_profile(**_profile_kwargs(mode="full"))

    assert result.data["requestId"] == PPR_ID
    assert result.data["status"] == "queued"
    assert result.data["webhook"]["signingSecret"] == "whsec_example"
    assert "subject" not in result.data
    assert result.meta["creditsCharged"] == 0


# -- POST /party/profile: Idempotency-Key ------------------------------------------


def test_build_party_profile_sends_explicit_idempotency_key(make_client):
    client, mock = make_client()
    mock.return_value = ok(QUICK_PROFILE, meta=QUICK_META)

    client.build_party_profile(**_profile_kwargs(idempotency_key="profile-key-1"))

    assert call(mock)[2]["headers"]["Idempotency-Key"] == "profile-key-1"


def test_build_party_profile_generates_idempotency_key_with_retry_posts(make_client):
    client, mock = make_client()
    mock.return_value = ok(QUICK_PROFILE, meta=QUICK_META)

    client.build_party_profile(**_profile_kwargs(retry_posts=True))

    assert _UUID_V4_RE.match(call(mock)[2]["headers"]["Idempotency-Key"])


def test_build_party_profile_reuses_one_idempotency_key_across_retries(make_client):
    client, mock = make_client(retry_posts=True)
    mock.side_effect = [requests.ConnectionError("reset"), ok(QUICK_PROFILE, meta=QUICK_META)]

    client.build_party_profile(**_profile_kwargs())

    assert mock.call_count == 2
    first = call(mock, 0)[2]["headers"]["Idempotency-Key"]
    assert _UUID_V4_RE.match(first)
    assert call(mock, 1)[2]["headers"]["Idempotency-Key"] == first


def test_build_party_profile_surfaces_replayed(make_client):
    client, mock = make_client()
    mock.return_value = FakeResponse(
        200, {"success": True, "data": QUICK_PROFILE, "meta": QUICK_META}, headers={"Idempotency-Replayed": "true"}
    )

    result = client.build_party_profile(**_profile_kwargs(idempotency_key="profile-key-1"))

    assert result.replayed is True


# -- POST /party/profile: errors and retries ----------------------------------------


@pytest.mark.parametrize(
    "status,code,exc_class",
    [
        (400, "VALIDATION_ERROR", ValidationError),
        (400, "IDEMPOTENCY_KEY_INVALID", ValidationError),
        (402, "INSUFFICIENT_API_CREDITS", InsufficientCreditsError),
        (403, "API_TIER_NOT_ALLOWED", PermissionDeniedError),
        (403, "API_NOT_AVAILABLE_ON_TRIAL", PermissionDeniedError),
        (403, "API_ENTERPRISE_ONLY", PermissionDeniedError),
        (409, "IDEMPOTENCY_KEY_REUSED", ConflictError),
        (409, "IDEMPOTENCY_IN_PROGRESS", ConflictError),
        (429, "DISTINCT_NAMES_LIMIT_REACHED", RateLimitError),
        (429, "PARTY_PROFILE_TOO_MANY_ACTIVE", RateLimitError),
        (502, "PARTY_SCREEN_SEARCH_DEGRADED", BadGatewayError),
        (503, "PARTY_PROFILE_FULL_UNAVAILABLE", ServiceUnavailableError),
        (503, "ACCOUNT_STANDING_UNAVAILABLE", ServiceUnavailableError),
        (503, "ENTITLEMENT_UNAVAILABLE", ServiceUnavailableError),
    ],
)
def test_build_party_profile_maps_documented_errors(make_client, status, code, exc_class):
    client, mock = make_client()
    mock.return_value = refusal(status, code, requestId="req-1")

    with pytest.raises(exc_class) as info:
        client.build_party_profile(**_profile_kwargs())

    assert info.value.status_code == status
    assert info.value.code == code
    assert info.value.request_id == "req-1"
    assert mock.call_count == 1


def test_build_party_profile_too_many_active_carries_retry_after_and_is_not_retried(make_client, sleep_calls):
    client, mock = make_client()
    mock.return_value = FakeResponse(
        429, {"success": False, "code": "PARTY_PROFILE_TOO_MANY_ACTIVE", "error": "Too many."}, headers={"Retry-After": "30"}
    )

    with pytest.raises(RateLimitError) as info:
        client.build_party_profile(**_profile_kwargs(mode="full"))

    assert info.value.retry_after == 30.0
    assert mock.call_count == 1
    assert sleep_calls == []


def test_build_party_profile_not_retried_after_connection_error_by_default(make_client):
    client, mock = make_client()
    mock.side_effect = requests.ConnectionError("reset")

    with pytest.raises(CourtMeshError) as info:
        client.build_party_profile(**_profile_kwargs())

    assert info.value.status_code is None
    assert mock.call_count == 1


def test_build_party_profile_full_unavailable_not_retried_even_with_retry_posts(make_client):
    client, mock = make_client(retry_posts=True)
    mock.return_value = refusal(503, "PARTY_PROFILE_FULL_UNAVAILABLE")

    with pytest.raises(ServiceUnavailableError):
        client.build_party_profile(**_profile_kwargs(mode="full"))

    assert mock.call_count == 1


@pytest.mark.parametrize("body", [{"success": False, "error": "Charge not confirmed."}, {"success": False, "code": "SETTLEMENT_UNCONFIRMED"}])
def test_build_party_profile_503_of_unknown_charge_not_retried_even_with_retry_posts(make_client, body):
    client, mock = make_client(retry_posts=True)
    mock.return_value = FakeResponse(503, body)

    with pytest.raises(ServiceUnavailableError):
        client.build_party_profile(**_profile_kwargs())

    assert mock.call_count == 1


def test_build_party_profile_standing_unavailable_retried_with_retry_posts(make_client):
    client, mock = make_client(retry_posts=True)
    mock.side_effect = [refusal(503, "ENTITLEMENT_UNAVAILABLE"), ok(QUICK_PROFILE, meta=QUICK_META)]

    result = client.build_party_profile(**_profile_kwargs())

    assert mock.call_count == 2
    assert result.data["verdict"] == "identity_found"


def test_build_party_profile_rate_limited_is_retried(make_client):
    client, mock = make_client()
    mock.side_effect = [
        FakeResponse(429, {"success": False, "code": "RATE_LIMITED", "error": "Slow down."}, headers={"Retry-After": "1"}),
        ok(QUICK_PROFILE, meta=QUICK_META),
    ]

    client.build_party_profile(**_profile_kwargs())

    assert mock.call_count == 2


# -- GET /party/profile/{requestId} ---------------------------------------------------


STATUS_RUNNING = {
    "requestId": PPR_ID,
    "mode": "full",
    "status": "running",
    "stage": "analyse",
    "progress": {
        "casesFound": 3,
        "refreshesStarted": 2,
        "refreshesFinished": 2,
        "casesAnalysed": 1,
        "casesNotAnalysed": 0,
        "partyAnalysis": "pending",
    },
    "createdAt": "2026-11-11T09:30:00.000Z",
    "startedAt": "2026-11-11T09:30:02.000Z",
    "finishedAt": None,
    "resultExpiresAt": None,
    "credits": {
        "charged": 40,
        "maxCredits": 1000,
        "breakdown": {
            "search": {"credits": 10},
            "courtRefreshes": {"count": 2, "credits": 2},
            "caseAnalyses": {"full": 1, "short": 0, "existing": 0, "tokens": 9000, "credits": 28},
            "partyAnalysis": {"tokens": 0, "credits": 0},
        },
    },
}


def test_get_party_profile_url_and_result(make_client):
    client, mock = make_client()
    mock.return_value = ok(STATUS_RUNNING, meta={"creditsCharged": 0, "metered": True})

    result = client.get_party_profile(PPR_ID)

    method, url, kwargs = call(mock)
    assert (method, url) == ("GET", BASE + "/party/profile/" + PPR_ID)
    assert kwargs["params"] is None
    assert kwargs["json"] is None
    assert "Idempotency-Key" not in kwargs["headers"]
    assert result.data["stage"] == "analyse"
    assert result.data["credits"]["breakdown"]["courtRefreshes"]["count"] == 2


def test_get_party_profile_encodes_the_id(make_client):
    client, mock = make_client()
    mock.return_value = ok(STATUS_RUNNING)

    client.get_party_profile("ppr_x/../y")

    assert call(mock)[1] == BASE + "/party/profile/ppr_x%2F..%2Fy"


def test_get_party_profile_completed_carries_result(make_client):
    client, mock = make_client()
    completed = dict(STATUS_RUNNING, status="completed", result=dict(QUICK_PROFILE, partyAnalysis=None, notes=["One note."]))
    completed.pop("stage")
    mock.return_value = ok(completed)

    result = client.get_party_profile(PPR_ID)

    assert result.data["result"]["partyAnalysis"] is None
    assert result.data["result"]["notes"] == ["One note."]


@pytest.mark.parametrize(
    "status,code,exc_class",
    [
        (404, "NOT_FOUND", NotFoundError),
        (429, "PDF_LIMIT_REACHED", RateLimitError),
        (500, "INTERNAL_ERROR", ServerError),
    ],
)
def test_get_party_profile_maps_documented_errors(make_client, status, code, exc_class):
    client, mock = make_client()
    mock.return_value = refusal(status, code)

    with pytest.raises(exc_class) as info:
        client.get_party_profile(PPR_ID)

    assert info.value.code == code


def test_get_party_profile_is_a_get_and_retried_after_502(make_client):
    client, mock = make_client()
    mock.side_effect = [FakeResponse(502, {"success": False, "error": "Bad gateway"}), ok(STATUS_RUNNING)]

    client.get_party_profile(PPR_ID)

    assert mock.call_count == 2


# -- DELETE /audit ------------------------------------------------------------------------


DELETE_OK = {"before": "2026-11-05T00:00:00.000Z", "removed": 120, "complete": True, "note": "Activity of this API key before this time is deleted."}


def test_delete_audit_activity_url_method_and_params(make_client):
    client, mock = make_client()
    mock.return_value = ok(DELETE_OK, meta={"creditsCharged": 0, "metered": False})

    result = client.delete_audit_activity("2026-11-05T00:00:00Z")

    method, url, kwargs = call(mock)
    assert (method, url) == ("DELETE", BASE + "/audit")
    assert kwargs["params"] == {"before": "2026-11-05T00:00:00Z"}
    assert kwargs["json"] is None
    assert "Idempotency-Key" not in kwargs["headers"]
    assert result.data["removed"] == 120
    assert result.data["complete"] is True


def test_delete_audit_activity_partial_reports_complete_false(make_client):
    client, mock = make_client()
    mock.return_value = ok(dict(DELETE_OK, complete=False, removed=5000))

    result = client.delete_audit_activity("2026-11-05T00:00:00Z")

    assert result.data["complete"] is False


def test_delete_audit_activity_converts_an_aware_datetime_to_utc(make_client):
    client, mock = make_client()
    mock.return_value = ok(DELETE_OK)

    ist = timezone(timedelta(hours=5, minutes=30))
    client.delete_audit_activity(datetime(2026, 11, 5, 5, 30, tzinfo=ist))

    assert call(mock)[2]["params"] == {"before": "2026-11-05T00:00:00Z"}


@pytest.mark.parametrize("before", [datetime(2026, 11, 5), "", "   ", None])
def test_delete_audit_activity_refuses_a_missing_or_naive_time_before_sending(make_client, before):
    client, mock = make_client()

    with pytest.raises(ValueError):
        client.delete_audit_activity(before)

    assert mock.call_count == 0


@pytest.mark.parametrize(
    "status,code,exc_class",
    [
        (400, "VALIDATION_ERROR", ValidationError),
        (403, "IP_NOT_ALLOWED", PermissionDeniedError),
        (500, "INTERNAL_ERROR", ServerError),
        (503, "ACCOUNT_STANDING_UNAVAILABLE", ServiceUnavailableError),
    ],
)
def test_delete_audit_activity_maps_documented_errors_without_retrying(make_client, status, code, exc_class):
    client, mock = make_client()
    mock.return_value = refusal(status, code)

    with pytest.raises(exc_class) as info:
        client.delete_audit_activity("2026-11-05T00:00:00Z")

    assert info.value.code == code
    assert mock.call_count == 1


@pytest.mark.parametrize("error", [requests.ConnectionError("reset"), requests.Timeout("read timed out")])
def test_delete_audit_activity_never_retried_after_a_network_error(make_client, sleep_calls, error):
    client, mock = make_client(max_retries=3)
    mock.side_effect = error

    with pytest.raises(CourtMeshError) as info:
        client.delete_audit_activity("2026-11-05T00:00:00Z")

    assert info.value.status_code is None
    assert mock.call_count == 1
    assert sleep_calls == []


@pytest.mark.parametrize("status", [502, 503, 504])
def test_delete_audit_activity_never_retried_after_a_gateway_status(make_client, status):
    client, mock = make_client(max_retries=3)
    mock.return_value = FakeResponse(status, {"success": False, "error": "Unavailable"})

    with pytest.raises(CourtMeshError):
        client.delete_audit_activity("2026-11-05T00:00:00Z")

    assert mock.call_count == 1


def test_delete_audit_activity_rate_limited_is_retried(make_client):
    client, mock = make_client()
    mock.side_effect = [
        FakeResponse(429, {"success": False, "code": "RATE_LIMITED", "error": "Slow down."}, headers={"Retry-After": "1"}),
        ok(DELETE_OK),
    ]

    client.delete_audit_activity("2026-11-05T00:00:00Z")

    assert mock.call_count == 2


def test_other_deletes_still_retry_after_a_network_error(make_client):
    client, mock = make_client()
    mock.side_effect = [requests.ConnectionError("reset"), FakeResponse(204, None)]

    client.delete_watchlist("wl_1")

    assert mock.call_count == 2


# -- new optional response fields ---------------------------------------------------------


def test_search_cases_surfaces_cnr_lookup(make_client):
    client, mock = make_client()
    mock.return_value = FakeResponse(
        200,
        {
            "success": True,
            "data": [],
            "cnrLookup": {"cnr": CNR, "status": "pending", "requestId": "chk_1"},
            "meta": {},
            "pagination": {"total": 0, "hasMore": False, "limit": 20, "nextCursor": None},
        },
    )

    result = client.search_cases(cnr=CNR)

    assert result.cnr_lookup == {"cnr": CNR, "status": "pending", "requestId": "chk_1"}


def test_search_cases_cnr_lookup_is_none_when_absent(make_client):
    client, mock = make_client()
    same = [{"caseId": "000000000000000000000021", "caseType": "SLP(C)", "decisionDate": None}]
    mock.return_value = ok([{"id": "c1", "sameMatter": same}], meta={}, pagination={"total": 1, "hasMore": False})

    result = client.search_cases(query="example")

    assert result.cnr_lookup is None
    assert result.data[0]["sameMatter"] == same


def test_new_fields_pass_through_on_case_cnr_orders_changes_and_screen(make_client):
    client, mock = make_client()
    case = {
        "id": "c1",
        "bench": "Delhi",
        "courtRecordActs": [{"act": "EXAMPLE ACT", "sections": ["3", "4"]}],
        "courtRecordFir": [{"firNumber": "12", "firYear": "2024", "policeStation": "Example Nagar"}],
    }
    mock.return_value = ok(case)
    assert client.get_case("c1").data["courtRecordFir"][0]["policeStation"] == "Example Nagar"

    mock.return_value = ok({"cnr": CNR, "status": "found", "case": case, "requestId": None})
    assert client.get_case_by_cnr(CNR).data["case"]["bench"] == "Delhi"

    mock.return_value = ok(
        {
            "caseId": "c1",
            "ordersTextWithheld": True,
            "withheldReason": "not_published",
            "documents": [
                {"id": "d1", "kind": "order", "date": None, "orderNumber": None, "textAvailable": False, "pdfAvailable": False, "unavailableReason": "not_published"}
            ],
        }
    )
    orders = client.list_case_orders("c1").data
    assert orders["ordersTextWithheld"] is True
    assert orders["documents"][0]["unavailableReason"] == "not_published"

    mock.return_value = ok(
        [{"id": "e1", "type": "case.order_added", "createdAt": "2026-11-12T00:00:00Z", "cnr": CNR, "caseId": None, "watchlists": [], "data": {}, "withheld": "case_restricted"}],
        pagination={"nextCursor": "c2", "hasMore": False},
    )
    assert client.list_changes().data[0]["withheld"] == "case_restricted"
    assert client.list_watchlist_events("wl_1").data[0]["withheld"] == "case_restricted"

    mock.return_value = ok({"matches": [dict(case, caseId="c1", sameMatter=[{"caseId": "c2"}])], "relatedButUnverified": []})
    match = client.screen_party(name="Example Person", entityType="person", purpose="kyc").data["matches"][0]
    assert match["courtRecordActs"][0]["sections"] == ["3", "4"]
    assert match["sameMatter"] == [{"caseId": "c2"}]


def test_models_declare_the_new_fields_as_optional():
    for model, fields in (
        (CaseDetails, ("bench", "courtRecordActs", "courtRecordFir")),
        (PartyScreenMatch, ("courtRecordActs", "courtRecordFir", "sameMatter")),
        (CaseListItem, ("sameMatter",)),
        (SemanticSearchResultItem, ("sameMatter",)),
        (ChangeEvent, ("withheld",)),
        (CaseDocumentRow, ("unavailableReason",)),
        (CaseDocuments, ("ordersTextWithheld", "withheldReason")),
    ):
        for field in fields:
            assert field in model.__optional_keys__, (model.__name__, field)
    assert {"id", "textAvailable", "pdfAvailable"} <= CaseDocumentRow.__required_keys__
    assert {"caseId", "documents"} <= CaseDocuments.__required_keys__


def test_new_refusal_codes_are_listed():
    assert "PARTY_PROFILE_FULL_UNAVAILABLE" in API_REFUSAL_CODES
    assert "PARTY_PROFILE_TOO_MANY_ACTIVE" in API_REFUSAL_CODES


def test_new_methods_have_expected_signatures():
    expected = {
        "build_party_profile": [
            "name", "entityType", "purpose", "aliases", "identifiers", "address", "knownPersons", "court",
            "since", "limit", "adjudicate", "displayThreshold", "minConfidence", "include",
            "allowUnconfirmedPrimary", "mode", "maxCredits", "webhook", "timeout", "retry_posts", "idempotency_key",
        ],
        "get_party_profile": ["request_id", "timeout"],
        "delete_audit_activity": ["before", "timeout"],
    }
    for name, params in expected.items():
        signature = inspect.signature(getattr(CourtMesh, name))
        assert [p for p in signature.parameters if p != "self"] == params, name
        assert signature.return_annotation is not inspect.Signature.empty, name
    assert inspect.signature(CourtMesh.delete_audit_activity).parameters["before"].default is inspect.Parameter.empty
