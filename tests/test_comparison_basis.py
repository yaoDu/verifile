"""Which two filings get paired, and what the guardrail says about it.

A 10-Q supports two comparisons that answer different questions. Year over year
holds seasonality constant; sequential shows the immediately preceding quarter
and does not. The same two dates are correct for one and nonsense for the other,
so the intent has to be recorded on the pair rather than inferred from the gap.

The defects pinned here: the manual pair picker pre-selected a pair the guardrail
always refused (the same self-refusing default that was fixed for the automatic
path but missed here); comparability notes were copied into `warnings` as well as
the pair, so every surface printed each one twice; and a mis-picked pair was told
to "check for a fiscal-calendar change" when its calendar was entirely normal.
"""

from __future__ import annotations

from datetime import date

import pytest

from filing_change_analyst.analytics.period_matching import periods_compatible
from filing_change_analyst.models import Filing, XbrlFact
from filing_change_analyst.sec.filings import (
    check_comparability,
    comparable_earlier_filing,
    supported_bases,
)

QUARTER_ENDS = ("2026-03-31", "2025-12-31", "2025-09-30", "2025-03-31", "2024-12-31")


def _filing(end: str, form: str = "10-Q") -> Filing:
    d = date.fromisoformat(end)
    return Filing(
        cik="0000789019",
        ticker="MSFT",
        company_name="MICROSOFT CORP",
        form=form,
        accession=f"0000000000-00-{d.strftime('%m%d%y')[:6]}",
        filing_date=d,
        report_date=d,
        primary_document="msft.htm",
        fiscal_year_end="0630",
    )


@pytest.fixture()
def quarters() -> list[Filing]:
    return [_filing(e) for e in QUARTER_ENDS]


# --------------------------------------------------------------------------- #
# The guardrail
# --------------------------------------------------------------------------- #


def test_consecutive_quarters_are_refused_year_over_year():
    ok, notes = check_comparability(_filing("2025-12-31"), _filing("2026-03-31"))
    assert not ok
    assert any("3 months apart" in n for n in notes)


def test_consecutive_quarters_are_accepted_sequentially():
    """The exact pair that used to be unusable: Dec 2025 → Mar 2026."""
    ok, notes = check_comparability(
        _filing("2025-12-31"), _filing("2026-03-31"), "sequential"
    )
    assert ok
    assert any("Seasonality is not held constant" in n for n in notes)


def test_a_refusal_says_which_basis_would_work():
    _, notes = check_comparability(_filing("2025-12-31"), _filing("2026-03-31"))
    assert any("switch to the sequential basis" in n for n in notes)

    _, seq_notes = check_comparability(
        _filing("2025-03-31"), _filing("2026-03-31"), "sequential"
    )
    assert any("year-over-year basis" in n for n in seq_notes)


def test_year_apart_quarters_are_refused_sequentially():
    """Sequential means adjacent. A year back is the wrong pair for it."""
    ok, notes = check_comparability(
        _filing("2025-03-31"), _filing("2026-03-31"), "sequential"
    )
    assert not ok
    assert any("not the immediately preceding quarter" in n for n in notes)


def test_sequential_pairs_always_carry_the_seasonality_caveat():
    _, notes = check_comparability(
        _filing("2025-12-31"), _filing("2026-03-31"), "sequential"
    )
    seasonality = [n for n in notes if "Seasonality" in n]
    assert len(seasonality) == 1
    assert "may reflect the time of year" in seasonality[0]


def test_year_over_year_pairs_carry_no_seasonality_caveat():
    _, notes = check_comparability(_filing("2025-03-31"), _filing("2026-03-31"))
    assert not any("Seasonality" in n for n in notes)


def test_no_fiscal_calendar_warning_on_a_sequential_pair():
    """Consecutive quarters end in different months by definition."""
    _, notes = check_comparability(
        _filing("2025-12-31"), _filing("2026-03-31"), "sequential"
    )
    assert not any("fiscal-calendar change" in n for n in notes)


def test_no_fiscal_calendar_warning_when_the_gap_is_already_wrong():
    """The gap note explains it; adding a calendar warning misdirects the reader."""
    _, notes = check_comparability(_filing("2025-12-31"), _filing("2026-03-31"))
    assert not any("fiscal-calendar change" in n for n in notes)


@pytest.mark.parametrize("earlier_end", ["2025-02-28", "2025-04-30"])
def test_a_genuine_fiscal_calendar_shift_is_still_flagged(earlier_end):
    """Nearly a year apart but ending in a different month is the real signal —
    the filer moved their quarter end. A wrong pair is months out, not one."""
    _, notes = check_comparability(_filing(earlier_end), _filing("2026-03-31"))
    assert any("fiscal-calendar change" in n for n in notes)


# --------------------------------------------------------------------------- #
# The manual pair picker's default
# --------------------------------------------------------------------------- #


def test_picker_default_is_a_pair_the_guardrail_accepts(quarters):
    """It used to offer the next filing in the list — always the prior quarter."""
    for basis, expected in (("year_over_year", "2025-03-31"), ("sequential", "2025-12-31")):
        match = comparable_earlier_filing(quarters[0], quarters, basis)
        assert match is not None
        assert match.report_date.isoformat() == expected
        ok, _ = check_comparability(match, quarters[0], basis)
        assert ok


def test_picker_default_never_looks_forward(quarters):
    """The earlier filing must actually be earlier."""
    for basis in ("year_over_year", "sequential"):
        match = comparable_earlier_filing(quarters[-1], quarters, basis)
        assert match is None or match.report_date < quarters[-1].report_date


def test_picker_has_no_default_when_history_is_too_short():
    only = [_filing("2026-03-31"), _filing("2025-12-31")]
    assert comparable_earlier_filing(only[0], only, "year_over_year") is None


def test_10k_offers_one_basis_and_10q_offers_two():
    assert supported_bases("10-K") == ("year_over_year",)
    assert supported_bases("10-Q") == ("year_over_year", "sequential")
    assert supported_bases("10-Q/A") == ("year_over_year", "sequential")


def test_a_10k_pair_is_unaffected_by_the_basis_argument():
    earlier, later = _filing("2025-06-30", "10-K"), _filing("2026-06-30", "10-K")
    assert check_comparability(earlier, later) == check_comparability(
        earlier, later, "year_over_year"
    )


# --------------------------------------------------------------------------- #
# Fact-level alignment
#
# The structural check above passes the *pair*; this one passes each *fact*.
# Both have to know the basis: a Dec-to-Mar quarterly pair is ~275 days from
# being a year apart, so measuring year-over-year alignment on it blocked all 21
# metrics on a pair the structural check had just accepted.
# --------------------------------------------------------------------------- #


def _fact(end: str, start: str | None = None) -> XbrlFact:
    return XbrlFact(
        concept="Revenue",
        unit="USD",
        value=1.0,
        start=date.fromisoformat(start) if start else None,
        end=date.fromisoformat(end),
    )


def test_consecutive_quarters_align_sequentially():
    ok, note = periods_compatible(
        _fact("2025-12-31", "2025-10-01"),
        _fact("2026-03-31", "2026-01-01"),
        basis="sequential",
    )
    assert ok, note
    assert "one period apart" in note


def test_consecutive_quarters_do_not_align_year_over_year():
    ok, note = periods_compatible(
        _fact("2025-12-31", "2025-10-01"), _fact("2026-03-31", "2026-01-01")
    )
    assert not ok
    assert "exactly 1 year(s) apart" in note


def test_quarters_a_year_apart_do_not_align_sequentially():
    ok, note = periods_compatible(
        _fact("2025-03-31", "2025-01-01"),
        _fact("2026-03-31", "2026-01-01"),
        basis="sequential",
    )
    assert not ok
    assert "not consecutive periods" in note


def test_balance_sheet_facts_align_sequentially_from_the_period_class():
    """An instant states a date but no duration; without the class every
    instant metric — cash, debt, equity — dropped out of a sequential run."""
    ok, note = periods_compatible(
        _fact("2025-12-31"), _fact("2026-03-31"), basis="sequential", period_class="quarterly"
    )
    assert ok, note


def test_a_balance_sheet_gap_of_the_wrong_size_is_still_refused():
    ok, _ = periods_compatible(
        _fact("2025-03-31"), _fact("2026-03-31"), basis="sequential", period_class="quarterly"
    )
    assert not ok


def test_sequential_alignment_is_unverifiable_without_a_length():
    ok, note = periods_compatible(_fact("2025-12-31"), _fact("2026-03-31"), basis="sequential")
    assert not ok
    assert "not stated" in note


# --------------------------------------------------------------------------- #
# Sequential year-to-date is not a comparison that exists
# --------------------------------------------------------------------------- #


def test_sequential_year_to_date_is_refused_with_a_reason(fact_store, pair):
    """It finds no facts rather than failing, so it has to say so outright."""
    from filing_change_analyst.analytics.comparisons import compare_filings

    sequential = pair.model_copy(update={"basis": "sequential"})
    _, _, warnings = compare_filings(
        fact_store, sequential, duration_class="three_quarters"
    )
    assert any("cannot be read on a year-to-date basis" in w for w in warnings)


def test_sequential_quarterly_carries_no_such_warning(fact_store, pair):
    from filing_change_analyst.analytics.comparisons import compare_filings

    sequential = pair.model_copy(update={"basis": "sequential"})
    _, _, warnings = compare_filings(fact_store, sequential, duration_class="quarterly")
    assert not any("year-to-date basis" in w for w in warnings)
