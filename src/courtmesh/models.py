"""Typed response models for the CourtMesh API.

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

try:
    from typing import Literal
except ImportError:  # pragma: no cover - Python 3.7 fallback, unused at runtime
    Literal = None  # type: ignore[assignment]

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Pagination shapes. Two different shapes exist, they are kept separate on
# purpose, do not unify them.
# ---------------------------------------------------------------------------


class SearchCasesPagination(TypedDict, total=False):
    """Pagination block returned by POST /search/cases.

    `page` is absent once cursor pagination has taken over. `totalPages`
    does not exist on this endpoint. `nextCursor` has two shapes:
    a signed, opaque string (pass it back as `cursor`), or the
    legacy raw sort tuple (an array, pass it back as a JSON
    encoded `searchAfter` string). Either way, `None` means
    there is no next page.
    """

    total: int
    hasMore: bool
    page: int
    limit: int
    nextCursor: Union[str, List[Any], None]


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
    """Raw shape of API response bodies.

    `meta` and `pagination` are only present when the handler supplies
    them. On error, `success` is False and `error` (plus optionally
    `details`, for validation failures) is set instead of `data`.
    """

    success: bool
    data: Any
    meta: Dict[str, Any]
    pagination: Dict[str, Any]
    error: str
    details: List[str]


@dataclass
class APIResponse(Generic[T]):
    """Convenience wrapper for non-paginated endpoints: unwrapped data + meta.

    Attributes:
        request_id: the request id for this call, either the server's own
            `meta["requestId"]`/body level `requestId` when it set one, or
            (backfilled client side as a fallback) the `X-Request-Id`
            response header.
        replayed: `True` only when this call sent an `idempotency_key` that
            matched a previous request within its 24 hour window: the
            server returned the stored response instead of doing the work
            again, and nothing was charged. Only ever set on the
            idempotency-key-aware methods (for example `screen_party`,
            `screen_party_batch`, `build_party_profile`, `analyze_case`,
            `analyze_consolidated`, `request_timeline`); `None` on every
            other response.
    """

    data: T
    meta: Dict[str, Any]
    request_id: Optional[str] = None
    replayed: Optional[bool] = None


# ---------------------------------------------------------------------------
# 1. GET /judges/search
# ---------------------------------------------------------------------------


class JudgeSearchMeta(TypedDict, total=False):
    query: str
    responseTime: str
    totalMatches: int


# ---------------------------------------------------------------------------
# Shared case shapes (API 1.8.0)
# ---------------------------------------------------------------------------


class SameMatterEntry(TypedDict, total=False):
    """Another order or document of the same Supreme Court matter. Fetch it
    by `caseId` like any case. Only `caseId` is always present."""

    caseId: str
    caseType: str
    #: Date and time, or `None`.
    decisionDate: Optional[str]


class CourtRecordAct(TypedDict):
    """An act and its sections as the court record states them. The act
    name is as the court wrote it."""

    act: str
    sections: List[str]


class CourtRecordFir(TypedDict, total=False):
    """The FIR a district case arose from, as the court record states it.
    Each field is left out when the court has not recorded it."""

    firNumber: str
    firYear: str
    policeStation: str


# ---------------------------------------------------------------------------
# 2. POST /search/cases
# ---------------------------------------------------------------------------


class CaseListItem(TypedDict, total=False):
    """One search hit: the stored document fields plus `id`/`score` (the
    documented contract names; `_id`/`_score` are the legacy field names,
    kept for backwards compatibility).

    Every field is optional, presence varies per document. Note that
    analysis fields such as `detailedSummary` and `holding` never appear here.
    """

    id: str
    score: float
    highlights: Dict[str, List[str]]
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
    #: Supreme Court only: the other orders and documents of the same
    #: matter, newest first. Rows are grouped by matter within a page, so a
    #: page can hold fewer rows than `limit`; page with `nextCursor`, not
    #: the row count.
    sameMatter: List[SameMatterEntry]


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
    #: The sort actually applied (after resolving a deprecated `sortBy`
    #: alias like `"date"`): `"relevance"`, `"recent"` or `"oldest"`.
    sortBy: str
    #: Present, and truthy, only when at least one deprecated input was
    #: silently resolved (for example `sortBy: "date"`).
    warnings: List[str]
    #: Present, and True, only when one or more results were withheld by
    #: the restricted-case gate (a party's takedown, or a masked title).
    someRecordsWithheld: bool
    #: Present, and True, only when the restricted-case check itself could
    #: not run (fail-closed masking, not a confirmed clean page).
    restrictedCheckDegraded: bool
    responseTime: str


class SearchCnrLookup(TypedDict, total=False):
    """`cnr_lookup` on a `search_cases(cnr=...)` result that returned no
    case: what is happening with that CNR.

    `status` is `pending` (a court check is running; `requestId` is the
    check as `get_case_by_cnr` reports it), `not_found`, `cooldown`,
    `limit_reached` or `unavailable`. `cnr` and `status` are always present.
    """

    cnr: str
    status: str
    requestId: str


@dataclass
class SearchCasesResult:
    """Result of `search_cases`, one page of raw search hits."""

    data: List[CaseListItem]
    meta: SearchCasesMeta
    pagination: SearchCasesPagination
    #: See `APIResponse.request_id`.
    request_id: Optional[str] = None
    #: The top level `cnrLookup` of the response, present only on a `cnr`
    #: search that returned no case. `None` otherwise.
    cnr_lookup: Optional[SearchCnrLookup] = None


# ---------------------------------------------------------------------------
# 3. POST /search/cases/semantic
# ---------------------------------------------------------------------------


class SemanticSearchResultItem(TypedDict, total=False):
    """One watermarked semantic search result. `similarity` is the relevance score."""

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
    #: Supreme Court only: the other orders and documents of the same
    #: matter. See `CaseListItem.sameMatter`.
    sameMatter: List[SameMatterEntry]


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
    #: Present, and True, only when one or more results were withheld by
    #: the restricted-case gate (a party's takedown, or a masked title).
    someRecordsWithheld: bool
    #: Present, and True, only when the restricted-case check itself could
    #: not run (fail-closed masking, not a confirmed clean page).
    restrictedCheckDegraded: bool


@dataclass
class SemanticSearchResult:
    """Result of `semantic_search`.

    `data` holds `SemanticSearchResultItem` objects, unless
    `meta["fallbackMode"]` is set, in which case it holds raw
    `CaseListItem` hits, see `SemanticSearchMeta`.
    """

    data: List[Union[SemanticSearchResultItem, CaseListItem]]
    meta: SemanticSearchMeta
    pagination: SemanticSearchPagination
    #: See `APIResponse.request_id`.
    request_id: Optional[str] = None


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
    #: Canonical 16 character CNR when the court published one.
    cnr: str
    courtName: str
    courtType: str
    caseYear: Union[int, str]
    registrationDate: str
    #: Where the case stands, for example "Pending" or "Disposed".
    caseStatus: str
    caseStage: str
    #: YYYY-MM-DD.
    nextHearingDate: str
    lastListedOn: str
    orderCount: int
    summary: str
    metadata: CaseDetailsMetadata
    hasDocuments: bool
    documentCount: int
    hasAnalysis: bool
    #: Tribunal cases only: the bench that heard the matter, for example
    #: `Delhi` for an ITAT appeal. Absent when the record does not name one.
    bench: str
    #: Acts and sections as the court record states them. Separate from the
    #: acts found by analysis of the judgment. Absent when the record lists
    #: none, on a protected matter, or on a district case not yet fetched
    #: from the court.
    courtRecordActs: List[CourtRecordAct]
    #: District cases only: FIR details as the court record states them,
    #: under the same rule as `courtRecordActs`.
    courtRecordFir: List[CourtRecordFir]


class CaseAdvocates(TypedDict):
    petitioner: List[str]
    respondent: List[str]


class CaseHearing(TypedDict):
    businessDate: Optional[str]
    hearingDate: Optional[str]
    purpose: Optional[str]
    judge: Optional[str]
    causeListType: Optional[str]


class _CaseDocumentRowRequired(TypedDict):
    id: str
    kind: str
    date: Optional[str]
    orderNumber: Optional[str]
    textAvailable: bool
    pdfAvailable: bool


class CaseDocumentRow(_CaseDocumentRowRequired, total=False):
    #: Present only when `textAvailable` is False: `no_text` (no readable
    #: text is held for this document) or `not_published` (the text of this
    #: case is not offered on the API).
    unavailableReason: str


class _CaseDocumentsRequired(TypedDict):
    caseId: str
    documents: List[CaseDocumentRow]


class CaseDocuments(_CaseDocumentsRequired, total=False):
    #: Present and True when the text of this case is not offered on the
    #: API. Every row then reads `textAvailable: False` and
    #: `pdfAvailable: False`.
    ordersTextWithheld: bool
    #: `not_published`, present with `ordersTextWithheld`.
    withheldReason: str


class CaseDocumentText(TypedDict):
    caseId: str
    documentId: str
    kind: str
    date: Optional[str]
    orderNumber: Optional[str]
    textAvailable: bool
    text: Optional[str]
    textLength: int
    textTruncated: bool
    pdfAvailable: bool


class CnrRefreshResult(TypedDict):
    input: str
    cnr: Optional[str]
    status: str
    caseId: Optional[str]
    lastRefreshedAt: Optional[str]


class CnrRefreshBatchSummary(TypedDict):
    requested: int
    started: int


class CnrRefreshBatch(TypedDict):
    results: List[CnrRefreshResult]
    summary: CnrRefreshBatchSummary


class CnrRefreshState(TypedDict):
    cnr: str
    state: str
    lastRefreshedAt: Optional[str]


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

    Internal metadata is stripped by the server and never appears here.
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
    """`pdfUrl` is a directly fetchable HTTPS link on the CourtMesh API host.

    It carries its own short lived signed token, so it needs no API key and no
    decryption, and fetching it costs no credits. Valid for `expiresIn` seconds.
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
    """Body of POST /request-timeline. `result.meta["liveFetch"]` (a plain
    bool, not modeled as its own TypedDict since `APIResponse.meta` is
    untyped) says whether this call actually reached a live source or
    served a stored read, regardless of whether `refresh` was requested.
    """

    requestId: str
    status: str
    cached: bool
    message: str
    orderCount: int
    orders: List[Order]
    #: Present, and False, only when this case's court does not support a
    #: live refresh at all (`refresh` is then a no-op regardless of tier).
    liveFetchSupported: bool


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


class HealthCheckResult(TypedDict, total=False):
    """One dependency's result within `HealthResponse["checks"]` (`deep=True` only).

    Live-verified 2026-09-19: the deployed server actually sends each
    `checks` entry as a bare status string (for example `"ok"`), never this
    richer object - `latencyMs`/`error` were not observed on the wire. Kept
    as the documented, richer shape a `checks` entry may still take (see
    `HealthCheckEntry`), in case a future or different deployment sends it.
    """

    status: str
    latencyMs: float
    error: str


#: A `HealthResponse["checks"]` entry: live-verified 2026-09-19 to always be
#: a bare status string in production (`"ok"` / `"degraded"` / `"down"`), not
#: a `HealthCheckResult` object. Both shapes are accepted so this type never
#: has to change again purely because the server started sending more detail
#: per dependency.
HealthCheckEntry = Union[str, HealthCheckResult]


class HealthResponse(TypedDict, total=False):
    """Body of GET /health. Not enveloped in `data`, unlike every other
    endpoint.

    `commit` is the deployed commit SHA, or `None` when the server does not
    report one. `checks` is present only when `deep=True` was passed to
    `health()`: one entry per dependency, each a bare status string in production - see `HealthCheckEntry`.
    `status` is `"healthy"` on the plain form; the deep form's `status` is
    one of `"healthy"`, `"degraded"` or `"unhealthy"` (the last one only
    alongside HTTP 503, meaning a hard dependency is down).
    """

    success: bool
    status: str
    version: str
    commit: Optional[str]
    checks: Dict[str, HealthCheckEntry]
    timestamp: str
    requestId: str


# ---------------------------------------------------------------------------
# 13. POST /party/screen
# ---------------------------------------------------------------------------


class PartyScreenIdentifiers(TypedDict, total=False):
    pan: str
    gstin: str
    cin: str
    llpin: str


class PartyScreenAddress(TypedDict, total=False):
    city: str
    state: str
    stateCode: str


if Literal is not None:
    PartyRole = Literal["petitioner", "respondent", "unknown"]
else:  # pragma: no cover
    PartyRole = str  # type: ignore[assignment,misc]


class PartyScreenConfidence(TypedDict, total=False):
    """`band` is one of `confirmed`, `probable`, `possible`, `unlikely`.
    `engine` is `"rules"` for the deterministic resolver, or `"llm"` when
    `adjudicate=True` triggered adjudication for this candidate (or the LLM
    path degraded and fell back to rules).
    """

    band: str
    #: Alias of `calibrated`, kept as a stable top-level "the number" field.
    score: float
    calibrated: float
    engine: str


class PartyScreenSignal(TypedDict, total=False):
    """`status` is one of `matched`, `conflicted`, `absent`. `weight` is one
    of `strong`, `moderate`, `weak`. `evidence` is the exact input token(s)
    the signal is grounded in, absent when there is nothing to cite.
    """

    name: str
    status: str
    weight: str
    evidence: str


class PartyScreenEvidence(TypedDict, total=False):
    entityMatch: bool
    matchedFields: List[str]
    strategies: List[str]
    signals: List[PartyScreenSignal]
    nameSimilarity: float
    disambiguatorPresent: bool


class PartyScreenMatch(TypedDict, total=False):
    """One confirmed or scored match. Items in `relatedButUnverified` are
    the same plain-case fields (`caseId` through `casePageUrl`) but never
    carry `partyRole`, `confidence`, `evidence` or `rationale` - see
    `PartyScreenRelatedMatch`.
    """

    caseId: str
    title: str
    court: str
    caseNumber: str
    cnr: str
    caseType: str
    acts: List[str]
    sections: List[str]
    petitioners: List[str]
    respondents: List[str]
    filingDate: str
    decisionDate: str
    disposalNature: str
    citation: str
    summary: str
    casePageUrl: str
    partyRole: str
    confidence: PartyScreenConfidence
    evidence: PartyScreenEvidence
    rationale: str
    #: Acts and sections as the court record states them, separate from
    #: `acts` and `sections` (which come from analysis of the judgment).
    #: Never present on a protected matter.
    courtRecordActs: List[CourtRecordAct]
    #: District cases only: FIR details as the court record states them.
    courtRecordFir: List[CourtRecordFir]
    #: Supreme Court only: the other orders and documents of the same matter.
    sameMatter: List[SameMatterEntry]


class PartyScreenRelatedMatch(TypedDict, total=False):
    """The plain case fields only: everything on `PartyScreenMatch` except
    `partyRole`, `confidence`, `evidence` and `rationale`. A candidate the
    screen found but could not confidently confirm, below `displayThreshold`
    or withheld from full confidence scoring for another reason.
    """

    caseId: str
    title: str
    court: str
    caseNumber: str
    cnr: str
    caseType: str
    acts: List[str]
    sections: List[str]
    petitioners: List[str]
    respondents: List[str]
    filingDate: str
    decisionDate: str
    disposalNature: str
    citation: str
    summary: str
    casePageUrl: str


class PartyScreenByBand(TypedDict, total=False):
    confirmed: int
    probable: int
    possible: int
    unlikely: int


class PartyScreenSummary(TypedDict, total=False):
    """`verdict` is one of `matches_found`, `no_matches_found`,
    `inconclusive`. `matches_found` describes what was found internally,
    independent of `displayThreshold` - raising the threshold can leave
    `matches` empty (`matchCount == 0`) while the verdict is still
    `matches_found`. `since` on the request forces `inconclusive` (it is a
    best-effort filter, so completeness can never be certified either way).
    `no_matches_found` is only returned when `coverage["exhaustive"]` is
    True and nothing was withheld.
    """

    matchCount: int
    byBand: PartyScreenByBand
    highestBand: Optional[str]
    verdict: str


class PartyScreenCoverage(TypedDict, total=False):
    """Whether this screen exhaustively searched the corpus, and whether
    any plan limit or restricted case removed candidates from the result.

    Exactly these six fields, no more: `candidatesEvaluated` and
    `adjudicationsRun` are not part of this object (`adjudicationsRun` is a
    top level field of `PartyScreenResult` instead, see below).
    """

    exhaustive: bool
    exhaustiveWithinFilters: bool
    planClamped: bool
    anyStrategyErrored: bool
    strategiesRun: List[str]
    someRecordsWithheld: bool


class PartyScreenRedactedName(TypedDict, total=False):
    """Live-verified 2026-09-19: shape of `query["name"]` on a replayed
    idempotent `party/screen` response, in place of the plain string sent on
    the original call."""

    redacted: bool
    length: int


class PartyScreenRedactedAliases(TypedDict, total=False):
    """Live-verified 2026-09-19: shape of `query["aliases"]` on a replayed
    idempotent `party/screen` response, in place of the plain list sent on
    the original call."""

    redacted: bool
    count: int


class PartyScreenQueryEcho(TypedDict, total=False):
    """The normalised request, echoed back for audit trails.

    `name` and `aliases` are the plain values sent on the original call, but
    live-verified 2026-09-19: when this is a replayed idempotent response
    (`result.replayed is True`, `Idempotency-Replayed: true` on the wire),
    the server redacts both instead of echoing them back - `name` becomes
    `{"redacted": True, "length": ...}` and `aliases` becomes
    `{"redacted": True, "count": ...}`. Check `"redacted" in query["name"]`
    (or `result.replayed`) before treating either as the original value.
    """

    name: Union[str, PartyScreenRedactedName]
    aliases: Union[List[str], PartyScreenRedactedAliases]
    entityType: str
    purpose: str
    #: The single court filter actually applied (never the raw request's
    #: string-or-list shape), absent when none was supplied.
    court: str
    since: str
    limit: int
    adjudicate: bool
    displayThreshold: float


class PartyScreenResult(TypedDict, total=False):
    """Body of POST /party/screen. `query` echoes the normalised request
    for audit trails. `notice` links the case removal / takedown policy.

    `adjudicationsRun`: how many candidates were actually sent to the LLM
    for adjudication. Requesting `adjudicate=True` alone does not guarantee
    this is greater than 0 - every candidate may already have been decided
    deterministically, in which case the model is never called and this
    stays 0, which is also why the adjudication credit surcharge is billed
    on this being greater than 0, not on the request flag alone.
    """

    query: PartyScreenQueryEcho
    summary: PartyScreenSummary
    matches: List[PartyScreenMatch]
    relatedButUnverified: List[PartyScreenRelatedMatch]
    coverage: PartyScreenCoverage
    adjudicationsRun: int
    notice: str


class PartyScreenMeta(TypedDict, total=False):
    """100 credits when matches are found, 20 when none are, plus a flat
    surcharge only when the result's `adjudicationsRun` is greater than 0
    (see `PartyScreenResult`).
    """

    creditsCharged: int
    adjudicated: bool
    corpusAsOf: str


# ---------------------------------------------------------------------------
# POST /party/profile and GET /party/profile/{requestId} (API 1.8.0)
# ---------------------------------------------------------------------------


class PartyProfileWebhook(TypedDict, total=False):
    """`webhook` on a full mode request. `url` is required and must be a
    public https address with no credentials in it. `headers` (at most 20)
    are sent with the notice, for example your own `Authorization`."""

    url: str
    headers: Dict[str, str]


class PartyProfileCountCredits(TypedDict):
    count: int
    credits: int


class PartyProfileCredits(TypedDict):
    credits: int


class PartyProfileTokensCredits(TypedDict):
    tokens: int
    credits: int


class _PartyProfileCreditsBreakdownRequired(TypedDict):
    searches: PartyProfileCountCredits
    caseRecords: PartyProfileCountCredits
    documentLists: PartyProfileCountCredits


class PartyProfileCreditsBreakdown(_PartyProfileCreditsBreakdownRequired, total=False):
    """`meta["creditsBreakdown"]` of a quick profile: what each part cost.
    `aiReview` is present only when the AI review was charged, and
    `minimumCharge` only when the call used less than the minimum (the
    top up, so the parts add up to `meta["creditsCharged"]`)."""

    aiReview: PartyProfileCountCredits
    minimumCharge: PartyProfileCredits


class PartyProfileMeta(TypedDict, total=False):
    """`meta` of a quick profile. `creditsCharged` is what left the wallet,
    0 whenever `metered` is False."""

    creditsCharged: int
    metered: bool
    creditsBreakdown: PartyProfileCreditsBreakdown
    adjudicated: bool
    corpusAsOf: str
    responseTime: str
    requestId: str


class PartyProfileSubject(TypedDict, total=False):
    """`name` and `entityType` are always present; `aliases` only when the
    request gave some."""

    name: str
    entityType: str
    aliases: List[str]


class PartyProfileByRole(TypedDict, total=False):
    petitioner: int
    respondent: int
    unknown: int


class PartyProfileSummary(TypedDict, total=False):
    """`profile` of an identity, built by code from the returned cases (no
    model). Counts of zero, empty lists and unknown dates are left out;
    `pending` and `disposed` are always present."""

    summary: str
    byCourtType: Dict[str, int]
    byRole: PartyProfileByRole
    pending: int
    disposed: int
    statusUnknown: int
    categories: List[str]
    flags: List[str]
    #: YYYY-MM-DD.
    firstSeen: str
    #: YYYY-MM-DD.
    lastActivity: str


class PartyProfileDocumentLinks(TypedDict, total=False):
    """`text` is the path of the text endpoint relative to the API base, or
    `None` when the text is not offered. `pdf` is a download URL valid for
    one hour that needs no API key, or `None`; the first time it is opened it
    is charged as one PDF call to the key that read the profile, free after
    that. `pdfExpiresAt` is present only with a link."""

    text: Optional[str]
    pdf: Optional[str]
    pdfExpiresAt: str


class PartyProfileDocument(TypedDict):
    """One document held for a case, never its body. `kind` is
    `case_document` or `order`; `date` is YYYY-MM-DD or `None`."""

    documentId: str
    kind: str
    date: Optional[str]
    links: PartyProfileDocumentLinks


class PartyProfileCourtRefresh(TypedDict, total=False):
    """Full mode only. `status` is one of `refreshed`, `already_current`,
    `recently_refreshed`, `not_supported_for_this_court`, `not_available`,
    `not_found_at_court`, `no_cnr`, `in_progress`, `failed`, `timed_out`,
    `not_started`. `attempts` is present only when more than one try was
    made."""

    status: str
    attempts: int


class PartyProfileCaseAnalysis(TypedDict, total=False):
    """Full mode only. `status` is `new`, `updated`, `existing`, `short`
    (written for this request only because `maxCredits` could not cover a
    full analysis of every case) or `not_done` (with a `reason`)."""

    status: str
    summary: str
    outcome: Optional[str]
    issues: List[str]
    analysedAt: str
    reason: str


class PartyProfileCase(TypedDict, total=False):
    """One case of the primary identity. Fields with no value are left out.
    `caseId`, `partyRole`, `status`, `decisionDate` (None for a pending
    case) and `confidence` are always present. `caseNumber` is given only
    when it differs from `cnr`."""

    caseId: str
    cnr: str
    caseNumber: str
    court: str
    courtType: str
    #: Tribunal cases only: the bench that heard the matter.
    bench: str
    caseType: str
    title: str
    petitioners: List[str]
    respondents: List[str]
    #: `petitioner`, `respondent` or `unknown`.
    partyRole: str
    #: `pending`, `disposed` or `unknown`.
    status: str
    filingDate: str
    nextHearingDate: str
    decisionDate: Optional[str]
    disposalNature: str
    #: Acts from analysis of the judgment, when `include` has `acts`.
    acts: List[str]
    sections: List[str]
    courtRecordActs: List[CourtRecordAct]
    #: District cases only.
    courtRecordFir: List[CourtRecordFir]
    #: Supreme Court only.
    sameMatter: List[SameMatterEntry]
    #: `confirmed`, `probable`, `possible` or `unlikely`.
    confidence: str
    matchReasons: List[str]
    #: Newest first, when `include` has `documents` and the listing was read.
    documents: List[PartyProfileDocument]
    documentsNote: str
    #: Present (and True) only when the case holds more documents than one
    #: listing carries.
    documentsMore: bool
    courtRefresh: PartyProfileCourtRefresh
    analysis: PartyProfileCaseAnalysis


class PartyProfileIdentity(TypedDict, total=False):
    """The primary identity: the cases judged to belong to the person or
    company asked about. `confidence` is the band of its strongest case."""

    confidence: str
    why: List[str]
    caseCount: int
    profile: PartyProfileSummary
    cases: List[PartyProfileCase]


class PartyProfileOtherCase(TypedDict, total=False):
    """Basic facts of one case of another identity, at no extra cost. Only
    `caseId` is always present; `get_case` gives the case in full."""

    caseId: str
    cnr: str
    caseNumber: str
    court: str
    caseType: str
    title: str
    petitioners: List[str]
    respondents: List[str]
    partyRole: str
    filingDate: str
    decisionDate: str
    disposalNature: str


class PartyProfileOtherIdentity(TypedDict, total=False):
    """An identity other than the primary, listed under
    `possibleOtherPeople`. `why` says why it was kept apart."""

    confidence: str
    why: List[str]
    caseCount: int
    caseIds: List[str]
    cases: List[PartyProfileOtherCase]


class PartyProfileKeyRisk(TypedDict):
    risk: str
    caseIds: List[str]


class PartyProfileNotableCase(TypedDict):
    caseId: str
    why: str


class PartyProfileOpenMatter(TypedDict):
    caseId: str
    note: str


class PartyProfileAnalysis(TypedDict):
    """Full mode only: one analysis of the person or company, written by a
    model from this profile's own court record facts and case analyses.
    Every case id in it is a case of this profile. Being a party to a case
    is not a finding against anyone."""

    overview: str
    litigationPattern: str
    keyRisks: List[PartyProfileKeyRisk]
    notableCases: List[PartyProfileNotableCase]
    openMatters: List[PartyProfileOpenMatter]
    caveats: List[str]


class PartyProfileResult(TypedDict, total=False):
    """`data` of a quick profile, and `result` of a completed full mode
    request.

    `verdict` is `identity_found`, `no_confirmed_identity`,
    `no_matches_found` or `inconclusive`. `identities` holds the primary
    identity in full, and is empty when none reaches `minConfidence`.
    `notes` is always present and lists anything left out (empty when
    nothing was). `partyAnalysis` is full mode only, and `None` when it
    could not be written (`notes` says why).
    """

    subject: PartyProfileSubject
    verdict: str
    summary: str
    identities: List[PartyProfileIdentity]
    possibleOtherPeople: List[PartyProfileOtherIdentity]
    relatedButUnverified: List[PartyScreenRelatedMatch]
    partyAnalysis: Optional[PartyProfileAnalysis]
    notes: List[str]
    notice: str


class PartyProfileAcceptedWebhook(TypedDict, total=False):
    """`signingSecret` is shown once: store it to check the
    `CourtMesh-Signature` header of the completion notice."""

    signingSecret: str
    note: str


class PartyProfileAccepted(TypedDict, total=False):
    """`data` of the 202 answer to a full mode request. Nothing is charged
    yet. `status` is `queued`; read the request with `get_party_profile`.
    `webhook` is present only when the request carried one."""

    requestId: str
    mode: str
    status: str
    statusUrl: str
    maxCredits: int
    webhook: PartyProfileAcceptedWebhook


class PartyProfileProgress(TypedDict):
    casesFound: int
    refreshesStarted: int
    refreshesFinished: int
    casesAnalysed: int
    casesNotAnalysed: int
    #: `pending`, `done` or `not_done`.
    partyAnalysis: str


class PartyProfileCaseAnalysesCredits(TypedDict):
    full: int
    short: int
    existing: int
    tokens: int
    credits: int


class _PartyProfileStageBreakdownRequired(TypedDict):
    search: PartyProfileCredits
    courtRefreshes: PartyProfileCountCredits
    caseAnalyses: PartyProfileCaseAnalysesCredits
    partyAnalysis: PartyProfileTokensCredits


class PartyProfileStageBreakdown(_PartyProfileStageBreakdownRequired, total=False):
    minimumCharge: PartyProfileCredits


class _PartyProfileRequestCreditsRequired(TypedDict):
    charged: int
    maxCredits: int
    breakdown: PartyProfileStageBreakdown


class PartyProfileRequestCredits(_PartyProfileRequestCreditsRequired, total=False):
    """`charged` is what has left the wallet for this request so far.
    `unconfirmed` is True while the outcome of a debit is not yet confirmed,
    so `charged` may still rise by that stage."""

    unconfirmed: bool


class PartyProfileWebhookState(TypedDict):
    #: `pending`, `delivered` or `failed`.
    state: str
    attempts: int


class PartyProfileFailure(TypedDict):
    """`code` is one of `INTERNAL_ERROR`, `PARTY_SCREEN_SEARCH_DEGRADED`,
    `INSUFFICIENT_CREDITS`, `SETTLEMENT_UNCONFIRMED`, `API_KEY_INACTIVE`,
    `PROFILE_FAILED`."""

    code: str
    message: str


class PartyProfileRequestStatus(TypedDict, total=False):
    """`data` of `GET /party/profile/{requestId}`.

    `status` is `queued`, `running`, `completed` or `failed`. `stage` is
    present while queued or running (`find`, `refresh`, `await_refresh`,
    `reread`, `analyse`, `review`, `finish`). `result` is present once
    `status` is `completed` and the result has not expired; after 30 days
    `resultExpired` is True and only the status, progress and credits
    remain. `failure` is present on a failed request, and what it was
    charged before failing stays in `credits`.
    """

    requestId: str
    mode: str
    status: str
    stage: str
    progress: PartyProfileProgress
    createdAt: str
    startedAt: Optional[str]
    finishedAt: Optional[str]
    resultExpiresAt: Optional[str]
    credits: PartyProfileRequestCredits
    webhook: PartyProfileWebhookState
    failure: PartyProfileFailure
    resultExpired: bool
    result: PartyProfileResult


# ---------------------------------------------------------------------------
# 14. GET /coverage
# ---------------------------------------------------------------------------


class CoverageByCourtType(TypedDict, total=False):
    courtType: str
    records: int
    documentBearing: int
    latestDecisionDate: Optional[str]


class CoverageByYear(TypedDict, total=False):
    year: int
    records: int


class CoverageCourt(TypedDict, total=False):
    court: str
    #: Nullable as of 2026-09-19 (live-verified: still populated for every
    #: observed row, but the spec now allows `None`).
    courtType: Optional[str]
    records: int
    documentBearing: int
    earliestDecisionDate: Optional[str]
    latestDecisionDate: Optional[str]
    #: How many business days behind live filings this court's records
    #: appear to be. `None` when it cannot be computed.
    businessDaysBehind: Optional[int]


class CoverageDistrictCourts(TypedDict, total=False):
    """District Courts are reported as a single rolled up row."""

    records: int
    documentBearing: int
    latestDecisionDate: Optional[str]
    businessDaysBehind: Optional[int]


class CoverageData(TypedDict, total=False):
    """Body of GET /coverage.

    Only these fields are ever returned.
    """

    generatedAt: str
    index: str
    total: int
    documentBearing: int
    statusOnly: int
    byCourtType: List[CoverageByCourtType]
    byYear: List[CoverageByYear]
    courts: List[CoverageCourt]
    districtCourts: CoverageDistrictCourts


class CoverageMeta(TypedDict, total=False):
    """Live-verified 2026-09-19: a previously documented `ageSeconds` field
    does not exist on the wire; the server sends two distinct ages instead,
    both always present."""

    generatedAt: str
    cacheTtlSeconds: int
    #: How old the underlying data snapshot itself is - seconds since
    #: `data["generatedAt"]` - independent of when this service happened to
    #: fetch it.
    snapshotAgeSeconds: int
    #: How long ago this service fetched and cached the snapshot. `stale`
    #: is judged against this one, not `snapshotAgeSeconds`.
    cacheAgeSeconds: int
    #: True once `cacheAgeSeconds` reaches `cacheTtlSeconds` - only possible
    #: when a refresh failed or was unusually delayed.
    stale: bool
    corpusNote: str


# ---------------------------------------------------------------------------
# 15. GET /usage
# ---------------------------------------------------------------------------


if Literal is not None:
    ApiTier = Literal["free", "payg", "scale", "enterprise"]
else:  # pragma: no cover
    ApiTier = str  # type: ignore[assignment,misc]


class UsageWalletOwner(TypedDict, total=False):
    type: str
    id: str


class UsageBalance(TypedDict, total=False):
    total: int
    monthlyGrant: int
    signupGrant: int
    purchased: int


class UsageTierLimits(TypedDict, total=False):
    """Mirrors the per tier limits the API reports.
    `-1` means unlimited on any per period field for a tier that has a
    numbered cap.

    `limits` itself is always a populated object, `data["limits"]` is
    required and never `None`. `requestsPerMinute` is the limit applied to
    this key (matches `X-RateLimit-Limit`); `published` is this tier's
    documented number from the "Rate limits and per-IP limits" table. Every field except `requestsPerMinute` and
    `published` is typed `Optional`; treat
    `None` the same as `-1`/unlimited (or "allowed") unless you have
    evidence a given tier distinguishes the two.
    """

    requestsPerMinute: int
    requestsPerDay: Optional[int]
    requestsPerMonth: Optional[int]
    maxPageSize: Optional[int]
    maxPaginationDepth: Optional[int]
    distinctCaseFetchesPerDay: Optional[int]
    pdfCallsPerMonth: Optional[int]
    aiCallsPerMonth: Optional[int]
    concurrentAnalyzeJobs: Optional[int]
    apiKeys: Optional[int]
    semanticSearchAllowed: Optional[bool]
    liveFetchAllowed: Optional[bool]
    liveFetchesPerDay: Optional[int]
    analysisReadAllowed: Optional[bool]
    partyScreensPerMonth: Optional[int]
    #: This tier's number in the OpenAPI rate-limit table. Added 2026-09-19.
    published: int


class UsagePeriod(TypedDict, total=False):
    """The [start, end] ISO timestamps of the Asia/Kolkata calendar month
    this usage was aggregated over."""

    start: str
    end: str
    key: str


class UsageByEndpoint(TypedDict, total=False):
    endpoint: str
    calls: int
    credits: int


class UsageData(TypedDict, total=False):
    """Body of GET /usage."""

    tier: str
    walletOwner: UsageWalletOwner
    balance: UsageBalance
    limits: UsageTierLimits
    period: UsagePeriod
    creditsUsedThisPeriod: int
    byEndpoint: List[UsageByEndpoint]
    subscriptionRenewsAt: Optional[str]


class UsageMeta(TypedDict, total=False):
    requestId: str
    #: Whether this account is self serve.
    selfServe: bool


# ---------------------------------------------------------------------------
# 16. GET /me
# ---------------------------------------------------------------------------


class MeData(TypedDict, total=False):
    userId: str
    email: str
    name: Optional[str]
    role: Optional[str]
    #: Only present when the account belongs to an organization.
    organizationId: str


# ---------------------------------------------------------------------------
# 17. GET /audit
# ---------------------------------------------------------------------------


class AuditHit(TypedDict, total=False):
    id: str
    userId: str
    organizationId: str
    endpoint: str
    method: str
    statusCode: int
    responseTime: float
    isAiAnalysis: bool
    creditsDeducted: int
    #: Observed `None` in production for hits with nothing to log (for
    #: example a plain `GET /me`), not only omitted.
    metadata: Optional[Dict[str, Any]]
    #: Live-verified 2026-09-19 against the redeployed server and its
    #: updated OpenAPI spec: `ipHash` (a SHA-256 hex digest of the caller's
    #: IP) is still sent, and remains the only IP-shaped field - raw
    #: `ipAddress` does not exist on the wire. `userAgent`, however, is no
    #: longer sent at all as of this deploy (dropped for privacy alongside
    #: raw `ipAddress`, per the endpoint's updated description); this SDK's
    #: field for it is removed.
    ipHash: str
    createdAt: str


class AuditTopEndpoint(TypedDict, total=False):
    endpoint: str
    count: int


class AuditSummary(TypedDict, total=False):
    totalHits: int
    totalAiAnalysisHits: int
    avgResponseTime: float
    successfulHits: int
    #: A string, e.g. `"98.5"` with one decimal place.
    successRate: str
    totalCreditsDeducted: int


class AuditData(TypedDict, total=False):
    hits: List[AuditHit]
    summary: AuditSummary
    topEndpoints: List[AuditTopEndpoint]


class AuditPagination(TypedDict, total=False):
    total: int
    limit: int
    offset: int
    hasMore: bool


@dataclass
class AuditResult:
    """Result of `audit`. `GET /audit` nests its own pagination shape under
    the envelope, distinct from `SearchCasesPagination`/`SemanticSearchPagination`.
    """

    data: AuditData
    pagination: AuditPagination
    request_id: Optional[str] = None


class AuditDeleteResult(TypedDict, total=False):
    """`data` of `DELETE /audit`.

    `before` is the time used, in UTC. `removed` counts the calls removed
    from `audit()` by this request. `complete` is False when part is left:
    send the same request again to finish.
    """

    before: str
    removed: int
    complete: bool
    note: str


# ---------------------------------------------------------------------------
# 18. GET /reference/courts
# ---------------------------------------------------------------------------

#: court/courtType -> display name(s).
CourtNamesMap = Dict[str, List[str]]


class CourtHierarchy(TypedDict, total=False):
    #: The 4 court types (level 1).
    courtTypes: List[str]
    #: courtType -> court values (level 2). High Court is collapsed to representatives.
    courtsByType: CourtNamesMap
    #: court -> courtName values (level 3). Includes an entry per High Court representative.
    courtNamesByCourt: CourtNamesMap


# ---------------------------------------------------------------------------
# 19. GET /reference/case-types
# ---------------------------------------------------------------------------


class CaseTypeEntry(TypedDict, total=False):
    code: str
    fullForm: str
    primaryType: str
    nature: str


# ---------------------------------------------------------------------------
# 20. POST /party/screen/batch
# ---------------------------------------------------------------------------


class PartyScreenBatchItemOk(TypedDict, total=False):
    clientRef: str
    #: The item's 0 based position in the request's `items` array.
    index: int
    ok: bool
    screen: PartyScreenResult


class PartyScreenBatchError(TypedDict, total=False):
    code: str
    message: str


class PartyScreenBatchItemResult(TypedDict, total=False):
    """One entry of `data["results"]`. `ok` discriminates between the
    success shape (`screen` present) and the failure shape (`error`
    present).
    """

    clientRef: str
    index: int
    ok: bool
    screen: PartyScreenResult
    error: PartyScreenBatchError


class PartyScreenBatchSummary(TypedDict, total=False):
    items: int
    matchesFound: int
    noMatches: int
    inconclusive: int
    errors: int


class PartyScreenBatchResult(TypedDict, total=False):
    """Body of POST /party/screen/batch."""

    results: List[PartyScreenBatchItemResult]
    summary: PartyScreenBatchSummary


class PartyScreenBatchMeta(TypedDict, total=False):
    """`creditsCharged` is the sum across every item that ran (a per-item
    error charges nothing for that item). `truncated`/`truncatedReason` are
    present only when the batch itself was clamped.
    """

    creditsCharged: int
    requestId: str
    truncated: bool
    truncatedReason: str


# ---------------------------------------------------------------------------
# CNR lookup, watchlists, change feed and webhooks (0.5.0)
# ---------------------------------------------------------------------------


class CursorPagination(TypedDict, total=False):
    """Pagination block of the monitoring list endpoints. `nextCursor` is
    returned even on an empty `/changes` page so a client can poll forward."""

    nextCursor: Optional[str]
    hasMore: bool
    limit: int


@dataclass
class CursorListResult(Generic[T]):
    """One page of a monitoring list endpoint."""

    data: List[T]
    pagination: CursorPagination
    meta: Dict[str, Any]
    #: See `APIResponse.request_id`.
    request_id: Optional[str] = None

    @property
    def next_cursor(self) -> Optional[str]:
        return self.pagination.get("nextCursor")


class CnrLookup(TypedDict, total=False):
    """`data` of `GET /cases/by-cnr/{cnr}`. `status` is `found` or `pending` in a success body
    (`not_found` surfaces as `NotFoundError`). `requestId` is opaque: poll the same call, not `get_timeline`.
    When this comes from `search_cases(cnr=...)` instead, it is one ordinary search hit, not this shape."""

    cnr: str
    status: str
    case: Optional[CaseDetails]
    requestId: Optional[str]


class WatchlistItemInput(TypedDict, total=False):
    cnr: str
    reference: str
    label: str


class Watchlist(TypedDict, total=False):
    id: str
    name: str
    itemCount: int
    createdAt: str
    updatedAt: str
    metadata: Optional[Dict[str, Any]]


class WatchItemResult(TypedDict, total=False):
    """Outcome of adding one CNR. `result` is `watching`, `pending`,
    `invalid`, `duplicate`, `cap_exceeded` or `not_found`.

    `cap_exceeded` covers your watched CNR cap, the daily limit on adding
    CNRs we do not hold yet, and the daily add allowance per account (Free 50,
    Pay As You Go 5,000, Scale 50,000, Enterprise 500,000 per Indian calendar
    day); `message` says which. `not_found` also covers a case taken down at a
    party's request and a CNR the court portal had nothing for in the last 24
    hours (nothing is refetched until that cooldown passes)."""

    cnr: str
    result: str
    message: str


class WatchSnapshot(TypedDict, total=False):
    """Dates are `YYYY-MM-DD` (Indian calendar). A court's year 9999 "no date"
    comes back as `None`."""

    caseStatus: Optional[str]
    caseStage: Optional[str]
    nextHearingDate: Optional[str]
    lastListedOn: Optional[str]
    orderCount: Optional[int]
    latestOrderDate: Optional[str]
    disposalNature: Optional[str]


class WatchlistItem(TypedDict, total=False):
    """`status` is `watching`, `pending`, `not_found`, `error` or `unavailable`.

    `unavailable` means the case was taken down at a party's request: no events
    are sent for it, and `caseId`, `court`, `title`, `snapshot`,
    `lastCheckedAt` and `lastChangedAt` are all `None`."""

    cnr: str
    reference: Optional[str]
    label: Optional[str]
    status: str
    caseId: Optional[str]
    court: Optional[str]
    title: Optional[str]
    lastCheckedAt: Optional[str]
    lastChangedAt: Optional[str]
    snapshot: Optional[WatchSnapshot]
    addedAt: str


class ChangeEventWatchlistRef(TypedDict, total=False):
    id: str
    reference: Optional[str]


class ChangeEvent(TypedDict, total=False):
    """One change event. The feed and the webhook body are identical.

    `type` is one of `case.tracking_started`, `case.order_added`,
    `case.hearing_date_changed`, `case.status_changed`,
    `case.stage_changed`, `case.disposed`, `case.not_found` or
    `webhook.test`. Dedupe on `id`: delivery is at least once.

    `case.tracking_started` arrives once the first fresh refresh of the case
    completes (immediately when the stored record is already current), not at
    the moment of the add. After that, a burst of new orders announces only
    the newest 20, and an order dated more than 7 days before you started
    watching is never announced to you. A taken down case sends no events.
    """

    id: str
    type: str
    createdAt: str
    cnr: str
    caseId: Optional[str]
    watchlists: List[ChangeEventWatchlistRef]
    data: Dict[str, Any]
    #: `case_restricted`, present only when the case was removed after this
    #: event was recorded. The event keeps its place in the feed, with
    #: `data` empty and `caseId` None.
    withheld: str


class Webhook(TypedDict, total=False):
    id: str
    url: str
    events: List[str]
    watchlistIds: Optional[List[str]]
    description: Optional[str]
    enabled: bool
    disabledReason: Optional[str]
    #: True for 24 hours after a secret rotation, while both secrets sign.
    secretRotating: bool
    createdAt: str
    updatedAt: str
    #: Present only on create and rotate. Shown once.
    secret: str


class WebhookDelivery(TypedDict, total=False):
    """`status` is `pending`, `succeeded` or `failed`. `lastError` is
    `"expired"` on a delivery that was never attempted for 24 hours and was
    marked `failed` instead of being sent."""

    id: str
    eventId: str
    eventType: str
    status: str
    attempts: int
    lastAttemptAt: Optional[str]
    nextAttemptAt: Optional[str]
    lastResponseStatus: Optional[int]
    lastError: Optional[str]
    createdAt: str


# ---------------------------------------------------------------------------
# Acts and sections (0.6.0). These endpoints need the `legislation` scope.
# Each call costs 1 credit when it returns something and nothing when it
# returns nothing. Repeal status is on every act and provision: check it
# before relying on one.
# ---------------------------------------------------------------------------


class ActsPagePagination(TypedDict, total=False):
    """Pagination of the page numbered acts endpoints. `total` counts matches
    before unpublished records are removed, so a page can hold fewer rows
    than `limit`."""

    page: int
    limit: int
    total: int
    totalPages: int
    hasMore: bool


class ActSummary(TypedDict, total=False):
    slug: str
    title: str
    docClass: str
    year: Optional[int]
    number: Optional[str]
    citation: Optional[str]
    jurisdiction: str
    stateName: Optional[str]
    #: Short forms this act is known by.
    aliases: List[str]
    #: Whether the act has been repealed. Check this before relying on it.
    repealed: bool
    #: What repealed it, and from when.
    repealNote: Optional[str]


class Act(ActSummary, total=False):
    shortTitle: Optional[str]
    longTitle: Optional[str]
    ministryName: Optional[str]
    subjects: List[str]
    #: ``sections`` has a table of contents. ``full-text`` was published only as
    #: one document, so it has no provisions to list.
    textSource: str
    sectionCount: int
    #: A caveat about how the text was extracted, when there is one.
    textNote: Optional[str]


class ActMatch(TypedDict, total=False):
    act: ActSummary
    #: ``short_form`` is an exact match on a known short form, otherwise ``text``.
    matchedBy: str


class ActResolution(TypedDict, total=False):
    """`data` of `resolve_act`: up to five candidates, best first."""

    query: str
    matches: List[ActMatch]


class ActAmendment(TypedDict, total=False):
    slug: Optional[str]
    title: str
    year: Optional[int]
    number: Optional[str]
    citation: Optional[str]
    sourceUrl: Optional[str]


class ActHistory(TypedDict, total=False):
    """`data` of `get_act_history`. Act level only: it does not map old
    sections to new ones."""

    slug: str
    #: What repealed this act. Empty when no repeal is recorded.
    succession: List[Dict[str, Any]]
    amendments: List[ActAmendment]
    #: Amendments made by a State, which apply only in that State.
    stateAmendments: List[Dict[str, Any]]
    editions: List[Dict[str, Any]]
    #: Rules, regulations and notifications made under the act, up to 100 of each kind.
    instruments: List[Dict[str, Any]]
    #: How many instruments of each kind exist, which can exceed what is listed.
    instrumentCounts: Dict[str, int]


class ActSectionEntry(TypedDict, total=False):
    """One provision in an act's table of contents."""

    actSlug: str
    slug: str
    partType: str
    number: Optional[str]
    heading: Optional[str]
    #: Judgments recorded as citing this provision. Not an exhaustive count.
    citationCount: int
    #: Whether this provision on its own was repealed. See `actRepealed` for the act.
    repealedProvision: bool


class SectionRow(ActSectionEntry, total=False):
    """A provision with its act, as returned by `search_sections` and `lookup_section`."""

    actTitle: Optional[str]
    actYear: Optional[int]
    jurisdiction: Optional[str]
    stateName: Optional[str]
    #: Whether the act this provision belongs to was repealed.
    actRepealed: bool
    actRepealNote: Optional[str]
    #: Present on search results.
    snippet: str


class ActSectionBlock(TypedDict, total=False):
    depth: int
    kind: str
    marker: Optional[str]
    text: str


class ActSectionAmendment(TypedDict, total=False):
    action: str
    note: str
    byInstrument: Optional[str]
    byYear: Optional[int]


class ActSection(SectionRow, total=False):
    """`data` of `get_act_section`."""

    textNote: Optional[str]
    #: The whole provision as plain text.
    text: str
    #: The same text with its structure: subsections, clauses, provisos, explanations.
    blocks: List[ActSectionBlock]
    amendments: List[ActSectionAmendment]
    previous: Optional[Dict[str, Any]]
    next: Optional[Dict[str, Any]]


class SectionMatch(TypedDict, total=False):
    section: SectionRow
    #: ``alias``, ``title`` or ``number_only``.
    matchedBy: str
    #: True when no act was named, so this is one of many provisions with that
    #: number. Choose or name the act.
    ambiguous: bool


class SectionLookup(TypedDict, total=False):
    """`data` of `lookup_section`: provisions the citation could name, best first."""

    query: str
    matches: List[SectionMatch]


class CitingCase(TypedDict, total=False):
    #: Read the judgment with `get_case(id)`.
    id: str
    title: Optional[str]
    court: Optional[str]
    courtType: Optional[str]
    cnr: Optional[str]
    caseNumber: Optional[str]
    #: ISO date.
    decisionDate: Optional[str]


class CitingCases(TypedDict, total=False):
    """`data` of `list_section_citing_cases`: judgments citing exactly one
    provision, newest first. Not an exhaustive list of every judgment applying
    the provision, and an empty list does not mean no judgment applied it.
    Some matters are never listed."""

    section: Dict[str, Any]
    #: False for a provision we do not list judgments for, including sexual
    #: offences and cruelty provisions. That says nothing about whether any exist.
    listAvailable: bool
    note: str
    #: A page can hold fewer rows than `limit`, or none, while
    #: `pagination["hasMore"]` is true. Keep following `nextCursor`.
    cases: List[CitingCase]


@dataclass
class ActsPageResult(Generic[T]):
    """One page of a page numbered acts endpoint (`search_acts`,
    `list_act_sections`, `search_sections`)."""

    data: List[T]
    meta: Dict[str, Any]
    pagination: ActsPagePagination
    #: See `APIResponse.request_id`.
    request_id: Optional[str] = None


@dataclass
class CitingCasesResult:
    """Result of `list_section_citing_cases`. `pagination` holds
    `limit`, `hasMore` and `nextCursor`. A page can be empty while `hasMore`
    is true."""

    data: CitingCases
    meta: Dict[str, Any]
    pagination: CursorPagination
    #: See `APIResponse.request_id`.
    request_id: Optional[str] = None

    @property
    def next_cursor(self) -> Optional[str]:
        return self.pagination.get("nextCursor")
