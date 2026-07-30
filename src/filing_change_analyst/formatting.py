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
