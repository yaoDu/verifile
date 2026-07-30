"""Citation identifiers, SEC link construction and evidence-support rules."""

from __future__ import annotations

import pytest

from filing_change_analyst.retrieval.citations import (
    evidence_is_supported,
    filing_index_url,
    format_citation,
    valid_accession,
    validate_citation_ids,
    validate_metric_ids,
)


def test_accession_format_validation():
    assert valid_accession("0000950170-25-100235")
    assert not valid_accession("950170-25-100235")
    assert not valid_accession("0000950170251002350")
    assert not valid_accession("")


def test_filing_index_url_is_canonical():
    url = filing_index_url("0000789019", "0000950170-25-100235")
    assert url == (
        "https://www.sec.gov/Archives/edgar/data/789019/000095017025100235/"
        "0000950170-25-100235-index.htm"
    )


def test_malformed_accession_raises_rather_than_building_a_bad_link():
    with pytest.raises(ValueError):
        filing_index_url("0000789019", "not-an-accession")


def test_filing_urls_use_the_unpadded_cik(fy2025):
    assert "/edgar/data/789019/" in fy2025.primary_document_url
    assert fy2025.primary_document_url.endswith("msft-20250630.htm")
    assert "0000950170-25-100235" not in fy2025.primary_document_url  # path uses no dashes


def test_unknown_citation_ids_are_dropped(earlier_html, fy2024):
    from filing_change_analyst.retrieval.chunking import chunk_filing
    from filing_change_analyst.sec.sections import extract_sections

    sections, _, _strategy = extract_sections(earlier_html)
    chunks = chunk_filing(sections, fy2024, "earlier")
    allowed = {c.chunk_id for c in chunks}
    real = chunks[0].chunk_id

    kept, dropped = validate_citation_ids([real, "E-item_7_mdna-999-fake01", "[" + real + "]"], allowed)
    assert kept == [real]
    assert dropped == ["E-item_7_mdna-999-fake01"]


def test_metric_id_validation(fact_store, pair):
    from filing_change_analyst.analytics.comparisons import compare_filings

    comps, _, _ = compare_filings(fact_store, pair)
    kept, dropped = validate_metric_ids(["revenue", "made_up_metric", "capex"], comps)
    assert kept == ["revenue", "capex"]
    assert dropped == ["made_up_metric"]


def test_cross_period_claims_need_both_sides():
    ok, _ = evidence_is_supported(["a"], ["b"])
    assert ok
    ok, why = evidence_is_supported(["a"], [])
    assert not ok and "later" in why
    ok, why = evidence_is_supported([], ["b"])
    assert not ok and "earlier" in why
    ok, why = evidence_is_supported([], [])
    assert not ok and "No source evidence" in why


def test_citation_string_has_no_page_number_and_carries_provenance(earlier_html, fy2024):
    from filing_change_analyst.retrieval.chunking import chunk_filing
    from filing_change_analyst.sec.sections import extract_sections

    sections, _, _strategy = extract_sections(earlier_html)
    chunk = chunk_filing(sections, fy2024, "earlier")[0]
    citation = format_citation(chunk)
    assert fy2024.accession in citation
    assert "sec.gov" in citation
    assert chunk.section_label in citation
    assert "page" not in citation.lower()


def test_every_brief_citation_resolves(fact_store, pair, earlier_html, later_html, fy2024, fy2025):
    """Integration guard: no brief may reference an id that is not in the result."""
    from filing_change_analyst.analytics.comparisons import compare_filings
    from filing_change_analyst.models import AnalysisResult
    from filing_change_analyst.research.change_detection import detect_material_changes
    from filing_change_analyst.retrieval.chunking import chunk_filing
    from filing_change_analyst.retrieval.index import Bm25Index
    from filing_change_analyst.retrieval.search import probe_all_topics
    from filing_change_analyst.sec.sections import extract_sections

    chunks = []
    for html, filing, period in ((earlier_html, fy2024, "earlier"), (later_html, fy2025, "later")):
        sections, _, _strategy = extract_sections(html)
        chunks.extend(chunk_filing(sections, filing, period))
    index = Bm25Index(chunks)
    comps, _, _ = compare_filings(fact_store, pair)
    changes = detect_material_changes(probe_all_topics(index), comps)
    result = AnalysisResult(pair=pair, comparisons=comps, chunks=chunks, changes=changes)

    for c in changes:
        for cid in c.earlier_source_ids + c.later_source_ids:
            assert result.chunk_by_id(cid) is not None, cid
        for mid in c.related_metric_ids:
            assert result.comparison_by_id(mid) is not None, mid
