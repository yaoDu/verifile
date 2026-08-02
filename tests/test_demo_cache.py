"""The bundled warm cache: seeding, idempotence, and archive safety.

The hosted demo depends on this to render on a visitor's first click, and the
archive arrives over the same git clone as the code, so it is validated rather
than trusted. Every test here is offline and builds its own archives.
"""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from filing_change_analyst.services.cache import DiskCache
from filing_change_analyst.services.demo_cache import (
    UnsafeArchiveError,
    _safe_members,
    seed_demo_cache,
)

URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000789019.json"
PAYLOAD = b'{"entityName": "MICROSOFT CORPORATION"}'


def _archive(tmp_path: Path, entries: dict[str, bytes]) -> Path:
    """Build a demo-cache archive holding ``entries`` as {url: payload}."""
    staged = DiskCache(tmp_path / "staged")
    for url, payload in entries.items():
        staged.put(url, payload)
    out = tmp_path / "demo_cache.tar.gz"
    with tarfile.open(out, "w:gz") as tf:
        for path in sorted(staged.root.rglob("*")):
            tf.add(path, arcname=str(path.relative_to(staged.root)))
    return out


def test_seeds_an_empty_cache_and_payloads_survive(tmp_path):
    archive = _archive(tmp_path, {URL: PAYLOAD})
    cache = DiskCache(tmp_path / "live")
    assert cache.stats()["entries"] == 0

    state = seed_demo_cache(archive=archive, cache=cache)

    assert state["seeded"] is True
    assert state["entries"] == 1
    # The bytes must come back byte-identical: the whole provenance claim rests
    # on the cache returning exactly what SEC returned.
    assert DiskCache(tmp_path / "live").get(URL) == PAYLOAD


def test_a_warm_cache_is_never_overwritten(tmp_path):
    """A developer's own cache — or a live-fetched one — outranks the bundle."""
    archive = _archive(tmp_path, {URL: PAYLOAD})
    cache = DiskCache(tmp_path / "live")
    cache.put(URL, b'{"entityName": "FETCHED LIVE"}')

    state = seed_demo_cache(archive=archive, cache=cache)

    assert state["seeded"] is False
    assert DiskCache(tmp_path / "live").get(URL) == b'{"entityName": "FETCHED LIVE"}'


def test_seeding_is_idempotent(tmp_path):
    archive = _archive(tmp_path, {URL: PAYLOAD})
    root = tmp_path / "live"
    assert seed_demo_cache(archive=archive, cache=DiskCache(root))["seeded"] is True
    assert seed_demo_cache(archive=archive, cache=DiskCache(root))["seeded"] is False


def test_a_missing_archive_degrades_quietly(tmp_path):
    """A slow demo beats a demo that will not start: no raise, just no seed."""
    state = seed_demo_cache(archive=tmp_path / "absent.tar.gz", cache=DiskCache(tmp_path / "live"))
    assert state["seeded"] is False
    assert state["entries"] == 0


def test_a_corrupt_archive_degrades_quietly(tmp_path):
    corrupt = tmp_path / "demo_cache.tar.gz"
    corrupt.write_bytes(b"this is not a gzip stream")
    state = seed_demo_cache(archive=corrupt, cache=DiskCache(tmp_path / "live"))
    assert state["seeded"] is False


@pytest.mark.parametrize("name", ["../escaped.bin", "/etc/passwd", "blobs/../../escaped.bin"])
def test_traversal_members_are_refused(tmp_path, name):
    hostile = tmp_path / "hostile.tar.gz"
    with tarfile.open(hostile, "w:gz") as tf:
        info = tarfile.TarInfo(name)
        info.size = len(PAYLOAD)
        tf.addfile(info, io.BytesIO(PAYLOAD))

    dest = tmp_path / "live"
    dest.mkdir()
    with tarfile.open(hostile) as tf, pytest.raises(UnsafeArchiveError):
        _safe_members(tf, dest)


def test_symlink_members_are_refused(tmp_path):
    """A symlink member can redirect a later write outside the cache directory."""
    hostile = tmp_path / "hostile.tar.gz"
    with tarfile.open(hostile, "w:gz") as tf:
        info = tarfile.TarInfo("blobs/link.bin")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tf.addfile(info)

    dest = tmp_path / "live"
    dest.mkdir()
    with tarfile.open(hostile) as tf, pytest.raises(UnsafeArchiveError):
        _safe_members(tf, dest)


def test_a_hostile_archive_leaves_the_cache_empty(tmp_path):
    """The guard is wired into the public entry point, not just available."""
    hostile = tmp_path / "hostile.tar.gz"
    with tarfile.open(hostile, "w:gz") as tf:
        info = tarfile.TarInfo("../escaped.bin")
        info.size = len(PAYLOAD)
        tf.addfile(info, io.BytesIO(PAYLOAD))

    state = seed_demo_cache(archive=hostile, cache=DiskCache(tmp_path / "live"))

    assert state["seeded"] is False
    assert not (tmp_path / "escaped.bin").exists()


def test_the_shipped_archive_is_present_and_safe():
    """The archive actually committed to the repository must pass the same guard."""
    from filing_change_analyst.services.demo_cache import DEMO_CACHE_ARCHIVE

    assert DEMO_CACHE_ARCHIVE.exists(), (
        f"{DEMO_CACHE_ARCHIVE} is missing — rebuild it with "
        "`python scripts/build_demo_cache.py` before deploying."
    )
    with tarfile.open(DEMO_CACHE_ARCHIVE) as tf:
        members = _safe_members(tf, Path("/tmp/cache-dest"))
    assert any(m.name == "cache.sqlite" for m in members)
    assert any(m.name.startswith("blobs/") for m in members)
