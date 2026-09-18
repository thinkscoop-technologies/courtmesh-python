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
    does not exist on this endpoint. `nextCursor` has two shapes depending
    on whether the API self-serve tiers flag is on for the account:
    a signed, opaque string (pass it back as `cursor`) when it is on, or the
    legacy raw OpenSearch sort tuple (an array, pass it back as a JSON
    encoded `searchAfter` string) when it is off. Either way, `None` means
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
    """Convenience wrapper for non-paginated endpoints: unwrapped data + meta.

    Attributes:
        request_id: the request id for this call, either the server's own
            `meta["requestId"]`/body level `requestId` when it set one, or
            (backfilled client side as a fallback) the `X-Request-Id`
            response header.
        replayed: `True` only when this call sent an `idempotency_key` that
            matched a previous request within its 24 hour window: the
            server returned the stored response instead of doing the work
            again, and nothing was charged. Only ever set on the five
            idempotency-key-aware methods (`screen_party`,
            `screen_party_batch`, `analyze_case`, `analyze_consolidated`,
            `request_timeline`); `None` on every other response.
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
# 2. POST /search/cases
# ---------------------------------------------------------------------------


class CaseListItem(TypedDict, total=False):
    """One OpenSearch hit: `_source` fields plus `id`/`score` (the
    documented contract names; `_id`/`_score` are the legacy field names,
    kept for backwards compatibility).

    Every field is optional, presence varies per document. Note that
    `detailedSummary`, `holding`, `keyFacts_joined`, `legalIssues_joined`
    and `courtsReasoning` are indexed but excluded from `_source`, so they
    never appear here.
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


@dataclass
class SearchCasesResult:
    """Result of `search_cases`, one page of raw OpenSearch hits."""

    data: List[CaseListItem]
    meta: SearchCasesMeta
    pagination: SearchCasesPagination
    #: See `APIResponse.request_id`.
    request_id: Optional[str] = None


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
    `meta["fallbackMode"] == "opensearch"`, in which case it holds raw
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

    `commit` is the deployed commit SHA, or `None` when the server has no
    `GIT_SHA` set. `checks` is present only when `deep=True` was passed to
    `health()`: one entry per dependency (Mongo, OpenSearch, Qdrant, Redis,
    IAM), each a bare status string in production - see `HealthCheckEntry`.
    `status` is `"healthy"` on the plain form; the deep form's `status` is
    one of `"healthy"`, `"degraded"` or `"unhealthy"` (the last one only
    alongside HTTP 503, meaning a hard dependency - Mongo or OpenSearch - is
    down).
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
    #: How many business days behind live filings this court's index
    #: appears to be. `None` when it cannot be computed.
    businessDaysBehind: Optional[int]


class CoverageDistrictCourts(TypedDict, total=False):
    """District Courts are reported as a single rolled up row, the index
    has no per-state field."""

    records: int
    documentBearing: int
    latestDecisionDate: Optional[str]
    businessDaysBehind: Optional[int]


class CoverageData(TypedDict, total=False):
    """Body of GET /coverage.

    Only these fields are ever returned - the server's
    `sanitizeCoverageResponse` strips every other field the raw OpenSearch
    coverage response carries (operational bookkeeping such as
    `byYearMissing`, `sumOtherDocCount`, `docCountErrorUpperBound`, an
    upstream `ageSeconds`, and the refresh job's own job status) before this
    is ever cached or served - confirmed against the redeployed OpenAPI spec
    and a live call 2026-09-19.
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
    """Mirrors the server's `TierLimits` (server/config/api-tiers.ts).
    `-1` means unlimited on any per period field for a tier that has a
    numbered cap.

    `limits` itself is always a populated object (verified live and in the
    redeployed OpenAPI spec, `data["limits"]` is required and never `None`).
    Live-verified 2026-09-19 on an Enterprise key with the API self-serve
    tiers flag off: `requestsPerMinute` is 10, the flat legacy ceiling
    actually enforced right now (matches `X-RateLimit-Limit`); `published`
    is this tier's documented number (600 for enterprise) from the "Rate
    limits and per-IP limits" table, whether or not it is the one enforced
    yet; and every other field came back `None`, not `-1` and not
    `True`/`False` - this tier apparently has no configured cap at all for
    those fields with the flag off. `requestsPerMinute` and `published`
    converge once self serve tiers are enabled. Every field except
    `requestsPerMinute` and `published` is typed `Optional` to match; treat
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
    #: This tier's number in the OpenAPI rate-limit table, whether or not it
    #: is the one `requestsPerMinute` currently enforces. Added 2026-09-19.
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
    #: Live-verified 2026-09-19, undocumented until now: whether this
    #: account is on the API self-serve tiers flag.
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
    #: A string, e.g. `"98.5"` - the server formats it with `toFixed(1)`.
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
