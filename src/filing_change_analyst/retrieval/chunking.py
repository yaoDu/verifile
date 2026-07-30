"""Section-aware chunking.

Chunks carry full SEC provenance so that any excerpt shown to an analyst can be
traced back to company, form, accession number, section and source URL without
a second lookup.
"""

from __future__ import annotations

import hashlib
import re
from typing import Literal

from ..models import EvidenceChunk, Filing, FilingSection

TARGET_CHARS = 1100
MAX_CHARS = 1800
MIN_CHARS = 180

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(“\"])")


def _paragraphs(text: str) -> list[str]:
    """Group the flattened text back into paragraph-sized units."""
    lines = [ln.strip() for ln in text.split("\n")]
    paras: list[str] = []
    buf: list[str] = []
    for ln in lines:
        if not ln:
            continue
        buf.append(ln)
        # A line ending in sentence punctuation closes a paragraph; short
        # heading-like lines stand alone.
        if ln.endswith((".", "!", "?", ":", ";")) and len(" ".join(buf)) > 200:
            paras.append(" ".join(buf))
            buf = []
    if buf:
        paras.append(" ".join(buf))
    return [p for p in paras if p]


def _split_oversized(para: str) -> list[str]:
    if len(para) <= MAX_CHARS:
        return [para]
    out, buf = [], ""
    for sent in _SENTENCE_SPLIT.split(para):
        if buf and len(buf) + len(sent) + 1 > TARGET_CHARS:
            out.append(buf.strip())
            buf = sent
        else:
            buf = f"{buf} {sent}".strip()
    if buf:
        out.append(buf.strip())
    return out or [para[:MAX_CHARS]]


def _chunk_id(period: str, accession: str, section_id: str, ordinal: int, text: str) -> str:
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:6]
    return f"{period[0].upper()}-{section_id}-{ordinal:03d}-{digest}"


def chunk_section(
    section: FilingSection,
    filing: Filing,
    period: Literal["earlier", "later"],
    headings: list[str] | None = None,
) -> list[EvidenceChunk]:
    """Turn one section into retrievable chunks."""
    headings = headings or []
    chunks: list[EvidenceChunk] = []
    current_heading = ""
    ordinal = 0
    pending: list[str] = []

    def flush() -> None:
        nonlocal pending, ordinal
        if not pending:
            return
        body = " ".join(pending).strip()
        pending = []
        if len(body) < MIN_CHARS:
            return
        for piece in _split_oversized(body):
            nonlocal_ordinal = ordinal
            chunks.append(
                EvidenceChunk(
                    chunk_id=_chunk_id(period, filing.accession, section.section_id, nonlocal_ordinal, piece),
                    period=period,
                    ticker=filing.ticker,
                    company_name=filing.company_name,
                    cik=filing.cik,
                    form=filing.form,
                    accession=filing.accession,
                    filing_date=filing.filing_date,
                    report_date=filing.report_date,
                    section_id=section.section_id,
                    section_label=section.label,
                    heading=current_heading,
                    text=piece,
                    ordinal=nonlocal_ordinal,
                    source_url=filing.primary_document_url,
                )
            )
            ordinal += 1

    heading_set = {h.strip() for h in headings}
    for para in _paragraphs(section.text):
        if para.strip() in heading_set:
            flush()
            current_heading = para.strip()
            continue
        pending.append(para)
        if len(" ".join(pending)) >= TARGET_CHARS:
            flush()
    flush()
    return chunks


def chunk_filing(
    sections: dict[str, FilingSection],
    filing: Filing,
    period: Literal["earlier", "later"],
    headings: list[str] | None = None,
) -> list[EvidenceChunk]:
    out: list[EvidenceChunk] = []
    for section in sections.values():
        out.extend(chunk_section(section, filing, period, headings=headings))
    return out
