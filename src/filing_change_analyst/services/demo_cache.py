"""Warm-start the disk cache from a bundled archive of SEC responses.

The hosted demo runs on a shared cloud IP, which is exactly the kind of client
SEC EDGAR throttles first, and a cold run would make a visitor wait through
~30 MB of downloads before seeing anything. So the repository ships a
pre-warmed copy of the SEC responses the demo tickers need, and this module
unpacks it into the cache directory the first time the app starts.

What is bundled is the *raw bytes SEC returned*, keyed by request URL — the same
thing :class:`~filing_change_analyst.services.cache.DiskCache` would have stored
after a live run. Nothing downstream changes: sections are still extracted,
facts still selected, and every figure still computed at request time. The
sidebar's "Bypass cache" toggle forces a live re-fetch, so the provenance claim
stays checkable.

Seeding is deliberately conservative — it is skipped entirely when the cache
already holds entries, so a developer's own warm cache is never overwritten and
the offline test suite is unaffected.

Rebuild the archive with ``python scripts/build_demo_cache.py``.
"""

from __future__ import annotations

import logging
import tarfile
from pathlib import Path

from ..config import PROJECT_ROOT
from .cache import DiskCache

log = logging.getLogger(__name__)

DEMO_CACHE_ARCHIVE = PROJECT_ROOT / "data" / "demo_cache.tar.gz"


class UnsafeArchiveError(RuntimeError):
    """Raised when an archive member would write outside the destination."""


def _safe_members(tf: tarfile.TarFile, dest: Path) -> list[tarfile.TarInfo]:
    """Return members that are plain files/dirs landing inside ``dest``.

    ``tarfile`` will happily honour ``../`` paths, absolute paths, symlinks and
    device nodes. The bundled archive is ours and contains none of those, but it
    arrives over the same git clone as everything else, so it is validated
    rather than trusted. Python 3.12's ``filter="data"`` does the equivalent;
    this is spelled out so the guarantee does not depend on the runtime's
    patch version.
    """
    resolved_dest = dest.resolve()
    safe: list[tarfile.TarInfo] = []
    for member in tf.getmembers():
        if not (member.isfile() or member.isdir()):
            raise UnsafeArchiveError(f"{member.name!r} is not a regular file or directory")
        target = (resolved_dest / member.name).resolve()
        if target != resolved_dest and resolved_dest not in target.parents:
            raise UnsafeArchiveError(f"{member.name!r} would escape {dest}")
        safe.append(member)
    return safe


def seed_demo_cache(archive: Path | None = None, cache: DiskCache | None = None) -> dict:
    """Extract the bundled cache when the live cache is empty.

    Returns the cache stats dict with an added ``seeded`` flag. Never raises on
    a missing or unreadable archive: a demo that starts slowly is a far better
    outcome than a demo that does not start.
    """
    cache = cache or DiskCache()
    stats = cache.stats()

    if stats["entries"]:
        return {**stats, "seeded": False}

    src = archive or DEMO_CACHE_ARCHIVE
    if not src.exists():
        log.info("No bundled cache at %s; the first run will fetch from SEC.", src)
        return {**stats, "seeded": False}

    try:
        with tarfile.open(src, "r:gz") as tf:
            tf.extractall(cache.root, members=_safe_members(tf, cache.root))
    except (OSError, tarfile.TarError, UnsafeArchiveError) as exc:
        log.warning("Could not seed the bundled cache from %s: %s", src, exc)
        return {**stats, "seeded": False}

    seeded = DiskCache(cache.root).stats()
    log.info(
        "Seeded %s cache entries (%.1f MB) from %s",
        seeded["entries"],
        seeded["bytes"] / 1e6,
        src.name,
    )
    return {**seeded, "seeded": True}
