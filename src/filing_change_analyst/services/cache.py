"""Content-addressed disk cache for SEC responses.

Two reasons this exists:

1. SEC fair-access — repeated demo runs must not re-hammer EDGAR.
2. Reproducibility — a cached run produces byte-identical evidence, which is
   what makes the interview demo and the evaluation suite deterministic.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

from ..config import get_settings

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache_entries (
    key         TEXT PRIMARY KEY,
    url         TEXT NOT NULL,
    path        TEXT NOT NULL,
    fetched_at  REAL NOT NULL,
    byte_size   INTEGER NOT NULL
);
"""


def _key_for(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]


class DiskCache:
    """SQLite index + blob files on disk."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else get_settings().cache_path
        self.blobs = self.root / "blobs"
        self.blobs.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "cache.sqlite"
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(_SCHEMA)

    def get(self, url: str, max_age_s: float | None = None) -> bytes | None:
        key = _key_for(url)
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT path, fetched_at FROM cache_entries WHERE key = ?", (key,)
            ).fetchone()
        if not row:
            return None
        path, fetched_at = Path(row[0]), row[1]
        if not path.is_absolute():
            path = self.root / path
        if not path.exists():
            return None
        if max_age_s is not None and (time.time() - fetched_at) > max_age_s:
            return None
        return path.read_bytes()

    def put(self, url: str, payload: bytes) -> None:
        key = _key_for(url)
        path = self.blobs / f"{key}.bin"
        path.write_bytes(payload)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cache_entries (key, url, path, fetched_at, byte_size)"
                " VALUES (?, ?, ?, ?, ?)",
                (key, url, str(path.relative_to(self.root)), time.time(), len(payload)),
            )

    def get_json(self, url: str, max_age_s: float | None = None) -> Any | None:
        raw = self.get(url, max_age_s=max_age_s)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            log.warning("Discarding corrupt cache entry for %s", url)
            return None

    def invalidate(self, url: str) -> None:
        key = _key_for(url)
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT path FROM cache_entries WHERE key = ?", (key,)).fetchone()
            if row:
                p = self.root / row[0]
                p.unlink(missing_ok=True)
            conn.execute("DELETE FROM cache_entries WHERE key = ?", (key,))

    def stats(self) -> dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            n, total = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(byte_size), 0) FROM cache_entries"
            ).fetchone()
        return {"entries": n, "bytes": total, "root": str(self.root)}
