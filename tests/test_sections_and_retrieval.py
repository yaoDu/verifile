"""Section extraction, chunk provenance, BM25 retrieval and topic probes."""

from __future__ import annotations

import pytest

from filing_change_analyst.research.change_detection import (
    detect_material_changes,
    diff_risk_headings,
)
from filing_change_analyst.retrieval.chunking import chunk_filing
from filing_change_analyst.retrieval.index import Bm25Index
from filing_change_analyst.retrieval.search import (
    TOPICS_BY_ID,
    expand_query,
    probe_topic,
    retrieve_for_question,
    sections_for_question,
)
from filing_change_analyst.sec.sections import (
    extract_risk_headings,
    extract_sections,
    html_to_text,
)

# --------------------------------------------------------------------------- #
# Section extraction
# --------------------------------------------------------------------------- #


def test_required_sections_are_extracted(later_html):
    sections, notes = extract_sections(later_html)
    for required in ("item_1_business", "item_1a_risk_factors", "item_7_mdna"):
        assert required in sections, notes
        assert sections[required].char_count > 200


def test_section_text_starts_at_the_item_heading(later_html):
    sections, _ = extract_sections(later_html)
    assert sections["item_1a_risk_factors"].text.startswith("ITEM 1A.")
    assert sections["item_7_mdna"].text.startswith("ITEM 7.")


def test_table_of_contents_is_not_mistaken_for_the_section(later_html):
    sections, _ = extract_sections(later_html)
    # The TOC uses title case; a TOC match would produce a tiny section.
    assert sections["item_1_business"].char_count > 500


def test_running_page_headers_are_stripped(later_html):
    text = html_to_text(later_html)
    assert "\nPART I\n" not in f"\n{text}\n"
    assert "ITEM 1A. RISK FACTORS" in text


def test_sections_do_not_bleed_into_each_other(later_html):
    sections, _ = extract_sections(later_html)
    assert "ITEM 1A." not in sections["item_1_business"].text
    assert "ITEM 7." not in sections["item_1a_risk_factors"].text


def test_html_is_never_passed_through(later_html):
    text = html_to_text(later_html)
    assert "<" not in text and "font-weight" not in text


def test_extraction_failure_is_reported_not_hidden():
    sections, notes = extract_sections(b"<html><body><p>Nothing useful here.</p></body></html>")
    assert sections == {}
    assert any("No upper-case item headings" in n for n in notes)


# --------------------------------------------------------------------------- #
# Risk headings
# --------------------------------------------------------------------------- #


def test_risk_headings_are_extracted_from_item_1a_only(later_html):
    headings, confidence = extract_risk_headings(later_html)
    assert len(headings) >= 5
    assert confidence in ("high", "moderate")
    assert any("intense competition" in h for h in headings)
    assert not any("Fiscal Year" in h for h in headings)


def test_risk_diff_finds_added_and_removed(earlier_html, later_html):
    e_head, _ = extract_risk_headings(earlier_html)
    l_head, _ = extract_risk_headings(later_html)
    delta = diff_risk_headings(e_head, l_head)
    assert any("datacenter capacity" in h for h in delta.added)
    assert any("goodwill" in h for h in delta.removed)
    assert len(delta.retained) >= 4


def test_reworded_risk_counts_as_retained_not_added_and_removed():
    delta = diff_risk_headings(
        ["We face intense competition across all markets, which may adversely affect results."],
        ["We face intense competition across all markets, which could adversely affect results."],
    )
    assert delta.added == []
    assert delta.removed == []
    assert len(delta.retained) == 1


# --------------------------------------------------------------------------- #
# Chunking and provenance
# --------------------------------------------------------------------------- #


@pytest.fixture()
def index(earlier_html, later_html, fy2024, fy2025):
    chunks = []
    for html, filing, period in (
        (earlier_html, fy2024, "earlier"),
        (later_html, fy2025, "later"),
    ):
        sections, _ = extract_sections(html)
        headings, _ = extract_risk_headings(html)
        chunks.extend(chunk_filing(sections, filing, period, headings=headings))
    return Bm25Index(chunks)


def test_every_chunk_carries_full_provenance(earlier_html, fy2024):
    sections, _ = extract_sections(earlier_html)
    chunks = chunk_filing(sections, fy2024, "earlier")
    assert chunks
    for c in chunks:
        assert c.chunk_id and c.accession == fy2024.accession
        assert c.section_id and c.section_label
        assert c.source_url.startswith("https://www.sec.gov/Archives/")
        assert c.report_date == fy2024.report_date


def test_chunk_ids_are_unique_and_stable(earlier_html, fy2024):
    sections, _ = extract_sections(earlier_html)
    a = chunk_filing(sections, fy2024, "earlier")
    b = chunk_filing(sections, fy2024, "earlier")
    assert [c.chunk_id for c in a] == [c.chunk_id for c in b]
    assert len({c.chunk_id for c in a}) == len(a)


# --------------------------------------------------------------------------- #
# Retrieval
# --------------------------------------------------------------------------- #


def test_search_respects_the_period_filter(index):
    later = index.search("datacenter capacity power", period="later", top_k=5)
    assert later and all(r.chunk.period == "later" for r in later)


def test_search_respects_the_section_filter(index):
    hits = index.search("competition", section_ids=("item_1a_risk_factors",), top_k=5)
    assert hits and all(r.chunk.section_id == "item_1a_risk_factors" for r in hits)


def test_search_returns_deterministic_ordering(index):
    a = index.search("capital expenditures datacenter", top_k=5)
    b = index.search("capital expenditures datacenter", top_k=5)
    assert [r.chunk.chunk_id for r in a] == [r.chunk.chunk_id for r in b]


def test_unmatched_query_returns_nothing(index):
    assert index.search("zzzqqqxyz nonexistentterm", top_k=5) == []


def test_phrase_frequency_does_not_double_count_overlaps(index):
    counts = index.phrase_frequency(["artificial intelligence", "intelligence"], period="later")
    assert counts["intelligence"] == 0  # consumed by the longer phrase


def test_topic_probe_returns_both_periods(index):
    probe = probe_topic(index, TOPICS_BY_ID["capex_infrastructure"], top_k=3)
    assert probe.earlier and probe.later
    assert probe.has_both_sides
    assert "per 10,000 tokens" in probe.signal_note


def test_capacity_emphasis_increased_in_the_later_fixture(index):
    probe = probe_topic(index, TOPICS_BY_ID["capacity_constraints"], top_k=3)
    assert probe.emphasis_delta > 0


def test_question_routing_picks_the_risk_section():
    assert sections_for_question("Which risks are new?") == ("item_1a_risk_factors",)
    assert "item_7_mdna" in sections_for_question("What drove the change in gross margin?")


def test_query_expansion_adds_domain_synonyms():
    assert "datacenters" in expand_query("What changed in capex discussion?")
    assert "cost of revenue" in expand_query("What affected margin?")


def test_retrieval_for_question_balances_both_periods(index):
    route = retrieve_for_question(index, "What changed in capital expenditure discussion?")
    periods = {e.chunk.period for e in route.evidence}
    assert periods == {"earlier", "later"}


def test_material_changes_require_both_period_evidence(index, fact_store, pair):
    from filing_change_analyst.analytics.comparisons import compare_filings
    from filing_change_analyst.retrieval.search import probe_all_topics

    comps, _, _ = compare_filings(fact_store, pair)
    topics = probe_all_topics(index)
    changes = detect_material_changes(topics, comps)
    assert changes
    for c in changes:
        assert c.earlier_source_ids and c.later_source_ids
        assert c.caveat
        assert c.evidence_strength in ("high", "moderate", "low")


def test_one_metric_cannot_anchor_every_change(index, fact_store, pair):
    from filing_change_analyst.analytics.comparisons import compare_filings
    from filing_change_analyst.research.change_detection import MAX_CLAIMS_PER_METRIC
    from filing_change_analyst.retrieval.search import probe_all_topics

    comps, _, _ = compare_filings(fact_store, pair)
    changes = detect_material_changes(probe_all_topics(index), comps)
    usage: dict[str, int] = {}
    for c in changes:
        for mid in c.related_metric_ids:
            usage[mid] = usage.get(mid, 0) + 1
    assert all(v <= MAX_CLAIMS_PER_METRIC for v in usage.values()), usage
