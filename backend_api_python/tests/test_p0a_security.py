"""P0A/G0A tests: versioned credential envelope, bootstrap guards and the
insecure-key write block.

Covers the P0A acceptance items:
- v2 envelope round-trip, key-id selection, purpose isolation, collection
  reads across rotation;
- SECRET_KEY is never used by online write/read paths (legacy blobs only
  via decrypt_legacy_blob);
- staging/production startup guards refuse missing persistent keys and
  default admin passwords;
- ALLOW_INSECURE_DEV_KEY semantics: dev-only, blocks sensitive writes,
  refused outside development;
- migration command conversion paths (legacy -> v2, rotation, idempotency).
"""

from __future__ import annotations

import base64
import hashlib
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet

from app.security.bootstrap_guards import (
    InsecureKeyWriteBlocked,
    SecurityBootstrapError,
    deployment_env,
    enforce_startup_security,
    insecure_dev_key_active,
    resolve_persistent_credential_key,
)
from app.utils.credential_crypto import (
    CredentialCryptoError,
    PURPOSE_BROKER_CREDENTIAL,
    PURPOSE_MFA_SECRET,
    active_key,
    decrypt_credential_blob,
    decrypt_legacy_blob,
    encrypt_credential_blob,
    is_envelope,
    key_collection,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Strip every P0A-related variable so tests are order-independent."""
    for var in (
        "CREDENTIAL_ENCRYPTION_KEY",
        "CREDENTIAL_ENCRYPTION_KEYS",
        "CREDENTIAL_ENCRYPTION_ACTIVE_KEY_ID",
        "CREDENTIAL_ENCRYPTION_KEY_FILE",
        "DEPLOYMENT_ENV",
        "ADMIN_PASSWORD",
        "ALLOW_INSECURE_DEV_KEY",
        "SECRET_KEY",
    ):
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# Envelope: round-trip, key selection, purpose isolation
# ---------------------------------------------------------------------------


def test_roundtrip_encodes_purpose_and_fingerprint(monkeypatch):
    from app.utils.credential_crypto import key_fingerprint

    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "k1")
    blob = encrypt_credential_blob('{"a":1}', PURPOSE_BROKER_CREDENTIAL)
    assert blob.startswith(f"v2:broker-credential:{key_fingerprint('k1')}:")
    assert decrypt_credential_blob(blob, PURPOSE_BROKER_CREDENTIAL) == '{"a":1}'


def test_purpose_isolation_blocks_cross_decrypt(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "k1")
    broker = encrypt_credential_blob("{}", PURPOSE_BROKER_CREDENTIAL)
    mfa = encrypt_credential_blob("{}", PURPOSE_MFA_SECRET)
    with pytest.raises(CredentialCryptoError, match="purpose mismatch"):
        decrypt_credential_blob(broker, PURPOSE_MFA_SECRET)
    with pytest.raises(CredentialCryptoError, match="purpose mismatch"):
        decrypt_credential_blob(mfa, PURPOSE_BROKER_CREDENTIAL)


def test_unknown_purpose_rejected(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "k1")
    with pytest.raises(CredentialCryptoError, match="Unknown credential purpose"):
        encrypt_credential_blob("{}", "totally-not-a-purpose")


def test_no_key_at_all_fails_closed(monkeypatch):
    with pytest.raises(Exception):
        encrypt_credential_blob("{}", PURPOSE_BROKER_CREDENTIAL)


def test_secret_key_never_used_by_online_paths(monkeypatch):
    """The historical fallback is gone: a write with only SECRET_KEY set
    must fail, and a legacy SECRET_KEY blob must not decrypt online."""
    monkeypatch.setenv("SECRET_KEY", "legacy-session-secret")
    with pytest.raises(Exception):
        encrypt_credential_blob("{}", PURPOSE_BROKER_CREDENTIAL)
    fkey = base64.urlsafe_b64encode(hashlib.sha256(b"legacy-session-secret").digest())
    legacy = Fernet(fkey).encrypt(b"{}").decode()
    with pytest.raises(CredentialCryptoError, match="not a v2 envelope"):
        decrypt_credential_blob(legacy, PURPOSE_BROKER_CREDENTIAL)
    # ...but the explicit migration-only path still reads it.
    assert decrypt_legacy_blob(legacy) == "{}"


# ---------------------------------------------------------------------------
# Versioned key collection and rotation
# ---------------------------------------------------------------------------


def test_collection_reads_old_and_new_keys(monkeypatch):
    from app.utils.credential_crypto import key_fingerprint

    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEYS", "old-1:aaa,primary:bbb")
    old_blob = _encrypt_with_raw_key("aaa", "data")
    assert old_blob.split(":")[2] == key_fingerprint("aaa")
    # A blob whose fingerprint names the old key decrypts with the old key.
    assert decrypt_credential_blob(old_blob, PURPOSE_BROKER_CREDENTIAL) == "data"


def test_active_key_id_selection(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEYS", "old-1:aaa,primary:bbb")
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_ACTIVE_KEY_ID", "primary")
    assert active_key()[1] == "bbb"
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_ACTIVE_KEY_ID", "old-1")
    assert active_key()[1] == "aaa"


def test_active_key_single_entry_needs_no_marker(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEYS", "only:zzz")
    monkeypatch.delenv("CREDENTIAL_ENCRYPTION_KEY", raising=False)
    assert active_key()[1] == "zzz"


def test_active_key_id_must_exist(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEYS", "primary:bbb")
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_ACTIVE_KEY_ID", "missing")
    with pytest.raises(CredentialCryptoError, match="not a"):
        active_key()


def test_multi_entry_collection_requires_marker(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEYS", "old-1:aaa,new-2:bbb")
    monkeypatch.delenv("CREDENTIAL_ENCRYPTION_KEY", raising=False)
    with pytest.raises(CredentialCryptoError, match="ACTIVE_KEY_ID"):
        active_key()


def test_missing_key_id_in_blob_reports_configuration_error(monkeypatch):
    from app.utils.credential_crypto import key_fingerprint

    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "k1")
    blob = encrypt_credential_blob("x", PURPOSE_BROKER_CREDENTIAL)
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "k2")  # swap key value
    with pytest.raises(CredentialCryptoError, match=key_fingerprint("k1")):
        decrypt_credential_blob(blob, PURPOSE_BROKER_CREDENTIAL)


def test_rotation_full_cycle(monkeypatch):
    from app.utils.credential_crypto import key_fingerprint

    # Phase 1: encrypt under the old compat key.
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "old")
    blob = encrypt_credential_blob('{"k":"v"}', PURPOSE_BROKER_CREDENTIAL)
    assert blob.split(":")[2] == key_fingerprint("old")
    # Phase 2: rotate — new key active, old key kept readable.
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEYS", "old-1:old,primary:new")
    monkeypatch.delenv("CREDENTIAL_ENCRYPTION_KEY")
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_ACTIVE_KEY_ID", "primary")
    assert decrypt_credential_blob(blob, PURPOSE_BROKER_CREDENTIAL) == '{"k":"v"}'
    rotated = encrypt_credential_blob('{"k":"v"}', PURPOSE_BROKER_CREDENTIAL)
    assert rotated.split(":")[2] == key_fingerprint("new")
    # Phase 3: shrink to the new key only.
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEYS", "primary:new")
    monkeypatch.delenv("CREDENTIAL_ENCRYPTION_ACTIVE_KEY_ID")
    assert decrypt_credential_blob(rotated, PURPOSE_BROKER_CREDENTIAL) == '{"k":"v"}'


def _encrypt_with_raw_key(secret: str, plaintext: str) -> str:
    from app.utils.credential_crypto import key_fingerprint

    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    token = Fernet(key).encrypt(plaintext.encode()).decode()
    return f"v2:{PURPOSE_BROKER_CREDENTIAL}:{key_fingerprint(secret)}:{token}"


# ---------------------------------------------------------------------------
# Startup guards
# ---------------------------------------------------------------------------


def test_env_defaults_to_development(monkeypatch):
    assert deployment_env() == "development"


def test_invalid_env_rejected(monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_ENV", "prod")
    with pytest.raises(SecurityBootstrapError, match="invalid"):
        deployment_env()


def test_production_requires_persistent_key(monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_ENV", "production")
    monkeypatch.setenv("ADMIN_PASSWORD", "strong-password")
    with pytest.raises(SecurityBootstrapError, match="persistent key"):
        enforce_startup_security()


def test_production_requires_non_default_admin_password(monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_ENV", "production")
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "k1")
    monkeypatch.setenv("ADMIN_PASSWORD", "123456")
    with pytest.raises(SecurityBootstrapError, match="default"):
        enforce_startup_security()
    monkeypatch.delenv("ADMIN_PASSWORD")
    with pytest.raises(SecurityBootstrapError, match="default"):
        enforce_startup_security()
    monkeypatch.setenv("ADMIN_PASSWORD", "s3cure!")
    enforce_startup_security()  # no raise


def test_staging_same_rules(monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_ENV", "staging")
    with pytest.raises(SecurityBootstrapError):
        enforce_startup_security()


def test_development_requires_key_or_explicit_optin(monkeypatch):
    with pytest.raises(SecurityBootstrapError, match="ALLOW_INSECURE_DEV_KEY"):
        enforce_startup_security()
    monkeypatch.setenv("ALLOW_INSECURE_DEV_KEY", "true")
    enforce_startup_security()  # no raise


def test_insecure_dev_key_refused_outside_development(monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_ENV", "production")
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "k1")
    monkeypatch.setenv("ADMIN_PASSWORD", "s3cure!")
    monkeypatch.setenv("ALLOW_INSECURE_DEV_KEY", "true")
    with pytest.raises(SecurityBootstrapError, match="only valid"):
        enforce_startup_security()


def test_key_file_injection(tmp_path, monkeypatch):
    key_file = tmp_path / "credential_key"
    key_file.write_text("file-key-value\n")
    monkeypatch.setenv("DEPLOYMENT_ENV", "production")
    monkeypatch.setenv("ADMIN_PASSWORD", "s3cure!")
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY_FILE", str(key_file))
    assert resolve_persistent_credential_key() == "file-key-value"
    enforce_startup_security()  # file key satisfies the guard


def test_missing_key_file_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_ENV", "production")
    monkeypatch.setenv("ADMIN_PASSWORD", "s3cure!")
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY_FILE", str(tmp_path / "absent"))
    with pytest.raises(SecurityBootstrapError, match="cannot be read"):
        enforce_startup_security()


# ---------------------------------------------------------------------------
# Insecure-key write block (dev-only escape hatch)
# ---------------------------------------------------------------------------


def test_insecure_key_blocks_sensitive_writes(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_DEV_KEY", "true")
    assert insecure_dev_key_active() is True
    for purpose in (PURPOSE_BROKER_CREDENTIAL, PURPOSE_MFA_SECRET):
        with pytest.raises(InsecureKeyWriteBlocked):
            encrypt_credential_blob("{}", purpose)


def test_persistent_key_disables_insecure_mode(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_DEV_KEY", "true")
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "k1")
    assert insecure_dev_key_active() is False
    blob = encrypt_credential_blob("{}", PURPOSE_BROKER_CREDENTIAL)
    assert decrypt_credential_blob(blob, PURPOSE_BROKER_CREDENTIAL) == "{}"


def test_non_sensitive_purposes_unaffected(monkeypatch):
    """Only the two credential purposes are guarded; arbitrary purposes are
    rejected by the envelope validation instead of the write block."""
    monkeypatch.setenv("ALLOW_INSECURE_DEV_KEY", "true")
    with pytest.raises(CredentialCryptoError, match="Unknown credential purpose"):
        encrypt_credential_blob("{}", "settings-snapshot")


# ---------------------------------------------------------------------------
# Migration command conversion logic (pure part)
# ---------------------------------------------------------------------------


def test_migration_classify_and_convert(monkeypatch):
    from app.commands.migrate_credentials import _classify, _convert_row

    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "newkey")
    monkeypatch.setenv("SECRET_KEY", "oldsession")

    assert _classify("") == ("empty", "", "")
    assert _classify("   ") == ("empty", "", "")

    fkey = base64.urlsafe_b64encode(hashlib.sha256(b"oldsession").digest())
    legacy = Fernet(fkey).encrypt(b'{"legacy":1}').decode()
    assert _classify(legacy) == ("legacy", "", "")
    new_blob, kind, src = _convert_row(legacy, PURPOSE_BROKER_CREDENTIAL, dry_run=False)
    assert kind == "legacy" and src == "legacy"
    assert is_envelope(new_blob)
    assert decrypt_credential_blob(new_blob, PURPOSE_BROKER_CREDENTIAL) == '{"legacy":1}'

    current = encrypt_credential_blob('{"cur":2}', PURPOSE_MFA_SECRET)
    fp = current.split(":")[2]
    assert _classify(current) == ("envelope", PURPOSE_MFA_SECRET, fp)
    out, kind, _ = _convert_row(current, PURPOSE_MFA_SECRET, dry_run=False)
    assert out is None and kind == "current"  # already current -> untouched

    # Wrong-purpose envelope still reported correctly.
    assert _classify(current) != ("envelope", PURPOSE_BROKER_CREDENTIAL, fp)
    with pytest.raises(Exception):
        _convert_row(current, PURPOSE_BROKER_CREDENTIAL, dry_run=False)


def test_migration_dry_run_writes_nothing(monkeypatch):
    from app.commands.migrate_credentials import _convert_row

    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "newkey")
    monkeypatch.setenv("SECRET_KEY", "oldsession")
    fkey = base64.urlsafe_b64encode(hashlib.sha256(b"oldsession").digest())
    legacy = Fernet(fkey).encrypt(b'{"x":1}').decode()
    out, kind, src = _convert_row(legacy, PURPOSE_BROKER_CREDENTIAL, dry_run=True)
    assert kind == "legacy" and src == "legacy"
    assert out.startswith("dry-run:")
