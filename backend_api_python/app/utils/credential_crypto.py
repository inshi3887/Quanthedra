"""Versioned envelope encryption for persisted credentials and MFA secrets.

P0A (D-009 / D-014 / ADR-P0A-001) contract:

- Ciphertext format: ``v2:<purpose>:<key-fingerprint>:<ciphertext>`` where
  ``<purpose>`` is ``broker-credential`` or ``mfa-secret`` (purpose
  isolation: an MFA secret can never be substituted for a broker
  credential or vice versa) and ``<key-fingerprint>`` identifies the exact
  key value that encrypted the blob (``k`` + first 12 hex of SHA-256 of
  the key). Content-derived ids make blobs self-describing: pointing the
  compat variable at a different key can never silently re-tag old data.
- ``CREDENTIAL_ENCRYPTION_KEYS`` holds ``config-id:key`` pairs
  (comma-separated; the config id is operator documentation only).
  ``CREDENTIAL_ENCRYPTION_KEY`` remains supported as the *active* writer
  key so existing deployments keep working; both sources feed the same
  fingerprint-addressed collection.
- Writes always use the active key. Reads resolve by fingerprint, so
  rotation (add-new-key -> re-encrypt -> retire-old-key) is a config
  change plus one idempotent migration run.
- Legacy raw-Fernet blobs (pre-P0A, encrypted with
  ``CREDENTIAL_ENCRYPTION_KEY`` or — historical fallback — ``SECRET_KEY``)
  stay decryptable ONLY through :func:`decrypt_legacy_blob`, which exists
  for the offline migration command. Online read/write paths never
  produce or transparently accept legacy blobs without an explicit
  opt-in, and no write path ever falls back to ``SECRET_KEY``.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
from typing import Dict, Optional, Tuple

from cryptography.fernet import Fernet, InvalidToken


ENVELOPE_VERSION = "v2"

PURPOSE_BROKER_CREDENTIAL = "broker-credential"
PURPOSE_MFA_SECRET = "mfa-secret"
KNOWN_PURPOSES = (PURPOSE_BROKER_CREDENTIAL, PURPOSE_MFA_SECRET)

class CredentialCryptoError(ValueError):
    """Raised for envelope format, purpose or key-resolution problems."""


# ---------------------------------------------------------------------------
# Key collection
# ---------------------------------------------------------------------------


def _parse_key_collection(raw: str) -> Dict[str, str]:
    """Parse ``key-id:key`` pairs (comma separated). Empty fragments and
    malformed entries are skipped so a trailing comma does not brick reads."""
    out: Dict[str, str] = {}
    for fragment in raw.split(","):
        fragment = fragment.strip()
        if not fragment:
            continue
        if ":" not in fragment:
            continue
        key_id, key = fragment.split(":", 1)
        key_id = key_id.strip()
        key = key.strip()
        if key_id and key:
            out[key_id] = key
    return out


def key_fingerprint(secret: str) -> str:
    """Stable, content-derived envelope key-id.

    The envelope stores this fingerprint, NOT the operator-chosen config
    id, so a blob always names the exact key value that encrypted it.
    Replacing ``CREDENTIAL_ENCRYPTION_KEY`` without migrating therefore
    produces a precise "key not configured" error instead of silently
    decrypting-with-the-wrong-key or tagging old blobs with a reused id.
    (12 hex chars of SHA-256 — non-reversible, collision-impractical at
    this width for a bounded key set.)
    """
    return "k" + hashlib.sha256(secret.encode("utf-8")).hexdigest()[:12]


def key_collection() -> Dict[str, str]:
    """All configured decryption secrets, keyed by content fingerprint.

    Sources, merged (duplicates by value collapse naturally):
      1. ``CREDENTIAL_ENCRYPTION_KEYS`` — versioned collection
         (``config-id:key`` pairs; the config id is documentation only).
      2. ``CREDENTIAL_ENCRYPTION_KEY`` — compatibility active key.
    """
    raw = _parse_key_collection(os.getenv("CREDENTIAL_ENCRYPTION_KEYS", ""))
    collection = {key_fingerprint(secret): secret for secret in raw.values()}
    compat = (os.getenv("CREDENTIAL_ENCRYPTION_KEY") or "").strip()
    if compat:
        collection[key_fingerprint(compat)] = compat
    return collection


def active_key() -> Tuple[str, str]:
    """The (fingerprint, secret) every new encryption must use.

    Selection order:
      1. ``CREDENTIAL_ENCRYPTION_ACTIVE_KEY_ID`` naming a config id from
         ``CREDENTIAL_ENCRYPTION_KEYS`` (rotation: point it at the new key).
      2. ``CREDENTIAL_ENCRYPTION_KEY`` (compat single-variable path).
      3. The single entry of ``CREDENTIAL_ENCRYPTION_KEYS`` when exactly
         one is configured.
    """
    explicit = (os.getenv("CREDENTIAL_ENCRYPTION_ACTIVE_KEY_ID") or "").strip()
    raw = _parse_key_collection(os.getenv("CREDENTIAL_ENCRYPTION_KEYS", ""))
    if explicit:
        if explicit not in raw:
            raise CredentialCryptoError(
                f"CREDENTIAL_ENCRYPTION_ACTIVE_KEY_ID={explicit!r} is not a "
                "config id in CREDENTIAL_ENCRYPTION_KEYS"
            )
        secret = raw[explicit]
        return key_fingerprint(secret), secret
    compat = (os.getenv("CREDENTIAL_ENCRYPTION_KEY") or "").strip()
    if compat:
        return key_fingerprint(compat), compat
    if len(raw) == 1:
        secret = next(iter(raw.values()))
        return key_fingerprint(secret), secret
    if raw:
        raise CredentialCryptoError(
            "CREDENTIAL_ENCRYPTION_ACTIVE_KEY_ID must name the active config "
            "id when CREDENTIAL_ENCRYPTION_KEYS holds multiple keys and "
            "CREDENTIAL_ENCRYPTION_KEY is unset"
        )
    raise CredentialCryptoError(
        "No credential encryption key configured. Set CREDENTIAL_ENCRYPTION_KEY "
        "(or the versioned CREDENTIAL_ENCRYPTION_KEYS collection)."
    )


def _fernet(secret: str) -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


# ---------------------------------------------------------------------------
# v2 envelope
# ---------------------------------------------------------------------------


def encrypt_credential_blob(plaintext_json: str, purpose: str) -> str:
    """Encrypt JSON text into a ``v2`` envelope for storage.

    ``purpose`` binds the ciphertext to one credential class; decryption
    verifies it, preventing cross-purpose substitution. Required (no
    default) so every caller declares what it stores: exchange/broker
    credentials pass ``PURPOSE_BROKER_CREDENTIAL``, MFA code passes
    ``PURPOSE_MFA_SECRET``.
    """
    if purpose not in KNOWN_PURPOSES:
        raise CredentialCryptoError(f"Unknown credential purpose: {purpose!r}")
    if plaintext_json is None:
        plaintext_json = ""
    # P0A write-time guard: the development-only insecure key must never
    # persist real credentials (D-009). No-op whenever a persistent key or
    # a non-development environment is in effect.
    from app.security.bootstrap_guards import ensure_credential_write_allowed

    ensure_credential_write_allowed(purpose)
    key_id, key = active_key()
    token = _fernet(key).encrypt(plaintext_json.encode("utf-8")).decode("ascii")
    return f"{ENVELOPE_VERSION}:{purpose}:{key_id}:{token}"


def decrypt_credential_blob(stored: object, purpose: str) -> str:
    """Decrypt a stored value to JSON text. Empty / None yields empty string.

    Accepts v2 envelopes (verified against ``purpose`` and decrypted with
    the matching key from the collection). Legacy raw-Fernet blobs are NOT
    accepted here anymore: run the P0A migration command to convert them
    (they remain readable via :func:`decrypt_legacy_blob`).
    """
    if stored is None:
        return ""
    s = stored.decode("utf-8") if isinstance(stored, (bytes, bytearray)) else str(stored)
    s = s.strip()
    if not s:
        return ""

    parsed = _parse_envelope(s)
    if parsed is None:
        # Legacy blob in an online read path. Fail loudly with migration
        # guidance instead of silently accepting key-fallback behaviour.
        raise CredentialCryptoError(
            "Credential blob is not a v2 envelope. Run the credential "
            "re-encryption migration (python -m app.commands.migrate_credentials) "
            "to convert legacy ciphertexts."
        )
    version, blob_purpose, key_id, token = parsed
    if version != ENVELOPE_VERSION:
        raise CredentialCryptoError(f"Unsupported envelope version: {version!r}")
    if blob_purpose != purpose:
        raise CredentialCryptoError(
            f"Envelope purpose mismatch: stored {blob_purpose!r}, requested {purpose!r}"
        )
    collection = key_collection()
    key = collection.get(key_id)
    if key is None:
        raise CredentialCryptoError(
            f"Envelope was encrypted with key fingerprint {key_id!r}, which is "
            "not among the configured keys (CREDENTIAL_ENCRYPTION_KEYS / "
            "CREDENTIAL_ENCRYPTION_KEY). Restore the original key value to the "
            "collection, or re-encrypt via the migration command."
        )
    try:
        return _fernet(key).decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise CredentialCryptoError(
            f"Cannot decrypt credential blob with key {key_id!r} "
            "(wrong key or corrupted ciphertext)"
        ) from exc


def _parse_envelope(s: str) -> Optional[Tuple[str, str, str, str]]:
    """Split ``v2:<purpose>:<key-id>:<token>``; None when not an envelope."""
    parts = s.split(":", 3)
    if len(parts) != 4 or parts[0] != ENVELOPE_VERSION:
        return None
    version, purpose, key_id, token = parts
    if not purpose or not key_id or not token:
        return None
    return version, purpose, key_id, token


def is_envelope(stored: object) -> bool:
    """True when the value is a v2 envelope (used by the migration command
    to skip already-migrated rows idempotently)."""
    if stored is None:
        return False
    s = stored.decode("utf-8") if isinstance(stored, (bytes, bytearray)) else str(stored)
    return _parse_envelope(s.strip()) is not None


# ---------------------------------------------------------------------------
# Legacy decryption (migration command only — never used by write paths)
# ---------------------------------------------------------------------------


def decrypt_legacy_blob(stored: object) -> str:
    """Decrypt a pre-P0A raw-Fernet blob.

    Tries ``CREDENTIAL_ENCRYPTION_KEY`` first, then ``SECRET_KEY`` — the
    historical fallback order. Exclusively for the offline migration
    command; online code paths must not call this.
    """
    if stored is None:
        return ""
    s = stored.decode("utf-8") if isinstance(stored, (bytes, bytearray)) else str(stored)
    s = s.strip()
    if not s:
        return ""
    if is_envelope(s):
        raise CredentialCryptoError("Value is already a v2 envelope; use decrypt_credential_blob")

    candidates = []
    for env in ("CREDENTIAL_ENCRYPTION_KEY", "SECRET_KEY"):
        secret = (os.getenv(env) or "").strip()
        if secret and secret not in candidates:
            candidates.append(secret)
    if not candidates:
        raise CredentialCryptoError(
            "No legacy key configured (CREDENTIAL_ENCRYPTION_KEY / SECRET_KEY) "
            "to decrypt legacy credential blobs"
        )
    for secret in candidates:
        try:
            return _fernet(secret).decrypt(s.encode("ascii")).decode("utf-8")
        except (InvalidToken, binascii.Error):
            continue
    raise CredentialCryptoError("Cannot decrypt legacy credential blob with any configured legacy key")
