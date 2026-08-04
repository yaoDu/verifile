"""Duration-aware fact selection.

A 10-Q tags the quarter *and* the year-to-date figure against the same period
end. Selecting on the end date alone makes those look like conflicting values
for one period, so the pick between them is arbitrary and every metric carries a
spurious warning. These tests pin the distinction.
"""

from __future__ import annotations

from datetime import date

import pytest

from filing_change_analyst.analytics.comparisons import build_metric_set
from filing_change_analyst.analytics.period_matching import default_duration_class
from filing_change_analyst.models import Filing
from filing_change_analyst.sec.facts import FactStore

CONCEPT = "RevenueFromContractWithCustomerExcludingAssessedTax"
ACCN = "0001193125-26-191507"


def _entry(start: str, end: str, val: float, *, accn: str = ACCN, filed: str = "2026-04-29") -> dict:
    return {
        "start": start,
        "end": end,
        "val": val,
        "accn": accn,
        "form": "10-Q",
        "fy": 2026,
        "fp": "Q3",
        "filed": filed,
        "frame": None,
    }


def _store(entries: list[dict], concept: str = CONCEPT) -> FactStore:
    return FactStore(
        {
            "cik": 789019,
            "entityName": "MICROSOFT CORPORATION",
            "facts": {"us-gaap": {concept: {"label": "Revenue", "units": {"USD": entries}}}},
        }
    )


def _filing(form: str = "10-Q", end: str = "2026-03-31") -> Filing:
    return Filing(
        cik="0000789019",
        ticker="MSFT",
        company_name="MICROSOFT CORP",
        form=form,
        accession=ACCN,
        filing_date=date(2026, 4, 29),
        report_date=date.fromisoformat(end),
        primary_document="msft-20260331.htm",
        fiscal_year_end="0630",
    )


# The real shape of a 10-Q: quarter and year-to-date, same end, same filing.
QUARTER = _entry("2026-01-01", "2026-03-31", 82_886_000_000)
YTD = _entry("2025-07-01", "2026-03-31", 241_832_000_000)


@pytest.mark.parametrize(
    ("duration_class", "expected_value", "expected_start"),
    [
        ("quarterly", 82_886_000_000, date(2026, 1, 1)),
        ("three_quarters", 241_832_000_000, date(2025, 7, 1)),
    ],
)
def test_duration_class_picks_the_right_period(duration_class, expected_value, expected_start):
    store = _store([YTD, QUARTER])
    fact, rule, warnings = store.select(
        CONCEPT, _filing(), period_end=date(2026, 3, 31), duration_class=duration_class
    )
    assert fact is not None
    assert fact.value == expected_value
    assert fact.start == expected_start
    assert rule == "filing_scoped_exact_period"
    assert warnings == []


def test_quarter_and_ytd_are_not_reported_as_a_conflict():
    """The bug: two durations sharing an end date warned as 'conflicting values'."""
    store = _store([YTD, QUARTER])
    _, _, warnings = store.select(
        CONCEPT, _filing(), period_end=date(2026, 3, 31), duration_class="quarterly"
    )
    assert not any("conflicting" in w for w in warnings)


def test_selection_is_independent_of_parse_order():
    """Without duration filtering the pick fell out of dict ordering."""
    picks = {
        tuple(
            _store(entries)
            .select(CONCEPT, _filing(), period_end=date(2026, 3, 31), duration_class="quarterly")[0]
            .value
            for entries in ([YTD, QUARTER], [QUARTER, YTD])
        )
    }
    assert picks == {(82_886_000_000, 82_886_000_000)}


def test_10q_metric_set_defaults_to_the_quarter_without_warnings():
    store = _store([YTD, QUARTER])
    values, _, warnings = build_metric_set(store, _filing())
    revenue = values["revenue"]
    assert revenue.value == 82_886_000_000
    assert revenue.duration_class == "quarterly"
    assert warnings == []


def test_ytd_basis_is_available_on_request():
    store = _store([YTD, QUARTER])
    values, _, warnings = build_metric_set(store, _filing(), duration_class="three_quarters")
    assert values["revenue"].value == 241_832_000_000
    assert values["revenue"].duration_class == "three_quarters"
    assert warnings == []


def test_missing_duration_omits_the_metric_rather_than_substituting():
    """A quarter must never be silently filled in with a year-to-date figure."""
    store = _store([YTD])
    fact, _, warnings = store.select(
        CONCEPT, _filing(), period_end=date(2026, 3, 31), duration_class="quarterly"
    )
    assert fact is None
    assert any("no quarterly fact" in w and "three_quarters" in w for w in warnings)


def test_cross_filing_fallback_still_takes_the_original_report():
    """Rule 3 is unchanged: no fact in this filing, so use the earliest filed."""
    store = _store(
        [
            _entry("2026-01-01", "2026-03-31", 82_000_000_000, accn="a", filed="2026-04-29"),
            _entry("2026-01-01", "2026-03-31", 82_886_000_000, accn="b", filed="2026-07-30"),
        ]
    )
    fact, rule, warnings = store.select(
        CONCEPT, _filing(), period_end=date(2026, 3, 31), duration_class="quarterly"
    )
    assert fact is not None
    assert fact.value == 82_000_000_000  # as first reported
    assert rule == "cross_filing_original_report"
    assert any("first reported" in w for w in warnings)


def test_duration_filter_applies_to_the_cross_filing_fallback_too():
    """The fallback must not reach past the requested duration either."""
    store = _store([_entry("2025-07-01", "2026-03-31", 241_832_000_000, accn="other")])
    fact, _, warnings = store.select(
        CONCEPT, _filing(), period_end=date(2026, 3, 31), duration_class="quarterly"
    )
    assert fact is None
    assert any("no quarterly fact" in w for w in warnings)


def test_same_day_conflict_does_not_claim_a_newer_value_exists():
    """Two values filed the same day: 'used the most recently filed' was untrue."""
    store = _store(
        [
            _entry("2026-01-01", "2026-03-31", 82_000_000_000),
            _entry("2026-01-01", "2026-03-31", 82_886_000_000),
        ]
    )
    _, _, warnings = store.select(
        CONCEPT, _filing(), period_end=date(2026, 3, 31), duration_class="quarterly"
    )
    conflict = next(w for w in warnings if "conflicting" in w)
    assert "no newer value to prefer" in conflict
    assert "most recently filed" not in conflict
    assert "quarterly" in conflict  # names the duration the conflict is within


@pytest.mark.parametrize(
    ("form", "expected"),
    [
        ("10-K", "annual"),
        ("10-Q", "quarterly"),
        ("20-F", "annual"),
        ("10-k", "annual"),  # case-insensitive
        ("8-K", None),  # no opinion: do not filter
        (None, None),
    ],
)
def test_default_duration_class(form, expected):
    assert default_duration_class(form) == expected


def test_10k_is_unaffected():
    """Annual filings were never ambiguous; the default must not change them."""
    annual = _entry("2025-07-01", "2026-06-30", 320_000_000_000)
    store = _store([annual])
    values, _, warnings = build_metric_set(store, _filing(form="10-K", end="2026-06-30"))
    assert values["revenue"].value == 320_000_000_000
    assert values["revenue"].duration_class == "annual"
    assert warnings == []
