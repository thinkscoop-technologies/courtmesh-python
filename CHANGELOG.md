# Changelog

All notable changes to `courtmesh` are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Each entry also states which CourtMesh API behaviour the version targets,
since some of this SDK's contract depends on your account's plan.

## [0.6.0]

Adds the Acts and sections API. These calls need the `legislation` scope and cost 1 credit when something is returned, nothing when nothing is. Adds case depth and refresh by CNR. Adds the cause list calls. They need the `causelist` scope and an account with cause lists enabled. Adds party profiles and deleting a key's own audit activity. Targets API docs 1.8.0.

### Added

- `search_acts`, `resolve_act`, `get_act`, `get_act_history`, `list_act_sections`, `get_act_section`, `list_section_citing_cases`, `search_sections` and `lookup_section`.
- `iter_section_citing_cases`, a generator that walks the citing judgments cursor by cursor.
- Typed models for all of the above, exported from the package root (`Act`, `ActSection`, `ActHistory`, `SectionRow`, `CitingCases` and others), plus `ActsPageResult` and `CitingCasesResult`.
- Error codes `ACT_NOT_FOUND` and `SECTION_NOT_FOUND` (both `NotFoundError`, not charged) and `UPSTREAM_UNAVAILABLE` (`BadGatewayError`, not charged, safe to retry), in `API_REFUSAL_CODES`.
- `include` on `get_case` and `get_case_by_cnr`: hearing history and advocates, at no extra charge. Either can be null when no such record is held.
- `list_case_orders` (1 credit): the documents of a case with availability flags. `get_case_document_text`: the stored text of one, 2 credits and charged only when text is returned.
- `refresh_case_by_cnr`, `get_case_refresh_state` and `refresh_cases_batch`: refresh by CNR, one at a time or up to 50, with a free status read.
- `ORDER_TEXT_LIMIT_REACHED` error code.
- `list_cause_listings` and `iter_cause_listings` for `GET /cause-lists/listings`, `list_matter_cause_listings` for `GET /matters/{matterId}/cause-listings`, `get_court_cause_list` for `GET /cause-lists/court`, and `check_cause_lists` for `POST /cause-lists/check` (1 to 100 watched CNRs, at most 7 days).
- Statuses `listed`, `no_entry_found`, `list_not_read`, `cannot_check` and `not_watched`. `listed` and `no_entry_found` cost 1 credit per CNR, the others are free. `no_entry_found` does not show a case is not listed.
- Types for listings, court lists, rows, pagination and the check result (including `data["from"]` and `data["to"]`, the dates looked at, and the `reason` values of `cannot_check`; a check is limited to 100 CNRs and to CNRs times dates of at most 300, validated before a request is sent; a 503 `SETTLEMENT_UNCONFIRMED`, where the charge outcome is unknown, is never retried automatically, even with `retry_posts`), and the `CauseListPage` result with `has_more`.
- `matter_id` (24 hex characters), `court_key`, dates and the CNR count are checked before a request is sent and raise `ValidationError`.
- A `502` with `UPSTREAM_UNAVAILABLE` raises the existing `BadGatewayError`; it is not charged and GET calls are retried as before. `CAUSE_LISTS_NOT_ENABLED` (403) raises `PermissionDeniedError`.
- `build_party_profile` for `POST /party/profile`: the cases of a person or company grouped into identities, quick mode (one answer) or full mode (202, then court refresh and analysis behind it). Accepts `idempotency_key`. Metered: at least 100 credits, at most 304 in quick mode; full mode is charged by usage up to `maxCredits`. Not available on the Free tier.
- `get_party_profile` for `GET /party/profile/{requestId}`: status, progress, credits and, once completed, the result of a full mode request. Free.
- `delete_audit_activity(before)` for `DELETE /audit`: permanently deletes the calling key's own activity before a UTC time. Cannot be undone. Never retried automatically after a network error or a 502, 503 or 504; a naive `datetime` raises `ValueError`.
- Typed models for the above (`PartyProfileResult`, `PartyProfileAccepted`, `PartyProfileRequestStatus`, `PartyProfileCase`, `AuditDeleteResult` and others), exported from the package root.
- Error codes `PARTY_PROFILE_FULL_UNAVAILABLE` (503, never retried) and `PARTY_PROFILE_TOO_MANY_ACTIVE` (429, not retried automatically) in `API_REFUSAL_CODES`. On `build_party_profile`, a 503 is retried (with `retry_posts`) only for `ACCOUNT_STANDING_UNAVAILABLE` and `ENTITLEMENT_UNAVAILABLE`.
- New optional response fields: `bench`, `courtRecordActs` and `courtRecordFir` on `CaseDetails` (so also on `get_case_by_cnr`); `courtRecordActs`, `courtRecordFir` and `sameMatter` on `PartyScreenMatch`; `sameMatter` on search and semantic search hits; `SearchCasesResult.cnr_lookup` (the response's `cnrLookup`) on a `cnr` search that returned no case; `withheld` on change feed and watchlist events; `unavailableReason` on order rows, and `ordersTextWithheld` and `withheldReason` on `list_case_orders`.
- `CnrLookup.case` is typed as `CaseDetails`.

### Notes

- Some matters are never listed on the citing list, and a page can hold fewer rows than `limit`, or none, while `hasMore` is true. Keep following `nextCursor`. Search, resolve, lookup and citing list calls have a lower per minute limit and return 429 above it.
- The citing list is not exhaustive, and an empty list does not mean no judgment applied the provision. Check repeal status before relying on an act or provision.
- `get_act_history` is act level and does not map old sections to new ones.

## [0.5.0]

Adds CNR lookup and case monitoring (API docs 1.3.0).

### Added

- `get_case_by_cnr(cnr, fetch=False)` for `GET /cases/by-cnr/{cnr}`, and a `cnr` argument on `search_cases` (exact match; `query` is now optional when `cnr` is given).
- Watchlists: `create_watchlist`, `list_watchlists`, `get_watchlist`, `update_watchlist`, `delete_watchlist`, `add_watchlist_items`, `list_watchlist_items`, `remove_watchlist_item`.
- Change feed: `list_changes`, `list_watchlist_events`, with generators `iter_changes` and `iter_watchlist_events` that walk pages until caught up.
- Webhooks: `create_webhook`, `list_webhooks`, `get_webhook`, `update_webhook`, `delete_webhook`, `rotate_webhook_secret`, `test_webhook`, `list_webhook_deliveries`, `retry_webhook_delivery`, plus `iter_watchlists`, `iter_watchlist_items`, `iter_webhooks` and `iter_webhook_deliveries`.
- `verify_webhook_signature(raw_body, header, secret, tolerance_seconds=300)` and `WebhookSignatureError`.
- `normalize_cnr` and `assert_cnr`, exported, matching the server's CNR normalisation.
- Typed models for all of the above, including `ChangeEvent` and `CursorListResult`.
- `PATCH` and `DELETE` support in the HTTP layer. `DELETE` is retried like `GET`; `PATCH` and all new `POST` calls follow the `retry_posts` rule and send an `Idempotency-Key` when it is in effect.

### Changed

- `get_case_by_cnr` with `fetch=True`: the call that starts the fetch returns `pending` and is free; the poll that returns the record is the one 1 credit charge. `requestId` is opaque and is polled via the same call, not `get_timeline`.
- `ITEM_NOT_FOUND` documented; `Webhook.secretRotating` added.
- `request_timeline(refresh=True)` now costs 1 credit (it was 20). Docs and docstrings updated.
- `search_cases` takes `query` as optional (required unless `cnr` is set).
- `User-Agent` is `courtmesh-python/0.5.0`.
- Project URLs now point at `github.com/thinkscoop-technologies/courtmesh-python`.
- `WatchlistItem.status` gains `unavailable` (a case taken down at a party's request: `caseId`, `court`, `title`, `snapshot`, `lastCheckedAt` and `lastChangedAt` are `None`, no events are sent). Adding a taken down CNR returns `not_found`.
- Documented the daily add allowance per account (Free 50, Pay As You Go 5,000, Scale 50,000, Enterprise 500,000) on top of the daily limit on new CNRs; both report `cap_exceeded`. The watch cap counts distinct CNRs across all lists.
- Documented the 24 hour cooldown after the court portal has nothing for a CNR: watchlist adds return `not_found` and `get_case_by_cnr(..., fetch=True)` raises `NotFoundError` without a new fetch.
- Documented that `search_cases(cnr=...)` returns one ordinary search hit, that `case.tracking_started` is sent after the first fresh refresh, that a burst announces the newest 20 orders and never orders dated more than 7 days before watching began, that feed cursors are opaque and `since` is converted once, and that dates are `YYYY-MM-DD` with 9999 meaning no date.
- Documented webhook behaviour: `test_webhook` is sent even to a disabled endpoint, 10 second deadline and 64 KB read per attempt, never attempted deliveries older than 24 hours are `failed` with `lastError: "expired"`, a webhook created without `events` echoes the full default `case.*` list, and `watchlist_ids=[]` means all lists. `create_webhook` honours `idempotency_key`.
- Validation error `details` is a list of `"path: message"` strings for query and body alike.

## [0.4.1]

Live QA pass against the redeployed production API
(`research.courtmesh.ai`, 2026-09-19) and its updated OpenAPI spec. All items
below were confirmed with live calls against an Enterprise key, not only
against the spec.

### Added

- `User-Agent: courtmesh-python/0.4.1` sent on every request.
- `UsageTierLimits["published"]`: this tier's number in the OpenAPI
  rate-limit table, distinct from `requestsPerMinute` (the limit applied to this
  key).
- `CoverageMeta["snapshotAgeSeconds"]`, `["cacheAgeSeconds"]` and
  `["stale"]`, replacing a single `ageSeconds` field that never actually
  existed on the wire.
- `CoverageCourt["courtType"]`, now explicitly `Optional[str]` (added to the
  live schema 2026-09-19).
- `HealthCheckEntry`, `HealthCheckResult`, `PartyScreenRedactedName` and
  `PartyScreenRedactedAliases` (carried forward from the interim QA branch,
  re-verified live, see Changed below).

### Changed

- **Breaking:** `AuditHit["userAgent"]` removed; the redeployed server no
  longer sends it at all (dropped for privacy alongside raw `ipAddress`,
  which never appeared on the wire in the first place). `AuditHit["ipHash"]`
  (a SHA-256 digest of the caller's IP) is retained; a same-day interim fix
  had renamed `ipAddress` to `ipHash`, which remains correct.
- **Breaking:** `UsageTierLimits`: every field but `requestsPerMinute` (and
  now `published`) is `Optional`, matching the live response. `limits` itself is confirmed always a
  populated dict, never `None`.
- **Breaking:** `CoverageCourt`/`CoverageByCourtType`/`CoverageDistrictCourts`
  date and `businessDaysBehind` fields are now `Optional`, matching the live
  schema.
- `AuditHit["metadata"]` is now `Optional[Dict[str, Any]]`; observed `None`
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

Targets the API's account-introspection endpoints
(`GET /usage`, `GET /me`, `GET /audit`), the public reference endpoints
(`GET /reference/courts`, `GET /reference/case-types`), the new
`POST /party/screen/batch` endpoint, and the `Idempotency-Key` contract
being rolled out across the five job/charge-triggering POST endpoints.

### Added

- `get_usage()`: `GET /usage`, this key's tier, wallet balance,
  the per tier limits, the current Asia/Kolkata billing period and a
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
  `GET /health?deep=1`: also checks each backing dependency's
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

Targets the API as of 2026-09-18.

### Added

- `cursor` request field on `search_cases`, and `pagination["nextCursor"]`
  can now be a signed opaque string as well as the legacy raw list. `searchAfter` is
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
  `adjudicationsRun`; `adjudicationsRun` moved to a top level field of
  `PartyScreenResult` (matching the server's actual response shape).
- **Breaking:** `semantic_search`'s `caseNumber` argument is now a single
  digits-only string (was a string-or-list, validated but silently ignored
  by the handler for any value that was not already digits-only); `judges`/
  `judge` are now aliases collapsed into the single `judgeName` field sent
  on the wire, matching what AI search actually matches against
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
