# Changelog

All notable changes to `courtmesh` are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Each entry also states which server flags/behaviour the version targets on
the CourtMesh research server, since some of this SDK's contract only takes
effect once a given server flag is on for your account.

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
