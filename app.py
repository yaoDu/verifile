"""Evidence-First Filing Change Analyst — Streamlit interface.

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
    """Copy Streamlit secrets into the process environment.

    Settings are read from the environment (or a local ``.env``) by
    ``pydantic-settings``, which knows nothing about ``st.secrets``. Hosted
    deployments have no ``.env`` — they inject configuration through the
    platform's secrets store — so the two have to be joined up before
    :func:`get_settings` builds its cached ``Settings``.

    Only upper-case scalars are copied, and an existing environment variable
    always wins, so a local ``.env`` still overrides the deployment. Values are
    never logged; ``config.py`` is the only place they are read.
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
from filing_change_analyst.services.cache import DiskCache  # noqa: E402
from filing_change_analyst.services.demo_cache import seed_demo_cache  # noqa: E402
from filing_change_analyst.services.llm import LlmClient  # noqa: E402
from filing_change_analyst.ui import components as ui  # noqa: E402

configure_logging()
settings = get_settings()

st.set_page_config(
    page_title="Evidence-First Filing Change Analyst",
    page_icon="📑",
    layout="wide",
)


@st.cache_resource(show_spinner="Unpacking the bundled SEC cache…")
def _warm_cache() -> dict:
    """Unpack the bundled SEC responses once per container. No-op when warm."""
    return seed_demo_cache()


cache_state = _warm_cache()


# --------------------------------------------------------------------------- #
# Sidebar — View A: company and filing selection
# --------------------------------------------------------------------------- #

with st.sidebar:
    st.title("📑 Filing Change Analyst")
    st.caption(
        "Compare a company's two most recent comparable SEC filings, with every figure "
        "calculated in Python and every claim traced to a source."
    )

    ticker = st.text_input("Ticker", value=settings.default_ticker).strip().upper()
    form = st.selectbox("Filing type", ("10-K", "10-Q"), index=0)
    use_ai = st.toggle(
        "Add AI interpretation",
        value=settings.llm_available,
        disabled=not settings.llm_available,
        help="Deterministic analysis always runs first; the model only interprets it.",
    )
    refresh = st.toggle("Bypass cache (re-download from SEC)", value=False)

    compare = st.button("🔍 Compare latest filings", type="primary", use_container_width=True)

    with st.expander("Choose a specific filing pair"):
        st.caption(
            "By default the two most recent filings of the selected type are compared. "
            "Pick different ones here to test the period-comparability guardrails."
        )
        if st.button("List available filings", use_container_width=True):
            try:
                st.session_state["filing_options"] = available_filings(ticker, form)
            except SecError as exc:
                st.error(str(exc))
        options = st.session_state.get("filing_options") or []
        custom_pair = None
        if options:
            labels = {f.label: f for f in options}
            later_label = st.selectbox("Latest filing", list(labels), index=0)
            earlier_label = st.selectbox(
                "Earlier filing", list(labels), index=min(1, len(labels) - 1)
            )
            if st.button("Compare this pair", use_container_width=True):
                custom_pair = pair_from_filings(labels[earlier_label], labels[later_label])
                st.session_state["custom_pair"] = custom_pair
                compare = True

    st.divider()
    ui.llm_status_badge(settings.llm_available)
    if not settings.sec_identity_configured():
        st.warning(
            "`SEC_USER_AGENT` is not set to a real `Name email` value. SEC blocks unidentified "
            "clients — copy `.env.example` to `.env` and fill it in."
        )
    stats = DiskCache().stats()
    st.caption(f"Cache: {stats['entries']} entries, {stats['bytes'] / 1e6:.1f} MB")
    if cache_state.get("seeded"):
        st.caption(
            "Warm-started from the SEC responses bundled in the repository, so the demo "
            "renders on the first click. These are the raw bytes EDGAR returned — every "
            "figure is still computed from them at request time. Tick **Bypass cache** "
            "above to force a live fetch and check that for yourself."
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
        )
        if use_ai and settings.llm_available:
            bundle = apply_ai_synthesis(bundle, client=LlmClient(), progress=progress)
        else:
            bundle.result.warnings.append(
                "AI interpretation was not requested or is unavailable; all findings below are "
                "produced deterministically in Python."
            )
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
    st.title("Evidence-First Filing Change Analyst")
    st.markdown(
        """
**The question this answers:** *what materially changed in this company's latest filing
versus the previous comparable one, and what evidence supports each conclusion?*

Pick a ticker in the sidebar and press **Compare latest filings**. The default is a
Microsoft 10-K year-over-year comparison.

**Suggested tickers.** Any US filer with a 10-K works, fetched live from EDGAR.
`MSFT`, `AAPL`, `NVDA` and `PG` have their SEC responses pre-warmed in this
deployment and return in a few seconds. `PG` is worth a look precisely because it is
where the system is *weakest* — its 10-K carries no item numbers, so section
extraction falls back to a low-confidence strategy and says so on screen.

**How it works**

1. SEC EDGAR submissions pick the two most recent comparable filings, and structural
   comparability checks run *before* any arithmetic.
2. Financial metrics are read from SEC XBRL company facts. Every change is computed in
   Python — the model is never asked to produce a number.
3. Items 1, 1A, 7 and 7A are extracted, chunked with full provenance, and indexed with BM25.
4. Fixed topic probes retrieve matched earlier/later evidence and measure a normalised
   emphasis delta, producing citable material changes *with or without* a model.
5. When an API key is present, the model interprets those measured signals under strict
   citation, numeric-grounding and no-recommendation guardrails.
        """
    )
    st.stop()

result = bundle.result

st.title(f"{result.pair.later.company_name} ({result.pair.later.ticker})")
ui.filing_pair_header(result)
ui.extraction_strategy_note(result)

for w in result.warnings:
    st.warning(w)

# A persistent view selector rather than `st.tabs`. Streamlit tab selection is
# not widget state, so any rerun triggered from inside a tab — submitting a
# question, expanding a source — snaps the user back to the first tab. A
# `segmented_control` keyed in session state survives reruns.
VIEWS = (
    "📊 Financial snapshot",
    "🔀 Material changes",
    "🛡️ Risk factors",
    "❓ Ask the filings",
    "📄 Analyst brief",
)
view = st.segmented_control(
    "View", VIEWS, default=VIEWS[0], key="active_view", label_visibility="collapsed"
) or VIEWS[0]
st.divider()

# --------------------------------------------------------------------------- #
# View B — financial change snapshot
# --------------------------------------------------------------------------- #

if view == VIEWS[0]:
    st.subheader("Period-over-period financial changes")
    st.caption(
        "All values are read from SEC XBRL facts and all changes are calculated in Python. "
        "Level metrics show a percentage change; ratio metrics show a percentage-point (pp) "
        "change. Missing data shows as `N/A` and is never estimated."
    )
    usable = [c for c in result.comparisons if c.status == "ok"]
    blocked = [c for c in result.comparisons if c.status != "ok"]
    m1, m2, m3 = st.columns(3)
    m1.metric("Metrics compared", f"{len(usable)} / {len(result.comparisons)}")
    m2.metric("Evidence chunks indexed", f"{len(result.chunks):,}")
    m3.metric("Analysis time", f"{bundle.elapsed_s:.1f}s")

    st.dataframe(ui.metrics_table(result), use_container_width=True, hide_index=True)
    st.caption(f"**Free-cash-flow definition:** {FREE_CASH_FLOW_DEFINITION}")

    if blocked:
        st.warning(
            f"{len(blocked)} metric(s) could not be compared: "
            + ", ".join(f"{c.label} ({c.status})" for c in blocked)
        )

    if result.restatements:
        st.subheader("Restatement / reclassification flags")
        st.caption(
            "The prior period as first reported, compared with the same period as re-tagged in "
            "the newer filing. A difference means part of the year-over-year change is a "
            "reclassification rather than performance."
        )
        for r in result.restatements:
            st.error(
                f"**{r.label}** — originally `{r.as_originally_reported:,.0f}`, restated "
                f"`{r.as_restated_in_later_filing:,.0f}` ({r.relative_difference:.2f}%). {r.note}"
            )

    st.subheader("Inspect the underlying facts")
    for c in result.comparisons:
        ui.provenance_expander(c)

# --------------------------------------------------------------------------- #
# View C — material textual changes
# --------------------------------------------------------------------------- #

if view == VIEWS[1]:
    st.subheader("Material changes, with earlier and later evidence side by side")
    st.caption(
        "Each change is anchored on a measured signal: a Python-computed metric move, a "
        "normalised change in topic emphasis, or both. Topics below the materiality threshold "
        "are omitted rather than padded out."
    )
    if not result.changes:
        st.info(
            "No topic exceeded the materiality thresholds for this filing pair. That is the "
            "honest result — nothing is manufactured to fill the section."
        )
    for change in result.changes:
        ui.change_card(change, result)

    with st.expander("All topic probes and measured emphasis deltas"):
        st.caption(
            "Every probe is a fixed, versioned query, so the same filing pair always produces "
            "the same evidence. Emphasis is phrase frequency per 10,000 tokens."
        )
        for t in sorted(result.topics, key=lambda t: -abs(t.emphasis_delta)):
            st.markdown(
                f"**{t.topic_label}** — earlier `{t.earlier_rate:.1f}` → later "
                f"`{t.later_rate:.1f}` (**{t.emphasis_delta:+.1f}**)"
            )
            st.caption(t.signal_note)

# --------------------------------------------------------------------------- #
# Risk factors
# --------------------------------------------------------------------------- #

if view == VIEWS[2]:
    st.subheader("Item 1A risk-factor heading diff")
    rd = result.risk_delta
    if rd is None:
        st.info("Risk-factor headings could not be extracted from one or both filings.")
    else:
        st.markdown(f"✅ **Verified fact.** {risk_change_summary(rd)}")
        c1, c2, c3 = st.columns(3)
        c1.metric("New headings", len(rd.added))
        c2.metric("No longer present", len(rd.removed))
        c3.metric("Retained", len(rd.retained))

        left, right = st.columns(2)
        with left:
            st.markdown("**New or substantially reworded**")
            for h in rd.added or ["_(none)_"]:
                st.markdown(f"- {h}")
        with right:
            st.markdown("**Present previously, not matched now**")
            for h in rd.removed or ["_(none)_"]:
                st.markdown(f"- {h}")
        st.warning(f"⚠️ **Caveat.** {rd.note}")

        with st.expander("Retained risk headings"):
            for h in rd.retained:
                st.markdown(f"- {h}")

# --------------------------------------------------------------------------- #
# View D — filing Q&A
# --------------------------------------------------------------------------- #

if view == VIEWS[3]:
    st.subheader("Ask a question about the selected filings")
    st.caption(
        "Answers use only evidence retrieved from the two selected filings. When the evidence "
        "does not support an answer, the system says so instead of guessing."
    )
    preset = st.selectbox("Suggested questions", ("—",) + SUGGESTED_QUESTIONS)
    question = st.text_input(
        "Your question", value="" if preset == "—" else preset, key="qa_question"
    )
    if st.button("Search the filings", type="primary") and question.strip():
        with st.spinner("Retrieving evidence…"):
            qa = answer_question(
                question.strip(),
                bundle.index,
                result.pair,
                result.comparisons,
                client=LlmClient() if (use_ai and settings.llm_available) else None,
                risk_delta=result.risk_delta,
            )
        if qa.answer_type == "answered":
            st.success(qa.answer)
        elif qa.answer_type == "insufficient_evidence":
            st.warning(f"**Insufficient evidence.** {qa.answer}")
        else:
            st.info(qa.answer)
        if qa.related_metric_ids:
            bits = []
            for mid in qa.related_metric_ids:
                comp = result.comparison_by_id(mid)
                if comp:
                    from filing_change_analyst.formatting import change_text

                    bits.append(f"`{mid}` {change_text(comp)}")
            if bits:
                st.markdown(f"🧮 **Related calculated changes.** {'; '.join(bits)}")
        if qa.caveat:
            st.warning(f"⚠️ {qa.caveat}")

        st.markdown("#### Retrieved evidence")
        earlier = [e for e in qa.evidence if e.chunk.period == "earlier"]
        later = [e for e in qa.evidence if e.chunk.period == "later"]
        left, right = st.columns(2)
        with left:
            st.markdown(f"**Earlier filing ({result.pair.earlier.report_date})**")
            ui.evidence_list(earlier)
        with right:
            st.markdown(f"**Latest filing ({result.pair.later.report_date})**")
            ui.evidence_list(later)

# --------------------------------------------------------------------------- #
# View E — one-page brief
# --------------------------------------------------------------------------- #

if view == VIEWS[4]:
    st.subheader("One-page analyst brief")
    markdown = build_markdown_brief(result)
    st.download_button(
        "⬇️ Download Markdown brief",
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
    st.markdown(markdown)
