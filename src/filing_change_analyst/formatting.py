"""Display formatting. Formatting never changes a value — it only renders it."""

from __future__ import annotations

from .models import MetricComparison, MetricValue

NA = "N/A"


def money(value: float | None, unit: str = "USD") -> str:
    if value is None:
        return NA
    if unit not in ("USD", "usd"):
        return f"{value:,.2f} {unit}"
    a = abs(value)
    if a >= 1e12:
        return f"${value / 1e12:,.2f}T"
    if a >= 1e9:
        return f"${value / 1e9:,.2f}B"
    if a >= 1e6:
        return f"${value / 1e6:,.1f}M"
    return f"${value:,.2f}"


def ratio_pct(value: float | None) -> str:
    return NA if value is None else f"{value * 100:.2f}%"


def per_share(value: float | None) -> str:
    return NA if value is None else f"${value:,.2f}"


def metric_value_text(mv: MetricValue, kind: str) -> str:
    if not mv.available:
        return NA
    if kind == "ratio":
        return ratio_pct(mv.value)
    if kind == "count":
        return per_share(mv.value)
    return money(mv.value, mv.unit)


def change_text(comp: MetricComparison) -> str:
    """The change column: percent for levels, percentage POINTS for ratios."""
    if comp.status != "ok":
        return NA
    if comp.kind == "ratio":
        return NA if comp.point_change is None else f"{comp.point_change:+.2f} pp"
    if comp.percent_change is None:
        return NA
    return f"{comp.percent_change:+.2f}%"


def absolute_change_text(comp: MetricComparison) -> str:
    if comp.status != "ok" or comp.absolute_change is None:
        return NA
    if comp.kind == "ratio":
        return f"{comp.absolute_change * 100:+.2f} pp"
    if comp.kind == "count":
        return f"{comp.absolute_change:+,.2f}"
    return ("+" if comp.absolute_change >= 0 else "−") + money(abs(comp.absolute_change), comp.earlier.unit)


def status_text(comp: MetricComparison) -> str:
    return {
        "ok": "OK",
        "missing_earlier": "Missing in earlier filing",
        "missing_later": "Missing in latest filing",
        "missing_both": "Not tagged in either filing",
        "incompatible_periods": "BLOCKED — incompatible periods",
    }[comp.status]


def short_excerpt(text: str, limit: int = 420) -> str:
    """Trim an excerpt at a word boundary. Filings are quoted, not reproduced."""
    t = " ".join(text.split())
    if len(t) <= limit:
        return t
    return t[:limit].rsplit(" ", 1)[0] + " …"


def escape_dollars(text: str) -> str:
    """Stop Streamlit reading ``$…$`` as LaTeX.

    This is the escape that actually bites. A claim reading ``capex rose from
    $64.55B to $115.95B`` loses both dollar signs and renders everything between
    them in maths italics — silently turning a correct figure into a misleading
    one. Dollar amounts appear in nearly every generated claim, every brief and
    most filing excerpts, so this is the common case rather than an edge case.

    Narrow by design: it leaves every other Markdown construct alone, so it is
    safe to apply to text that is *meant* to be Markdown, such as the analyst
    brief.
    """
    return text.replace("$", r"\$")


# Order matters: the backslash must be escaped before anything that introduces
# one, or the escapes we add would themselves be escaped.
_MD_SPECIALS = ("\\", "$", "*", "_", "`", "~", "<")


def md_safe(text: str) -> str:
    """Neutralise Markdown markup in a *content* string before rendering.

    For strings that are prose rather than markup: filing excerpts, generated
    claims, caveats, model answers. Covers :func:`escape_dollars` and adds the
    emphasis characters, so filing text containing ``*`` or ``_`` reads as the
    filing wrote it instead of turning into bold or italic. Complements — and
    does not replace — the rule that filing text is never rendered with
    ``unsafe_allow_html``.
    """
    for ch in _MD_SPECIALS:
        text = text.replace(ch, "\\" + ch)
    return text
