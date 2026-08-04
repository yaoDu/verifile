"""The analysis pipeline: filings → facts → metrics → evidence → changes.

Every stage below is deterministic. The optional LLM layer is applied *after*
this pipeline completes, so a failure or absence of the model can never remove
the financial comparison or the source evidence.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from .analytics.comparisons import compare_filings
from .models import AnalysisResult, ComparisonBasis, DurationClass, Filing, FilingPair
from .research.change_detection import detect_material_changes, diff_risk_headings
from .retrieval.chunking import chunk_filing
from .retrieval.index import Bm25Index
from .retrieval.search import probe_all_topics
from .sec.client import SecClient, SecError
from .sec.facts import FactStore
from .sec.filings import build_pair, list_filings, select_filing_pair
from .sec.sections import extract_risk_headings, extract_sections, section_confidence

if TYPE_CHECKING:  # imported lazily at runtime so no-LLM installs stay light
    from .services.llm import LlmClient

log = logging.getLogger(__name__)

ProgressFn = Callable[[str], None]


def _noop(_: str) -> None:  # pragma: no cover - trivial
    pass


class AnalysisBundle:
    """The analysis plus the live retrieval index (not serialisable into the result)."""

    def __init__(self, result: AnalysisResult, index: Bm25Index, elapsed_s: float) -> None:
        self.result = result
        self.index = index
        self.elapsed_s = elapsed_s


def run_analysis(
    ticker: str = "MSFT",
    form: str = "10-K",
    *,
    client: SecClient | None = None,
    pair: FilingPair | None = None,
    progress: ProgressFn = _noop,
    refresh: bool = False,
    duration_class: DurationClass | None = None,
    basis: ComparisonBasis = "year_over_year",
) -> AnalysisBundle:
    """Run the deterministic pipeline end to end.

    ``duration_class`` pins which reporting length the metrics use. ``None``
    takes the form default (10-K annual, 10-Q quarterly); pass
    ``"three_quarters"`` for a 10-Q read on a year-to-date basis.

    ``basis`` says which comparison to build: the same quarter a year earlier
    (default) or the immediately preceding one. It is orthogonal to
    ``duration_class`` — the first picks *which two filings*, the second picks
    *which figure within each*.
    """
    started = time.perf_counter()
    owns_client = client is None
    client = client or SecClient()
    warnings: list[str] = []
    data_notes: list[str] = []

    try:
        if pair is None:
            progress(f"Selecting the two most recent comparable {form} filings for {ticker.upper()}…")
            pair = select_filing_pair(client, ticker, form, refresh=refresh, basis=basis)
        # Comparability notes deliberately stay on the pair rather than being
        # copied into `warnings`. Every surface that shows them — the context
        # bar, the brief's blocking block — reads them from the pair, so copying
        # them here printed each note twice.

        progress("Loading structured XBRL facts from SEC…")
        store = FactStore(client.company_facts(pair.later.cik, refresh=refresh))

        progress("Calculating period-over-period changes in Python…")
        comparisons, restatements, calc_warnings = compare_filings(
            store, pair, duration_class=duration_class
        )
        warnings.extend(calc_warnings)

        sections: dict[str, dict] = {}
        section_strategy: dict[str, str] = {}
        chunks = []
        risk_delta = None
        risk_meta: dict[str, tuple[list[str], str, int]] = {}

        for period, filing in (("earlier", pair.earlier), ("later", pair.later)):
            progress(f"Downloading and sectioning the {period} filing ({filing.form} {filing.accession})…")
            try:
                raw = client.filing_document(
                    filing.cik, filing.accession, filing.primary_document, refresh=refresh
                )
            except SecError as exc:
                warnings.append(
                    f"Could not download the {period} filing document ({exc}). Text evidence for "
                    "that period is unavailable; the financial comparison is unaffected."
                )
                sections[period] = {}
                section_strategy[period] = "none"
                risk_meta[period] = ([], "low", 0)
                continue

            # The form decides which items exist at all: MD&A is Item 7 in a
            # 10-K and Item 2 in a 10-Q. Reading one through the other's outline
            # silently loses sections rather than failing.
            secs, notes, strategy = extract_sections(raw, filing.form)
            sections[period] = secs
            section_strategy[period] = strategy
            if strategy == "none":
                warnings.append(
                    f"Section extraction failed for the {period} filing "
                    f"({filing.form} {filing.accession}): no item headings could be located by "
                    "any supported convention. No text evidence is available for that period, so "
                    "material-change detection and filing search are unavailable. The financial "
                    "comparison is unaffected."
                )
            elif strategy != "upper_case":
                data_notes.append(
                    f"{period} filing: sections located with the '{strategy}' heading convention "
                    f"(extraction confidence {section_confidence(strategy)})."
                )
            data_notes.extend(f"{period} filing: {n}" for n in notes)
            headings, confidence = extract_risk_headings(raw, strategy, filing.form)
            risk_chars = secs["item_1a_risk_factors"].char_count if "item_1a_risk_factors" in secs else 0
            risk_meta[period] = (headings, confidence, risk_chars)
            chunks.extend(chunk_filing(secs, filing, period, headings=headings))  # type: ignore[arg-type]

        progress("Indexing evidence and probing research topics…")
        index = Bm25Index(chunks)
        topics = probe_all_topics(index)

        if not chunks:
            warnings.append(
                "No text evidence could be extracted from either filing, so there are no "
                "material changes, no risk diff and no filing search. Only the financial "
                "comparison below is available."
            )

        e_head, e_conf, e_chars = risk_meta.get("earlier", ([], "low", 0))
        l_head, l_conf, l_chars = risk_meta.get("later", ([], "low", 0))
        if e_head or l_head:
            confidence = "low" if "low" in (e_conf, l_conf) else ("high" if e_conf == l_conf == "high" else "moderate")
            risk_delta = diff_risk_headings(
                e_head, l_head, earlier_chars=e_chars, later_chars=l_chars, confidence=confidence
            )
        else:
            warnings.append(
                "Risk-factor headings could not be extracted from one or both filings, so the "
                "risk-factor diff is unavailable."
            )

        changes = detect_material_changes(topics, comparisons)
        if len(changes) < 3:
            data_notes.append(
                f"Only {len(changes)} topic(s) exceeded the materiality thresholds; the change "
                "list is intentionally short rather than padded."
            )

        result = AnalysisResult(
            pair=pair,
            comparisons=comparisons,
            restatements=restatements,
            sections=sections,  # type: ignore[arg-type]
            chunks=chunks,
            topics=topics,
            changes=changes,
            risk_delta=risk_delta,
            section_strategy=section_strategy,
            warnings=list(dict.fromkeys(warnings)),
            data_notes=list(dict.fromkeys(data_notes)),
        )
        return AnalysisBundle(result, index, time.perf_counter() - started)
    finally:
        if owns_client:
            client.close()


def apply_ai_synthesis(
    bundle: AnalysisBundle,
    *,
    client: LlmClient | None = None,
    progress: ProgressFn = _noop,
) -> AnalysisBundle:
    """Layer optional AI interpretation on top of a completed deterministic run.

    Called separately from :func:`run_analysis` on purpose: the deterministic
    result is already complete and displayable before the first model token is
    requested, so a slow or failing model degrades the experience rather than
    breaking it.
    """
    from .research.synthesis import interpret_changes, write_brief_sections
    from .services.llm import LlmClient

    result = bundle.result
    client = client or LlmClient()
    if not client.available:
        result.warnings.append(
            "AI synthesis is disabled: no API_KEY is configured. The financial "
            "comparison, risk diff, topic evidence and Markdown brief are unaffected."
        )
        result.llm_logs = client.logs
        return bundle

    progress("Interpreting measured changes with the model…")
    changes, notes = interpret_changes(
        client, result.pair, result.comparisons, result.topics, result.changes
    )
    result.changes = changes
    result.data_notes.extend(notes)

    progress("Drafting the interpretive brief sections…")
    extras, brief_notes = write_brief_sections(
        client, result.pair, result.comparisons, result.changes, result.risk_delta
    )
    result.brief_extras = extras
    result.data_notes.extend(brief_notes)

    result.llm_logs = client.logs
    result.llm_used = any(r.ok for r in client.logs)
    result.data_notes = list(dict.fromkeys(result.data_notes))
    return bundle


def available_filings(
    ticker: str, form: str = "10-K", *, client: SecClient | None = None, limit: int = 8
) -> list[Filing]:
    owns = client is None
    client = client or SecClient()
    try:
        return list_filings(client, ticker, form, limit=limit)
    finally:
        if owns:
            client.close()


def pair_from_filings(
    earlier: Filing, later: Filing, basis: ComparisonBasis = "year_over_year"
) -> FilingPair:
    return build_pair(earlier, later, basis)
