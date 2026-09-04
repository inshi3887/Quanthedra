"""P0A / G0A production baseline security guards (D-009 / D-014).

Single source of truth for the fail-closed startup and write-time rules
that must survive any application rollback (D-014: these refusals are NOT
feature flags and cannot be rolled back as one):

- ``DEPLOYMENT_ENV`` selects the deployment profile:
  ``development`` (default) | ``staging`` | ``production``.
- staging/production refuse to start without a *persistent* credential
  encryption key (env or key file). No code path generates an in-memory
  credential key.
- staging/production refuse the default bootstrap admin password
  (``123456`` / unset).
- ``ALLOW_INSECURE_DEV_KEY=true`` is a development-only escape hatch that
  lets a keyless dev container boot for UI work. It never touches real
  credentials: every broker-credential / MFA write fails closed while it
  is active.

Every process class (API, trading worker, Celery worker/scheduler,
migration job) runs the same guard via ``enforce_startup_security``.
"""

from __future__ import annotations

import os
from typing import Optional

from app.utils.logger import get_logger
from app.utils.credential_crypto import (
    PURPOSE_BROKER_CREDENTIAL,
    PURPOSE_MFA_SECRET,
    key_collection,
)

logger = get_logger(__name__)


ENV_DEVELOPMENT = "development"
ENV_STAGING = "staging"
ENV_PRODUCTION = "production"
_KNOWN_ENVS = (ENV_DEVELOPMENT, ENV_STAGING, ENV_PRODUCTION)

_INSECURE_ADMIN_PASSWORDS = {"123456"}

SENSITIVE_CREDENTIAL_PURPOSES = (PURPOSE_BROKER_CREDENTIAL, PURPOSE_MFA_SECRET)


class SecurityBootstrapError(RuntimeError):
    """The process must not start; the deployment fails a P0A/G0A rule."""


class InsecureKeyWriteBlocked(PermissionError):
    """A sensitive credential write was refused because the process runs
    with the development-only insecure key."""


def deployment_env() -> str:
    raw = (os.getenv("DEPLOYMENT_ENV") or "").strip().lower()
    if not raw:
        return ENV_DEVELOPMENT
    if raw not in _KNOWN_ENVS:
        raise SecurityBootstrapError(
            f"DEPLOYMENT_ENV={raw!r} is invalid; expected one of {', '.join(_KNOWN_ENVS)}"
        )
    return raw


def resolve_persistent_credential_key() -> str:
    """Return the persistent credential key, or "" when none is configured.

    Sources, in order:
      1. ``CREDENTIAL_ENCRYPTION_KEY`` env (the entrypoint keeps this in
         sync with the .env file value).
      2. ``CREDENTIAL_ENCRYPTION_KEY_FILE`` — path to a mounted secret
         file (Docker secret / bind mount); trailing newline stripped.

    Never generates a key.
    """
    key = (os.getenv("CREDENTIAL_ENCRYPTION_KEY") or "").strip()
    if key:
        return key
    key_file = (os.getenv("CREDENTIAL_ENCRYPTION_KEY_FILE") or "").strip()
    if key_file:
        try:
            with open(key_file, "r", encoding="utf-8") as fh:
                return fh.read().strip()
        except OSError as exc:
            raise SecurityBootstrapError(
                f"CREDENTIAL_ENCRYPTION_KEY_FILE={key_file!r} cannot be read: {exc}"
            ) from exc
    return ""


def allow_insecure_dev_key_requested() -> bool:
    return (os.getenv("ALLOW_INSECURE_DEV_KEY") or "").strip().lower() in ("1", "true", "yes")


def insecure_dev_key_active() -> bool:
    """True only in development, only when explicitly requested, and only
    when no persistent key exists. While active, sensitive credential
    writes are refused (see :func:`ensure_credential_write_allowed`)."""
    if deployment_env() != ENV_DEVELOPMENT:
        return False
    if not allow_insecure_dev_key_requested():
        return False
    return not resolve_persistent_credential_key()


def _admin_password_is_default() -> bool:
    password = (os.getenv("ADMIN_PASSWORD") or "").strip()
    if not password:
        return True
    return password in _INSECURE_ADMIN_PASSWORDS


def enforce_startup_security() -> None:
    """Fail closed for P0A/G0A violations. Called by every process class
    before serving traffic or consuming jobs."""
    env = deployment_env()

    # -- credential encryption key --------------------------------------
    key = resolve_persistent_credential_key()
    if not key:
        if env in (ENV_STAGING, ENV_PRODUCTION):
            raise SecurityBootstrapError(
                "CREDENTIAL_ENCRYPTION_KEY is not configured. Staging and "
                "production refuse to start without a persistent key because "
                "an ephemeral key makes every saved broker credential and MFA "
                "secret unreadable after restart. Generate one with: "
                'python3 -c "import secrets; print(secrets.token_hex(32))" '
                "and set it via .env or CREDENTIAL_ENCRYPTION_KEY_FILE."
            )
        # Development without a key and without the explicit opt-in also
        # refuses; the pre-P0A auto-generation hid credential loss.
        if not allow_insecure_dev_key_requested():
            raise SecurityBootstrapError(
                "CREDENTIAL_ENCRYPTION_KEY is not configured. Set a persistent "
                "key in .env, or run development explicitly with "
                "ALLOW_INSECURE_DEV_KEY=true (insecure key mode blocks saving "
                "broker credentials and MFA secrets)."
            )
        logger.warning(
            "[P0A] Running with the development-only insecure credential key: "
            "saving broker credentials and MFA secrets is BLOCKED until a "
            "persistent CREDENTIAL_ENCRYPTION_KEY is configured."
        )

    # -- bootstrap admin password ----------------------------------------
    if env in (ENV_STAGING, ENV_PRODUCTION) and _admin_password_is_default():
        raise SecurityBootstrapError(
            "ADMIN_PASSWORD is unset or still the bootstrap default. "
            "Staging and production refuse to start with a known default "
            "administrator password. Set a strong ADMIN_PASSWORD in .env."
        )

    # -- insecure key outside development ---------------------------------
    if allow_insecure_dev_key_requested() and env != ENV_DEVELOPMENT:
        raise SecurityBootstrapError(
            "ALLOW_INSECURE_DEV_KEY=true is only valid with "
            "DEPLOYMENT_ENV=development."
        )


def ensure_credential_write_allowed(purpose: str) -> None:
    """Write-time guard for credential-encrypting services.

    Fail closed when the process runs with the development-only insecure
    key and the write targets a sensitive credential class. Non-sensitive
    development data (test fixtures, plaintext dev settings) is allowed.
    """
    if purpose not in SENSITIVE_CREDENTIAL_PURPOSES:
        return
    if insecure_dev_key_active():
        raise InsecureKeyWriteBlocked(
            f"Refusing to persist a {purpose} while the development-only "
            "insecure credential key is active. Configure a persistent "
            "CREDENTIAL_ENCRYPTION_KEY first (D-009 / G0A)."
        )


def credential_inventory_report() -> dict:
    """Small diagnostic for startup logs / canary scripts. Never contains
    key material — only ids and presence flags."""
    collection = key_collection()
    return {
        "deployment_env": deployment_env(),
        "persistent_key_configured": bool(resolve_persistent_credential_key()),
        "key_ids": sorted(collection.keys()),
        "insecure_dev_key_active": insecure_dev_key_active(),
    }
