"""Period classification and compatibility rules.

Silently comparing a quarter with a year is the single most damaging error this
kind of tool can make, so period logic lives in its own module with its own
tests and is applied *before* any arithmetic.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from ..models import DurationClass, MetricComparison, XbrlFact

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


# A 10-Q tags the quarter *and* the year-to-date figure against the same period
# end, so the form alone does not identify the period an analyst means. These
# are the defaults; the caller may override (the UI exposes a Quarter/YTD
# toggle for 10-Qs).
DEFAULT_DURATION_BY_FORM: dict[str, DurationClass] = {
    "10-K": "annual",
    "20-F": "annual",
    "40-F": "annual",
    "10-Q": "quarterly",
}


def default_duration_class(form: str | None) -> DurationClass | None:
    """Default reporting length for a form type, or ``None`` if unknown.

    ``None`` means "do not filter", which preserves the previous behaviour for
    form types this prototype has no opinion about.
    """
    if not form:
        return None
    return DEFAULT_DURATION_BY_FORM.get(form.strip().upper())


# How a reporting length is named to the analyst. One table, because the chip
# above the figures and the caveat under a change must never disagree about what
# basis is on screen.
BASIS_LABELS: dict[str, str] = {
    "annual": "Annual (12 months)",
    "three_quarters": "Year to date (9 months)",
    "half_year": "Year to date (6 months)",
    "quarterly": "Quarter (3 months)",
}

# Anything shorter than a year comes from a 10-Q, whose MD&A narrates the period
# *and* the cumulative year to date.
SUB_ANNUAL_CLASSES = frozenset({"quarterly", "half_year", "three_quarters"})

# Year-to-date figures accumulate from the fiscal year start, so consecutive
# quarters carry different year-to-date lengths — six months, then nine. There is
# no sequential year-to-date comparison to make, and asking for one finds no
# facts rather than failing loudly, so callers are told outright.
YEAR_TO_DATE_CLASSES = frozenset({"half_year", "three_quarters"})

BASIS_PHRASES: dict[str, str] = {
    "quarterly": "the quarter alone",
    "half_year": "the six months to date",
    "three_quarters": "the nine months to date",
}


def reported_basis(comparisons: Iterable[MetricComparison]) -> DurationClass | None:
    """The one reporting length the compared figures share, if they share one.

    Read back off the facts that were actually selected rather than off the
    requested setting, so nothing downstream can label the figures with a basis
    they do not have. ``None`` when the comparison is empty or mixed: say nothing
    rather than guess.
    """
    classes = {
        c.later.duration_class
        for c in comparisons
        if c.usable and c.later.available and c.later.period_type == "duration"
    }
    return classes.pop() if len(classes) == 1 else None


def fiscal_alignment_drift_days(earlier_end: date, later_end: date, expected_years: int = 1) -> int:
    """How far the two period ends are from being exactly ``expected_years`` apart."""
    try:
        target = later_end.replace(year=later_end.year - expected_years)
    except ValueError:  # 29 Feb -> non-leap year
        target = later_end.replace(year=later_end.year - expected_years, day=28)
    return abs((target - earlier_end).days)


# Nominal length of each reporting class, used to say where the *preceding*
# period should end. Only needed for instants: a duration fact states its own
# length, but a balance-sheet date does not.
NOMINAL_PERIOD_DAYS: dict[str, int] = {
    "annual": 365,
    "three_quarters": 273,
    "half_year": 182,
    "quarterly": 91,
}


def sequential_drift_days(
    earlier_end: date, later_end: date, period_days: int | None
) -> int | None:
    """How far the earlier period end is from being exactly one period back.

    A sequential comparison expects the later period to *follow* the earlier one,
    so the two ends should sit one period length apart — not one year, which is
    what the year-over-year check measures. Returns ``None`` when the length is
    unknown and no judgement can be made.
    """
    if not period_days:
        return None
    return abs((later_end - earlier_end).days - period_days)


def periods_compatible(
    earlier: XbrlFact | None,
    later: XbrlFact | None,
    *,
    expected_years: int = 1,
    basis: str = "year_over_year",
    period_class: DurationClass | None = None,
) -> tuple[bool, str]:
    """Decide whether two facts may be compared. Returns ``(ok, explanation)``.

    ``basis`` decides what "aligned" means. A year-over-year comparison expects
    the two period ends a year apart; a sequential one expects them one period
    apart. Checking the wrong one blocks every metric — a Dec-to-Mar quarterly
    pair is ~275 days from being a year apart, and correct sequentially.

    ``period_class`` supplies that length for balance-sheet facts, which state a
    date but no duration. Without it every instant metric — cash, debt, equity —
    would be unverifiable on a sequential comparison and drop out.

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

    if basis == "sequential":
        # A duration fact states its own length. An instant does not, so it falls
        # back to the nominal length of the comparison the caller asked for.
        period_days = later.duration_days or NOMINAL_PERIOD_DAYS.get(period_class or "", 0)
        drift = sequential_drift_days(earlier.end, later.end, period_days)
        if drift is None:
            return False, (
                f"Cannot verify sequential alignment: the reporting length of the period ending "
                f"{later.end} is not stated, so there is no way to check that {earlier.end} is "
                "the period immediately before it."
            )
        if drift > MAX_FISCAL_ALIGNMENT_DRIFT_DAYS:
            return False, (
                f"Sequential alignment problem: period ends {earlier.end} and {later.end} are "
                f"{drift} days away from being exactly one period ({period_days} days) apart, so "
                "these are not consecutive periods."
            )
        alignment = f"one period apart ({period_days}d)"
    else:
        drift = fiscal_alignment_drift_days(earlier.end, later.end, expected_years)
        if drift > MAX_FISCAL_ALIGNMENT_DRIFT_DAYS:
            return False, (
                f"Fiscal alignment problem: period ends {earlier.end} and {later.end} are "
                f"{drift} days away from being exactly {expected_years} year(s) apart."
            )
        alignment = f"{expected_years} year(s) apart"

    note = f"Compatible: {earlier.period_type}"
    if earlier.period_type == "duration":
        note += f", {classify_duration(earlier.duration_days)} ({earlier.duration_days}d vs {later.duration_days}d)"
    note += f", ends {earlier.end} → {later.end}, {alignment}"
    if drift:
        note += f" (drift {drift}d, within tolerance)"
    return True, note
