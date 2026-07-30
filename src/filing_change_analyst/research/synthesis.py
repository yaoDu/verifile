"""Constrained AI synthesis, applied on top of the deterministic result.

Nothing here can remove or alter a deterministic finding. The model's output is
put through four mechanical gates before it is accepted:

1. **Schema validation** — Pydantic, in :mod:`services.llm`.
2. **Citation validation** — every source id must resolve to a supplied chunk,
   and a cross-period claim must cite both periods.
3. **Numeric grounding** — any figure in the generated prose must appear in the
   supplied evidence or in the Python-computed metric table.
4. **Content guardrails** — anything resembling an investment recommendation is
   dropped.

A change that fails any gate is discarded and the deterministic change for that
topic stands.
"""

from __future__ import annotations

import logging

from ..analytics.validation import (
    allowed_number_set,
    contains_recommendation,
    ungrounded_numbers,
)
from ..models import (
    LlmBriefSections,
    LlmChangeSet,
    MaterialChange,
    MetricComparison,
    RiskFactorDelta,
    TopicEvidencePair,
)
from ..retrieval.citations import (
    evidence_is_supported,
    validate_citation_ids,
    validate_metric_ids,
)
from ..services.llm import LlmClient
from . import prompts
from .change_detection import risk_change_summary

log = logging.getLogger(__name__)

MAX_TOPICS_TO_MODEL = 6


def _topic_evidence_ids(topics: list[TopicEvidencePair]) -> set[str]:
    ids: set[str] = set()
    for t in topics:
        ids |= {e.chunk.chunk_id for e in t.earlier}
        ids |= {e.chunk.chunk_id for e in t.later}
    return ids


def _topic_texts(topics: list[TopicEvidencePair]) -> list[str]:
    out: list[str] = []
    for t in topics:
        out.extend(e.chunk.text for e in t.earlier)
        out.extend(e.chunk.text for e in t.later)
        out.append(t.signal_note)
    return out


def interpret_changes(
    client: LlmClient,
    pair,
    comparisons: list[MetricComparison],
    topics: list[TopicEvidencePair],
    deterministic: list[MaterialChange],
) -> tuple[list[MaterialChange], list[str]]:
    """Ask the model to interpret the top signals. Returns ``(changes, notes)``.

    On any failure the deterministic list is returned unchanged.
    """
    notes: list[str] = []
    if not client.available:
        return deterministic, ["AI synthesis unavailable (no API key); showing deterministic changes only."]

    ranked_ids = [c.topic_id for c in deterministic][:MAX_TOPICS_TO_MODEL]
    selected = [t for t in topics if t.topic_id in ranked_ids and t.has_both_sides]
    if not selected:
        return deterministic, ["No topic had evidence from both filings; AI synthesis skipped."]

    parsed, run = client.structured(
        system=prompts.system_prompt(prompts.CHANGE_ROLE),
        user=prompts.change_user_prompt(pair, comparisons, selected),
        schema=LlmChangeSet,
        purpose="material_changes",
    )
    if parsed is None:
        notes.append(f"AI change synthesis failed ({run.error}); deterministic changes retained.")
        return deterministic, notes

    if parsed.insufficient_evidence and not parsed.changes:
        notes.append(
            "The model judged the retrieved evidence insufficient for additional interpretation; "
            "deterministic changes are shown."
        )
        return deterministic, notes

    allowed_ids = _topic_evidence_ids(selected)
    allowed_numbers = allowed_number_set(comparisons, _topic_texts(selected))
    by_topic = {c.topic_id: c for c in deterministic}
    topic_lookup = {t.topic_id: t for t in selected}

    accepted: list[MaterialChange] = []
    dropped_citations: list[str] = []
    dropped = 0
    used_topics: set[str] = set()

    for i, ch in enumerate(parsed.changes):
        earlier_ok, bad_e = validate_citation_ids(ch.earlier_source_ids, allowed_ids)
        later_ok, bad_l = validate_citation_ids(ch.later_source_ids, allowed_ids)
        dropped_citations.extend(bad_e + bad_l)

        supported, why = evidence_is_supported(earlier_ok, later_ok)
        if not supported:
            log.info("Dropping model change %d: %s", i, why)
            dropped += 1
            continue

        prose = f"{ch.claim} {ch.why_it_matters} {ch.caveat}"
        if contains_recommendation(prose):
            log.info("Dropping model change %d: contains recommendation language", i)
            dropped += 1
            continue

        bad_numbers = ungrounded_numbers(prose, allowed_numbers)
        if bad_numbers:
            log.info("Dropping model change %d: ungrounded numbers %s", i, bad_numbers)
            notes.append(
                "One AI-generated change was discarded because it contained figures "
                f"({', '.join(bad_numbers[:3])}) that do not appear in the supplied evidence "
                "or the calculated metrics."
            )
            dropped += 1
            continue

        metric_ids, bad_metrics = validate_metric_ids(ch.related_metric_ids, comparisons)
        if bad_metrics:
            dropped_citations.extend(bad_metrics)

        # Attribute the change to the topic whose evidence it actually cites.
        topic_id = _infer_topic(earlier_ok + later_ok, topic_lookup) or ""
        base = by_topic.get(topic_id)
        used_topics.add(topic_id)
        accepted.append(
            MaterialChange(
                change_id=f"chg-llm-{topic_id or i}",
                topic_id=topic_id,
                topic_label=topic_lookup[topic_id].topic_label if topic_id in topic_lookup else "",
                claim=ch.claim,
                claim_type=ch.claim_type,
                classification=ch.classification,
                why_it_matters=ch.why_it_matters,
                earlier_source_ids=earlier_ok,
                later_source_ids=later_ok,
                related_metric_ids=metric_ids or (base.related_metric_ids if base else []),
                evidence_strength=ch.evidence_strength,
                caveat=ch.caveat,
                generated_by="llm",
            )
        )

    run.dropped_citations = list(dict.fromkeys(dropped_citations))
    run.dropped_changes = dropped
    if dropped_citations:
        notes.append(
            f"{len(run.dropped_citations)} model-supplied identifier(s) did not match the "
            "supplied evidence and were removed."
        )
    if dropped:
        notes.append(f"{dropped} AI-generated change(s) failed validation and were discarded.")

    if not accepted:
        notes.append("No AI-generated change passed validation; deterministic changes retained.")
        return deterministic, notes

    # Keep deterministic entries for topics the model did not cover, so the
    # measured signal is never silently lost.
    leftovers = [c for c in deterministic if c.topic_id not in used_topics]
    return accepted + leftovers, notes


def _infer_topic(source_ids: list[str], topics: dict[str, TopicEvidencePair]) -> str | None:
    counts: dict[str, int] = {}
    for tid, t in topics.items():
        ids = {e.chunk.chunk_id for e in t.earlier} | {e.chunk.chunk_id for e in t.later}
        n = sum(1 for s in source_ids if s in ids)
        if n:
            counts[tid] = n
    if not counts:
        return None
    return max(counts, key=lambda k: counts[k])


def write_brief_sections(
    client: LlmClient,
    pair,
    comparisons: list[MetricComparison],
    changes: list[MaterialChange],
    risk_delta: RiskFactorDelta | None,
) -> tuple[LlmBriefSections | None, list[str]]:
    """Executive summary, bull/bear interpretation, questions and caveats."""
    notes: list[str] = []
    if not client.available:
        return None, []

    changes_summary = "\n".join(
        f"- [{c.claim_type}/{c.evidence_strength}] {c.claim} (metrics: "
        f"{', '.join(c.related_metric_ids) or 'none'})"
        for c in changes
    ) or "(no material changes exceeded the thresholds)"
    risk_summary = risk_change_summary(risk_delta) if risk_delta else "(risk diff unavailable)"
    if risk_delta:
        if risk_delta.added:
            risk_summary += "\nNew risk headings: " + "; ".join(risk_delta.added[:6])
        if risk_delta.removed:
            risk_summary += "\nRemoved risk headings: " + "; ".join(risk_delta.removed[:6])

    parsed, run = client.structured(
        system=prompts.system_prompt(prompts.BRIEF_ROLE),
        user=prompts.brief_user_prompt(pair, comparisons, changes_summary, risk_summary),
        schema=LlmBriefSections,
        purpose="brief_sections",
    )
    if parsed is None:
        return None, [f"AI brief sections unavailable ({run.error}); the brief omits them."]

    allowed = allowed_number_set(comparisons, [changes_summary, risk_summary])
    cleaned = LlmBriefSections()
    removed = 0
    for field in (
        "executive_summary",
        "bull_considerations",
        "bear_considerations",
        "questions_for_management",
        "caveats",
    ):
        kept: list[str] = []
        for line in getattr(parsed, field):
            if contains_recommendation(line):
                removed += 1
                continue
            if ungrounded_numbers(line, allowed):
                removed += 1
                continue
            kept.append(line)
        setattr(cleaned, field, kept)

    if removed:
        notes.append(
            f"{removed} AI-written brief line(s) were removed for containing unsupported figures "
            "or recommendation language."
        )
    return cleaned, notes
