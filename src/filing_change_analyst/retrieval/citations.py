"""Citation formatting and mechanical validation.

Nothing reaches the analyst unless its citation identifier resolves to a chunk
that was actually supplied as evidence. This is the guardrail that stops a model
from inventing a source id.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..models import EvidenceChunk, MetricComparison

_ACCESSION_RE = re.compile(r"^\d{10}-\d{2}-\d{6}$")


def valid_accession(accession: str) -> bool:
    return bool(_ACCESSION_RE.match(accession or ""))


def filing_index_url(cik: str, accession: str) -> str:
    """Canonical EDGAR filing-index URL. Raises on a malformed accession."""
    if not valid_accession(accession):
        raise ValueError(f"Malformed SEC accession number: {accession!r}")
    return (
        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
        f"{accession.replace('-', '')}/{accession}-index.htm"
    )


def format_citation(chunk: EvidenceChunk) -> str:
    """Short, human-checkable citation. Never contains a page number."""
    return (
        f"[{chunk.chunk_id}] {chunk.company_name} ({chunk.ticker}) {chunk.form} "
        f"period ending {chunk.report_date.isoformat()}, filed {chunk.filing_date.isoformat()}, "
        f"{chunk.section_label}, accession {chunk.accession} — {chunk.source_url}"
    )


def validate_citation_ids(
    claimed_ids: Iterable[str], allowed: Iterable[str]
) -> tuple[list[str], list[str]]:
    """Split claimed ids into ``(kept, dropped)`` against the supplied evidence."""
    allowed_set = set(allowed)
    kept, dropped = [], []
    for cid in claimed_ids:
        c = (cid or "").strip().strip("[]")
        (kept if c in allowed_set else dropped).append(c)
    # Preserve order, remove duplicates.
    return list(dict.fromkeys(kept)), list(dict.fromkeys(dropped))


def validate_metric_ids(
    claimed_ids: Iterable[str], comparisons: Iterable[MetricComparison]
) -> tuple[list[str], list[str]]:
    allowed = {c.metric_id for c in comparisons}
    kept, dropped = [], []
    for mid in claimed_ids:
        m = (mid or "").strip()
        (kept if m in allowed else dropped).append(m)
    return list(dict.fromkeys(kept)), list(dict.fromkeys(dropped))


def evidence_is_supported(claim_earlier: list[str], claim_later: list[str]) -> tuple[bool, str]:
    """A cross-period change claim needs evidence from both periods."""
    if claim_earlier and claim_later:
        return True, ""
    if not claim_earlier and not claim_later:
        return False, "No source evidence was cited for this claim."
    missing = "earlier" if not claim_earlier else "later"
    return False, f"Only one period is cited; evidence from the {missing} filing is missing."
