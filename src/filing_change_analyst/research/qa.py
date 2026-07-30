"""Filing question answering.

Retrieval is always deterministic, so the evidence panel works with or without a
model. Without a key the system returns the ranked excerpts and says explicitly
that no answer was synthesised — an honest partial result rather than silence.
"""

from __future__ import annotations

import logging
import re

from ..analytics.validation import (
    allowed_number_set,
    contains_recommendation,
    ungrounded_numbers,
)
from ..models import LlmAnswer, MetricComparison, QaResult, RiskFactorDelta
from ..retrieval.citations import validate_citation_ids, validate_metric_ids
from ..retrieval.index import Bm25Index
from ..retrieval.search import expand_query, retrieve_for_question
from ..services.llm import LlmClient
from . import prompts
from .change_detection import risk_change_summary

log = logging.getLogger(__name__)

# Deciding "can this question be answered from the filings at all?" is a
# retrieval problem the raw BM25 score cannot solve. Measured on the default
# MSFT FY2025/FY2024 pair over 16 answerable and 6 unanswerable questions:
#
#   signal                          answerable        unanswerable    separates?
#   ------------------------------  ----------------  --------------  ----------
#   BM25 top score                    5.8 – 34.4        5.6 – 14.5       no
#   query coverage (raw)              0.41 – 1.00       0.17 – 0.67      no
#   query coverage (content terms)    0.76 – 1.00       0.11 – 0.67      yes
#
# The fix that made coverage work is dropping *question words* ("describe",
# "drove", "factors") before measuring: filings never contain them, so leaving
# them in made well-phrased questions look unanswerable. See
# ``Bm25Index.content_terms``.
#
# MIN_QUERY_COVERAGE sits between the two measured ranges. MIN_TOP_SCORE is a
# separate floor for a query that matches literally nothing.
#
# These are calibrated on one filing pair with ~8% margin on each side, so they
# are a genuine tuning risk on other companies — listed as such in the README.
# Neither gate can catch a question whose *words* are all present but whose
# *fact* is undisclosed ("what was the closing share price" measures 0.77).
# That judgement needs the model, and is a documented limitation.
MIN_TOP_SCORE = 3.0
MIN_QUERY_COVERAGE = 0.70

_RISK_CHANGE_QUESTION = re.compile(
    r"(risk).{0,40}(new|added|removed|chang|appear|prominen|differ)"
    r"|(new|added|removed|chang|appear|prominen|differ).{0,40}(risk)",
    re.I,
)

SUGGESTED_QUESTIONS: tuple[str, ...] = (
    "What changed in the discussion of capital expenditure?",
    "Which risks appear new or more prominent?",
    "What factors did management identify as affecting gross margin?",
    "How did management's description of competition change?",
    "What drove the change in operating cash flow?",
    "What did management say about AI investment and capacity?",
)


def _risk_delta_answer(
    question: str, delta: RiskFactorDelta, evidence: list
) -> QaResult:
    """Answer a 'what risks changed' question from the deterministic heading diff.

    Retrieval is a poor tool for this question — the answer is a set difference,
    not a passage — so it is served directly from the Item 1A diff and works
    without a model.
    """
    lines = [risk_change_summary(delta)]
    if delta.added:
        lines.append("New or substantially reworded risk headings: " + "; ".join(delta.added))
    if delta.removed:
        lines.append(
            "Risk headings present in the earlier filing but not matched in the latest: "
            + "; ".join(delta.removed)
        )
    if not delta.added and not delta.removed:
        lines.append("No heading was added or removed above the similarity threshold.")
    return QaResult(
        question=question,
        answer=" ".join(lines),
        answer_type="answered",
        evidence=evidence,
        caveat=delta.note,
        generated_by="deterministic",
    )


def answer_question(
    question: str,
    index: Bm25Index,
    pair,
    comparisons: list[MetricComparison],
    client: LlmClient | None = None,
    *,
    risk_delta: RiskFactorDelta | None = None,
    top_k_per_period: int = 3,
) -> QaResult:
    """Retrieve evidence and, when a model is available, synthesise an answer."""
    route = retrieve_for_question(index, question, top_k_per_period=top_k_per_period)
    evidence = route.evidence

    if risk_delta is not None and _RISK_CHANGE_QUESTION.search(question):
        return _risk_delta_answer(question, risk_delta, evidence)

    top_score = max((e.score for e in evidence), default=0.0)
    coverage, missing = index.query_coverage(expand_query(question))
    if not evidence or top_score < MIN_TOP_SCORE or coverage < MIN_QUERY_COVERAGE:
        missing_note = (
            f" Terms not found anywhere in the extracted sections: {', '.join(missing[:6])}."
            if missing
            else ""
        )
        return QaResult(
            question=question,
            answer=(
                "Insufficient evidence: no passage in the extracted sections of either filing "
                f"matched this question strongly enough to answer it (best BM25 score "
                f"{top_score:.1f}, query-term coverage {coverage:.0%}).{missing_note} Try wording "
                "the question with terminology the filing itself would use."
            ),
            answer_type="insufficient_evidence",
            evidence=evidence,
            caveat=(
                "Only Items 1, 1A, 7 and 7A are indexed; the financial statements, notes, "
                "exhibits and Item 5 market information are not searchable here."
            ),
        )

    if client is None or not client.available:
        return QaResult(
            question=question,
            answer=(
                "AI synthesis is unavailable (no ANTHROPIC_API_KEY configured). The most "
                "relevant passages from both filings are shown below for direct reading; every "
                "excerpt carries its filing, section and accession number."
            ),
            answer_type="llm_unavailable",
            evidence=evidence,
            caveat="No answer was generated. The evidence below is retrieval output, unranked by relevance to your specific phrasing beyond BM25 scoring.",
        )

    parsed, run = client.structured(
        system=prompts.system_prompt(prompts.QA_ROLE),
        user=prompts.qa_user_prompt(pair, question, evidence, comparisons),
        schema=LlmAnswer,
        purpose="question_answer",
    )
    if parsed is None:
        return QaResult(
            question=question,
            answer=(
                f"The answer could not be generated ({run.error}). The retrieved evidence is "
                "shown below so the question can still be answered by reading the sources."
            ),
            answer_type="llm_unavailable",
            evidence=evidence,
            caveat="Model call failed; this is a retrieval-only result.",
        )

    allowed_ids = {e.chunk.chunk_id for e in evidence}
    kept_ids, dropped_ids = validate_citation_ids(parsed.source_ids, allowed_ids)
    metric_ids, dropped_metrics = validate_metric_ids(parsed.related_metric_ids, comparisons)
    run.dropped_citations = dropped_ids + dropped_metrics

    caveat = parsed.caveat
    text = parsed.answer

    if contains_recommendation(f"{text} {caveat}"):
        return QaResult(
            question=question,
            answer=(
                "The generated answer was withheld because it contained investment-recommendation "
                "language, which this tool does not produce. The retrieved evidence is shown below."
            ),
            answer_type="insufficient_evidence",
            evidence=evidence,
            caveat="Answer suppressed by the recommendation guardrail.",
            generated_by="llm",
        )

    allowed_numbers = allowed_number_set(comparisons, [e.chunk.text for e in evidence])
    bad = ungrounded_numbers(f"{text} {caveat}", allowed_numbers)
    if bad:
        caveat = (
            f"{caveat} Note: the generated answer contained figures ({', '.join(bad[:3])}) that "
            "could not be matched to the supplied evidence or the calculated metrics — verify "
            "them against the excerpts below before using them."
        ).strip()

    if parsed.answer_type == "insufficient_evidence" or not kept_ids:
        return QaResult(
            question=question,
            answer=text,
            answer_type="insufficient_evidence",
            evidence=evidence,
            related_metric_ids=metric_ids,
            caveat=caveat or "The model reported that the retrieved evidence does not settle this question.",
            generated_by="llm",
        )

    cited = [e for e in evidence if e.chunk.chunk_id in set(kept_ids)]
    return QaResult(
        question=question,
        answer=text,
        answer_type="answered",
        evidence=cited or evidence,
        related_metric_ids=metric_ids,
        caveat=caveat,
        generated_by="llm",
    )
