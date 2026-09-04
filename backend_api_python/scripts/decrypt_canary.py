"""P0A cross-container decrypt canary (run inside each service container).

Per the P0A acceptance: after any key rotation, every process class that
touches credential material must prove it can decrypt with the *currently
configured* key collection.

For each purpose (broker-credential / mfa-secret) the canary:
  1. encrypts a fresh canary plaintext with the active key;
  2. decrypts it back and verifies the round-trip;
  3. verifies the purpose binding is enforced (decrypting under the wrong
     purpose must fail);
  4. verifies a legacy-shaped blob is NOT accepted by the online path.

No database, no network, no persisted state; prints PASS/FAIL per check
and exits non-zero on the first failure. The plaintext never contains real
credential material and is never logged.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    from app.utils.credential_crypto import (
        CredentialCryptoError,
        PURPOSE_BROKER_CREDENTIAL,
        PURPOSE_MFA_SECRET,
        active_key,
        decrypt_credential_blob,
        encrypt_credential_blob,
        is_envelope,
    )
    from app.security.bootstrap_guards import credential_inventory_report

    inventory = credential_inventory_report()
    print(f"[canary] inventory: {inventory}")
    if not inventory["persistent_key_configured"]:
        print("[canary] FAIL: no persistent credential key configured")
        return 1
    key_id, _ = active_key()
    print(f"[canary] active key-id: {key_id}")

    failures = 0

    def check(name: str, fn) -> None:
        nonlocal failures
        try:
            fn()
            print(f"[canary] PASS {name}")
        except Exception as exc:  # noqa: BLE001 — canary reports everything
            failures += 1
            print(f"[canary] FAIL {name}: {type(exc).__name__}: {exc}")

    for purpose, marker in (
        (PURPOSE_BROKER_CREDENTIAL, '{"canary":"broker"}'),
        (PURPOSE_MFA_SECRET, '{"canary":"mfa"}'),
    ):
        blob = encrypt_credential_blob(marker, purpose)

        def _roundtrip(blob=blob, purpose=purpose, marker=marker):
            assert decrypt_credential_blob(blob, purpose) == marker

        def _wrong_purpose(blob=blob, purpose=purpose):
            other = PURPOSE_MFA_SECRET if purpose == PURPOSE_BROKER_CREDENTIAL else PURPOSE_BROKER_CREDENTIAL
            try:
                decrypt_credential_blob(blob, other)
            except CredentialCryptoError:
                return
            raise AssertionError("cross-purpose decrypt unexpectedly succeeded")

        def _envelope_shape(blob=blob):
            assert is_envelope(blob) and blob.split(":")[2] == key_id

        check(f"roundtrip[{purpose}]", _roundtrip)
        check(f"purpose-binding[{purpose}]", _wrong_purpose)
        check(f"envelope-shape[{purpose}]", _envelope_shape)

    def _legacy_rejected():
        # A legacy raw-Fernet token must NOT pass the online read path.
        from cryptography.fernet import Fernet
        import base64, hashlib, os

        key = os.getenv("CREDENTIAL_ENCRYPTION_KEY") or ""
        assert key, "canary requires CREDENTIAL_ENCRYPTION_KEY to fabricate a legacy blob"
        fkey = base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest())
        legacy = Fernet(fkey).encrypt(b'{"legacy":true}').decode()
        try:
            decrypt_credential_blob(legacy, PURPOSE_BROKER_CREDENTIAL)
        except CredentialCryptoError:
            return
        raise AssertionError("legacy blob accepted by online decrypt path")

    check("legacy-not-accepted-online", _legacy_rejected)

    if failures:
        print(f"[canary] RESULT: FAIL ({failures} check(s) failed)")
        return 1
    print("[canary] RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
