"""Period classification and compatibility rules.

Silently comparing a quarter with a year is the single most damaging error this
kind of tool can make, so period logic lives in its own module with its own
tests and is applied *before* any arithmetic.
"""

from __future__ import annotations

from datetime import date

from ..models import DurationClass, XbrlFact

# Reported fiscal periods drift by a few days (52/53-week calendars, leap years),
# so each class is a tolerance band rather than an exact day count.
DURATION_BANDS: dict[str, tuple[int, int]] = {
    "annual": (330, 400),
    "three_quarters": (250, 290),
    "half_year": (160, 200),
    "quarterly": (75, 105),
}

# Two durations of the same class must still be within this many days of each
# other, which blocks e.g. a 53-week year against a 26-week stub.
MAX_DURATION_DELTA_DAYS = 45

# For a like-for-like YoY comparison the two period ends must sit within this
# many days of "exactly N years apart".
MAX_FISCAL_ALIGNMENT_DRIFT_DAYS = 45


def classify_duration(days: int | None) -> DurationClass:
    """Map a duration in days to a named class. ``None`` means an instant fact."""
    if days is None:
        return "instant"
    for name, (lo, hi) in DURATION_BANDS.items():
        if lo <= days <= hi:
            return name  # type: ignore[return-value]
    return "other"


def classify_fact(fact: XbrlFact) -> DurationClass:
    return classify_duration(fact.duration_days)


def fiscal_alignment_drift_days(earlier_end: date, later_end: date, expected_years: int = 1) -> int:
    """How far the two period ends are from being exactly ``expected_years`` apart."""
    try:
        target = later_end.replace(year=later_end.year - expected_years)
    except ValueError:  # 29 Feb -> non-leap year
        target = later_end.replace(year=later_end.year - expected_years, day=28)
    return abs((target - earlier_end).days)


def periods_compatible(
    earlier: XbrlFact | None,
    later: XbrlFact | None,
    *,
    expected_years: int = 1,
) -> tuple[bool, str]:
    """Decide whether two facts may be compared. Returns ``(ok, explanation)``.

    The explanation is written for an analyst, not a developer: it is shown in
    the UI whenever a comparison is blocked.
    """
    if earlier is None and later is None:
        return False, "No facts available for either period."
    if earlier is None:
        return False, "No fact available for the earlier period."
    if later is None:
        return False, "No fact available for the later period."

    if earlier.period_type != later.period_type:
        return False, (
            f"Period-type mismatch: earlier fact is a {earlier.period_type} value and later fact "
            f"is a {later.period_type} value. Balance-sheet (instant) and income-statement "
            "(duration) facts cannot be compared directly."
        )

    if earlier.unit != later.unit:
        return False, f"Unit mismatch: '{earlier.unit}' vs '{later.unit}'."

    if earlier.period_type == "duration":
        e_days, l_days = earlier.duration_days or 0, later.duration_days or 0
        e_class, l_class = classify_duration(e_days), classify_duration(l_days)
        if e_class != l_class:
            return False, (
                f"Duration mismatch: earlier period is {e_days} days ({e_class}), later period is "
                f"{l_days} days ({l_class}). Comparing these would mix reporting frequencies."
            )
        if e_class == "other":
            return False, (
                f"Unrecognised reporting duration ({e_days} days vs {l_days} days); this "
                "prototype only compares standard annual, three-quarter, half-year and "
                "quarterly periods."
            )
        if abs(e_days - l_days) > MAX_DURATION_DELTA_DAYS:
            return False, (
                f"Durations differ by {abs(e_days - l_days)} days ({e_days} vs {l_days}), which "
                f"exceeds the {MAX_DURATION_DELTA_DAYS}-day tolerance for a like-for-like "
                "comparison."
            )

    drift = fiscal_alignment_drift_days(earlier.end, later.end, expected_years)
    if drift > MAX_FISCAL_ALIGNMENT_DRIFT_DAYS:
        return False, (
            f"Fiscal alignment problem: period ends {earlier.end} and {later.end} are "
            f"{drift} days away from being exactly {expected_years} year(s) apart."
        )

    note = f"Compatible: {earlier.period_type}"
    if earlier.period_type == "duration":
        note += f", {classify_duration(earlier.duration_days)} ({earlier.duration_days}d vs {later.duration_days}d)"
    note += f", ends {earlier.end} → {later.end}"
    if drift:
        note += f" (fiscal drift {drift}d, within tolerance)"
    return True, note
