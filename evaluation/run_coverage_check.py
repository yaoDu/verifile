"""Multi-filer coverage check — how far does this generalise beyond Microsoft?

    python evaluation/run_coverage_check.py [--tickers MSFT,AAPL,...]

The main evaluation suite measures *correctness* on one filing pair with hand-read
ground truth. This measures *coverage*: for a spread of large filers across
sectors and fiscal calendars, does the pipeline produce a usable result at all,
and where does it degrade?

It has no pass/fail ground truth. Its job is to keep the README's generality claims
honest, and it is how the title-case and title-only section strategies and the
older-submissions-shard fallback were found: anchoring on upper-case item headings
alone silently produced zero text evidence for four of ten filers.

Writes evaluation/COVERAGE.md.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from filing_change_analyst.config import configure_logging  # noqa: E402
from filing_change_analyst.pipeline import run_analysis  # noqa: E402
from filing_change_analyst.sec.client import SecError  # noqa: E402
from filing_change_analyst.sec.sections import section_confidence  # noqa: E402

# Chosen for spread, not for flattery: two fiscal-June filers, two January filers,
# a bank, an insurer/conglomerate, an energy major, staples, a retailer and an
# automaker. Banks and conglomerates are expected to lose income-statement metrics.
DEFAULT_TICKERS = (
    "MSFT", "AAPL", "NVDA", "TSLA", "WMT", "UNH", "KO", "PG", "JPM", "BRK-B", "XOM",
)


def check(ticker: str) -> dict:
    started = time.perf_counter()
    row: dict = {"ticker": ticker}
    try:
        bundle = run_analysis(ticker, "10-K")
    except SecError as exc:
        row.update(status="refused", detail=str(exc))
        return row
    except Exception as exc:  # noqa: BLE001 - a crash is the finding
        row.update(status="crashed", detail=f"{type(exc).__name__}: {exc}")
        return row

    r = bundle.result
    usable = [c for c in r.comparisons if c.status == "ok"]
    strategies = sorted({s for s in r.section_strategy.values() if s})
    rd = r.risk_delta
    row.update(
        status="ok",
        seconds=round(time.perf_counter() - started, 1),
        company=r.pair.later.company_name,
        periods=f"{r.pair.earlier.report_date} → {r.pair.later.report_date}",
        metrics=f"{len(usable)}/{len(r.comparisons)}",
        chunks=len(r.chunks),
        changes=len(r.changes),
        risk=f"{rd.earlier_heading_count}→{rd.later_heading_count}" if rd else "none",
        strategy=",".join(strategies) or "none",
        confidence=(
            min((section_confidence(s) for s in strategies), key=lambda c: c == "low")
            if strategies
            else "low"
        ),
        warnings=len(r.warnings),
        missing=[c.metric_id for c in r.comparisons if c.status != "ok"],
    )
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tickers", default=",".join(DEFAULT_TICKERS))
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "COVERAGE.md")
    args = ap.parse_args()
    configure_logging()

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    rows = []
    for t in tickers:
        row = check(t)
        rows.append(row)
        if row["status"] == "ok":
            print(
                f"  [ok]      {t:6s} metrics={row['metrics']:>6s} chunks={row['chunks']:>4d} "
                f"changes={row['changes']} strategy={row['strategy']}"
            )
        else:
            print(f"  [{row['status']}] {t:6s} {row['detail'][:110]}")

    ok = [r for r in rows if r["status"] == "ok"]
    with_text = [r for r in ok if r["chunks"] > 0]

    lines = [
        "# Multi-filer coverage check",
        "",
        f"Run {datetime.now(UTC):%Y-%m-%d %H:%M UTC} over {len(rows)} filers, "
        "deterministic-only (no API key).",
        "",
        f"**{len(ok)}/{len(rows)} produced a usable comparison; "
        f"{len(with_text)}/{len(rows)} also produced text evidence.**",
        "",
        "This is a coverage measurement, not a correctness one — there is no hand-read ground "
        "truth for these filers. It exists to keep the README's generality claims honest.",
        "",
        "| Ticker | Company | Periods | Metrics | Chunks | Changes | Risk headings | Heading strategy | Confidence | Warnings |",
        "|---|---|---|---:|---:|---:|---|---|---|---:|",
    ]
    for r in rows:
        if r["status"] != "ok":
            lines.append(
                f"| **{r['ticker']}** | — | — | — | — | — | — | — | — | "
                f"`{r['status']}` |"
            )
            continue
        lines.append(
            f"| {r['ticker']} | {r['company'][:26]} | {r['periods']} | {r['metrics']} | "
            f"{r['chunks']} | {r['changes']} | {r['risk']} | `{r['strategy']}` | "
            f"{r['confidence']} | {r['warnings']} |"
        )
    lines.append("")

    refused = [r for r in rows if r["status"] != "ok"]
    if refused:
        lines += ["## Refused or crashed", ""]
        for r in refused:
            lines.append(f"- **{r['ticker']}** (`{r['status']}`): {r['detail']}")
        lines.append("")

    lines += ["## Metrics that degraded to N/A", ""]
    for r in ok:
        if r["missing"]:
            lines.append(f"- **{r['ticker']}**: {', '.join(r['missing'])}")
    lines += [
        "",
        "Missing metrics are reported as `N/A` with the concepts that were tried; nothing is "
        "estimated. Banks and insurance conglomerates legitimately lack gross profit, cost of "
        "revenue and PP&E-style capital expenditure, so a low metric count for those filers is "
        "correct behaviour rather than a failure.",
        "",
        "## What this check found",
        "",
        "- **Section anchoring needed three strategies, not one.** Upper-case item headings "
        "(`ITEM 1A.`) work for MSFT, WMT, UNH, KO and TSLA. Workiva-generated filings (AAPL, "
        "NVDA, BRK-B) use title case. P&G omits item numbers from the body entirely and needs "
        "bare title anchoring, which is reported at low confidence. Before this was fixed, four "
        "of ten filers produced **zero** text evidence with only a risk-diff warning.",
        "- **High-volume filers overflow the `recent` submissions block.** JPMorgan files ~25,000 "
        "documents, so `recent` spans a few weeks and holds one 10-K; the rest are in the "
        "paginated older shards. The tool refused JPM outright until it learned to read them.",
        "- **A reassigned ticker is a real condition.** XOM currently resolves to "
        "'ExxonMobil Holdings Corp' (CIK 0002115436) in the SEC ticker index, a registrant with "
        "no 10-K history. The tool refuses with an explanation rather than comparing the wrong "
        "entity — the correct outcome, but it cannot follow the ticker to the predecessor.",
    ]
    args.out.write_text("\n".join(lines) + "\n")
    print(f"\n{len(ok)}/{len(rows)} usable, {len(with_text)} with text evidence. Report: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
