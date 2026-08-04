"""Verifile — Streamlit interface.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:  # allow `streamlit run app.py` without installing
    sys.path.insert(0, str(SRC))

import streamlit as st  # noqa: E402


def _bridge_secrets_to_env() -> None:
    """Copy Streamlit secrets into the environment before settings are built.

    Hosted deployments have no ``.env``. An existing environment variable wins,
    so a local ``.env`` still takes precedence. Values are never logged.
    """
    try:
        items = list(st.secrets.items())
    except Exception:  # noqa: BLE001 — no secrets file configured; that is fine
        return
    for key, value in items:
        if key.isupper() and isinstance(value, str | int | float | bool):
            os.environ.setdefault(key, str(value))


_bridge_secrets_to_env()

from filing_change_analyst.analytics.metric_definitions import (  # noqa: E402
    FREE_CASH_FLOW_DEFINITION,
)
from filing_change_analyst.config import configure_logging, get_settings  # noqa: E402
from filing_change_analyst.formatting import (  # noqa: E402
    change_text,
    escape_dollars,
    md_safe,
)
from filing_change_analyst.pipeline import (  # noqa: E402
    apply_ai_synthesis,
    available_filings,
    pair_from_filings,
    run_analysis,
)
from filing_change_analyst.research.brief import brief_filename, build_markdown_brief  # noqa: E402
from filing_change_analyst.research.change_detection import risk_change_summary  # noqa: E402
from filing_change_analyst.research.qa import SUGGESTED_QUESTIONS, answer_question  # noqa: E402
from filing_change_analyst.sec.client import SecError  # noqa: E402
from filing_change_analyst.sec.filings import comparable_earlier_filing  # noqa: E402
from filing_change_analyst.services.cache import DiskCache  # noqa: E402
from filing_change_analyst.services.demo_cache import seed_demo_cache  # noqa: E402
from filing_change_analyst.services.llm import LlmClient  # noqa: E402
from filing_change_analyst.ui import components as ui  # noqa: E402

configure_logging()
settings = get_settings()

st.set_page_config(
    page_title="Verifile — SEC filing change analysis",
    page_icon="◆",
    layout="wide",
)

ui.inject_theme()


@st.cache_resource(show_spinner="Unpacking the bundled SEC cache…")
def _warm_cache() -> dict:
    """Unpack the bundled SEC responses once per container. No-op when warm."""
    return seed_demo_cache()


cache_state = _warm_cache()


# --------------------------------------------------------------------------- #
# Command bar
#
# This replaced a permanent 300px sidebar. Choosing a ticker is a one-time act;
# reading the comparison is the rest of the session. A side column optimised for
# the former, permanently taxing the latter — and width is exactly what the
# analysis needs, since the metric grid, its bars and full-measure evidence all
# compete for it. Query on one line at the top, everything below given to data.
#
# The three popovers separate concerns the sidebar had stacked as equals: what
# to compare (the bar itself), how to run it (Options), and how the machine is
# configured (Status).
# --------------------------------------------------------------------------- #

with st.container(border=True):
    b_mark, b_ticker, b_form, b_go, b_opts, b_pair, b_status = st.columns(
        [1.35, 1.35, 1.15, 1.35, 0.95, 1.05, 0.95], vertical_alignment="bottom"
    )
    with b_mark:
        ui.wordmark()
    with b_ticker:
        ticker = st.text_input("Ticker", value=settings.default_ticker).strip().upper()
    with b_form:
        form = st.selectbox("Filing type", ("10-K", "10-Q"), index=0)
    with b_go:
        compare = st.button("Compare", type="primary", width="stretch")

    with b_opts, st.popover("Options", width="stretch"):
        use_ai = st.toggle(
            "Add AI interpretation",
            value=settings.llm_available,
            disabled=not settings.llm_available,
            help="Deterministic analysis always runs first; the model only interprets it.",
        )
        refresh = st.toggle("Bypass cache (re-download from SEC)", value=False)
        # Two independent choices, both meaningless for a 10-K and so hidden for
        # it: which two filings to pair, and which figure to read within each.
        duration_class: str | None = None
        comparison_basis = "year_over_year"
        if form == "10-Q":
            paired = st.radio(
                "Compare against",
                ("Same quarter last year", "Previous quarter"),
                index=0,
                help=(
                    "Year over year holds seasonality constant and is the standard "
                    "read. Sequential shows the immediately preceding quarter, which "
                    "is more current but mixes seasonality into every move."
                ),
            )
            comparison_basis = (
                "year_over_year" if paired.startswith("Same") else "sequential"
            )
            # A 10-Q tags the quarter *and* the year-to-date figure against the
            # same period end, so the length has to be chosen rather than
            # inferred from the end date. Year to date is only offered against
            # the same quarter last year: it accumulates from the fiscal year
            # start, so consecutive quarters cover six months and then nine and
            # have nothing like-for-like to compare.
            sequential = comparison_basis == "sequential"
            length = st.radio(
                "10-Q reporting basis",
                ("Quarter (3 months)", "Year to date"),
                index=0,
                disabled=sequential,
                help=(
                    "A 10-Q reports both. The quarter isolates the period; year to "
                    "date is cumulative from the fiscal year start and smooths "
                    "seasonality. Both sides of the comparison always use the same basis."
                ),
            )
            if sequential:
                st.caption(
                    "Year to date is unavailable against the previous quarter — it accumulates "
                    "from the fiscal year start, so consecutive quarters are not like-for-like."
                )
            duration_class = (
                "quarterly" if sequential or length.startswith("Quarter") else "three_quarters"
            )

    with b_pair, st.popover("Filing pair", width="stretch"):
        st.caption(
            "By default the two most recent filings of the selected type are compared. "
            "Pick different ones here to test the period-comparability guardrails."
        )
        if st.button("List available filings", width="stretch"):
            try:
                st.session_state["filing_options"] = available_filings(ticker, form)
            except SecError as exc:
                st.error(str(exc))
        options = st.session_state.get("filing_options") or []
        if options:
            labels = {f.label: f for f in options}
            names = list(labels)
            later_label = st.selectbox("Latest filing", names, index=0)
            # Default to a filing the guardrail will actually accept. Offering
            # the next one in the list pre-selected a pair that is always three
            # months apart, so opening this popover on a year-over-year 10-Q and
            # pressing Compare produced a guaranteed refusal.
            match = comparable_earlier_filing(
                labels[later_label], options, comparison_basis
            )
            default = names.index(match.label) if match else min(1, len(names) - 1)
            earlier_label = st.selectbox("Earlier filing", names, index=default)
            if st.button("Compare this pair", width="stretch"):
                st.session_state["custom_pair"] = pair_from_filings(
                    labels[earlier_label], labels[later_label], comparison_basis
                )
                compare = True

    with b_status, st.popover("Status", width="stretch"):
        ui.llm_status_badge(settings.llm_available)
        if not settings.sec_identity_configured():
            st.warning(
                "`SEC_USER_AGENT` is not set to a real `Name email` value. SEC blocks "
                "unidentified clients — copy `.env.example` to `.env` and fill it in."
            )
        stats = DiskCache().stats()
        st.caption(f"Cache: {stats['entries']} entries, {stats['bytes'] / 1e6:.1f} MB")
        if cache_state.get("seeded"):
            st.caption(
                "Warm-started from SEC responses bundled with the app. These are the raw bytes "
                "EDGAR returned; every figure is still computed from them at request time. "
                "Tick **Bypass cache** in Options to force a live fetch."
            )
        st.caption("Research aid only. Not investment advice.")


# --------------------------------------------------------------------------- #
# Run the pipeline
# --------------------------------------------------------------------------- #

if compare:
    status = st.status("Running analysis…", expanded=True)

    def progress(msg: str) -> None:
        status.write(msg)

    try:
        bundle = run_analysis(
            ticker,
            form,
            pair=st.session_state.pop("custom_pair", None),
            progress=progress,
            refresh=refresh,
            duration_class=duration_class,
            basis=comparison_basis,
        )
        if use_ai and settings.llm_available:
            bundle = apply_ai_synthesis(bundle, client=LlmClient(), progress=progress)
        # Running without the model is a *mode*, not an event, and it used to be
        # appended to `warnings` — so every deterministic run opened with a
        # full-width amber banner. That trains the reader to skip banners, which
        # is costly here because the genuine ones (comparability failure,
        # low-confidence extraction) share the treatment. The header now carries
        # it as a chip instead; `result.llm_used` already records the fact.
        st.session_state["bundle"] = bundle
        status.update(
            label=f"Analysis complete in {bundle.elapsed_s:.1f}s", state="complete", expanded=False
        )
    except SecError as exc:
        status.update(label="Analysis failed", state="error", expanded=True)
        st.error(f"Could not complete the comparison: {exc}")
    except Exception as exc:  # noqa: BLE001
        status.update(label="Analysis failed", state="error", expanded=True)
        st.error(f"Unexpected error: {type(exc).__name__}: {exc}")


bundle = st.session_state.get("bundle")

if bundle is None:
    ui.landing()
    st.stop()

result = bundle.result

ui.company_header(result)
ui.filing_context_bar(result)
ui.extraction_strategy_note(result)

for w in result.warnings:
    st.warning(w)

# A persistent view selector rather than `st.tabs`. Streamlit tab selection is
# not widget state, so any rerun triggered from inside a tab — submitting a
# question, expanding a source — snaps the user back to the first tab. A
# `segmented_control` keyed in session state survives reruns.
VIEWS = (
    "Financial snapshot",
    "Material changes",
    "Risk factors",
    "Ask the filings",
    "Analyst brief",
)
view = (
    st.segmented_control(
        "View", VIEWS, default=VIEWS[0], key="active_view", label_visibility="collapsed"
    )
    or VIEWS[0]
)
st.divider()

# --------------------------------------------------------------------------- #
# View B — financial change snapshot
# --------------------------------------------------------------------------- #

if view == VIEWS[0]:
    usable = [c for c in result.comparisons if c.status == "ok"]
    blocked = [c for c in result.comparisons if c.status != "ok"]

    ui.section_heading(
        "Largest moves this period",
        "Level metrics are ranked among themselves by percentage change and ratio metrics "
        "among themselves by percentage points; the two are never ranked against each other.",
    )
    ui.headline_movers(result)

    ui.section_heading(
        "Period-over-period financial changes",
        "Every value is read from SEC XBRL facts and every change is calculated in Python. "
        "Level metrics show a percentage change; ratio metrics show a percentage-point (pp) "
        "change. Missing data shows as N/A and is never estimated.",
    )
    ui.metric_grid(result)
    ui.direction_legend()

    st.caption(f"**Free-cash-flow definition:** {FREE_CASH_FLOW_DEFINITION}")
    st.caption(
        f"{len(usable)} of {len(result.comparisons)} metrics compared · "
        f"{len(result.chunks):,} evidence chunks indexed · analysis took {bundle.elapsed_s:.1f}s"
    )

    if blocked:
        st.warning(
            f"{len(blocked)} metric(s) could not be compared: "
            + ", ".join(f"{c.label} ({c.status})" for c in blocked)
        )

    if result.restatements:
        ui.section_heading(
            "Restatement and reclassification flags",
            "The prior period as first reported, compared with the same period as re-tagged in "
            "the newer filing. A difference means part of the year-over-year change is a "
            "reclassification rather than performance.",
        )
        for r in result.restatements:
            st.error(
                f"**{r.label}** — originally `{r.as_originally_reported:,.0f}`, restated "
                f"`{r.as_restated_in_later_filing:,.0f}` ({r.relative_difference:.2f}%). {r.note}"
            )

    with st.expander("Sortable table and per-metric provenance"):
        st.dataframe(ui.metrics_table(result), width="stretch", hide_index=True)
        st.markdown("###### Underlying facts, metric by metric")
        for c in result.comparisons:
            ui.provenance_expander(c)

# --------------------------------------------------------------------------- #
# View C — material textual changes
# --------------------------------------------------------------------------- #

if view == VIEWS[1]:
    ui.section_heading(
        "Shift in topic emphasis across all probes",
        "Every probe is a fixed, versioned query, so the same filing pair always produces the "
        "same evidence. Probes that cleared the materiality threshold become the changes below.",
    )
    ui.emphasis_chart(result)

    ui.section_heading(
        "Material changes, with earlier and later evidence side by side",
        "Each change is anchored on a measured signal: a Python-computed metric move, a "
        "normalised change in topic emphasis, or both. Topics below the materiality threshold "
        "are omitted rather than padded out.",
    )
    if not result.changes:
        st.info(
            "No topic exceeded the materiality thresholds for this filing pair. That is the "
            "honest result — nothing is manufactured to fill the section."
        )
    for change in result.changes:
        ui.change_card(change, result)

    with st.expander("Per-probe emphasis rates and signal notes"):
        for t in sorted(result.topics, key=lambda t: -abs(t.emphasis_delta)):
            st.markdown(
                f"**{t.topic_label}** — earlier `{t.earlier_rate:.1f}` → later "
                f"`{t.later_rate:.1f}` (**{t.emphasis_delta:+.1f}** per 10,000 tokens)"
            )
            st.caption(t.signal_note)

# --------------------------------------------------------------------------- #
# Risk factors
# --------------------------------------------------------------------------- #

if view == VIEWS[2]:
    rd = result.risk_delta
    if rd is None:
        st.info("Risk-factor headings could not be extracted from one or both filings.")
    else:
        ui.section_heading(
            "Item 1A risk-factor heading diff",
            "Turnover in the risk section, heading by heading. The bar shows the proportion "
            "of the latest filing's risk headings that are new, retained or gone.",
        )
        st.markdown(f"**Verified fact.** {md_safe(risk_change_summary(rd))}")
        ui.risk_composition(rd)

        ui.evidence_side_label(
            "Heading changes", f"{len(rd.added)} new · {len(rd.removed)} no longer present"
        )
        ui.heading_ledger(rd.added, rd.removed)
        st.warning(f"**Caveat.** {md_safe(rd.note)}")

        with st.expander(f"Retained risk headings ({len(rd.retained)})"):
            for h in rd.retained:
                st.markdown(f"- {md_safe(h)}")

# --------------------------------------------------------------------------- #
# View D — filing Q&A
# --------------------------------------------------------------------------- #

if view == VIEWS[3]:
    ui.section_heading(
        "Ask a question about the selected filings",
        "Answers use only evidence retrieved from the two selected filings. When the evidence "
        "does not support an answer, the system says so instead of guessing.",
    )
    # Streamlit discards the state of widgets a rerun did not draw, so leaving
    # this view and coming back used to clear the question box. Mirroring into a
    # plain (non-widget) key preserves it.
    if "qa_question" not in st.session_state:
        st.session_state["qa_question"] = st.session_state.get("qa_question_kept", "")

    def use_preset() -> None:
        """Copy the chosen suggestion into the question box.

        A keyed widget ignores its own ``value=`` argument on every rerun after
        the first, so the previous ``value="" if preset == "—" else preset``
        never reached the box: picking a suggested question silently did
        nothing. Writing to session state from the selectbox's own callback is
        the supported way to drive one widget from another.
        """
        chosen = st.session_state.get("qa_preset", "—")
        if chosen != "—":
            st.session_state["qa_question"] = chosen

    st.selectbox(
        "Suggested questions", ("—",) + SUGGESTED_QUESTIONS, key="qa_preset", on_change=use_preset
    )
    question = st.text_input("Your question", key="qa_question")
    st.session_state["qa_question_kept"] = question

    # A stored answer belongs to the question that produced it. Editing the box
    # without searching again would otherwise leave the old answer sitting under
    # the new question, which reads as though it answered it.
    if st.session_state.get("qa_asked") != question.strip():
        st.session_state.pop("qa_result", None)
        st.session_state.pop("qa_error", None)

    if st.button("Search the filings", type="primary") and question.strip():
        with st.spinner("Retrieving evidence…"):
            # The only user-triggered action that previously ran unguarded. The
            # model client degrades internally, but retrieval, a revoked key or
            # a network fault still raise — and with `showErrorDetails="none"`
            # set for deployment, an escaped exception reaches the analyst as an
            # opaque redacted panel rather than something they can act on.
            try:
                st.session_state["qa_result"] = answer_question(
                    question.strip(),
                    bundle.index,
                    result.pair,
                    result.comparisons,
                    client=LlmClient() if (use_ai and settings.llm_available) else None,
                    risk_delta=result.risk_delta,
                )
                st.session_state["qa_asked"] = question.strip()
                st.session_state.pop("qa_error", None)
            except SecError as exc:
                st.session_state["qa_error"] = f"Could not search the filings: {exc}"
                st.session_state.pop("qa_result", None)
            except Exception as exc:  # noqa: BLE001 — surface, never blank the page
                st.session_state["qa_error"] = (
                    f"The question could not be answered: {type(exc).__name__}: {exc}. "
                    "The deterministic analysis in the other views is unaffected."
                )
                st.session_state.pop("qa_result", None)

    if st.session_state.get("qa_error"):
        st.error(st.session_state["qa_error"])

    qa = st.session_state.get("qa_result")
    if qa is not None:
        if qa.answer_type == "answered":
            st.success(md_safe(qa.answer))
        elif qa.answer_type == "insufficient_evidence":
            st.warning(f"**Insufficient evidence.** {md_safe(qa.answer)}")
        else:
            st.info(md_safe(qa.answer))
        if qa.related_metric_ids:
            bits = []
            for mid in qa.related_metric_ids:
                comp = result.comparison_by_id(mid)
                if comp:
                    bits.append(f"`{mid}` {change_text(comp)}")
            if bits:
                st.markdown(f"**Related calculated changes.** {'; '.join(bits)}")
        if qa.caveat:
            st.warning(f"{md_safe(qa.caveat)}")

        ui.section_heading(
            "Retrieved evidence",
            "Ordered oldest first. Each excerpt names the filing it came from and links to it.",
        )
        ui.evidence_list(qa.evidence)

# --------------------------------------------------------------------------- #
# View E — one-page brief
# --------------------------------------------------------------------------- #

if view == VIEWS[4]:
    ui.section_heading(
        "Analyst brief",
        "The same findings as a self-contained Markdown document, with every citation and "
        "caveat carried through.",
    )
    markdown = build_markdown_brief(result)
    st.download_button(
        "Download Markdown brief",
        data=markdown,
        file_name=brief_filename(result),
        mime="text/markdown",
        type="primary",
    )
    if result.llm_logs:
        with st.expander("Model run log (model, prompt version, latency, tokens)"):
            for r in result.llm_logs:
                st.markdown(
                    f"- `{r.purpose}` · model `{r.model}` · prompt `{r.prompt_version}` · "
                    f"{r.latency_ms} ms · tokens in/out `{r.input_tokens}`/`{r.output_tokens}` · "
                    f"{'ok' if r.ok else 'FAILED: ' + r.error}"
                    + (
                        f" · dropped citations: `{', '.join(r.dropped_citations)}`"
                        if r.dropped_citations
                        else ""
                    )
                    + (f" · dropped changes: {r.dropped_changes}" if r.dropped_changes else "")
                )
    st.markdown("---")
    # The download carries the original bytes; only the on-screen preview needs
    # dollar signs protected from Streamlit's LaTeX handling.
    st.markdown(escape_dollars(markdown))
