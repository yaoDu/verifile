"""Period classification and compatibility — the highest-risk logic in the system."""

from __future__ import annotations

from datetime import date

import pytest

from filing_change_analyst.analytics.period_matching import (
    classify_duration,
    fiscal_alignment_drift_days,
    periods_compatible,
)
from filing_change_analyst.models import XbrlFact
from filing_change_analyst.sec.filings import check_comparability


def fact(start: str | None, end: str, value: float = 1.0, unit: str = "USD") -> XbrlFact:
    return XbrlFact(
        concept="Revenues",
        unit=unit,
        value=value,
        start=date.fromisoformat(start) if start else None,
        end=date.fromisoformat(end),
    )


@pytest.mark.parametrize(
    ("days", "expected"),
    [
        (None, "instant"),
        (365, "annual"),
        (366, "annual"),
        (371, "annual"),  # 53-week year
        (273, "three_quarters"),
        (181, "half_year"),
        (92, "quarterly"),
        (84, "quarterly"),
        (45, "other"),
        (600, "other"),
    ],
)
def test_classify_duration(days, expected):
    assert classify_duration(days) == expected


def test_annual_vs_annual_is_compatible():
    ok, note = periods_compatible(fact("2023-07-01", "2024-06-30"), fact("2024-07-01", "2025-06-30"))
    assert ok
    assert "annual" in note


def test_quarterly_vs_annual_is_rejected():
    ok, note = periods_compatible(fact("2024-04-01", "2024-06-30"), fact("2024-07-01", "2025-06-30"))
    assert not ok
    assert "Duration mismatch" in note


def test_instant_vs_duration_is_rejected():
    ok, note = periods_compatible(fact(None, "2024-06-30"), fact("2024-07-01", "2025-06-30"))
    assert not ok
    assert "Period-type mismatch" in note


def test_unit_mismatch_is_rejected():
    ok, note = periods_compatible(
        fact("2023-07-01", "2024-06-30", unit="USD"),
        fact("2024-07-01", "2025-06-30", unit="EUR"),
    )
    assert not ok
    assert "Unit mismatch" in note


def test_two_year_gap_is_rejected_for_yoy():
    ok, note = periods_compatible(fact("2022-07-01", "2023-06-30"), fact("2024-07-01", "2025-06-30"))
    assert not ok
    assert "Fiscal alignment" in note


def test_two_year_gap_allowed_when_expected():
    ok, _ = periods_compatible(
        fact("2022-07-01", "2023-06-30"), fact("2024-07-01", "2025-06-30"), expected_years=2
    )
    assert ok


def test_instants_one_year_apart_are_compatible():
    ok, note = periods_compatible(fact(None, "2024-06-30"), fact(None, "2025-06-30"))
    assert ok
    assert "instant" in note


def test_missing_fact_sides_are_reported_individually():
    assert periods_compatible(None, fact("2024-07-01", "2025-06-30"))[1].startswith("No fact")
    assert periods_compatible(fact("2023-07-01", "2024-06-30"), None)[1].startswith("No fact")
    assert periods_compatible(None, None)[0] is False


def test_53_week_drift_within_tolerance():
    # A 52/53-week filer: FY ends move by a few days but stay comparable.
    ok, _ = periods_compatible(fact("2023-07-03", "2024-06-30"), fact("2024-07-01", "2025-06-29"))
    assert ok


def test_fiscal_alignment_drift_handles_leap_day():
    assert fiscal_alignment_drift_days(date(2024, 2, 29), date(2025, 2, 28)) <= 1


# --------------------------------------------------------------------------- #
# Filing-level structural checks
# --------------------------------------------------------------------------- #


def test_filing_pair_annual_ok(fy2024, fy2025):
    ok, notes = check_comparability(fy2024, fy2025)
    assert ok
    assert notes == []


def test_filing_pair_two_years_apart_is_rejected(fy2023, fy2025):
    ok, notes = check_comparability(fy2023, fy2025)
    assert not ok
    assert any("months apart" in n for n in notes)


def test_filing_pair_reversed_order_is_rejected(fy2024, fy2025):
    ok, notes = check_comparability(fy2025, fy2024)
    assert not ok
    assert any("Period ordering" in n for n in notes)


def test_form_mismatch_is_rejected(fy2024, fy2025):
    quarterly = fy2025.model_copy(update={"form": "10-Q"})
    ok, notes = check_comparability(fy2024, quarterly)
    assert not ok
    assert any("Form mismatch" in n for n in notes)


def test_amendment_is_flagged_but_not_blocking(fy2024, fy2025):
    amended = fy2025.model_copy(update={"form": "10-K/A", "is_amendment": True})
    ok, notes = check_comparability(fy2024, amended)
    assert ok
    assert any("amendment" in n for n in notes)
