"""End-to-end smoke test, fully offline.

Loads the default company, selects a filing pair, calculates metrics, retrieves
evidence, detects changes and exports the Markdown brief — the exact path the
interview demo follows.
"""

from __future__ import annotations

import pytest

from filing_change_analyst.pipeline import apply_ai_synthesis, run_analysis
from filing_change_analyst.research.brief import brief_filename, build_markdown_brief
from filing_change_analyst.research.qa import SUGGESTED_QUESTIONS, answer_question
from filing_change_analyst.sec.client import SecError


@pytest.fixture(scope="module")
def analysis(request):
    fake = request.getfixturevalue("fake_client")
    return run_analysis("MSFT", "10-K", client=fake)


@pytest.fixture()
def bundle(fake_client):
    return run_analysis("MSFT", "10-K", client=fake_client)


def test_default_pair_is_the_two_most_recent_10ks(bundle):
    pair = bundle.result.pair
    assert pair.later.report_date.year == 2025
    assert pair.earlier.report_date.year == 2024
    assert pair.comparability_ok


def test_pipeline_produces_every_required_artefact(bundle):
    r = bundle.result
    assert len(r.comparisons) >= 6
    assert len([c for c in r.comparisons if c.status == "ok"]) >= 6
    assert r.chunks
    assert r.topics
    assert r.risk_delta is not None
    assert len(r.changes) >= 3


def test_every_change_shows_both_periods(bundle):
    for c in bundle.result.changes:
        assert c.earlier_source_ids and c.later_source_ids
        for cid in c.earlier_source_ids + c.later_source_ids:
            chunk = bundle.result.chunk_by_id(cid)
            assert chunk is not None
            assert chunk.accession in (
                bundle.result.pair.earlier.accession,
                bundle.result.pair.later.accession,
            )


def test_earlier_and_later_evidence_come_from_the_right_filings(bundle):
    r = bundle.result
    for c in r.changes:
        for cid in c.earlier_source_ids:
            assert r.chunk_by_id(cid).accession == r.pair.earlier.accession
        for cid in c.later_source_ids:
            assert r.chunk_by_id(cid).accession == r.pair.later.accession


def test_pipeline_runs_without_an_llm_and_says_so(bundle):
    from filing_change_analyst.services.llm import LlmClient

    result = apply_ai_synthesis(bundle, client=LlmClient(api_key="")).result
    assert result.llm_used is False
    assert any("AI synthesis is disabled" in w for w in result.warnings)
    # The deterministic findings survive untouched.
    assert len(result.changes) >= 3
    assert all(c.generated_by == "deterministic" for c in result.changes)


def test_markdown_brief_contains_all_nine_sections(bundle):
    md = build_markdown_brief(bundle.result)
    for heading in (
        "## 1. Executive change summary",
        "## 2. Verified financial changes",
        "## 3. Management commentary changes",
        "## 4. Risk-factor changes",
        "## 5. Bull considerations",
        "## 6. Bear considerations",
        "## 7. Questions for management",
        "## 8. Caveats and missing information",
        "## 9. Sources",
    ):
        assert heading in md, heading


def test_brief_labels_facts_calculations_and_interpretation(bundle):
    md = build_markdown_brief(bundle.result)
    assert "[CALCULATED CHANGE]" in md or "[MANAGEMENT STATEMENT]" in md
    assert "[CAVEAT]" in md
    assert "interpretation, not a recommendation" in md
    assert "not investment advice" in md


def test_brief_carries_valid_sec_provenance(bundle):
    md = build_markdown_brief(bundle.result)
    r = bundle.result
    assert r.pair.earlier.accession in md
    assert r.pair.later.accession in md
    assert "https://www.sec.gov/Archives/edgar/data/789019/" in md
    assert str(r.pair.later.report_date) in md


def test_brief_states_the_free_cash_flow_definition(bundle):
    md = build_markdown_brief(bundle.result)
    assert "PROTOTYPE DEFINITION" in md
    assert "operating cash flow minus capital expenditure" in md


def test_brief_filename_is_stable_and_descriptive(bundle):
    assert brief_filename(bundle.result) == "MSFT_10-K_2025-06-30_change_brief.md"


def test_qa_returns_cited_evidence_without_a_model(bundle):
    qa = answer_question(
        SUGGESTED_QUESTIONS[0], bundle.index, bundle.result.pair, bundle.result.comparisons
    )
    assert qa.answer_type in ("llm_unavailable", "insufficient_evidence")
    assert qa.evidence
    for e in qa.evidence:
        assert e.chunk.source_url.startswith("https://www.sec.gov/")


def test_qa_declines_when_nothing_matches(bundle):
    qa = answer_question(
        "What is the chief executive's favourite colour?",
        bundle.index,
        bundle.result.pair,
        bundle.result.comparisons,
    )
    assert qa.answer_type == "insufficient_evidence"
    assert "Insufficient evidence" in qa.answer


def test_unknown_ticker_fails_with_a_clear_message(fake_client):
    with pytest.raises(SecError) as exc:
        run_analysis("NOTATICKER", "10-K", client=fake_client)
    assert "was not found" in str(exc.value)


def test_unsupported_form_is_refused(fake_client):
    with pytest.raises(SecError) as exc:
        run_analysis("MSFT", "8-K", client=fake_client)
    assert "not supported" in str(exc.value)


def test_incompatible_pair_is_flagged_end_to_end(fake_client, fy2023, fy2025):
    from filing_change_analyst.pipeline import pair_from_filings

    bundle = run_analysis("MSFT", "10-K", client=fake_client, pair=pair_from_filings(fy2023, fy2025))
    r = bundle.result
    assert not r.pair.comparability_ok
    assert any("months apart" in w for w in r.warnings)
    assert all(c.status == "incompatible_periods" for c in r.comparisons if c.earlier.available and c.later.available)
    md = build_markdown_brief(r)
    assert "Period comparability failed" in md


def test_analysis_is_reproducible(fake_client):
    a = run_analysis("MSFT", "10-K", client=fake_client).result
    b = run_analysis("MSFT", "10-K", client=fake_client).result
    assert [c.chunk_id for c in a.chunks] == [c.chunk_id for c in b.chunks]
    assert [c.claim for c in a.changes] == [c.claim for c in b.changes]
    assert [
        (c.metric_id, c.percent_change, c.point_change) for c in a.comparisons
    ] == [(c.metric_id, c.percent_change, c.point_change) for c in b.comparisons]


def test_missing_filing_document_degrades_gracefully(
    submissions_json, companyfacts_json, later_html
):
    """Losing one document must not lose the financial comparison."""
    from tests.conftest import FakeSecClient

    class Partial(FakeSecClient):
        def filing_document(self, cik, accession, document, refresh=False):
            if accession == "0000950170-24-087843":
                raise SecError("simulated 503 from SEC")
            return super().filing_document(cik, accession, document, refresh)

    client = Partial(
        submissions_json, companyfacts_json, {"0000950170-25-100235": later_html}
    )
    r = run_analysis("MSFT", "10-K", client=client).result
    assert len([c for c in r.comparisons if c.status == "ok"]) >= 6
    assert any("Could not download the earlier filing" in w for w in r.warnings)
    md = build_markdown_brief(r)
    assert "## 2. Verified financial changes" in md
