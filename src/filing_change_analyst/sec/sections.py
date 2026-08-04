"""HTML filing → plain text → named sections.

Filing HTML has no stable page numbering, so this module never invents page
numbers. It anchors evidence on *section names* plus the SEC accession number
and document URL, which are stable and verifiable.

Two things vary and both are handled explicitly:

*Which items exist* depends on the form. A 10-K and a 10-Q number their items on
unrelated schemes, so each form has its own outline (see below).

*How the item heading is marked up* depends on the filer, so extraction tries
three anchoring conventions in order of precision and reports which one worked.
This was built after measuring ten large filers: MSFT uses upper case,
Workiva-generated filings (AAPL, NVDA, BRK-B) use title case, and P&G omits item
numbers from the body entirely. Anchoring on upper case alone silently produced
*zero* sections for four of the ten.

Where every strategy fails, the caller is told extraction failed rather than being
handed an empty result that looks like "this filing has no risk factors".
"""

from __future__ import annotations

import logging
import re
import warnings
from typing import NamedTuple

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from ..models import FilingSection

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

log = logging.getLogger(__name__)

# Running page headers and page numbers, removed before anchoring.
_NOISE_LINE = re.compile(
    r"""^(
        PART\s+[IVX]+(\s*,\s*[IVX]+)*
      | Item\s+\d+[A-C]?(\s*,\s*\d+[A-C]?)*\.?
      | \d{1,4}
      | FORM\s+10-[KQ]
      | \(?continued\)?
    )$""",
    re.VERBOSE,
)

# Anchoring strategies, tried in order of precision. Filers do not agree on how
# they render item headings, and measuring ten large filers showed three distinct
# conventions:
#
#   upper_case  MSFT-style — "ITEM 1A. RISK FACTORS"
#   mixed_case  Workiva-generated (AAPL, NVDA, BRK-B) — "Item 1A. Risk Factors"
#   title_only  P&G-style — no item prefix in the body at all, just "Risk Factors"
#
# The table of contents is not a problem for the first two: filers put the item
# number and the item title in separate table cells, so the flattened TOC line is
# a bare "Item 1A." which `_NOISE_LINE` already removes. `title_only` has no such
# protection and is reported at low confidence.
_ITEM_ANCHOR_UPPER = re.compile(r"(?m)^ITEM\s+(\d{1,2}[A-C]?)\s*[\.\:\-–—]")
_ITEM_ANCHOR_ANY_CASE = re.compile(r"(?mi)^ITEM\s+(\d{1,2}[A-C]?)\s*[\.\:\-–—]")

# Strategy names, most precise first.
STRATEGIES = ("upper_case", "mixed_case", "title_only")

MIN_HEADING_CHARS = 35
MAX_HEADING_CHARS = 320


# --------------------------------------------------------------------------- #
# What the items are, per form
#
# A 10-K and a 10-Q number their items on unrelated schemes. MD&A is Item 7 in a
# 10-K and Item 2 in a 10-Q; a 10-Q's Item 1 is the financial statements, not the
# business description; and a 10-Q restarts numbering at Part II, so "Item 1" and
# "Item 2" each occur twice in one document.
#
# Reading a 10-Q through the 10-K map therefore does not merely mislabel. It
# drops MD&A on the floor (a 10-Q has no Item 7 to find), files the financial
# statements under "Business", and — because no Item 7 is ever located — rejects
# the correct anchoring strategy and falls through to the least precise one,
# which matches the table of contents and hands back the whole document as
# "Risk Factors". Every citation from that run names the wrong section.
#
# Each outline lists a form's items in the order they appear in the document.
# `section_id` is the semantic slot this tool retrieves from, deliberately shared
# across forms so a topic probe for MD&A finds it in either. Items with no slot
# are still listed: an item is what bounds the end of the item before it.
# `title` anchors the item when the body carries no item number at all.
# --------------------------------------------------------------------------- #


class OutlineItem(NamedTuple):
    """One item in a form's prescribed order."""

    number: str
    section_id: str | None
    label: str
    title: re.Pattern[str] | None = None


_OUTLINE_10K: tuple[OutlineItem, ...] = (
    OutlineItem("1", "item_1_business", "Item 1 — Business", re.compile(r"(?mi)^BUSINESS\.?$")),
    OutlineItem(
        "1A", "item_1a_risk_factors", "Item 1A — Risk Factors", re.compile(r"(?mi)^RISK FACTORS\.?$")
    ),
    OutlineItem(
        "1B", None, "Item 1B — Unresolved Staff Comments",
        re.compile(r"(?mi)^UNRESOLVED STAFF COMMENTS\.?$"),
    ),
    OutlineItem("1C", None, "Item 1C — Cybersecurity", re.compile(r"(?mi)^CYBERSECURITY\.?$")),
    OutlineItem("2", None, "Item 2 — Properties", re.compile(r"(?mi)^PROPERTIES\.?$")),
    OutlineItem(
        "3", None, "Item 3 — Legal Proceedings", re.compile(r"(?mi)^LEGAL PROCEEDINGS\.?$")
    ),
    OutlineItem("4", None, "Item 4 — Mine Safety Disclosures"),
    OutlineItem(
        "5", None, "Item 5 — Market for Registrant's Common Equity",
        re.compile(r"(?mi)^MARKET FOR (THE )?REGISTRANT.{0,60}$"),
    ),
    OutlineItem("6", None, "Item 6 — [Reserved]"),
    OutlineItem(
        "7", "item_7_mdna", "Item 7 — Management's Discussion and Analysis",
        re.compile(r"(?mi)^MANAGEMENT.S DISCUSSION AND ANALYSIS.{0,80}$"),
    ),
    OutlineItem(
        "7A", "item_7a_market_risk",
        "Item 7A — Quantitative and Qualitative Disclosures About Market Risk",
        re.compile(r"(?mi)^QUANTITATIVE AND QUALITATIVE DISCLOSURES ABOUT MARKET RISK\.?$"),
    ),
    OutlineItem(
        "8", "item_8_financial_statements", "Item 8 — Financial Statements",
        re.compile(r"(?mi)^FINANCIAL STATEMENTS AND SUPPLEMENTARY DATA\.?$"),
    ),
    OutlineItem("9", None, "Item 9 — Changes in and Disagreements with Accountants"),
    OutlineItem("9A", None, "Item 9A — Controls and Procedures"),
    OutlineItem("9B", None, "Item 9B — Other Information"),
    OutlineItem("9C", None, "Item 9C — Disclosure Regarding Foreign Jurisdictions"),
    OutlineItem("10", None, "Item 10 — Directors and Executive Officers"),
    OutlineItem("11", None, "Item 11 — Executive Compensation"),
    OutlineItem("12", None, "Item 12 — Security Ownership"),
    OutlineItem("13", None, "Item 13 — Certain Relationships and Related Transactions"),
    OutlineItem("14", None, "Item 14 — Principal Accountant Fees and Services"),
    OutlineItem("15", None, "Item 15 — Exhibits and Financial Statement Schedules"),
    OutlineItem("16", None, "Item 16 — Form 10-K Summary"),
)

_OUTLINE_10Q: tuple[OutlineItem, ...] = (
    # Part I — Financial Information. The statements here are the same content a
    # 10-K files under Item 8, so they share its slot.
    OutlineItem(
        "1", "item_8_financial_statements", "Part I Item 1 — Financial Statements",
        re.compile(r"(?mi)^FINANCIAL STATEMENTS\.?$"),
    ),
    OutlineItem(
        "2", "item_7_mdna", "Part I Item 2 — Management's Discussion and Analysis",
        re.compile(r"(?mi)^MANAGEMENT.S DISCUSSION AND ANALYSIS.{0,80}$"),
    ),
    OutlineItem(
        "3", "item_7a_market_risk",
        "Part I Item 3 — Quantitative and Qualitative Disclosures About Market Risk",
        re.compile(r"(?mi)^QUANTITATIVE AND QUALITATIVE DISCLOSURES ABOUT MARKET RISK\.?$"),
    ),
    OutlineItem(
        "4", None, "Part I Item 4 — Controls and Procedures",
        re.compile(r"(?mi)^CONTROLS AND PROCEDURES\.?$"),
    ),
    # Part II — Other Information. Numbering restarts from 1 here, which is why
    # anchors are matched against this sequence rather than by number alone.
    OutlineItem(
        "1", None, "Part II Item 1 — Legal Proceedings",
        re.compile(r"(?mi)^LEGAL PROCEEDINGS\.?$"),
    ),
    OutlineItem(
        "1A", "item_1a_risk_factors", "Part II Item 1A — Risk Factors",
        re.compile(r"(?mi)^RISK FACTORS\.?$"),
    ),
    OutlineItem(
        "2", None, "Part II Item 2 — Unregistered Sales of Equity Securities",
        re.compile(r"(?mi)^UNREGISTERED SALES OF EQUITY SECURITIES.{0,60}$"),
    ),
    OutlineItem("3", None, "Part II Item 3 — Defaults Upon Senior Securities"),
    OutlineItem("4", None, "Part II Item 4 — Mine Safety Disclosures"),
    OutlineItem(
        "5", None, "Part II Item 5 — Other Information",
        re.compile(r"(?mi)^OTHER INFORMATION\.?$"),
    ),
    OutlineItem("6", None, "Part II Item 6 — Exhibits", re.compile(r"(?mi)^EXHIBITS\.?$")),
)

DEFAULT_FORM = "10-K"
_OUTLINES: dict[str, tuple[OutlineItem, ...]] = {"10-K": _OUTLINE_10K, "10-Q": _OUTLINE_10Q}


def form_key(form: str | None) -> str:
    """Normalise a form type. An amendment shares its base form's outline."""
    return (form or DEFAULT_FORM).strip().upper().split("/")[0]


def outline_for(form: str | None) -> tuple[OutlineItem, ...]:
    """The item outline for a form, defaulting to the 10-K's."""
    return _OUTLINES.get(form_key(form), _OUTLINE_10K)


# A strategy must locate these sections in substance before it is accepted;
# otherwise the next, less precise strategy is tried. This is what stops a
# table-of-contents match being taken for the section itself.
_ANCHOR_SECTIONS: dict[str, tuple[str, ...]] = {
    "10-K": ("item_1_business", "item_1a_risk_factors", "item_7_mdna"),
    # A 10-Q has no business description at all, and its Item 1A is routinely a
    # single sentence referring back to the 10-K. MD&A is the only section a 10-Q
    # always carries in substance, so requiring more would reject the correct
    # extraction and force the fallback that caused the original defect.
    "10-Q": ("item_7_mdna",),
}

# Sections whose absence is worth reporting to the analyst.
_EXPECTED_SECTIONS: dict[str, tuple[str, ...]] = {
    "10-K": ("item_1_business", "item_1a_risk_factors", "item_7_mdna"),
    "10-Q": ("item_7_mdna", "item_1a_risk_factors"),
}

_MIN_SECTION_CHARS = 1500


def html_to_text(raw: bytes | str) -> str:
    """Flatten filing HTML to normalised plain text.

    Filing content is untrusted input: all markup, scripts and styles are
    discarded here and never re-rendered, so nothing downstream can execute or
    inject markup into the UI.
    """
    soup = _soup(raw)
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text("\n")
    return _normalise(text)


def _soup(raw: bytes | str) -> BeautifulSoup:
    return BeautifulSoup(raw, "lxml")


def _normalise(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    lines = [ln.strip() for ln in text.split("\n")]
    kept = [ln for ln in lines if ln and not _NOISE_LINE.match(ln)]
    out = "\n".join(kept)
    return re.sub(r"\n{3,}", "\n\n", out)


def _claim(
    outline: tuple[OutlineItem, ...], number: str, cursor: int, taken: dict[int, int]
) -> int | None:
    """Which outline entry an ``Item <number>`` anchor refers to.

    Walking forward is what separates a 10-Q's two "Item 1"s: the second can only
    be Part II's, because Part I's has already been consumed. An anchor with no
    entry left ahead of it falls back to any unclaimed entry with that number, so
    a filer who prints an item out of order is still read rather than dropped;
    an anchor matching no entry at all is ignored, which is what a stray
    cross-reference to another form's item numbering looks like.
    """
    for idx in range(cursor, len(outline)):
        if outline[idx].number == number and idx not in taken:
            return idx
    for idx, item in enumerate(outline):
        if item.number == number and idx not in taken:
            return idx
    return None


def _offsets_from_pattern(
    text: str, pattern: re.Pattern[str], outline: tuple[OutlineItem, ...]
) -> dict[int, int]:
    """Match item anchors, in document order, against the form's outline."""
    offsets: dict[int, int] = {}
    cursor = 0
    for m in pattern.finditer(text):
        idx = _claim(outline, m.group(1).upper(), cursor, offsets)
        if idx is None:
            continue
        offsets[idx] = m.start()
        cursor = max(cursor, idx + 1)
    return offsets


def _offsets_from_titles(text: str, outline: tuple[OutlineItem, ...]) -> dict[int, int]:
    """Locate sections by bare title when the body carries no item prefix.

    For each title, the *last* standalone occurrence is taken: filers repeat the
    title in cross-references and the table of contents earlier in the document,
    and the section body itself is the final one.
    """
    offsets: dict[int, int] = {}
    for idx, item in enumerate(outline):
        if item.title is None:
            continue
        matches = list(item.title.finditer(text))
        if matches:
            offsets[idx] = matches[-1].start()
    return offsets


def _slice_sections(
    text: str, offsets: dict[int, int], outline: tuple[OutlineItem, ...]
) -> dict[str, FilingSection]:
    positions = sorted(offsets.items(), key=lambda p: p[1])
    out: dict[str, FilingSection] = {}
    for n, (idx, start) in enumerate(positions):
        item = outline[idx]
        if item.section_id is None:
            continue  # anchored only to bound the section before it
        end = positions[n + 1][1] if n + 1 < len(positions) else len(text)
        body = text[start:end].strip()
        note = ""
        if len(body) < 500:
            note = (
                f"Only {len(body)} characters were captured for {item.label}; "
                "the heading may have been matched inside a table of contents."
            )
        out[item.section_id] = FilingSection(
            section_id=item.section_id,
            label=item.label,
            text=body,
            char_count=len(body),
            extraction_note=note,
        )
    return out


def _strategy_is_usable(sections: dict[str, FilingSection], form: str) -> bool:
    """A strategy is accepted only if it produced substantial required sections."""
    required = _ANCHOR_SECTIONS.get(form_key(form), _ANCHOR_SECTIONS[DEFAULT_FORM])
    for section_id in required:
        section = sections.get(section_id)
        if section is None or section.char_count < _MIN_SECTION_CHARS:
            return False
    return True


def find_item_offsets(
    text: str, strategy: str = "upper_case", form: str = DEFAULT_FORM
) -> dict[int, int]:
    """Map outline index → character offset, using one anchoring strategy.

    Keyed on the position in the form's outline rather than the printed item
    number, because a 10-Q's numbering is not unique within the document.
    """
    outline = outline_for(form)
    if strategy == "upper_case":
        return _offsets_from_pattern(text, _ITEM_ANCHOR_UPPER, outline)
    if strategy == "mixed_case":
        return _offsets_from_pattern(text, _ITEM_ANCHOR_ANY_CASE, outline)
    if strategy == "title_only":
        return _offsets_from_titles(text, outline)
    raise ValueError(f"Unknown anchoring strategy: {strategy}")


def extract_sections(
    raw: bytes | str, form: str = DEFAULT_FORM
) -> tuple[dict[str, FilingSection], list[str], str]:
    """Extract the sections this prototype uses.

    ``form`` selects the item outline; passing the wrong one does not just
    mislabel sections, it loses them (see the outline tables above).

    Returns ``(sections, notes, strategy)``. ``strategy`` names which anchoring
    convention actually worked, or ``"none"`` when extraction failed — it is
    surfaced in the UI and the brief so an analyst can see how the text was
    located rather than having to trust it.
    """
    text = html_to_text(raw)
    outline = outline_for(form)
    notes: list[str] = []

    best: dict[str, FilingSection] = {}
    used = "none"
    for strategy in STRATEGIES:
        offsets = find_item_offsets(text, strategy, form)
        if not offsets:
            continue
        candidate = _slice_sections(text, offsets, outline)
        if _strategy_is_usable(candidate, form):
            best, used = candidate, strategy
            break
        # Keep the most complete attempt so a partial result is still returned.
        if len(candidate) > len(best):
            best, used = candidate, strategy

    if not best:
        notes.append(
            "No item headings could be located in this document by any of the "
            f"{len(STRATEGIES)} supported conventions ({', '.join(STRATEGIES)}); section "
            "extraction failed and no text evidence is available for this filing."
        )
        return {}, notes, "none"

    if used != STRATEGIES[0]:
        notes.append(
            f"Sections were located using the '{used}' heading convention rather than the "
            "preferred upper-case convention."
        )
    if used == "title_only":
        notes.append(
            "Sections were located by bare section title because the filing body carries no "
            "item numbers. This is the least precise strategy: a cross-reference to a section "
            "title can be mistaken for the section itself. Treat these excerpts with extra care."
        )

    notes.extend(s.extraction_note for s in best.values() if s.extraction_note)
    labels = {i.section_id: i.label for i in outline if i.section_id}
    for section_id in _EXPECTED_SECTIONS.get(form_key(form), _EXPECTED_SECTIONS[DEFAULT_FORM]):
        if section_id not in best:
            notes.append(
                f"{labels.get(section_id, section_id)} could not be located in this filing; "
                "evidence for it will be unavailable."
            )
    return best, notes, used


def section_confidence(strategy: str) -> str:
    return {"upper_case": "high", "mixed_case": "high", "title_only": "low"}.get(strategy, "low")


def extract_bold_headings(raw: bytes | str) -> list[str]:
    """Bold/strong runs that look like sub-headings, in document order.

    Filers bold their risk-factor headings, which gives a far more reliable
    signal than trying to infer topic boundaries from prose.
    """
    soup = _soup(raw)
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    out: list[str] = []
    seen: set[str] = set()
    for el in soup.find_all(["span", "p", "div", "b", "strong"]):
        style = (el.get("style") or "").replace(" ", "").lower()
        is_bold = el.name in ("b", "strong") or "font-weight:700" in style or "font-weight:bold" in style
        if not is_bold:
            continue
        txt = re.sub(r"\s+", " ", el.get_text(" ")).strip()
        if not (MIN_HEADING_CHARS <= len(txt) <= MAX_HEADING_CHARS):
            continue
        if txt.isupper():  # item headings and cover-page boilerplate
            continue
        if txt in seen:
            continue
        seen.add(txt)
        out.append(txt)
    return out


def extract_risk_headings(
    raw: bytes | str, strategy: str | None = None, form: str = DEFAULT_FORM
) -> tuple[list[str], str]:
    """Risk-factor headings only. Returns ``(headings, confidence)``.

    ``strategy`` should be the one :func:`extract_sections` reported, and ``form``
    the same one it was given, so the risk-factor span is located exactly the way
    the sections were.
    """
    text = html_to_text(raw)
    outline = outline_for(form)
    risk = next(
        (i for i, item in enumerate(outline) if item.section_id == "item_1a_risk_factors"), None
    )
    if risk is None:
        return [], "low"

    offsets: dict[int, int] = {}
    for candidate in ([strategy] if strategy and strategy != "none" else list(STRATEGIES)):
        offsets = find_item_offsets(text, candidate, form)
        if risk in offsets:
            break
    start = offsets.get(risk)
    if start is None:
        return [], "low"
    later = [v for k, v in offsets.items() if v > start]
    end = min(later) if later else len(text)
    risk_text = text[start:end]

    headings: list[str] = []
    for h in extract_bold_headings(raw):
        pos = text.find(h[:80])
        if pos == -1:
            # Text may be split across styled runs; fall back to a token probe.
            probe = " ".join(h.split()[:6])
            pos = text.find(probe)
        if pos != -1 and start <= pos < end:
            headings.append(h)

    if not headings:
        return [], "low"
    confidence = "high" if len(headings) >= 8 and len(risk_text) > 20000 else "moderate"
    return headings, confidence
