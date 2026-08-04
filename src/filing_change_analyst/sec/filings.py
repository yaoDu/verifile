"""Filing discovery and comparable-pair selection."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

from ..models import ComparisonBasis, Filing, FilingPair
from .client import TTL_INDEX, SecClient, SecError

log = logging.getLogger(__name__)

SUPPORTED_FORMS = ("10-K", "10-Q")

# A 10-K/A amends a 10-K. We surface amendments but never silently prefer them,
# because an amendment often restates only part of the original document.
_AMENDMENT_SUFFIX = "/A"

# Older submission shards are immutable once published, but they are indexes
# rather than archives, so they get the same TTL as the recent index.
TTL_OLDER_SHARD = TTL_INDEX


def _parse_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def list_filings(
    client: SecClient,
    ticker: str,
    form: str = "10-K",
    *,
    include_amendments: bool = True,
    limit: int = 12,
    refresh: bool = False,
) -> list[Filing]:
    """Return the most recent filings of ``form`` for ``ticker``, newest first."""
    form = form.upper()
    if form not in SUPPORTED_FORMS:
        raise SecError(f"Form '{form}' is not supported by this prototype (10-K / 10-Q only).")

    cik, company_name = client.resolve_ticker(ticker)
    subs = client.submissions(cik, refresh=refresh)
    filings_block: dict[str, Any] = subs.get("filings", {})
    recent: dict[str, Any] = filings_block.get("recent", {})
    if not recent.get("form"):
        raise SecError(
            f"SEC returned no filings at all for {ticker.upper()} (CIK {cik}, "
            f"'{subs.get('name', company_name)}'). This registrant has no filing history."
        )

    fye = str(subs.get("fiscalYearEnd") or "")
    tickers = subs.get("tickers") or [ticker.upper()]
    resolved_ticker = ticker.upper() if ticker.upper() in tickers else str(tickers[0])
    company = str(subs.get("name") or company_name)

    def collect(block: dict[str, Any], into: list[Filing]) -> None:
        forms = block.get("form") or []
        for i in range(len(forms)):
            f = str(forms[i])
            base = f[: -len(_AMENDMENT_SUFFIX)] if f.endswith(_AMENDMENT_SUFFIX) else f
            if base != form:
                continue
            if f.endswith(_AMENDMENT_SUFFIX) and not include_amendments:
                continue
            filing_date = _parse_date(str(block["filingDate"][i]))
            report_date = _parse_date(str(block["reportDate"][i])) or filing_date
            if filing_date is None or report_date is None:
                continue
            docs = block.get("primaryDocument") or []
            into.append(
                Filing(
                    cik=cik,
                    ticker=resolved_ticker,
                    company_name=company,
                    form=f,
                    accession=str(block["accessionNumber"][i]),
                    filing_date=filing_date,
                    report_date=report_date,
                    primary_document=str(docs[i] if i < len(docs) else "") or "",
                    fiscal_year_end=fye,
                    is_amendment=f.endswith(_AMENDMENT_SUFFIX),
                )
            )
            if len(into) >= limit:
                return

    out: list[Filing] = []
    collect(recent, out)

    # High-volume filers overflow the `recent` block. JPMorgan files ~25,000
    # documents, so `recent` spans only a few weeks and contains a single 10-K —
    # the rest live in the older paginated shards listed under `filings.files`.
    # Without this fallback the tool refuses mega-cap banks outright.
    if len(out) < 2:
        shards = filings_block.get("files") or []
        for shard in shards:
            name = str(shard.get("name") or "")
            if not name:
                continue
            try:
                older = client.fetch_json(
                    f"https://data.sec.gov/submissions/{name}", ttl=TTL_OLDER_SHARD
                )
            except SecError as exc:  # a missing shard must not fail the whole lookup
                log.warning("Could not load older submissions shard %s: %s", name, exc)
                continue
            collect(older, out)
            if len(out) >= max(2, min(limit, 4)):
                break

    # Dedupe on accession in case a shard overlaps `recent`.
    seen: set[str] = set()
    unique = [f for f in out if not (f.accession in seen or seen.add(f.accession))]
    unique.sort(key=lambda x: (x.report_date, x.filing_date), reverse=True)
    return unique


def _months_between(a: date, b: date) -> int:
    return abs((a.year - b.year) * 12 + (a.month - b.month))


# The gap, in months, that makes two filings of a given form like-for-like, per
# comparison basis. `check_comparability` enforces this and `select_filing_pair`
# searches by it, so the rule that refuses a pair and the rule that chooses one
# cannot drift apart — which is exactly how the 10-Q default came to refuse
# itself on every run.
COMPARABLE_GAP_MONTHS: dict[str, dict[str, tuple[int, int]]] = {
    "10-K": {
        "year_over_year": (10, 14),  # allow for 52/53-week calendars and fiscal drift
    },
    "10-Q": {
        "year_over_year": (12, 12),  # the same quarter a year earlier
        "sequential": (2, 4),  # the immediately preceding quarter
    },
}


def _gap_window(form: str, basis: ComparisonBasis = "year_over_year") -> tuple[int, int] | None:
    return COMPARABLE_GAP_MONTHS.get(form.replace(_AMENDMENT_SUFFIX, ""), {}).get(basis)


def supported_bases(form: str) -> tuple[ComparisonBasis, ...]:
    """Which comparison bases this form offers. A 10-K only has one."""
    windows = COMPARABLE_GAP_MONTHS.get(form.replace(_AMENDMENT_SUFFIX, ""), {})
    return tuple(b for b in ("year_over_year", "sequential") if b in windows)  # type: ignore[misc]


# Attached to every sequential comparison. A quarter-on-quarter move in a
# seasonal business is not evidence of a trend, and the figures cannot show that
# on their own.
SEQUENTIAL_SEASONALITY_NOTE = (
    "Sequential comparison: this is the immediately preceding quarter, not the same quarter a "
    "year earlier. Seasonality is not held constant, so a move here may reflect the time of "
    "year rather than a change in the business. Use the year-over-year basis to control for it."
)


def check_comparability(
    earlier: Filing, later: Filing, basis: ComparisonBasis = "year_over_year"
) -> tuple[bool, list[str]]:
    """Structural checks before any numbers are computed.

    ``basis`` says which comparison the pair is *meant* to be, because the same
    two dates can be valid or nonsense depending on the question being asked:
    three months apart is correct for a sequential comparison and wrong for a
    year-over-year one.

    Returns ``(ok, notes)``. ``ok=False`` means the pair should be refused or
    displayed with a blocking warning — not quietly compared.
    """
    notes: list[str] = []
    ok = True

    base_e = earlier.form.replace(_AMENDMENT_SUFFIX, "")
    base_l = later.form.replace(_AMENDMENT_SUFFIX, "")
    if base_e != base_l:
        ok = False
        notes.append(
            f"Form mismatch: comparing {earlier.form} with {later.form}. "
            "Annual and quarterly filings cover different durations and are not comparable."
        )

    if later.report_date <= earlier.report_date:
        ok = False
        notes.append(
            f"Period ordering problem: the 'later' filing period ends {later.report_date} "
            f"which is not after the 'earlier' filing period end {earlier.report_date}."
        )

    gap_months = _months_between(earlier.report_date, later.report_date)
    window = _gap_window(base_l, basis)
    gap_ok = bool(window) and window[0] <= gap_months <= window[1]
    if window and not gap_ok:
        ok = False
        if base_l == "10-K":
            notes.append(
                f"Annual periods are {gap_months} months apart (expected ~12). "
                "This is not a like-for-like year-over-year comparison."
            )
        elif basis == "sequential":
            notes.append(
                f"Quarterly periods are {gap_months} months apart, which is not the immediately "
                "preceding quarter (expected ~3). Pick adjacent quarters, or switch to the "
                "year-over-year basis."
            )
        else:
            notes.append(
                f"Quarterly periods are {gap_months} months apart. A year-over-year comparison "
                "needs the same quarter of the prior year (12 months apart). To compare with the "
                "immediately preceding quarter, switch to the sequential basis."
            )

    if basis == "sequential" and gap_ok:
        notes.append(SEQUENTIAL_SEASONALITY_NOTE)

    # A calendar shift shows up as periods that are *nearly* a year apart but end
    # in different months, so the note fires within a couple of months of the
    # year-over-year window. Outside that the pair is simply the wrong one, and
    # the gap note above already says so — telling a filer with an entirely
    # normal calendar to "check for a fiscal-calendar change" only misdirects.
    if basis == "year_over_year" and earlier.report_date.month != later.report_date.month:
        yoy = _gap_window(base_l, "year_over_year")
        plausible_shift = yoy is not None and yoy[0] - 2 <= gap_months <= yoy[1] + 2
        if plausible_shift:
            notes.append(
                f"Fiscal period ends fall in different months ({earlier.report_date:%b} vs "
                f"{later.report_date:%b}); check for a fiscal-calendar change."
            )

    if earlier.is_amendment or later.is_amendment:
        notes.append(
            "One or both filings is an amendment (form ends in /A). Amendments may restate "
            "only part of the original filing; verify figures against the original document."
        )

    return ok, notes


def select_filing_pair(
    client: SecClient,
    ticker: str,
    form: str = "10-K",
    *,
    refresh: bool = False,
    basis: ComparisonBasis = "year_over_year",
) -> FilingPair:
    """Default selection: the latest filing of ``form`` and the most recent
    filing that is actually *comparable* with it on ``basis``.

    The second half of that sentence used to be aspirational. This took the two
    newest filings and then checked them, which is right for a 10-K — the one
    before last is a year back — but wrong for a year-over-year 10-Q, where the
    two newest are always consecutive quarters three months apart. Every default
    10-Q run refused itself, and the form was usable only through the manual
    pair picker.

    The search walks back to the first filing inside the window for the requested
    basis — four filings back for a year-over-year quarterly comparison, one for
    a sequential one. When nothing in the history fits, it falls back to the
    second-newest so the caller still gets the honest refusal with its reasons
    rather than an exception.
    """
    filings = list_filings(client, ticker, form, refresh=refresh)
    if len(filings) < 2:
        detail = ""
        if filings:
            f = filings[0]
            detail = (
                f" The only one found is {f.form} for the period ending {f.report_date} "
                f"(accession {f.accession})."
            )
        else:
            detail = (
                " This can happen when a ticker has just been reassigned to a newly registered "
                "entity after a reorganisation — the SEC ticker index points at the new "
                "registrant, which has no filing history yet."
            )
        raise SecError(
            f"Found {len(filings)} {form} filing(s) for {ticker.upper()}; at least 2 are needed "
            f"for a period-over-period comparison.{detail}"
        )

    # Prefer originals over amendments when both cover the same report date.
    by_period: dict[date, Filing] = {}
    for f in filings:
        existing = by_period.get(f.report_date)
        if existing is None or (existing.is_amendment and not f.is_amendment):
            by_period[f.report_date] = f
    ordered = sorted(by_period.values(), key=lambda x: x.report_date, reverse=True)

    later = ordered[0]
    earlier = ordered[1]
    window = _gap_window(later.form, basis)
    if window:
        low, high = window
        for candidate in ordered[1:]:
            if low <= _months_between(candidate.report_date, later.report_date) <= high:
                earlier = candidate
                break

    return build_pair(earlier, later, basis)


def comparable_earlier_filing(
    later: Filing, options: Sequence[Filing], basis: ComparisonBasis = "year_over_year"
) -> Filing | None:
    """The most recent of ``options`` that is comparable with ``later``.

    Shared with the manual pair picker so its pre-selection cannot offer a pair
    the guardrail then refuses. The picker used to default to the next filing in
    the list, which for a year-over-year 10-Q is always the previous quarter —
    the same self-refusing default that was fixed for the automatic path.
    """
    window = _gap_window(later.form, basis)
    if not window:
        return None
    low, high = window
    for candidate in sorted(options, key=lambda f: f.report_date, reverse=True):
        if candidate.report_date >= later.report_date:
            continue
        if low <= _months_between(candidate.report_date, later.report_date) <= high:
            return candidate
    return None


def build_pair(
    earlier: Filing, later: Filing, basis: ComparisonBasis = "year_over_year"
) -> FilingPair:
    ok, notes = check_comparability(earlier, later, basis)
    return FilingPair(
        earlier=earlier, later=later, basis=basis, comparability_ok=ok, comparability_notes=notes
    )
