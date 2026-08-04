"""XBRL fact parsing and transparent fact selection.

Selection rules (applied in order, and recorded on every selected fact so an
analyst can see exactly why a number was chosen):

1. **Filing-scoped, exact period.** Prefer a fact whose ``accn`` equals the
   selected filing's accession number *and* whose period end equals the
   filing's report date. This is the value as printed in that filing.
2. **Filing-scoped, near period.** Same accession, period end within a few days
   (52/53-week calendars).
3. **Any filing, exact period, as originally reported.** Fall back to the
   earliest-filed fact for the period — the number as first published.
4. Otherwise the metric is reported as missing. Nothing is interpolated.

Duplicates are deduped on (concept, unit, start, end, value); genuine conflicts
(same period, *same duration*, different value) are surfaced as warnings.

Note on duration: a period end date alone does not identify a period. A 10-Q
tags the quarter and the year-to-date figure with the same end date, so callers
must say which duration they want via ``duration_class``; otherwise the two are
indistinguishable and the choice between them would be arbitrary.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any

from ..analytics.period_matching import classify_duration
from ..models import DurationClass, Filing, XbrlFact

log = logging.getLogger(__name__)

# 52/53-week fiscal calendars move the period end by up to a week.
NEAR_PERIOD_TOLERANCE_DAYS = 10


def _d(value: Any) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        return None


class FactStore:
    """Parsed ``companyfacts`` for one company."""

    def __init__(self, company_facts: dict[str, Any]) -> None:
        self.raw = company_facts
        self.cik = str(company_facts.get("cik", ""))
        self.entity_name = str(company_facts.get("entityName", ""))
        self._by_concept: dict[str, list[XbrlFact]] = {}
        self._concept_labels: dict[str, str] = {}
        self._parse()

    def _parse(self) -> None:
        facts = self.raw.get("facts", {})
        for taxonomy, concepts in facts.items():
            if taxonomy not in ("us-gaap", "ifrs-full"):
                continue
            for concept, body in concepts.items():
                label = str(body.get("label") or concept)
                rows: list[XbrlFact] = []
                seen: set[tuple] = set()
                for unit, entries in (body.get("units") or {}).items():
                    for e in entries:
                        end = _d(e.get("end"))
                        if end is None or e.get("val") is None:
                            continue
                        try:
                            val = float(e["val"])
                        except (TypeError, ValueError):
                            continue
                        start = _d(e.get("start"))
                        key = (unit, start, end, val, e.get("accn"))
                        if key in seen:
                            continue
                        seen.add(key)
                        rows.append(
                            XbrlFact(
                                concept=concept,
                                taxonomy=taxonomy,
                                unit=str(unit),
                                value=val,
                                start=start,
                                end=end,
                                fiscal_year=e.get("fy"),
                                fiscal_period=e.get("fp"),
                                form=e.get("form"),
                                accession=e.get("accn"),
                                filed=_d(e.get("filed")),
                                frame=e.get("frame"),
                            )
                        )
                if rows:
                    self._by_concept[concept] = rows
                    self._concept_labels[concept] = label

    # -- access ------------------------------------------------------------ #

    def has_concept(self, concept: str) -> bool:
        return concept in self._by_concept

    def concept_label(self, concept: str) -> str:
        return self._concept_labels.get(concept, concept)

    def facts_for(self, concept: str) -> list[XbrlFact]:
        return list(self._by_concept.get(concept, []))

    def concepts(self) -> Iterable[str]:
        return self._by_concept.keys()

    # -- selection --------------------------------------------------------- #

    def select(
        self,
        concept: str,
        filing: Filing,
        *,
        period_type: str = "duration",
        period_end: date | None = None,
        duration_class: DurationClass | None = None,
        require_same_accession: bool = False,
    ) -> tuple[XbrlFact | None, str, list[str]]:
        """Select one fact. Returns ``(fact, selection_rule, warnings)``.

        ``duration_class`` restricts duration facts to one reporting length
        (e.g. ``"quarterly"``). Without it a 10-Q's quarter and year-to-date
        facts both match the same period end and the pick between them is
        arbitrary.
        """
        target_end = period_end or filing.report_date
        warnings: list[str] = []
        candidates = [f for f in self.facts_for(concept) if f.period_type == period_type]
        if duration_class is not None and period_type == "duration":
            matching = [f for f in candidates if classify_duration(f.duration_days) == duration_class]
            if not matching and candidates:
                available = sorted({classify_duration(f.duration_days) for f in candidates})
                warnings.append(
                    f"{concept}: no {duration_class} fact for period ending {target_end}; "
                    f"only {', '.join(available)} durations are tagged. Metric omitted rather "
                    "than substituted with a different reporting length."
                )
                return None, "", warnings
            candidates = matching
        if not candidates:
            return None, "", warnings

        same_accn = [f for f in candidates if f.accession == filing.accession]

        exact = [f for f in same_accn if f.end == target_end]
        if exact:
            chosen, w = self._disambiguate(exact, concept, target_end)
            return chosen, "filing_scoped_exact_period", warnings + w

        near = [
            f
            for f in same_accn
            if abs((f.end - target_end).days) <= NEAR_PERIOD_TOLERANCE_DAYS
        ]
        if near:
            near.sort(key=lambda f: abs((f.end - target_end).days))
            chosen, w = self._disambiguate(
                [f for f in near if f.end == near[0].end], concept, target_end
            )
            warnings.append(
                f"{concept}: no fact ends exactly on {target_end}; used the fact ending "
                f"{chosen.end if chosen else '?'} from the same filing (52/53-week calendar)."
            )
            return chosen, "filing_scoped_near_period", warnings + w

        if require_same_accession:
            return None, "", warnings

        any_exact = [f for f in candidates if f.end == target_end]
        if any_exact:
            # As *originally* reported: earliest filed wins.
            any_exact.sort(key=lambda f: (f.filed or date.max, f.accession or ""))
            chosen = any_exact[0]
            warnings.append(
                f"{concept}: value not tagged in filing {filing.accession}; used the value as "
                f"first reported in {chosen.form} {chosen.accession} (filed {chosen.filed})."
            )
            return chosen, "cross_filing_original_report", warnings

        return None, "", warnings

    @staticmethod
    def _disambiguate(
        facts: list[XbrlFact], concept: str, target_end: date
    ) -> tuple[XbrlFact | None, list[str]]:
        """Pick one fact from same-period candidates, warning only on real conflicts.

        Callers filter by duration first, so anything still competing here has
        the same concept, end and reporting length -- a genuine disagreement.
        """
        if not facts:
            return None, []
        values = {round(f.value, 6) for f in facts}
        warnings: list[str] = []
        if len(values) > 1:
            # Most recently filed wins; accession breaks a same-day tie so the
            # result never depends on parse order.
            facts = sorted(
                facts, key=lambda f: (f.filed or date.min, f.accession or ""), reverse=True
            )
            chosen = facts[0]
            newest = {f.filed for f in facts}
            basis = (
                f"used the most recently filed ({chosen.filed})"
                if len(newest) > 1
                else f"all filed {chosen.filed}, so there is no newer value to prefer; "
                f"used accession {chosen.accession}"
            )
            warnings.append(
                f"{concept}: {len(values)} conflicting values tagged for the same "
                f"{classify_duration(chosen.duration_days)} period ending {target_end} "
                f"({sorted(values)}); {basis}."
            )
        return facts[0], warnings
