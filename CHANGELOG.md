# Changelog

All notable changes to `courtmesh` are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Each entry also states which server flags/behaviour the version targets on
the CourtMesh research server, since some of this SDK's contract only takes
effect once a given server flag is on for your account.

## [0.4.1]

Live QA pass against the redeployed production research server
(`research.courtmesh.ai`, 2026-09-19) and its updated OpenAPI spec. All items
below were confirmed with live calls against an Enterprise key, not only
against the spec.

### Added

- `User-Agent: courtmesh-python/0.4.1` sent on every request.
- `UsageTierLimits["published"]`: this tier's number in the OpenAPI
  rate-limit table, distinct from `requestsPerMinute` (the number actually
  enforced right now) until the API self-serve tiers flag is on for your
  account, at which point the two converge.
- `CoverageMeta["snapshotAgeSeconds"]`, `["cacheAgeSeconds"]` and
  `["stale"]`, replacing a single `ageSeconds` field that never actually
  existed on the wire.
- `CoverageCourt["courtType"]`, now explicitly `Optional[str]` (added to the
  live schema 2026-09-19).
- `HealthCheckEntry`, `HealthCheckResult`, `PartyScreenRedactedName` and
  `PartyScreenRedactedAliases` (carried forward from the interim QA branch,
  re-verified live, see Changed below).

### Changed

- **Breaking:** `AuditHit["userAgent"]` removed - the redeployed server no
  longer sends it at all (dropped for privacy alongside raw `ipAddress`,
  which never appeared on the wire in the first place). `AuditHit["ipHash"]`
  (a SHA-256 digest of the caller's IP) is retained; a same-day interim fix
  had renamed `ipAddress` to `ipHash`, which remains correct.
- **Breaking:** `UsageTierLimits`: every field but `requestsPerMinute` (and
  now `published`) is `Optional`, matching a live Enterprise-key response
  with the self-serve tiers flag off. `limits` itself is confirmed always a
  populated dict, never `None`.
- **Breaking:** `CoverageCourt`/`CoverageByCourtType`/`CoverageDistrictCourts`
  date and `businessDaysBehind` fields are now `Optional`, matching the live
  schema.
- `AuditHit["metadata"]` is now `Optional[Dict[str, Any]]` - observed `None`
  in production for hits with nothing to log, not only omitted.
- `HealthResponse["checks"]` entries are bare status strings in production
  (`"ok" | "fail" | "skipped"`), not `{"status", "latencyMs"?, "error"?}`
  dicts; `HealthCheckEntry` accepts either shape (interim fix, re-verified
  live).
- `PartyScreenQueryEcho["name"]`/`["aliases"]` are redacted to
  `{"redacted": True, "length": ...}`/`{"redacted": True, "count": ...}` on
  a replayed idempotent `party/screen` response instead of echoing the
  original string/list (interim fix, re-verified live via a same-key
  replay).
- Confirmed unchanged and correct: `caseNumber` is a string (never a number)
  on every endpoint that returns one; the five idempotency-key-aware POST
  endpoints (`screen_party`, `screen_party_batch`, `analyze_case`,
  `analyze_consolidated`, `request_timeline`) still send `Idempotency-Key`
  and mark a replay; the per-endpoint default timeouts are unchanged.

### Removed

- `AuditHit["userAgent"]` (see Changed above).

## [0.4.0]

Targets the research server's account-introspection endpoints
(`GET /usage`, `GET /me`, `GET /audit`), the public reference endpoints
(`GET /reference/courts`, `GET /reference/case-types`), the new
`POST /party/screen/batch` endpoint, and the `Idempotency-Key` contract
being rolled out across the five job/charge-triggering POST endpoints.

### Added

- `get_usage()`: `GET /usage`, this key's tier, wallet balance,
  `TIER_LIMITS` for that tier, the current Asia/Kolkata billing period and a
  per endpoint call breakdown. Unmetered.
- `me()`: `GET /me`, the calling account's id, email, name, role and (if
  any) organization id.
- `audit(...)`: `GET /audit`, this key's own logged calls (or, for an org
  admin, an organization's), with summary stats and a top-endpoints
  breakdown. Takes `organizationId`, `userId`, `limit`, `offset`,
  `startDate`, `endDate`. Returns a new `AuditResult` dataclass (`data`,
  `pagination`, `request_id`).
- `reference_courts()`: `GET /reference/courts`, the court taxonomy
  accepted by `court` filters elsewhere in this API. No API key required.
- `reference_case_types()`: `GET /reference/case-types`, every `caseType`
  value accepted elsewhere in this API. No API key required.
- `screen_party_batch(items, purpose, ...)`: `POST /party/screen/batch`,
  screens 1 to 25 names in one call; each item is independently priced and
  can independently fail (`result.data["results"][i]["ok"]`) without
  failing the whole batch. Not available on the Free tier. LLM adjudication
  is not supported in the batch endpoint.
- `health()` now takes a `deep` argument, `health(deep=True)` calls
  `GET /health?deep=1`: also checks Mongo, OpenSearch, Qdrant, Redis and IAM
  standing, and reports `status in ("degraded", "unhealthy")` plus a
  `checks` dict per dependency. `HealthResponse` gained `commit` and
  `checks`.
- `idempotency_key` argument on `screen_party`, `screen_party_batch`,
  `analyze_case`, `analyze_consolidated` and `request_timeline`: sent as
  the `Idempotency-Key` header (1 to 128 characters, `[A-Za-z0-9_.-]`,
  scoped per API key for 24 hours). A replayed call with the same key and
  body returns the stored response again (`result.replayed is True`, no
  new charge); the same key with a different body raises `ConflictError`
  with `code == "IDEMPOTENCY_KEY_REUSED"`. When omitted, and `retry_posts`
  is in effect for that call (the call's own override, or the client's
  default), the SDK auto-generates a UUID v4 so an automatic retry of that
  exact call is always safe from a double charge or a double-run job.
- `APIResponse.request_id` / `.replayed` (also on `SearchCasesResult` and
  `SemanticSearchResult`, `request_id` only): every response now carries
  the request id, either the server's own `meta["requestId"]`/body level
  `requestId` when it set one, or (backfilled client side as a fallback)
  the `X-Request-Id` response header. `replayed` is `True` when the
  response carried `Idempotency-Replayed: true`.
- `ConflictError` (409): raised by the five idempotency-key-aware methods
  when the same `Idempotency-Key` was reused with a different body
  (`code == "IDEMPOTENCY_KEY_REUSED"`) or a request with that key is still
  in flight (`code == "IDEMPOTENCY_IN_PROGRESS"`).
  `IDEMPOTENCY_KEY_REUSED`, `IDEMPOTENCY_IN_PROGRESS` and
  `IDEMPOTENCY_KEY_INVALID` added to `API_REFUSAL_CODES`/`ApiRefusalCode`.
- New models: `ApiTier`, `UsageData`/`UsageMeta`/`UsageBalance`/
  `UsageTierLimits`/`UsagePeriod`/`UsageByEndpoint`/`UsageWalletOwner`,
  `MeData`, `AuditResult`/`AuditData`/`AuditHit`/`AuditSummary`/
  `AuditTopEndpoint`/`AuditPagination`, `CourtHierarchy`/`CourtNamesMap`,
  `CaseTypeEntry`, `PartyScreenBatchItemOk`/`PartyScreenBatchError`/
  `PartyScreenBatchItemResult`/`PartyScreenBatchSummary`/
  `PartyScreenBatchResult`/`PartyScreenBatchMeta`, `HealthCheckResult`.

## [0.3.0]

Targets the research server after the 2026-09-18 API abuse-control and
parity pass (`server/config/api-tiers.ts`, `server/routes/api-v1-prod.ts`,
`server/middleware/api-tier-limits.ts`, `server/utils/rate-limiter.ts`).
Correct against that server regardless of whether `API_SELF_SERVE_TIERS` is
on for your account, though several fields (`cursor`, tier refusal codes,
per tier pagination caps) are only ever populated once it is.

### Added

- `cursor` request field on `search_cases`, and `pagination["nextCursor"]`
  can now be a signed opaque string (when the API self-serve tiers flag is
  on for your account) as well as the legacy raw list. `searchAfter` is
  documented as deprecated/legacy.
- `iter_search_cases` is now cursor-first: it passes
  `pagination["nextCursor"]` back as `cursor` (or, on the legacy list
  shape, continues via `searchAfter`) instead of only incrementing `page`.
- `refresh` argument on `request_timeline`; `result.meta["liveFetch"]` and
  `result.data["liveFetchSupported"]` on its response.
- `allow_remote_fetch` argument on `analyze_case`.
- `meta["sortBy"]`, `meta["warnings"]`, `meta["someRecordsWithheld"]` and
  `meta["restrictedCheckDegraded"]` on `search_cases` and `semantic_search`.
- `PayloadTooLargeError` (413).
- `API_REFUSAL_CODES` (tuple) and `ApiRefusalCode` (`Literal`), mirroring
  the server's own machine refusal codes plus the handler-local and
  SDK-synthesised ones (`CASE_RESTRICTED`, `PDF_NOT_STORED`,
  `CASE_NOT_FOUND`, `PARTY_SCREEN_SEARCH_DEGRADED`, `CURSOR_INVALID`,
  `PAGE_LIMIT_EXCEEDED`, `PAGINATION_DEPTH_EXCEEDED`, the `API_KEY_*` auth
  codes, `ORGANIZATION_DEACTIVATED`, `ACCOUNT_STANDING_UNAVAILABLE`,
  `IP_NOT_ALLOWED`, `VALIDATION_ERROR`, `MALFORMED_JSON`,
  `PAYLOAD_TOO_LARGE`, and more) and `is_retryable_429_code`.
- `code` and `request_id` on every exception class (previously there was no
  machine-readable `code` attribute at all, only `response_body["code"]`).
- `wallet`, `wallet_owner` and `contact_admin` on `InsufficientCreditsError`;
  `limit` and `tier` on `ValidationError`, with a synthesised `message` for
  the two pagination cap codes (whose response body carries no message of
  its own) and, more generally, `_http.py`'s error message now falls back
  to the machine `code` when the body has neither `error` nor `message`.
- `retry_posts` and `max_retry_after_seconds` client options (also
  overridable per call), and per call `timeout=`/`retry_posts=` arguments
  on every endpoint method.
- Per endpoint default timeouts: `semantic_search` 630s, `request_timeline`
  240s, `analyze_consolidated` 300s, `screen_party` 90s, everything else 30s.
- `PartyRole`, `PartyScreenRelatedMatch` and `PartyScreenQueryEcho` types.

### Changed

- **Breaking:** `CaseListItem` now exposes `id`/`score`/`highlights` as the
  primary fields; `_id`/`_score` are kept but documented as legacy.
- **Breaking:** `PartyScreenCoverage` no longer has `candidatesEvaluated` or
  `adjudicationsRun` - `adjudicationsRun` moved to a top level field of
  `PartyScreenResult` (matching the server's actual response shape).
- **Breaking:** `semantic_search`'s `caseNumber` argument is now a single
  digits-only string (was a string-or-list, validated but silently ignored
  by the handler for any value that was not already digits-only); `judges`/
  `judge` are now aliases collapsed into the single `judgeName` field sent
  on the wire, matching what the vector store actually matches against
  (one judge name).
- Only `RATE_LIMITED` and `CONCURRENT_ANALYSIS_LIMIT` are retried
  automatically on a 429; a daily/monthly cap code never is.
- A POST is no longer retried automatically after a connection/timeout
  error or a 502/503/504 response, unless `retry_posts=True`. A 429 is
  unaffected by this (it is a pre-flight refusal on every method).
- Renamed "CourtMesh Enterprise API" to "CourtMesh API" throughout.

### Removed

- Deleted four stale README caveats that no longer describe the live
  server: `caseNumber` is applied server side (not ignored); `sortBy`
  supports `relevance`/`recent`/`oldest` (not only `relevance`);
  `semantic_search`'s top level filter fields are merged in, not ignored;
  `semantic_search` no longer returns HTTP 200 for a failed request.

## [0.2.0] and earlier

Pre-dates this changelog. See git history.
