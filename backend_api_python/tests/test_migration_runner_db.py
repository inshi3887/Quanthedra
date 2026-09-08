"""P1 release-gate tests against a real PostgreSQL.

Gated on ``TEST_DATABASE_URL`` (a disposable database — the suite drops
and recreates the public schema between cases). Without it the whole
module skips, so offline CI is unaffected.

Covers the plan P1 acceptance items:
- fresh database: init.sql + every dated migration applies exactly once
  and the ledger records all of them;
- idempotency: a second run is a no-op;
- concurrency: two runners racing apply each migration exactly once
  (advisory lock serialises);
- checksum drift: editing an applied file fails the run;
- failure recovery: a failing migration leaves no ledger row and the
  following migration never ran;
- baseline probe: reference manifest matches a DB built by the full
  pipeline; a drifted DB is refused with a diff report.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.release_gate_db

pytest.importorskip("psycopg2")

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "")


def _db_available() -> bool:
    if not TEST_DATABASE_URL:
        return False
    try:
        import psycopg2

        conn = psycopg2.connect(TEST_DATABASE_URL, connect_timeout=5)
        conn.close()
        return True
    except Exception:
        return False


if not _db_available():
    pytest.skip("TEST_DATABASE_URL not set or database unreachable", allow_module_level=True)


@pytest.fixture()
def fresh_db(monkeypatch):
    """Drop and recreate the public schema for test isolation, and point the
    app connection pool at the test database for the duration of the case."""
    import psycopg2

    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("SKIP_AUTO_MIGRATE", "1")

    # Reset the pooled engine so it reconnects with the test URL.
    import app.utils.db_postgres as dbp

    monkeypatch.setattr(dbp, "_connection_pool", None)

    conn = psycopg2.connect(TEST_DATABASE_URL)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    cur.close()
    conn.close()
    yield TEST_DATABASE_URL


def _run_runner():
    from app.utils.migration_runner import run_dated_migrations

    return run_dated_migrations()


def _apply_init():
    from app.utils.db import _apply_init_sql
    from app.utils.logger import get_logger

    _apply_init_sql(get_logger("test"), strict=True)


def _ledger_rows():
    import psycopg2

    conn = psycopg2.connect(TEST_DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SELECT version, name FROM qd_schema_migrations ORDER BY version, name")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def test_fresh_database_applies_everything_once(fresh_db):
    _apply_init()
    report = _run_runner()
    assert len(report["applied_now"]) == 11
    assert report["already_applied"] == []

    # Idempotent second run.
    report2 = _run_runner()
    assert report2["applied_now"] == []
    assert len(report2["already_applied"]) == 11

    rows = _ledger_rows()
    assert len(rows) == 11
    # Deterministic ordering by (version, name).
    assert rows[0][0] <= rows[-1][0]


def test_concurrent_runners_apply_once(fresh_db):
    import threading

    _apply_init()
    results = []
    errors = []

    def worker():
        try:
            results.append(_run_runner())
        except Exception as exc:  # pragma: no cover — reported via errors
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)

    assert not errors, errors
    total_applied = sum(len(r["applied_now"]) for r in results)
    assert total_applied == 11, (
        "every migration must be applied exactly once across all runners"
    )
    assert len(_ledger_rows()) == 11


def test_checksum_drift_aborts(fresh_db):
    from app.utils.migration_runner import MigrationError

    _apply_init()
    _run_runner()

    # Corrupt the ledger checksum for one migration -> next run fails.
    import psycopg2

    conn = psycopg2.connect(TEST_DATABASE_URL)
    cur = conn.cursor()
    cur.execute(
        "UPDATE qd_schema_migrations SET checksum = 'deadbeef' "
        "WHERE ctid = (SELECT ctid FROM qd_schema_migrations LIMIT 1)"
    )
    cur.close()
    conn.commit()
    conn.close()

    with pytest.raises(MigrationError, match="Checksum drift"):
        _run_runner()


def test_failed_migration_leaves_no_ledger_row(fresh_db, tmp_path):
    from app.utils.migration_runner import MigrationError, run_dated_migrations

    _apply_init()
    # A migration set where the second file fails but the first succeeds.
    root = tmp_path
    dated = root / "dated"
    dated.mkdir()
    (dated / "20260101_ok.sql").write_text(
        "CREATE TABLE p1_gate_ok (id INT);", encoding="utf-8"
    )
    (dated / "20260102_bad.sql").write_text(
        "CREATE TABLE p1_gate_bad (id INT); CREATE TABLE p1_gate_bad (id INT);",
        encoding="utf-8",
    )
    (dated / "20260103_never.sql").write_text(
        "CREATE TABLE p1_gate_never (id INT);", encoding="utf-8"
    )

    with pytest.raises(MigrationError, match="20260102_bad"):
        run_dated_migrations(root=root)

    rows = _ledger_rows()
    # The first migration committed in its own transaction (per-transaction
    # contract) so it stays in the ledger; the failing one recorded nothing
    # and the third never ran.
    assert rows == [("20260101", "ok")], rows
    # The first migration's transaction committed (own-transaction contract);
    # the failing one left no table; the third never ran.
    import psycopg2

    conn = psycopg2.connect(TEST_DATABASE_URL)
    cur = conn.cursor()
    cur.execute(
        "SELECT to_regclass('public.p1_gate_ok') IS NOT NULL, "
        "       to_regclass('public.p1_gate_bad') IS NULL, "
        "       to_regclass('public.p1_gate_never') IS NULL"
    )
    ok, bad_absent, never_absent = cur.fetchone()
    cur.close()
    conn.close()
    assert ok and bad_absent and never_absent

    # Re-running after fixing the file converges (resumable): 20260101_ok
    # is already ledgered from the first pass, so only the two remainders
    # apply now.
    (dated / "20260102_bad.sql").write_text(
        "CREATE TABLE p1_gate_bad (id INT);", encoding="utf-8"
    )
    report = run_dated_migrations(root=root)
    assert report["applied_now"] == [
        "20260102_bad.sql",
        "20260103_never.sql",
    ]
    assert sorted(_ledger_rows()) == [("20260101", "ok"), ("20260102", "bad"), ("20260103", "never")]


def test_baseline_probe_matches_full_pipeline(fresh_db):
    from app.commands.migrate import _build_reference_manifest
    from app.utils.schema_fingerprint import (
        collect_manifest,
        diff_manifests,
        manifest_fingerprint,
    )

    _apply_init()
    _run_runner()

    import psycopg2

    conn = psycopg2.connect(TEST_DATABASE_URL)
    cur = conn.cursor()
    reference = _build_reference_manifest()
    current = collect_manifest(cur)
    cur.close()
    conn.close()

    diffs = diff_manifests(current, reference)
    assert diffs == [], f"pipeline-built DB must match reference: {diffs[:10]}"
    assert manifest_fingerprint(current) == manifest_fingerprint(reference)


def test_baseline_probe_refuses_drifted_database(fresh_db):
    from app.commands.migrate import _build_reference_manifest
    from app.utils.schema_fingerprint import (
        collect_manifest,
        diff_manifests,
    )

    _apply_init()
    _run_runner()
    # Simulated legacy drift: a manual table the reference doesn't have.
    import psycopg2

    conn = psycopg2.connect(TEST_DATABASE_URL)
    cur = conn.cursor()
    cur.execute("CREATE TABLE qd_legacy_manual_fix (id INT PRIMARY KEY)")
    conn.commit()

    reference = _build_reference_manifest()
    current = collect_manifest(cur)
    cur.close()
    conn.close()
    diffs = diff_manifests(current, reference)
    assert any("table-only-in-current: qd_legacy_manual_fix" in d for d in diffs)
