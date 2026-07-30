"""HTML filing → plain text → named sections.

10-K HTML has no stable page numbering, so this module never invents page
numbers. It anchors evidence on *section names* plus the SEC accession number
and document URL, which are stable and verifiable.

Section detection uses the fact that EDGAR filers render the real item headings
in upper case (``ITEM 1A. RISK FACTORS``) while the table of contents and the
running page headers use title case (``Item 1A.``). That single distinction
removes almost all of the usual table-of-contents false positives; where it
fails we report low extraction confidence instead of guessing.
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

# Real item headings, as rendered in upper case in the body of the filing.
_ITEM_ANCHOR = re.compile(r"(?m)^ITEM\s+(\d{1,2}[A-C]?)\s*[\.\:\-–—]")

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


def find_item_offsets(text: str) -> dict[str, int]:
    """Map item number → character offset of its first upper-case heading."""
    offsets: dict[str, int] = {}
    for m in _ITEM_ANCHOR.finditer(text):
        item = m.group(1).upper()
        offsets.setdefault(item, m.start())
    return offsets


def extract_sections(raw: bytes | str) -> tuple[dict[str, FilingSection], list[str]]:
    """Extract the sections this prototype uses. Returns ``(sections, notes)``."""
    text = html_to_text(raw)
    offsets = find_item_offsets(text)
    notes: list[str] = []
    sections: dict[str, FilingSection] = {}

    if not offsets:
        notes.append(
            "No upper-case item headings were found in this document; section extraction "
            "failed and only whole-document search is available."
        )
        return sections, notes

    positions = [(item, offsets[item]) for item in _ITEM_ORDER if item in offsets]
    positions.sort(key=lambda p: p[1])

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
            notes.append(note)
        sections[section_id] = FilingSection(
            section_id=section_id,
            label=SECTION_LABELS[section_id],
            text=body,
            char_count=len(body),
            extraction_note=note,
        )

    for required in ("item_1_business", "item_1a_risk_factors", "item_7_mdna"):
        if required not in sections:
            notes.append(
                f"{SECTION_LABELS[required]} could not be located in this filing; "
                "evidence for it will be unavailable."
            )
    return sections, notes


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


def extract_risk_headings(raw: bytes | str) -> tuple[list[str], str]:
    """Risk-factor headings only. Returns ``(headings, confidence)``."""
    text = html_to_text(raw)
    offsets = find_item_offsets(text)
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
