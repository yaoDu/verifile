"""Insufficient-evidence gating and deterministic question routing."""

from __future__ import annotations

import pytest

from filing_change_analyst.pipeline import run_analysis
from filing_change_analyst.research.qa import (
    MIN_QUERY_COVERAGE,
    MIN_TOP_SCORE,
    answer_question,
)
from filing_change_analyst.retrieval.index import Bm25Index


@pytest.fixture()
def bundle(fake_client):
    return run_analysis("MSFT", "10-K", client=fake_client)


def test_content_terms_drop_question_words_but_keep_subject():
    terms = Bm25Index.content_terms("What factors drove the change in capital expenditure?")
    assert "capital" in terms and "expenditure" in terms
    for noise in ("what", "factors", "drove", "change"):
        assert noise not in terms


def test_content_terms_never_empty_a_real_query():
    assert Bm25Index.content_terms("How did management describe competition?") == [
        "management",
        "competition",
    ]


def test_answerable_question_is_not_declined(bundle):
    qa = answer_question(
        "What did management say about capital expenditures and datacenters?",
        bundle.index,
        bundle.result.pair,
        bundle.result.comparisons,
    )
    assert qa.answer_type != "insufficient_evidence"
    assert qa.evidence


@pytest.mark.parametrize(
    "question",
    [
        "What is the chief executive officer's favourite colour?",
        "How many hectares of vineyards does the company farm?",
        "What is the recipe for the company's cafeteria lasagne?",
        "What was the aggregate remuneration of the company's veterinary staff?",
    ],
)
def test_vocabulary_gap_questions_are_declined(bundle, question):
    qa = answer_question(
        question, bundle.index, bundle.result.pair, bundle.result.comparisons
    )
    assert qa.answer_type == "insufficient_evidence"
    assert "Insufficient evidence" in qa.answer


def test_decline_message_reports_the_measured_signals(bundle):
    qa = answer_question(
        "How many hectares of vineyards does the company farm?",
        bundle.index,
        bundle.result.pair,
        bundle.result.comparisons,
    )
    assert "BM25 score" in qa.answer and "coverage" in qa.answer
    assert "hectares" in qa.answer or "vineyards" in qa.answer
    assert qa.caveat  # the indexing limitation is always stated


def test_coverage_separates_answerable_from_unanswerable(bundle):
    """Guards against loosening the gate until nothing is ever declined.

    The absolute threshold is calibrated on the full-size filings; on the
    miniature fixtures we assert the separation the threshold relies on, plus
    that the threshold still falls inside the measured gap.
    """
    from filing_change_analyst.retrieval.search import expand_query

    answerable = [
        "What did management say about capital expenditures and datacenters?",
        "What factors did management identify as affecting gross margin?",
        "How did management describe competition?",
    ]
    unanswerable = [
        "How many hectares of vineyards does the company farm?",
        "What is the recipe for the company's cafeteria lasagne?",
    ]
    a_min = min(bundle.index.query_coverage(expand_query(q))[0] for q in answerable)
    u_max = max(bundle.index.query_coverage(expand_query(q))[0] for q in unanswerable)
    assert u_max < a_min, "coverage no longer separates the two classes"
    assert u_max < MIN_QUERY_COVERAGE <= a_min
    assert MIN_TOP_SCORE > 0


def test_risk_change_question_is_answered_from_the_diff(bundle):
    qa = answer_question(
        "Which risks appear new or more prominent?",
        bundle.index,
        bundle.result.pair,
        bundle.result.comparisons,
        risk_delta=bundle.result.risk_delta,
    )
    assert qa.answer_type == "answered"
    assert qa.generated_by == "deterministic"
    assert "risk-factor headings" in qa.answer
    assert qa.caveat  # heading-level-only limitation is always attached


def test_risk_routing_requires_the_delta(bundle):
    """Without the diff the question falls through to ordinary retrieval."""
    qa = answer_question(
        "Which risks appear new or more prominent?",
        bundle.index,
        bundle.result.pair,
        bundle.result.comparisons,
        risk_delta=None,
    )
    assert qa.generated_by == "deterministic"
    assert qa.answer_type in ("llm_unavailable", "insufficient_evidence")


def test_no_llm_mode_never_claims_an_answer(bundle):
    qa = answer_question(
        "What factors did management identify as affecting gross margin?",
        bundle.index,
        bundle.result.pair,
        bundle.result.comparisons,
        client=None,
    )
    assert qa.answer_type == "llm_unavailable"
    assert "AI synthesis is unavailable" in qa.answer
    assert qa.evidence  # but the evidence is still returned for reading
