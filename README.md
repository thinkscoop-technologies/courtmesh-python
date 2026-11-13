# courtmesh

Python SDK for the CourtMesh API: search Indian case law, fetch
case details and AI analysis, request document timelines, and more.

This SDK is generated directly from the CourtMesh server source. It does not
invent request or response fields, every field documented below is real. A
few real server quirks are documented explicitly rather than hidden, see
"Caveats" at the end.

## Install

```bash
pip install courtmesh
```

Requires Python 3.9 or newer. Or, from a local checkout:

```bash
pip install -e ".[test]"
```

## Quickstart

```python
from courtmesh import CourtMesh

with CourtMesh(api_key="cm-your-api-key-here") as cm:
    result = cm.search_cases(query="right to privacy")
    for hit in result.data:
        print(hit.get("title"))
```

## Auth

Every endpoint except `GET /health` requires an API key. The server accepts
two header forms, checked in this order:

1. `X-API-Key: <key>`
2. `Authorization: Bearer <key>`

The SDK defaults to the `Authorization: Bearer <key>` form. Pass the API key
directly, or set the `COURTMESH_API_KEY` environment variable:

```python
from courtmesh import CourtMesh

# explicit key, Authorization: Bearer header
cm = CourtMesh(api_key="cm-your-api-key-here")

# or read from COURTMESH_API_KEY
import os
os.environ["COURTMESH_API_KEY"] = "cm-your-api-key-here"
cm = CourtMesh()

# use the X-API-Key header instead of Authorization: Bearer
cm = CourtMesh(api_key="cm-your-api-key-here", auth_header="x-api-key")
```

`base_url` defaults to `https://research.courtmesh.ai/api/v1/prod` and can
be overridden, for example to point at a staging environment:

```python
cm = CourtMesh(api_key="...", base_url="https://staging.example.com/api/v1/prod")
```

You can also supply your own `requests.Session` (for custom TLS settings,
proxies or connection pooling) and use the client as a context manager so
the session is closed automatically:

```python
import requests
from courtmesh import CourtMesh

session = requests.Session()
with CourtMesh(
    api_key="...",
    session=session,
    timeout=60,              # per request default; per endpoint defaults and per call
                             # overrides both take priority, see Timeouts below
    max_retries=5,
    retry_posts=False,      # default, see Retries below
    max_retry_after_seconds=60,  # default cap on how long a 429 is retried automatically
) as cm:
    health = cm.health()
    print(health["status"])
```

A client side timeout does not cancel the request server side and never
triggers a refund: the call may still complete (and be billed) after the
SDK has already raised `RequestTimeoutError`.

## Rate limits

Per key requests-per-minute, requests-per-day and requests-per-month
ceilings apply, and vary by tier (Free is the tightest, Enterprise the
widest). Requests over one of them get HTTP 429 with `code: "RATE_LIMITED"`
and a `retryAfter` value in seconds. The SDK retries a `RATE_LIMITED` 429
automatically (see "Retries" below), so in normal use you will not see
`RateLimitError` unless `max_retries` is exhausted or the advertised delay
exceeds `max_retry_after_seconds`. Response headers `X-RateLimit-Limit`,
`X-RateLimit-Remaining` and `X-RateLimit-Reset` are available on
`cm.session` if you inspect responses yourself, though the SDK's typed
methods do not currently surface them.

## Endpoint examples

### 1. `search_judges`, `GET /judges/search`

```python
result = cm.search_judges("khanna")
print(result.data)          # ["JUSTICE A B", ...], at most 50 names
print(result.meta)          # {"query": "khanna", "responseTime": "3ms", "totalMatches": 12}
```

### 2. `search_cases`, `POST /search/cases`

Keyword search across Indian court records. `caseNumber` is applied server
side (one value; a list's first element is used). `sortBy` accepts
`"relevance"`, `"recent"` or `"oldest"`, plus the deprecated alias `"date"`
(resolved to `"recent"`, with a note in `result.meta["warnings"]`).

```python
result = cm.search_cases(
    query="motor accident compensation",
    court="Delhi High Court",
    year=2022,
    caseType="MAC APP",
    judgeName="Justice X",
    fromDate="2022-01-01",
    toDate="2022-12-31",
    page=1,
    limit=20,
    sortBy="recent",
)
print(result.data)         # list of raw search hits (id, score, optional highlights;
                            # _id/_score kept for legacy)
print(result.meta)         # {"query": ..., "filters": {...}, "sortBy": ..., "responseTime": ...}
print(result.pagination)   # {"total": ..., "hasMore": ..., "page": ..., "limit": ..., "nextCursor": ...}
```

Paging past the first screen: pass the previous page's
`result.pagination["nextCursor"]` back as `cursor` (a signed, opaque string); an invalid or query-mismatched cursor raises
`ValidationError` with `code == "CURSOR_INVALID"`. `iter_search_cases` (see
Pagination below) does this for you, including the legacy list-shaped
`nextCursor`.

### 3. `semantic_search`, `POST /search/cases/semantic`

AI search by meaning, billed as an AI interaction. **Not available on the Free
tier**: raises `PermissionDeniedError` with `code == "SEMANTIC_NOT_ALLOWED"`
before any work or charge. The top level filter fields, whatever the
query's natural language implies, and the `filters` object are all merged,
weakest first in that order; `filters` (the AI search's own filter keys)
always wins on overlap.

```python
result = cm.semantic_search(
    query="landmark judgment on the right to privacy",
    court="Supreme Court",  # merged in, but filters below wins if both set the same key
    filters={"court": "Supreme Court", "decisionDate": {"$gte": "2015-01-01"}},
    limit=10,
)
for item in result.data:
    print(item["title"], item["similarity"])
print(result.meta.get("someRecordsWithheld"), result.meta.get("restrictedCheckDegraded"))
```

`caseNumber` and `judgeName` (also `judges`/`judge`, mapped to the same
field) are narrower here than on `search_cases`: AI search filters
case numbers numerically, so `caseNumber` must be a digits only string
(`cm.semantic_search(..., caseNumber="1234")`, raises `ValueError`
otherwise), and it matches a single judge name, so `judgeName` accepts one
string, not a list.

### 4. `get_case`, `GET /cases/{id}`

```python
result = cm.get_case("64f0abc123...")     # 24 character hexadecimal case id or caseNumber
print(result.data["title"], result.data["caseNumber"])
```

### 5. `get_case_analysis`, `GET /cases/{id}/analysis`

```python
result = cm.get_case_analysis("64f0abc123...")
if result.data["hasAnalysis"]:
    print(result.data["analysis"]["summary"])
else:
    print(result.data["message"])
```

### 6. `get_related`, `GET /cases/{id}/related`

```python
result = cm.get_related("64f0abc123...")
for doc in result.data["relatedDocuments"]:
    print(doc["title"], doc["decisionDate"], doc["isCurrent"])
for event in result.data["timeline"]:
    print(event["date"], event["status"])
```

### 7. `get_case_pdf`, `GET /cases/{id}/pdf`

```python
result = cm.get_case_pdf("64f0abc123...")
print(result.data["pdfUrl"])       # a fetchable link, valid for result.data["expiresIn"] seconds
```

Note: `pdfUrl` is a directly fetchable HTTPS link on the CourtMesh API host.
It carries its own short lived signed token, so it needs no API key and no
decryption, and fetching it costs no credits. Failure codes: `CASE_NOT_FOUND` (404), `CASE_RESTRICTED` (403),
`PDF_NOT_STORED` (404, no stored document; `request_timeline` with
`refresh=True` may fetch one for High Court and District Court cases).

### 8. `analyze_case`, `POST /cases/{id}/analyze`

Asynchronous, 202 Accepted. Poll `get_case` (or `get_case_analysis`) a bit
later. Costs 100 credits (reduced from 150), plus a surcharge when
`allow_remote_fetch` triggers an external fetch. **Not available on the
Free tier**: `analyze_case`, `analyze_consolidated` and `get_case_analysis`
all raise `PermissionDeniedError` with `code == "API_TIER_NOT_ALLOWED"` and
`response_body["upgradeUrl"]` for Free tier keys, before any work is done
or any credit is charged.

```python
result = cm.analyze_case("64f0abc123...")
print(result.data["status"])       # "processing"

# force re-analysis even if one exists
result = cm.analyze_case("64f0abc123...", force=True)

# a case with no stored document can only be analyzed by fetching it from an
# external URL. Not on the Free tier, and the host must be on the server's
# allowlist - either violation raises PermissionDeniedError with
# code == "REMOTE_FETCH_NOT_ALLOWED".
result = cm.analyze_case("64f0abc123...", allow_remote_fetch=True)
```

### 9. `analyze_consolidated`, `POST /cases/{id}/analyze-consolidated`

Synchronous and slow (up to 300s by default, see Timeouts below), analyses
the case plus related documents.

```python
result = cm.analyze_consolidated("64f0abc123...")
print(result.data["status"])                       # "success" or "already_analyzed"
print(result.data["consolidatedAnalysis"]["summary"])
```

### 10. `request_timeline`, `POST /request-timeline`

`case_id` must be the 24 character hexadecimal case id. `refresh=True` forces a live
court-portal fetch instead of serving the last stored read. Both cost 1
credit, and `result.meta["liveFetch"]` says which one actually happened;
`result.data.get("liveFetchSupported")` comes back `False` when the case's
court has no live refresh at all. Not available on the Free tier
(`PermissionDeniedError`, `code == "LIVE_FETCH_NOT_ALLOWED"`) and capped
per day per tier (`RateLimitError`, `code == "LIVE_FETCH_LIMIT_REACHED"`).

```python
result = cm.request_timeline("64f0abc123456789abcdef01")
print(result.data["requestId"], result.data["status"], result.meta["liveFetch"])

# Force a live fetch instead of serving the cached read.
refreshed = cm.request_timeline("64f0abc123456789abcdef01", refresh=True)
print(refreshed.meta["liveFetch"], refreshed.data.get("liveFetchSupported"))
```

### 11. `get_timeline`, `GET /get-timeline/{requestId}`

```python
job = cm.get_timeline(result.data["requestId"])
print(job.data["status"])
if job.data["status"] == "completed":
    print(job.data.get("orders"))
```

### 12. `health`, `GET /health`

No auth required. Unlike every other endpoint, the response
is not wrapped in `data`.

```python
health = cm.health()
print(health["status"], health["version"])
```

### 13. `screen_party`, `POST /party/screen`

Screens a person or company name against the case law corpus for litigation, insolvency and other court records. Requires an API key. Costs 100 credits when matches are found, 20 when none are, plus a flat surcharge only when `result.data["adjudicationsRun"] > 0`; requesting `adjudicate=True` does not by itself guarantee a model call happened (every candidate may already have been decided deterministically), so it does not by itself bill the surcharge either. `adjudicate=True` is not available on the Free tier (`PermissionDeniedError`, `code == "API_TIER_NOT_ALLOWED"`).

```python
result = cm.screen_party(
    name="Acme Textiles Pvt Ltd",
    entityType="company",
    purpose="due_diligence",
    identifiers={"gstin": "07AAAAA0000A1Z5"},
    address={"city": "Delhi", "state": "Delhi", "stateCode": "DL"},
    limit=40,
    adjudicate=True,
)

print(result.data["summary"]["verdict"])   # "matches_found" | "no_matches_found" | "inconclusive"
for match in result.data["matches"]:
    print(match["title"], match["confidence"]["band"], match["confidence"]["engine"], match.get("casePageUrl"))
print(result.data["coverage"]["exhaustive"], result.data["coverage"]["someRecordsWithheld"], result.data["adjudicationsRun"])
print(result.meta["creditsCharged"], result.meta["adjudicated"])
```

Verdict semantics: `matches_found` describes what was found internally, independent of `displayThreshold`; raising the threshold can leave `matches` empty (`summary["matchCount"] == 0`) while the verdict is still `matches_found`. `since` forces `inconclusive` (it is a best-effort filter, so completeness can never be certified either way). `no_matches_found` is only ever returned when `coverage["exhaustive"]` is `True` and nothing was withheld.

**DPDP note.** `purpose` is required on every call and is the only thing about the query the server retains in its logs, `name`, `aliases`, `knownPersons`, `identifiers` and `address` are never logged. The results are drawn entirely from public court records, they are not sourced from or cross-checked against any private database. **A screen is not an identity check**: it tells you whether a name (optionally narrowed by identifiers, address or known associates) appears in litigation or insolvency records, it does not verify who a person or company actually is. `result.data["notice"]` links the case removal / takedown policy; `result.data["coverage"]["someRecordsWithheld"]` is `True` when one or more otherwise-matching cases were removed from the results because they are under a takedown order.

### 14. `get_coverage`, `GET /coverage`

Corpus coverage and freshness stats: totals, by court type, by year, per court, and a rolled up District Courts row. No API key is required by the server for this endpoint, but this client always has one (the constructor requires it) and sends it along anyway. Server side cached for up to 6 hours.

```python
result = cm.get_coverage()
print(result.data["total"])
for court in result.data["courts"]:
    print(court["court"], court["records"], court.get("latestDecisionDate"), court.get("businessDaysBehind"))
print(result.data["districtCourts"].get("records"))
```

Most fields are optional (use `.get(...)` rather than `[...]`), since a court or year row may not report every stat.

## Party profile

`build_party_profile` takes the same fields as `screen_party` and returns the cases grouped into identities: the primary identity in full (court, bench, status, next hearing, acts and FIR as the court record states them, documents with links, and a summary built by code), and every other group under `possibleOtherPeople` for you to judge. Not available on the Free tier.

The server defaults to full mode where it is available, so pass `mode` when you need one answer shape.

```python
# Quick mode: one answer.
profile = cm.build_party_profile(
    name="Acme Example Traders Private Limited",
    entityType="company",
    purpose="due_diligence",
    identifiers={"cin": "U00000ZZ2020PTC000000"},
    mode="quick",
)
print(profile.data["verdict"], profile.data["summary"])
for identity in profile.data["identities"]:
    for case in identity["cases"]:
        print(case["caseId"], case.get("court"), case["status"], case["confidence"])
print(profile.meta["creditsCharged"], profile.meta["creditsBreakdown"])

# Full mode: answers at once, the work runs behind it. Read it back for free.
accepted = cm.build_party_profile(
    name="Acme Example Traders Private Limited",
    entityType="company",
    purpose="due_diligence",
    mode="full",
    maxCredits=500,
)
status = cm.get_party_profile(accepted.data["requestId"])
print(status.data["status"], status.data.get("stage"), status.data["credits"]["charged"])
if status.data["status"] == "completed":
    print(status.data["result"]["partyAnalysis"])
```

Pricing, quick mode: at least 100 credits per profile, even when no case is found. Above that, 1 credit per internal search call (at most 24), 1 per case record read and 1 per documents listing that offers a document (at most 100 cases are enriched), plus each AI review call priced by its tokens and never above an 80 credit allowance. One call never costs more than 304 credits. The balance is checked against the most the call could cost before it runs.

Pricing, full mode: charged by usage, one stage at a time: the search stage at the quick rates, 1 credit per court refresh started (retries are free), each case analysis by its tokens (a short one is about 5 credits), each reused analysis at the price of reading a stored analysis, and the party analysis by its tokens. `maxCredits` (100 to 5000, default 1000 or your balance if lower) is the most a request may spend. Accepting a request and reading its status are free. At most 3 full profiles may be queued or running per account (`RateLimitError`, `code == "PARTY_PROFILE_TOO_MANY_ACTIVE"`). Where full mode is not available the call raises `ServiceUnavailableError` with `code == "PARTY_PROFILE_FULL_UNAVAILABLE"` and nothing is charged.

A document's `links["pdf"]` works for one hour without an API key. Receiving it is free; the first open is charged as one PDF call, later opens are free. Pass `webhook={"url": "https://..."}` with a full mode request to be told when it ends, and check deliveries with `verify_webhook_signature` using the `signingSecret` returned once in the 202 answer. A 503 whose charge outcome is unknown is never retried automatically: check `get_usage()` before sending the request again. Being a party to a case is not a finding against anyone.

## Deleting audit activity

`delete_audit_activity` permanently deletes this API key's own activity before a UTC time. **It cannot be undone.** Those calls are no longer listed by `audit()` and the request details kept with them are erased. Other keys on the account are not touched, and what you were charged stays on your invoices and usage totals. Needs the `account` scope; free.

```python
from datetime import datetime, timezone

result = cm.delete_audit_activity(datetime(2026, 11, 5, tzinfo=timezone.utc))
# or cm.delete_audit_activity("2026-11-05T00:00:00Z")
print(result.data["removed"], result.data["complete"])
while not result.data["complete"]:
    result = cm.delete_audit_activity("2026-11-05T00:00:00Z")
```

A naive `datetime` raises `ValueError` before anything is sent. This call is never retried automatically after a connection error, a timeout or a 502, 503 or 504, because the outcome is then unknown: check with `audit()`, then send it again if needed.

## Case depth and refresh by CNR

```python
# Hearing history and advocates, at no extra charge. Either can be None when we hold no such record.
record = cm.get_case(case_id, include=["hearings", "advocates"])

# The documents of a case, then the stored text of one. 2 credits when text comes back, free when it does not.
rows = cm.list_case_orders(case_id).data["documents"]
for row in rows:
    if row["textAvailable"]:
        print(cm.get_case_document_text(case_id, row["id"]).data["text"])
        break

# Refresh by CNR: answers at once. 1 credit when queued, 0 for every other status.
cm.refresh_case_by_cnr("ZZAB010000012024")
state = cm.get_case_refresh_state("ZZAB010000012024")  # free

# Up to 50 CNRs in one call, a status for each.
batch = cm.refresh_cases_batch(["ZZAB010000012024", "ZZAB010000022024"])
```

Not every order has readable text, and how many do varies by court and by age, so read `textAvailable` rather than assuming. Calls that return text count against a monthly allowance (`ORDER_TEXT_LIMIT_REACHED`). A refresh charged on acceptance is not refunded if the court fetch later fails.

## CNR lookup and case monitoring

Look a case up by CNR (any common spelling works), or watch a list of CNRs
and be told when something changes. Tracking is free within your plan's
watch cap; you pay only for reading the change feed (1 credit per non-empty
page of up to 100 events) and for CNR lookups (1 credit per record returned).

```python
import os
from courtmesh import CourtMesh, normalize_cnr

normalize_cnr("CNR: ZZAB-01-000001-2024")  # "ZZAB010000012024", or None if it cannot be a CNR

with CourtMesh(api_key=os.environ["COURTMESH_API_KEY"]) as cm:
    # One-off lookup. fetch=True starts a live fetch for a CNR we do not hold yet.
    # The starting call returns "pending" and is free; poll the same call (same CNR) until "found".
    # A CNR we do not hold and did not fetch raises NotFoundError (CASE_NOT_FOUND). So does fetch=True
    # for a CNR the court portal had nothing for in the last 24 hours: it is not asked again until that passes.
    lookup = cm.get_case_by_cnr("ZZAB010000012024", fetch=True)
    print(lookup.data["status"])  # "found" | "pending"

    # 1. Watch a CNR.
    wl = cm.create_watchlist(
        "Loan book",
        items=[{"cnr": "ZZAB010000012024", "reference": "LOAN-42"}],
    )
    print(wl.data["id"], wl.data["results"])  # per item: watching | pending | invalid | duplicate | cap_exceeded | not_found

    # 2. Poll the change feed. Store next_cursor and pass it back next time.
    page = cm.list_changes(cursor=load_cursor(), types=["case.hearing_date_changed", "case.order_added"])
    for event in page.data:
        print(event["type"], event["cnr"], event["data"])
    save_cursor(page.next_cursor)  # returned even when the page is empty

    # Or walk everything until caught up.
    for event in cm.iter_changes(since="2026-11-01T00:00:00Z"):
        handle(event)
```

### Receive webhooks

Create an endpoint (https only). The `secret` is shown once, so store it.

```python
hook = cm.create_webhook("https://example.com/hooks/courtmesh")
print(hook.data["secret"])  # whsec_...
cm.test_webhook(hook.data["id"])  # sends a webhook.test event now
```

Verify every delivery with the RAW request body. Flask:

```python
import os
from flask import Flask, request
from courtmesh import verify_webhook_signature, WebhookSignatureError

app = Flask(__name__)

@app.post("/hooks/courtmesh")
def courtmesh_hook():
    try:
        event = verify_webhook_signature(
            request.get_data(),  # raw bytes, not request.json
            request.headers.get("CourtMesh-Signature"),
            os.environ["COURTMESH_WEBHOOK_SECRET"],
        )
    except WebhookSignatureError:
        return "bad signature", 400
    # Delivery is at least once: dedupe on event["id"] (also sent as the CourtMesh-Event-Id header).
    print(event["type"], event["cnr"])
    return "", 200  # any 2xx within 10 seconds counts as delivered
```

FastAPI:

```python
import os
from fastapi import FastAPI, HTTPException, Request
from courtmesh import verify_webhook_signature, WebhookSignatureError

app = FastAPI()

@app.post("/hooks/courtmesh")
async def courtmesh_hook(request: Request):
    raw = await request.body()
    try:
        event = verify_webhook_signature(
            raw, request.headers.get("CourtMesh-Signature"), os.environ["COURTMESH_WEBHOOK_SECRET"]
        )
    except WebhookSignatureError:
        raise HTTPException(status_code=400, detail="bad signature")
    return {"ok": True}
```

`verify_webhook_signature(raw_body, header, secret, tolerance_seconds=300)`
rejects a timestamp more than 300 seconds from now, computes HMAC-SHA256 over
`"<t>.<raw body>"` and compares in constant time against every `v1=` value in
the header (two during a 24 hour secret rotation). Pass a list of secrets to
cover your side of a rotation. It returns the parsed event or raises
`WebhookSignatureError` (`exc.reason` says why).

Each attempt has a 10 second deadline and reads at most 64 KB of your
response. Failed deliveries are retried after 1 min, 5 min, 30 min, 2 h, 6 h,
12 h and 24 h. A delivery that could not be attempted within 24 hours is
marked `failed` with `lastError: "expired"` instead of being sent. Use `list_webhook_deliveries(id)` to inspect attempts and
`retry_webhook_delivery(id, delivery_id)` to re-send one.

### What the change feed sends

- Dates are `YYYY-MM-DD` on the Indian calendar. A court's year 9999 "no date" is returned as `None`.
- `case.tracking_started` is sent once the first fresh refresh of the case completes, carrying the fresh snapshot, not at the moment you add the CNR (a record that is already current sends it at add time). A CNR we fetched live for you sends it as soon as the case lands.
- A burst of new orders announces only the newest 20, oldest first. An order dated more than 7 days before you started watching is never announced.
- A case taken down at a party's request shows as an `unavailable` item (`caseId`, `court`, `title`, `snapshot`, `lastCheckedAt` and `lastChangedAt` are `None`) and sends no events. Adding a CNR that is already taken down returns `not_found`.
- Cursors are opaque and ordered by an internal sequence. `since` is converted to a position once; keep using the `nextCursor` you get back.
- A webhook created without `events` echoes the full default `case.*` list; `watchlist_ids=[]` means all lists. `create_webhook` honours `idempotency_key`, and `test_webhook` is sent even to a switched off endpoint.
- A 400 validation error carries `details` as a list of `"path: message"` strings in `exc.response_body["details"]`, for query and body alike.

### Monitoring methods

| Method | Endpoint | Credits |
|---|---|---|
| `get_case_by_cnr(cnr, fetch=False)` | `GET /cases/by-cnr/{cnr}` | 1 when a record is returned (`pending` and `not_found` are free; with `fetch`, the starting call is free and the poll that returns the record is the one charge) |
| `search_cases(cnr=...)` | `POST /search/cases` | as search (returns one ordinary search hit; progress fields and `orderCount` are only on `get_case_by_cnr`) |
| `create_watchlist`, `get_watchlist`, `update_watchlist`, `delete_watchlist` | `/watchlists` | 0 |
| `list_watchlists` / `iter_watchlists` | `GET /watchlists` | 0 |
| `add_watchlist_items`, `remove_watchlist_item` | `/watchlists/{id}/items` | 0 |
| `list_watchlist_items` / `iter_watchlist_items` | `GET /watchlists/{id}/items` | 0 |
| `list_changes` / `iter_changes` | `GET /changes` | 1 per non-empty page |
| `list_watchlist_events` / `iter_watchlist_events` | `GET /watchlists/{id}/events` | 1 per non-empty page |
| `create_webhook`, `get_webhook`, `update_webhook`, `delete_webhook`, `rotate_webhook_secret`, `test_webhook` | `/webhooks` | 0 |
| `list_webhooks` / `iter_webhooks` | `GET /webhooks` | 0 |
| `list_webhook_deliveries` / `iter_webhook_deliveries`, `retry_webhook_delivery` | `/webhooks/{id}/deliveries` | 0 |

The `iter_*` helpers yield individual items; the `list_*` methods return a
`CursorListResult` with `.data`, `.pagination` and `.next_cursor`.

Watch caps per account (distinct CNRs across all watchlists, so the same CNR
on two lists uses one slot): Free 10, Pay As You Go 1,000, Scale 10,000,
Enterprise by contract. Two daily limits apply to adding, counted per Indian
calendar day, and items over either come back as `cap_exceeded` with a
message: every add that results in a watched or pending item counts toward a
daily add allowance (Free 50, Pay As You Go 5,000, Scale 50,000, Enterprise
500,000), and adding CNRs we do not hold yet starts a live fetch, so those
also have their own daily limit (Free 20, Pay As You Go 500, Scale 5,000,
Enterprise unlimited). A Supreme Court CNR we do not hold comes back
`not_found` at once. If the court portal had nothing for a CNR in the last 24
hours, adding it again is `not_found` with a message and starts no new fetch
(the same cooldown makes `get_case_by_cnr(..., fetch=True)` raise
`NotFoundError`). `not_found`, `error` and `unavailable` items still count
toward the cap until removed. At most
50 watchlists and 10 webhook endpoints per account. `WATCH_CAP_EXCEEDED`
(403) is raised only when the cap is already full and you sent a new CNR.
Webhook delivery history is kept 30 days and events 90 days; an event appears
in the feed about 2 seconds after it is created. `test_webhook` makes one
attempt and never retries. New error codes surface as typed exceptions with
`code` set: `INVALID_CNR`, `WATCHLIST_NOT_FOUND`, `WEBHOOK_NOT_FOUND`,
`DELIVERY_NOT_FOUND`, `WATCH_CAP_EXCEEDED`, `WATCHLIST_LIMIT_REACHED`,
`WEBHOOK_LIMIT_REACHED`, `INVALID_WEBHOOK_URL`, `ITEM_NOT_FOUND` (removing a
CNR that is not in the list). API keys need the
`monitoring:read` and `monitoring:write` scopes (keys without explicit
scopes have full access). Cause list calls need the `causelist` scope.

## Cause lists

Read the hearing listings found for your matters, read the published list of a court you have a matter in, and check whether CNRs you watch appear on a stored list. All calls need an API key with the `causelist` scope and an account with cause lists enabled.

```python
# Listings found for your matters. Default range: today and the next 7 days. At most 31 days.
first = cm.list_cause_listings(from_date="2026-11-05", to_date="2026-11-12", limit=50)
print(first.data, first.pagination, first.has_more)  # pagination: page, limit, total, totalPages, hasMore

# Walk every listing (pages start at 1; each page is one call).
for listing in cm.iter_cause_listings(from_date="2026-11-05", to_date="2026-11-12"):
    print(listing["date"], listing["courtKey"], listing["caseText"])

# One matter. matter_id is the 24 character id.
one = cm.list_matter_cause_listings("66f1a2b3c4d5e6f7a8b9c0d1")
print(one.data["matter"], one.data["listings"])

# The published list of one court on one date. court_key comes from a listing.
court = cm.get_court_cause_list("DC:99:1:9900001:1:1", "2026-11-05")
print(court.data["status"], court.data["complete"], len(court.data["rows"]))

# Check CNRs you watch (1 to 100). Default range: today and tomorrow. At most 7 days.
check = cm.check_cause_lists(["ZZAB010000012024", "ZZAB010000022024"])
for r in check.data["results"]:
    print(r["cnr"], r["status"], r["reason"], r["listings"])
print(check.data["summary"], check.meta["creditsCharged"])
```

`from_date` and `to_date` are sent as `from` and `to`, together or not at all. Dates, `matter_id` and `court_key` are checked before a request is sent and a bad value raises `ValidationError`. A court key is `SC`, `HC:<state>:<bench>` or `DC:<state>:<district>:<complex>:<establishment>:<court number>`, digits only.

| Method | Endpoint | Credits |
|---|---|---|
| `list_cause_listings` / `iter_cause_listings` | `GET /cause-lists/listings` | 1 per successful call |
| `list_matter_cause_listings(matter_id)` | `GET /matters/{matterId}/cause-listings` | 1 per successful call |
| `get_court_cause_list(court_key, date)` | `GET /cause-lists/court` | 1 when `status` is `ok` or `partial`; 0 for `none`, `empty`, `not_published`, `invalid_court` and `unavailable` |
| `check_cause_lists(cnrs, from_date, to_date)` | `POST /cause-lists/check` | 1 per CNR with status `listed` or `no_entry_found`; 0 for the rest |

`check_cause_lists` never contacts a court: it reads lists already held, and it takes an `Idempotency-Key` like the other POST calls. Each result has one of these statuses:

| Status | Meaning | Credits |
|---|---|---|
| `listed` | A row of this case was found. `listings` holds the rows. | 1 |
| `no_entry_found` | A list was read and no row was recognised. This does not show the case is not listed: `dates[].complete` says how much of each list was read. | 1 |
| `list_not_read` | No list was held for the dates. For a District Court it can also mean the list of the case's own courtroom could not be confirmed (`dates[].status` is then `none`). | 0 |
| `cannot_check` | `reason` says why: `pending`, `record_unavailable`, `court_not_supported`, or a court identification reason (`no_case_identity`, `no_court_key`, `no_court_number`, `invalid_court_key`, `unsupported_court`). `courtKey` can be `None`. | 0 |
| `not_watched` | Your account does not watch this CNR. | 0 |

Only listings that were found are reported. An empty result is not a statement that a case is absent from a list, so confirm against the court's own list when it matters. At most 100 CNRs, and distinct CNRs (repeats are ignored) times dates in the range (inclusive; 2 by default) at most 300, checked before a request is sent (`ValidationError`). The call also needs at least 1 credit available when it starts: a balance below the number of watched CNRs in the call raises `InsufficientCreditsError`. The same error can arrive after the answer is ready, when the credits due cannot be settled; no results are returned then. A `ServiceUnavailableError` with `code` `SETTLEMENT_UNCONFIRMED` means the answer was ready but the charge outcome is unknown and no results were returned: it is never retried automatically, even with `retry_posts`, so check your balance with `get_usage()` first; repeating the call with the same `idempotency_key` is refused with 409 `IDEMPOTENCY_IN_PROGRESS` for up to 24 hours. A 503 `ENTITLEMENT_UNAVAILABLE` ran nothing and is safe to retry. A listing's `matchedBy` is `cnr`, `diary`, `key` or `related_key`; `caseText` and `courtKey` can be `None`. `data["from"]` and `data["to"]` give the dates that were looked at, including when you sent none. A temporary outage raises `BadGatewayError` (`code == "UPSTREAM_UNAVAILABLE"`) and is not charged; GET calls are retried, and the check call is retried only when `retry_posts` is on (it then sends an `Idempotency-Key`). An account without cause list access raises `PermissionDeniedError` (`CAUSE_LISTS_NOT_ENABLED`); an unknown matter or a court without an open matter of yours raises `NotFoundError`.

## Acts and sections

Read Indian statutes: find an act, read a provision with its amendment notes, follow what replaced a repealed law, and list judgments that cite a provision. These calls need the `legislation` scope. Each costs 1 credit when it returns something and nothing when it returns nothing. Text is the statute as published. Repeal status is on every act and provision, so check `repealed` (acts) and `actRepealed` or `repealedProvision` (provisions) before relying on one.

```python
from courtmesh import CourtMesh

with CourtMesh(api_key="cm-...") as cm:
    # "section 302 IPC" to the provision it names. A lettered section keeps its letter.
    found = cm.lookup_section("section 302 IPC")
    match = found.data["matches"][0]  # match["ambiguous"] is True when no act was named
    section = match["section"]
    print(section["actRepealed"], section.get("actRepealNote"))

    # The full text, then judgments citing exactly this provision.
    text = cm.get_act_section(section["actSlug"], section["slug"])
    print(text.data["text"])

    for case in cm.iter_section_citing_cases(section["actSlug"], section["slug"]):
        print(case["id"], case.get("title"), case.get("decisionDate"))
```

Methods: `search_acts`, `resolve_act`, `get_act`, `get_act_history`, `list_act_sections`, `get_act_section`, `list_section_citing_cases` (with the `iter_section_citing_cases` generator), `search_sections`, `lookup_section`.

The citing list ends at your plan's pagination depth, and it is not exhaustive: an empty list does not mean no judgment applied the provision, and `listAvailable: false` means judgments cannot be listed for that provision. It matches the exact provision only, so a search for section 302 of the Penal Code does not return judgments that cite only its successor. Some matters are never listed: `listAvailable` is false for a provision we do not list judgments for, including sexual offences and cruelty provisions. A page can hold fewer rows than `limit`, or none, while `pagination["hasMore"]` is true, so keep following `pagination["nextCursor"]` (it is opaque); `iter_section_citing_cases` does this for you. `get_act_history` is at act level: it lists what repealed an act and what amended it, and does not map old sections to new ones. "Order VII Rule 11 CPC" style citations are not resolved by `lookup_section` and return no match.

An unknown act slug raises `NotFoundError` with `code == "ACT_NOT_FOUND"`, and an unknown provision raises it with `SECTION_NOT_FOUND`. Neither is charged. A temporary failure listing citing judgments raises `BadGatewayError` (`UPSTREAM_UNAVAILABLE`); it is free and safe to retry. `search_acts`, `resolve_act`, `search_sections`, `lookup_section` and `list_section_citing_cases` have a lower per minute limit than other calls and are refused with 429 (`RateLimitError`) above it.

## Pagination

`search_cases` and `semantic_search` both take `page` / `limit` and return a
`pagination` dict, but the two shapes are different, see "Caveats". Default
page size is 20 for both (also the Free tier's own `maxPageSize`; do not
request more than your tier allows, see `PAGE_LIMIT_EXCEEDED` below). Use
the generator helpers to walk every page without managing `page` yourself:

```python
for hit in cm.iter_search_cases("motor accident compensation", court="Delhi High Court", limit=20):
    print(hit.get("title"))

for item in cm.iter_semantic_search("landmark judgment on privacy", limit=20):
    print(item["title"], item["similarity"])
```

`iter_search_cases` is cursor-first: once a page's `pagination["nextCursor"]`
comes back as a signed string, it is passed back as `cursor` on the next
call rather than incrementing `page`. On the legacy path (`nextCursor`
comes back as a raw list instead), it walks pages via `searchAfter`
instead; either way you do not have to branch on the shape.

Both generators stop as soon as `hasMore` is false or a page comes back
empty. Pass `max_pages=` to cap the number of pages fetched; a hard safety
cap also applies internally so a misbehaving server can never cause an
infinite loop.

An invalid or query-mismatched `cursor` raises `ValidationError` with
`code == "CURSOR_INVALID"`. Requesting a `limit` above your tier's cap
raises `ValidationError` with `code == "PAGE_LIMIT_EXCEEDED"` (`limit` and
`tier` are set on the exception); paging deeper than your tier allows
raises the same class with `code == "PAGINATION_DEPTH_EXCEEDED"`. Neither
of these two response bodies carries a human message on the wire
(`{"success": False, "code", "limit", "tier"}`), this SDK synthesises
`exc.message` for you.

## Error handling

Every error the SDK raises is a `CourtMeshError` (or one of its subclasses
below), carrying `status_code`, `message` and the raw `response_body`:

```python
from courtmesh import (
    CourtMesh,
    CourtMeshError,
    ValidationError,
    PayloadTooLargeError,
    AuthenticationError,
    InsufficientCreditsError,
    PermissionDeniedError,
    NotFoundError,
    RequestTimeoutError,
    RateLimitError,
    ServerError,
    BadGatewayError,
    ServiceUnavailableError,
    API_REFUSAL_CODES,
)

cm = CourtMesh(api_key="...")

try:
    result = cm.get_case("does-not-exist")
except NotFoundError as exc:
    print("not found:", exc.message)
except InsufficientCreditsError as exc:
    print("need more credits:", exc.shortfall)
    if exc.contact_admin:
        print("contact your org admin")
    else:
        print("top up at", exc.top_up_url)
except RateLimitError as exc:
    print("rate limited, retry after", exc.retry_after, "seconds, resets at", exc.reset_time, "code:", exc.code)
except ValidationError as exc:
    print("bad request:", exc.message, exc.response_body.get("details") if exc.response_body else None)
except CourtMeshError as exc:
    print("request failed:", exc.status_code, exc.code, exc.message, exc.request_id)
```

Exception classes map to real HTTP status codes:

| status | exception |
|---|---|
| 400, 413 | `ValidationError` (`details` for a field-level validation failure; `code`/`limit`/`tier` for `PAGE_LIMIT_EXCEEDED`/`PAGINATION_DEPTH_EXCEEDED`; `code == "CURSOR_INVALID"` for a bad pagination cursor; `PayloadTooLargeError` (413) is a subclass for a request body over the size limit) |
| 401 | `AuthenticationError` (`code`: `API_KEY_MISSING`, `API_KEY_INVALID_FORMAT`, `API_KEY_INVALID`, `API_KEY_REVOKED`, `API_KEY_EXPIRED`) |
| 402 | `InsufficientCreditsError` (every priced endpoint pre-flight reserves the charge before doing any work; `required`, `balance`, `shortfall`, `wallet`, `wallet_owner` (`"user"` or `"org"`), and either `top_up_url` or `contact_admin=True`, never both) |
| 403 | `PermissionDeniedError` (`code`/`response_body["upgradeUrl"]` for tier/feature restrictions, for example `API_NOT_AVAILABLE_ON_TRIAL`, `API_TIER_NOT_ALLOWED`, `SEMANTIC_NOT_ALLOWED`, `LIVE_FETCH_NOT_ALLOWED`, `REMOTE_FETCH_NOT_ALLOWED`, `PARTY_SCREEN_LIMIT_REACHED`) |
| 404 | `NotFoundError` (`code`: `CASE_NOT_FOUND` or `PDF_NOT_STORED` on the pdf endpoint; `ACT_NOT_FOUND` or `SECTION_NOT_FOUND` on the acts endpoints) |
| 408 | `RequestTimeoutError` |
| 429 | `RateLimitError` (has `retry_after`, `reset_time`; `code` is `RATE_LIMITED`, `CONCURRENT_ANALYSIS_LIMIT`, or a daily/monthly cap code like `DISTINCT_NAMES_LIMIT_REACHED`) |
| 500 | `ServerError` |
| 502 | `BadGatewayError` (also `code == "PARTY_SCREEN_SEARCH_DEGRADED"`; the underlying case search itself errored and returned nothing usable, retry) |
| 503 | `ServiceUnavailableError` (`code == "ENTITLEMENT_UNAVAILABLE"` when account standing could not be verified, safe to retry; `code == "SETTLEMENT_UNCONFIRMED"` on `check_cause_lists`: the charge outcome is unknown, never retried automatically, check your balance first; `code == "PARTY_PROFILE_FULL_UNAVAILABLE"` on `build_party_profile`: full mode is not available, nothing charged, never retried) |

All inherit `CourtMeshError`. Status codes not in this table (practically,
only a raw 504 that survives retries) fall back to the base
`CourtMeshError`. `InsufficientCreditsError` (402) is never retried, the
call will not succeed until the account has enough credits.

Every exception exposes `code` (the server's machine readable `code` field
verbatim, when sent) and `request_id` (when the API sends one). `API_REFUSAL_CODES` is exported as a tuple of the
server's own refusal codes, for membership testing without hand-typing
string literals:

```python
if isinstance(exc, PermissionDeniedError) and exc.code == "SEMANTIC_NOT_ALLOWED":
    ...
assert exc.code in API_REFUSAL_CODES
```

### Retries

By default the SDK retries, with exponential backoff plus jitter:

- a 429 whose `code` is `RATE_LIMITED` or `CONCURRENT_ANALYSIS_LIMIT` -
  never a daily or monthly cap code (`DISTINCT_NAMES_LIMIT_REACHED`,
  `LIVE_FETCH_LIMIT_REACHED`, `DISTINCT_CASES_LIMIT_REACHED`,
  `PDF_LIMIT_REACHED`, `TOO_MANY_KEYS_FROM_IP`), since those will not clear
  before the advertised delay anyway;
- for a **GET** request only: a 502, 503 or 504 response, or a
  connection/timeout error.

`max_retries` defaults to 3.

**POST requests are not retried after they have reached the network** (a
connection/timeout error, or a 502/503/504 response) unless you opt in with
`retry_posts=True` (client-wide, in the `CourtMesh(...)` constructor) or
per call (`cm.search_cases(..., retry_posts=True)`). This is deliberate: a
POST that may have already been received and acted on server side
(analyze, party/screen, and similar) risks a double charge or a duplicate
job if retried blindly. A 429 is not gated by `retry_posts`; it is a
pre-flight refusal, so no work was done regardless of method.

For a 429, the delay is chosen in this order:

1. The `Retry-After` response header, if present.
2. The JSON body's `retryAfter` field, in seconds (this is what the CourtMesh API itself sends today).
3. Exponential backoff with jitter, the same fallback used for 502, 503, 504 and connection errors.

That delay is capped at `max_retry_after_seconds` (default 60). A daily or
monthly cap can advertise a `Retry-After` of up to a day; when the
advertised delay exceeds the cap, the SDK does not sleep and retry: it
raises `RateLimitError` immediately, with `retry_after` set to the real
(uncapped) delay, so you can decide for yourself whether to wait that long.

### Timeouts

Per endpoint defaults, since some run far longer server side than a
typical call: `semantic_search` 630s, `request_timeline` 240s,
`analyze_consolidated` 300s, `screen_party` and `build_party_profile`
90s, everything else 30s.
Override per call:

```python
cm.screen_party(..., timeout=120)
```

A client side timeout does not cancel the request server side and never
triggers a refund.

### The semantic search transport quirk (defensive fallback only)

`semantic_search` used to be able to return `HTTP 200` with
`{"success": false, "error": "..."}` in the body, because the server wrote
the response headers before it finished the search. The server
sends a proper non-200 status for a semantic search failure today, so this
should never trigger in practice; the SDK still checks `success` and
raises `CourtMeshError` as a belt-and-braces fallback in case a future
response ever starts streaming before failing:

```python
try:
    result = cm.semantic_search(query="right to privacy")
except CourtMeshError as exc:
    print("semantic search failed:", exc.message)
```

## Caveats (real server behaviour, not SDK limitations)

- Two different pagination shapes exist and are not unified:
  - `search_cases`: `{"total", "hasMore", "page"?, "limit", "nextCursor"}`.
    `page` is absent when you used `searchAfter` cursor pagination,
    `totalPages` does not exist on this endpoint.
  - `semantic_search`: `{"page", "limit", "total", "totalPages", "hasMore"}`.
    `total` and `totalPages` are estimates, exact only on the last page.

## Development

```bash
git clone <this-repo>
cd courtmesh-python
python3.12 -m venv .venv
.venv/bin/pip install -e ".[test]"
.venv/bin/pytest
```

No network calls are made in the test suite, all HTTP is mocked.

## Releasing

Maintainers: see [RELEASING.md](RELEASING.md).

## License

MIT, see `LICENSE`. Copyright Thinkscoop Technologies LLP.
