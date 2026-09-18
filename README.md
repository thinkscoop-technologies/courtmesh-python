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

Or, from a local checkout:

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
cm = CourtMesh(api_key="...", base_url="https://staging.courtmesh.ai/api/v1/prod")
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

Keyword search over the OpenSearch index. `caseNumber` is applied server
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
print(result.data)         # list of raw OpenSearch hits (id, score, optional highlights;
                            # _id/_score kept for legacy)
print(result.meta)         # {"query": ..., "filters": {...}, "sortBy": ..., "responseTime": ...}
print(result.pagination)   # {"total": ..., "hasMore": ..., "page": ..., "limit": ..., "nextCursor": ...}
```

Paging past the first screen: pass the previous page's
`result.pagination["nextCursor"]` back as `cursor` (a signed, opaque string
on self-serve accounts) - an invalid or query-mismatched cursor raises
`ValidationError` with `code == "CURSOR_INVALID"`. `iter_search_cases` (see
Pagination below) does this for you, including the legacy list-shaped
`nextCursor` some accounts still get.

### 3. `semantic_search`, `POST /search/cases/semantic`

Vector search, billed as an AI interaction. **Not available on the Free
tier**: raises `PermissionDeniedError` with `code == "SEMANTIC_NOT_ALLOWED"`
before any work or charge. The top level filter fields, whatever the
query's natural language implies, and the `filters` object are all merged,
weakest first in that order - `filters` (the vector store's own keys)
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
field) are narrower here than on `search_cases`: the vector store filters
case numbers numerically, so `caseNumber` must be a digits only string
(`cm.semantic_search(..., caseNumber="1234")`, raises `ValueError`
otherwise), and it matches a single judge name, so `judgeName` accepts one
string, not a list.

### 4. `get_case`, `GET /cases/{id}`

```python
result = cm.get_case("64f0abc123...")     # Mongo ObjectId or caseNumber
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
print(result.data["pdfUrl"])       # ciphertext, expires in result.data["expiresIn"] seconds
```

Note: `pdfUrl` is an encrypted, presigned S3 URL, not a directly fetchable
link. Decrypting it needs a case specific key that is not part of this API
surface. Failure codes: `CASE_NOT_FOUND` (404), `CASE_RESTRICTED` (403),
`PDF_NOT_STORED` (404, no stored document - `request_timeline` with
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

`case_id` must be a Mongo ObjectId string. `refresh=True` forces a live
court-portal fetch (20 credits) instead of serving the last stored read (1
credit) - `result.meta["liveFetch"]` says which one actually happened,
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

No auth required, no rate limit. Unlike every other endpoint, the response
is not wrapped in `data`.

```python
health = cm.health()
print(health["status"], health["version"])
```

### 13. `screen_party`, `POST /party/screen`

Screens a person or company name against the case law corpus for litigation, insolvency and other court records. Requires an API key. Costs 100 credits when matches are found, 20 when none are, plus a flat surcharge only when `result.data["adjudicationsRun"] > 0` - requesting `adjudicate=True` does not by itself guarantee a model call happened (every candidate may already have been decided deterministically), so it does not by itself bill the surcharge either. `adjudicate=True` is not available on the Free tier (`PermissionDeniedError`, `code == "API_TIER_NOT_ALLOWED"`).

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

Verdict semantics: `matches_found` describes what was found internally, independent of `displayThreshold` - raising the threshold can leave `matches` empty (`summary["matchCount"] == 0`) while the verdict is still `matches_found`. `since` forces `inconclusive` (it is a best-effort filter, so completeness can never be certified either way). `no_matches_found` is only ever returned when `coverage["exhaustive"]` is `True` and nothing was withheld.

**DPDP note.** `purpose` is required on every call and is the only thing about the query the server retains in its logs, `name`, `aliases`, `knownPersons`, `identifiers` and `address` are never logged. The results are drawn entirely from public court records, they are not sourced from or cross-checked against any private database. **A screen is not an identity check**: it tells you whether a name (optionally narrowed by identifiers, address or known associates) appears in litigation or insolvency records, it does not verify who a person or company actually is. `result.data["notice"]` links the case removal / takedown policy; `result.data["coverage"]["someRecordsWithheld"]` is `True` when one or more otherwise-matching cases were removed from the results because they are under a takedown order.

### 14. `get_coverage`, `GET /coverage`

Corpus coverage and freshness stats: totals, by court type, by year, per court, and a rolled up District Courts row (the index has no per-state field). No API key is required by the server for this endpoint, but this client always has one (the constructor requires it) and sends it along anyway. Server side cached for up to 6 hours.

```python
result = cm.get_coverage()
print(result.data["total"], result.data.get("documentBearing"), result.data.get("statusOnly"))
for court in result.data["courts"]:
    print(court["court"], court["records"], court.get("documentBearing"), court.get("latestDecisionDate"), court.get("businessDaysBehind"))
print(result.data["districtCourts"].get("records"))
```

Most fields are optional (use `.get(...)` rather than `[...]`), since a court or year row may not report every stat.

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
instead - either way you do not have to branch on which shape your account
gets.

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
| 404 | `NotFoundError` (`code`: `CASE_NOT_FOUND` or `PDF_NOT_STORED` on the pdf endpoint) |
| 408 | `RequestTimeoutError` |
| 429 | `RateLimitError` (has `retry_after`, `reset_time`; `code` is `RATE_LIMITED`, `CONCURRENT_ANALYSIS_LIMIT`, or a daily/monthly cap code like `DISTINCT_NAMES_LIMIT_REACHED`) |
| 500 | `ServerError` |
| 502 | `BadGatewayError` (also `code == "PARTY_SCREEN_SEARCH_DEGRADED"` - the underlying case search itself errored and returned nothing usable, retry) |
| 503 | `ServiceUnavailableError` (`code == "ENTITLEMENT_UNAVAILABLE"` when account standing could not be verified) |

All inherit `CourtMeshError`. Status codes not in this table (practically,
only a raw 504 that survives retries) fall back to the base
`CourtMeshError`. `InsufficientCreditsError` (402) is never retried, the
call will not succeed until the account has enough credits.

Every exception exposes `code` (the server's machine readable `code` field
verbatim, when sent) and `request_id` (echoed once the API's request-id
middleware ships). `API_REFUSAL_CODES` is exported as a tuple of the
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
job if retried blindly. A 429 is not gated by `retry_posts` - it is a
pre-flight refusal, so no work was done regardless of method.

For a 429, the delay is chosen in this order:

1. The `Retry-After` response header, if a proxy in front of the API sets one.
2. The JSON body's `retryAfter` field, in seconds (this is what the CourtMesh API itself sends today).
3. Exponential backoff with jitter, the same fallback used for 502, 503, 504 and connection errors.

That delay is capped at `max_retry_after_seconds` (default 60). A daily or
monthly cap can advertise a `Retry-After` of up to a day - when the
advertised delay exceeds the cap, the SDK does not sleep and retry: it
raises `RateLimitError` immediately, with `retry_after` set to the real
(uncapped) delay, so you can decide for yourself whether to wait that long.

### Timeouts

Per endpoint defaults, since some run far longer server side than a
typical call: `semantic_search` 630s, `request_timeline` 240s,
`analyze_consolidated` 300s, `screen_party` 90s, everything else 30s.
Override per call:

```python
cm.screen_party(..., timeout=120)
```

A client side timeout does not cancel the request server side and never
triggers a refund.

### The semantic search transport quirk (defensive fallback only)

`semantic_search` used to be able to return `HTTP 200` with
`{"success": false, "error": "..."}` in the body, because the server wrote
the response headers before it finished the vector search. The server
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

- **`get_case_pdf`'s `pdfUrl` is ciphertext, not a fetchable URL.**
  Decrypting it uses a case specific key and is outside this API surface.
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
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/pip install -e ".[test]"
.venv/bin/pytest
```

No network calls are made in the test suite, all HTTP is mocked.

## Publishing

These are the exact commands a human runs to push this SDK to GitHub and
publish it to PyPI. Nothing here is automated by the SDK itself.

### 1. Push to GitHub

```bash
cd courtmesh-python
git remote add origin git@github.com:courtmesh/courtmesh-python.git
git push -u origin main
```

### 2. Build the release artifacts

```bash
python -m pip install --upgrade build twine
python -m build
```

This produces `dist/courtmesh-0.4.0.tar.gz` and `dist/courtmesh-0.4.0-py3-none-any.whl`.

### 3. Check the build

```bash
python -m twine check dist/*
```

### 4. Upload to PyPI

```bash
python -m twine upload dist/*
```

Twine will prompt for your PyPI username (use `__token__`) and an API token.
To upload to TestPyPI first instead:

```bash
python -m twine upload --repository testpypi dist/*
```

## License

MIT, see `LICENSE`. Copyright Thinkscoop Technologies LLP.
