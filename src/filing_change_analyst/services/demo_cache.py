"""Warm-start the disk cache from a bundled archive of SEC responses.

A cold run pulls ~30 MB from EDGAR, which SEC rate-limits by IP. The bundle
holds the raw bytes SEC returned, keyed by request URL — the same thing a live
run would cache, so nothing downstream changes.

Rebuild with ``python scripts/build_demo_cache.py``.
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
    """Return the archive members, rejecting any that escape ``dest``.

    Spelled out rather than relying on Python 3.12's ``filter="data"``, so the
    guarantee does not depend on the runtime's patch version.
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

    Skipped when the cache already holds entries, so a warm local cache is
    never overwritten. A missing or unreadable archive degrades to a slow cold
    start rather than raising.
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
