"""Build the bundled warm cache shipped with the hosted demo.

Why this exists
---------------
The hosted demo has to render on a visitor's *first* click. A cold run pulls
~30 MB from SEC EDGAR and takes the better part of a minute; worse, EDGAR
rate-limits by IP, and a shared cloud host is not a friendly IP to share. So the
deployment ships a pre-warmed copy of exactly the SEC responses the demo tickers
need, and :mod:`filing_change_analyst.services.demo_cache` unpacks it on boot.

This is an ordinary HTTP cache warm-start, not canned output: the archive holds
the *raw bytes SEC returned*, keyed by URL, and every figure in the app is still
computed from them at request time. The sidebar's "Bypass cache" toggle forces a
live re-fetch, so a sceptical reviewer can prove that for themselves.

Regenerate with a warm local cache::

    python scripts/build_demo_cache.py

The archive is content-addressed the same way the live cache is, so rebuilding
after refreshing a filing produces a drop-in replacement.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import tarfile
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from filing_change_analyst.services.cache import DiskCache  # noqa: E402
from filing_change_analyst.services.demo_cache import DEMO_CACHE_ARCHIVE  # noqa: E402

# CIKs whose cached SEC responses are bundled. MSFT is the app default and
# carries three filings so that both the live FY2026/FY2025 pair and the pinned
# FY2025/FY2024 evaluation pair resolve offline. The other three are the ones
# worth reaching for in a walkthrough: AAPL and NVDA exercise the `mixed_case`
# section-anchoring strategy, and P&G is the `title_only` low-confidence case the
# README singles out as the system's weakest filer.
BUNDLED_CIKS = {
    "0000789019": "MSFT — app default, FY2026/FY2025/FY2024",
    "0000320193": "AAPL — mixed_case anchoring",
    "0001045810": "NVDA — mixed_case anchoring",
    "0000080424": "PG   — title_only anchoring, low confidence",
}

# The ticker index is CIK-independent and needed to resolve any ticker at all.
ALWAYS_INCLUDE = ("https://www.sec.gov/files/company_tickers.json",)


def _wanted(url: str) -> bool:
    if url in ALWAYS_INCLUDE:
        return True
    return any(
        f"CIK{cik}.json" in url or f"/data/{int(cik)}/" in url for cik in BUNDLED_CIKS
    )


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
        # Deterministic-ish archive: sorted members, so an unchanged cache
        # rebuilds to a byte-similar file instead of a noisy git diff.
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
    ap.add_argument(
        "--source",
        type=Path,
        default=REPO_ROOT / ".cache",
        help="Warm cache directory to draw from (default: ./.cache)",
    )
    ap.add_argument("--out", type=Path, default=DEMO_CACHE_ARCHIVE)
    args = ap.parse_args()
    if not args.source.exists():
        raise SystemExit(f"No cache at {args.source}")
    if shutil.which("git") and args.out.exists():
        print(f"Overwriting existing archive at {args.out}")
    build(args.source, args.out)


if __name__ == "__main__":
    main()
