"""Filing discovery and comparable-pair selection."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from ..models import Filing, FilingPair
from .client import SecClient, SecError

log = logging.getLogger(__name__)

SUPPORTED_FORMS = ("10-K", "10-Q")

# A 10-K/A amends a 10-K. We surface amendments but never silently prefer them,
# because an amendment often restates only part of the original document.
_AMENDMENT_SUFFIX = "/A"


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
    recent: dict[str, Any] = subs.get("filings", {}).get("recent", {})
    if not recent.get("form"):
        raise SecError(f"SEC returned no recent filings for {ticker}.")

    fye = str(subs.get("fiscalYearEnd") or "")
    tickers = subs.get("tickers") or [ticker.upper()]
    resolved_ticker = ticker.upper() if ticker.upper() in tickers else str(tickers[0])

    out: list[Filing] = []
    n = len(recent["form"])
    for i in range(n):
        f = str(recent["form"][i])
        base = f[: -len(_AMENDMENT_SUFFIX)] if f.endswith(_AMENDMENT_SUFFIX) else f
        if base != form:
            continue
        if f.endswith(_AMENDMENT_SUFFIX) and not include_amendments:
            continue
        filing_date = _parse_date(str(recent["filingDate"][i]))
        report_date = _parse_date(str(recent["reportDate"][i])) or filing_date
        if filing_date is None or report_date is None:
            continue
        out.append(
            Filing(
                cik=cik,
                ticker=resolved_ticker,
                company_name=str(subs.get("name") or company_name),
                form=f,
                accession=str(recent["accessionNumber"][i]),
                filing_date=filing_date,
                report_date=report_date,
                primary_document=str(recent.get("primaryDocument", [""] * n)[i] or ""),
                fiscal_year_end=fye,
                is_amendment=f.endswith(_AMENDMENT_SUFFIX),
            )
        )
        if len(out) >= limit:
            break

    out.sort(key=lambda x: (x.report_date, x.filing_date), reverse=True)
    return out


def _months_between(a: date, b: date) -> int:
    return abs((a.year - b.year) * 12 + (a.month - b.month))


def check_comparability(earlier: Filing, later: Filing) -> tuple[bool, list[str]]:
    """Structural checks before any numbers are computed.

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
    if base_l == "10-K":
        if not (10 <= gap_months <= 14):
            ok = False
            notes.append(
                f"Annual periods are {gap_months} months apart (expected ~12). "
                "This is not a like-for-like year-over-year comparison."
            )
    elif base_l == "10-Q" and gap_months != 12:
        # A 10-Q is only comparable with the same quarter of the prior year.
        ok = False
        notes.append(
            f"Quarterly periods are {gap_months} months apart. This prototype only compares a "
            "quarter with the same quarter of the prior year (12 months apart)."
        )
    if earlier.report_date.month != later.report_date.month:
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
) -> FilingPair:
    """Default selection: the two most recent comparable filings of ``form``."""
    filings = list_filings(client, ticker, form, refresh=refresh)
    if len(filings) < 2:
        raise SecError(
            f"Found {len(filings)} {form} filing(s) for {ticker.upper()}; at least 2 are needed "
            "for a period-over-period comparison."
        )

    # Prefer originals over amendments when both cover the same report date.
    by_period: dict[date, Filing] = {}
    for f in filings:
        existing = by_period.get(f.report_date)
        if existing is None or (existing.is_amendment and not f.is_amendment):
            by_period[f.report_date] = f
    ordered = sorted(by_period.values(), key=lambda x: x.report_date, reverse=True)

    later, earlier = ordered[0], ordered[1]
    ok, notes = check_comparability(earlier, later)
    return FilingPair(earlier=earlier, later=later, comparability_ok=ok, comparability_notes=notes)


def build_pair(earlier: Filing, later: Filing) -> FilingPair:
    ok, notes = check_comparability(earlier, later)
    return FilingPair(earlier=earlier, later=later, comparability_ok=ok, comparability_notes=notes)
