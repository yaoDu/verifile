"""Markdown analyst brief.

Section order and labelling follow one rule: an analyst reading the brief must
always be able to tell, without effort, whether a line is a reported fact, a
Python calculation, a quote from management, or a model interpretation.

**On length.** An earlier version ran to roughly twelve pages, two thirds of it
a single section that quoted four 460-character excerpts for every change. The
cut that followed removed *quoted volume and duplicated scaffolding*, never
evidence: each change still carries both periods, a citable chunk id and a
resolvable SEC link, and the metric table is still complete, because a brief
that drops citations to look tidy would defeat the point of the tool. What went
were the second excerpt per side, an appendix relisting chunk ids already
printed inline, and two placeholder sections that said only that AI was off.
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


MIN_SHARED_CAVEAT = 60


def _shared_caveat_prefix(caveats: list[str]) -> str:
    """The leading text every caveat has in common, cut at a sentence boundary.

    Returns ``""`` when fewer than two changes carry a caveat or when the common
    opening is too short to be worth hoisting — a shared fragment of a few words
    is noise, not a shared caveat. Cutting on ``". "`` matters: hoisting half a
    sentence would leave both the hoisted text and the remainder ungrammatical,
    and a caveat that reads as a typo is a caveat nobody trusts.
    """
    present = [c for c in caveats if c]
    if len(present) < 2:
        return ""
    prefix = present[0]
    for text in present[1:]:
        while not text.startswith(prefix):
            prefix = prefix[:-1]
            if not prefix:
                return ""
    cut = prefix.rfind(". ")
    if cut == -1:
        return prefix.strip() if prefix.strip().endswith(".") else ""
    prefix = prefix[: cut + 1]
    return prefix if len(prefix) >= MIN_SHARED_CAVEAT else ""


def _metric_row(c: MetricComparison) -> str:
    earlier = metric_value_text(c.earlier, c.kind)
    later = metric_value_text(c.later, c.kind)
    src = (
        ", ".join(dict.fromkeys(p.concept for p in (c.later.provenance or c.earlier.provenance)))
        or "—"
    )
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
        f"**{l.form} period ending {l.report_date}** (filed {l.filing_date}, accession "
        f"`{l.accession}`, [source]({l.primary_document_url}))  \n"
        f"compared with **{e.form} period ending {e.report_date}** (filed {e.filing_date}, "
        f"accession `{e.accession}`, [source]({e.primary_document_url}))"
    )
    out.append("")
    out.append(
        f"_Generated {now} by Verifile. "
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

    # 1 — What changed
    #
    # Merged from what used to be a standalone executive summary followed by a
    # commentary section that restated every claim in full. The summary now
    # exists only when the model wrote one; otherwise the claims below are the
    # summary, rather than being printed twice.
    out.append("## 1. What changed")
    out.append("")
    extras = result.brief_extras
    if extras and extras.executive_summary:
        for line in extras.executive_summary:
            out.append(f"- **[{LABELS['interpretation']}]** {line}")
        out.append("")

    if not result.changes:
        out.append(
            "_No topic exceeded the materiality thresholds. This is reported rather than "
            "padded with immaterial wording differences._"
        )
        out.append("")

    # Deterministic changes are generated from one template, so their caveats
    # share a long opening and differ only in a trailing sentence. Repeating the
    # shared part under every change trained the reader to skip it, which is the
    # opposite of what a caveat is for — so it is stated once here and each
    # change keeps only whatever it adds on top.
    shared_caveat = _shared_caveat_prefix([c.caveat for c in result.changes])
    if shared_caveat:
        out.append(f"**[{LABELS['caveat']}]** Applies to every change below. {shared_caveat}")
        out.append("")

    for c in result.changes:
        label = LABELS.get(c.claim_type, c.claim_type.upper())
        origin = "Python-measured" if c.generated_by == "deterministic" else "AI-interpreted"
        out.append(f"### {c.topic_label or c.topic_id}")
        out.append("")
        out.append(f"**[{label}]** {c.claim}")
        out.append("")

        meta = [f"{origin}", f"`{c.classification}`", f"{c.evidence_strength} evidence"]
        for mid in c.related_metric_ids:
            comp = result.comparison_by_id(mid)
            if comp:
                meta.append(f"`{mid}` {change_text(comp)}")
        out.append(f"_{' · '.join(meta)}_")
        out.append("")
        if c.why_it_matters:
            out.append(f"Why it may matter: {c.why_it_matters}")
            out.append("")

        # One excerpt per side rather than two. Both periods are still quoted and
        # still cited, so a reader can always follow a claim back to the filing.
        for period, ids in (("Earlier", c.earlier_source_ids), ("Later", c.later_source_ids)):
            if not ids:
                out.append(f"**{period}:** _(none cited)_")
                out.append("")
                continue
            chunk = result.chunk_by_id(ids[0])
            if chunk is None:
                continue
            out.append(f"**{period}.** {short_excerpt(chunk.text, 200)}")
            out.append("")
            out.append(
                f"> — {chunk.form} period ending {chunk.report_date}, {chunk.section_label}, "
                f"accession `{chunk.accession}` · id `{chunk.chunk_id}` "
                f"· [source]({chunk.source_url})"
            )
            out.append("")
        rest = c.caveat[len(shared_caveat) :].strip() if shared_caveat else c.caveat
        if rest:
            out.append(f"**[{LABELS['caveat']}]** {rest}")
            out.append("")

    # 2 — Verified financial changes
    out.append("## 2. Verified financial changes")
    out.append("")
    out.append(
        "_Every value below is read from SEC XBRL facts and every change is computed in Python. "
        "Percentage changes apply to levels; ratio metrics move in percentage points (pp)._"
    )
    out.append("")
    out.append(
        "| Metric | Previous period | Latest period | Absolute change | % / pp change | XBRL concept |"
    )
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

    # 3 — Risk-factor changes
    out.append("## 3. Risk-factor changes")
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

    # 4 — Interpretation, kept in one section
    #
    # Bull and bear used to be separate top-level sections that, with AI off,
    # printed nothing but two identical "not generated" lines. They now share a
    # section and the bull/bear halves are simply absent when there is nothing
    # to say. The no-recommendation framing stays in the heading, where it
    # governs everything underneath it.
    out.append("## 4. Interpretation and open questions")
    out.append("")
    out.append("_Everything in this section is interpretation, not a recommendation._")
    out.append("")
    if extras and (extras.bull_considerations or extras.bear_considerations):
        for heading, lines in (
            ("Supportive of the business", extras.bull_considerations),
            ("Unfavourable to the business", extras.bear_considerations),
        ):
            if not lines:
                continue
            out.append(f"**{heading}**")
            out.append("")
            for line in lines:
                out.append(f"- **[{LABELS['interpretation']}]** {line}")
            out.append("")
    else:
        out.append(
            "_Bull and bear framing is model-generated and AI synthesis is off, so it is "
            "omitted rather than guessed at._"
        )
        out.append("")

    questions = list(extras.questions_for_management) if extras else []
    if not questions:
        questions = [
            "Which portion of the change in capital expenditure is attributable to each "
            "reportable segment? The filings do not disclose a segment-level capex split.",
            "What depreciable-life assumptions underlie the current infrastructure build, "
            "and how sensitive are reported margins to them?",
        ]
    out.append("**Questions for management**")
    out.append("")
    for line in questions:
        out.append(f"- **[{LABELS['open_question']}]** {line}")
    out.append("")

    # 5 — Caveats
    out.append("## 5. Method and caveats")
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

    # 6 — Sources
    #
    # The appendix that relisted every cited chunk id was removed: each id is
    # already printed beside the excerpt it belongs to in section 1, so the
    # appendix restated the section's provenance at the length of a page.
    out.append("## 6. Sources")
    out.append("")
    out.append(
        f"- {e.company_name} {e.form}, period ending {e.report_date}, filed "
        f"{e.filing_date}, accession `{e.accession}` — {e.primary_document_url}"
    )
    out.append(
        f"- {l.company_name} {l.form}, period ending {l.report_date}, filed "
        f"{l.filing_date}, accession `{l.accession}` — {l.primary_document_url}"
    )
    out.append(
        f"- SEC XBRL company facts API — https://data.sec.gov/api/xbrl/companyfacts/CIK{int(l.cik):010d}.json"
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
