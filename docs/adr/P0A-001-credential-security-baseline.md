# ADR-P0A-001: Production baseline security hardening

- **Status**: Implemented (P0A; G0A acceptance checklist in the delivery
  report; a few items require a real deployment for final sign-off)
- **Date**: 2026-09-03

## Context

The recorded QD baseline had four P0A/G0A blockers (development plan P0A,
D-009/D-014):

1. `docker-entrypoint.sh` generated an **in-memory** `CREDENTIAL_ENCRYPTION_KEY`
   when `.env` was not writable, while the production overlay mounts `.env`
   read-only — together these rotated the credential key on every restart,
   silently bricking all saved broker credentials and MFA secrets.
2. The default administrator password was `123456` (env.example shipped it as
   the documented default and `Config.ADMIN_PASSWORD` defaulted to it).
3. `credential_crypto.py` fell back to the JWT/session `SECRET_KEY` for
   encryption, coupling credential security to session-key rotation, and
   produced unversioned raw Fernet blobs with no purpose binding.
4. The development environment had no guard against saving real credentials
   under an ephemeral key.

## Decision

### 1. Versioned envelope with purpose binding (`app/utils/credential_crypto.py`)

- Ciphertext: `v2:<purpose>:<key-fingerprint>:<fernet-token>`.
- `purpose` is `broker-credential` or `mfa-secret`, required at both
  encrypt/decrypt — cross-purpose substitution is rejected.
- The key id in the envelope is a **content fingerprint** (`k` + 12 hex of
  SHA-256 of the key value), not an operator-chosen label. Blobs are
  self-describing: pointing the compat variable at a different key can never
  silently re-tag or mis-decrypt old data; the failure names the exact
  missing fingerprint.
- Keys: `CREDENTIAL_ENCRYPTION_KEY` (compat, active writer) and
  `CREDENTIAL_ENCRYPTION_KEYS` (`config-id:key` pairs for rotation).
  `CREDENTIAL_ENCRYPTION_ACTIVE_KEY_ID` selects the writer when the
  collection alone is configured with multiple entries. Reads resolve by
  fingerprint across the whole collection — rotation is config + one
  idempotent migration run.
- The `SECRET_KEY` fallback is **removed from all online paths**: writes fail
  without a credential key, online reads reject non-envelope blobs with
  migration guidance, and legacy decryption survives only in
  `decrypt_legacy_blob()` for the offline migration command.

### 2. Fail-closed startup guards (`app/security/bootstrap_guards.py`)

- `DEPLOYMENT_ENV=development|staging|production` (default development).
- staging/production: refuse to start without a persistent credential key
  (env or `CREDENTIAL_ENCRYPTION_KEY_FILE`), refuse the default/unset
  `ADMIN_PASSWORD`, refuse `ALLOW_INSECURE_DEV_KEY`.
- development: requires a persistent key **or** the explicit
  `ALLOW_INSECURE_DEV_KEY=true` opt-in; the insecure mode blocks every
  broker-credential / MFA write at the crypto layer (fail closed).
- Wired into `create_app` — API, trading worker, scheduler, Celery workers
  and the migration job all inherit the same guard.

### 3. Entrypoint and Compose unification

- `docker-entrypoint.sh`: no in-memory credential key in any path.
  Development generates a **persistent** key into `.env`; a read-only `.env`
  without a key exits with instructions (or runs the explicit insecure dev
  mode). staging/production additionally refuse missing `SECRET_KEY`, the
  documented default `SECRET_KEY`, and the default admin password.
- `docker-compose.production.yml`: mounts
  `./backend_api_python/secrets:/run/secrets/quantdinger:ro`, sets
  `DEPLOYMENT_ENV=production` and
  `CREDENTIAL_ENCRYPTION_KEY_FILE=/run/secrets/quantdinger/credential_key`,
  resolving the `.env:ro` vs entrypoint-write conflict by construction.
- `.gitignore` covers `backend_api_python/secrets/`.

### 4. Migration, rotation runbook, canary

- `app/commands/migrate_credentials.py`: idempotent, resumable
  (deterministic key-ordered batches), dry-run mode, append-only
  `qd_p0a_migration_log` audit (checksums, key ids, purpose — never
  plaintext), per-row fail-closed.
- `docs/deployment/CREDENTIAL_KEY_ROTATION.md`: four-phase reversible
  rotation (dual-key window → re-encrypt → canary → shrink) with rollback
  per phase.
- `scripts/decrypt_canary.py`: per-container round-trip, purpose-binding,
  envelope-shape and legacy-rejection checks (8 checks, all PASS locally).

## Consequences

- Rolling back the application version does **not** roll back the refusal
  behaviour (D-014): the guards live in the entrypoint and bootstrap path,
  and re-introducing an in-memory key would require a deliberate code change
  that G0A review would flag.
- Existing deployments upgrading to P0A run the migration command once; until
  they do, online reads of pre-P0A blobs fail loudly with instructions rather
  than silently succeeding via a hidden fallback.
- Saving the first real broker credential now requires the G0A checklist
  (persistent key + non-default admin password + canary PASS).
