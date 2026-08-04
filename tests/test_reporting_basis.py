"""Naming the reporting basis the displayed figures actually use.

A 10-Q reports the quarter and the year-to-date figure against the same period
end, and its MD&A narrates both. The grid shows one of them. Measured on MSFT
Q3 FY2026: cost of revenue is +22.4% on the quarter, while the MD&A paragraph
retrieved beside it says "increased $13.0 billion or 20%" — the nine-month
figure. Both are the filing's own numbers, so the basis has to be stated rather
than left for the reader to infer.
"""

from __future__ import annotations

import pytest

from filing_change_analyst.analytics.period_matching import BASIS_LABELS, reported_basis
from filing_change_analyst.models import MetricComparison, MetricValue
from filing_change_analyst.research.change_detection import detect_material_changes


def _value(duration_class: str, *, period_type: str = "duration", value: float = 1.0) -> MetricValue:
    return MetricValue(
        metric_id="revenue",
        value=value,
        unit="USD",
        period_type=period_type,
        duration_class=duration_class,
    )


def _comparison(duration_class: str, *, period_type: str = "duration") -> MetricComparison:
    return MetricComparison(
        metric_id="revenue",
        label="Revenue",
        kind="currency",
        earlier=_value(duration_class, period_type=period_type),
        later=_value(duration_class, period_type=period_type, value=2.0),
        percent_change=100.0,
        status="ok",
    )


@pytest.mark.parametrize(
    "duration_class", ["quarterly", "three_quarters", "half_year", "annual"]
)
def test_basis_is_read_back_off_the_selected_facts(duration_class):
    assert reported_basis([_comparison(duration_class)]) == duration_class


def test_mixed_bases_report_nothing_rather_than_guessing():
    mixed = [_comparison("quarterly"), _comparison("three_quarters")]
    assert reported_basis(mixed) is None


def test_instant_metrics_do_not_decide_the_basis():
    """A balance-sheet item has no duration; it must not dilute the answer."""
    comparisons = [_comparison("quarterly"), _comparison("instant", period_type="instant")]
    assert reported_basis(comparisons) == "quarterly"


def test_empty_comparison_has_no_basis():
    assert reported_basis([]) is None


def test_every_basis_has_a_label():
    for duration_class in ("annual", "three_quarters", "half_year", "quarterly"):
        assert BASIS_LABELS[duration_class]


# --------------------------------------------------------------------------- #
# The caveat carried on a change
#
# The fixtures are a 10-K pair, so the comparison is re-based onto a sub-annual
# reporting length rather than re-derived: the topic-to-metric linkage stays
# real and only the basis under test changes.
# --------------------------------------------------------------------------- #


@pytest.fixture()
def annual_changes(earlier_html, later_html, fy2024, fy2025, fact_store, pair):
    from filing_change_analyst.analytics.comparisons import compare_filings
    from filing_change_analyst.retrieval.chunking import chunk_filing
    from filing_change_analyst.retrieval.index import Bm25Index
    from filing_change_analyst.retrieval.search import probe_all_topics
    from filing_change_analyst.sec.sections import extract_sections

    chunks = []
    for html, filing, period in ((earlier_html, fy2024, "earlier"), (later_html, fy2025, "later")):
        sections, _, _ = extract_sections(html, filing.form)
        chunks.extend(chunk_filing(sections, filing, period))
    topics = probe_all_topics(Bm25Index(chunks))
    comparisons, _, _ = compare_filings(fact_store, pair)
    return topics, comparisons


def _rebased(comparisons, duration_class: str):
    out = []
    for c in comparisons:
        copy = c.model_copy(deep=True)
        for side in (copy.earlier, copy.later):
            if side.period_type == "duration":
                side.duration_class = duration_class
        out.append(copy)
    return out


def test_sub_annual_changes_warn_that_the_excerpt_may_be_on_the_other_basis(annual_changes):
    topics, comparisons = annual_changes
    changes = detect_material_changes(topics, _rebased(comparisons, "quarterly"))
    quoting = [c for c in changes if c.related_metric_ids]
    assert quoting, "expected at least one change that pairs figures with excerpts"
    for c in quoting:
        assert "the quarter alone" in c.caveat
        assert "may be on the other basis" in c.caveat


def test_year_to_date_basis_is_named_as_such(annual_changes):
    topics, comparisons = annual_changes
    changes = detect_material_changes(topics, _rebased(comparisons, "three_quarters"))
    quoting = [c for c in changes if c.related_metric_ids]
    assert quoting
    assert all("the nine months to date" in c.caveat for c in quoting)


def test_annual_changes_carry_no_basis_caveat(annual_changes):
    topics, comparisons = annual_changes
    changes = detect_material_changes(topics, comparisons)
    assert changes
    for c in changes:
        assert "other basis" not in c.caveat


def test_a_language_only_change_does_not_claim_a_basis(annual_changes):
    """The caveat is about figures; a change with no figures must not carry it."""
    topics, comparisons = annual_changes
    changes = detect_material_changes(topics, _rebased(comparisons, "quarterly"))
    for c in changes:
        if not c.related_metric_ids:
            assert "other basis" not in c.caveat
