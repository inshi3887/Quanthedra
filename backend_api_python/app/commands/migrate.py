"""P1 strict migration entrypoint for deployments.

Pipeline (plan P1 task 4): ``init.sql -> dated migrations -> access
verification``. Every step fails closed: production must run this job
before serving traffic; application boot keeps a compatible auto-apply
mode but is no longer the migration authority.

Baseline adoption for pre-existing legacy databases (plan P1 task 7):

    python -m app.commands.migrate --baseline-stamp

compares the live schema against the reference manifest built from
``init.sql`` + all dated migrations. Stamp only happens on an exact
match; otherwise the command prints a reconciliation report and exits 1
(never silently stamps). Once stamped, the ledger is backfilled so the
next strict run treats every published migration as already applied.

Flags:
    (default)          strict pipeline on an empty/baseline-stamped DB
    --baseline-stamp   attempt legacy-database baseline adoption
    --check            plan only: report pending migrations, exit 1 if any
"""

from __future__ import annotations

import argparse
import sys

REFERENCE_FINGERPRINT_ENV = "QD_REFERENCE_SCHEMA_FINGERPRINT"


def _build_reference_manifest():
    """Build the reference manifest from init.sql + all dated migrations
    against a scratch schema in the same database, then drop it.

    Uses a raw connection: the app cursor wrapper rewrites INSERT-led
    statements (legacy lastrowid compat), which corrupts scripts that
    merely begin with an INSERT (e.g. the hk_universe_categories seed)."""
    from app.utils.migration_runner import _raw_connection, migrations_root
    from app.utils.schema_fingerprint import collect_manifest

    scratch = "p1_reference_schema_scratch"
    root = migrations_root()
    scripts = [
        root / "init.sql",
        root / "market_symbols_master.sql",
        root / "strategy_v2_templates.sql",
    ]
    dated = sorted((root / "dated").glob("*.sql"))

    conn = _raw_connection()
    try:
        cur = conn.cursor()
        try:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {scratch}")
            # search_path drives every unqualified CREATE in the scripts.
            cur.execute(f"SET search_path TO {scratch}")
            for script in scripts + dated:
                if script.exists():
                    cur.execute(script.read_text(encoding="utf-8"))
            conn.commit()
            manifest = collect_manifest(cur, schema=scratch)
        finally:
            try:
                conn.rollback()
                cur.execute(f"DROP SCHEMA IF EXISTS {scratch} CASCADE")
                conn.commit()
            except Exception:
                pass
            cur.close()
    finally:
        conn.close()
    return manifest


def run_baseline_stamp() -> int:
    from app.utils.db import get_db_connection
    from app.utils.logger import get_logger
    from app.utils.migration_runner import (
        _ADVISORY_LOCK_KEY,
        discover_dated_migrations,
    )
    from app.utils.schema_fingerprint import collect_manifest, diff_manifests, manifest_fingerprint

    logger = get_logger("p1.migrate")

    from app.utils.migration_runner import _raw_connection

    conn = _raw_connection()
    with conn:
        cur = conn.cursor()
        cur.execute("SELECT pg_advisory_lock(%s)", (_ADVISORY_LOCK_KEY,))
        try:
            reference = _build_reference_manifest()
            current = collect_manifest(cur)
            ref_fp = manifest_fingerprint(reference)
            cur_fp = manifest_fingerprint(current)
            logger.info(
                "Baseline probe: current=%s reference=%s",
                cur_fp[:16], ref_fp[:16],
            )
            if cur_fp != ref_fp:
                diffs = diff_manifests(current, reference)
                bar = "=" * 72
                print(bar)
                print("BASELINE ADOPTION REFUSED — schema does not match the")
                print("reference manifest built from init.sql + dated migrations.")
                print(f"diff count: {len(diffs)} (first 50 shown)")
                for line in diffs[:50]:
                    print(f"  - {line}")
                print("")
                print("Fix the drift manually (or restore from a known-good backup),")
                print("then re-run. This command will never silently stamp a")
                print("mismatched database (plan P1 task 7, fail closed).")
                print(bar)
                return 1

            # Exact match: create the ledger and backfill every dated
            # migration as applied (baseline stamp).
            cur.execute(
                "CREATE TABLE IF NOT EXISTS qd_schema_migrations ("
                " version VARCHAR(8) NOT NULL, name VARCHAR(200) NOT NULL,"
                " checksum VARCHAR(64) NOT NULL, applied_at TIMESTAMP NOT NULL DEFAULT NOW(),"
                " duration_ms INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (version, name))"
            )
            files = discover_dated_migrations()
            for mf in files:
                cur.execute(
                    "INSERT INTO qd_schema_migrations (version, name, checksum, duration_ms) "
                    "VALUES (%s, %s, %s, 0) ON CONFLICT (version, name) DO NOTHING",
                    (mf.version, mf.name, mf.checksum),
                )
            conn.commit()
            print(
                "Baseline adopted: schema matches the reference manifest; "
                f"{len(files)} dated migrations stamped into qd_schema_migrations."
            )
            print(f"Reference fingerprint: {ref_fp}")
            return 0
        finally:
            try:
                cur.execute("SELECT pg_advisory_unlock(%s)", (_ADVISORY_LOCK_KEY,))
                conn.commit()
            except Exception:
                conn.rollback()
            cur.close()
        conn.close()


def _plan_only() -> int:
    from app.utils.db import get_db_connection
    from app.utils.migration_runner import discover_dated_migrations

    pending_files = discover_dated_migrations()
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT count(*) AS n FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='qd_schema_migrations'"
        )
        if not cur.fetchone()["n"]:
            print(f"plan: {len(pending_files)} dated migrations pending (no ledger yet)")
            return 1 if pending_files else 0
        cur.execute("SELECT version, name FROM qd_schema_migrations")
        done = {(r["version"], r["name"]) for r in cur.fetchall()}
        outstanding = [mf.label for mf in pending_files if (mf.version, mf.name) not in done]
        for label in outstanding:
            print(f"pending: {label}")
        return 1 if outstanding else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline-stamp",
        action="store_true",
        help="attempt legacy-database baseline adoption (exact manifest match required)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="plan only: report pending dated migrations without applying",
    )
    args = parser.parse_args()

    if args.baseline_stamp:
        sys.exit(run_baseline_stamp())

    from app.security.bootstrap_guards import enforce_startup_security
    from app.utils.db import init_database
    from app.utils.migration_runner import (
        MigrationError,
        apply_dated_migrations_strict,
    )
    from app.utils.logger import get_logger

    logger = get_logger("p1.migrate")
    enforce_startup_security()

    if args.check:
        sys.exit(_plan_only())

    try:
        # Step 1: idempotent bootstrap schema (strict: abort on failure).
        init_database(strict_migrations=True)
        # Step 2: ordered dated migrations under the advisory lock.
        report = apply_dated_migrations_strict()
        # Step 3: critical-table access verification.
        from app.utils.db import _verify_table_access

        _verify_table_access(logger)
    except MigrationError as exc:
        logger.error("Migration run aborted: %s", exc)
        sys.exit(1)
    logger.info(
        "Strict migrate complete: %d applied, %d already applied",
        len(report["applied_now"]), len(report["already_applied"]),
    )


if __name__ == "__main__":
    main()
