"""Guardrails applied to anything a language model produces.

The strongest of these is :func:`ungrounded_numbers`. The model is instructed
never to write a figure that it was not given; this function mechanically checks
that instruction by extracting every numeric literal from the generated text and
confirming it appears either in the supplied evidence excerpts or in the
Python-computed metric table. Anything else is treated as fabricated.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..models import MetricComparison

# Numbers with optional thousands separators, decimals, %, and $ signs.
_NUMBER_RE = re.compile(r"-?\$?\d[\d,]*(?:\.\d+)?%?")

# Ordinals, years and small counts are linguistic, not financial, so requiring a
# source for them produces noise without protecting anything.
_SAFE_INTEGERS = set(range(0, 13)) | set(range(1900, 2101))


def _canon(token: str) -> str:
    """Normalise a numeric literal for comparison: 1,234.50 → 1234.5."""
    t = token.strip().lstrip("$").rstrip("%").replace(",", "").replace("−", "-")
    t = t.lstrip("-")
    if not t:
        return ""
    try:
        v = float(t)
    except ValueError:
        return ""
    # Compare on a canonical decimal form so 45.1 and 45.10 match.
    return f"{v:.6f}".rstrip("0").rstrip(".")


def _variants(value: float) -> set[str]:
    """Every rendering of one computed value an analyst might legitimately see."""
    out: set[str] = set()
    scales = (1.0, 1e-3, 1e-6, 1e-9, 1e-12, 100.0)
    for scale in scales:
        v = value * scale
        for places in (0, 1, 2, 3, 4):
            out.add(_canon(f"{abs(v):.{places}f}"))
    out.discard("")
    return out


def allowed_number_set(
    comparisons: Iterable[MetricComparison], evidence_texts: Iterable[str]
) -> set[str]:
    """Canonical numbers the model is permitted to repeat."""
    allowed: set[str] = set()
    for c in comparisons:
        for v in (
            c.earlier.value,
            c.later.value,
            c.absolute_change,
            c.percent_change,
            c.point_change,
        ):
            if v is not None:
                allowed |= _variants(float(v))
    for text in evidence_texts:
        for m in _NUMBER_RE.finditer(text or ""):
            allowed.add(_canon(m.group(0)))
    allowed.discard("")
    return allowed


def ungrounded_numbers(text: str, allowed: set[str]) -> list[str]:
    """Numeric literals in ``text`` that are not present in the allowed set."""
    bad: list[str] = []
    for m in _NUMBER_RE.finditer(text or ""):
        token = m.group(0)
        canon = _canon(token)
        if not canon:
            continue
        try:
            as_float = float(canon)
        except ValueError:
            continue
        if as_float.is_integer() and int(as_float) in _SAFE_INTEGERS and "%" not in token:
            continue
        if canon not in allowed:
            bad.append(token)
    return list(dict.fromkeys(bad))


# --------------------------------------------------------------------------- #
# Content guardrails
# --------------------------------------------------------------------------- #

_RECOMMENDATION_RE = re.compile(
    r"\b(buy|sell|hold|overweight|underweight|outperform|underperform|price target|"
    r"we recommend|should (?:buy|sell|own|purchase)|strong (?:buy|sell))\b",
    re.I,
)


def contains_recommendation(text: str) -> bool:
    """Detect investment advice, which this product must never produce."""
    return bool(_RECOMMENDATION_RE.search(text or ""))


_INJECTION_RE = re.compile(
    r"(ignore (all )?(previous|prior|above) instructions"
    r"|disregard (the )?(system|previous) (prompt|instructions)"
    r"|you are now"
    r"|<\s*/?\s*(system|assistant|instructions)\s*>"
    r"|new instructions:)",
    re.I,
)


def strip_injection_markers(text: str) -> tuple[str, bool]:
    """Neutralise instruction-like strings found inside untrusted filing text.

    Filing content is data. If a document (or a user question) contains text that
    looks like an instruction to the model, it is redacted before it ever enters
    the prompt, and the caller is told it happened.
    """
    if not text:
        return "", False
    cleaned, n = _INJECTION_RE.subn("[redacted-instruction-like-text]", text)
    return cleaned, n > 0
