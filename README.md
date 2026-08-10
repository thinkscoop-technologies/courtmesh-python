# courtmesh

Python SDK for the CourtMesh Enterprise API: search Indian case law, fetch
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
with CourtMesh(api_key="...", session=session, timeout=60, max_retries=5) as cm:
    health = cm.health()
    print(health["status"])
```

## Rate limits

The server allows 10 requests per minute per API key. Requests over that
limit get HTTP 429 with a `retryAfter` value in seconds. The SDK retries
429 automatically (see "Error handling and retries" below), so in normal
use you will not see `RateLimitError` unless `max_retries` is exhausted.
Response headers `X-RateLimit-Limit`, `X-RateLimit-Remaining` and
`X-RateLimit-Reset` are available on `cm.session` if you inspect responses
yourself, though the SDK's typed methods do not currently surface them.

## Endpoint examples

### 1. `search_judges`, `GET /judges/search`

```python
result = cm.search_judges("khanna")
print(result.data)          # ["JUSTICE A B", ...], at most 50 names
print(result.meta)          # {"query": "khanna", "responseTime": "3ms", "totalMatches": 12}
```

### 2. `search_cases`, `POST /search/cases`

Keyword search over the OpenSearch index.

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
    sortBy="relevance",
)
print(result.data)         # list of raw OpenSearch hits (_id, _score, _source fields)
print(result.meta)         # {"query": ..., "filters": {...}, "responseTime": ...}
print(result.pagination)   # {"total": ..., "hasMore": ..., "page": ..., "limit": ..., "nextCursor": ...}
```

### 3. `semantic_search`, `POST /search/cases/semantic`

Vector search. Filters go through the `filters` object, see "Caveats".

```python
result = cm.semantic_search(
    query="landmark judgment on the right to privacy",
    filters={"court": "Supreme Court", "decisionDate": {"$gte": "2015-01-01"}},
    limit=10,
)
for item in result.data:
    print(item["title"], item["similarity"])
```

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
surface.

### 8. `analyze_case`, `POST /cases/{id}/analyze`

Asynchronous. Poll `get_case` (or `get_case_analysis`) a bit later.

```python
result = cm.analyze_case("64f0abc123...")
print(result.data["status"])       # "processing"

# force re-analysis even if one exists
result = cm.analyze_case("64f0abc123...", force=True)
```

### 9. `analyze_consolidated`, `POST /cases/{id}/analyze-consolidated`

Synchronous and slow, analyses the case plus related documents.

```python
result = cm.analyze_consolidated("64f0abc123...")
print(result.data["status"])                       # "success" or "already_analyzed"
print(result.data["consolidatedAnalysis"]["summary"])
```

### 10. `request_timeline`, `POST /request-timeline`

`case_id` must be a Mongo ObjectId string.

```python
result = cm.request_timeline("64f0abc123456789abcdef01")
print(result.data["requestId"], result.data["status"])
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

## Pagination

`search_cases` and `semantic_search` both take `page` / `limit` and return a
`pagination` dict, but the two shapes are different, see "Caveats". Use the
generator helpers to walk every page without managing `page` yourself:

```python
for hit in cm.iter_search_cases("motor accident compensation", court="Delhi High Court", limit=50):
    print(hit.get("title"))

for item in cm.iter_semantic_search("landmark judgment on privacy", limit=20):
    print(item["title"], item["similarity"])
```

Both generators stop as soon as `hasMore` is false or a page comes back
empty. Pass `max_pages=` to cap the number of pages fetched; a hard safety
cap also applies internally so a misbehaving server can never cause an
infinite loop.

## Error handling

Every error the SDK raises is a `CourtMeshError` (or one of its subclasses
below), carrying `status_code`, `message` and the raw `response_body`:

```python
from courtmesh import (
    CourtMesh,
    CourtMeshError,
    ValidationError,
    AuthenticationError,
    PermissionDeniedError,
    NotFoundError,
    RequestTimeoutError,
    RateLimitError,
    ServerError,
    BadGatewayError,
    ServiceUnavailableError,
)

cm = CourtMesh(api_key="...")

try:
    result = cm.get_case("does-not-exist")
except NotFoundError as exc:
    print("not found:", exc.message)
except RateLimitError as exc:
    print("rate limited, retry after", exc.retry_after, "seconds, resets at", exc.reset_time)
except ValidationError as exc:
    print("bad request:", exc.message, exc.response_body.get("details"))
except CourtMeshError as exc:
    print("request failed:", exc.status_code, exc.message)
```

Exception classes map to real HTTP status codes:

| status | exception |
|---|---|
| 400 | `ValidationError` |
| 401 | `AuthenticationError` |
| 403 | `PermissionDeniedError` |
| 404 | `NotFoundError` |
| 408 | `RequestTimeoutError` |
| 429 | `RateLimitError` (has `retry_after`, `reset_time`) |
| 500 | `ServerError` |
| 502 | `BadGatewayError` |
| 503 | `ServiceUnavailableError` |

All inherit `CourtMeshError`. Status codes not in this table (practically,
only a raw 504 that survives retries) fall back to the base
`CourtMeshError`.

### Retries

The SDK retries automatically on HTTP 429, 502, 503, 504 and on connection
errors, using exponential backoff plus jitter, up to `max_retries` (default
3, configurable in the `CourtMesh(...)` constructor). For a 429 it honours
the `Retry-After` response header first, then falls back to the JSON body's
`retryAfter` seconds. If retries are exhausted, the matching exception
above is raised.

### The semantic search transport quirk

`semantic_search` can return `HTTP 200` with `{"success": false, "error": "..."}`
in the body, because the server writes the response headers before it
finishes the vector search, so a late failure (embedding generation,
Qdrant query, upstream fetch) cannot change the status code any more. The
SDK checks `success` for you and raises `CourtMeshError` in this case, so
you never have to check `success` yourself:

```python
try:
    result = cm.semantic_search(query="right to privacy")
except CourtMeshError as exc:
    # exc.status_code will read 200 here, that IS the quirk, not an SDK bug
    print("semantic search failed:", exc.message)
```

## Caveats (real server behaviour, not SDK limitations)

- **`caseNumber` on `search_cases` is accepted and validated, and it is
  echoed back in `result.meta["filters"]["caseNumber"]`, but it is never
  forwarded to the search backend.** It does not filter results.
- **`sortBy` on `search_cases` only meaningfully supports `"relevance"`.**
  The zod schema validates `"relevance" | "date"`, but the search backend
  actually expects `relevance|recent|oldest`, so `"date"` does not match
  anything the backend understands.
- **`semantic_search` ignores every top level filter field** (`court`,
  `caseType`, `caseNumber`, `judgeName`/`judges`/`judge`, `year`,
  `fromDate`, `toDate`). They are validated but never read by the handler.
  Use the `filters=` object instead, see the example above for the
  recognised keys.
- **`semantic_search` can return HTTP 200 with `success: false`.** See "The
  semantic search transport quirk" above, the SDK raises for you.
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

This produces `dist/courtmesh-0.1.0.tar.gz` and `dist/courtmesh-0.1.0-py3-none-any.whl`.

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
