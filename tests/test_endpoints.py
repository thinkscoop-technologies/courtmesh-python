"""One test per endpoint method, plus envelope unwrapping checks."""
from helpers import FakeResponse


# -- 1. GET /judges/search --------------------------------------------------


def test_search_judges_with_query(make_client, envelope):
    client, mock_request = make_client()
    body = envelope(
        data=["JUSTICE A B", "JUSTICE C D"],
        meta={"query": "khanna", "responseTime": "3ms", "totalMatches": 2},
    )
    mock_request.return_value = FakeResponse(200, body)

    result = client.search_judges("khanna")

    assert result.data == ["JUSTICE A B", "JUSTICE C D"]
    assert result.meta["totalMatches"] == 2
    method, url = mock_request.call_args.args
    assert method == "GET"
    assert url.endswith("/judges/search")
    assert mock_request.call_args.kwargs["params"] == {"q": "khanna"}


def test_search_judges_default_empty_query(make_client, envelope):
    client, mock_request = make_client()
    mock_request.return_value = FakeResponse(200, envelope(data=["A"] * 50, meta={"query": "", "responseTime": "1ms", "totalMatches": 50}))

    result = client.search_judges()

    assert len(result.data) == 50
    assert mock_request.call_args.kwargs["params"] is None


# -- 2. POST /search/cases ---------------------------------------------------


def test_search_cases_sends_query_and_optional_filters(make_client, envelope):
    client, mock_request = make_client()
    body = envelope(
        data=[{"_id": "1", "title": "State v. X", "_score": 4.2, "_sort": [4.2, "1"]}],
        meta={"query": "state", "filters": {"court": "Delhi High Court"}, "responseTime": "10ms"},
        pagination={"total": 1, "hasMore": False, "page": 1, "limit": 20, "nextCursor": None},
    )
    mock_request.return_value = FakeResponse(200, body)

    result = client.search_cases(
        query="state",
        court="Delhi High Court",
        year=2021,
        caseNumber="123/2021",
        judgeName="Justice X",
        fromDate="2020-01-01",
        toDate="2021-01-01",
        page=1,
        limit=20,
        sortBy="relevance",
    )

    assert result.data[0]["title"] == "State v. X"
    assert result.meta["filters"]["court"] == "Delhi High Court"
    assert result.pagination["total"] == 1
    assert result.pagination["nextCursor"] is None

    method, url = mock_request.call_args.args
    assert method == "POST"
    assert url.endswith("/search/cases")
    sent_body = mock_request.call_args.kwargs["json"]
    assert sent_body["query"] == "state"
    assert sent_body["court"] == "Delhi High Court"
    assert sent_body["year"] == 2021
    assert sent_body["caseNumber"] == "123/2021"
    assert sent_body["sortBy"] == "relevance"


def test_search_cases_omits_unset_optional_fields(make_client, envelope):
    client, mock_request = make_client()
    mock_request.return_value = FakeResponse(
        200,
        envelope(data=[], meta={"query": "x", "filters": {}, "responseTime": "1ms"}, pagination={"total": 0, "hasMore": False, "limit": 20}),
    )

    client.search_cases(query="x")

    sent_body = mock_request.call_args.kwargs["json"]
    assert sent_body == {"query": "x"}


# -- 3. POST /search/cases/semantic ------------------------------------------


def test_semantic_search_uses_filters_object(make_client, envelope):
    client, mock_request = make_client()
    body = envelope(
        data=[
            {
                "id": "1",
                "caseNumber": "1/2020",
                "title": "Right to Privacy",
                "court": "Supreme Court",
                "caseType": "WP",
                "judges": ["JUSTICE A"],
                "petitioners": ["P"],
                "respondents": ["R"],
                "decisionDate": "2020-01-01",
                "disposalNature": "Allowed",
                "summary": "...",
                "hasDocuments": True,
                "hasAnalysis": True,
                "similarity": 0.87,
            }
        ],
        meta={"query": "privacy", "appliedFilters": {"court": "Supreme Court"}, "responseTime": "40ms", "searchType": "semantic"},
        pagination={"page": 1, "limit": 20, "total": 1, "totalPages": 1, "hasMore": False},
    )
    mock_request.return_value = FakeResponse(200, body)

    result = client.semantic_search(
        query="right to privacy",
        filters={"court": "Supreme Court", "decisionDate": {"$gte": "2019-01-01"}},
    )

    assert result.data[0]["similarity"] == 0.87
    assert result.meta["searchType"] == "semantic"
    sent_body = mock_request.call_args.kwargs["json"]
    assert sent_body["filters"] == {"court": "Supreme Court", "decisionDate": {"$gte": "2019-01-01"}}


# -- 4. GET /cases/{id} -------------------------------------------------------


def test_get_case(make_client, envelope):
    client, mock_request = make_client()
    body = envelope(
        data={
            "id": "64f0abc",
            "caseNumber": "123/2021",
            "title": "State v. X",
            "court": "Delhi High Court",
            "caseType": "Criminal Appeal",
            "judges": ["JUSTICE A"],
            "petitioners": ["State"],
            "respondents": ["X"],
            "decisionDate": "2021-05-01",
            "disposalNature": "Dismissed",
            "summary": "...",
            "hasDocuments": True,
            "documentCount": 3,
            "hasAnalysis": False,
        },
        meta={"responseTime": "5ms", "note": "Use /cases/:id/analysis endpoint to get AI analysis separately"},
    )
    mock_request.return_value = FakeResponse(200, body)

    result = client.get_case("64f0abc")

    assert result.data["caseNumber"] == "123/2021"
    assert "detailedSummary" not in result.data
    method, url = mock_request.call_args.args
    assert method == "GET"
    assert url.endswith("/cases/64f0abc")


# -- 5. GET /cases/{id}/analysis ----------------------------------------------


def test_get_case_analysis_when_missing(make_client, envelope):
    client, mock_request = make_client()
    body = envelope(
        data={"id": "1", "caseNumber": "123/2021", "hasAnalysis": False, "message": "AI analysis not available for this case"},
        meta={"responseTime": "2ms", "note": "Use POST /cases/:id/analyze to generate AI analysis"},
    )
    mock_request.return_value = FakeResponse(200, body)

    result = client.get_case_analysis("1")

    assert result.data["hasAnalysis"] is False
    assert "analysis" not in result.data


def test_get_case_analysis_when_present(make_client, envelope):
    client, mock_request = make_client()
    body = envelope(
        data={
            "id": "1",
            "caseNumber": "123/2021",
            "hasAnalysis": True,
            "analysis": {
                "summary": "...",
                "keyFacts": ["fact 1"],
                "issues": [{"question": "Was X liable?", "holding": "Yes"}],
                "citedCases": {"followed": ["A v B"]},
                "arguments": {"petitioner": ["arg 1"]},
                "practiceAreas": ["Criminal"],
                "legalPrinciples": ["principle 1"],
            },
        },
        meta={"responseTime": "2ms", "note": ""},
    )
    mock_request.return_value = FakeResponse(200, body)

    result = client.get_case_analysis("1")

    assert result.data["hasAnalysis"] is True
    assert result.data["analysis"]["issues"][0]["holding"] == "Yes"
    method, url = mock_request.call_args.args
    assert url.endswith("/cases/1/analysis")


# -- 6. GET /cases/{id}/related -----------------------------------------------


def test_get_related_with_documents(make_client, envelope):
    client, mock_request = make_client()
    body = envelope(
        data={
            "relatedDocuments": [
                {"id": "1", "title": "Order 1", "caseNumber": "123/2021", "court": "Delhi High Court", "decisionDate": "2021-01-01", "caseType": "CRL", "isCurrent": True}
            ],
            "timeline": [{"date": "2021-01-01", "status": "Case Initiated", "statusLabel": "Case Initiated", "documentId": "1"}],
        },
        meta={"responseTime": "3ms", "caseNumber": "123/2021", "totalDocuments": 1, "timelineEvents": 1},
    )
    mock_request.return_value = FakeResponse(200, body)

    result = client.get_related("1")

    assert result.data["relatedDocuments"][0]["isCurrent"] is True
    assert result.data["timeline"][0]["status"] == "Case Initiated"
    assert result.meta["totalDocuments"] == 1


def test_get_related_without_case_number(make_client, envelope):
    client, mock_request = make_client()
    body = envelope(
        data={"relatedDocuments": [], "timeline": []},
        meta={"responseTime": "1ms", "message": "No case number found for this case"},
    )
    mock_request.return_value = FakeResponse(200, body)

    result = client.get_related("1")

    assert result.data["relatedDocuments"] == []
    assert result.meta["message"] == "No case number found for this case"


# -- 7. GET /cases/{id}/pdf ----------------------------------------------------


def test_get_case_pdf(make_client, envelope):
    client, mock_request = make_client()
    body = envelope(
        data={"pdfUrl": "ENCRYPTED_CIPHERTEXT", "expiresIn": 3600, "caseId": "1", "caseNumber": "123/2021", "caseTitle": "State v. X"},
        meta={"responseTime": "2ms", "note": "The PDF URL is encrypted and expires in 1 hour. Use the decryption key provided in your SDK."},
    )
    mock_request.return_value = FakeResponse(200, body)

    result = client.get_case_pdf("1")

    assert result.data["expiresIn"] == 3600
    assert result.data["pdfUrl"] == "ENCRYPTED_CIPHERTEXT"
    method, url = mock_request.call_args.args
    assert url.endswith("/cases/1/pdf")


# -- 8. POST /cases/{id}/analyze -----------------------------------------------


def test_analyze_case_started(make_client, envelope):
    client, mock_request = make_client()
    body = envelope(
        data={"message": "Analysis has been started", "status": "processing"},
        meta={"responseTime": "1ms", "note": "You can check the analysis status by calling the GET /cases/:id endpoint in 30-60 seconds."},
    )
    mock_request.return_value = FakeResponse(202, body)

    result = client.analyze_case("1")

    assert result.data["status"] == "processing"
    sent_body = mock_request.call_args.kwargs["json"]
    assert sent_body == {"force": False}


def test_analyze_case_already_exists(make_client, envelope):
    client, mock_request = make_client()
    body = envelope(
        data={"message": "Analysis already exists", "analysis": {"summary": "..."}, "alreadyExists": True},
        meta={"responseTime": "1ms", "note": ""},
    )
    mock_request.return_value = FakeResponse(200, body)

    result = client.analyze_case("1", force=False)

    assert result.data["alreadyExists"] is True


def test_analyze_case_force(make_client, envelope):
    client, mock_request = make_client()
    body = envelope(data={"message": "Analysis has been started", "status": "processing"}, meta={"responseTime": "1ms", "note": ""})
    mock_request.return_value = FakeResponse(202, body)

    client.analyze_case("1", force=True)

    sent_body = mock_request.call_args.kwargs["json"]
    assert sent_body == {"force": True}


# -- 9. POST /cases/{id}/analyze-consolidated ----------------------------------


def test_analyze_consolidated_success(make_client, envelope):
    client, mock_request = make_client()
    body = envelope(
        data={
            "status": "success",
            "consolidatedAnalysis": {"summary": "...", "benchComposition": "Division Bench", "opinionType": "Majority"},
            "message": "Consolidated analysis complete",
        },
        meta={"responseTime": "12000ms", "relatedCases": 5},
    )
    mock_request.return_value = FakeResponse(200, body)

    result = client.analyze_consolidated("1")

    assert result.data["status"] == "success"
    assert result.data["consolidatedAnalysis"]["benchComposition"] == "Division Bench"
    assert result.meta["relatedCases"] == 5
    method, url = mock_request.call_args.args
    assert url.endswith("/cases/1/analyze-consolidated")


def test_analyze_consolidated_already_analyzed(make_client, envelope):
    client, mock_request = make_client()
    body = envelope(
        data={"status": "already_analyzed", "consolidatedAnalysis": {"summary": "..."}, "message": "Consolidated analysis already exists"},
        meta={"responseTime": "3ms"},
    )
    mock_request.return_value = FakeResponse(200, body)

    result = client.analyze_consolidated("1", force=False)

    assert result.data["status"] == "already_analyzed"
    assert "relatedCases" not in result.meta


# -- 10. POST /request-timeline -------------------------------------------------


def test_request_timeline_pending(make_client, envelope):
    client, mock_request = make_client()
    body = envelope(data={"requestId": "job-1", "status": "pending"}, meta={"responseTime": "2ms"})
    mock_request.return_value = FakeResponse(200, body)

    result = client.request_timeline("64f0abc0000000000000001")

    assert result.data["status"] == "pending"
    sent_body = mock_request.call_args.kwargs["json"]
    assert sent_body == {"case_id": "64f0abc0000000000000001"}


def test_request_timeline_supreme_court_case(make_client, envelope):
    client, mock_request = make_client()
    body = envelope(
        data={
            "requestId": "64f0abc0000000000000001",
            "status": "completed",
            "orderCount": 0,
            "orders": [],
            "message": "Supreme Court cases do not have separate orders. ...",
        },
        meta={"responseTime": "1ms"},
    )
    mock_request.return_value = FakeResponse(200, body)

    result = client.request_timeline("64f0abc0000000000000001")

    assert result.data["orderCount"] == 0
    assert result.data["orders"] == []


def test_request_timeline_cached(make_client, envelope):
    client, mock_request = make_client()
    body = envelope(
        data={"requestId": "job-1", "status": "completed", "cached": True, "orderCount": 2, "orders": [{"_id": "o1"}, {"_id": "o2"}]},
        meta={"responseTime": "1ms"},
    )
    mock_request.return_value = FakeResponse(200, body)

    result = client.request_timeline("64f0abc0000000000000001")

    assert result.data["cached"] is True
    assert len(result.data["orders"]) == 2


# -- 11. GET /get-timeline/{requestId} -------------------------------------------


def test_get_timeline_in_progress(make_client, envelope):
    client, mock_request = make_client()
    body = envelope(
        data={"requestId": "job-1", "status": "pending", "createdAt": "2026-08-10T09:00:00.000Z", "updatedAt": "2026-08-10T09:00:00.000Z"},
        meta={"responseTime": "2ms"},
    )
    mock_request.return_value = FakeResponse(200, body)

    result = client.get_timeline("job-1")

    assert result.data["status"] == "pending"
    method, url = mock_request.call_args.args
    assert url.endswith("/get-timeline/job-1")


def test_get_timeline_completed_omits_result_when_total_order_count_present(make_client, envelope):
    client, mock_request = make_client()
    body = envelope(
        data={
            "requestId": "job-1",
            "status": "completed",
            "createdAt": "2026-08-10T09:00:00.000Z",
            "updatedAt": "2026-08-10T09:05:00.000Z",
            "startedAt": "2026-08-10T09:00:01.000Z",
            "completedAt": "2026-08-10T09:05:00.000Z",
            "orders": [{"_id": "o1"}],
            "orderCount": 1,
            "totalOrderCount": 1,
        },
        meta={"responseTime": "2ms"},
    )
    mock_request.return_value = FakeResponse(200, body)

    result = client.get_timeline("job-1")

    assert "result" not in result.data
    assert result.data["totalOrderCount"] == 1


# -- 12. GET /health -------------------------------------------------------------


def test_health_is_not_enveloped(make_client):
    client, mock_request = make_client()
    body = {"success": True, "status": "healthy", "version": "1.0.0", "timestamp": "2026-08-10T09:00:00.000Z"}
    mock_request.return_value = FakeResponse(200, body)

    result = client.health()

    assert result == body
    assert result["status"] == "healthy"
    method, url = mock_request.call_args.args
    assert method == "GET"
    assert url.endswith("/health")
    headers = mock_request.call_args.kwargs["headers"]
    assert "Authorization" not in headers
    assert "X-API-Key" not in headers


# -- 13. POST /party/screen -------------------------------------------------------


def test_screen_party_sends_required_and_optional_fields(make_client, envelope):
    client, mock_request = make_client()
    body = envelope(
        data={
            "query": {"name": "Acme Textiles Pvt Ltd", "entityType": "company"},
            "summary": {
                "matchCount": 1,
                "byBand": {"confirmed": 1, "probable": 0, "possible": 0, "unlikely": 0},
                "highestBand": "confirmed",
                "verdict": "matches_found",
            },
            "matches": [
                {
                    "caseId": "abc123",
                    "title": "Acme Textiles Pvt Ltd v. State",
                    "court": "Delhi High Court",
                    "petitioners": ["Acme Textiles Pvt Ltd"],
                    "respondents": ["State"],
                    "partyRole": "petitioner",
                    "confidence": {"band": "confirmed", "score": 0.94, "calibrated": 0.96, "engine": "deterministic"},
                    "evidence": {
                        "entityMatch": True,
                        "matchedFields": ["name", "gstin"],
                        "strategies": ["exact", "fuzzy"],
                        "signals": [{"name": "gstin_match", "status": "matched", "weight": 0.6, "evidence": "07AAAAA0000A1Z5"}],
                        "nameSimilarity": 0.98,
                        "disambiguatorPresent": True,
                    },
                    "rationale": "GSTIN and name both match.",
                    "casePageUrl": "https://research.courtmesh.ai/case/abc123",
                }
            ],
            "relatedButUnverified": [],
            "coverage": {
                "exhaustive": True,
                "exhaustiveWithinFilters": True,
                "planClamped": False,
                "anyStrategyErrored": False,
                "strategiesRun": ["exact", "fuzzy"],
                "someRecordsWithheld": False,
                "candidatesEvaluated": 12,
                "adjudicationsRun": 0,
            },
            "notice": "Results are public court records. See the case removal policy for takedown requests.",
        },
        meta={"creditsCharged": 100, "adjudicated": False, "corpusAsOf": "2026-09-17"},
    )
    mock_request.return_value = FakeResponse(200, body)

    result = client.screen_party(
        name="Acme Textiles Pvt Ltd",
        entityType="company",
        purpose="due_diligence",
        identifiers={"gstin": "07AAAAA0000A1Z5"},
        address={"city": "Delhi", "state": "Delhi", "stateCode": "DL"},
        limit=40,
        adjudicate=True,
    )

    assert result.data["summary"]["verdict"] == "matches_found"
    assert result.data["matches"][0]["confidence"]["band"] == "confirmed"
    assert result.data["coverage"]["exhaustive"] is True
    assert result.meta["creditsCharged"] == 100

    method, url = mock_request.call_args.args
    assert method == "POST"
    assert url.endswith("/party/screen")
    sent_body = mock_request.call_args.kwargs["json"]
    assert sent_body["name"] == "Acme Textiles Pvt Ltd"
    assert sent_body["entityType"] == "company"
    assert sent_body["purpose"] == "due_diligence"
    assert sent_body["identifiers"] == {"gstin": "07AAAAA0000A1Z5"}
    assert sent_body["adjudicate"] is True


def test_screen_party_no_matches_omits_unset_optional_fields(make_client, envelope):
    client, mock_request = make_client()
    body = envelope(
        data={
            "query": {"name": "A Very Uncommon Name"},
            "summary": {
                "matchCount": 0,
                "byBand": {"confirmed": 0, "probable": 0, "possible": 0, "unlikely": 0},
                "highestBand": None,
                "verdict": "no_matches_found",
            },
            "matches": [],
            "relatedButUnverified": [],
            "coverage": {
                "exhaustive": True,
                "exhaustiveWithinFilters": True,
                "planClamped": False,
                "anyStrategyErrored": False,
                "strategiesRun": ["exact", "fuzzy"],
                "someRecordsWithheld": False,
                "candidatesEvaluated": 0,
                "adjudicationsRun": 0,
            },
            "notice": "Results are public court records.",
        },
        meta={"creditsCharged": 20, "adjudicated": False, "corpusAsOf": "2026-09-17"},
    )
    mock_request.return_value = FakeResponse(200, body)

    result = client.screen_party(name="A Very Uncommon Name", entityType="person", purpose="kyc")

    assert result.data["summary"]["verdict"] == "no_matches_found"
    assert result.meta["creditsCharged"] == 20
    sent_body = mock_request.call_args.kwargs["json"]
    assert sent_body == {"name": "A Very Uncommon Name", "entityType": "person", "purpose": "kyc"}


# -- 14. GET /coverage -------------------------------------------------------------


def test_get_coverage_unwraps_snapshot_and_sends_api_key(make_client, envelope):
    client, mock_request = make_client()
    body = envelope(
        data={
            "generatedAt": "2026-09-18T00:00:00.000Z",
            "index": "courtmesh_cases_v3",
            "total": 315_600_000,
            "documentBearing": 12_000_000,
            "statusOnly": 303_600_000,
            "byCourtType": [{"courtType": "High Court", "records": 40_000_000, "documentBearing": 8_000_000, "latestDecisionDate": "2026-09-17"}],
            "byYear": [{"year": 2026, "records": 1_200_000}],
            "courts": [
                {
                    "court": "Delhi High Court",
                    "courtType": "High Court",
                    "records": 2_000_000,
                    "documentBearing": 500_000,
                    "earliestDecisionDate": "1950-01-01",
                    "latestDecisionDate": "2026-09-17",
                    "businessDaysBehind": 1,
                }
            ],
            "districtCourts": {"records": 300_000_000, "documentBearing": 1_000_000, "latestDecisionDate": "2026-09-16", "businessDaysBehind": 2},
        },
        meta={"generatedAt": "2026-09-18T00:00:00.000Z", "cacheTtlSeconds": 21600, "corpusNote": "Counted 2026-09-18."},
    )
    mock_request.return_value = FakeResponse(200, body)

    result = client.get_coverage()

    assert result.data["total"] == 315_600_000
    assert result.data["districtCourts"]["records"] == 300_000_000
    assert result.meta["cacheTtlSeconds"] == 21600

    method, url = mock_request.call_args.args
    assert method == "GET"
    assert url.endswith("/coverage")
    headers = mock_request.call_args.kwargs["headers"]
    # No API key is required by the server for this endpoint, but the
    # client always has one (the constructor requires it) and sends it
    # anyway.
    assert headers.get("Authorization", "").startswith("Bearer ")


# -- 15. GET /usage -----------------------------------------------------------


def test_get_usage_unwraps_tier_balance_and_by_endpoint(make_client, envelope):
    client, mock_request = make_client()
    body = envelope(
        data={
            "tier": "payg",
            "walletOwner": {"type": "user", "id": "u1"},
            "balance": {"total": 5000, "monthlyGrant": 0, "signupGrant": 1000, "purchased": 4000},
            "limits": {"requestsPerMinute": 60, "partyScreensPerMonth": 100},
            "period": {"start": "2026-09-01T00:00:00.000Z", "end": "2026-09-30T18:29:59.999Z", "key": "2026-09"},
            "creditsUsedThisPeriod": 340,
            "byEndpoint": [{"endpoint": "/api/v1/prod/search/cases", "calls": 12, "credits": 12}],
            "subscriptionRenewsAt": None,
        },
        meta={"requestId": "req-usage-1"},
    )
    mock_request.return_value = FakeResponse(200, body)

    result = client.get_usage()

    assert result.data["tier"] == "payg"
    assert result.data["balance"]["total"] == 5000
    assert result.data["byEndpoint"][0]["calls"] == 12
    assert result.meta["requestId"] == "req-usage-1"
    method, url = mock_request.call_args.args
    assert method == "GET"
    assert url.endswith("/usage")


# -- 16. GET /health?deep=1 ----------------------------------------------------


def test_health_deep_sends_deep_query_param(make_client):
    client, mock_request = make_client()
    body = {
        "success": True,
        "status": "degraded",
        "version": "1.0.0",
        "commit": "abc123",
        "checks": {"mongo": {"status": "ok", "latencyMs": 12}, "opensearch": {"status": "degraded", "latencyMs": 900}},
        "timestamp": "2026-09-18T00:00:00.000Z",
    }
    mock_request.return_value = FakeResponse(200, body)

    result = client.health(deep=True)

    assert result["status"] == "degraded"
    assert result["checks"]["opensearch"]["status"] == "degraded"
    params = mock_request.call_args.kwargs["params"]
    assert params == {"deep": "1"}


def test_health_plain_sends_no_query_param(make_client):
    client, mock_request = make_client()
    body = {"success": True, "status": "healthy", "version": "1.0.0", "timestamp": "2026-09-18T00:00:00.000Z"}
    mock_request.return_value = FakeResponse(200, body)

    client.health()

    params = mock_request.call_args.kwargs["params"]
    assert params is None


# -- 17. GET /me ----------------------------------------------------------------


def test_me_unwraps_account_identity(make_client, envelope):
    client, mock_request = make_client()
    body = envelope(data={"userId": "u1", "email": "a@b.com", "name": "A B", "role": "ORG_ADMIN", "organizationId": "org1"})
    mock_request.return_value = FakeResponse(200, body)

    result = client.me()

    assert result.data["userId"] == "u1"
    assert result.data["organizationId"] == "org1"
    method, url = mock_request.call_args.args
    assert url.endswith("/me")
    headers = mock_request.call_args.kwargs["headers"]
    assert headers.get("Authorization", "").startswith("Bearer ")


# -- 18. GET /audit -------------------------------------------------------------


def test_audit_sends_query_params_and_unwraps_hits(make_client):
    client, mock_request = make_client()
    body = {
        "success": True,
        "data": {
            "hits": [{"id": "h1", "endpoint": "/api/v1/prod/search/cases", "method": "POST", "statusCode": 200, "responseTime": 120, "createdAt": "2026-09-18T00:00:00.000Z"}],
            "summary": {"totalHits": 1, "totalAiAnalysisHits": 0, "avgResponseTime": 120, "successfulHits": 1, "successRate": "100.0", "totalCreditsDeducted": 1},
            "topEndpoints": [{"endpoint": "/api/v1/prod/search/cases", "count": 1}],
        },
        "pagination": {"total": 1, "limit": 50, "offset": 0, "hasMore": False},
    }
    mock_request.return_value = FakeResponse(200, body)

    result = client.audit(userId="u1", limit=50, offset=0)

    assert len(result.data["hits"]) == 1
    assert result.data["summary"]["successRate"] == "100.0"
    assert result.pagination["total"] == 1
    method, url = mock_request.call_args.args
    assert url.endswith("/audit")
    params = mock_request.call_args.kwargs["params"]
    assert params == {"userId": "u1", "limit": 50, "offset": 0}


# -- 19. GET /reference/courts --------------------------------------------------


def test_reference_courts_unwraps_hierarchy_without_requiring_auth(make_client):
    client, mock_request = make_client()
    body = {
        "success": True,
        "data": {
            "courtTypes": ["Supreme Court", "High Court", "District Court", "Tribunal"],
            "courtsByType": {"High Court": ["Delhi High Court"]},
            "courtNamesByCourt": {"Delhi High Court": ["High Court of Delhi"]},
        },
    }
    mock_request.return_value = FakeResponse(200, body)

    result = client.reference_courts()

    assert "High Court" in result.data["courtTypes"]
    assert "Delhi High Court" in result.data["courtsByType"]["High Court"]
    headers = mock_request.call_args.kwargs["headers"]
    assert "Authorization" not in headers


# -- 20. GET /reference/case-types ----------------------------------------------


def test_reference_case_types_unwraps_flattened_list(make_client):
    client, mock_request = make_client()
    body = {"success": True, "data": [{"code": "CRL.A", "fullForm": "Criminal Appeal", "primaryType": "Criminal", "nature": "Appellate"}]}
    mock_request.return_value = FakeResponse(200, body)

    result = client.reference_case_types()

    assert result.data[0]["code"] == "CRL.A"


# -- 21. POST /party/screen/batch ------------------------------------------------


def test_screen_party_batch_sends_items_and_unwraps_per_item_results(make_client, envelope):
    client, mock_request = make_client()
    body = envelope(
        data={
            "results": [
                {
                    "clientRef": "row-1",
                    "index": 0,
                    "ok": True,
                    "screen": {
                        "query": {"name": "Acme Textiles Pvt Ltd", "entityType": "company", "purpose": "due_diligence"},
                        "summary": {"matchCount": 0, "byBand": {"confirmed": 0, "probable": 0, "possible": 0, "unlikely": 0}, "highestBand": None, "verdict": "no_matches_found"},
                        "matches": [],
                        "relatedButUnverified": [],
                        "coverage": {"exhaustive": True, "exhaustiveWithinFilters": True, "planClamped": False, "anyStrategyErrored": False, "strategiesRun": ["exact"], "someRecordsWithheld": False},
                        "adjudicationsRun": 0,
                        "notice": "Results are public court records.",
                    },
                },
                {"clientRef": "row-2", "index": 1, "ok": False, "error": {"code": "VALIDATION_ERROR", "message": "name must be 2..200 characters"}},
            ],
            "summary": {"items": 2, "matchesFound": 0, "noMatches": 1, "inconclusive": 0, "errors": 1},
        },
        meta={"creditsCharged": 20, "requestId": "req-batch-1"},
    )
    mock_request.return_value = FakeResponse(200, body)

    result = client.screen_party_batch(
        items=[
            {"clientRef": "row-1", "name": "Acme Textiles Pvt Ltd", "entityType": "company"},
            {"clientRef": "row-2", "name": "A"},
        ],
        purpose="due_diligence",
    )

    assert result.data["summary"]["items"] == 2
    assert result.data["results"][0]["ok"] is True
    assert result.data["results"][1]["ok"] is False
    assert result.data["results"][1]["error"]["code"] == "VALIDATION_ERROR"
    assert result.meta["creditsCharged"] == 20
    method, url = mock_request.call_args.args
    assert method == "POST"
    assert url.endswith("/party/screen/batch")
    sent_body = mock_request.call_args.kwargs["json"]
    assert sent_body["purpose"] == "due_diligence"
    assert len(sent_body["items"]) == 2
