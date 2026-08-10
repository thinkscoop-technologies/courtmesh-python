"""CourtMesh Enterprise API Python SDK.

Example:
    from courtmesh import CourtMesh

    with CourtMesh(api_key="cm-...") as cm:
        result = cm.search_cases(query="right to privacy")
        for hit in result.data:
            print(hit.get("title"))
"""
from .client import CourtMesh, DEFAULT_BASE_URL
from .errors import (
    AuthenticationError,
    BadGatewayError,
    CourtMeshError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    RequestTimeoutError,
    ServerError,
    ServiceUnavailableError,
    ValidationError,
)
from .models import (
    APIResponse,
    AnalysisArguments,
    AnalysisIssue,
    AnalyzeResponse,
    CaseAnalysis,
    CaseAnalysisResponse,
    CaseDetails,
    CaseDetailsMetadata,
    CaseListItem,
    CitedCases,
    ConsolidatedAnalysis,
    ConsolidatedAnalyzeResponse,
    Envelope,
    HealthResponse,
    JudgeSearchMeta,
    Order,
    PdfResponse,
    RelatedDocument,
    RelatedResponse,
    RequestTimelineResponse,
    SearchCasesFilters,
    SearchCasesMeta,
    SearchCasesPagination,
    SearchCasesResult,
    SemanticSearchMeta,
    SemanticSearchPagination,
    SemanticSearchResult,
    SemanticSearchResultItem,
    TimelineEvent,
    TimelineJob,
)

__version__ = "0.1.0"

__all__ = [
    "CourtMesh",
    "DEFAULT_BASE_URL",
    "__version__",
    # errors
    "CourtMeshError",
    "ValidationError",
    "AuthenticationError",
    "PermissionDeniedError",
    "NotFoundError",
    "RequestTimeoutError",
    "RateLimitError",
    "ServerError",
    "BadGatewayError",
    "ServiceUnavailableError",
    # models
    "APIResponse",
    "Envelope",
    "SearchCasesPagination",
    "SemanticSearchPagination",
    "SearchCasesResult",
    "SearchCasesMeta",
    "SearchCasesFilters",
    "SemanticSearchResult",
    "SemanticSearchMeta",
    "SemanticSearchResultItem",
    "CaseListItem",
    "CaseDetails",
    "CaseDetailsMetadata",
    "CaseAnalysis",
    "CaseAnalysisResponse",
    "AnalysisIssue",
    "CitedCases",
    "AnalysisArguments",
    "ConsolidatedAnalysis",
    "ConsolidatedAnalyzeResponse",
    "AnalyzeResponse",
    "RelatedDocument",
    "TimelineEvent",
    "RelatedResponse",
    "PdfResponse",
    "Order",
    "RequestTimelineResponse",
    "TimelineJob",
    "JudgeSearchMeta",
    "HealthResponse",
]
