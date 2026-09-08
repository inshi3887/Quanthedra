"""P1: ordered dated-migration runner with audit ledger.

Contract (DEVELOPMENT_PLAN第八版 §P1):

- Ledger table ``qd_schema_migrations(version, name, checksum, applied_at,
  duration_ms)`` records every applied dated migration.
- Files live in ``migrations/dated/`` and MUST be named ``YYYYMMDD_<name>.sql``.
  Anything else is an error (fail closed), not a warning.
- Migrations run in ascending (version, name) order; each in its own
  transaction; a failure leaves no ledger row and aborts the run.
- A PostgreSQL advisory lock serialises concurrent runners: the second
  instance waits, then observes the ledger and applies nothing.
- Already-applied files are checksum-verified; drift between the file on
  disk and the ledger checksum aborts the run (fail closed — someone
  edited published history).
- A file present in the ledger but missing on disk is an error.

The reference-schema manifest used by the legacy-database baseline probe
lives in :mod:`app.utils.schema_fingerprint`.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from app.utils.logger import get_logger

logger = get_logger(__name__)


MIGRATIONS_DIRNAME = "dated"
_FILENAME_RE = re.compile(r"^(\d{8})_[A-Za-z0-9_]+\.sql$")
_LEDGER_TABLE = "qd_schema_migrations"
_ADVISORY_LOCK_KEY = 0x51443100  # "QD1\0" — P1 migration runner, stable key

_LEDGER_DDL = """
CREATE TABLE IF NOT EXISTS qd_schema_migrations (
    version     VARCHAR(8)  NOT NULL,
    name        VARCHAR(200) NOT NULL,
    checksum    VARCHAR(64) NOT NULL,
    applied_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    duration_ms INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (version, name)
)
"""


class MigrationError(RuntimeError):
    """The migration run must abort; the database is left untouched for the
    failing step."""


@dataclass(frozen=True)
class MigrationFile:
    version: str
    name: str
    path: Path
    checksum: str

    @property
    def label(self) -> str:
        return f"{self.version}_{self.name}.sql"


def migrations_root() -> Path:
    """``backend_api_python/migrations`` — repo-layout independent."""
    return Path(__file__).resolve().parents[2] / "migrations"


def _checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def discover_dated_migrations(root: Optional[Path] = None) -> List[MigrationFile]:
    """Scan ``migrations/dated/`` and return files in execution order.

    Raises :class:`MigrationError` on: illegal filenames, duplicate
    ``(version, name)`` pairs (case variations included), or a missing
    directory (a fresh checkout must still fail loudly rather than silently
    applying zero migrations).
    """
    base = (root or migrations_root()) / MIGRATIONS_DIRNAME
    if not base.is_dir():
        raise MigrationError(f"Dated migration directory is missing: {base}")

    seen: dict[Tuple[str, str], Path] = {}
    out: List[MigrationFile] = []
    for entry in sorted(base.iterdir()):
        if not entry.is_file() or entry.name.startswith("."):
            continue
        match = _FILENAME_RE.match(entry.name)
        if not match:
            raise MigrationError(
                f"Illegal dated-migration filename {entry.name!r} in {base}: "
                "expected YYYYMMDD_<name>.sql"
            )
        version, name = match.group(1), entry.name[len(match.group(1)) + 1 : -4]
        key = (version, name.lower())
        if key in seen:
            raise MigrationError(
                f"Duplicate dated migration version/name: {entry.name} conflicts "
                f"with {seen[key].name}"
            )
        seen[key] = entry
        out.append(
            MigrationFile(
                version=version,
                name=name,
                path=entry,
                checksum=_checksum(entry.read_text(encoding="utf-8")),
            )
        )
    out.sort(key=lambda m: (m.version, m.name.lower()))
    return out


def _ensure_ledger(cur) -> None:
    cur.execute(_LEDGER_DDL)


def _fetch_ledger(cur) -> dict[Tuple[str, str], str]:
    cur.execute(f"SELECT version, name, checksum FROM {_LEDGER_TABLE}")
    return {(r["version"], r["name"]): r["checksum"] for r in (cur.fetchall() or [])}


def plan_run(files: List[MigrationFile], ledger: dict[Tuple[str, str], str]) -> Tuple[List[MigrationFile], List[str]]:
    """Split discovery output into (to_apply, already_applied_labels) and
    enforce checksum/missing-file invariants."""
    to_apply: List[MigrationFile] = []
    applied: List[str] = []
    for mf in files:
        key = (mf.version, mf.name)
        if key not in ledger:
            to_apply.append(mf)
            continue
        recorded = ledger[key]
        if recorded != mf.checksum:
            raise MigrationError(
                f"Checksum drift for {mf.label}: ledger={recorded[:12]}… "
                f"file={mf.checksum[:12]}… — published migrations must never be "
                "edited; write a new dated migration instead."
            )
        applied.append(mf.label)
    extra = set(ledger) - {(m.version, m.name) for m in files}
    if extra:
        version, name = sorted(extra)[0]
        raise MigrationError(
            f"Ledger row {version}_{name} has no matching file on disk — the "
            "migration history is incomplete on this checkout."
        )
    return to_apply, applied


def _raw_connection():
    """Dedicated psycopg2 connection for migration runs.

    Deliberately NOT the pooled/wrapped ``get_db_connection``: the app's
    cursor wrapper rewrites statements starting with INSERT to append
    ``RETURNING id`` (legacy lastrowid compat), which corrupts multi-statement
    migration scripts that merely *begin* with an INSERT. A bare cursor sends
    the script bytes verbatim. The dedicated connection also gives the
    advisory lock a clean session: closing the connection always releases
    it, even after a crash.
    """
    import psycopg2
    import psycopg2.extras

    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise MigrationError(
            "DATABASE_URL is not set; the migration runner cannot connect"
        )
    conn = psycopg2.connect(url, connect_timeout=15)
    conn.autocommit = False
    # Dict rows so the ledger helpers keep their key-based access.
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn


def run_dated_migrations(
    *,
    root: Optional[Path] = None,
    lock_timeout_seconds: int = 60,
) -> dict:
    """Apply all pending dated migrations. Returns a run report.

    Concurrent safety: ``pg_advisory_lock`` is taken on the dedicated
    migration connection before reading the ledger; a second runner
    therefore always re-reads the ledger after the first one commits and
    finds nothing to do (plan P1 acceptance: two runners apply each
    migration exactly once).
    """
    files = discover_dated_migrations(root)
    conn = _raw_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT pg_advisory_lock(%s)", (_ADVISORY_LOCK_KEY,))
        try:
            _ensure_ledger(cur)
            conn.commit()
            ledger = _fetch_ledger(cur)
            conn.commit()
            to_apply, applied_labels = plan_run(files, ledger)
            applied_now: List[str] = []
            for mf in to_apply:
                started = _now_ms()
                try:
                    # Each migration is one transaction (plan P1): a failure
                    # must leave neither schema changes nor a ledger row.
                    cur.execute(mf.path.read_text(encoding="utf-8"))
                    cur.execute(
                        f"INSERT INTO {_LEDGER_TABLE} (version, name, checksum, duration_ms) "
                        "VALUES (%s, %s, %s, %s)",
                        (mf.version, mf.name, mf.checksum, _now_ms() - started),
                    )
                    conn.commit()
                    applied_now.append(mf.label)
                    logger.info("Applied migration %s", mf.label)
                except Exception as exc:
                    conn.rollback()
                    raise MigrationError(f"Migration {mf.label} failed: {exc}") from exc
            return {
                "applied_now": applied_now,
                "already_applied": applied_labels,
                "total_files": len(files),
            }
        finally:
            try:
                cur.execute("SELECT pg_advisory_unlock(%s)", (_ADVISORY_LOCK_KEY,))
                conn.commit()
            except Exception:
                conn.rollback()
            cur.close()
    finally:
        conn.close()


def _now_ms() -> int:
    import time

    return int(time.monotonic() * 1000)


def apply_dated_migrations_strict() -> dict:
    """Entry point used by ``app.commands.migrate`` (strict mode):
    any error propagates and the deploy job exits non-zero."""
    report = run_dated_migrations()
    logger.info(
        "Dated migrations: %d applied now, %d already applied (of %d files)",
        len(report["applied_now"]),
        len(report["already_applied"]),
        report["total_files"],
    )
    return report


__all__ = [
    "MigrationError",
    "MigrationFile",
    "apply_dated_migrations_strict",
    "discover_dated_migrations",
    "plan_run",
    "run_dated_migrations",
]
