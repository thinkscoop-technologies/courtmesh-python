"""Typed response models for the CourtMesh Enterprise API.

Every field here was taken directly from the API spec (which was itself
derived from the server source). Nothing is invented. Most shapes use
`TypedDict(total=False)` because the server drops keys whose value is
undefined, so any field may legitimately be absent from a given response.

The paginated search endpoints get their own result dataclasses because
they combine three independent pieces (data, meta, pagination) and the two
endpoints do not share a pagination shape, see `SearchCasesPagination` and
`SemanticSearchPagination` below.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Generic, List, Optional, TypeVar, TypedDict, Union

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Pagination shapes. Two different shapes exist, they are kept separate on
# purpose, do not unify them.
# ---------------------------------------------------------------------------


class SearchCasesPagination(TypedDict, total=False):
    """Pagination block returned by POST /search/cases.

    `page` is absent when the caller used cursor pagination (`searchAfter`).
    `totalPages` does not exist on this endpoint. `nextCursor` is an array
    or None.
    """

    total: int
    hasMore: bool
    page: int
    limit: int
    nextCursor: Optional[List[Any]]


class SemanticSearchPagination(TypedDict, total=False):
    """Pagination block returned by POST /search/cases/semantic.

    `total` and `totalPages` are estimates, exact only on the last page.
    """

    page: int
    limit: int
    total: int
    totalPages: int
    hasMore: bool


# ---------------------------------------------------------------------------
# The response envelope.
# ---------------------------------------------------------------------------


class Envelope(TypedDict, total=False):
    """Raw shape of `successResponse` / handler error bodies.

    `meta` and `pagination` are only present when the handler supplies
    them. On error, `success` is False and `error` (plus optionally
    `details`, for zod validation failures) is set instead of `data`.
    """

    success: bool
    data: Any
    meta: Dict[str, Any]
    pagination: Dict[str, Any]
    error: str
    details: List[str]


@dataclass
class APIResponse(Generic[T]):
    """Convenience wrapper for non-paginated endpoints: unwrapped data + meta."""

    data: T
    meta: Dict[str, Any]


# ---------------------------------------------------------------------------
# 1. GET /judges/search
# ---------------------------------------------------------------------------


class JudgeSearchMeta(TypedDict, total=False):
    query: str
    responseTime: str
    totalMatches: int


# ---------------------------------------------------------------------------
# 2. POST /search/cases
# ---------------------------------------------------------------------------


class CaseListItem(TypedDict, total=False):
    """One OpenSearch hit: `_source` fields plus `_id`, `_score`, `_sort`.

    Every field is optional, presence varies per document. Note that
    `detailedSummary`, `holding`, `keyFacts_joined`, `legalIssues_joined`
    and `courtsReasoning` are indexed but excluded from `_source`, so they
    never appear here.
    """

    _id: str
    _score: float
    _sort: List[Any]
    mongoId: str
    title: str
    titleRaw: str
    headnote: str
    summary: str
    petitioners: List[str]
    respondents: List[str]
    parties_all: List[str]
    judges: List[str]
    advocates: List[str]
    caseNumber: str
    extracted_citations: List[str]
    cited_sections: List[str]
    courtType: str
    court: str
    courtName: str
    caseType: str
    caseTypeFullForm: str
    caseStatus: str
    caseYear: int
    registrationYear: int
    cnr: str
    source: str
    decisionDate: str
    registrationDate: str
    citation: str
    disposalNature: str
    hasDocuments: bool
    documentTypes: List[str]
    practiceAreas: List[str]
    precedentValue: str
    createdAt: str
    updatedAt: str


class SearchCasesFilters(TypedDict, total=False):
    """Echo of the request filters in `meta.filters` for POST /search/cases."""

    court: Any
    year: Any
    caseType: Any
    caseNumber: Any
    judgeName: Any
    fromDate: str
    toDate: str


class SearchCasesMeta(TypedDict, total=False):
    query: str
    filters: SearchCasesFilters
    responseTime: str


@dataclass
class SearchCasesResult:
    """Result of `search_cases`, one page of raw OpenSearch hits."""

    data: List[CaseListItem]
    meta: SearchCasesMeta
    pagination: SearchCasesPagination


# ---------------------------------------------------------------------------
# 3. POST /search/cases/semantic
# ---------------------------------------------------------------------------


class SemanticSearchResultItem(TypedDict, total=False):
    """One watermarked semantic search result. `similarity` is the Qdrant score."""

    id: str
    caseNumber: str
    title: str
    court: str
    caseType: str
    judges: List[str]
    petitioners: List[str]
    respondents: List[str]
    decisionDate: str
    disposalNature: str
    summary: str
    hasDocuments: bool
    hasAnalysis: bool
    similarity: float


class SemanticSearchMeta(TypedDict, total=False):
    """Meta block for POST /search/cases/semantic.

    `message` is only present when there were no results. `fallbackMode`
    is only present when the handler fell back to keyword search because
    the cleaned query was shorter than 3 characters, in that case `data`
    holds raw `CaseListItem` hits instead of `SemanticSearchResultItem`.
    """

    query: str
    originalQuery: str
    appliedFilters: Any
    responseTime: str
    searchType: str
    message: str
    fallbackMode: str


@dataclass
class SemanticSearchResult:
    """Result of `semantic_search`.

    `data` holds `SemanticSearchResultItem` objects, unless
    `meta["fallbackMode"] == "opensearch"`, in which case it holds raw
    `CaseListItem` hits, see `SemanticSearchMeta`.
    """

    data: List[Union[SemanticSearchResultItem, CaseListItem]]
    meta: SemanticSearchMeta
    pagination: SemanticSearchPagination


# ---------------------------------------------------------------------------
# 4. GET /cases/{id}
# ---------------------------------------------------------------------------


class CaseDetailsMetadata(TypedDict, total=False):
    diaryNumber: str


class CaseDetails(TypedDict, total=False):
    """Case details, watermarked. Deliberately excludes analysis fields such
    as `detailedSummary`, `headnote`, `holding` and `keyFacts`, those live
    on GET /cases/{id}/analysis.
    """

    id: str
    caseNumber: str
    title: str
    court: str
    caseType: str
    judges: List[str]
    petitioners: List[str]
    respondents: List[str]
    decisionDate: str
    disposalNature: str
    summary: str
    metadata: CaseDetailsMetadata
    hasDocuments: bool
    documentCount: int
    hasAnalysis: bool


class CaseDetailsMeta(TypedDict, total=False):
    responseTime: str
    note: str


# ---------------------------------------------------------------------------
# 5. GET /cases/{id}/analysis, 8. POST /cases/{id}/analyze,
#    9. POST /cases/{id}/analyze-consolidated
# ---------------------------------------------------------------------------


class AnalysisIssue(TypedDict, total=False):
    question: str
    holding: str


class CitedCases(TypedDict, total=False):
    followed: List[str]
    distinguished: List[str]
    overruled: List[str]
    referred: List[str]


class AnalysisArguments(TypedDict, total=False):
    petitioner: List[str]
    respondent: List[str]


class CaseAnalysis(TypedDict, total=False):
    """The AI analysis object, shared by the analysis and analyze endpoints."""

    summary: str
    detailedSummary: str
    comprehensiveSummary: str
    headnote: str
    holding: str
    keyFacts: List[str]
    issues: List[AnalysisIssue]
    courtsReasoning: str
    citedCases: CitedCases
    precedentRelationships: Any
    arguments: AnalysisArguments
    practiceAreas: List[str]
    subCategories: List[str]
    tags: List[str]
    procedureType: str
    precedentValue: str
    legalPrinciples: List[str]
    doctrinesApplied: List[str]
    statutoryInterpretation: str
    constitutionalProvisions: List[str]


class ConsolidatedAnalysis(CaseAnalysis, total=False):
    """Same keys as `CaseAnalysis` plus the consolidated-only fields.

    Internal `analysisModel` / `analysisVersion` / `analysisDate` fields
    are stripped by the server and never appear here.
    """

    benchComposition: Any
    opinionType: str
    factPattern: Any
    linkedCases: Any
    outcome: Any


class CaseAnalysisResponse(TypedDict, total=False):
    """Body of GET /cases/{id}/analysis.

    When `hasAnalysis` is False, only `message` is set alongside the id
    fields. When True, `analysis` is set instead.
    """

    id: str
    caseNumber: str
    hasAnalysis: bool
    message: str
    analysis: CaseAnalysis


class CaseAnalysisMeta(TypedDict, total=False):
    responseTime: str
    note: str


class AnalyzeResponse(TypedDict, total=False):
    """Body of POST /cases/{id}/analyze.

    On 202 (freshly started): `message` and `status` are set.
    On 200 (already exists, force not set): `message`, `analysis` and
    `alreadyExists` are set instead.
    """

    message: str
    status: str
    analysis: CaseAnalysis
    alreadyExists: bool


class ConsolidatedAnalyzeResponse(TypedDict, total=False):
    """Body of POST /cases/{id}/analyze-consolidated."""

    status: str
    consolidatedAnalysis: ConsolidatedAnalysis
    message: str


class ConsolidatedAnalyzeMeta(TypedDict, total=False):
    responseTime: str
    relatedCases: int


# ---------------------------------------------------------------------------
# 6. GET /cases/{id}/related
# ---------------------------------------------------------------------------


class RelatedDocument(TypedDict, total=False):
    id: str
    title: str
    caseNumber: str
    court: str
    decisionDate: str
    caseType: str
    isCurrent: bool


class TimelineEvent(TypedDict, total=False):
    """One timeline entry. `status` is one of `Final Judgment`,
    `Hearings / Orders`, `Case Initiated`. `statusLabel` is `disposalNature`
    when present, otherwise it repeats `status`.
    """

    date: str
    status: str
    statusLabel: str
    documentId: str


class RelatedResponse(TypedDict, total=False):
    relatedDocuments: List[RelatedDocument]
    timeline: List[TimelineEvent]


class RelatedMeta(TypedDict, total=False):
    responseTime: str
    caseNumber: str
    totalDocuments: int
    timelineEvents: int
    message: str


# ---------------------------------------------------------------------------
# 7. GET /cases/{id}/pdf
# ---------------------------------------------------------------------------


class PdfResponse(TypedDict, total=False):
    """`pdfUrl` is ciphertext, not a fetchable URL, it requires a case
    specific decryption key that is not part of this API surface.
    """

    pdfUrl: str
    expiresIn: int
    caseId: str
    caseNumber: str
    caseTitle: str


class PdfMeta(TypedDict, total=False):
    responseTime: str
    note: str


# ---------------------------------------------------------------------------
# 10. POST /request-timeline, 11. GET /get-timeline/{requestId}
# ---------------------------------------------------------------------------


class Order(TypedDict, total=False):
    _id: str
    title: str
    caseNumber: str
    decisionDate: str
    court: str
    caseType: str
    disposalNature: str
    judges: List[str]
    judge: str
    petitioners: List[str]
    respondents: List[str]
    # The API reports whether a document exists, never where it is stored.
    hasS3Key: bool


class RequestTimelineResponse(TypedDict, total=False):
    requestId: str
    status: str
    cached: bool
    message: str
    orderCount: int
    orders: List[Order]


class TimelineJob(TypedDict, total=False):
    """Body of GET /get-timeline/{requestId}.

    `result` is omitted whenever `totalOrderCount` is present.
    """

    requestId: str
    status: str
    createdAt: str
    updatedAt: str
    startedAt: str
    completedAt: str
    error: str
    result: Any
    orders: List[Order]
    orderCount: int
    totalOrderCount: int


class ResponseTimeMeta(TypedDict, total=False):
    responseTime: str


# ---------------------------------------------------------------------------
# 12. GET /health
# ---------------------------------------------------------------------------


class HealthResponse(TypedDict, total=False):
    """Body of GET /health. Not enveloped in `data`, unlike every other
    endpoint."""

    success: bool
    status: str
    version: str
    timestamp: str
