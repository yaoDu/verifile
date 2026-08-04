"""Streamlit rendering helpers.

Two rules govern this module, and they pull in opposite directions:

1. **Filing text is never rendered as HTML.** Every excerpt, heading and
   model-generated claim goes through Streamlit's default *escaping* Markdown
   path, additionally passed through :func:`~..formatting.md_safe`.
2. **Our own chrome is rendered as HTML** — the metric grid, the emphasis
   chart, the context bar. Streamlit has no primitive for a diverging bar or a
   grouped numeric table, and the alternative is to show an analyst twenty-one
   undifferentiated rows of grey text.

The dividing line is the *origin* of the string. Anything interpolated into
markup in this module comes from our own constants (metric labels, topic
labels, section names) or from numbers we formatted ourselves, and is passed
through :func:`html.escape` regardless as defence in depth. Filing-derived
strings never reach those helpers.
"""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from ..analytics.period_matching import BASIS_LABELS, reported_basis
from ..formatting import (
    absolute_change_text,
    change_text,
    md_safe,
    metric_value_text,
    short_excerpt,
    status_text,
)
from ..models import (
    COMPARISON_BASIS_LABELS,
    AnalysisResult,
    EvidenceChunk,
    MaterialChange,
    MetricComparison,
    RetrievedEvidence,
    RiskFactorDelta,
)
from ..sec.filings import supported_bases
from . import theme

# Text only. Emoji render as full-colour glyphs that sit outside the palette and
# look like clip art next to monospace chips, and they carry no meaning the label
# does not already carry — the chip's colour does the signalling.
CLAIM_LABELS = {
    "verified_fact": "Verified fact",
    "calculated_change": "Calculated change",
    "management_statement": "Management statement",
    "interpretation": "AI interpretation",
    "caveat": "Caveat",
    "open_question": "Open question",
}

# Presentation-only grouping. An analyst reads a statement at a time; a flat
# alphabetical-ish list of twenty-one metrics forces them to do that sorting in
# their head. The unit column tells the reader what the group's bar scale means,
# since level metrics move in percent and ratio metrics in percentage points.
METRIC_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Income statement",
        (
            "revenue",
            "cost_of_revenue",
            "gross_profit",
            "operating_income",
            "net_income",
            "rnd_expense",
            "sgna_expense",
            "diluted_eps",
        ),
    ),
    (
        "Margins and intensity",
        (
            "gross_margin",
            "operating_margin",
            "net_margin",
            "capex_intensity",
            "rnd_intensity",
        ),
    ),
    ("Cash flow", ("operating_cash_flow", "capex", "free_cash_flow")),
    (
        "Balance sheet",
        (
            "cash_and_equivalents",
            "short_term_investments",
            "total_debt",
            "net_cash",
            "stockholders_equity",
        ),
    ),
)

_E = html.escape


def inject_theme() -> None:
    theme.inject()


def wordmark() -> None:
    """The product name, set as a wordmark rather than an emoji plus a title.

    The mark is a CSS diamond, so it takes the accent colour and the page's font
    rendering like everything else. A pasted emoji would be a third-party colour
    bitmap that ignores the palette and shifts between platforms.
    """
    theme.render(
        '<div class="fca-wordmark">'
        '<span class="fca-wordmark-mark"></span>'
        "<span>Verifile</span>"
        "</div>"
    )


# --------------------------------------------------------------------------- #
# Small shared pieces
# --------------------------------------------------------------------------- #


def section_heading(title: str, note: str = "") -> None:
    note_html = f'<div class="fca-sec-note">{_E(note)}</div>' if note else ""
    theme.render(
        f'<div class="fca-sec"><div class="fca-sec-title">{_E(title)}</div>{note_html}</div>'
    )


def direction_legend() -> None:
    """Colour encodes direction only.

    Financial UIs habitually paint "up" green and "down" red, which quietly
    asserts that rising capex or rising debt is good news. This app measures
    changes and refuses to grade them, so the legend says so out loud.
    """
    theme.render(
        f'<div class="fca-legend">'
        f'<span><span class="sw" style="background:{theme.UP}"></span>Increased</span>'
        f'<span><span class="sw" style="background:{theme.DOWN}"></span>Decreased</span>'
        f"<span>Bars are scaled within each group. Colour shows the direction of a "
        f"change, not whether it is favourable.</span>"
        f"</div>"
    )


def _signed_change(c: MetricComparison) -> float | None:
    """The number the bar encodes: percent for levels, percentage points for ratios."""
    if c.status != "ok":
        return None
    return c.point_change if c.kind == "ratio" else c.percent_change


CLIP_RATIO = 8.0


def _bar_scale(magnitudes: list[float]) -> float:
    """Pick a bar scale that a single outlier cannot flatten.

    A metric that moves +400% while everything else moves single digits would,
    on a max-scaled axis, render every other row as an invisible stub. Where the
    largest magnitude is more than ``CLIP_RATIO`` times the median the axis is
    clipped and over-scale bars are marked with a ``›``.

    The threshold is deliberately high. Clipping trades away truthful
    proportions for legibility, and on a chart whose entire purpose is showing
    which numbers moved most, that is a bad trade unless the alternative is
    genuinely unreadable. At 4× it fired on ordinary filings — a margin group
    where one ratio moved 12 pp and the rest moved 1 pp is normal, not
    pathological — and made a 12 pp move look the same size as a 4 pp one.
    """
    mags = sorted(m for m in magnitudes if m is not None)
    if not mags:
        return 1.0
    top, median = mags[-1], mags[len(mags) // 2]
    if median > 0 and top > CLIP_RATIO * median:
        return max(CLIP_RATIO * median, 1.0)
    return max(top, 1.0)


def _bar_cell(value: float | None, scale: float, row: int = 0) -> str:
    """One diverging bar. ``row`` staggers the grow-in so the column reads as a
    chart being drawn rather than as everything appearing at once."""
    if value is None:
        return '<td class="fca-bar"></td>'
    mag = abs(value)
    clipped = mag > scale
    width = 50.0 if clipped else (mag / scale) * 50.0
    width = max(width, 0.9)
    side = "up" if value > 0 else "down"
    if value > 0:
        pos = f"left:50%;width:{width:.2f}%"
        clip = '<span class="fca-bar-clip" style="right:-0.85rem">›</span>' if clipped else ""
    else:
        pos = f"left:{50 - width:.2f}%;width:{width:.2f}%"
        clip = '<span class="fca-bar-clip" style="left:-0.85rem">‹</span>' if clipped else ""
    delay = f"animation-delay:{min(row, 24) * 32}ms"
    return (
        f'<td class="fca-bar"><div class="fca-bar-track">'
        f'<div class="fca-bar-fill {side}" style="{pos};{delay}"></div>{clip}'
        f"</div></td>"
    )


# --------------------------------------------------------------------------- #
# Filing context
# --------------------------------------------------------------------------- #


def company_header(result: AnalysisResult) -> None:
    """Company name, ticker and the run's mode chips on one line.

    This line and the context bar below it replaced four stacked strips —
    company name, context bar, an extraction-strategy caption and a mode banner
    — that pushed the analysis a screenful down. The chips carry the two facts
    that were previously prose: whether a model touched the findings, and how
    confidently the filing's sections were located.

    ``company_name`` comes from EDGAR's submissions metadata rather than from
    this repository, so it is escaped like any other third-party string before
    reaching :func:`theme.render`.
    """
    later = result.pair.later
    chips = [f'<span class="fca-chip">{_E(later.form)}</span>']
    if result.llm_used:
        chips.append('<span class="fca-chip k">AI interpretation</span>')
    else:
        chips.append('<span class="fca-chip">Deterministic only</span>')

    confidence = _extraction_confidence(result)
    if confidence:
        cls = {"high": "s-high", "moderate": "s-moderate", "low": "s-low"}[confidence]
        chips.append(f'<span class="fca-chip {cls}">{_E(confidence)}-confidence sections</span>')

    theme.render(
        f'<div class="fca-rise fca-result-head">'
        f'<div class="fca-result-name">{_E(later.company_name)} '
        f'<span class="tk">({_E(later.ticker)})</span></div>'
        f'<div class="fca-chips">{"".join(chips)}</div>'
        f"</div>"
    )


def _extraction_confidence(result: AnalysisResult) -> str | None:
    """The weaker of the two filings' section-extraction confidences."""
    if not result.section_strategy:
        return None
    from ..sec.sections import section_confidence

    ranked = {"low": 0, "moderate": 1, "high": 2}
    levels = [section_confidence(s) for s in result.section_strategy.values() if s]
    if not levels:
        return None
    return min(levels, key=lambda level: ranked.get(level, 0))


def _reporting_basis(result: AnalysisResult) -> str | None:
    """The reporting length the displayed figures actually use.

    A 10-Q reports the quarter and the year-to-date figure against the same
    period end, so without this the reader cannot tell which one is on screen.
    """
    return BASIS_LABELS.get(reported_basis(result.comparisons) or "")


def filing_context_bar(result: AnalysisResult) -> None:
    """Both filings' identity in one horizontal band.

    This replaced two stacked bullet lists that consumed roughly a third of the
    first screen. The metadata is provenance an analyst checks once and then
    ignores, so it earns one dense row above the analysis, not a section.
    """
    pair = result.pair
    e, l = pair.earlier, pair.later  # noqa: E741

    def card(label: str, f, kind: str) -> str:  # noqa: ANN001 — Filing, kept local
        """One filing as a block led by the part that differs.

        ``%b %Y`` is the deliberate choice for the headline. Two 10-Ks a year
        apart differ in the year; two 10-Qs differ in the month; a full ISO date
        differs in neither until you reach the fourth character. Month-and-year
        makes the distinction visible at a glance in both cases, and the exact
        dates stay directly underneath for anyone who needs them.
        """
        return (
            f'<div class="fca-cmp-card {kind}">'
            f'<div class="fca-cmp-k">{_E(label)}</div>'
            f'<div class="fca-cmp-period">{_E(f.report_date.strftime("%b %Y"))}</div>'
            f'<div class="fca-cmp-meta">'
            f'<span class="lbl">Period ended</span> {_E(f.report_date.isoformat())}<br>'
            f'<span class="lbl">Filed</span> {_E(f.filing_date.isoformat())}'
            f"</div>"
            f'<div class="fca-cmp-acc">'
            f'<a href="{_E(f.primary_document_url)}" target="_blank" '
            f'title="Open this filing on SEC EDGAR">{_E(f.accession)} ↗</a></div>'
            f"</div>"
        )

    months = round((l.report_date - e.report_date).days / 30.44)
    length = _reporting_basis(result)
    length_chip = (
        f'<span class="fca-cmp-gap" title="Reporting length of every figure below; '
        f'both periods use the same basis">{_E(length)}</span>'
        if length
        else ""
    )
    # Which two filings were paired, as distinct from the length of each period.
    # Named only when the form offers a choice, so a 10-K is not labelled with a
    # decision it never had.
    comparison_chip = (
        f'<span class="fca-cmp-gap" title="Which two periods are paired">'
        f"{_E(COMPARISON_BASIS_LABELS[pair.basis])}</span>"
        if len(supported_bases(l.form)) > 1
        else ""
    )
    theme.render(
        f'<div class="fca-cmp">'
        f'<div class="fca-cmp-head">'
        f'<span class="fca-cmp-form">{_E(l.form)}</span>'
        f"{comparison_chip}"
        f"{length_chip}"
        f'<span class="fca-cmp-gap">{months} months apart</span>'
        f"</div>"
        f'<div class="fca-cmp-body">'
        f"{card('Previous filing', e, 'prev')}"
        f'<div class="fca-cmp-join"><span class="fca-cmp-arrow">→</span></div>'
        f"{card('Current filing', l, 'curr')}"
        f"</div></div>"
    )

    if not pair.comparability_ok:
        st.error(
            "**Period comparability check failed — figures below are suppressed.**\n\n"
            + "\n".join(f"- {md_safe(n)}" for n in pair.comparability_notes)
        )
    elif pair.comparability_notes:
        st.warning("\n".join(f"- {md_safe(n)}" for n in pair.comparability_notes))


def extraction_strategy_note(result: AnalysisResult) -> None:
    """Warn only when the section extraction is actually weak.

    Filers disagree on markup, so the strategy that worked is provenance rather
    than an implementation detail — but on a healthy filing it is a line of
    reassurance printed above every analysis. The confidence chip in the header
    now carries the healthy case, and the full detail stays one click away in
    the per-metric provenance. What remains here is the case that genuinely
    changes how an analyst should read the excerpts.
    """
    if not result.section_strategy:
        return
    from ..sec.sections import section_confidence

    bits = [
        f"{period}: `{strategy}` ({section_confidence(strategy)} confidence)"
        for period in ("earlier", "later")
        if (strategy := result.section_strategy.get(period))
    ]
    if not bits:
        return
    line = "Section headings located by — " + " · ".join(bits)
    if any("title_only" in b for b in bits):
        st.warning(
            f"{line}. The `title_only` strategy anchors on bare section titles because the "
            "filing body carries no item numbers; a cross-reference to a section title can be "
            "mistaken for the section itself, so treat these excerpts with extra care."
        )
    elif any("none" in b for b in bits):
        st.error(f"{line}. No text evidence is available for that period.")


# --------------------------------------------------------------------------- #
# Financial snapshot
# --------------------------------------------------------------------------- #


def headline_movers(result: AnalysisResult) -> None:
    """The three largest level moves plus the largest ratio move.

    Levels are ranked among themselves by percent change and ratios among
    themselves by percentage points; the two pools are never sorted against each
    other, because "+12 pp of margin" and "+12% of revenue" are not the same
    size of event and a combined ranking would imply they are.
    """
    usable = [c for c in result.comparisons if c.status == "ok"]
    levels = [c for c in usable if c.kind != "ratio" and c.percent_change is not None]
    ratios = [c for c in usable if c.kind == "ratio" and c.point_change is not None]
    levels.sort(key=lambda c: -abs(c.percent_change or 0))
    ratios.sort(key=lambda c: -abs(c.point_change or 0))

    picks = levels[:3] + ratios[:1]
    if not picks:
        return

    cards = []
    for i, c in enumerate(picks):
        val = _signed_change(c)
        side = "up" if (val or 0) > 0 else "down"
        # Stagger so the row assembles left to right instead of snapping in.
        delay = f"animation-delay:{i * 70}ms"
        cards.append(
            f'<div class="fca-mover {side} fca-rise" style="{delay}">'
            f'<div class="fca-mover-k">{_E(c.label)}</div>'
            f'<div class="fca-mover-v {side}">{"▲" if side == "up" else "▼"} '
            f"{_E(change_text(c).lstrip('+'))}</div>"
            f'<div class="fca-mover-sub">{_E(metric_value_text(c.earlier, c.kind))}'
            f'<span class="arw">→</span>{_E(metric_value_text(c.later, c.kind))}</div>'
            f"</div>"
        )
    theme.render(f'<div class="fca-movers">{"".join(cards)}</div>')


def metric_grid(result: AnalysisResult) -> None:
    """The metric matrix, grouped by statement with an inline diverging bar.

    The bar is the point of this component. Percentages in a column of grey text
    all look alike; a bar with a zero axis lets an analyst find the two rows
    worth reading before parsing a single digit.
    """
    by_id = {c.metric_id: c for c in result.comparisons}
    seen: set[str] = set()
    groups: list[tuple[str, list[MetricComparison]]] = []
    for name, ids in METRIC_GROUPS:
        members = [by_id[i] for i in ids if i in by_id]
        seen.update(c.metric_id for c in members)
        if members:
            groups.append((name, members))
    rest = [c for c in result.comparisons if c.metric_id not in seen]
    if rest:
        groups.append(("Other", rest))

    head = (
        "<thead><tr>"
        '<th class="l">Metric</th><th>Previous</th><th>Latest</th>'
        '<th>Absolute change</th><th class="c">Change</th><th>&nbsp;</th>'
        "</tr></thead>"
    )

    body: list[str] = []
    row_index = 0
    for name, members in groups:
        vals = [_signed_change(c) for c in members]
        scale = _bar_scale([abs(v) for v in vals if v is not None])
        unit = "pp" if all(c.kind == "ratio" for c in members) else "%"
        body.append(
            f'<tr class="fca-grp"><td class="l" colspan="4"><span class="fca-grp-l">{_E(name)}'
            f'</span></td><td colspan="2" class="l"><span class="fca-grp-scale">'
            f"bar scale ±{scale:,.0f} {unit}</span></td></tr>"
        )
        for c in members:
            val = _signed_change(c)
            if c.status != "ok":
                body.append(
                    f'<tr><td class="l dim">{_E(c.label)}</td>'
                    f'<td class="num dim">{_E(metric_value_text(c.earlier, c.kind))}</td>'
                    f'<td class="num dim">{_E(metric_value_text(c.later, c.kind))}</td>'
                    f'<td class="num dim">—</td>'
                    f'<td class="fca-chg na">{_E(status_text(c))}</td>'
                    f'<td class="fca-bar"></td></tr>'
                )
                row_index += 1
                continue
            side = "up" if (val or 0) > 0 else "down"
            body.append(
                f'<tr><td class="l">{_E(c.label)}</td>'
                f'<td class="num">{_E(metric_value_text(c.earlier, c.kind))}</td>'
                f'<td class="num">{_E(metric_value_text(c.later, c.kind))}</td>'
                f'<td class="num">{_E(absolute_change_text(c))}</td>'
                f'<td class="fca-chg {side}">{_E(change_text(c))}</td>'
                f"{_bar_cell(val, scale, row_index)}</tr>"
            )
            row_index += 1

    theme.render(f'<div class="fca-grid"><table>{head}<tbody>{"".join(body)}</tbody></table></div>')


def metrics_table(result: AnalysisResult) -> pd.DataFrame:
    """Flat tabular form, kept for sorting and copy-out alongside the visual grid."""
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
    # The label leads with the metric name: twenty-one rows all beginning
    # "Source and provenance —" are impossible to scan.
    with st.expander(f"{c.label}  ·  source and provenance"):
        st.caption(c.definition)
        st.markdown(f"**Period check:** {md_safe(c.period_note) or '—'}")
        for label, mv in (("Previous period", c.earlier), ("Latest period", c.later)):
            st.markdown(f"**{label}**")
            if not mv.available:
                st.markdown(f"- `N/A` — {md_safe(mv.missing_reason or 'not reported')}")
                continue
            st.markdown(f"- Derivation: {md_safe(mv.derivation)}")
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
            st.warning(md_safe(w))


# --------------------------------------------------------------------------- #
# Topic emphasis
# --------------------------------------------------------------------------- #


def emphasis_chart(result: AnalysisResult, threshold: float = 0.0) -> None:
    """Every topic probe as a diverging bar, sorted by magnitude.

    This dataset is the most chart-shaped thing the pipeline produces — a signed
    delta over a fixed set of labels — and it was previously a list of sentences.
    Probes that did not clear the materiality threshold are drawn at reduced
    opacity rather than hidden, so the reader can see what was considered and
    rejected, not only what survived.
    """
    topics = sorted(result.topics, key=lambda t: -abs(t.emphasis_delta))
    if not topics:
        st.info("No topic probes ran for this filing pair.")
        return
    scale = _bar_scale([abs(t.emphasis_delta) for t in topics])

    rows = []
    for i, t in enumerate(topics):
        d = t.emphasis_delta
        mag = abs(d)
        if mag < 0.05:
            side, cls = "flat", "flat"
        else:
            side = "up" if d > 0 else "down"
            cls = side
        clipped = mag > scale
        width = 50.0 if clipped else (mag / scale) * 50.0
        width = max(width, 0.6)
        pos = (
            f"left:50%;width:{width:.2f}%"
            if d > 0
            else f"left:{50 - width:.2f}%;width:{width:.2f}%"
        )
        sub = " thr" if mag < threshold else ""
        delay = f"animation-delay:{min(i, 24) * 36}ms"
        fill = (
            f'<div class="fca-emph-fill {side}{sub}" style="{pos};{delay}"></div>'
            if side != "flat"
            else ""
        )
        rows.append(
            f'<div class="fca-emph-row">'
            f'<div class="fca-emph-l" title="{_E(t.topic_label)}">{_E(t.topic_label)}</div>'
            f'<div class="fca-emph-track">{fill}</div>'
            f'<div class="fca-emph-v {cls}">{d:+.1f}</div>'
            f"</div>"
        )
    theme.render(f'<div class="fca-emph">{"".join(rows)}</div>')
    st.caption(
        f"Mentions per 10,000 tokens, later filing minus earlier. Bar scale ±{scale:,.1f}. "
        "Faded bars fall below the materiality threshold and raise no change above."
    )


# --------------------------------------------------------------------------- #
# Risk factors
# --------------------------------------------------------------------------- #


def risk_composition(rd: RiskFactorDelta) -> None:
    """Added / retained / removed as one proportional bar.

    Three separate metric tiles reading 4, 2 and 29 make the reader compute the
    proportion themselves. A single stacked bar shows immediately that this is a
    largely stable risk section with a small amount of turnover.
    """
    a, r, k = len(rd.added), len(rd.removed), len(rd.retained)
    total = max(a + r + k, 1)
    segs = []
    for i, (count, cls) in enumerate(((a, "add"), (k, "keep"), (r, "rem"))):
        if not count:
            continue
        pct = count / total * 100
        text = str(count) if pct > 4 else ""
        segs.append(
            f'<div class="fca-risk-seg {cls}" '
            f'style="width:{pct:.2f}%;animation-delay:{i * 90}ms">{text}</div>'
        )
    theme.render(
        f'<div class="fca-risk-bar">{"".join(segs)}</div>'
        f'<div class="fca-risk-key">'
        f'<span><span class="sw" style="background:{theme.UP}"></span>'
        f"<b>{a}</b> new or substantially reworded</span>"
        f'<span><span class="sw" style="background:rgba(255,255,255,0.16)"></span>'
        f"<b>{k}</b> retained</span>"
        f'<span><span class="sw" style="background:{theme.DOWN}"></span>'
        f"<b>{r}</b> no longer present</span>"
        f"</div>"
    )


# --------------------------------------------------------------------------- #
# Evidence
# --------------------------------------------------------------------------- #


def evidence_side_label(title: str, when: str) -> None:
    theme.render(f'<div class="fca-side">{_E(title)} <span class="dt">{_E(when)}</span></div>')


def evidence_card(chunk: EvidenceChunk, score: float | None = None, limit: int = 420) -> None:
    """One excerpt: a period marker strip, the quote, then its provenance.

    The marker strip is our own metadata and goes through :func:`theme.render`.
    The excerpt does not, and must not. It is rendered through Streamlit's
    default *escaping* Markdown path and never with ``unsafe_allow_html``: this
    matters more than it looks, because ``html_to_text`` strips tags but
    BeautifulSoup's ``get_text`` also *decodes HTML entities*, so a filing that
    legitimately writes ``&lt;img src=x onerror=...&gt;`` — a 10-K quoting
    markup, or using ``&lt;`` in a formula — yields a raw ``<img …>`` in the
    extracted text. Rendering that as HTML is exactly what this project promises
    not to do. Splitting the row into three calls is what lets the strip carry
    markup while the filing text stays inert.

    ``md_safe`` is layered on top so dollar amounts survive Streamlit's LaTeX
    handling intact.
    """
    period = "later" if chunk.period == "later" else "earlier"
    caption = "Latest filing" if period == "later" else "Earlier filing"
    theme.render(
        f'<div class="fca-ev">'
        f'<span class="fca-ev-dot {period}"></span>'
        f'<span class="fca-ev-k {period}">{_E(caption)}</span>'
        f'<span class="fca-ev-date">{_E(chunk.report_date.isoformat())}</span>'
        f'<span class="fca-ev-sec">{_E(chunk.section_label)}</span>'
        f'<span class="fca-ev-rule"></span>'
        f"</div>"
    )
    st.markdown(f"> {md_safe(short_excerpt(chunk.text, limit))}")
    score_s = f" · BM25 `{score:.2f}`" if score is not None else ""
    st.caption(
        f"{chunk.form} · accession `{chunk.accession}` · `{chunk.chunk_id}`"
        f"{score_s} · [open filing]({chunk.source_url})"
    )


def evidence_timeline(chunks: list[tuple[EvidenceChunk, float | None]], limit: int = 420) -> None:
    """Excerpts stacked oldest first, so before/after reads as vertical order."""
    if not chunks:
        st.caption("No excerpt cited.")
        return
    ordered = sorted(chunks, key=lambda pair: (pair[0].period != "earlier", pair[0].report_date))
    for chunk, score in ordered:
        evidence_card(chunk, score, limit=limit)


def evidence_list(items: list[RetrievedEvidence]) -> None:
    if not items:
        st.info("No evidence retrieved.")
        return
    evidence_timeline([(i.chunk, i.score) for i in items], limit=520)


def heading_ledger(added: list[str], removed: list[str]) -> None:
    """Added and removed headings as one typed list rather than two columns.

    Two columns looked orderly only when the sets happened to be the same
    length. With four new headings beside two removed — or twelve beside one —
    the shorter column left a block of dead space, and the reader still had to
    merge the two lists mentally to see the period's net movement. One ledger
    marked ``+``/``−`` scales to any split and reads in a single pass.

    The heading text is filing-derived, so it stays on the escaped Markdown path
    and never reaches :func:`theme.render`. Only the ``+``/``−`` marker is
    coloured, and it is coloured with Streamlit's own ``:colour[…]`` directive
    rather than injected markup, so the whole row needs no raw HTML at all.
    """
    if not added and not removed:
        st.caption("No heading-level changes detected.")
        return
    for text in added:
        st.markdown(f":green[**+**] &nbsp;{md_safe(text)}")
    for text in removed:
        st.markdown(f":blue[**−**] &nbsp;{md_safe(text)}")


def change_card(change: MaterialChange, result: AnalysisResult) -> None:
    label = CLAIM_LABELS.get(change.claim_type, change.claim_type.replace("_", " "))
    origin = "Python-measured" if change.generated_by == "deterministic" else "AI-interpreted"
    direction = {
        "expanded_emphasis": "up",
        "new_disclosure": "up",
        "reduced_emphasis": "down",
        "removed_disclosure": "down",
    }.get(change.classification, "")

    # One bordered container per change, so the claim, its evidence and its
    # caveat read as a single unit. Previously only the title block was boxed and
    # everything below it spilled onto the page background, which made a run of
    # changes look like one undifferentiated column of text.
    with st.container(border=True):
        theme.render(
            f'<div class="fca-card-head {direction}">'
            f'<div class="fca-card-t">{_E(change.topic_label or change.topic_id)}</div>'
            f'<div class="fca-chips">'
            f'<span class="fca-chip k">{_E(label)}</span>'
            f'<span class="fca-chip">{_E(origin)}</span>'
            f'<span class="fca-chip">{_E(change.classification.replace("_", " "))}</span>'
            f'<span class="fca-chip s-{_E(change.evidence_strength)}">'
            f"{_E(change.evidence_strength)} evidence</span>"
            f"</div></div>"
        )

        st.markdown(f"**Claim.** {md_safe(change.claim)}")
        if change.why_it_matters:
            st.markdown(f"**Why it may matter.** {md_safe(change.why_it_matters)}")

        if change.related_metric_ids:
            bits = []
            for mid in change.related_metric_ids:
                comp = result.comparison_by_id(mid)
                if comp:
                    bits.append(f"`{mid}` {change_text(comp)}")
            if bits:
                st.markdown(f"**Deterministic financial change.** {'; '.join(bits)}")

        # One excerpt per period, stacked oldest first. Two per side in two
        # columns produced four ragged blocks of ~45-character lines; the claim
        # above already says what changed, so the evidence only has to let the
        # reader verify it against each filing.
        cited = [
            (chunk, None)
            for cid in (change.earlier_source_ids[:1] + change.later_source_ids[:1])
            if (chunk := result.chunk_by_id(cid)) is not None
        ]
        if cited:
            evidence_timeline(cited)
        else:
            st.caption("No excerpt cited for either period.")

        st.warning(f"**Caveat.** {md_safe(change.caveat)}")


def landing() -> None:
    """The pre-analysis screen.

    Previously a single block of prose that buried the one instruction a first
    visitor needs — pick a ticker and press the button — under a numbered
    description of the pipeline. The pipeline description is still here, because
    an evidence-first tool should explain its method, but it now sits below the
    call to action in scannable cards instead of ahead of it.
    """
    theme.render(
        '<div class="fca-rise" style="padding:2rem 0 0.4rem">'
        '<div class="fca-eyebrow" style="margin-bottom:0.85rem">'
        '<span class="fca-dot"></span>SEC 10-K and 10-Q change analysis</div>'
        '<div class="fca-hero-h">What <em>actually</em> changed since the last filing?</div>'
        '<div class="fca-hero-p">'
        "Every figure is calculated in Python from SEC XBRL facts. Every claim carries an "
        "excerpt from both filings and a link to the source. The model interprets measured "
        "signals — it is never asked to produce a number."
        "</div></div>"
    )
    theme.render(
        '<div class="fca-cta fca-rise" style="animation-delay:90ms">'
        "Enter a ticker in the bar above and press <b>Compare</b>. "
        "The default is a Microsoft 10-K year-over-year comparison."
        "</div>"
    )

    steps = (
        (
            "01",
            "Select and check",
            "SEC EDGAR submissions pick the two most recent comparable "
            "filings. Structural comparability checks run before any arithmetic.",
        ),
        (
            "02",
            "Calculate",
            "Metrics come from SEC XBRL company facts and every change is "
            "computed in Python. Missing data stays missing rather than being estimated.",
        ),
        (
            "03",
            "Retrieve",
            "Items 1, 1A, 7 and 7A are extracted, chunked with full provenance "
            "and indexed with BM25.",
        ),
        (
            "04",
            "Measure",
            "Fixed topic probes retrieve matched earlier and later evidence and "
            "measure a normalised emphasis delta — citable with or without a model.",
        ),
        (
            "05",
            "Interpret",
            "With an API key present, the model reads those measured signals "
            "under strict citation, numeric-grounding and no-recommendation guardrails.",
        ),
        (
            "06",
            "Show the seams",
            "Extraction confidence, restatement flags and blocked metrics "
            "are surfaced on screen, not hidden.",
        ),
    )
    cards = "".join(
        f'<div class="fca-step" style="animation-delay:{140 + i * 60}ms">'
        f'<div class="fca-step-n">{n}</div>'
        f'<div class="fca-step-t">{_E(t)}</div>'
        f'<div class="fca-step-d">{_E(d)}</div>'
        f"</div>"
        for i, (n, t, d) in enumerate(steps)
    )
    theme.render(f'<div class="fca-steps">{cards}</div>')

    theme.render(
        '<div style="font-size:0.83rem;color:var(--ink-muted);line-height:1.62;max-width:82ch">'
        "<b>Suggested tickers.</b> Any US filer with a 10-K works, fetched live from EDGAR. "
        "<code>MSFT</code>, <code>AAPL</code>, <code>NVDA</code> and <code>PG</code> have their "
        "SEC responses pre-warmed in this deployment and return in a few seconds. "
        "<code>PG</code> is worth a look precisely because it is where the system is "
        "<i>weakest</i> — its 10-K carries no item numbers, so section extraction falls back to "
        "a low-confidence strategy and says so on screen."
        "</div>"
    )


def llm_status_badge(available: bool) -> None:
    if available:
        st.success("AI synthesis **enabled**")
    else:
        st.info(
            "AI synthesis **off** — no `API_KEY`. The financial comparison, risk diff, "
            "evidence retrieval and brief all still work."
        )
