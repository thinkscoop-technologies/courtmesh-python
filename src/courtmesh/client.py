"""The CourtMesh API client."""
from __future__ import annotations

import json as _json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional, Sequence, Union
from urllib.parse import quote

import requests

from ._http import DEFAULT_MAX_RETRIES, DEFAULT_MAX_RETRY_AFTER_SECONDS, DEFAULT_TIMEOUT, HTTPTransport
from .errors import CourtMeshError
from .cause_lists import (
    CHECK_MAX_DAYS,
    LISTINGS_MAX_DAYS,
    CauseListCheckData,
    CauseListCourtList,
    CauseListing,
    CauseListPage,
    MatterCauseListings,
    assert_check_body,
    assert_court_list_query,
    assert_date_range,
    assert_matter_id,
)
from .monitoring import cnr_for_request
from .models import (
    APIResponse,
    Act,
    ActHistory,
    ActResolution,
    ActSection,
    ActSectionEntry,
    ActSummary,
    ActsPageResult,
    AnalyzeResponse,
    AuditData,
    AuditDeleteResult,
    AuditResult,
    CaseAnalysisResponse,
    CaseDetails,
    CaseDocuments,
    CaseDocumentText,
    CnrRefreshBatch,
    CnrRefreshResult,
    CnrRefreshState,
    CaseTypeEntry,
    ChangeEvent,
    CitingCase,
    CitingCasesResult,
    CnrLookup,
    ConsolidatedAnalyzeResponse,
    CourtHierarchy,
    CoverageData,
    CursorListResult,
    HealthResponse,
    MeData,
    PartyProfileAccepted,
    PartyProfileRequestStatus,
    PartyProfileResult,
    PartyProfileWebhook,
    PartyScreenBatchResult,
    PartyScreenResult,
    PdfResponse,
    RelatedResponse,
    RequestTimelineResponse,
    SearchCasesResult,
    SectionLookup,
    SectionRow,
    SemanticSearchResult,
    TimelineJob,
    UsageData,
    Watchlist,
    WatchlistItem,
    Webhook,
    WebhookDelivery,
)

DEFAULT_BASE_URL = "https://research.courtmesh.ai/api/v1/prod"

# A single search page can legitimately return items on every attempt if a
# server bug always reports hasMore=True. This caps the pagination
# generators so a caller loop can never spin forever.
_MAX_SAFETY_PAGES = 10_000

# Per endpoint request timeout defaults (R4), in seconds. Endpoints not
# listed here use the client's general `timeout` (default 30).
_SEMANTIC_SEARCH_TIMEOUT = 630.0
_REQUEST_TIMELINE_TIMEOUT = 240.0
_ANALYZE_CONSOLIDATED_TIMEOUT = 300.0
_SCREEN_PARTY_TIMEOUT = 90.0
_PARTY_PROFILE_TIMEOUT = 90.0

# The only 503 codes of POST /party/profile documented as refused before any
# work or charge, and so safe to retry (with retry_posts). Any other 503 on
# that call, including PARTY_PROFILE_FULL_UNAVAILABLE and a debit whose
# outcome is unknown, is raised at once.
_PARTY_PROFILE_RETRYABLE_503_CODES = frozenset({"ACCOUNT_STANDING_UNAVAILABLE", "ENTITLEMENT_UNAVAILABLE"})

StrOrList = Union[str, Sequence[str]]
IntOrList = Union[int, str, Sequence[Union[int, str]]]


def _set_if_present(payload: Dict[str, Any], **fields: Any) -> None:
    for key, value in fields.items():
        if value is not None:
            payload[key] = value


def _seg(value: Any) -> str:
    """URL-encode one path segment."""
    return quote(str(value), safe="")


def _compact(**fields: Any) -> Dict[str, Any]:
    return {key: value for key, value in fields.items() if value is not None}


def _normalized_item(item: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(item)
    if "cnr" in normalized:
        normalized["cnr"] = cnr_for_request(normalized["cnr"])
    return normalized


def _changes_params(
    cursor: Optional[str],
    since: Optional[str],
    types: Optional[StrOrList],
    cnr: Optional[str],
    limit: Optional[int],
) -> Dict[str, Any]:
    return _compact(
        cursor=cursor,
        since=since,
        types=types if types is None or isinstance(types, str) else ",".join(types),
        cnr=cnr_for_request(cnr) if cnr is not None else None,
        limit=limit,
    )


def _include_params(include: Optional[Sequence[str]]) -> Optional[Dict[str, str]]:
    return {"include": ",".join(include)} if include else None


def _audit_before_param(before: Union[str, datetime]) -> str:
    """`before` for `DELETE /audit`: a string is sent as given (the server
    validates it); a datetime must carry a timezone and is sent in UTC. A
    naive datetime is refused rather than guessed at."""
    if isinstance(before, datetime):
        if before.tzinfo is None or before.utcoffset() is None:
            raise ValueError("before must carry a timezone, for example datetime(2026, 11, 5, tzinfo=timezone.utc).")
        return before.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if not isinstance(before, str) or not before.strip():
        raise ValueError("before is required: a date and time with Z or an offset, for example 2026-11-05T00:00:00Z.")
    return before.strip()


def _generate_idempotency_key() -> str:
    """A random UUID v4, used to auto-generate an `Idempotency-Key` when a
    caller has opted into `retry_posts` but did not supply their own key."""
    return str(uuid.uuid4())


class CourtMesh:
    """Client for the CourtMesh API.

    Example:
        with CourtMesh(api_key="cm-...") as cm:
            result = cm.search_cases(query="right to privacy")
            for hit in result.data:
                print(hit.get("title"))

    Retries, by default: a 429 whose `code` is `RATE_LIMITED` or
    `CONCURRENT_ANALYSIS_LIMIT` (never a daily or monthly cap code, see
    `courtmesh.errors.is_retryable_429_code`), and, for GET requests only,
    a 502/503/504 response or a connection/timeout error. See
    `retry_posts` to also retry POST requests, and `max_retry_after_seconds`
    for the cap on how long a 429 is retried automatically before this SDK
    gives up and raises instead of waiting.
    """

    DEFAULT_BASE_URL = DEFAULT_BASE_URL

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        session: Optional[requests.Session] = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        auth_header: str = "authorization",
        retry_posts: bool = False,
        max_retry_after_seconds: float = DEFAULT_MAX_RETRY_AFTER_SECONDS,
    ) -> None:
        """
        Args:
            api_key: your CourtMesh API key, for example `cm-...-....`. Falls
                back to the `COURTMESH_API_KEY` environment variable.
            base_url: API base URL, defaults to the production endpoint.
            session: an existing `requests.Session` to reuse, for example to
                share connection pooling or custom TLS settings. A new one
                is created when omitted.
            timeout: per request timeout in seconds. `semantic_search`,
                `request_timeline`, `analyze_consolidated` and
                `screen_party` each default to a longer per endpoint
                timeout instead (see their own docstrings); pass `timeout=`
                to any method call to override further. A client side
                timeout does not cancel the request server side and never
                triggers a refund.
            max_retries: how many times to retry a retryable failure before
                giving up.
            auth_header: `"authorization"` (default) sends
                `Authorization: Bearer <key>`. `"x-api-key"` sends
                `X-API-Key: <key>` instead. Both forms are accepted by the
                server, checked in that order.
            retry_posts: allow retrying a POST request after it has already
                reached the network (a connection/timeout error, or a
                502/503/504 response) (R3). Default False: a POST that may
                have already been received and acted on server side is not
                retried automatically, to avoid double charging or double
                running a job (analyze, party/screen, and similar). A 429
                response is a pre-flight refusal, so it is retried
                regardless of this setting. Overridable per call via that
                method's own `retry_posts=` argument.
            max_retry_after_seconds: caps how long this client will wait on
                a `Retry-After`/`retryAfter` it is honouring for a 429, in
                seconds. Default 60. When the advertised delay is longer
                than this (a daily or monthly cap can carry a `Retry-After`
                of up to a day), this SDK does not sleep and retry: it
                raises `RateLimitError` immediately, with `retry_after` set
                to the real (uncapped) delay the server advertised.
        """
        resolved_key = api_key or os.environ.get("COURTMESH_API_KEY")
        if not resolved_key:
            raise ValueError(
                "An API key is required. Pass api_key=, or set the "
                "COURTMESH_API_KEY environment variable."
            )
        if auth_header not in ("authorization", "x-api-key"):
            raise ValueError('auth_header must be "authorization" or "x-api-key".')

        self.api_key = resolved_key
        self.base_url = base_url.rstrip("/")
        self._transport = HTTPTransport(
            base_url=self.base_url,
            api_key=self.api_key,
            session=session,
            timeout=timeout,
            max_retries=max_retries,
            auth_header=auth_header,
            retry_posts=retry_posts,
            max_retry_after_seconds=max_retry_after_seconds,
        )

    def __enter__(self) -> "CourtMesh":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying session."""
        self._transport.close()

    @property
    def session(self) -> requests.Session:
        """The underlying `requests.Session`, for advanced customisation."""
        return self._transport.session

    def _resolve_idempotency_key(
        self, idempotency_key: Optional[str], retry_posts: Optional[bool]
    ) -> Optional[str]:
        """Resolves the `Idempotency-Key` to send for one of the five
        idempotency-aware POST methods: the caller's own explicit key, else
        an auto-generated UUID v4 when `retry_posts` is in effect for this
        call (the per-call override, falling back to the client's own
        default), else `None` (no header sent).
        """
        if idempotency_key:
            return idempotency_key
        effective_retry_posts = self._transport.retry_posts if retry_posts is None else retry_posts
        return _generate_idempotency_key() if effective_retry_posts else None

    # -- 1. GET /judges/search -------------------------------------------

    def search_judges(self, q: str = "", timeout: Optional[float] = None) -> APIResponse[List[str]]:
        """Search Supreme Court and High Court judge names.

        Args:
            q: free text, case insensitive substring match. Empty string
                returns the first 50 names from the combined list.
            timeout: per call timeout override, in seconds.

        Returns at most 50 matching names.
        """
        params: Dict[str, Any] = {}
        if q:
            params["q"] = q
        response = self._transport.request("GET", "/judges/search", params=params or None, timeout=timeout)
        body = self._transport.parse_envelope(response)
        return APIResponse(data=body.get("data", []), meta=body.get("meta", {}), request_id=body.get("requestId"), replayed=body.get("replayed"))

    # -- 2. POST /search/cases --------------------------------------------

    def search_cases(
        self,
        query: Optional[str] = None,
        court: Optional[StrOrList] = None,
        year: Optional[IntOrList] = None,
        caseType: Optional[StrOrList] = None,
        caseNumber: Optional[StrOrList] = None,
        judgeName: Optional[StrOrList] = None,
        judges: Optional[StrOrList] = None,
        judge: Optional[StrOrList] = None,
        fromDate: Optional[str] = None,
        toDate: Optional[str] = None,
        page: Optional[int] = None,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
        searchAfter: Optional[str] = None,
        sortBy: Optional[str] = None,
        timeout: Optional[float] = None,
        retry_posts: Optional[bool] = None,
        cnr: Optional[str] = None,
    ) -> SearchCasesResult:
        """Keyword search across Indian court records.

        Args:
            query: at least 1 character after trimming. Required unless
                `cnr` is given.
            cnr: exact CNR match (no fuzzy text matching). Any common
                spelling is accepted and normalised to the canonical 16
                characters before sending. When present, `query` is optional
                and ignored. The result is one ordinary search hit (or an
                empty list), not the full record: progress fields and
                `orderCount` are only on `get_case_by_cnr`. When no case
                comes back, `result.cnr_lookup` says what is happening
                with the CNR (`status` is `pending`, `not_found`,
                `cooldown`, `limit_reached` or `unavailable`).
            court, caseType, judgeName, judges, judge: a single string or a
                list of strings. `judgeName`, `judges` and `judge` are
                aliases for the same filter, the handler uses
                `judgeName or judges or judge`, in that order.
            year: an int (1947..current year), the string `"YYYY"`, or a
                list of those.
            caseNumber: filters the search to one case number. A list is
                accepted but only its first string element is used; the
                schema rejects more than one value rather than silently
                dropping the rest.
            fromDate, toDate: `YYYY-MM-DD`.
            page: 1 based, default 1. Ignored once `cursor` is supplied.
            limit: 1..100, default 20 (the Free tier's own max page size is
                20; higher tiers allow more, see `PAGE_LIMIT_EXCEEDED`).
            cursor: the signed, opaque cursor from a previous page's
                `pagination["nextCursor"]`. Prefer this over `page`/
                `searchAfter` for paging past the first screen; see
                `iter_search_cases`, which manages it for you. An invalid or
                query-mismatched cursor raises `ValidationError` with
                `code == "CURSOR_INVALID"` (400).
            searchAfter: deprecated legacy cursor mechanism. A
                JSON encoded array string (the raw sort tuple
                from a previous page's `pagination["nextCursor"]`). New
                integrations should use `cursor` instead.
            sortBy: `"relevance"`, `"recent"` or `"oldest"`, plus the
                deprecated alias `"date"` (resolved to `"recent"`, with a
                note in `meta["warnings"]`). The response's `meta["sortBy"]`
                reports which sort was actually applied.
            timeout: per call timeout override, in seconds.
            retry_posts: per call override of the client's `retry_posts`.
        """
        payload: Dict[str, Any] = {}
        if query is not None:
            payload["query"] = query
        if cnr is not None:
            payload["cnr"] = cnr_for_request(cnr)
        _set_if_present(
            payload,
            court=court,
            year=year,
            caseType=caseType,
            caseNumber=caseNumber,
            judgeName=judgeName,
            judges=judges,
            judge=judge,
            fromDate=fromDate,
            toDate=toDate,
            page=page,
            limit=limit,
            cursor=cursor,
            searchAfter=searchAfter,
            sortBy=sortBy,
        )
        response = self._transport.request(
            "POST", "/search/cases", json_body=payload, timeout=timeout, retry_posts=retry_posts
        )
        body = self._transport.parse_envelope(response)
        return SearchCasesResult(
            data=body.get("data", []),
            meta=body.get("meta", {}),
            pagination=body.get("pagination", {}),
            request_id=body.get("requestId"),
            cnr_lookup=body.get("cnrLookup"),
        )

    def iter_search_cases(
        self,
        query: str,
        limit: int = 20,
        max_pages: Optional[int] = None,
        **kwargs: Any,
    ) -> Iterator[Any]:
        """Yield every hit from `search_cases`, walking pages automatically.

        Stops when a page comes back empty or `pagination["hasMore"]` is
        false. `max_pages` caps how many pages are fetched (useful in
        tests or to bound cost); regardless, an internal safety cap
        (`_MAX_SAFETY_PAGES` pages) always applies so a server bug can
        never cause an infinite loop. Default page size is 20 (also the
        Free tier's own `maxPageSize`).

        Cursor-first: once a page's `pagination["nextCursor"]` comes back as
        a signed string, it is passed back as `cursor` on the next call
        rather than incrementing `page`. On the legacy path (`nextCursor`
        comes back as a raw list instead), this walks pages via
        `searchAfter` instead - either way you do not have to branch on
        the shape.

        Args:
            query: same as `search_cases`.
            limit: page size, 1..100.
            max_pages: optional cap on the number of pages fetched.
            **kwargs: any other `search_cases` filter (court, year, ...).
        """
        kwargs.pop("page", None)
        kwargs.pop("limit", None)
        cursor = kwargs.pop("cursor", None)
        search_after = kwargs.pop("searchAfter", None)
        current_page = 1
        pages_fetched = 0
        hard_cap = _MAX_SAFETY_PAGES if max_pages is None else min(max_pages, _MAX_SAFETY_PAGES)
        while pages_fetched < hard_cap:
            using_cursor = isinstance(cursor, str) and len(cursor) > 0
            result = self.search_cases(
                query,
                page=None if using_cursor else current_page,
                limit=limit,
                cursor=cursor,
                searchAfter=None if using_cursor else search_after,
                **kwargs,
            )
            items = result.data or []
            if not items:
                return
            for item in items:
                yield item
            pages_fetched += 1
            if not result.pagination.get("hasMore"):
                return

            next_cursor = result.pagination.get("nextCursor")
            if isinstance(next_cursor, str) and len(next_cursor) > 0:
                # Current mechanism: hand the signed cursor
                # straight back.
                cursor = next_cursor
                search_after = None
            elif isinstance(next_cursor, list) and len(next_cursor) > 0:
                # Legacy path: continue via a JSON-encoded searchAfter instead.
                cursor = None
                search_after = _json.dumps(next_cursor)
                next_page = result.pagination.get("page")
                current_page = (next_page if next_page is not None else current_page) + 1
            else:
                cursor = None
                next_page = result.pagination.get("page")
                current_page = (next_page if next_page is not None else current_page) + 1

    # -- 3. POST /search/cases/semantic ------------------------------------

    def semantic_search(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        page: Optional[int] = None,
        limit: Optional[int] = None,
        court: Optional[StrOrList] = None,
        caseType: Optional[StrOrList] = None,
        caseNumber: Optional[str] = None,
        judgeName: Optional[str] = None,
        judges: Optional[str] = None,
        judge: Optional[str] = None,
        year: Optional[IntOrList] = None,
        fromDate: Optional[str] = None,
        toDate: Optional[str] = None,
        timeout: Optional[float] = None,
        retry_posts: Optional[bool] = None,
    ) -> SemanticSearchResult:
        """AI search by meaning, with a language model filter extraction pre-step.

        This is billed as an AI interaction by the server. **Not available
        on the Free tier**: raises `PermissionDeniedError` with
        `code == "SEMANTIC_NOT_ALLOWED"` before any work or charge.

        Args:
            query: required, at least 3 characters after trimming.
            filters: the AI search's own filter keys, applied directly
                and taking precedence over both the top level fields below
                and whatever the language model inferred from `query`.
                Recognised keys: `court`, `caseType`, `caseYear`,
                `caseNumber`, `judgeName` (also accepts `judges`/`judge`,
                mapped to `judgeName`), `decisionDate` (`{"$gte": ..., "$lte": ...}`),
                `practiceArea`, `sourceCaseId`.
            page, limit: same semantics as `search_cases`.
            court, caseType, year, fromDate, toDate: merged into the
                effective filters at explicit-top-level precedence: each
                wins over whatever the language model inferred from `query`,
                but the matching key in `filters` (see above) wins over this.
            caseNumber: same precedence as `court` above. AI search
                filters case numbers numerically, so this must be a digits
                only string (e.g. `"1234"`); use `search_cases` to filter on
                a full case number string instead.
            judgeName: same precedence as `court` above. AI search
                matches a single judge name, so this accepts one string, not
                a list; `judges`/`judge` are aliases of this same field.
                Use `search_cases` to filter on several judges.

        Raises:
            ValueError: `caseNumber` was supplied and is not digits only.
            CourtMeshError: when the response body has `success: false`.
                This is a defensive fallback only: the server sends a
                proper non-200 status for a semantic search failure today,
                so this should never trigger in practice. Kept in case a
                future response ever starts streaming before failing.

        Note:
            When the cleaned query (after filter extraction) is shorter
            than 3 characters, the handler falls back to keyword search:
            `meta["fallbackMode"]` is set and `data` holds raw
            `CaseListItem` hits instead of watermarked semantic results.
        """
        if caseNumber is not None and not str(caseNumber).isdigit():
            raise ValueError(
                'Semantic search filters case numbers numerically, so caseNumber must be '
                'digits only (e.g. "1234"). Use search_cases to filter on a full case number string.'
            )
        judge_name_value = judgeName or judges or judge
        payload: Dict[str, Any] = {"query": query}
        _set_if_present(
            payload,
            filters=filters,
            page=page,
            limit=limit,
            court=court,
            caseType=caseType,
            caseNumber=caseNumber,
            judgeName=judge_name_value,
            year=year,
            fromDate=fromDate,
            toDate=toDate,
        )
        response = self._transport.request(
            "POST",
            "/search/cases/semantic",
            json_body=payload,
            timeout=_SEMANTIC_SEARCH_TIMEOUT if timeout is None else timeout,
            retry_posts=retry_posts,
        )
        body = self._transport.parse_envelope(response)
        if body.get("success") is False:
            raise CourtMeshError(
                body.get("error") or "Semantic search failed.",
                status_code=response.status_code,
                response_body=body,
            )
        return SemanticSearchResult(
            data=body.get("data", []),
            meta=body.get("meta", {}),
            pagination=body.get("pagination", {}),
            request_id=body.get("requestId"),
        )

    def iter_semantic_search(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 20,
        max_pages: Optional[int] = None,
        **kwargs: Any,
    ) -> Iterator[Any]:
        """Yield every result from `semantic_search`, walking pages automatically.

        Stops when a page comes back empty or `pagination["hasMore"]` is
        false, same safety cap as `iter_search_cases` applies.
        """
        kwargs.pop("page", None)
        kwargs.pop("limit", None)
        current_page = 1
        pages_fetched = 0
        hard_cap = _MAX_SAFETY_PAGES if max_pages is None else min(max_pages, _MAX_SAFETY_PAGES)
        while pages_fetched < hard_cap:
            result = self.semantic_search(
                query, filters=filters, page=current_page, limit=limit, **kwargs
            )
            items = result.data or []
            if not items:
                return
            for item in items:
                yield item
            pages_fetched += 1
            if not result.pagination.get("hasMore"):
                return
            next_page = result.pagination.get("page")
            current_page = (next_page if next_page is not None else current_page) + 1

    # -- 4. GET /cases/{id} -------------------------------------------------

    def get_case(
        self, case_id: str, timeout: Optional[float] = None, include: Optional[Sequence[str]] = None
    ) -> APIResponse[CaseDetails]:
        """Fetch case details by 24 character hexadecimal case id or caseNumber.

        The server tries a case id lookup first and falls back to a
        caseNumber lookup. The response deliberately excludes analysis
        fields, use `get_case_analysis` for those.

        Pass `include=["hearings", "advocates"]` for hearing history and
        advocates, at no extra charge. Either can come back None when we hold
        no such record for this case, and empty when we hold it and it lists
        none.
        """
        path = "/cases/{}".format(quote(str(case_id), safe=""))
        response = self._transport.request("GET", path, params=_include_params(include), timeout=timeout)
        body = self._transport.parse_envelope(response)
        return APIResponse(data=body.get("data", {}), meta=body.get("meta", {}), request_id=body.get("requestId"), replayed=body.get("replayed"))

    # -- 5. GET /cases/{id}/analysis ----------------------------------------

    def get_case_analysis(self, case_id: str, timeout: Optional[float] = None) -> APIResponse[CaseAnalysisResponse]:
        """Fetch the AI analysis for a case, if one exists.

        Check `data["hasAnalysis"]`: when False there is only a `message`,
        when True the full `analysis` object is present. Not available on
        the Free tier (`PermissionDeniedError`, `code == "API_TIER_NOT_ALLOWED"`).
        """
        path = "/cases/{}/analysis".format(quote(str(case_id), safe=""))
        response = self._transport.request("GET", path, timeout=timeout)
        body = self._transport.parse_envelope(response)
        return APIResponse(data=body.get("data", {}), meta=body.get("meta", {}), request_id=body.get("requestId"), replayed=body.get("replayed"))

    # -- 6. GET /cases/{id}/related -----------------------------------------

    def get_related(self, case_id: str, timeout: Optional[float] = None) -> APIResponse[RelatedResponse]:
        """Fetch related documents and derived timeline for a case.

        Related documents are every case document sharing the same
        `caseNumber` (limit 50). The timeline only includes documents that
        have both a decisionDate and a stored PDF.
        """
        path = "/cases/{}/related".format(quote(str(case_id), safe=""))
        response = self._transport.request("GET", path, timeout=timeout)
        body = self._transport.parse_envelope(response)
        return APIResponse(data=body.get("data", {}), meta=body.get("meta", {}), request_id=body.get("requestId"), replayed=body.get("replayed"))

    # -- 7. GET /cases/{id}/pdf ----------------------------------------------

    def get_case_pdf(self, case_id: str, timeout: Optional[float] = None) -> APIResponse[PdfResponse]:
        """Fetch a time limited download link for the case PDF.

        `data["pdfUrl"]` is a directly fetchable HTTPS link on the CourtMesh
        API host, valid for `data["expiresIn"]` seconds (3600). It carries its
        own signed token, so it needs no API key and no decryption, and
        fetching it costs no credits.

        Failure codes: `CASE_NOT_FOUND` (404), `CASE_RESTRICTED` (403),
        `PDF_NOT_STORED` (404, no stored document - `request_timeline` with
        `refresh=True` may fetch one for High Court and District Court
        cases; see `response_body["hint"]`).
        """
        path = "/cases/{}/pdf".format(quote(str(case_id), safe=""))
        response = self._transport.request("GET", path, timeout=timeout)
        body = self._transport.parse_envelope(response)
        return APIResponse(data=body.get("data", {}), meta=body.get("meta", {}), request_id=body.get("requestId"), replayed=body.get("replayed"))

    # -- 8. POST /cases/{id}/analyze ------------------------------------------

    def analyze_case(
        self,
        case_id: str,
        force: bool = False,
        allow_remote_fetch: bool = False,
        timeout: Optional[float] = None,
        retry_posts: Optional[bool] = None,
        idempotency_key: Optional[str] = None,
    ) -> APIResponse[AnalyzeResponse]:
        """Start AI analysis for a case. Asynchronous.

        On success this normally returns HTTP 202 with
        `{"message": "Analysis has been started", "status": "processing"}`.
        Poll `get_case` after 30-60 seconds to see whether it finished. If
        an analysis already exists and `force` is not set, the server
        instead returns HTTP 200 with the existing analysis and
        `alreadyExists: True`.

        Args:
            force: re-run analysis even if one already exists.
            allow_remote_fetch: required (`True`) when the only way to
                analyze this case is fetching its document from an external
                URL (no stored text and no stored document). Not
                available on the Free tier and the target host must be on
                the server's allowlist (`PermissionDeniedError` with
                `code == "REMOTE_FETCH_NOT_ALLOWED"` either way). Adds a
                credit surcharge on top of the base analyze price, charged
                once at admission.
            idempotency_key: sent as the `Idempotency-Key` header (1 to 128
                characters, `[A-Za-z0-9_.-]`, scoped per API key for 24
                hours). A replayed call with the same key and the same body
                returns the stored response again (`result.replayed`
                becomes `True`, no new charge); the same key with a
                different body raises `ConflictError` with
                `code == "IDEMPOTENCY_KEY_REUSED"`. When omitted, and
                `retry_posts` (this call's override, or the client's own
                default) is in effect, a random UUID v4 is generated for
                you, so an automatic retry of this exact call is always
                safe from a double charge or a double-run job.
        """
        path = "/cases/{}/analyze".format(quote(str(case_id), safe=""))
        payload: Dict[str, Any] = {"force": force}
        if allow_remote_fetch:
            payload["allowRemoteFetch"] = True
        response = self._transport.request(
            "POST",
            path,
            json_body=payload,
            timeout=timeout,
            retry_posts=retry_posts,
            idempotency_key=self._resolve_idempotency_key(idempotency_key, retry_posts),
        )
        body = self._transport.parse_envelope(response)
        return APIResponse(data=body.get("data", {}), meta=body.get("meta", {}), request_id=body.get("requestId"), replayed=body.get("replayed"))

    # -- 9. POST /cases/{id}/analyze-consolidated -----------------------------

    def analyze_consolidated(
        self,
        case_id: str,
        force: bool = False,
        timeout: Optional[float] = None,
        retry_posts: Optional[bool] = None,
        idempotency_key: Optional[str] = None,
    ) -> APIResponse[ConsolidatedAnalyzeResponse]:
        """Run consolidated AI analysis. Synchronous and slow (up to 300s
        by default, see `timeout`).

        Analyses the current case plus related documents: for a High
        Court case, the current case plus the latest 5 orders; for a
        Supreme Court case, up to 20 documents sharing the same
        caseNumber.

        Args:
            force: re-run even if a consolidated analysis already exists.
            timeout: per call timeout override, in seconds. Defaults to 300.
            idempotency_key: see `analyze_case`.
        """
        path = "/cases/{}/analyze-consolidated".format(quote(str(case_id), safe=""))
        response = self._transport.request(
            "POST",
            path,
            json_body={"force": force},
            timeout=_ANALYZE_CONSOLIDATED_TIMEOUT if timeout is None else timeout,
            retry_posts=retry_posts,
            idempotency_key=self._resolve_idempotency_key(idempotency_key, retry_posts),
        )
        body = self._transport.parse_envelope(response)
        return APIResponse(data=body.get("data", {}), meta=body.get("meta", {}), request_id=body.get("requestId"), replayed=body.get("replayed"))

    # -- 10. POST /request-timeline --------------------------------------------

    def request_timeline(
        self,
        case_id: str,
        refresh: bool = False,
        timeout: Optional[float] = None,
        retry_posts: Optional[bool] = None,
        idempotency_key: Optional[str] = None,
    ) -> APIResponse[RequestTimelineResponse]:
        """Request the orders timeline for a case. `case_id` must be the
        24 character hexadecimal case id.

        For Supreme Court cases this returns immediately with
        `status: "completed"`, `orderCount: 0`, `orders: []`, since those
        cases have no separate orders. If the timeline was already fetched
        today, the response has `cached: True` and the orders directly.
        Otherwise poll `get_timeline` with the returned `requestId`.

        Args:
            refresh: force a live fetch from the court portal instead of
                serving the last stored read. Default False. Costs 1
                credit, the same as a stored read (it was 20 before 0.5.0);
                `result.meta["liveFetch"]` says whether live work happened.
                Not available on the Free tier
                (`PermissionDeniedError`, `code == "LIVE_FETCH_NOT_ALLOWED"`)
                and capped per day per tier
                (`RateLimitError`, `code == "LIVE_FETCH_LIMIT_REACHED"`).
                `result.data["liveFetchSupported"]` comes back `False` when
                this case's court does not support a live refresh at all.
            timeout: per call timeout override, in seconds. Defaults to 240.
            idempotency_key: see `analyze_case`.
        """
        payload: Dict[str, Any] = {"case_id": case_id}
        if refresh:
            payload["refresh"] = True
        response = self._transport.request(
            "POST",
            "/request-timeline",
            json_body=payload,
            timeout=_REQUEST_TIMELINE_TIMEOUT if timeout is None else timeout,
            retry_posts=retry_posts,
            idempotency_key=self._resolve_idempotency_key(idempotency_key, retry_posts),
        )
        body = self._transport.parse_envelope(response)
        return APIResponse(data=body.get("data", {}), meta=body.get("meta", {}), request_id=body.get("requestId"), replayed=body.get("replayed"))

    # -- 11. GET /get-timeline/{requestId} --------------------------------------

    def get_timeline(self, request_id: str, timeout: Optional[float] = None) -> APIResponse[TimelineJob]:
        """Poll the job created by `request_timeline`.

        `data["result"]` is omitted whenever `data["totalOrderCount"]` is
        present.
        """
        path = "/get-timeline/{}".format(quote(str(request_id), safe=""))
        response = self._transport.request("GET", path, timeout=timeout)
        body = self._transport.parse_envelope(response)
        return APIResponse(data=body.get("data", {}), meta=body.get("meta", {}), request_id=body.get("requestId"), replayed=body.get("replayed"))

    # -- 12. GET /health ----------------------------------------------------

    def health(self, deep: bool = False, timeout: Optional[float] = None) -> HealthResponse:
        """Check API health. No auth required, rate limited by the
        public health limiter.

        The plain form (`deep=False`, default) is a cheap liveness probe: no
        dependency calls, always fast, always HTTP 200 while the process is
        up. Pass `deep=True` to also check each backing dependency's
        standing (each bounded to 1s) - `status` then also reports
        `"degraded"`, and HTTP 503 (`status == "unhealthy"`) when a hard
        dependency is down.

        Unlike every other endpoint, the response is not enveloped in
        `data`, this method returns the body directly.
        """
        params = {"deep": "1"} if deep else None
        response = self._transport.request("GET", "/health", params=params, require_auth=False, timeout=timeout)
        body = self._transport.parse_envelope(response)
        return body

    # -- 13. POST /party/screen ----------------------------------------------

    def screen_party(
        self,
        name: str,
        entityType: str,
        purpose: str,
        aliases: Optional[List[str]] = None,
        identifiers: Optional[Dict[str, Any]] = None,
        address: Optional[Dict[str, Any]] = None,
        knownPersons: Optional[List[str]] = None,
        court: Optional[StrOrList] = None,
        since: Optional[str] = None,
        limit: Optional[int] = None,
        adjudicate: Optional[bool] = None,
        displayThreshold: Optional[float] = None,
        timeout: Optional[float] = None,
        retry_posts: Optional[bool] = None,
        idempotency_key: Optional[str] = None,
    ) -> APIResponse[PartyScreenResult]:
        """Screen a person or company name against the case law corpus for
        litigation, insolvency and related court records. Requires an API
        key.

        Costs 100 credits when matches are found, 20 when none are, plus a
        flat surcharge only when `result.data["adjudicationsRun"] > 0`
        (requesting `adjudicate=True` alone does not guarantee a model call
        happened - every candidate may already have been decided
        deterministically - so it does not by itself bill the surcharge
        either). `adjudicate=True` is not available on the Free tier
        (`PermissionDeniedError`, `code == "API_TIER_NOT_ALLOWED"`). Every
        priced endpoint including this one pre-flight reserves the charge
        before doing any work: a shortfall raises `InsufficientCreditsError`
        (402) before the screen runs.

        DPDP note: `purpose` is required and is the only thing about the
        query the server retains in its logs; `name`, `aliases`,
        `knownPersons`, `identifiers` and `address` are never logged. The
        results are drawn entirely from public court records, not from or
        cross-checked against any private database. A screen is not an
        identity check: it tells you whether a name (optionally narrowed
        by identifiers, address or known associates) appears in litigation
        or insolvency records, it does not verify who a person or company
        actually is.

        Args:
            name: required, 2 to 200 characters.
            entityType: `"person"` or `"company"`.
            purpose: required, one of `"kyc"`, `"bgv"`, `"due_diligence"`,
                `"litigation"`, `"research"`, `"compliance"`.
            aliases: alternate spellings or names, at most 7.
            identifiers: `{"pan": ..., "gstin": ..., "cin": ..., "llpin": ...}`,
                all optional.
            address: `{"city": ..., "state": ..., "stateCode": ...}`.
            knownPersons: names of persons known to be associated with
                this party, improves disambiguation for common names.
            court: a single court name or a list of them.
            since: `YYYY-MM-DD`, only cases on or after this date are
                considered.
            limit: 1 to 100, default 40.
            adjudicate: run LLM adjudication on ambiguous candidates.
                Default False.
            displayThreshold: minimum calibrated confidence score, 0 to 1,
                required for a candidate to appear in `data["matches"]`
                rather than `data["relatedButUnverified"]`.
            timeout: per call timeout override, in seconds. Defaults to 90.
            idempotency_key: see `analyze_case`.

        Returns:
            `result.data["summary"]["verdict"]` is one of `"matches_found"`
            (describes what was found internally, independent of
            `displayThreshold`: raising the threshold can leave `matches`
            empty, `summary["matchCount"] == 0`, while the verdict is still
            `"matches_found"`), `"no_matches_found"` (only when
            `result.data["coverage"]["exhaustive"]` is True and nothing was
            withheld), or `"inconclusive"` (always returned when `since` was
            supplied, since it is a best-effort filter and completeness can
            never be certified either way). `result.data["notice"]` links
            the case removal / takedown policy;
            `result.data["coverage"]["someRecordsWithheld"]` is True when
            one or more otherwise-matching cases were removed from the
            results because they are under a takedown order.
        """
        payload: Dict[str, Any] = {"name": name, "entityType": entityType, "purpose": purpose}
        _set_if_present(
            payload,
            aliases=aliases,
            identifiers=identifiers,
            address=address,
            knownPersons=knownPersons,
            court=court,
            since=since,
            limit=limit,
            adjudicate=adjudicate,
            displayThreshold=displayThreshold,
        )
        response = self._transport.request(
            "POST",
            "/party/screen",
            json_body=payload,
            timeout=_SCREEN_PARTY_TIMEOUT if timeout is None else timeout,
            retry_posts=retry_posts,
            idempotency_key=self._resolve_idempotency_key(idempotency_key, retry_posts),
        )
        body = self._transport.parse_envelope(response)
        return APIResponse(data=body.get("data", {}), meta=body.get("meta", {}), request_id=body.get("requestId"), replayed=body.get("replayed"))

    # -- 14. GET /coverage ----------------------------------------------------

    def get_coverage(self, timeout: Optional[float] = None) -> APIResponse[CoverageData]:
        """Fetch corpus coverage and freshness stats: totals, by court
        type, by year, per court, and a rolled up District Courts row.

        No API key is required for this endpoint, but this client always
        has one (the constructor requires it) and sends it along anyway.
        Server side cached for up to 6 hours. Most fields are optional, so read them with `.get()`,
        since a court or year row may not report every stat.
        """
        response = self._transport.request("GET", "/coverage", timeout=timeout)
        body = self._transport.parse_envelope(response)
        return APIResponse(data=body.get("data", {}), meta=body.get("meta", {}), request_id=body.get("requestId"), replayed=body.get("replayed"))

    # -- 15. GET /usage ---------------------------------------------------------

    def get_usage(self, timeout: Optional[float] = None) -> APIResponse[UsageData]:
        """Report this API key's tier, wallet balance, per period limits
        and per endpoint call volume for the current Asia/Kolkata calendar
        month.

        Unmetered like every other account introspection call: checking
        your own usage never itself burns a credit.
        """
        response = self._transport.request("GET", "/usage", timeout=timeout)
        body = self._transport.parse_envelope(response)
        return APIResponse(data=body.get("data", {}), meta=body.get("meta", {}), request_id=body.get("requestId"), replayed=body.get("replayed"))

    # -- 16. GET /me --------------------------------------------------------

    def me(self, timeout: Optional[float] = None) -> APIResponse[MeData]:
        """The calling account's own id, email, name, role and (if any)
        organization id."""
        response = self._transport.request("GET", "/me", timeout=timeout)
        body = self._transport.parse_envelope(response)
        return APIResponse(data=body.get("data", {}), meta=body.get("meta", {}), request_id=body.get("requestId"), replayed=body.get("replayed"))

    # -- 17. GET /audit -------------------------------------------------------

    def audit(
        self,
        organizationId: Optional[str] = None,
        userId: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        startDate: Optional[str] = None,
        endDate: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> AuditResult:
        """Fetch this API key's own logged calls (or, for an org admin, an
        organization's), with summary stats and a top-endpoints breakdown.

        Args:
            organizationId: must be the caller's own organization, or
                `PermissionDeniedError`.
            userId: must be the caller's own id, or (for an org admin) a
                teammate's, or `PermissionDeniedError`.
            limit: 1 to 200, default 50.
            offset: default 0.
            startDate: ISO 8601.
            endDate: ISO 8601.
        """
        params: Dict[str, Any] = {}
        _set_if_present(
            params,
            organizationId=organizationId,
            userId=userId,
            limit=limit,
            offset=offset,
            startDate=startDate,
            endDate=endDate,
        )
        response = self._transport.request("GET", "/audit", params=params or None, timeout=timeout)
        body = self._transport.parse_envelope(response)
        return AuditResult(
            data=body.get("data", {}),
            pagination=body.get("pagination", {}),
            request_id=body.get("requestId"),
        )

    # -- DELETE /audit (API 1.8.0) ----------------------------------------------

    def delete_audit_activity(
        self, before: Union[str, datetime], timeout: Optional[float] = None
    ) -> APIResponse[AuditDeleteResult]:
        """Permanently delete this API key's own activity before a time.

        WARNING: this cannot be undone. The calls before `before` are no
        longer listed by `audit()`, and the request details kept with them
        for your account (what was sent, IP address, user agent) are erased.
        Only the calling key's own activity is touched; other keys on the
        account are not. What you were charged stays on your invoices,
        credit balance and usage totals. A separate security log keeps its
        own record of account activity.

        Needs the `account` scope, like `audit()`. Free and unmetered.

        A large history is removed in parts: when `result.data["complete"]`
        is False, call this again with the same `before` to finish.
        Repeating a request is safe.

        Never retried automatically once the request may have reached the
        server: a connection or timeout error, or a 502, 503 or 504
        response, is raised at once (a connection or timeout error as
        `CourtMeshError` with no `status_code`), since the outcome is then
        unknown. Check with `audit()` before sending it again. A 429
        `RATE_LIMITED` is a refusal before any work and is retried as usual.

        Args:
            before: a full date and time with `Z` or an offset, for example
                `"2026-11-05T00:00:00Z"`, not in the future. A `datetime`
                must carry a timezone (a naive one raises `ValueError`) and
                is sent in UTC.
            timeout: per call timeout override, in seconds.

        Returns:
            `result.data`: `before` (the time used, in UTC), `removed` (calls
            removed by this request), `complete` and `note`.

        Raises:
            ValidationError: `before` missing, not a full date and time, or
                in the future (400, `VALIDATION_ERROR`).
            PermissionDeniedError: the key lacks the `account` scope, or the
                account, organisation or source IP may not make this call
                (403).
            ServerError: the delete failed and nothing was charged (500).
        """
        params = {"before": _audit_before_param(before)}
        response = self._transport.request(
            "DELETE", "/audit", params=params, timeout=timeout, retry_after_dispatch=False
        )
        return self._envelope(response)

    # -- 18. GET /reference/courts ----------------------------------------------

    def reference_courts(self, timeout: Optional[float] = None) -> APIResponse[CourtHierarchy]:
        """The court taxonomy accepted by `court` filters elsewhere in this
        API: the 4 court types, courts per type, and display names per
        court. No API key required. Cached for 1 hour server side.
        """
        response = self._transport.request("GET", "/reference/courts", require_auth=False, timeout=timeout)
        body = self._transport.parse_envelope(response)
        return APIResponse(data=body.get("data", {}), meta=body.get("meta", {}), request_id=body.get("requestId"), replayed=body.get("replayed"))

    # -- 19. GET /reference/case-types -------------------------------------------

    def reference_case_types(self, timeout: Optional[float] = None) -> APIResponse[List[CaseTypeEntry]]:
        """Every `caseType` value accepted elsewhere in this API,
        deduplicated by code and sorted. No API key required, same caching
        as `reference_courts`.
        """
        response = self._transport.request("GET", "/reference/case-types", require_auth=False, timeout=timeout)
        body = self._transport.parse_envelope(response)
        return APIResponse(data=body.get("data", []), meta=body.get("meta", {}), request_id=body.get("requestId"), replayed=body.get("replayed"))

    # -- 20. POST /party/screen/batch --------------------------------------------

    def screen_party_batch(
        self,
        items: List[Dict[str, Any]],
        purpose: str,
        entityType: Optional[str] = None,
        adjudicate: Optional[bool] = None,
        timeout: Optional[float] = None,
        retry_posts: Optional[bool] = None,
        idempotency_key: Optional[str] = None,
    ) -> APIResponse[PartyScreenBatchResult]:
        """Screen up to 25 names in one call.

        Each item is independently priced and can independently fail
        without failing the whole batch - check `"ok"` on each entry in
        `result.data["results"]`. Not available on the Free tier. LLM
        adjudication is not supported here (`adjudicate` may only be
        `False`/omitted); use `screen_party` one at a time for that. See
        `screen_party` for the DPDP note: `purpose` is required and is the
        only thing about the query the server retains in its logs.

        Args:
            items: 1 to 25 dicts, each shaped like `screen_party`'s own
                arguments: `{"clientRef": ..., "name": ..., "aliases": ...,
                "entityType": ..., "identifiers": ..., "address": ...,
                "knownPersons": ..., "court": ..., "since": ..., "limit": ...,
                "displayThreshold": ...}`. `clientRef` is optional and is
                only ever echoed back on the matching result item, to help
                you line results up with requests; `entityType` falls back
                to this call's own `entityType` when omitted on an item.
            purpose: required, same values as `screen_party`.
            entityType: default `entityType` applied to any item that does
                not specify its own.
            adjudicate: batch adjudication is not supported; only `False`
                or `None` may be passed here.
            idempotency_key: see `analyze_case`.
        """
        payload: Dict[str, Any] = {"items": items, "purpose": purpose}
        _set_if_present(payload, entityType=entityType, adjudicate=adjudicate)
        response = self._transport.request(
            "POST",
            "/party/screen/batch",
            json_body=payload,
            timeout=_SCREEN_PARTY_TIMEOUT if timeout is None else timeout,
            retry_posts=retry_posts,
            idempotency_key=self._resolve_idempotency_key(idempotency_key, retry_posts),
        )
        body = self._transport.parse_envelope(response)
        return APIResponse(data=body.get("data", {}), meta=body.get("meta", {}), request_id=body.get("requestId"), replayed=body.get("replayed"))

    # -- POST /party/profile, GET /party/profile/{requestId} (API 1.8.0) ----

    def build_party_profile(
        self,
        name: str,
        entityType: str,
        purpose: str,
        aliases: Optional[List[str]] = None,
        identifiers: Optional[Dict[str, Any]] = None,
        address: Optional[Dict[str, Any]] = None,
        knownPersons: Optional[List[str]] = None,
        court: Optional[StrOrList] = None,
        since: Optional[str] = None,
        limit: Optional[int] = None,
        adjudicate: Optional[bool] = None,
        displayThreshold: Optional[float] = None,
        minConfidence: Optional[str] = None,
        include: Optional[Sequence[str]] = None,
        allowUnconfirmedPrimary: Optional[bool] = None,
        mode: Optional[str] = None,
        maxCredits: Optional[int] = None,
        webhook: Optional[PartyProfileWebhook] = None,
        timeout: Optional[float] = None,
        retry_posts: Optional[bool] = None,
        idempotency_key: Optional[str] = None,
    ) -> APIResponse[Union[PartyProfileResult, PartyProfileAccepted]]:
        """Build a litigation profile of a person or company in one call:
        everything `screen_party` finds, grouped into identities, with the
        cases of the primary identity enriched (court, bench, status, next
        hearing, acts and FIR as the court record states them, documents
        with links) and a summary built by code. Not available on the Free
        tier (`PermissionDeniedError`, `code == "API_TIER_NOT_ALLOWED"`).

        Two modes. The server defaults to `full` where full mode is
        available, else `quick`, so pass `mode` when you need one answer
        shape:

        - `mode="quick"`: the profile in one answer (200).
          `result.data` is a `PartyProfileResult`.
        - `mode="full"`: answers 202 at once and the work runs behind it:
          every case of the first identity with a CNR is refreshed from its
          court, each case is analysed, then the party is analysed.
          `result.data` is a `PartyProfileAccepted` (`requestId`, `status`
          `"queued"`, `statusUrl`, `maxCredits`). Read the outcome with
          `get_party_profile(result.data["requestId"])`, or pass `webhook`.
          At most 3 full profiles may be queued or running per account
          (`RateLimitError`, `code == "PARTY_PROFILE_TOO_MANY_ACTIVE"`,
          not retried automatically). Where full mode is not available it
          raises `ServiceUnavailableError` with
          `code == "PARTY_PROFILE_FULL_UNAVAILABLE"` and nothing is charged.

        A quick answer carries `subject`; a full mode answer carries
        `statusUrl` and `requestId` instead.

        Pricing, quick mode (metered): every profile costs at least 100
        credits, even when no case is found. Above that it is priced by
        what the call used: 1 credit per internal search call (at most 24),
        1 per case record read and 1 per documents listing that offers a
        document (at most 100 cases are enriched), plus each AI review call
        priced by its tokens and never above an 80 credit allowance. One
        call never costs more than 304 credits. `meta["creditsCharged"]` is
        what left the wallet and `meta["creditsBreakdown"]` itemises it.
        Before the call runs, the balance is checked against the most this
        request could cost; a short balance raises
        `InsufficientCreditsError` (402) and nothing runs. A refused or
        failed call charges nothing.

        Pricing, full mode: charged by actual usage one stage at a time: the
        search stage at the quick mode rates, 1 credit per court refresh
        started (retries are free), each new, rewritten or short case
        analysis by its tokens (a short one is about 5 credits), each
        reused analysis at the price of reading a stored analysis, and the
        party analysis by its tokens. An analysis that fails or is cut off
        is not charged. `maxCredits` (100 to 5000; default 1000, or your
        balance if that is lower) is the most the request may spend; the
        balance must cover it when the request is accepted. Up to 60
        credits of it (never more than 30 percent) are kept back so the
        party analysis can still be written. Accepting the request and
        reading its status cost nothing.

        Document links: `links["pdf"]` on a document is a download URL valid
        for one hour that needs no API key. Receiving it is free; the first
        time it is opened it is charged as one PDF call to the key that read
        the profile and counts toward the monthly PDF limit, and opening the
        same link again is free.

        Retries: like every POST, this is retried after it may have reached
        the server only with `retry_posts` (an `Idempotency-Key` is then
        generated for you when you pass none). Even then, a 503 is retried
        only for `ACCOUNT_STANDING_UNAVAILABLE` and
        `ENTITLEMENT_UNAVAILABLE`, which are refused before any work. When
        the debit outcome is unknown the answer is a 503 with no profile; it
        is never retried automatically, so check `get_usage()` before
        sending the request again.

        DPDP note: as on `screen_party`, `purpose` is required, and `name`,
        `aliases`, `knownPersons`, `identifiers` and `address` are never
        stored in plaintext by an API key request. A full mode request keeps
        the subject and the result encrypted until they can be read, and
        erases both 30 days after the request ends. Being a party to a case
        is not a finding against anyone.

        Args:
            name, entityType, purpose, aliases, identifiers, address,
            knownPersons, court, since, limit, adjudicate, displayThreshold:
                as on `screen_party`, with the same validation and caps.
            minConfidence: `"possible"`, `"probable"` or `"confirmed"`. The
                lowest band an identity needs to be the primary, and a case
                of the primary needs to be listed, enriched and billed.
                Server default: `probable` for a person, `possible` for a
                company.
            include: which sections to build, any of `"documents"`,
                `"acts"`, `"fir"`, `"status"`, `"summary"`. Omitted means
                all of them.
            allowUnconfirmedPrimary: for a person, let a group matched on
                name alone be the primary. Server default False.
            mode: `"full"` or `"quick"`, see above.
            maxCredits: full mode only, 100 to 5000.
            webhook: full mode only. `{"url": "https://...", "headers":
                {...}}`; the 202 answer carries `webhook["signingSecret"]`
                once. Check deliveries with `verify_webhook_signature`.
            timeout: per call timeout override, in seconds. Defaults to 90.
            retry_posts: per call override of the client's `retry_posts`.
            idempotency_key: see `analyze_case`.

        Raises:
            ValidationError: a field failed validation (400), or an invalid
                `Idempotency-Key` (`IDEMPOTENCY_KEY_INVALID`).
            InsufficientCreditsError: the balance does not cover the most
                this request could cost (402).
            PermissionDeniedError: `API_TIER_NOT_ALLOWED`,
                `API_NOT_AVAILABLE_ON_TRIAL` or `API_ENTERPRISE_ONLY` (403).
            ConflictError: `IDEMPOTENCY_KEY_REUSED` or
                `IDEMPOTENCY_IN_PROGRESS` (409).
            RateLimitError: `RATE_LIMITED` (shared with `screen_party`),
                `DISTINCT_NAMES_LIMIT_REACHED` or
                `PARTY_PROFILE_TOO_MANY_ACTIVE` (429).
            BadGatewayError: `PARTY_SCREEN_SEARCH_DEGRADED`, nothing charged
                (502).
            ServiceUnavailableError: `PARTY_PROFILE_FULL_UNAVAILABLE`,
                `ACCOUNT_STANDING_UNAVAILABLE` or `ENTITLEMENT_UNAVAILABLE`
                (503).
        """
        payload: Dict[str, Any] = {"name": name, "entityType": entityType, "purpose": purpose}
        _set_if_present(
            payload,
            aliases=aliases,
            identifiers=identifiers,
            address=address,
            knownPersons=knownPersons,
            court=court,
            since=since,
            limit=limit,
            adjudicate=adjudicate,
            displayThreshold=displayThreshold,
            minConfidence=minConfidence,
            include=list(include) if include is not None else None,
            allowUnconfirmedPrimary=allowUnconfirmedPrimary,
            mode=mode,
            maxCredits=maxCredits,
            webhook=webhook,
        )
        response = self._transport.request(
            "POST",
            "/party/profile",
            json_body=payload,
            timeout=_PARTY_PROFILE_TIMEOUT if timeout is None else timeout,
            retry_posts=retry_posts,
            idempotency_key=self._resolve_idempotency_key(idempotency_key, retry_posts),
            retryable_503_codes=_PARTY_PROFILE_RETRYABLE_503_CODES,
        )
        return self._envelope(response)

    def get_party_profile(
        self, request_id: str, timeout: Optional[float] = None
    ) -> APIResponse[PartyProfileRequestStatus]:
        """Read where a full mode party profile stands, and its result once
        finished. Free to call.

        `result.data["status"]` is `queued`, `running`, `completed` or
        `failed`; `stage` and `progress` show where it is, and `credits`
        what has been charged so far with a breakdown. Once completed,
        `result.data["result"]` holds the profile (the quick shape, plus
        `courtRefresh` and `analysis` on every case of the first identity
        and `partyAnalysis`). A failed request carries `failure` with a
        `code` and a plain `message`.

        Poll every few seconds to a minute. Waiting for court refreshes, with
        their retries, can take up to 25 minutes. The result can be read for
        30 days after the request ends; after that `resultExpired` is True
        and only the status, progress and credits remain.

        Args:
            request_id: the `requestId` from the 202 answer of
                `build_party_profile`, for example `"ppr_"` and 32 hex
                characters.
            timeout: per call timeout override, in seconds.

        Raises:
            NotFoundError: no such request for your account (404,
                `NOT_FOUND`). Another account's id answers the same.
            RateLimitError: rate limited (429).
        """
        response = self._transport.request("GET", "/party/profile/{}".format(_seg(request_id)), timeout=timeout)
        return self._envelope(response)

    # -- CNR lookup, watchlists, change feed, webhooks (0.5.0) -------------

    def _envelope(self, response: Any) -> APIResponse[Any]:
        body = self._transport.parse_envelope(response)
        return APIResponse(
            data=body.get("data", {}),
            meta=body.get("meta", {}),
            request_id=body.get("requestId"),
            replayed=body.get("replayed"),
        )

    def _list_result(self, response: Any) -> CursorListResult[Any]:
        body = self._transport.parse_envelope(response)
        return CursorListResult(
            data=body.get("data", []),
            pagination=body.get("pagination", {}),
            meta=body.get("meta", {}),
            request_id=body.get("requestId"),
        )

    def _post(
        self,
        path: str,
        payload: Optional[Dict[str, Any]],
        timeout: Optional[float],
        retry_posts: Optional[bool],
        idempotency_key: Optional[str],
    ) -> APIResponse[Any]:
        response = self._transport.request(
            "POST",
            path,
            json_body=payload,
            timeout=timeout,
            retry_posts=retry_posts,
            idempotency_key=self._resolve_idempotency_key(idempotency_key, retry_posts),
        )
        return self._envelope(response)

    def _patch(
        self, path: str, payload: Dict[str, Any], timeout: Optional[float], retry_posts: Optional[bool]
    ) -> APIResponse[Any]:
        response = self._transport.request("PATCH", path, json_body=payload, timeout=timeout, retry_posts=retry_posts)
        return self._envelope(response)

    def _delete(self, path: str, timeout: Optional[float]) -> APIResponse[Dict[str, Any]]:
        """DELETE; a 204 with no body becomes `{"deleted": True}`."""
        response = self._transport.request("DELETE", path, timeout=timeout)
        if response.status_code == 204:
            return APIResponse(data={"deleted": True}, meta={}, request_id=response.headers.get("X-Request-Id"))
        return self._envelope(response)

    def _iter_cursor(self, fetch_page: Any, stop_on_empty: bool, max_pages: Optional[int]) -> Iterator[Any]:
        """Yield every item, following `pagination["nextCursor"]`. For the
        change feed an empty page means caught up and stops the walk (an
        empty page is free). Other lists stop when there is no next cursor."""
        cursor: Optional[str] = None
        hard_cap = _MAX_SAFETY_PAGES if max_pages is None else min(max_pages, _MAX_SAFETY_PAGES)
        for _ in range(hard_cap):
            result = fetch_page(cursor)
            items = result.data or []
            if not items and stop_on_empty:
                return
            for item in items:
                yield item
            next_cursor = result.pagination.get("nextCursor")
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor == cursor:
                return
            if not stop_on_empty and result.pagination.get("hasMore") is False:
                return
            cursor = next_cursor

    def get_case_by_cnr(
        self, cnr: str, fetch: bool = False, timeout: Optional[float] = None, include: Optional[Sequence[str]] = None
    ) -> APIResponse[CnrLookup]:
        """Look a case up by CNR (any common spelling, normalised for you).

        1 credit, charged only when a record is returned. `result.data["status"]`
        is `found` (200, `result.data["case"]` holds the record) or `pending`
        (202, a live fetch is running: poll this same call with the same CNR;
        `result.data["requestId"]` is opaque and is not accepted by
        `get_timeline`). A CNR that is not in the corpus and was not fetched
        raises `NotFoundError` (`code == "CASE_NOT_FOUND"`). A Supreme Court
        CNR that is not in the corpus cannot be fetched live and raises it
        straight away.

        Args:
            fetch: start a live court portal fetch for a CNR we do not hold
                yet. The call that starts the fetch returns `pending` and is
                free; the poll that returns the record is the one 1 credit
                charge, and a fetch the court portal cannot satisfy costs
                nothing. Shares the daily live fetch cap with
                `request_timeline(refresh=True)`. If the court portal had
                nothing for this CNR in the last 24 hours, no new fetch is
                started and the call raises `NotFoundError` immediately.
            include: `hearings`, `advocates`, as on `get_case`.
        """
        path = "/cases/by-cnr/{}".format(quote(cnr_for_request(cnr), safe=""))
        params = {**({"fetch": "true"} if fetch else {}), **(_include_params(include) or {})}
        response = self._transport.request("GET", path, params=params or None, timeout=timeout)
        return self._envelope(response)

    def list_case_orders(self, case_id: str, timeout: Optional[float] = None) -> APIResponse[CaseDocuments]:
        """List the documents we hold for a case, newest first, with what is available for each.

        Read `textAvailable` before asking for the text: not every order has
        readable text. 1 credit.
        """
        path = "/cases/{}/orders".format(quote(str(case_id), safe=""))
        return self._envelope(self._transport.request("GET", path, timeout=timeout))

    def get_case_document_text(
        self, case_id: str, document_id: str, timeout: Optional[float] = None
    ) -> APIResponse[CaseDocumentText]:
        """Read the stored text of one document of a case.

        2 credits when text is returned; when we hold none, `textAvailable` is
        False, `text` is None and the call is free. Calls that return text
        count against a monthly allowance (`ORDER_TEXT_LIMIT_REACHED`). The
        text is machine read from the court document, so check anything you
        rely on against the original. Taken down and masked matters raise
        `PermissionDeniedError` (`CASE_RESTRICTED`).
        """
        path = "/cases/{}/orders/{}/text".format(quote(str(case_id), safe=""), quote(str(document_id), safe=""))
        return self._envelope(self._transport.request("GET", path, timeout=timeout))

    def refresh_case_by_cnr(
        self,
        cnr: str,
        timeout: Optional[float] = None,
        retry_posts: Optional[bool] = None,
        idempotency_key: Optional[str] = None,
    ) -> APIResponse[CnrRefreshResult]:
        """Queue a fresh read from the court and answer at once.

        A CNR we do not hold yet is fetched too. `status == "queued"` costs 1
        credit, charged on acceptance; every other status costs 0, including
        `running` when a refresh is already under way. Read progress with
        `get_case_refresh_state`. Not available on the Free tier.
        """
        path = "/cases/by-cnr/{}/refresh".format(quote(cnr_for_request(cnr), safe=""))
        return self._envelope(self._transport.request(
            "POST", path, json_body={}, timeout=timeout, retry_posts=retry_posts,
            idempotency_key=self._resolve_idempotency_key(idempotency_key, retry_posts),
        ))

    def get_case_refresh_state(self, cnr: str, timeout: Optional[float] = None) -> APIResponse[CnrRefreshState]:
        """Where a CNR's refresh stands.

        Free, and counts against the daily distinct cases allowance, so poll a
        few at a time. `failed` when the latest attempt gave up. Not available
        on the Free tier.
        """
        path = "/cases/by-cnr/{}/refresh".format(quote(cnr_for_request(cnr), safe=""))
        return self._envelope(self._transport.request("GET", path, timeout=timeout))

    def refresh_cases_batch(
        self,
        cnrs: Sequence[str],
        timeout: Optional[float] = None,
        retry_posts: Optional[bool] = None,
        idempotency_key: Optional[str] = None,
    ) -> APIResponse[CnrRefreshBatch]:
        """Refresh up to 50 CNRs in one call and answer at once, with a `status` for each.

        1 credit per CNR that reaches `queued`; every other status costs 0.
        When the daily live fetch allowance runs out the rest answer
        `not_accepted` and `meta["truncated"]` is True.
        """
        return self._envelope(self._transport.request(
            "POST", "/cases/refresh/batch", json_body={"cnrs": [cnr_for_request(c) for c in cnrs]},
            timeout=timeout, retry_posts=retry_posts,
            idempotency_key=self._resolve_idempotency_key(idempotency_key, retry_posts),
        ))

    # Watchlists

    def create_watchlist(
        self,
        name: str,
        items: Optional[Sequence[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
        retry_posts: Optional[bool] = None,
        idempotency_key: Optional[str] = None,
    ) -> APIResponse[Dict[str, Any]]:
        """Create a watchlist, optionally with up to 100 CNRs to start watching.

        `result.data["results"]` has one outcome per CNR (`watching`,
        `pending`, `invalid`, `duplicate`, `cap_exceeded`, `not_found`); a
        partial success is still a 200. Management calls are free.
        """
        payload: Dict[str, Any] = {"name": name}
        if items is not None:
            payload["items"] = [_normalized_item(item) for item in items]
        if metadata is not None:
            payload["metadata"] = metadata
        return self._post("/watchlists", payload, timeout, retry_posts, idempotency_key)

    def list_watchlists(
        self, cursor: Optional[str] = None, limit: Optional[int] = None, timeout: Optional[float] = None
    ) -> CursorListResult[Watchlist]:
        """One page of your watchlists."""
        params = _compact(cursor=cursor, limit=limit)
        return self._list_result(self._transport.request("GET", "/watchlists", params=params, timeout=timeout))

    def iter_watchlists(self, limit: Optional[int] = None, max_pages: Optional[int] = None) -> Iterator[Watchlist]:
        """Yield every watchlist, following cursors."""
        return self._iter_cursor(lambda c: self.list_watchlists(cursor=c, limit=limit), False, max_pages)

    def get_watchlist(self, watchlist_id: str, timeout: Optional[float] = None) -> APIResponse[Watchlist]:
        response = self._transport.request("GET", "/watchlists/{}".format(_seg(watchlist_id)), timeout=timeout)
        return self._envelope(response)

    def update_watchlist(
        self,
        watchlist_id: str,
        name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
        retry_posts: Optional[bool] = None,
    ) -> APIResponse[Watchlist]:
        """Rename a watchlist and/or replace its metadata."""
        payload = _compact(name=name, metadata=metadata)
        return self._patch("/watchlists/{}".format(_seg(watchlist_id)), payload or {}, timeout, retry_posts)

    def delete_watchlist(self, watchlist_id: str, timeout: Optional[float] = None) -> APIResponse[Dict[str, Any]]:
        """Delete a watchlist and its items. Events already emitted stay readable in `list_changes`."""
        return self._delete("/watchlists/{}".format(_seg(watchlist_id)), timeout)

    def add_watchlist_items(
        self,
        watchlist_id: str,
        items: Sequence[Dict[str, Any]],
        timeout: Optional[float] = None,
        retry_posts: Optional[bool] = None,
        idempotency_key: Optional[str] = None,
    ) -> APIResponse[Dict[str, Any]]:
        """Add 1 to 100 CNRs. Each gets a result in `result.data["results"]`:
        `watching`, `pending` (not in the corpus yet, so a live fetch was
        started), `invalid`, `duplicate`, `cap_exceeded` or `not_found`.

        `cap_exceeded` also means you passed the daily add allowance for the
        account (Free 50, Pay As You Go 5,000, Scale 50,000, Enterprise
        500,000 per Indian calendar day) or the daily limit on new CNRs.
        `not_found` is returned for a case taken down at a party's request and
        for a CNR the court portal had nothing for in the last 24 hours.

        Each item is a dict like `{"cnr": "...", "reference": "LOAN-42", "label": "..."}`.
        """
        payload = {"items": [_normalized_item(item) for item in items]}
        return self._post(
            "/watchlists/{}/items".format(_seg(watchlist_id)), payload, timeout, retry_posts, idempotency_key
        )

    def list_watchlist_items(
        self,
        watchlist_id: str,
        status: Optional[str] = None,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> CursorListResult[WatchlistItem]:
        """One page of the CNRs in a watchlist, optionally filtered by `status`
        (`watching`, `pending`, `not_found`, `error`)."""
        params = _compact(cursor=cursor, limit=limit, status=status)
        path = "/watchlists/{}/items".format(_seg(watchlist_id))
        return self._list_result(self._transport.request("GET", path, params=params, timeout=timeout))

    def iter_watchlist_items(
        self,
        watchlist_id: str,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        max_pages: Optional[int] = None,
    ) -> Iterator[WatchlistItem]:
        """Yield every item in a watchlist, following cursors."""
        return self._iter_cursor(
            lambda c: self.list_watchlist_items(watchlist_id, status=status, cursor=c, limit=limit), False, max_pages
        )

    def remove_watchlist_item(
        self, watchlist_id: str, cnr: str, timeout: Optional[float] = None
    ) -> APIResponse[Dict[str, Any]]:
        """Stop watching one CNR in one watchlist."""
        path = "/watchlists/{}/items/{}".format(_seg(watchlist_id), _seg(cnr_for_request(cnr)))
        return self._delete(path, timeout)

    # Change feed

    def list_changes(
        self,
        cursor: Optional[str] = None,
        since: Optional[str] = None,
        types: Optional[StrOrList] = None,
        cnr: Optional[str] = None,
        limit: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> CursorListResult[ChangeEvent]:
        """One page of change events across all your watchlists, oldest first.

        1 credit per non-empty page of up to 100 events; an empty page is free.
        `result.next_cursor` is always returned, even on an empty page, so you
        can store it and poll forward forever by passing it back as `cursor`.
        `since` (ISO timestamp) is used only when there is no `cursor`.
        Events are kept for 90 days. Delivery is at least once across
        webhooks, so dedupe on the event `id`.
        """
        params = _changes_params(cursor, since, types, cnr, limit)
        return self._list_result(self._transport.request("GET", "/changes", params=params, timeout=timeout))

    def iter_changes(
        self,
        since: Optional[str] = None,
        types: Optional[StrOrList] = None,
        cnr: Optional[str] = None,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
        max_pages: Optional[int] = None,
    ) -> Iterator[ChangeEvent]:
        """Yield every change event until caught up. Stops at the first empty
        page (which is free). To keep a durable position between runs, call
        `list_changes` yourself and store `result.next_cursor`."""
        first = {"cursor": cursor}

        def fetch(c: Optional[str]) -> CursorListResult[ChangeEvent]:
            return self.list_changes(cursor=c or first["cursor"], since=since, types=types, cnr=cnr, limit=limit)

        return self._iter_cursor(fetch, True, max_pages)

    def list_watchlist_events(
        self,
        watchlist_id: str,
        cursor: Optional[str] = None,
        since: Optional[str] = None,
        types: Optional[StrOrList] = None,
        cnr: Optional[str] = None,
        limit: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> CursorListResult[ChangeEvent]:
        """Same as `list_changes`, filtered to one watchlist. Same pricing."""
        params = _changes_params(cursor, since, types, cnr, limit)
        path = "/watchlists/{}/events".format(_seg(watchlist_id))
        return self._list_result(self._transport.request("GET", path, params=params, timeout=timeout))

    def iter_watchlist_events(
        self,
        watchlist_id: str,
        since: Optional[str] = None,
        types: Optional[StrOrList] = None,
        cnr: Optional[str] = None,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
        max_pages: Optional[int] = None,
    ) -> Iterator[ChangeEvent]:
        """Yield every event of one watchlist until caught up. See `iter_changes`."""
        first = {"cursor": cursor}

        def fetch(c: Optional[str]) -> CursorListResult[ChangeEvent]:
            return self.list_watchlist_events(
                watchlist_id, cursor=c or first["cursor"], since=since, types=types, cnr=cnr, limit=limit
            )

        return self._iter_cursor(fetch, True, max_pages)

    # Webhooks

    def create_webhook(
        self,
        url: str,
        events: Optional[Sequence[str]] = None,
        watchlist_ids: Optional[Sequence[str]] = None,
        description: Optional[str] = None,
        timeout: Optional[float] = None,
        retry_posts: Optional[bool] = None,
        idempotency_key: Optional[str] = None,
    ) -> APIResponse[Webhook]:
        """Register a webhook endpoint (https only).

        `result.data["secret"]` is shown once, here and on
        `rotate_webhook_secret`: store it. Use it with
        `verify_webhook_signature`. `events` defaults to every `case.*`
        type and the response echoes the full list; `watchlist_ids` defaults
        to all watchlists (the response echoes `[]`, which also means all).
        Honours `idempotency_key`.
        """
        payload = _compact(
            url=url,
            events=list(events) if events is not None else None,
            watchlistIds=list(watchlist_ids) if watchlist_ids is not None else None,
            description=description,
        )
        return self._post("/webhooks", payload, timeout, retry_posts, idempotency_key)

    def list_webhooks(
        self, cursor: Optional[str] = None, limit: Optional[int] = None, timeout: Optional[float] = None
    ) -> CursorListResult[Webhook]:
        params = _compact(cursor=cursor, limit=limit)
        return self._list_result(self._transport.request("GET", "/webhooks", params=params, timeout=timeout))

    def iter_webhooks(self, limit: Optional[int] = None, max_pages: Optional[int] = None) -> Iterator[Webhook]:
        """Yield every webhook endpoint, following cursors."""
        return self._iter_cursor(lambda c: self.list_webhooks(cursor=c, limit=limit), False, max_pages)

    def get_webhook(self, webhook_id: str, timeout: Optional[float] = None) -> APIResponse[Webhook]:
        """Never returns the secret."""
        response = self._transport.request("GET", "/webhooks/{}".format(_seg(webhook_id)), timeout=timeout)
        return self._envelope(response)

    def update_webhook(
        self,
        webhook_id: str,
        url: Optional[str] = None,
        events: Optional[Sequence[str]] = None,
        watchlist_ids: Optional[Sequence[str]] = None,
        description: Optional[str] = None,
        enabled: Optional[bool] = None,
        timeout: Optional[float] = None,
        retry_posts: Optional[bool] = None,
    ) -> APIResponse[Webhook]:
        """Change the URL, event filter, watchlist filter or description, or
        re-enable a disabled endpoint with `enabled=True`."""
        payload = _compact(
            url=url,
            events=list(events) if events is not None else None,
            watchlistIds=list(watchlist_ids) if watchlist_ids is not None else None,
            description=description,
            enabled=enabled,
        )
        return self._patch("/webhooks/{}".format(_seg(webhook_id)), payload, timeout, retry_posts)

    def delete_webhook(self, webhook_id: str, timeout: Optional[float] = None) -> APIResponse[Dict[str, Any]]:
        return self._delete("/webhooks/{}".format(_seg(webhook_id)), timeout)

    def rotate_webhook_secret(
        self,
        webhook_id: str,
        timeout: Optional[float] = None,
        retry_posts: Optional[bool] = None,
        idempotency_key: Optional[str] = None,
    ) -> APIResponse[Webhook]:
        """Issue a new signing secret. The old secret keeps signing in
        parallel for 24 hours (deliveries then carry two `v1=` signatures),
        so you can switch over without dropping events."""
        path = "/webhooks/{}/rotate-secret".format(_seg(webhook_id))
        return self._post(path, None, timeout, retry_posts, idempotency_key)

    def test_webhook(
        self,
        webhook_id: str,
        timeout: Optional[float] = None,
        retry_posts: Optional[bool] = None,
        idempotency_key: Optional[str] = None,
    ) -> APIResponse[WebhookDelivery]:
        """Send a `webhook.test` event to the endpoint now (a single attempt, never retried) and return the delivery object.

        It is sent even if the endpoint is switched off, and does not count
        toward its failure streak. Each attempt has a hard 10 second deadline
        and reads at most 64 KB of your response."""
        path = "/webhooks/{}/test".format(_seg(webhook_id))
        return self._post(path, None, timeout, retry_posts, idempotency_key)

    def list_webhook_deliveries(
        self,
        webhook_id: str,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> CursorListResult[WebhookDelivery]:
        """One page of delivery attempts for an endpoint."""
        params = _compact(cursor=cursor, limit=limit)
        path = "/webhooks/{}/deliveries".format(_seg(webhook_id))
        return self._list_result(self._transport.request("GET", path, params=params, timeout=timeout))

    def iter_webhook_deliveries(
        self, webhook_id: str, limit: Optional[int] = None, max_pages: Optional[int] = None
    ) -> Iterator[WebhookDelivery]:
        """Yield every delivery attempt for an endpoint, following cursors."""
        return self._iter_cursor(
            lambda c: self.list_webhook_deliveries(webhook_id, cursor=c, limit=limit), False, max_pages
        )

    def retry_webhook_delivery(
        self,
        webhook_id: str,
        delivery_id: str,
        timeout: Optional[float] = None,
        retry_posts: Optional[bool] = None,
        idempotency_key: Optional[str] = None,
    ) -> APIResponse[WebhookDelivery]:
        """Re-queue one delivery to be sent now."""
        path = "/webhooks/{}/deliveries/{}/retry".format(_seg(webhook_id), _seg(delivery_id))
        return self._post(path, None, timeout, retry_posts, idempotency_key)

    # -- Acts and sections (needs the `legislation` scope) --------------------

    def _acts_page(self, response: Any) -> ActsPageResult[Any]:
        body = self._transport.parse_envelope(response)
        return ActsPageResult(
            data=body.get("data", []),
            meta=body.get("meta", {}),
            pagination=body.get("pagination", {}),
            request_id=body.get("requestId"),
        )

    def search_acts(
        self,
        query: str,
        doc_class: Optional[str] = None,
        jurisdiction: Optional[str] = None,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        page: Optional[int] = None,
        limit: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> ActsPageResult[ActSummary]:
        """Find acts by title, short form or subject, ``GET /acts/search``.

        1 credit when something is returned, nothing when nothing is.
        ``pagination["total"]`` counts matches before unpublished records are
        removed, so a page can hold fewer rows than ``limit``. ``meta["weakMatch"]``
        is true when nothing matched closely. ``doc_class`` is one of ``act``,
        ``ordinance``, ``rule``, ``regulation``, ``amendment_act``,
        ``constitution``, ``code``; ``jurisdiction`` is ``central``, ``state``
        or ``union_territory``. Check ``repealed`` on each act before relying
        on it.
        """
        params = _compact(
            q=query,
            docClass=doc_class,
            jurisdiction=jurisdiction,
            yearFrom=year_from,
            yearTo=year_to,
            page=page,
            limit=limit,
        )
        return self._acts_page(self._transport.request("GET", "/acts/search", params=params, timeout=timeout))

    def resolve_act(self, query: str, timeout: Optional[float] = None) -> APIResponse[ActResolution]:
        """Turn what a lawyer writes ("IPC", "NI Act") into the act, ``GET /acts/resolve``.

        Returns up to five candidates, best first. Same pricing as ``search_acts``.
        """
        response = self._transport.request("GET", "/acts/resolve", params={"q": query}, timeout=timeout)
        return self._envelope(response)

    def get_act(self, slug: str, timeout: Optional[float] = None) -> APIResponse[Act]:
        """One act's details and repeal status, without its text, ``GET /acts/{slug}``.

        An unknown slug raises ``NotFoundError`` with ``code == "ACT_NOT_FOUND"``
        and costs nothing. 1 credit otherwise.
        """
        response = self._transport.request("GET", "/acts/{}".format(_seg(slug)), timeout=timeout)
        return self._envelope(response)

    def get_act_history(self, slug: str, timeout: Optional[float] = None) -> APIResponse[ActHistory]:
        """What repealed an act and what amended it, ``GET /acts/{slug}/history``.

        Act level only: it does not map old sections to new ones. An unknown
        slug raises ``NotFoundError`` (``ACT_NOT_FOUND``). 1 credit.
        """
        response = self._transport.request("GET", "/acts/{}/history".format(_seg(slug)), timeout=timeout)
        return self._envelope(response)

    def list_act_sections(
        self,
        slug: str,
        page: Optional[int] = None,
        limit: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> ActsPageResult[ActSectionEntry]:
        """The provisions of an act in order, without their text, ``GET /acts/{slug}/sections``.

        An act published only as one document has none (see ``textSource`` on
        ``get_act``). An unknown slug raises ``NotFoundError`` (``ACT_NOT_FOUND``).
        1 credit when rows come back.
        """
        params = _compact(page=page, limit=limit)
        path = "/acts/{}/sections".format(_seg(slug))
        return self._acts_page(self._transport.request("GET", path, params=params, timeout=timeout))

    def get_act_section(
        self, slug: str, section_slug: str, timeout: Optional[float] = None
    ) -> APIResponse[ActSection]:
        """One provision's full text, structured into blocks, with its amendment
        notes and repeal status, ``GET /acts/{slug}/sections/{sectionSlug}``.

        An unknown act or provision raises ``NotFoundError`` with
        ``code == "SECTION_NOT_FOUND"``, at no charge. 1 credit otherwise.
        """
        path = "/acts/{}/sections/{}".format(_seg(slug), _seg(section_slug))
        return self._envelope(self._transport.request("GET", path, timeout=timeout))

    def list_section_citing_cases(
        self,
        slug: str,
        section_slug: str,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> CitingCasesResult:
        """Judgments citing exactly this provision, newest first,
        ``GET /acts/{slug}/sections/{sectionSlug}/citing-cases``.

        A search for section 302 of the Penal Code does not return judgments
        that cite only its successor. This is not an exhaustive list of every
        judgment applying the provision, and an empty list does not mean no
        judgment applied it. ``data["listAvailable"]`` is false for a
        provision we do not list judgments for, including sexual offences and
        cruelty provisions. Some matters are never listed. A page can hold
        fewer rows than ``limit``, or none, while ``pagination["hasMore"]`` is
        true, so keep following ``pagination["nextCursor"]``. The cursor is
        opaque and valid only for the provision it was issued for. Read a
        judgment with ``get_case(id)``. A failed check raises
        ``BadGatewayError`` (``UPSTREAM_UNAVAILABLE``); it is free and safe to
        retry. 1 credit when cases come back.
        """
        params = _compact(cursor=cursor, limit=limit)
        path = "/acts/{}/sections/{}/citing-cases".format(_seg(slug), _seg(section_slug))
        body = self._transport.parse_envelope(self._transport.request("GET", path, params=params, timeout=timeout))
        return CitingCasesResult(
            data=body.get("data", {}),
            meta=body.get("meta", {}),
            pagination=body.get("pagination", {}),
            request_id=body.get("requestId"),
        )

    def iter_section_citing_cases(
        self,
        slug: str,
        section_slug: str,
        limit: Optional[int] = None,
        max_pages: Optional[int] = None,
    ) -> Iterator[CitingCase]:
        """Yield every citing judgment for a provision, following cursors
        until ``nextCursor`` is null. An empty page in the middle is skipped
        over, not treated as the end. The same caveats apply: the list is not
        exhaustive."""

        def fetch(c: Optional[str]) -> CursorListResult[CitingCase]:
            result = self.list_section_citing_cases(slug, section_slug, cursor=c, limit=limit)
            return CursorListResult(
                data=result.data.get("cases", []), pagination=result.pagination, meta=result.meta
            )

        return self._iter_cursor(fetch, False, max_pages)

    def search_sections(
        self,
        query: str,
        act: Optional[str] = None,
        number: Optional[str] = None,
        page: Optional[int] = None,
        limit: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> ActsPageResult[SectionRow]:
        """Full text search across provisions, with a short snippet per row,
        ``GET /sections/search``.

        Narrow it with ``act`` (an act slug) or ``number`` (an exact provision
        number such as ``"498A"``). Same pricing and ``pagination["total"]``
        caveat as ``search_acts``.
        """
        params = _compact(q=query, act=act, number=number, page=page, limit=limit)
        return self._acts_page(self._transport.request("GET", "/sections/search", params=params, timeout=timeout))

    def lookup_section(self, citation: str, timeout: Optional[float] = None) -> APIResponse[SectionLookup]:
        """Turn shorthand such as "section 302 IPC", "s.138 NI Act" or "Article 21"
        into the provision it names, ``GET /sections/lookup``.

        A lettered section keeps its letter. "Order VII Rule 11 CPC" is not
        resolved and returns no match. ``ambiguous`` is true on a match when
        no act was named: choose or name the act. 1 credit when something is
        returned.
        """
        response = self._transport.request("GET", "/sections/lookup", params={"q": citation}, timeout=timeout)
        return self._envelope(response)

    # -- Cause lists -------------------------------------------------------------

    def list_cause_listings(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        page: Optional[int] = None,
        limit: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> CauseListPage:
        """One page of the listings found for the matters in your account.

        Date range of at most 31 days, sent as `from` and `to` (`YYYY-MM-DD`,
        both or neither; default is today and the next 7 days). Pages start at
        1; `limit` is 1 to 100 and no more than your tier's maximum page size
        (default: the lower of 50 and your tier's maximum). Needs the `causelist` scope. 1 credit per successful
        call; a failed call is not charged. Only listings that were found are
        returned: an empty page does not mean a matter is not listed.

        Raises `ValidationError` for a bad date before any request is sent. A
        temporary outage is `BadGatewayError` (`code == "UPSTREAM_UNAVAILABLE"`,
        not charged, GET calls are retried); an account without cause list
        access is `PermissionDeniedError` (`CAUSE_LISTS_NOT_ENABLED`).
        """
        assert_date_range(from_date, to_date, LISTINGS_MAX_DAYS)
        params = _compact(**{"from": from_date, "to": to_date, "page": page, "limit": limit})
        response = self._transport.request("GET", "/cause-lists/listings", params=params or None, timeout=timeout)
        body = self._transport.parse_envelope(response)
        return CauseListPage(
            data=body.get("data", []),
            pagination=body.get("pagination", {}),
            meta=body.get("meta", {}),
            request_id=body.get("requestId"),
        )

    def iter_cause_listings(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        limit: Optional[int] = None,
        max_pages: Optional[int] = None,
    ) -> Iterator[CauseListing]:
        """Yield every listing, walking pages from 1 until `hasMore` is false.
        Each page is one call and one credit."""
        hard_cap = _MAX_SAFETY_PAGES if max_pages is None else min(max_pages, _MAX_SAFETY_PAGES)
        page = 1
        for _ in range(hard_cap):
            result = self.list_cause_listings(from_date, to_date, page=page, limit=limit)
            items = result.data or []
            for item in items:
                yield item
            if not items or not result.has_more:
                return
            page += 1

    def list_matter_cause_listings(
        self,
        matter_id: str,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> APIResponse[MatterCauseListings]:
        """The listings found for one matter in your account (`matter_id` is
        its 24 character id), within a date range of at most 31 days. 1 credit
        per successful call. An unknown matter raises `NotFoundError`
        (`MATTER_NOT_FOUND`), not charged."""
        assert_matter_id(matter_id)
        assert_date_range(from_date, to_date, LISTINGS_MAX_DAYS)
        params = _compact(**{"from": from_date, "to": to_date})
        path = "/matters/{}/cause-listings".format(_seg(matter_id))
        return self._envelope(self._transport.request("GET", path, params=params or None, timeout=timeout))

    def get_court_cause_list(
        self, court_key: str, date: str, timeout: Optional[float] = None
    ) -> APIResponse[CauseListCourtList]:
        """The published list of one court for one date, for a court you have
        an open matter in.

        `court_key` is `SC`, `HC:<state>:<bench>` or
        `DC:<state>:<district>:<complex>:<establishment>:<court number>`,
        digits only (a listing's `courtKey` works). `result.data["status"]`
        says what was read: `ok` and `partial` carry rows (1 credit); `none`,
        `empty`, `not_published`, `invalid_court` and `unavailable` are a 200
        with no rows and cost 0 (read `result.meta["creditsCharged"]`). The
        call still needs 1 credit available when it starts. A court with no
        open matter of yours raises `NotFoundError` (`COURT_LIST_NOT_FOUND`),
        not charged.
        """
        assert_court_list_query(court_key, date)
        params = {"courtKey": court_key, "date": date}
        return self._envelope(self._transport.request("GET", "/cause-lists/court", params=params, timeout=timeout))

    def check_cause_lists(
        self,
        cnrs: Sequence[str],
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        timeout: Optional[float] = None,
        retry_posts: Optional[bool] = None,
        idempotency_key: Optional[str] = None,
    ) -> APIResponse[CauseListCheckData]:
        """Check whether 1 to 100 CNRs that your account watches appear on a
        stored cause list, for a range of at most 7 days (default: today and
        tomorrow, Indian calendar). Needs the `causelist` scope. The call never
        contacts a court: it reads lists already held.

        Each entry of `result.data["results"]` has a `status`:

        - `listed`: a row of the case was found (1 credit).
        - `no_entry_found`: a list was read and no row was recognised (1
          credit). This is not proof that the case is not listed;
          `dates[].complete` says how much was read.
        - `list_not_read`, `cannot_check`, `not_watched`: free.

        At most 100 CNRs, and the number of distinct CNRs times the number of
        dates in the range (inclusive, 2 by default) at most 300; both are
        checked before a request is sent. Repeats of a CNR are ignored.

        Price: 1 credit per CNR with status `listed` or `no_entry_found`,
        settled once for the whole call (`result.meta["creditsCharged"]`). The
        call also needs at least 1 credit available when it starts: a balance
        below the number of watched CNRs in it raises `InsufficientCreditsError`.
        The same error can arrive after the answer is ready, when the credits
        due cannot be settled; no results are returned then. A
        `ServiceUnavailableError` with
        `code == "SETTLEMENT_UNCONFIRMED"` means the charge outcome is unknown:
        it is never retried automatically, even with `retry_posts`, and you
        should check your balance (`get_usage()`) first. Repeating the call with
        the same `idempotency_key` is refused with 409 `IDEMPOTENCY_IN_PROGRESS`
        for up to 24 hours. A 503 `ENTITLEMENT_UNAVAILABLE` ran nothing and is
        safe to retry.

        `result.data["from"]` and `result.data["to"]` are the dates that were
        looked at (the default range is resolved by the server). Only positive
        listings are reported. A temporary outage is `BadGatewayError`
        (`UPSTREAM_UNAVAILABLE`) for the whole call, not charged.
        `idempotency_key`: see `analyze_case`.
        """
        assert_check_body(cnrs, from_date, to_date)
        payload: Dict[str, Any] = {"cnrs": [cnr_for_request(cnr) for cnr in cnrs]}
        _set_if_present(payload, **{"from": from_date, "to": to_date})
        return self._post("/cause-lists/check", payload, timeout, retry_posts, idempotency_key)
