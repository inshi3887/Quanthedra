"""Legacy behaviour preserved under the P0A envelope contract.

P0A (ADR-P0A-001) removed the SECRET_KEY fallback from online paths and
made the ciphertext a purpose-bound v2 envelope. The two properties the
original tests protected still hold, expressed against the new contract:

1. Credential encryption is independent of SECRET_KEY rotation.
2. Pre-P0A raw-Fernet ciphertexts (including ones a legacy deployment
   made with only SECRET_KEY configured) remain readable through the
   migration-only path and are re-issued as v2 envelopes.
"""

from base64 import urlsafe_b64encode
from hashlib import sha256

from cryptography.fernet import Fernet

from app.utils.credential_crypto import (
    PURPOSE_BROKER_CREDENTIAL,
    decrypt_credential_blob,
    decrypt_legacy_blob,
    encrypt_credential_blob,
    is_envelope,
)


def _legacy_fernet(secret: str, plaintext: str) -> str:
    key = urlsafe_b64encode(sha256(secret.encode()).digest())
    return Fernet(key).encrypt(plaintext.encode()).decode()


def test_dedicated_credential_key_survives_secret_key_rotation(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "credential-key-a")
    monkeypatch.setenv("SECRET_KEY", "session-key-a")
    encrypted = encrypt_credential_blob('{"exchange_id":"alpaca"}', PURPOSE_BROKER_CREDENTIAL)

    monkeypatch.setenv("SECRET_KEY", "session-key-b")

    assert decrypt_credential_blob(encrypted, PURPOSE_BROKER_CREDENTIAL) == '{"exchange_id":"alpaca"}'


def test_legacy_secret_key_ciphertext_remains_readable(monkeypatch):
    """A pre-P0A blob made under SECRET_KEY-only configuration decrypts via
    the migration path and re-encrypts as a v2 envelope under the new key."""
    monkeypatch.delenv("CREDENTIAL_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("SECRET_KEY", "legacy-session-key")
    legacy_blob = _legacy_fernet("legacy-session-key", "legacy-secret")

    # The migration-only path still reads it while the legacy key is set...
    assert decrypt_legacy_blob(legacy_blob) == "legacy-secret"

    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "new-credential-key")

    # ...online reads reject the raw blob (P0A: no hidden fallback)...
    import pytest

    from app.utils.credential_crypto import CredentialCryptoError

    with pytest.raises(CredentialCryptoError):
        decrypt_credential_blob(legacy_blob, PURPOSE_BROKER_CREDENTIAL)

    # ...and re-issuing it as a v2 envelope reads under the new key.
    migrated = encrypt_credential_blob("legacy-secret", PURPOSE_BROKER_CREDENTIAL)
    assert is_envelope(migrated)
    assert decrypt_credential_blob(migrated, PURPOSE_BROKER_CREDENTIAL) == "legacy-secret"
