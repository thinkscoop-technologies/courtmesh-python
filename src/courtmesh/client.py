"""The CourtMesh API client."""
from __future__ import annotations

import json as _json
import os
import uuid
from typing import Any, Dict, Iterator, List, Optional, Sequence, Union
from urllib.parse import quote

import requests

from ._http import DEFAULT_MAX_RETRIES, DEFAULT_MAX_RETRY_AFTER_SECONDS, DEFAULT_TIMEOUT, HTTPTransport
from .errors import CourtMeshError
from .models import (
    APIResponse,
    AnalyzeResponse,
    AuditData,
    AuditResult,
    CaseAnalysisResponse,
    CaseDetails,
    CaseTypeEntry,
    ConsolidatedAnalyzeResponse,
    CourtHierarchy,
    CoverageData,
    HealthResponse,
    MeData,
    PartyScreenBatchResult,
    PartyScreenResult,
    PdfResponse,
    RelatedResponse,
    RequestTimelineResponse,
    SearchCasesResult,
    SemanticSearchResult,
    TimelineJob,
    UsageData,
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

StrOrList = Union[str, Sequence[str]]
IntOrList = Union[int, str, Sequence[Union[int, str]]]


def _set_if_present(payload: Dict[str, Any], **fields: Any) -> None:
    for key, value in fields.items():
        if value is not None:
            payload[key] = value


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
        query: str,
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
    ) -> SearchCasesResult:
        """Keyword search over the OpenSearch v3 case index.

        Args:
            query: required, at least 1 character after trimming.
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
            searchAfter: deprecated legacy cursor mechanism, honoured only
                for accounts without the API self-serve tiers flag on. A
                JSON encoded array string (the raw OpenSearch sort tuple
                from a previous page's `pagination["nextCursor"]`). New
                integrations should use `cursor` instead.
            sortBy: `"relevance"`, `"recent"` or `"oldest"`, plus the
                deprecated alias `"date"` (resolved to `"recent"`, with a
                note in `meta["warnings"]`). The response's `meta["sortBy"]`
                reports which sort was actually applied.
            timeout: per call timeout override, in seconds.
            retry_posts: per call override of the client's `retry_posts`.
        """
        payload: Dict[str, Any] = {"query": query}
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
        which shape your account gets.

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
                # Current, self-serve mechanism: hand the signed cursor
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
        """Vector (Qdrant) search with a GPT filter extraction pre-step.

        This is billed as an AI interaction by the server. **Not available
        on the Free tier**: raises `PermissionDeniedError` with
        `code == "SEMANTIC_NOT_ALLOWED"` before any work or charge.

        Args:
            query: required, at least 3 characters after trimming.
            filters: the vector store's own filter keys, applied directly
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
            caseNumber: same precedence as `court` above. The vector store
                filters case numbers numerically, so this must be a digits
                only string (e.g. `"1234"`); use `search_cases` to filter on
                a full case number string instead.
            judgeName: same precedence as `court` above. The vector store
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
            `meta["fallbackMode"] == "opensearch"` and `data` holds raw
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

    def get_case(self, case_id: str, timeout: Optional[float] = None) -> APIResponse[CaseDetails]:
        """Fetch case details by Mongo ObjectId or caseNumber.

        The server tries an ObjectId lookup first and falls back to a
        caseNumber lookup. The response deliberately excludes analysis
        fields, use `get_case_analysis` for those.
        """
        path = "/cases/{}".format(quote(str(case_id), safe=""))
        response = self._transport.request("GET", path, timeout=timeout)
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
        """Fetch an encrypted, presigned S3 URL for the case PDF.

        `data["pdfUrl"]` is ciphertext, valid for `data["expiresIn"]`
        seconds (3600). Decrypting it requires a case specific key that is
        not part of this API surface.

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
                URL (no stored text and no S3-stored document). Not
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
        """Request the orders timeline for a case. `case_id` must be a Mongo
        ObjectId string, it is passed straight to `new ObjectId()` server side.

        For Supreme Court cases this returns immediately with
        `status: "completed"`, `orderCount: 0`, `orders: []`, since those
        cases have no separate orders. If the timeline was already fetched
        today, the response has `cached: True` and the orders directly.
        Otherwise poll `get_timeline` with the returned `requestId`.

        Args:
            refresh: force a live fetch from the court portal instead of
                serving the last stored read. Default False. Costs 20
                credits when it actually triggers live work, versus 1
                credit for a stored read - see `result.meta["liveFetch"]`
                to see which one happened. Not available on the Free tier
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
        """Check API health. No auth required, not rate limited beyond the
        public health limiter.

        The plain form (`deep=False`, default) is a cheap liveness probe: no
        dependency calls, always fast, always HTTP 200 while the process is
        up. Pass `deep=True` to also check Mongo, OpenSearch, Qdrant, Redis
        and IAM standing (each bounded to 1s) - `status` then also reports
        `"degraded"`, and HTTP 503 (`status == "unhealthy"`) when a hard
        dependency (Mongo or OpenSearch) is down.

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
        type, by year, per court, and a rolled up District Courts row (the
        index has no per-state field).

        No API key is required for this endpoint, but this client always
        has one (the constructor requires it) and sends it along anyway.
        Server side cached for up to 6 hours. Most fields are optional
        (`total.get("documentBearing")` rather than `total["documentBearing"]`),
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
