"""Form-aware section extraction.

A 10-K and a 10-Q number their items on unrelated schemes. Reading a 10-Q with
the 10-K map did not merely mislabel sections — it lost them. There is no Item 7
in a 10-Q, so MD&A was never found; because MD&A was also what qualified an
anchoring strategy, the correct one was rejected on every 10-Q and extraction
fell through to the least precise strategy, which matches the table of contents.
The result was an 85-character "MD&A", the whole document filed as "Risk
Factors", and every citation naming the wrong section.

These tests pin the outline, the Part II numbering restart, and the fact that a
10-K still reads exactly as it did before.
"""

from __future__ import annotations

import pytest

from filing_change_analyst.sec.sections import (
    extract_risk_headings,
    extract_sections,
    find_item_offsets,
    html_to_text,
    outline_for,
)

BODY = "Body text for this section. " * 120


def _10q_html(*, risk_body: str = BODY, upper: bool = True) -> bytes:
    """A 10-Q with the real item structure, including Part II's restart.

    Item 1 and Item 2 each appear twice, which is what makes the item number
    alone insufficient to identify a section.
    """
    items = (
        ("1", "FINANCIAL STATEMENTS", BODY),
        ("2", "MANAGEMENT'S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION", BODY),
        ("3", "QUANTITATIVE AND QUALITATIVE DISCLOSURES ABOUT MARKET RISK", BODY),
        ("4", "CONTROLS AND PROCEDURES", BODY),
        ("1", "LEGAL PROCEEDINGS", BODY),
        ("1A", "RISK FACTORS", risk_body),
        ("2", "UNREGISTERED SALES OF EQUITY SECURITIES AND USE OF PROCEEDS", BODY),
        ("6", "EXHIBITS", BODY),
    )
    body = "".join(
        f"<p>ITEM {n}. {t}</p><p>{b}</p>"
        if upper
        else f"<p>Item {n}. {t.title()}</p><p>{b}</p>"
        for n, t, b in items
    )
    return f"<html><body>{body}</body></html>".encode()


# --------------------------------------------------------------------------- #
# The outline itself
# --------------------------------------------------------------------------- #


def test_10q_mdna_is_item_2_not_item_7():
    sections, _, strategy = extract_sections(_10q_html(), "10-Q")
    mdna = sections["item_7_mdna"]
    assert strategy == "upper_case"
    assert mdna.text.startswith("ITEM 2.")
    assert mdna.char_count > 1500
    assert mdna.label == "Part I Item 2 — Management's Discussion and Analysis"


def test_10q_item_1_is_financial_statements_not_business():
    """67,000 characters of financial statements used to be filed under 'Business'."""
    sections, _, _ = extract_sections(_10q_html(), "10-Q")
    assert "item_1_business" not in sections
    fin = sections["item_8_financial_statements"]
    assert fin.text.startswith("ITEM 1.")
    assert fin.label == "Part I Item 1 — Financial Statements"


def test_part_two_numbering_restart_is_resolved_by_position():
    """Item 1 appears twice: Financial Statements, then Legal Proceedings.

    Keying anchors on the item number alone made the second overwrite the first
    (or be dropped), depending on parse order.
    """
    sections, _, _ = extract_sections(_10q_html(), "10-Q")
    assert sections["item_8_financial_statements"].text.startswith("ITEM 1. FINANCIAL")
    assert sections["item_1a_risk_factors"].text.startswith("ITEM 1A.")
    # Part II Item 1 is Legal Proceedings, so it must not be read as Part I's.
    assert "LEGAL PROCEEDINGS" not in sections["item_8_financial_statements"].text


def test_risk_factors_stop_at_the_next_part_two_item():
    """Risk Factors used to swallow every Part II item that followed it."""
    sections, _, _ = extract_sections(_10q_html(), "10-Q")
    risk = sections["item_1a_risk_factors"].text
    assert "UNREGISTERED SALES" not in risk
    assert "EXHIBITS" not in risk


def test_10q_labels_name_the_part_so_a_citation_is_checkable():
    sections, _, _ = extract_sections(_10q_html(), "10-Q")
    labels = {s.label for s in sections.values()}
    assert labels == {
        "Part I Item 1 — Financial Statements",
        "Part I Item 2 — Management's Discussion and Analysis",
        "Part I Item 3 — Quantitative and Qualitative Disclosures About Market Risk",
        "Part II Item 1A — Risk Factors",
    }
    assert not any("Item 7" in label for label in labels)


def test_10q_does_not_report_a_missing_business_section():
    """A 10-Q has no Item 1 Business; complaining about it is noise, not a finding."""
    _, notes, _ = extract_sections(_10q_html(), "10-Q")
    assert not any("Business" in n for n in notes)


# --------------------------------------------------------------------------- #
# Strategy selection
# --------------------------------------------------------------------------- #


def test_a_10q_is_not_pushed_onto_the_title_only_fallback():
    """The defect: no Item 7 exists, so the correct strategy never qualified."""
    _, notes, strategy = extract_sections(_10q_html(), "10-Q")
    assert strategy == "upper_case"
    assert not any("least precise strategy" in n for n in notes)


def test_mixed_case_10q_is_extracted():
    sections, _, strategy = extract_sections(_10q_html(upper=False), "10-Q")
    assert strategy == "mixed_case"
    assert sections["item_7_mdna"].char_count > 1500


def test_a_token_risk_section_does_not_reject_the_strategy():
    """Measured on AAPL and PG: a 10-Q's Item 1A is often one line pointing at the
    10-K. Requiring it in substance would reject a correct extraction and force
    the table-of-contents fallback."""
    sections, _, strategy = extract_sections(
        _10q_html(risk_body="There have been no material changes to our risk factors."), "10-Q"
    )
    assert strategy == "upper_case"
    assert sections["item_7_mdna"].char_count > 1500
    assert sections["item_1a_risk_factors"].char_count < 500


def test_risk_headings_are_read_from_the_10q_risk_span():
    html = _10q_html().replace(
        b"<p>ITEM 1A. RISK FACTORS</p>",
        b"<p>ITEM 1A. RISK FACTORS</p>"
        b"<p><b>We face intense competition that may adversely affect our results.</b></p>",
    )
    headings, confidence = extract_risk_headings(html, "upper_case", "10-Q")
    assert any("intense competition" in h for h in headings)
    assert confidence in ("high", "moderate")


# --------------------------------------------------------------------------- #
# The 10-K path is untouched
# --------------------------------------------------------------------------- #


def test_10k_outline_still_maps_item_7_to_mdna(later_html):
    sections, _, strategy = extract_sections(later_html, "10-K")
    assert strategy == "upper_case"
    assert sections["item_7_mdna"].text.startswith("ITEM 7.")
    assert sections["item_7_mdna"].label == "Item 7 — Management's Discussion and Analysis"
    assert sections["item_1_business"].text.startswith("ITEM 1. BUSINESS")


def test_form_defaults_to_10k_for_callers_that_do_not_say(later_html):
    assert extract_sections(later_html)[0].keys() == extract_sections(later_html, "10-K")[0].keys()


@pytest.mark.parametrize(
    ("form", "expected_mdna_number"),
    [("10-K", "7"), ("10-k", "7"), ("10-K/A", "7"), ("10-Q", "2"), ("10-Q/A", "2"), (None, "7")],
)
def test_outline_selection_is_form_aware_and_tolerates_amendments(form, expected_mdna_number):
    mdna = next(i for i in outline_for(form) if i.section_id == "item_7_mdna")
    assert mdna.number == expected_mdna_number


def test_a_stray_cross_reference_does_not_drag_the_walk_backwards():
    """A body reference to another form's item numbering must not claim a slot."""
    html = _10q_html().replace(
        b"<p>ITEM 6. EXHIBITS</p>", b"<p>ITEM 14. SOMETHING NOT IN A 10-Q</p><p>ITEM 6. EXHIBITS</p>"
    )
    sections, _, _ = extract_sections(html, "10-Q")
    assert sections["item_7_mdna"].text.startswith("ITEM 2.")
    assert sections["item_1a_risk_factors"].text.startswith("ITEM 1A.")


def test_offsets_are_keyed_on_outline_position_not_item_number():
    """Two 'Item 1's cannot both be key '1'; positions keep them distinct."""
    text = html_to_text(_10q_html())
    offsets = find_item_offsets(text, "upper_case", "10-Q")
    outline = outline_for("10-Q")
    claimed = [outline[i].label for i in sorted(offsets, key=lambda i: offsets[i])]
    assert claimed[0] == "Part I Item 1 — Financial Statements"
    assert "Part II Item 1 — Legal Proceedings" in claimed
    assert len(set(offsets.values())) == len(offsets)  # no two items share an offset
