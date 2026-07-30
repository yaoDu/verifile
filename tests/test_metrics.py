"""Metric calculation, fact selection and missing-data behaviour."""

from __future__ import annotations

from datetime import date

import pytest

from filing_change_analyst.analytics.comparisons import (
    build_metric_set,
    compare_filings,
    compare_metric,
)
from filing_change_analyst.analytics.metric_definitions import METRICS_BY_ID
from filing_change_analyst.formatting import change_text, metric_value_text
from filing_change_analyst.models import MetricValue

# Values as printed in Microsoft's FY2025 10-K, used as ground truth.
FY2025 = {
    "revenue": 281_724_000_000,
    "gross_profit": 193_893_000_000,
    "operating_income": 128_528_000_000,
    "net_income": 101_832_000_000,
    "rnd_expense": 32_488_000_000,
    "operating_cash_flow": 136_162_000_000,
    "capex": 64_551_000_000,
    "diluted_eps": 13.64,
}
FY2024 = {
    "revenue": 245_122_000_000,
    "gross_profit": 171_008_000_000,
    "operating_income": 109_433_000_000,
    "net_income": 88_136_000_000,
    "rnd_expense": 29_510_000_000,
    "operating_cash_flow": 118_548_000_000,
    "capex": 44_477_000_000,
    "diluted_eps": 11.80,
}


def test_reported_values_match_the_filing(fact_store, fy2025, fy2024):
    later, _, _ = build_metric_set(fact_store, fy2025)
    earlier, _, _ = build_metric_set(fact_store, fy2024)
    for mid, expected in FY2025.items():
        assert later[mid].value == pytest.approx(expected), mid
    for mid, expected in FY2024.items():
        assert earlier[mid].value == pytest.approx(expected), mid


def test_selected_facts_come_from_the_selected_filing(fact_store, fy2025):
    values, _, _ = build_metric_set(fact_store, fy2025)
    prov = values["revenue"].provenance[0]
    assert prov.accession == fy2025.accession
    assert prov.end == date(2025, 6, 30)
    assert prov.selection_rule == "filing_scoped_exact_period"
    assert prov.duration_class == "annual"


def test_free_cash_flow_is_ocf_minus_capex(fact_store, fy2025):
    values, _, _ = build_metric_set(fact_store, fy2025)
    assert values["free_cash_flow"].value == pytest.approx(
        FY2025["operating_cash_flow"] - FY2025["capex"]
    )
    assert "operating_cash_flow - capex" in values["free_cash_flow"].derivation


def test_margins_are_ratios_not_percentages(fact_store, fy2025):
    values, _, _ = build_metric_set(fact_store, fy2025)
    gm = values["gross_margin"].value
    assert 0 < gm < 1
    assert gm == pytest.approx(FY2025["gross_profit"] / FY2025["revenue"])


def test_percent_change_for_levels(fact_store, pair):
    comps, _, _ = compare_filings(fact_store, pair)
    by_id = {c.metric_id: c for c in comps}
    rev = by_id["revenue"]
    expected = (FY2025["revenue"] - FY2024["revenue"]) / FY2024["revenue"] * 100
    assert rev.percent_change == pytest.approx(expected)
    assert rev.point_change is None
    assert change_text(rev).endswith("%")


def test_point_change_for_ratios(fact_store, pair):
    comps, _, _ = compare_filings(fact_store, pair)
    by_id = {c.metric_id: c for c in comps}
    gm = by_id["gross_margin"]
    expected_pp = (
        FY2025["gross_profit"] / FY2025["revenue"] - FY2024["gross_profit"] / FY2024["revenue"]
    ) * 100
    assert gm.point_change == pytest.approx(expected_pp)
    assert gm.percent_change is None
    assert change_text(gm).endswith("pp")


def test_capex_change_matches_hand_calculation(fact_store, pair):
    comps, _, _ = compare_filings(fact_store, pair)
    capex = next(c for c in comps if c.metric_id == "capex")
    expected = (FY2025["capex"] - FY2024["capex"]) / FY2024["capex"] * 100
    assert capex.percent_change == pytest.approx(expected)
    assert capex.percent_change == pytest.approx(45.13, abs=0.01)


def test_free_cash_flow_fell_while_capex_rose(fact_store, pair):
    comps, _, _ = compare_filings(fact_store, pair)
    by_id = {c.metric_id: c for c in comps}
    assert by_id["capex"].percent_change > 0
    assert by_id["free_cash_flow"].percent_change < 0


def test_all_display_metrics_are_produced(fact_store, pair):
    comps, _, _ = compare_filings(fact_store, pair)
    assert len(comps) >= 6
    usable = [c for c in comps if c.status == "ok"]
    assert len(usable) >= 6


def test_incompatible_pair_suppresses_every_comparison(fact_store, fy2023, fy2025):
    from filing_change_analyst.sec.filings import build_pair

    bad = build_pair(fy2023, fy2025)
    assert not bad.comparability_ok
    comps, _, _ = compare_filings(fact_store, bad)
    assert all(c.status == "incompatible_periods" for c in comps if c.earlier.available and c.later.available)
    assert all(c.percent_change is None and c.point_change is None for c in comps)


def _store_without(companyfacts_json, *concepts: str):
    import copy

    from filing_change_analyst.sec.facts import FactStore

    trimmed = copy.deepcopy(companyfacts_json)
    for c in concepts:
        trimmed["facts"]["us-gaap"].pop(c, None)
    return FactStore(trimmed)


def test_missing_metric_reports_na_and_a_reason(companyfacts_json, fy2025):
    store = _store_without(
        companyfacts_json,
        "ResearchAndDevelopmentExpense",
    )
    values, _, _ = build_metric_set(store, fy2025)
    missing = values["rnd_expense"]
    assert missing.value is None
    assert missing.missing_reason and "Tried:" in missing.missing_reason
    assert metric_value_text(missing, "currency") == "N/A"
    # Derived metrics that depend on it must also degrade, not guess.
    assert values["rnd_intensity"].value is None
    assert "rnd_expense" in values["rnd_intensity"].missing_reason


def test_gross_profit_falls_back_to_revenue_minus_cost_of_revenue(companyfacts_json, fy2025):
    store = _store_without(companyfacts_json, "GrossProfit")
    values, _, _ = build_metric_set(store, fy2025)
    gp = values["gross_profit"]
    assert gp.value == pytest.approx(FY2025["gross_profit"])
    assert "revenue - cost_of_revenue" in gp.derivation
    assert len(gp.provenance) == 2  # both inputs are traceable


def test_missing_side_blocks_the_comparison():
    mdef = METRICS_BY_ID["revenue"]
    present = MetricValue(metric_id="revenue", value=100.0, unit="USD", period_type="duration")
    absent = MetricValue(
        metric_id="revenue", value=None, unit="USD", period_type="duration", missing_reason="x"
    )
    assert compare_metric(mdef, absent, present, period_ok=True, period_note="").status == "missing_earlier"
    assert compare_metric(mdef, present, absent, period_ok=True, period_note="").status == "missing_later"
    assert compare_metric(mdef, absent, absent, period_ok=True, period_note="").status == "missing_both"


def test_zero_prior_value_does_not_divide_by_zero():
    mdef = METRICS_BY_ID["revenue"]
    zero = MetricValue(metric_id="revenue", value=0.0, unit="USD", period_type="duration")
    later = MetricValue(metric_id="revenue", value=50.0, unit="USD", period_type="duration")
    c = compare_metric(mdef, zero, later, period_ok=True, period_note="")
    assert c.percent_change is None
    assert c.absolute_change == 50.0
    assert any("zero" in w for w in c.warnings)


def test_sign_flip_suppresses_percent_change():
    mdef = METRICS_BY_ID["net_income"]
    loss = MetricValue(metric_id="net_income", value=-100.0, unit="USD", period_type="duration")
    profit = MetricValue(metric_id="net_income", value=50.0, unit="USD", period_type="duration")
    c = compare_metric(mdef, loss, profit, period_ok=True, period_note="")
    assert c.percent_change is None
    assert c.absolute_change == 150.0
    assert any("sign" in w for w in c.warnings)


def test_restatement_detection_runs_and_is_clean_for_msft(fact_store, pair):
    _, flags, _ = compare_filings(fact_store, pair)
    # MSFT did not restate FY2024 in the FY2025 10-K; the check must run and find nothing.
    assert flags == []


def test_every_reported_value_carries_provenance(fact_store, pair):
    comps, _, _ = compare_filings(fact_store, pair)
    for c in comps:
        for mv in (c.earlier, c.later):
            if mv.available:
                assert mv.provenance, f"{c.metric_id} has a value but no provenance"
                for p in mv.provenance:
                    assert p.concept and p.accession and p.unit
