"""Run the evaluation suite and write a report of measured results.

    python evaluation/run_evaluation.py [--json evaluation/results.json]

Runs against the live (cached) SEC data for the default MSFT 10-K pair, so the
numbers in the report are real. Questions marked ``llm_required`` are reported
as *not measured* when no ``API_KEY`` is configured, rather than being
scored as passes.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from filing_change_analyst.analytics.period_matching import classify_duration  # noqa: E402
from filing_change_analyst.config import configure_logging, get_settings  # noqa: E402
from filing_change_analyst.pipeline import apply_ai_synthesis, run_analysis  # noqa: E402
from filing_change_analyst.research.qa import answer_question  # noqa: E402
from filing_change_analyst.services.llm import LlmClient  # noqa: E402

QUESTIONS_PATH = Path(__file__).parent / "questions.json"


def _pinned_pair(target: dict):
    """Resolve the documented filing pair by accession number."""
    from filing_change_analyst.pipeline import available_filings, pair_from_filings

    wanted = {target["earlier_accession"], target["later_accession"]}
    filings = {
        f.accession: f
        for f in available_filings(target["ticker"], target["form"], limit=12)
        if f.accession in wanted
    }
    if len(filings) != 2:
        return None
    return pair_from_filings(
        filings[target["earlier_accession"]], filings[target["later_accession"]]
    )


class Case:
    def __init__(self, spec: dict) -> None:
        self.id = spec["id"]
        self.type = spec["type"]
        self.question = spec["question"]
        self.spec = spec
        self.passed: bool | None = None
        self.detail = ""
        self.latency_ms = 0
        self.measures: dict[str, bool] = {}

    def record(self, passed: bool | None, detail: str, **measures: bool) -> None:
        self.passed = passed
        self.detail = detail
        self.measures.update(measures)


# --------------------------------------------------------------------------- #
# Scorers
# --------------------------------------------------------------------------- #


def score_exact_number(case: Case, result) -> None:
    comp = result.comparison_by_id(case.spec["metric_id"])
    if comp is None:
        case.record(False, "metric not produced")
        return
    mv = comp.later if case.spec["period"] == "later" else comp.earlier
    if not mv.available:
        case.record(False, f"value unavailable: {mv.missing_reason}")
        return
    expected = float(case.spec["expected_value"])
    tol = abs(expected) * float(case.spec["tolerance_pct"]) / 100.0
    ok = abs(mv.value - expected) <= tol
    provenance_ok = bool(mv.provenance and all(p.accession for p in mv.provenance))
    case.record(
        ok,
        f"expected {expected:,.2f}, produced {mv.value:,.2f}"
        + ("" if ok else f" (tolerance ±{tol:,.2f})"),
        metric_correctness=ok,
        citation_validity=provenance_ok,
    )


def score_calculated_change(case: Case, result) -> None:
    comp = result.comparison_by_id(case.spec["metric_id"])
    if comp is None or comp.status != "ok":
        case.record(False, f"comparison unavailable (status={comp.status if comp else 'missing'})")
        return
    tol = float(case.spec["tolerance_abs"])
    if "expected_percent_change" in case.spec:
        expected, produced, unit = case.spec["expected_percent_change"], comp.percent_change, "%"
    else:
        expected, produced, unit = case.spec["expected_point_change"], comp.point_change, "pp"
    if produced is None:
        case.record(False, "change not computed")
        return
    ok = abs(produced - expected) <= tol
    case.record(
        ok,
        f"expected {expected:+.3f}{unit}, produced {produced:+.3f}{unit}",
        metric_correctness=ok,
        numerical_accuracy=ok,
    )


def score_period_correctness(case: Case, result) -> None:
    comp = result.comparison_by_id(case.spec["metric_id"])
    if comp is None:
        case.record(False, "metric not produced")
        return
    want_type = case.spec["expected_period_type"]
    want_class = case.spec["expected_duration_class"]
    checks = []
    for mv in (comp.earlier, comp.later):
        if not mv.available:
            checks.append(False)
            continue
        for p in mv.provenance:
            checks.append(
                p.period_type == want_type and classify_duration(p.duration_days) == want_class
            )
    ok = bool(checks) and all(checks) and comp.status == "ok"
    case.record(
        ok,
        f"both sides {want_type}/{want_class}: {ok}; comparison status={comp.status}",
        period_correctness=ok,
    )


def score_retrieval(case: Case, bundle) -> None:
    from filing_change_analyst.retrieval.search import retrieve_for_question

    route = retrieve_for_question(bundle.index, case.question)
    if not route.evidence:
        case.record(False, "no evidence retrieved", retrieval_success=False)
        return
    sections = {e.chunk.section_id for e in route.evidence}
    periods = {e.chunk.period for e in route.evidence}
    blob = " ".join(e.chunk.text.lower() for e in route.evidence)

    section_ok = bool(sections & set(case.spec["expected_sections"]))
    term_ok = any(t.lower() in blob for t in case.spec["expected_terms"])
    period_ok = periods == {"earlier", "later"} if case.spec.get("require_both_periods") else True
    citations_ok = all(
        e.chunk.chunk_id and e.chunk.accession and e.chunk.source_url for e in route.evidence
    )
    ok = section_ok and term_ok and period_ok
    case.record(
        ok,
        f"sections={sorted(sections)} periods={sorted(periods)} "
        f"section_hit={section_ok} term_hit={term_ok} both_periods={period_ok}",
        retrieval_success=ok,
        citation_validity=citations_ok,
        citation_support=term_ok,
    )


def score_cross_period(case: Case, result) -> None:
    if case.spec.get("check") == "risk_delta_nonempty":
        rd = result.risk_delta
        ok = rd is not None and (bool(rd.added) or bool(rd.removed))
        case.record(
            ok,
            "no risk delta" if rd is None else f"+{len(rd.added)} / -{len(rd.removed)} headings",
            retrieval_success=ok,
        )
        return

    topic_id = case.spec["expected_topic_id"]
    change = next((c for c in result.changes if c.topic_id == topic_id), None)
    topic = next((t for t in result.topics if t.topic_id == topic_id), None)
    if topic is None:
        case.record(False, f"topic {topic_id} not probed")
        return

    both = bool(topic.earlier) and bool(topic.later)
    comp = result.comparison_by_id(case.spec["expected_metric_id"])
    direction_ok = False
    if comp and comp.status == "ok":
        delta = comp.point_change if comp.kind == "ratio" else comp.percent_change
        if delta is not None:
            direction_ok = (delta > 0) == (case.spec["expected_metric_direction"] == "up")

    cited_ok = True
    if change is not None:
        cited_ok = all(
            result.chunk_by_id(cid) is not None
            for cid in change.earlier_source_ids + change.later_source_ids
        )

    ok = both and direction_ok
    case.record(
        ok,
        f"both_periods={both} metric_direction_ok={direction_ok} "
        f"surfaced_as_change={change is not None}",
        retrieval_success=both,
        metric_correctness=direction_ok,
        citation_validity=cited_ok,
    )


def score_insufficient(case: Case, bundle, client: LlmClient | None) -> None:
    if case.spec.get("llm_required") and (client is None or not client.available):
        case.record(None, "not measured — requires a configured model")
        return
    qa = answer_question(
        case.question,
        bundle.index,
        bundle.result.pair,
        bundle.result.comparisons,
        client=client,
        risk_delta=bundle.result.risk_delta,
    )
    ok = qa.answer_type == "insufficient_evidence"
    case.record(
        ok,
        f"answer_type={qa.answer_type}, {len(qa.evidence)} passages retrieved",
        insufficient_evidence_handling=ok,
    )


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #

MEASURE_LABELS = {
    "metric_correctness": "Metric correctness — calculated values match hand-read filing values",
    "period_correctness": "Period correctness — compared facts use compatible durations/instants",
    "retrieval_success": "Retrieval success — expected section/evidence is retrieved",
    "citation_validity": "Citation validity — every citation resolves to supplied evidence",
    "citation_support": "Citation support — retrieved excerpt contains the expected terminology",
    "numerical_accuracy": "Numerical accuracy — reported changes reproduce deterministic values",
    "insufficient_evidence_handling": "Insufficient-evidence handling — the system declines",
}


def build_report(cases: list[Case], result, elapsed_s: float, llm_on: bool) -> str:
    scored = [c for c in cases if c.passed is not None]
    passed = [c for c in scored if c.passed]
    skipped = [c for c in cases if c.passed is None]

    agg: dict[str, list[bool]] = {}
    for c in cases:
        for k, v in c.measures.items():
            agg.setdefault(k, []).append(v)

    latencies = [c.latency_ms for c in cases if c.latency_ms]
    lines: list[str] = []
    lines.append("# Evaluation results")
    lines.append("")
    lines.append(
        f"Run {datetime.now(UTC):%Y-%m-%d %H:%M UTC} against "
        f"{result.pair.later.ticker} {result.pair.later.form} "
        f"({result.pair.earlier.report_date} → {result.pair.later.report_date}). "
        f"AI synthesis: **{'enabled' if llm_on else 'disabled'}**."
    )
    lines.append("")
    lines.append(
        f"**{len(passed)} / {len(scored)} scored questions passed** "
        f"({len(skipped)} not measured). Pipeline run time {elapsed_s:.1f}s."
    )
    lines.append("")

    lines.append("## Measures")
    lines.append("")
    lines.append("| Measure | Result |")
    lines.append("|---|---|")
    for key, label in MEASURE_LABELS.items():
        vals = agg.get(key)
        if not vals:
            lines.append(f"| {label} | not measured |")
            continue
        lines.append(f"| {label} | {sum(vals)}/{len(vals)} ({sum(vals) / len(vals) * 100:.0f}%) |")

    unsupported = sum(
        1
        for c in result.changes
        if not (c.earlier_source_ids and c.later_source_ids and c.caveat)
    )
    lines.append(
        f"| Unsupported-claim rate — material changes lacking both-period evidence or a caveat "
        f"| {unsupported}/{len(result.changes)} |"
    )
    if latencies:
        lines.append(
            f"| Latency — median / slowest scored question | {statistics.median(latencies):.0f} ms "
            f"/ {max(latencies):.0f} ms |"
        )
    lines.append("")

    lines.append("## Question-level results")
    lines.append("")
    lines.append("| id | type | verdict | detail | ms |")
    lines.append("|---|---|---|---|---:|")
    for c in cases:
        verdict = "not measured" if c.passed is None else ("PASS" if c.passed else "**FAIL**")
        lines.append(f"| {c.id} | {c.type} | {verdict} | {c.detail} | {c.latency_ms} |")
    lines.append("")

    failures = [c for c in scored if not c.passed]
    lines.append("## Failures")
    lines.append("")
    if not failures:
        lines.append("None.")
    for c in failures:
        expected = " *(expected — standing negative control)*" if c.spec.get("known_limitation") else ""
        lines.append(f"- **{c.id}** ({c.type}){expected} — {c.question}")
        lines.append(f"  - Measured: {c.detail}")
        if c.spec.get("reason"):
            lines.append(f"  - Why it should decline: {c.spec['reason']}")
        if c.spec.get("known_limitation"):
            lines.append(f"  - Known limitation: {c.spec['known_limitation']}")
    lines.append("")

    if skipped:
        lines.append("## Not measured")
        lines.append("")
        for c in skipped:
            lines.append(f"- **{c.id}** — {c.detail}")
        lines.append("")

    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", type=Path, default=Path(__file__).parent / "results.json")
    ap.add_argument("--markdown", type=Path, default=Path(__file__).parent / "RESULTS.md")
    ap.add_argument("--no-llm", action="store_true", help="Force deterministic-only scoring")
    ap.add_argument(
        "--latest-pair",
        action="store_true",
        help="Score against the two most recent filings instead of the pinned documented pair. "
        "Exact-number questions will fail unless questions.json is refreshed to match.",
    )
    args = ap.parse_args()

    configure_logging()
    settings = get_settings()
    spec = json.loads(QUESTIONS_PATH.read_text())
    target = spec["target"]

    print(f"Running analysis for {target['ticker']} {target['form']}…")
    # Pin the pair by accession number. The app's default is always the two most
    # recent filings, but the ground truth in questions.json was read by hand
    # from two specific documents — so the suite must keep testing those, or a
    # newly filed 10-K would silently invalidate every expected value.
    pair = None
    if not args.latest_pair:
        pair = _pinned_pair(target)
        if pair is None:
            print(
                "  Could not pin the documented filing pair; falling back to the two most "
                "recent filings. Exact-number expectations may not apply."
            )
    bundle = run_analysis(target["ticker"], target["form"], pair=pair)
    client = None
    if settings.llm_available and not args.no_llm:
        client = LlmClient()
        bundle = apply_ai_synthesis(bundle, client=client)
    result = bundle.result

    if str(result.pair.later.report_date) != target["later_period_end"]:
        print(
            f"WARNING: scoring against the pair ending {result.pair.later.report_date}, but the "
            f"ground truth in questions.json is for {target['later_period_end']}. "
            "Exact-number expectations will fail until the file is refreshed."
        )

    cases = [Case(q) for q in spec["questions"]]
    for case in cases:
        started = time.perf_counter()
        if case.type == "exact_number":
            score_exact_number(case, result)
        elif case.type == "calculated_change":
            score_calculated_change(case, result)
        elif case.type == "period_correctness":
            score_period_correctness(case, result)
        elif case.type == "retrieval":
            score_retrieval(case, bundle)
        elif case.type == "cross_period_change":
            score_cross_period(case, result)
        elif case.type == "insufficient_evidence":
            score_insufficient(case, bundle, client)
        else:
            case.record(None, f"unknown question type {case.type}")
        case.latency_ms = int((time.perf_counter() - started) * 1000)
        verdict = "SKIP" if case.passed is None else ("PASS" if case.passed else "FAIL")
        print(f"  [{verdict}] {case.id} {case.type}: {case.detail}")

    report = build_report(cases, result, bundle.elapsed_s, llm_on=bool(client and client.available))
    args.markdown.write_text(report)
    args.json.write_text(
        json.dumps(
            {
                "run_at": datetime.now(UTC).isoformat(),
                "ticker": result.pair.later.ticker,
                "later_period_end": str(result.pair.later.report_date),
                "earlier_period_end": str(result.pair.earlier.report_date),
                "llm_enabled": bool(client and client.available),
                "pipeline_seconds": round(bundle.elapsed_s, 2),
                "cases": [
                    {
                        "id": c.id,
                        "type": c.type,
                        "question": c.question,
                        "passed": c.passed,
                        "detail": c.detail,
                        "latency_ms": c.latency_ms,
                        "measures": c.measures,
                    }
                    for c in cases
                ],
            },
            indent=2,
        )
    )
    scored = [c for c in cases if c.passed is not None]
    failed = [c for c in scored if not c.passed]
    print(f"\n{len(scored) - len(failed)}/{len(scored)} passed. Report: {args.markdown}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
