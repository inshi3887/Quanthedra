"""P0A credential re-encryption migration (legacy blobs -> v2 envelopes).

What it does
------------
Scans every table/column that stores P0A-encrypted material:

    qd_exchange_credentials.encrypted_config  -> purpose=broker-credential
    qd_user_mfa.secret_encrypted              -> purpose=mfa-secret

For each row it converts the stored blob to the versioned envelope:

1. legacy raw-Fernet value  -> decrypt with the legacy key set
   (``CREDENTIAL_ENCRYPTION_KEY`` then the historical ``SECRET_KEY``
   fallback), re-encrypt as ``v2:<purpose>:<active-key-id>:...``.
2. v2 envelope whose key-id is NOT the active key (e.g. during key
   rotation) -> decrypt with the matching collection key, re-encrypt
   under the active key.
3. v2 envelope already on the active key -> untouched (idempotent).

Safety properties (plan P0A task 8):

- Idempotent: re-running converges; already-migrated rows are skipped.
- Resumable: rows are processed in deterministic primary-key batches with
  per-row commits; an interrupted run continues where it stopped.
- Auditable: every conversion writes one row to ``qd_p0a_migration_log``
  (append-only) recording table, row id, purpose, source kind
  (legacy/envelope), source key-id, target key-id and checksums — never
  plaintext, never the raw keys.
- Fail-closed per row: a row that cannot be converted is counted and
  left untouched (the old value keeps working with its legacy key) and
  the run reports it instead of guessing.

Usage::

    python -m app.commands.migrate_credentials            # apply
    python -m app.commands.migrate_credentials --dry-run  # report only
    python -m app.commands.migrate_credentials --batch-size 200
"""

from __future__ import annotations

import argparse
import hashlib
import sys

# (table, primary key column, blob column, purpose) — keep in sync with
# migrations/init.sql and the credential_crypto caller inventory.
TARGETS = (
    ("qd_exchange_credentials", "id", "encrypted_config", "broker-credential"),
    ("qd_user_mfa", "user_id", "secret_encrypted", "mfa-secret"),
)

_LOG_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS qd_p0a_migration_log (
    id SERIAL PRIMARY KEY,
    table_name VARCHAR(64) NOT NULL,
    row_key BIGINT NOT NULL,
    purpose VARCHAR(32) NOT NULL,
    source_kind VARCHAR(16) NOT NULL,
    source_key_id VARCHAR(64) NOT NULL,
    target_key_id VARCHAR(64) NOT NULL,
    source_sha256 VARCHAR(64) NOT NULL DEFAULT '',
    target_sha256 VARCHAR(64) NOT NULL DEFAULT '',
    migrated_at TIMESTAMP DEFAULT NOW()
)
"""


def _checksum(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fetch_batch(cur, table: str, pk: str, blob_col: str, after_key: int, batch_size: int):
    cur.execute(
        f"SELECT {pk} AS row_key, {blob_col} AS blob FROM {table} "
        f"WHERE {pk} > %s ORDER BY {pk} LIMIT %s",
        (after_key, batch_size),
    )
    return cur.fetchall() or []


def _classify(blob: str):
    """Return (kind, purpose, key_id) for a stored blob."""
    from app.utils.credential_crypto import is_envelope

    if not blob or not blob.strip():
        return ("empty", "", "")
    if is_envelope(blob):
        parts = blob.strip().split(":", 3)
        return ("envelope", parts[1], parts[2])
    return ("legacy", "", "")


def _convert_row(blob: str, purpose: str, dry_run: bool):
    """Convert one blob. Returns (new_blob, source_kind, source_key_id)."""
    from app.utils.credential_crypto import (
        active_key,
        decrypt_credential_blob,
        decrypt_legacy_blob,
        encrypt_credential_blob,
    )

    kind, stored_purpose, source_key_id = _classify(blob)
    if kind == "empty":
        return None, kind, ""
    active_key_id, _ = active_key()
    if kind == "envelope" and stored_purpose == purpose and source_key_id == active_key_id:
        return None, "current", source_key_id
    if kind == "legacy":
        plaintext = decrypt_legacy_blob(blob)
        source_key_id = "legacy"
    else:
        plaintext = decrypt_credential_blob(blob, purpose)
    if dry_run:
        return f"dry-run:{purpose}", kind, source_key_id
    return encrypt_credential_blob(plaintext, purpose), kind, source_key_id


def run(batch_size: int = 100, dry_run: bool = False) -> int:
    from app.utils.db import get_db_connection
    from app.utils.logger import get_logger

    logger = get_logger("p0a.migrate_credentials")

    totals = {"legacy": 0, "envelope": 0, "current": 0, "empty": 0, "error": 0}
    if not dry_run:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(_LOG_TABLE_DDL)
            db.commit()
            cur.close()

    for table, pk, blob_col, purpose in TARGETS:
        after_key = 0
        logger.info("Scanning %s.%s (purpose=%s)", table, blob_col, purpose)
        while True:
            with get_db_connection() as db:
                cur = db.cursor()
                rows = _fetch_batch(cur, table, pk, blob_col, after_key, batch_size)
                cur.close()
            if not rows:
                break
            for row in rows:
                row_key = int(row["row_key"])
                after_key = max(after_key, row_key)
                blob = row.get("blob") or ""
                try:
                    new_blob, kind, source_key_id = _convert_row(blob, purpose, dry_run)
                except Exception as exc:
                    totals["error"] += 1
                    logger.error(
                        "Row %s.%s could not be converted: %s",
                        table, row_key, type(exc).__name__,
                    )
                    continue
                totals[kind] = totals.get(kind, 0) + 1
                if new_blob is None:
                    continue
                if dry_run:
                    logger.info(
                        "[dry-run] would migrate %s.%s kind=%s source_key=%s -> active",
                        table, row_key, kind, source_key_id or "-",
                    )
                    continue
                with get_db_connection() as db:
                    cur = db.cursor()
                    cur.execute(
                        f"UPDATE {table} SET {blob_col} = %s WHERE {pk} = %s",
                        (new_blob, row_key),
                    )
                    cur.execute(
                        "INSERT INTO qd_p0a_migration_log "
                        "(table_name, row_key, purpose, source_kind, source_key_id, target_key_id, "
                        " source_sha256, target_sha256) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                        (
                            table,
                            row_key,
                            purpose,
                            kind,
                            source_key_id,
                            (new_blob.split(":")[2] if new_blob.count(":") >= 3 else "?"),
                            _checksum(blob),
                            _checksum(new_blob),
                        ),
                    )
                    db.commit()
                    cur.close()

    logger.info(
        "Migration summary: legacy=%(legacy)d re-encrypted=%(envelope)d "
        "already-current=%(current)d empty=%(empty)d errors=%(error)d dry_run=%s",
        {**totals, "dry_run": dry_run},
    )
    return 0 if totals["error"] == 0 else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true", help="report without writing")
    args = parser.parse_args()

    # The migration reads legacy material; it does not require the full app,
    # but it MUST run with the same key configuration as the services.
    from app.security.bootstrap_guards import enforce_startup_security, credential_inventory_report
    from app.utils.logger import get_logger

    enforce_startup_security()
    get_logger("p0a.migrate_credentials").info("Key inventory: %s", credential_inventory_report())
    sys.exit(run(batch_size=max(1, args.batch_size), dry_run=args.dry_run))


if __name__ == "__main__":
    main()
