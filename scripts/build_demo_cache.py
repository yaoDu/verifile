"""Build the warm cache bundled with the hosted deployment.

Selects the cached SEC responses for the demo tickers from a warm local cache
and writes them to ``data/demo_cache.tar.gz``, which
:mod:`filing_change_analyst.services.demo_cache` unpacks on first start.

Usage::

    python scripts/build_demo_cache.py
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import tarfile
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from filing_change_analyst.services.cache import DiskCache  # noqa: E402
from filing_change_analyst.services.demo_cache import DEMO_CACHE_ARCHIVE  # noqa: E402

# MSFT carries three filings so both the live pair and the pinned evaluation
# pair resolve offline. The rest cover the other section-anchoring strategies.
#
# Both forms are bundled per filer. The 10-Q selector is offered in the UI, so a
# 10-Q that has to be fetched live is a 10-Q that fails on a cold container the
# first time SEC rate-limits it — the earlier bundle held 10-K documents only.
BUNDLED_CIKS = {
    "0000789019": "MSFT — app default, FY2026/FY2025/FY2024 + Q3 10-Qs",
    "0000320193": "AAPL — mixed_case anchoring",
    "0001045810": "NVDA — mixed_case anchoring",
    "0000080424": "PG   — title_only anchoring, low confidence",
}

# CIK-independent, and needed to resolve any ticker at all.
ALWAYS_INCLUDE = ("https://www.sec.gov/files/company_tickers.json",)


def _wanted(url: str) -> bool:
    if url in ALWAYS_INCLUDE:
        return True
    return any(f"CIK{cik}.json" in url or f"/data/{int(cik)}/" in url for cik in BUNDLED_CIKS)


def build(source_root: Path, out: Path) -> None:
    source = DiskCache(source_root)
    with sqlite3.connect(source.db_path) as conn:
        rows = conn.execute("SELECT url, byte_size FROM cache_entries").fetchall()

    selected = [(url, size) for url, size in rows if _wanted(url)]
    if not selected:
        raise SystemExit(
            f"No matching entries in {source_root}. Run the app once against the "
            "bundled tickers to warm the cache, then re-run this script."
        )

    with tempfile.TemporaryDirectory() as tmp:
        staged = DiskCache(Path(tmp) / "cache")
        copied = 0
        for url, _ in selected:
            payload = source.get(url, max_age_s=None)
            if payload is None:
                print(f"  ! skipping (blob missing): {url}")
                continue
            staged.put(url, payload)
            copied += 1

        out.parent.mkdir(parents=True, exist_ok=True)
        # Sorted members keep rebuilds from producing a noisy git diff.
        with tarfile.open(out, "w:gz") as tf:
            for path in sorted(staged.root.rglob("*")):
                tf.add(path, arcname=str(path.relative_to(staged.root)))

    raw = sum(size for _, size in selected)
    print(f"\nBundled {copied} cache entries for {len(BUNDLED_CIKS)} filers:")
    for cik, note in BUNDLED_CIKS.items():
        print(f"  {cik}  {note}")
    print(f"\n  raw        {raw / 1e6:7.2f} MB")
    print(f"  compressed {out.stat().st_size / 1e6:7.2f} MB  -> {out}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, default=REPO_ROOT / ".cache")
    ap.add_argument("--out", type=Path, default=DEMO_CACHE_ARCHIVE)
    args = ap.parse_args()
    if not args.source.exists():
        raise SystemExit(f"No cache at {args.source}")
    build(args.source, args.out)


if __name__ == "__main__":
    main()
