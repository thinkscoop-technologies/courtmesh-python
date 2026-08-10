"""The CourtMesh Enterprise API client."""
from __future__ import annotations

import os
from typing import Any, Dict, Iterator, List, Optional, Sequence, Union
from urllib.parse import quote

import requests

from ._http import DEFAULT_MAX_RETRIES, DEFAULT_TIMEOUT, HTTPTransport
from .errors import CourtMeshError
from .models import (
    APIResponse,
    AnalyzeResponse,
    CaseAnalysisResponse,
    CaseDetails,
    ConsolidatedAnalyzeResponse,
    HealthResponse,
    PdfResponse,
    RelatedResponse,
    RequestTimelineResponse,
    SearchCasesResult,
    SemanticSearchResult,
    TimelineJob,
)

DEFAULT_BASE_URL = "https://research.courtmesh.ai/api/v1/prod"

# A single search page can legitimately return items on every attempt if a
# server bug always reports hasMore=True. This caps the pagination
# generators so a caller loop can never spin forever.
_MAX_SAFETY_PAGES = 10_000

StrOrList = Union[str, Sequence[str]]
IntOrList = Union[int, str, Sequence[Union[int, str]]]


def _set_if_present(payload: Dict[str, Any], **fields: Any) -> None:
    for key, value in fields.items():
        if value is not None:
            payload[key] = value


class CourtMesh:
    """Client for the CourtMesh Enterprise API.

    Example:
        with CourtMesh(api_key="cm-...") as cm:
            result = cm.search_cases(query="right to privacy")
            for hit in result.data:
                print(hit.get("title"))
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
    ) -> None:
        """
        Args:
            api_key: your CourtMesh API key, for example `cm-...-....`. Falls
                back to the `COURTMESH_API_KEY` environment variable.
            base_url: API base URL, defaults to the production endpoint.
            session: an existing `requests.Session` to reuse, for example to
                share connection pooling or custom TLS settings. A new one
                is created when omitted.
            timeout: per request timeout in seconds.
            max_retries: how many times to retry a 429, 502, 503, 504 or
                connection error before giving up.
            auth_header: `"authorization"` (default) sends
                `Authorization: Bearer <key>`. `"x-api-key"` sends
                `X-API-Key: <key>` instead. Both forms are accepted by the
                server, checked in that order.
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

    # -- 1. GET /judges/search -------------------------------------------

    def search_judges(self, q: str = "") -> APIResponse[List[str]]:
        """Search Supreme Court and High Court judge names.

        Args:
            q: free text, case insensitive substring match. Empty string
                returns the first 50 names from the combined list.

        Returns at most 50 matching names.
        """
        params: Dict[str, Any] = {}
        if q:
            params["q"] = q
        response = self._transport.request("GET", "/judges/search", params=params or None)
        body = self._transport.parse_envelope(response)
        return APIResponse(data=body.get("data", []), meta=body.get("meta", {}))

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
        searchAfter: Optional[str] = None,
        sortBy: Optional[str] = None,
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
            caseNumber: accepted and echoed back in `meta.filters`, but the
                handler never forwards it to the search backend, so it does
                not actually filter results. This is a real server
                limitation, not an SDK bug.
            fromDate, toDate: `YYYY-MM-DD`.
            page: 1 based, default 1.
            limit: 1..100, default 20.
            searchAfter: an opaque cursor from a previous page's
                `pagination["nextCursor"]`, JSON encoded as a string.
            sortBy: `"relevance"` or `"date"`. Only `"relevance"` is
                meaningful today, the search backend actually expects
                `relevance|recent|oldest` and `"date"` does not match
                either of those.
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
            searchAfter=searchAfter,
            sortBy=sortBy,
        )
        response = self._transport.request("POST", "/search/cases", json_body=payload)
        body = self._transport.parse_envelope(response)
        return SearchCasesResult(
            data=body.get("data", []),
            meta=body.get("meta", {}),
            pagination=body.get("pagination", {}),
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
        never cause an infinite loop.

        Args:
            query: same as `search_cases`.
            limit: page size, 1..100.
            max_pages: optional cap on the number of pages fetched.
            **kwargs: any other `search_cases` filter (court, year, ...).
        """
        kwargs.pop("page", None)
        kwargs.pop("limit", None)
        current_page = 1
        pages_fetched = 0
        hard_cap = _MAX_SAFETY_PAGES if max_pages is None else min(max_pages, _MAX_SAFETY_PAGES)
        while pages_fetched < hard_cap:
            result = self.search_cases(query, page=current_page, limit=limit, **kwargs)
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

    # -- 3. POST /search/cases/semantic ------------------------------------

    def semantic_search(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        page: Optional[int] = None,
        limit: Optional[int] = None,
        court: Optional[StrOrList] = None,
        caseType: Optional[StrOrList] = None,
        caseNumber: Optional[StrOrList] = None,
        judgeName: Optional[StrOrList] = None,
        judges: Optional[StrOrList] = None,
        judge: Optional[StrOrList] = None,
        year: Optional[IntOrList] = None,
        fromDate: Optional[str] = None,
        toDate: Optional[str] = None,
    ) -> SemanticSearchResult:
        """Vector (Qdrant) search with a GPT filter extraction pre-step.

        This is billed as an AI interaction by the server.

        Args:
            query: required, at least 3 characters after trimming.
            filters: the ONLY filter channel the handler actually reads.
                Recognised keys: `court`, `caseType`, `caseYear`,
                `caseNumber`, `judgeName` (also accepts `judges`/`judge`,
                mapped to `judgeName`), `decisionDate` (`{"$gte": ..., "$lte": ...}`),
                `practiceArea`, `sourceCaseId`. Filters GPT extracts from
                the query text are merged with this, and values you pass
                here win over the GPT extracted ones.
            page, limit: same semantics as `search_cases`.
            court, caseType, caseNumber, judgeName, judges, judge, year,
                fromDate, toDate: accepted and validated the same way as
                `search_cases`, but VALIDATED ONLY, the handler never reads
                them. Pass filters via `filters=` instead.

        Raises:
            CourtMeshError: when the response body has `success: false`.
                This endpoint calls `res.writeHead(200, ...)` before doing
                any real work, so failures after that point (embedding
                generation, vector search, upstream fetch) still arrive
                with HTTP 200. This method checks `success` explicitly and
                raises so callers do not have to remember the quirk.

        Note:
            When the cleaned query (after filter extraction) is shorter
            than 3 characters, the handler falls back to keyword search:
            `meta["fallbackMode"] == "opensearch"` and `data` holds raw
            `CaseListItem` hits instead of watermarked semantic results.
        """
        payload: Dict[str, Any] = {"query": query}
        _set_if_present(
            payload,
            filters=filters,
            page=page,
            limit=limit,
            court=court,
            caseType=caseType,
            caseNumber=caseNumber,
            judgeName=judgeName,
            judges=judges,
            judge=judge,
            year=year,
            fromDate=fromDate,
            toDate=toDate,
        )
        response = self._transport.request("POST", "/search/cases/semantic", json_body=payload)
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

    def get_case(self, case_id: str) -> APIResponse[CaseDetails]:
        """Fetch case details by Mongo ObjectId or caseNumber.

        The server tries an ObjectId lookup first and falls back to a
        caseNumber lookup. The response deliberately excludes analysis
        fields, use `get_case_analysis` for those.
        """
        path = "/cases/{}".format(quote(str(case_id), safe=""))
        response = self._transport.request("GET", path)
        body = self._transport.parse_envelope(response)
        return APIResponse(data=body.get("data", {}), meta=body.get("meta", {}))

    # -- 5. GET /cases/{id}/analysis ----------------------------------------

    def get_case_analysis(self, case_id: str) -> APIResponse[CaseAnalysisResponse]:
        """Fetch the AI analysis for a case, if one exists.

        Check `data["hasAnalysis"]`: when False there is only a `message`,
        when True the full `analysis` object is present.
        """
        path = "/cases/{}/analysis".format(quote(str(case_id), safe=""))
        response = self._transport.request("GET", path)
        body = self._transport.parse_envelope(response)
        return APIResponse(data=body.get("data", {}), meta=body.get("meta", {}))

    # -- 6. GET /cases/{id}/related -----------------------------------------

    def get_related(self, case_id: str) -> APIResponse[RelatedResponse]:
        """Fetch related documents and derived timeline for a case.

        Related documents are every case document sharing the same
        `caseNumber` (limit 50). The timeline only includes documents that
        have both a decisionDate and a stored PDF.
        """
        path = "/cases/{}/related".format(quote(str(case_id), safe=""))
        response = self._transport.request("GET", path)
        body = self._transport.parse_envelope(response)
        return APIResponse(data=body.get("data", {}), meta=body.get("meta", {}))

    # -- 7. GET /cases/{id}/pdf ----------------------------------------------

    def get_case_pdf(self, case_id: str) -> APIResponse[PdfResponse]:
        """Fetch an encrypted, presigned S3 URL for the case PDF.

        `data["pdfUrl"]` is ciphertext, valid for `data["expiresIn"]`
        seconds (3600). Decrypting it requires a case specific key that is
        not part of this API surface.
        """
        path = "/cases/{}/pdf".format(quote(str(case_id), safe=""))
        response = self._transport.request("GET", path)
        body = self._transport.parse_envelope(response)
        return APIResponse(data=body.get("data", {}), meta=body.get("meta", {}))

    # -- 8. POST /cases/{id}/analyze ------------------------------------------

    def analyze_case(self, case_id: str, force: bool = False) -> APIResponse[AnalyzeResponse]:
        """Start AI analysis for a case. Asynchronous.

        On success this normally returns HTTP 202 with
        `{"message": "Analysis has been started", "status": "processing"}`.
        Poll `get_case` after 30-60 seconds to see whether it finished. If
        an analysis already exists and `force` is not set, the server
        instead returns HTTP 200 with the existing analysis and
        `alreadyExists: True`.

        Args:
            force: re-run analysis even if one already exists.
        """
        path = "/cases/{}/analyze".format(quote(str(case_id), safe=""))
        response = self._transport.request("POST", path, json_body={"force": force})
        body = self._transport.parse_envelope(response)
        return APIResponse(data=body.get("data", {}), meta=body.get("meta", {}))

    # -- 9. POST /cases/{id}/analyze-consolidated -----------------------------

    def analyze_consolidated(
        self, case_id: str, force: bool = False
    ) -> APIResponse[ConsolidatedAnalyzeResponse]:
        """Run consolidated AI analysis. Synchronous and slow.

        Analyses the current case plus related documents: for a High
        Court case, the current case plus the latest 5 orders; for a
        Supreme Court case, up to 20 documents sharing the same
        caseNumber.

        Args:
            force: re-run even if a consolidated analysis already exists.
        """
        path = "/cases/{}/analyze-consolidated".format(quote(str(case_id), safe=""))
        response = self._transport.request("POST", path, json_body={"force": force})
        body = self._transport.parse_envelope(response)
        return APIResponse(data=body.get("data", {}), meta=body.get("meta", {}))

    # -- 10. POST /request-timeline --------------------------------------------

    def request_timeline(self, case_id: str) -> APIResponse[RequestTimelineResponse]:
        """Request the orders timeline for a case. `case_id` must be a Mongo
        ObjectId string, it is passed straight to `new ObjectId()` server side.

        For Supreme Court cases this returns immediately with
        `status: "completed"`, `orderCount: 0`, `orders: []`, since those
        cases have no separate orders. If the timeline was already fetched
        today, the response has `cached: True` and the orders directly.
        Otherwise poll `get_timeline` with the returned `requestId`.
        """
        response = self._transport.request(
            "POST", "/request-timeline", json_body={"case_id": case_id}
        )
        body = self._transport.parse_envelope(response)
        return APIResponse(data=body.get("data", {}), meta=body.get("meta", {}))

    # -- 11. GET /get-timeline/{requestId} --------------------------------------

    def get_timeline(self, request_id: str) -> APIResponse[TimelineJob]:
        """Poll the job created by `request_timeline`.

        `data["result"]` is omitted whenever `data["totalOrderCount"]` is
        present.
        """
        path = "/get-timeline/{}".format(quote(str(request_id), safe=""))
        response = self._transport.request("GET", path)
        body = self._transport.parse_envelope(response)
        return APIResponse(data=body.get("data", {}), meta=body.get("meta", {}))

    # -- 12. GET /health ----------------------------------------------------

    def health(self) -> HealthResponse:
        """Check API health. No auth required, not rate limited.

        Unlike every other endpoint, the response is not enveloped in
        `data`, this method returns the body directly.
        """
        response = self._transport.request("GET", "/health", require_auth=False)
        body = self._transport.parse_envelope(response)
        return body
