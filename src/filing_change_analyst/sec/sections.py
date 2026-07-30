"""HTML filing → plain text → named sections.

10-K HTML has no stable page numbering, so this module never invents page
numbers. It anchors evidence on *section names* plus the SEC accession number
and document URL, which are stable and verifiable.

Filers do not agree on how they mark up item headings, so extraction tries three
anchoring conventions in order of precision and reports which one worked. This was
built after measuring ten large filers: MSFT uses upper case, Workiva-generated
filings (AAPL, NVDA, BRK-B) use title case, and P&G omits item numbers from the
body entirely. Anchoring on upper case alone silently produced *zero* sections for
four of the ten.

Where every strategy fails, the caller is told extraction failed rather than being
handed an empty result that looks like "this filing has no risk factors".
"""

from __future__ import annotations

import logging
import re
import warnings

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from ..models import SECTION_LABELS, FilingSection

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

# Bare section titles, used only when no item-prefixed anchor exists anywhere.
# Each maps to the item number it stands in for.
_TITLE_ANCHORS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("1", re.compile(r"(?mi)^BUSINESS\.?$")),
    ("1A", re.compile(r"(?mi)^RISK FACTORS\.?$")),
    ("1B", re.compile(r"(?mi)^UNRESOLVED STAFF COMMENTS\.?$")),
    ("2", re.compile(r"(?mi)^PROPERTIES\.?$")),
    ("3", re.compile(r"(?mi)^LEGAL PROCEEDINGS\.?$")),
    ("5", re.compile(r"(?mi)^MARKET FOR (THE )?REGISTRANT.{0,60}$")),
    ("7", re.compile(r"(?mi)^MANAGEMENT.S DISCUSSION AND ANALYSIS.{0,80}$")),
    ("7A", re.compile(r"(?mi)^QUANTITATIVE AND QUALITATIVE DISCLOSURES ABOUT MARKET RISK\.?$")),
    ("8", re.compile(r"(?mi)^FINANCIAL STATEMENTS AND SUPPLEMENTARY DATA\.?$")),
)

# Strategy names, most precise first.
STRATEGIES = ("upper_case", "mixed_case", "title_only")

# A strategy must locate at least this many of the sections this tool uses before
# it is accepted; otherwise the next, less precise strategy is tried.
_REQUIRED_ITEMS = ("1", "1A", "7")
_MIN_SECTION_CHARS = 1500

_ITEM_TO_SECTION = {
    "1": "item_1_business",
    "1A": "item_1a_risk_factors",
    "7": "item_7_mdna",
    "7A": "item_7a_market_risk",
    "8": "item_8_financial_statements",
}

# Item numbers, in document order, used to find where each section stops.
_ITEM_ORDER = [
    "1", "1A", "1B", "1C", "2", "3", "4",
    "5", "6", "7", "7A", "8", "9", "9A", "9B", "9C",
    "10", "11", "12", "13", "14", "15", "16",
]

MIN_HEADING_CHARS = 35
MAX_HEADING_CHARS = 320


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


def _offsets_from_pattern(text: str, pattern: re.Pattern[str]) -> dict[str, int]:
    offsets: dict[str, int] = {}
    for m in pattern.finditer(text):
        offsets.setdefault(m.group(1).upper(), m.start())
    return offsets


def _offsets_from_titles(text: str) -> dict[str, int]:
    """Locate sections by bare title when the body carries no item prefix.

    For each title, the *last* standalone occurrence is taken: filers repeat the
    title in cross-references and the table of contents earlier in the document,
    and the section body itself is the final one.
    """
    offsets: dict[str, int] = {}
    for item, pattern in _TITLE_ANCHORS:
        matches = list(pattern.finditer(text))
        if matches:
            offsets[item] = matches[-1].start()
    return offsets


def _slice_sections(text: str, offsets: dict[str, int]) -> dict[str, FilingSection]:
    positions = sorted(
        ((item, offsets[item]) for item in _ITEM_ORDER if item in offsets), key=lambda p: p[1]
    )
    out: dict[str, FilingSection] = {}
    for idx, (item, start) in enumerate(positions):
        section_id = _ITEM_TO_SECTION.get(item)
        if section_id is None:
            continue
        end = positions[idx + 1][1] if idx + 1 < len(positions) else len(text)
        body = text[start:end].strip()
        note = ""
        if len(body) < 500:
            note = (
                f"Only {len(body)} characters were captured for {SECTION_LABELS[section_id]}; "
                "the heading may have been matched inside a table of contents."
            )
        out[section_id] = FilingSection(
            section_id=section_id,
            label=SECTION_LABELS[section_id],
            text=body,
            char_count=len(body),
            extraction_note=note,
        )
    return out


def _strategy_is_usable(sections: dict[str, FilingSection]) -> bool:
    """A strategy is accepted only if it produced substantial required sections."""
    for item in _REQUIRED_ITEMS:
        section_id = _ITEM_TO_SECTION.get(item)
        if section_id is None:
            continue
        section = sections.get(section_id)
        if section is None or section.char_count < _MIN_SECTION_CHARS:
            return False
    return True


def find_item_offsets(text: str, strategy: str = "upper_case") -> dict[str, int]:
    """Map item number → character offset, using one anchoring strategy."""
    if strategy == "upper_case":
        return _offsets_from_pattern(text, _ITEM_ANCHOR_UPPER)
    if strategy == "mixed_case":
        return _offsets_from_pattern(text, _ITEM_ANCHOR_ANY_CASE)
    if strategy == "title_only":
        return _offsets_from_titles(text)
    raise ValueError(f"Unknown anchoring strategy: {strategy}")


def extract_sections(
    raw: bytes | str,
) -> tuple[dict[str, FilingSection], list[str], str]:
    """Extract the sections this prototype uses.

    Returns ``(sections, notes, strategy)``. ``strategy`` names which anchoring
    convention actually worked, or ``"none"`` when extraction failed — it is
    surfaced in the UI and the brief so an analyst can see how the text was
    located rather than having to trust it.
    """
    text = html_to_text(raw)
    notes: list[str] = []

    best: dict[str, FilingSection] = {}
    used = "none"
    for strategy in STRATEGIES:
        offsets = find_item_offsets(text, strategy)
        if not offsets:
            continue
        candidate = _slice_sections(text, offsets)
        if _strategy_is_usable(candidate):
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
    for item in _REQUIRED_ITEMS:
        section_id = _ITEM_TO_SECTION[item]
        if section_id not in best:
            notes.append(
                f"{SECTION_LABELS[section_id]} could not be located in this filing; "
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


def extract_risk_headings(raw: bytes | str, strategy: str | None = None) -> tuple[list[str], str]:
    """Risk-factor headings only. Returns ``(headings, confidence)``.

    ``strategy`` should be the one :func:`extract_sections` reported, so the Item
    1A span is located the same way the sections were.
    """
    text = html_to_text(raw)
    offsets: dict[str, int] = {}
    for candidate in ([strategy] if strategy and strategy != "none" else list(STRATEGIES)):
        offsets = find_item_offsets(text, candidate)
        if "1A" in offsets:
            break
    start = offsets.get("1A")
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
