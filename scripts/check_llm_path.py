"""Exercise the live model path and report what happened.

Runs one real synthesis against the pinned MSFT pair and prints which calls
succeeded, how the four gates behaved, and where tokens went. The key is read
from the environment and never printed.

    export API_KEY="sk-ant-..."       # or put it in .env
    python scripts/check_llm_path.py

Exits non-zero if every model call failed.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from filing_change_analyst.config import get_settings  # noqa: E402
from filing_change_analyst.pipeline import (  # noqa: E402
    apply_ai_synthesis,
    available_filings,
    pair_from_filings,
    run_analysis,
)
from filing_change_analyst.services.llm import LlmClient  # noqa: E402

# Pinned by accession so the run is reproducible.
FY2025 = "0000950170-25-100235"
FY2024 = "0000950170-24-087843"


def main() -> int:
    settings = get_settings()
    if not settings.llm_available:
        print("No API_KEY configured. Set it in the environment or .env and re-run.")
        return 2

    print(f"model      {settings.llm_model}")
    print(f"effort     {settings.llm_effort}")
    print(f"max_tokens {settings.llm_max_tokens}")
    print(f"timeout    {settings.llm_timeout:.0f}s\n")

    by_accession = {f.accession: f for f in available_filings("MSFT", "10-K")}
    missing = [a for a in (FY2024, FY2025) if a not in by_accession]
    if missing:
        print(f"Pinned filings not found: {', '.join(missing)}")
        return 2
    pair = pair_from_filings(by_accession[FY2024], by_accession[FY2025])

    print("Running the deterministic pipeline…")
    bundle = run_analysis("MSFT", "10-K", pair=pair)
    before = len(bundle.result.changes)

    print("Calling the model…\n")
    bundle = apply_ai_synthesis(bundle, client=LlmClient())
    result = bundle.result

    ok_calls = 0
    for r in result.llm_logs:
        status = "ok" if r.ok else "FAILED"
        print(f"[{status}] {r.purpose}")
        print(f"    prompt {r.prompt_version} · {r.latency_ms} ms · "
              f"tokens in/out {r.input_tokens}/{r.output_tokens}")
        if r.error:
            print(f"    error: {r.error}")
        if r.dropped_citations:
            print(f"    citations rejected by the gate: {', '.join(r.dropped_citations)}")
        if r.dropped_changes:
            print(f"    claims discarded by the gates: {r.dropped_changes}")
        print()
        ok_calls += bool(r.ok)

    print(f"material changes: {before} deterministic -> {len(result.changes)} after synthesis")
    print(f"brief sections added: {sorted(result.brief_extras) if result.brief_extras else 'none'}")
    if result.data_notes:
        print("\nnotes:")
        for note in result.data_notes:
            print(f"  · {note}")

    if not ok_calls:
        print(
            "\nEvery model call failed. A 'truncated before it produced valid JSON' "
            "error usually means max_tokens is too low: thinking and the response "
            "share that budget. Try FCA_LLM_MAX_TOKENS=32000."
        )
        return 1

    print(f"\n{ok_calls}/{len(result.llm_logs)} model calls succeeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
