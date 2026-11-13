"""Types and client side checks for the cause list endpoints.

Every call needs an API key with the ``causelist`` scope (keys without
explicit scopes have full access) and an account with cause lists enabled.
Only listings that were found are ever reported: an empty result, a
``no_entry_found`` status or a missing row is not a statement that a case is
absent from a list.
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

try:
    from typing import TypedDict
except ImportError:  # pragma: no cover
    from typing_extensions import TypedDict  # type: ignore[assignment]

from .errors import ValidationError

# ---------------------------------------------------------------------------
# Shapes. Every nullable string field is Optional[str].
# ---------------------------------------------------------------------------


class CauseListPagination(TypedDict, total=False):
    """Pagination block of `list_cause_listings`. Pages start at 1."""

    page: int
    limit: int
    total: int
    totalPages: int
    hasMore: bool


class CauseListCourt(TypedDict, total=False):
    """The court a list belongs to. `kind` is `SC`, `HC` or `DC`."""

    kind: Optional[str]
    name: Optional[str]
    courtNo: Optional[str]
    judges: List[str]
    designation: Optional[str]


class CauseListing(TypedDict, total=False):
    """One appearance of one of your matters on a cause list.

    `courtKey` is usable as `court_key` in `get_court_cause_list`. `matchedBy`
    is `cnr`, `diary`, `key` or `related_key`; `caseText` is None on a
    `related_key` match or a restricted row. `relation` is set when the item is an
    application or connected case of your matter rather than the matter itself.
    """

    id: str
    matterId: str
    matterTitle: Optional[str]
    date: str
    courtKey: str
    court: Optional[CauseListCourt]
    item: Optional[str]
    section: Optional[str]
    purpose: Optional[str]
    listType: Optional[str]
    stage: Optional[str]
    caseText: Optional[str]
    matchedBy: Optional[str]
    relation: Optional[str]
    fetchedAt: Optional[str]
    firstSeenAt: Optional[str]


class CauseListRelatedItem(TypedDict, total=False):
    relation: Optional[str]
    caseType: Optional[str]
    caseNumber: Optional[str]
    caseYear: Optional[str]
    key: Optional[str]


class CauseListRow(TypedDict, total=False):
    """One item of a court's list. A restricted row carries no party names or advocates."""

    item: Optional[str]
    itemRaw: Optional[str]
    section: Optional[str]
    purpose: Optional[str]
    listType: Optional[str]
    courtNo: Optional[str]
    courtName: Optional[str]
    judges: List[str]
    caseText: Optional[str]
    caseType: Optional[str]
    caseNumber: Optional[str]
    caseYear: Optional[str]
    key: Optional[str]
    cnr: Optional[str]
    diaryNumber: Optional[str]
    diaryYear: Optional[str]
    petitioner: Optional[str]
    respondent: Optional[str]
    advocates: Optional[str]
    stage: Optional[str]
    related: List[CauseListRelatedItem]
    restricted: bool


class CauseListCourtList(TypedDict, total=False):
    """`data` of `get_court_cause_list`.

    `status` is `ok`, `partial`, `empty`, `not_published`, `unavailable`,
    `invalid_court` or `none`. `ok` and `partial` carry rows (`partial` means
    some parts of the list could not be read); the others carry none.
    `complete` is true only when every part of the list was read.
    """

    courtKey: str
    date: str
    status: str
    complete: bool
    fetchedAt: Optional[str]
    court: Optional[CauseListCourt]
    rows: List[CauseListRow]


class MatterCauseListings(TypedDict, total=False):
    """`data` of `list_matter_cause_listings`: `matter` is `{id, title, courtKey}`."""

    matter: Dict[str, Optional[str]]
    listings: List[CauseListing]


class CauseListCheckDate(TypedDict, total=False):
    """What was read for one date of one CNR's court. `status` uses the court list statuses."""

    date: str
    status: str
    complete: bool
    fetchedAt: Optional[str]


class CauseListCheckListing(TypedDict, total=False):
    """A listing found for a watched CNR. It carries no party or advocate fields."""

    date: str
    courtKey: Optional[str]  # None when the court cannot be given
    court: Optional[CauseListCourt]
    item: Optional[str]
    section: Optional[str]
    purpose: Optional[str]
    listType: Optional[str]
    stage: Optional[str]
    caseText: Optional[str]
    matchedBy: Optional[str]
    relation: Optional[str]
    fetchedAt: Optional[str]


class CauseListCheckResult(TypedDict, total=False):
    """One CNR of a `check_cause_lists` call.

    `status` is one of:

    - `listed`: a row of this case was found (1 credit).
    - `no_entry_found`: a list was read and no row was recognised (1 credit).
      This is not proof that the case is not listed; `dates[].complete` says
      how much was read.
    - `list_not_read`: no list was held for the dates (free). For a District
      Court it can also mean the list of the case's own courtroom could not be
      confirmed (`dates[].status` is then `none`).
    - `cannot_check`: `reason` says why (free): `pending`, `record_unavailable`,
      `court_not_supported`, or a court identification reason (`no_case_identity`,
      `no_court_key`, `no_court_number`, `invalid_court_key`, `unsupported_court`). `courtKey`
      can be None.
    - `not_watched`: your account does not watch this CNR (free).
    """

    cnr: str
    status: str
    reason: Optional[str]
    courtKey: Optional[str]
    dates: List[CauseListCheckDate]
    listings: List[CauseListCheckListing]


class CauseListCheckSummary(TypedDict, total=False):
    listed: int
    noEntryFound: int
    listNotRead: int
    cannotCheck: int
    notWatched: int


# `from` is a reserved word, so this uses the functional TypedDict form. `from` and
# `to` are the dates that were looked at (`YYYY-MM-DD`); the default range is
# resolved by the server.
CauseListCheckData = TypedDict(
    "CauseListCheckData",
    {
        "results": List[CauseListCheckResult],
        "summary": CauseListCheckSummary,
        "from": str,
        "to": str,
    },
    total=False,
)
"""`data` of `check_cause_lists`: `results`, `summary`, and the `from` and `to` dates looked at."""


@dataclass
class CauseListPage:
    """One page of `list_cause_listings`."""

    data: List[CauseListing]
    pagination: CauseListPagination
    meta: Dict[str, Any] = field(default_factory=dict)
    #: See `APIResponse.request_id`.
    request_id: Optional[str] = None

    @property
    def has_more(self) -> bool:
        return bool(self.pagination.get("hasMore"))


# ---------------------------------------------------------------------------
# Client side validation. Messages match the server's.
# ---------------------------------------------------------------------------

#: Same pattern as the server.
COURT_KEY_PATTERN = re.compile(r"(SC|HC:\d{1,3}:\d{1,3}|DC:\d{1,3}:\d{1,4}:\d{1,9}:\d{1,4}:\d{1,5})", re.ASCII)
_MATTER_ID_PATTERN = re.compile(r"[0-9a-fA-F]{24}", re.ASCII)
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)

LISTINGS_MAX_DAYS = 31
CHECK_MAX_DAYS = 7
CHECK_MAX_CNRS = 100
#: CNRs times dates in the range, at most. The default range is 2 dates.
CHECK_MAX_CNR_DATES = 300


def _fail(details: Sequence[str]) -> None:
    raise ValidationError(
        "Validation failed. Please check your request and try again. ({})".format("; ".join(details)),
        status_code=400,
        code="VALIDATION_ERROR",
    )


def _parse_date(value: Any) -> Optional[_dt.date]:
    # ASCII digits only, and a real calendar date (2026-02-30 is refused).
    if not isinstance(value, str) or _ISO_DATE.fullmatch(value) is None or not value.isascii():
        return None
    try:
        return _dt.date.fromisoformat(value)
    except ValueError:
        return None


def assert_date_range(from_date: Optional[str], to_date: Optional[str], max_days: int) -> None:
    details: List[str] = []
    start = _parse_date(from_date) if from_date is not None else None
    end = _parse_date(to_date) if to_date is not None else None
    if from_date is not None and start is None:
        details.append("from: from must be a real date written YYYY-MM-DD.")
    if to_date is not None and end is None:
        details.append("to: to must be a real date written YYYY-MM-DD.")
    if not details:
        if (from_date is None) != (to_date is None):
            details.append("Send both from and to, or neither.")
        elif start is not None and end is not None:
            days = (end - start).days
            if days < 0:
                details.append("to cannot be before from.")
            elif days > max_days:
                details.append("from and to can be at most {} days apart.".format(max_days))
    if details:
        _fail(details)


def assert_matter_id(matter_id: Any) -> str:
    if not isinstance(matter_id, str) or _MATTER_ID_PATTERN.fullmatch(matter_id) is None:
        _fail(["matterId: matterId must be a 24 character hexadecimal id."])
    return matter_id


def assert_court_list_query(court_key: Any, date: Any) -> None:
    details: List[str] = []
    if not isinstance(court_key, str) or COURT_KEY_PATTERN.fullmatch(court_key) is None:
        details.append(
            "courtKey: courtKey is not a valid court key. Use SC, HC:<state>:<bench> or "
            "DC:<state>:<district>:<complex>:<establishment>:<court number>."
        )
    if _parse_date(date) is None:
        details.append("date: date must be a real date written YYYY-MM-DD.")
    if details:
        _fail(details)


def assert_check_body(cnrs: Any, from_date: Optional[str], to_date: Optional[str]) -> None:
    if isinstance(cnrs, (str, bytes)) or not isinstance(cnrs, (list, tuple)) or not 1 <= len(cnrs) <= CHECK_MAX_CNRS:
        _fail(["cnrs: send between 1 and {} CNRs.".format(CHECK_MAX_CNRS)])
    assert_date_range(from_date, to_date, CHECK_MAX_DAYS)
    dates = 2
    if from_date is not None and to_date is not None:
        dates = (_parse_date(to_date) - _parse_date(from_date)).days + 1  # type: ignore[operator]
    # Repeats are removed before counting, as the server does.
    from .monitoring import cnr_for_request

    distinct = len({cnr_for_request(cnr) for cnr in cnrs})
    if distinct * dates > CHECK_MAX_CNR_DATES:
        _fail(
            [
                "A call can cover at most {} CNR and date pairs. This one asks for {} CNRs over {} dates; "
                "send fewer CNRs or a shorter date range.".format(CHECK_MAX_CNR_DATES, distinct, dates)
            ]
        )
