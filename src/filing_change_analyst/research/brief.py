"""Markdown analyst brief.

Section order and labelling follow one rule: an analyst reading the brief must
always be able to tell, without effort, whether a line is a reported fact, a
Python calculation, a quote from management, or a model interpretation.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ..analytics.metric_definitions import FREE_CASH_FLOW_DEFINITION
from ..formatting import (
    absolute_change_text,
    change_text,
    metric_value_text,
    short_excerpt,
    status_text,
)
from ..models import AnalysisResult, MetricComparison
from .change_detection import risk_change_summary

LABELS = {
    "verified_fact": "VERIFIED FACT",
    "calculated_change": "CALCULATED CHANGE",
    "management_statement": "MANAGEMENT STATEMENT",
    "interpretation": "AI INTERPRETATION",
    "caveat": "CAVEAT",
    "open_question": "OPEN QUESTION",
}


def _metric_row(c: MetricComparison) -> str:
    earlier = metric_value_text(c.earlier, c.kind)
    later = metric_value_text(c.later, c.kind)
    src = ", ".join(
        dict.fromkeys(p.concept for p in (c.later.provenance or c.earlier.provenance))
    ) or "—"
    flag = "" if c.status == "ok" else f" ⚠️ {status_text(c)}"
    return (
        f"| {c.label}{flag} | {earlier} | {later} | {absolute_change_text(c)} | "
        f"{change_text(c)} | `{src}` |"
    )


def build_markdown_brief(result: AnalysisResult) -> str:
    pair = result.pair
    e, l = pair.earlier, pair.later  # noqa: E741
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    out: list[str] = []

    out.append(f"# Filing change brief — {l.company_name} ({l.ticker})")
    out.append("")
    out.append(
        f"**{l.form} for the period ending {l.report_date}** compared with "
        f"**{e.form} for the period ending {e.report_date}**."
    )
    out.append("")
    out.append("| | Earlier filing | Latest filing |")
    out.append("|---|---|---|")
    out.append(f"| Form | {e.form} | {l.form} |")
    out.append(f"| Period ending | {e.report_date} | {l.report_date} |")
    out.append(f"| Filed | {e.filing_date} | {l.filing_date} |")
    out.append(f"| Accession | `{e.accession}` | `{l.accession}` |")
    out.append(f"| SEC source | [filing]({e.primary_document_url}) | [filing]({l.primary_document_url}) |")
    out.append("")
    out.append(
        f"_Generated {now} by the Evidence-First Filing Change Analyst. "
        f"AI synthesis: **{'enabled' if result.llm_used else 'disabled'}**. "
        "This is a research aid, not investment advice._"
    )
    out.append("")

    if not pair.comparability_ok:
        out.append("> ## ⛔ Period comparability failed")
        for n in pair.comparability_notes:
            out.append(f"> - {n}")
        out.append(">")
        out.append("> Financial comparisons below are suppressed or must not be relied on.")
        out.append("")

    # 1 — Executive change summary
    out.append("## 1. Executive change summary")
    out.append("")
    extras = result.brief_extras
    if extras and extras.executive_summary:
        for line in extras.executive_summary:
            out.append(f"- **[{LABELS['interpretation']}]** {line}")
    else:
        out.append(
            "_AI synthesis unavailable — the deterministic findings below stand on their own._"
        )
        for c in result.changes[:5]:
            out.append(f"- **[{LABELS.get(c.claim_type, c.claim_type.upper())}]** {c.claim}")
    out.append("")

    # 2 — Verified financial changes
    out.append("## 2. Verified financial changes")
    out.append("")
    out.append(
        "_Every value below is read from SEC XBRL facts and every change is computed in Python. "
        "Percentage changes apply to levels; ratio metrics move in percentage points (pp)._"
    )
    out.append("")
    out.append("| Metric | Previous period | Latest period | Absolute change | % / pp change | XBRL concept |")
    out.append("|---|---:|---:|---:|---:|---|")
    for c in result.comparisons:
        out.append(_metric_row(c))
    out.append("")
    out.append(f"**Free-cash-flow definition used:** {FREE_CASH_FLOW_DEFINITION}")
    out.append("")

    if result.restatements:
        out.append("### Restatement / reclassification flags")
        out.append("")
        for r in result.restatements:
            out.append(
                f"- **[{LABELS['verified_fact']}]** {r.label}: the prior period was first "
                f"reported at {r.as_originally_reported:,.0f} and appears as "
                f"{r.as_restated_in_later_filing:,.0f} in the newer filing "
                f"({r.relative_difference:.2f}% difference). {r.note}"
            )
        out.append("")

    # 3 — Management commentary changes
    out.append("## 3. Management commentary changes")
    out.append("")
    if not result.changes:
        out.append(
            "_No topic exceeded the materiality thresholds. This is reported rather than "
            "padded with immaterial wording differences._"
        )
    for c in result.changes:
        label = LABELS.get(c.claim_type, c.claim_type.upper())
        origin = "Python-measured" if c.generated_by == "deterministic" else "AI-interpreted"
        out.append(f"### {c.topic_label or c.topic_id}")
        out.append("")
        out.append(f"**[{label}]** ({origin}) {c.claim}")
        out.append("")
        out.append(
            f"- Change type: `{c.classification}` · Evidence strength: **{c.evidence_strength}**"
        )
        if c.why_it_matters:
            out.append(f"- Why it may matter: {c.why_it_matters}")
        if c.related_metric_ids:
            metric_bits = []
            for mid in c.related_metric_ids:
                comp = result.comparison_by_id(mid)
                if comp:
                    metric_bits.append(f"`{mid}` {change_text(comp)}")
            if metric_bits:
                out.append(f"- **[{LABELS['calculated_change']}]** {'; '.join(metric_bits)}")
        out.append("")
        for period, ids in (("Earlier", c.earlier_source_ids), ("Later", c.later_source_ids)):
            out.append(f"**{period} evidence**")
            out.append("")
            if not ids:
                out.append("> _(none cited)_")
            for cid in ids[:2]:
                chunk = result.chunk_by_id(cid)
                if chunk is None:
                    continue
                out.append(f"> {short_excerpt(chunk.text, 460)}")
                out.append(">")
                out.append(
                    f"> — {chunk.form} period ending {chunk.report_date}, {chunk.section_label}, "
                    f"accession `{chunk.accession}` · [source]({chunk.source_url}) · id `{cid}`"
                )
                out.append("")
        out.append(f"**[{LABELS['caveat']}]** {c.caveat}")
        out.append("")

    # 4 — Risk-factor changes
    out.append("## 4. Risk-factor changes")
    out.append("")
    rd = result.risk_delta
    if rd is None:
        out.append("_Risk-factor headings could not be extracted from one or both filings._")
    else:
        out.append(f"**[{LABELS['verified_fact']}]** {risk_change_summary(rd)}")
        out.append("")
        if rd.added:
            out.append("**New or substantially reworded risk headings in the latest filing**")
            out.append("")
            for h in rd.added:
                out.append(f"- {h}")
            out.append("")
        if rd.removed:
            out.append("**Risk headings present previously but not matched in the latest filing**")
            out.append("")
            for h in rd.removed:
                out.append(f"- {h}")
            out.append("")
        out.append(f"**[{LABELS['caveat']}]** {rd.note}")
    out.append("")

    # 5 / 6 — Bull and bear
    out.append("## 5. Bull considerations *(interpretation, not a recommendation)*")
    out.append("")
    if extras and extras.bull_considerations:
        for line in extras.bull_considerations:
            out.append(f"- **[{LABELS['interpretation']}]** {line}")
    else:
        out.append("_Not generated: AI synthesis is disabled or produced no valid output._")
    out.append("")

    out.append("## 6. Bear considerations *(interpretation, not a recommendation)*")
    out.append("")
    if extras and extras.bear_considerations:
        for line in extras.bear_considerations:
            out.append(f"- **[{LABELS['interpretation']}]** {line}")
    else:
        out.append("_Not generated: AI synthesis is disabled or produced no valid output._")
    out.append("")

    # 7 — Questions
    out.append("## 7. Questions for management")
    out.append("")
    if extras and extras.questions_for_management:
        for line in extras.questions_for_management:
            out.append(f"- **[{LABELS['open_question']}]** {line}")
    else:
        out.append(
            f"- **[{LABELS['open_question']}]** Which portion of the change in capital "
            "expenditure is attributable to each reportable segment? The filings do not "
            "disclose a segment-level capex split."
        )
        out.append(
            f"- **[{LABELS['open_question']}]** What depreciable-life assumptions underlie the "
            "current infrastructure build, and how sensitive are reported margins to them?"
        )
    out.append("")

    # 8 — Caveats
    out.append("## 8. Caveats and missing information")
    out.append("")
    standing = [
        "Values come from SEC XBRL company facts, not from re-parsing the financial statements; "
        "an untagged or unusually tagged concept shows as N/A rather than being estimated.",
        "Only Items 1, 1A, 7 and 7A are extracted and indexed. Financial-statement notes, "
        "exhibits and segment tables are not searchable in this prototype.",
        "Emphasis deltas are phrase-frequency measures normalised per 10,000 tokens. They "
        "indicate prominence, not meaning, and can move because a filing was reorganised.",
        "The year-over-year comparison uses each period as reported in its own filing. Where a "
        "restatement flag is shown, part of the change may be a reclassification.",
    ]
    if result.section_strategy:
        from ..sec.sections import section_confidence

        detail = ", ".join(
            f"{period} filing `{strategy}` ({section_confidence(strategy)} confidence)"
            for period, strategy in sorted(result.section_strategy.items())
        )
        standing.append(
            "Filing sections were located by heading convention — "
            f"{detail}. Filers do not agree on how they mark up item headings; the convention "
            "used is part of the provenance of every excerpt above."
        )
    for line in standing:
        out.append(f"- **[{LABELS['caveat']}]** {line}")
    if extras and extras.caveats:
        for line in extras.caveats:
            out.append(f"- **[{LABELS['caveat']}]** {line}")
    for w in result.warnings:
        out.append(f"- **[{LABELS['caveat']}]** {w}")
    for n in result.data_notes:
        out.append(f"- **[{LABELS['caveat']}]** {n}")
    out.append("")

    # 9 — Sources
    out.append("## 9. Sources")
    out.append("")
    out.append(f"- {e.company_name} {e.form}, period ending {e.report_date}, filed "
               f"{e.filing_date}, accession `{e.accession}` — {e.primary_document_url}")
    out.append(f"- {l.company_name} {l.form}, period ending {l.report_date}, filed "
               f"{l.filing_date}, accession `{l.accession}` — {l.primary_document_url}")
    out.append(f"- SEC XBRL company facts API — https://data.sec.gov/api/xbrl/companyfacts/CIK{int(l.cik):010d}.json")
    out.append("")
    cited_ids = {i for c in result.changes for i in c.earlier_source_ids + c.later_source_ids}
    if cited_ids:
        out.append("### Cited excerpt identifiers")
        out.append("")
        for cid in sorted(cited_ids):
            chunk = result.chunk_by_id(cid)
            if chunk:
                out.append(
                    f"- `{cid}` — {chunk.form} period ending {chunk.report_date}, "
                    f"{chunk.section_label}, accession `{chunk.accession}`"
                )
        out.append("")

    if result.llm_logs:
        out.append("### Model run log")
        out.append("")
        out.append("| Purpose | Model | Prompt version | Latency (ms) | In/Out tokens | OK |")
        out.append("|---|---|---|---:|---|---|")
        for r in result.llm_logs:
            tokens = f"{r.input_tokens or '—'}/{r.output_tokens or '—'}"
            out.append(
                f"| {r.purpose} | `{r.model}` | `{r.prompt_version}` | {r.latency_ms} | "
                f"{tokens} | {'yes' if r.ok else 'no — ' + r.error} |"
            )
        out.append("")

    return "\n".join(out).rstrip() + "\n"


def brief_filename(result: AnalysisResult) -> str:
    p = result.pair.later
    return f"{p.ticker}_{p.form.replace('/', '-')}_{p.report_date}_change_brief.md"
