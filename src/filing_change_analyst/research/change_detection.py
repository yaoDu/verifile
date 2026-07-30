"""Deterministic cross-period change detection.

This is the distinctive part of the system. Every claimed change is produced
from two measurements that are computed in Python:

* a **numerical signal** — a period-over-period metric change from the XBRL
  comparison engine; and/or
* an **emphasis signal** — a normalised change in how often a topic's
  terminology appears in the filing's narrative sections.

Both are backed by retrieved earlier and later excerpts. The result is a set of
material changes that exists with or without an LLM; the model, when available,
only adds interpretation on top of these facts.
"""

from __future__ import annotations

import difflib
import logging
import re

from ..formatting import money, ratio_pct
from ..models import (
    MaterialChange,
    MetricComparison,
    RiskFactorDelta,
    TopicEvidencePair,
)
from ..retrieval.search import TOPICS_BY_ID

log = logging.getLogger(__name__)

# Materiality thresholds. Chosen to keep the change list short and defensible;
# they are configurable rather than hidden constants in the UI layer.
MIN_EMPHASIS_DELTA = 1.5  # occurrences per 10,000 tokens
MIN_PERCENT_CHANGE = 15.0  # %
MIN_POINT_CHANGE = 1.0  # percentage points
MAX_CHANGES = 8

# Two risk headings are "the same risk, reworded" above this similarity.
RISK_SIMILARITY_THRESHOLD = 0.72


def _normalise_heading(text: str) -> str:
    t = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
    return re.sub(r"\s+", " ", t).strip()


def diff_risk_headings(
    earlier: list[str],
    later: list[str],
    *,
    earlier_chars: int = 0,
    later_chars: int = 0,
    confidence: str = "moderate",
) -> RiskFactorDelta:
    """Set-diff of risk-factor headings with fuzzy matching for rewordings."""
    e_norm = {_normalise_heading(h): h for h in earlier}
    l_norm = {_normalise_heading(h): h for h in later}

    retained: list[str] = []
    added: list[str] = []
    removed: list[str] = []
    matched_earlier: set[str] = set()

    for lk, lv in l_norm.items():
        best_key, best_ratio = None, 0.0
        for ek in e_norm:
            if ek in matched_earlier:
                continue
            r = difflib.SequenceMatcher(None, lk, ek).ratio()
            if r > best_ratio:
                best_key, best_ratio = ek, r
        if best_key is not None and best_ratio >= RISK_SIMILARITY_THRESHOLD:
            matched_earlier.add(best_key)
            retained.append(lv)
        else:
            added.append(lv)

    for ek, ev in e_norm.items():
        if ek not in matched_earlier:
            removed.append(ev)

    note = (
        f"Headings compared with fuzzy matching at a {RISK_SIMILARITY_THRESHOLD:.2f} similarity "
        "threshold, so a reworded risk counts as retained rather than as one addition plus one "
        "removal. Heading-level only: a risk whose heading is unchanged may still have had its "
        "body text materially rewritten."
    )
    return RiskFactorDelta(
        added=added,
        removed=removed,
        retained=retained,
        earlier_heading_count=len(earlier),
        later_heading_count=len(later),
        earlier_char_count=earlier_chars,
        later_char_count=later_chars,
        extraction_confidence=confidence,  # type: ignore[arg-type]
        note=note,
    )


def _metric_phrase(comp: MetricComparison) -> str | None:
    """A sentence describing one metric change, built only from computed values."""
    if comp.status != "ok":
        return None
    if comp.kind == "ratio":
        if comp.point_change is None:
            return None
        return (
            f"{comp.label} moved {comp.point_change:+.2f} percentage points "
            f"({ratio_pct(comp.earlier.value)} → {ratio_pct(comp.later.value)})"
        )
    if comp.percent_change is None:
        return None
    return (
        f"{comp.label} changed {comp.percent_change:+.1f}% "
        f"({money(comp.earlier.value, comp.earlier.unit)} → {money(comp.later.value, comp.later.unit)})"
    )


def _metric_signal_strength(comp: MetricComparison) -> float:
    if comp.status != "ok":
        return 0.0
    if comp.kind == "ratio":
        return abs(comp.point_change or 0.0) / MIN_POINT_CHANGE
    return abs(comp.percent_change or 0.0) / MIN_PERCENT_CHANGE


def _metric_direction(comp: MetricComparison) -> int:
    if comp.status != "ok":
        return 0
    delta = comp.point_change if comp.kind == "ratio" else comp.percent_change
    if delta is None:
        return 0
    return 1 if delta > 0 else (-1 if delta < 0 else 0)


# One metric change may anchor at most this many claims, so a single headline
# number (e.g. capex) cannot be recycled into an apparently long change list.
MAX_CLAIMS_PER_METRIC = 2


def detect_material_changes(
    topics: list[TopicEvidencePair],
    comparisons: list[MetricComparison],
    *,
    max_changes: int = MAX_CHANGES,
) -> list[MaterialChange]:
    """Rank topics by measured signal and emit deterministic change records."""
    by_id = {c.metric_id: c for c in comparisons}

    # Pass 1: score every candidate topic so that metric budgets are spent on
    # the strongest signals first.
    candidates: list[tuple[float, TopicEvidencePair, list[MetricComparison], float, float]] = []
    for tp in topics:
        if not tp.has_both_sides:
            continue
        related = [by_id[m] for m in tp.related_metric_ids if m in by_id]
        material_metrics = [c for c in related if _metric_signal_strength(c) >= 1.0]
        material_metrics.sort(key=_metric_signal_strength, reverse=True)
        emphasis_strength = abs(tp.emphasis_delta) / MIN_EMPHASIS_DELTA
        metric_strength = max((_metric_signal_strength(c) for c in material_metrics), default=0.0)
        if emphasis_strength < 1.0 and metric_strength < 1.0:
            continue
        candidates.append(
            (emphasis_strength + metric_strength, tp, material_metrics, emphasis_strength, metric_strength)
        )
    candidates.sort(key=lambda c: -c[0])

    metric_budget: dict[str, int] = {}
    out: list[MaterialChange] = []

    for _score, tp, material_metrics, emphasis_strength, _metric_strength in candidates:
        topic = TOPICS_BY_ID.get(tp.topic_id)
        usable_metrics = []
        for c in material_metrics:
            if metric_budget.get(c.metric_id, 0) < MAX_CLAIMS_PER_METRIC:
                usable_metrics.append(c)
        if emphasis_strength < 1.0 and not usable_metrics:
            continue  # its only signal was an over-used metric

        phrases = [p for p in (_metric_phrase(c) for c in usable_metrics[:2]) if p]
        emph_dir = 1 if tp.emphasis_delta > 0 else -1
        direction = "increased" if emph_dir > 0 else "decreased"
        caveat_bits = [
            "Emphasis is a phrase-frequency measure over extracted sections, normalised per "
            "10,000 tokens — it is a prominence signal, not a semantic judgement, and filing "
            "formatting differences can affect it."
        ]

        if emphasis_strength >= 1.0 and phrases:
            metric_dirs = {_metric_direction(c) for c in usable_metrics[:2]}
            diverging = emph_dir not in metric_dirs and metric_dirs != {0}
            if diverging:
                classification = "quantitative_shift"
                claim = (
                    f"Reported figures and narrative emphasis diverge on "
                    f"{tp.topic_label.lower()}: {'; '.join(phrases)}, while narrative emphasis "
                    f"{direction} ({tp.emphasis_delta:+.1f} mentions per 10,000 tokens)."
                )
                caveat_bits.append(
                    "A divergence between the numbers and the language may simply reflect "
                    "reorganised disclosure rather than a change in management's priorities."
                )
                strength = "moderate"
            else:
                classification = "expanded_emphasis" if emph_dir > 0 else "reduced_emphasis"
                claim = (
                    f"Narrative emphasis on {tp.topic_label.lower()} {direction} "
                    f"({tp.emphasis_delta:+.1f} mentions per 10,000 tokens) and the linked "
                    f"reported figures moved in the same direction: {'; '.join(phrases)}."
                )
                strength = "high"
            claim_type = "calculated_change"
        elif phrases:
            classification = "quantitative_shift"
            claim = (
                f"Measured financial change linked to {tp.topic_label.lower()}: "
                f"{'; '.join(phrases)}. Narrative emphasis was broadly unchanged "
                f"({tp.emphasis_delta:+.1f} mentions per 10,000 tokens)."
            )
            claim_type = "calculated_change"
            strength = "moderate"
            caveat_bits.append(
                "The filing does not attribute this metric change to this topic; the association "
                "is drawn by this tool, not by management."
            )
        else:
            classification = "expanded_emphasis" if emph_dir > 0 else "reduced_emphasis"
            claim = (
                f"Narrative emphasis on {tp.topic_label.lower()} {direction} "
                f"({tp.emphasis_delta:+.1f} mentions per 10,000 tokens) without a corresponding "
                "material change in the linked reported metrics."
            )
            claim_type = "management_statement"
            strength = "moderate" if emphasis_strength >= 2.0 else "low"
            if topic and topic.related_metric_ids:
                caveat_bits.append(
                    "No linked reported metric moved beyond the materiality threshold, so this is "
                    "a language change only."
                )

        for c in usable_metrics[:2]:
            metric_budget[c.metric_id] = metric_budget.get(c.metric_id, 0) + 1

        out.append(
            MaterialChange(
                change_id=f"chg-{tp.topic_id}",
                topic_id=tp.topic_id,
                topic_label=tp.topic_label,
                claim=claim,
                claim_type=claim_type,  # type: ignore[arg-type]
                classification=classification,  # type: ignore[arg-type]
                why_it_matters=(topic.why_it_matters if topic else ""),
                earlier_source_ids=[e.chunk.chunk_id for e in tp.earlier],
                later_source_ids=[e.chunk.chunk_id for e in tp.later],
                related_metric_ids=[c.metric_id for c in usable_metrics[:2]],
                evidence_strength=strength,  # type: ignore[arg-type]
                caveat=" ".join(caveat_bits),
                generated_by="deterministic",
            )
        )
        if len(out) >= max_changes:
            break
    return out


def risk_change_summary(delta: RiskFactorDelta) -> str:
    """One-line, purely factual summary of the risk-factor diff."""
    return (
        f"{delta.later_heading_count} risk-factor headings in the latest filing versus "
        f"{delta.earlier_heading_count} in the previous one: {len(delta.added)} new, "
        f"{len(delta.removed)} no longer present, {len(delta.retained)} retained "
        f"(extraction confidence: {delta.extraction_confidence}). Item 1A length "
        f"{delta.earlier_char_count:,} → {delta.later_char_count:,} characters."
    )
