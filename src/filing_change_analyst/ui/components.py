"""Streamlit rendering helpers.

All filing text reaches the UI as plain strings rendered through Streamlit's
default (escaped) Markdown path — filing content is never injected as raw HTML.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..formatting import (
    absolute_change_text,
    change_text,
    metric_value_text,
    short_excerpt,
    status_text,
)
from ..models import (
    AnalysisResult,
    EvidenceChunk,
    MaterialChange,
    MetricComparison,
    RetrievedEvidence,
)

CLAIM_BADGE = {
    "verified_fact": ("✅", "Verified fact"),
    "calculated_change": ("🧮", "Calculated change"),
    "management_statement": ("💬", "Management statement"),
    "interpretation": ("🤖", "AI interpretation"),
    "caveat": ("⚠️", "Caveat"),
    "open_question": ("❓", "Open question"),
}

STRENGTH_COLOUR = {"high": "🟢", "moderate": "🟡", "low": "🔴"}


def filing_pair_header(result: AnalysisResult) -> None:
    pair = result.pair
    e, l = pair.earlier, pair.later  # noqa: E741
    c1, c2 = st.columns(2)
    for col, filing, label in ((c1, e, "Earlier filing"), (c2, l, "Latest filing")):
        with col:
            st.markdown(f"**{label}**")
            st.markdown(
                f"- Form: `{filing.form}`\n"
                f"- Period ending: `{filing.report_date}`\n"
                f"- Filed: `{filing.filing_date}`\n"
                f"- Accession: `{filing.accession}`\n"
                f"- [Open on SEC EDGAR]({filing.primary_document_url})"
            )
    if not pair.comparability_ok:
        st.error(
            "**Period comparability check failed — figures below are suppressed.**\n\n"
            + "\n".join(f"- {n}" for n in pair.comparability_notes)
        )
    elif pair.comparability_notes:
        st.warning("\n".join(f"- {n}" for n in pair.comparability_notes))


def metrics_table(result: AnalysisResult) -> pd.DataFrame:
    rows = []
    for c in result.comparisons:
        rows.append(
            {
                "Metric": c.label,
                "Previous period": metric_value_text(c.earlier, c.kind),
                "Latest period": metric_value_text(c.later, c.kind),
                "Absolute change": absolute_change_text(c),
                "% / pp change": change_text(c),
                "Status": status_text(c),
            }
        )
    return pd.DataFrame(rows)


def provenance_expander(c: MetricComparison) -> None:
    with st.expander(f"Source and provenance — {c.label}"):
        st.caption(c.definition)
        st.markdown(f"**Period check:** {c.period_note or '—'}")
        for label, mv in (("Previous period", c.earlier), ("Latest period", c.later)):
            st.markdown(f"**{label}**")
            if not mv.available:
                st.markdown(f"- `N/A` — {mv.missing_reason or 'not reported'}")
                continue
            st.markdown(f"- Derivation: {mv.derivation}")
            for p in mv.provenance:
                period = (
                    f"{p.start} → {p.end} ({p.duration_days}d, {p.duration_class})"
                    if p.start
                    else f"instant at {p.end}"
                )
                st.markdown(
                    f"  - `{p.taxonomy}:{p.concept}` · {period} · unit `{p.unit}` · "
                    f"form `{p.form}` · accession `{p.accession}` · filed `{p.filed}` · "
                    f"rule `{p.selection_rule}`"
                    + (f" · [source]({p.source_url})" if p.source_url else "")
                )
        for w in c.warnings:
            st.warning(w)


def evidence_card(chunk: EvidenceChunk, score: float | None = None) -> None:
    score_s = f" · BM25 score `{score:.2f}`" if score is not None else ""
    st.markdown(
        f"> {short_excerpt(chunk.text, 700)}\n\n"
        f"<small>— **{chunk.form}** period ending `{chunk.report_date}` · "
        f"{chunk.section_label} · accession `{chunk.accession}` · id `{chunk.chunk_id}`"
        f"{score_s} · [open filing]({chunk.source_url})</small>",
        unsafe_allow_html=True,
    )


def evidence_list(items: list[RetrievedEvidence]) -> None:
    if not items:
        st.info("No evidence retrieved for this side.")
        return
    for item in items:
        evidence_card(item.chunk, item.score)
        st.markdown("---")


def change_card(change: MaterialChange, result: AnalysisResult) -> None:
    icon, label = CLAIM_BADGE.get(change.claim_type, ("•", change.claim_type))
    origin = "Python-measured" if change.generated_by == "deterministic" else "AI-interpreted"
    strength = STRENGTH_COLOUR.get(change.evidence_strength, "")

    st.markdown(f"#### {change.topic_label or change.topic_id}")
    st.markdown(
        f"{icon} **{label}** · `{origin}` · change type `{change.classification}` · "
        f"evidence strength {strength} **{change.evidence_strength}**"
    )
    st.markdown(f"**Claim.** {change.claim}")
    if change.why_it_matters:
        st.markdown(f"**Why it may matter.** {change.why_it_matters}")

    if change.related_metric_ids:
        bits = []
        for mid in change.related_metric_ids:
            comp = result.comparison_by_id(mid)
            if comp:
                bits.append(f"`{mid}` {change_text(comp)}")
        if bits:
            st.markdown(f"🧮 **Deterministic financial change.** {'; '.join(bits)}")

    left, right = st.columns(2)
    with left:
        st.markdown("**Earlier evidence**")
        for cid in change.earlier_source_ids[:2]:
            chunk = result.chunk_by_id(cid)
            if chunk:
                evidence_card(chunk)
        if not change.earlier_source_ids:
            st.info("No earlier-period excerpt cited.")
    with right:
        st.markdown("**Later evidence**")
        for cid in change.later_source_ids[:2]:
            chunk = result.chunk_by_id(cid)
            if chunk:
                evidence_card(chunk)
        if not change.later_source_ids:
            st.info("No later-period excerpt cited.")

    st.warning(f"⚠️ **Caveat.** {change.caveat}")
    st.markdown("---")


def llm_status_badge(available: bool) -> None:
    if available:
        st.success("AI synthesis: **enabled**")
    else:
        st.info(
            "AI synthesis: **disabled** (no `ANTHROPIC_API_KEY`). "
            "The financial comparison, risk diff, evidence retrieval and Markdown brief all "
            "still work."
        )
