"""The deterministic comparison engine.

Everything the analyst sees as a number is produced here, in Python, from XBRL
facts with recorded provenance. The LLM layer receives these values as inputs
and is never asked to compute or restate them.
"""

from __future__ import annotations

import logging
from datetime import date

from ..models import (
    ComparisonBasis,
    DurationClass,
    FactProvenance,
    Filing,
    FilingPair,
    MetricComparison,
    MetricValue,
    RestatementFlag,
    XbrlFact,
)
from ..sec.facts import FactStore
from .metric_definitions import DISPLAY_ORDER, METRICS_BY_ID, REPORTED_METRICS, MetricDef
from .period_matching import (
    YEAR_TO_DATE_CLASSES,
    classify_duration,
    default_duration_class,
    periods_compatible,
)

log = logging.getLogger(__name__)

# Below this the percent change is unstable and we show the absolute change only.
MIN_DENOMINATOR_FOR_PERCENT = 1e-9

# A prior-year figure re-reported in the newer filing that differs by more than
# this fraction is flagged as a possible restatement.
RESTATEMENT_TOLERANCE = 0.001  # 0.1 %


# --------------------------------------------------------------------------- #
# Building metric values
# --------------------------------------------------------------------------- #


def _provenance(fact: XbrlFact, filing: Filing, rule: str) -> FactProvenance:
    return FactProvenance(
        concept=fact.concept,
        taxonomy=fact.taxonomy,
        unit=fact.unit,
        period_type=fact.period_type,
        start=fact.start,
        end=fact.end,
        duration_days=fact.duration_days,
        duration_class=classify_duration(fact.duration_days),
        form=fact.form,
        accession=fact.accession,
        filed=fact.filed,
        fiscal_year=fact.fiscal_year,
        fiscal_period=fact.fiscal_period,
        source_url=filing.primary_document_url
        if fact.accession == filing.accession
        else _archive_url(filing.cik, fact.accession),
        selection_rule=rule,
    )


def _archive_url(cik: str, accession: str | None) -> str | None:
    if not accession:
        return None
    return (
        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
        f"{accession.replace('-', '')}/{accession}-index.htm"
    )


def build_reported_metric(
    store: FactStore,
    filing: Filing,
    mdef: MetricDef,
    *,
    period_end: date | None = None,
    duration_class: DurationClass | None = None,
    require_same_accession: bool = False,
) -> tuple[MetricValue, XbrlFact | None, list[str]]:
    """Read one reported metric for one filing period."""
    target_end = period_end or filing.report_date
    warnings: list[str] = []

    # Multi-concept sums (e.g. total debt = current + non-current).
    if mdef.sum_concepts:
        total = 0.0
        provs: list[FactProvenance] = []
        facts: list[XbrlFact] = []
        complete = True
        for addend_options in mdef.sum_concepts:
            got = None
            for concept in addend_options:
                fact, rule, w = store.select(
                    concept,
                    filing,
                    period_type=mdef.period_type,
                    period_end=target_end,
                    duration_class=duration_class,
                    require_same_accession=require_same_accession,
                )
                warnings.extend(w)
                if fact is not None:
                    got = (fact, rule)
                    break
            if got is None:
                complete = False
                break
            fact, rule = got
            total += fact.value
            facts.append(fact)
            provs.append(_provenance(fact, filing, rule))
        if complete and facts:
            return (
                MetricValue(
                    metric_id=mdef.metric_id,
                    value=total * mdef.sign,
                    unit=facts[0].unit,
                    period_type=mdef.period_type,
                    start=facts[0].start,
                    end=facts[0].end,
                    duration_class=classify_duration(facts[0].duration_days),
                    provenance=provs,
                    derivation=" + ".join(p.concept for p in provs),
                ),
                facts[0],
                warnings,
            )

    for concept in mdef.concepts:
        fact, rule, w = store.select(
            concept,
            filing,
            period_type=mdef.period_type,
            period_end=target_end,
            duration_class=duration_class,
            require_same_accession=require_same_accession,
        )
        warnings.extend(w)
        if fact is None:
            continue
        return (
            MetricValue(
                metric_id=mdef.metric_id,
                value=fact.value * mdef.sign,
                unit=fact.unit,
                period_type=fact.period_type,
                start=fact.start,
                end=fact.end,
                duration_class=classify_duration(fact.duration_days),
                provenance=[_provenance(fact, filing, rule)],
                derivation=f"Reported XBRL concept {fact.taxonomy}:{concept}",
            ),
            fact,
            warnings,
        )

    tried = ", ".join(mdef.concepts + tuple(c for opts in mdef.sum_concepts for c in opts))
    return (
        MetricValue(
            metric_id=mdef.metric_id,
            value=None,
            unit="USD",
            period_type=mdef.period_type,
            end=target_end,
            missing_reason=f"No usable XBRL fact for period ending {target_end}. Tried: {tried}.",
        ),
        None,
        warnings,
    )


def _derive(
    mdef: MetricDef, inputs: dict[str, MetricValue], facts: dict[str, XbrlFact | None]
) -> MetricValue:
    """Compute a derived metric in Python from already-selected reported values."""
    missing = [k for k in mdef.derived_from if inputs.get(k) is None or not inputs[k].available]
    anchor = next(
        (inputs[k] for k in mdef.derived_from if inputs.get(k) and inputs[k].available), None
    )
    if missing:
        return MetricValue(
            metric_id=mdef.metric_id,
            value=None,
            unit="ratio" if mdef.kind == "ratio" else "USD",
            period_type=anchor.period_type if anchor else "duration",
            start=anchor.start if anchor else None,
            end=anchor.end if anchor else None,
            missing_reason=f"Requires {', '.join(missing)}, which could not be read from XBRL.",
            derivation=mdef.formula,
        )

    vals = {k: inputs[k].value for k in mdef.derived_from}
    value: float | None
    if mdef.metric_id in ("gross_margin", "operating_margin", "net_margin", "capex_intensity", "rnd_intensity"):
        numerator_key, denominator_key = mdef.derived_from
        denom = vals[denominator_key] or 0.0
        value = None if abs(denom) < MIN_DENOMINATOR_FOR_PERCENT else vals[numerator_key] / denom
    elif mdef.metric_id == "free_cash_flow":
        value = vals["operating_cash_flow"] - vals["capex"]
    elif mdef.metric_id == "net_cash":
        value = (
            vals["cash_and_equivalents"] + vals["short_term_investments"] - vals["total_debt"]
        )
    else:  # pragma: no cover - guarded by the metric catalogue
        raise ValueError(f"No derivation implemented for {mdef.metric_id}")

    provs = [p for k in mdef.derived_from for p in inputs[k].provenance]
    return MetricValue(
        metric_id=mdef.metric_id,
        value=value,
        unit="ratio" if mdef.kind == "ratio" else (inputs[mdef.derived_from[0]].unit),
        period_type=anchor.period_type if anchor else "duration",
        start=anchor.start if anchor else None,
        end=anchor.end if anchor else None,
        duration_class=anchor.duration_class if anchor else "other",
        provenance=provs,
        derivation=f"Calculated in Python: {mdef.formula}",
        missing_reason=None if value is not None else "Denominator is zero.",
    )


def build_metric_set(
    store: FactStore,
    filing: Filing,
    *,
    period_end: date | None = None,
    duration_class: DurationClass | None = None,
    require_same_accession: bool = False,
) -> tuple[dict[str, MetricValue], dict[str, XbrlFact | None], list[str]]:
    """All metrics (reported + derived) for one filing period.

    ``duration_class`` defaults to the form's usual reporting length so a 10-Q
    reads as the quarter rather than picking arbitrarily between the quarter and
    the year-to-date fact.
    """
    if duration_class is None:
        duration_class = default_duration_class(filing.form)
    values: dict[str, MetricValue] = {}
    facts: dict[str, XbrlFact | None] = {}
    warnings: list[str] = []

    for mdef in REPORTED_METRICS:
        mv, fact, w = build_reported_metric(
            store,
            filing,
            mdef,
            period_end=period_end,
            duration_class=duration_class,
            require_same_accession=require_same_accession,
        )
        values[mdef.metric_id] = mv
        facts[mdef.metric_id] = fact
        warnings.extend(w)

    # Gross profit fallback: revenue − cost of revenue when GrossProfit is untagged.
    gp, rev, cor = values["gross_profit"], values["revenue"], values["cost_of_revenue"]
    if not gp.available and rev.available and cor.available:
        values["gross_profit"] = MetricValue(
            metric_id="gross_profit",
            value=rev.value - cor.value,  # type: ignore[operator]
            unit=rev.unit,
            period_type=rev.period_type,
            start=rev.start,
            end=rev.end,
            duration_class=rev.duration_class,
            provenance=rev.provenance + cor.provenance,
            derivation="Calculated in Python: revenue - cost_of_revenue (GrossProfit not tagged)",
        )
        facts["gross_profit"] = facts["revenue"]

    for mid, mdef in METRICS_BY_ID.items():
        if mdef.derived_from:
            values[mid] = _derive(mdef, values, facts)
    return values, facts, warnings


# --------------------------------------------------------------------------- #
# Comparing
# --------------------------------------------------------------------------- #


def _compat_for(
    mdef: MetricDef,
    earlier_facts: dict[str, XbrlFact | None],
    later_facts: dict[str, XbrlFact | None],
    earlier_vals: dict[str, MetricValue],
    later_vals: dict[str, MetricValue],
    basis: ComparisonBasis = "year_over_year",
    period_class: DurationClass | None = None,
) -> tuple[bool, str]:
    """Period compatibility, resolved through derived metrics to their inputs."""
    keys = mdef.derived_from or (mdef.metric_id,)
    notes: list[str] = []
    for key in keys:
        ef, lf = earlier_facts.get(key), later_facts.get(key)
        if ef is None or lf is None:
            # Fall back to the metric values' own declared periods.
            ev, lv = earlier_vals.get(key), later_vals.get(key)
            if ev is None or lv is None or not (ev.available and lv.available):
                continue
            if ev.period_type != lv.period_type:
                return False, f"{key}: period-type mismatch ({ev.period_type} vs {lv.period_type})."
            continue
        ok, note = periods_compatible(ef, lf, basis=basis, period_class=period_class)
        if not ok:
            return False, f"{key}: {note}"
        notes.append(note)
    return True, notes[0] if notes else "Period metadata unavailable; compatibility not verified."


def compare_metric(
    mdef: MetricDef,
    earlier: MetricValue,
    later: MetricValue,
    *,
    period_ok: bool,
    period_note: str,
    extra_warnings: list[str] | None = None,
) -> MetricComparison:
    """Compute one comparison row. This is where all display arithmetic happens."""
    warnings = list(extra_warnings or [])
    comp = MetricComparison(
        metric_id=mdef.metric_id,
        label=mdef.label,
        kind=mdef.kind,
        earlier=earlier,
        later=later,
        period_note=period_note,
        definition=mdef.definition,
        warnings=warnings,
    )

    if not earlier.available and not later.available:
        comp.status = "missing_both"
        return comp
    if not earlier.available:
        comp.status = "missing_earlier"
        return comp
    if not later.available:
        comp.status = "missing_later"
        return comp
    if not period_ok:
        comp.status = "incompatible_periods"
        comp.warnings.append(
            "Comparison suppressed: " + (period_note or "incompatible reporting periods.")
        )
        return comp

    e, l = float(earlier.value), float(later.value)  # noqa: E741
    comp.absolute_change = l - e

    if mdef.kind == "ratio":
        # Ratios move in percentage POINTS, never percent.
        comp.point_change = (l - e) * 100.0
    else:
        if abs(e) < MIN_DENOMINATOR_FOR_PERCENT:
            comp.warnings.append(
                "Prior-period value is zero; percentage change is undefined and is not shown."
            )
        elif (e < 0) != (l < 0):
            comp.warnings.append(
                "The value changed sign between periods; percentage change is not meaningful "
                "and is not shown."
            )
        else:
            comp.percent_change = (l - e) / abs(e) * 100.0

    comp.status = "ok"
    return comp


def compare_filings(
    store: FactStore,
    pair: FilingPair,
    *,
    metric_ids: tuple[str, ...] = DISPLAY_ORDER,
    duration_class: DurationClass | None = None,
) -> tuple[list[MetricComparison], list[RestatementFlag], list[str]]:
    """Full deterministic comparison for a filing pair.

    ``duration_class`` pins both sides to one reporting length (for a 10-Q,
    ``"quarterly"`` or ``"three_quarters"`` for year-to-date). ``None`` uses the
    form default. Both sides always use the same length, so a quarter is never
    compared against a year-to-date figure.

    The fact-level alignment check reads ``pair.basis``: a sequential pair is one
    period apart, not one year, and measuring the wrong one blocks every metric.

    Returns ``(comparisons, restatement_flags, warnings)``.
    """
    # Resolved once here so the alignment check and the fact selection agree on
    # the reporting length; a balance-sheet fact has no duration of its own and
    # this is the only place its expected spacing can come from.
    period_class = duration_class or default_duration_class(pair.later.form)
    earlier_vals, earlier_facts, w1 = build_metric_set(
        store, pair.earlier, duration_class=duration_class
    )
    later_vals, later_facts, w2 = build_metric_set(
        store, pair.later, duration_class=duration_class
    )
    warnings = list(dict.fromkeys(w1 + w2))
    if pair.basis == "sequential" and period_class in YEAR_TO_DATE_CLASSES:
        warnings.insert(
            0,
            "A sequential comparison cannot be read on a year-to-date basis: year-to-date "
            "figures accumulate from the fiscal year start, so consecutive quarters cover "
            "different lengths (six months, then nine) and are not like-for-like. Every metric "
            "below is unavailable. Use the quarter basis for a sequential comparison, or "
            "compare year over year.",
        )

    comparisons: list[MetricComparison] = []
    for mid in metric_ids:
        mdef = METRICS_BY_ID.get(mid)
        if mdef is None:
            continue
        ok, note = _compat_for(
            mdef, earlier_facts, later_facts, earlier_vals, later_vals, pair.basis, period_class
        )
        if not pair.comparability_ok:
            ok = False
            note = "Filing pair failed structural comparability checks. " + " ".join(
                pair.comparability_notes
            )
        comparisons.append(
            compare_metric(
                mdef,
                earlier_vals[mid],
                later_vals[mid],
                period_ok=ok,
                period_note=note,
            )
        )

    restatements = detect_restatements(
        store, pair, earlier_vals, metric_ids=metric_ids, duration_class=duration_class
    )
    return comparisons, restatements, warnings


def detect_restatements(
    store: FactStore,
    pair: FilingPair,
    earlier_vals: dict[str, MetricValue],
    *,
    metric_ids: tuple[str, ...] = DISPLAY_ORDER,
    duration_class: DurationClass | None = None,
) -> list[RestatementFlag]:
    """Compare the prior year *as first reported* with the prior year *as shown in
    the newer filing*.

    A silent restatement makes a naive year-over-year comparison wrong, so it is
    surfaced rather than absorbed.
    """
    flags: list[RestatementFlag] = []
    restated_vals, _, _ = build_metric_set(
        store,
        pair.later,
        period_end=pair.earlier.report_date,
        duration_class=duration_class,
        require_same_accession=True,
    )
    for mid in metric_ids:
        mdef = METRICS_BY_ID.get(mid)
        if mdef is None or mdef.kind == "ratio":
            continue
        orig, restated = earlier_vals.get(mid), restated_vals.get(mid)
        if not (orig and restated and orig.available and restated.available):
            continue
        o, r = float(orig.value), float(restated.value)
        if abs(o) < MIN_DENOMINATOR_FOR_PERCENT:
            continue
        rel = abs(r - o) / abs(o)
        if rel > RESTATEMENT_TOLERANCE:
            flags.append(
                RestatementFlag(
                    metric_id=mid,
                    label=mdef.label,
                    as_originally_reported=o,
                    as_restated_in_later_filing=r,
                    difference=r - o,
                    relative_difference=rel * 100.0,
                    note=(
                        f"{mdef.label} for the period ending {pair.earlier.report_date} is tagged "
                        f"differently in {pair.later.form} {pair.later.accession} than in "
                        f"{pair.earlier.form} {pair.earlier.accession}. Year-over-year change may "
                        "reflect a reclassification or restatement as well as underlying "
                        "performance."
                    ),
                )
            )
    return flags
