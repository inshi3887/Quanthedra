#!/bin/sh
# QuantDinger Docker Entrypoint Script
# Checks and validates SECRET_KEY before starting the application

set -e

# P0A deployment profile: development (default) | staging | production.
DEPLOYMENT_ENV=$(printf '%s' "${DEPLOYMENT_ENV:-development}" | tr '[:upper:]' '[:lower:]')

echo "============================================"
echo "  QuantDinger Backend - Starting..."
echo "============================================"

# Check if .env file exists
if [ ! -f /app/.env ]; then
    echo "[WARNING] .env file not found at /app/.env"
    echo "Creating .env from env.example..."
    if [ -f /app/env.example ]; then
        if cp /app/env.example /app/.env 2>/tmp/quantdinger-env-copy.err; then
            echo "[INFO] Created .env from env.example"
            echo "[IMPORTANT] Please edit /app/.env and set a secure SECRET_KEY before restarting!"
        else
            echo "[WARNING] Cannot create /app/.env: $(cat /tmp/quantdinger-env-copy.err)"
            echo "[WARNING] Continuing with container environment variables only."
            echo "[TIP] Create the host env file before starting Docker:"
            echo "      cp backend_api_python/env.example backend_api_python/.env"
            rm -f /tmp/quantdinger-env-copy.err
        fi
    else
        echo "[WARNING] env.example not found. Continuing with container environment variables only."
    fi
fi

# Check SECRET_KEY configuration
DEFAULT_SECRET="quantdinger-secret-key-change-me"
CURRENT_SECRET=$(grep -E "^SECRET_KEY=" /app/.env 2>/dev/null | cut -d'=' -f2- | tr -d '"' | tr -d "'" | xargs || true)
CURRENT_SECRET=${CURRENT_SECRET:-${SECRET_KEY:-}}

if [ -z "$CURRENT_SECRET" ]; then
    if [ "$DEPLOYMENT_ENV" = "production" ] || [ "$DEPLOYMENT_ENV" = "staging" ]; then
        echo "[ERROR] SECRET_KEY is not configured; $DEPLOYMENT_ENV refuses to start (P0A/G0A)."
        echo "        Generate one with: python3 -c \"import secrets; print(secrets.token_hex(32))\" and set it in .env."
        exit 1
    fi
    NEW_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    if [ -f /app/.env ] && [ -w /app/.env ]; then
        echo "SECRET_KEY=${NEW_SECRET}" >> /app/.env
        echo "[AUTO] Generated random SECRET_KEY (was missing)."
    else
        export SECRET_KEY="$NEW_SECRET"
        echo "[AUTO] Generated random in-memory SECRET_KEY (no writable .env)."
        echo "[TIP]  Set a persistent SECRET_KEY in backend_api_python/.env for production."
    fi
    CURRENT_SECRET="$NEW_SECRET"
fi

# Auto-generate SECRET_KEY if using default (zero-config experience)
if [ "$CURRENT_SECRET" = "$DEFAULT_SECRET" ]; then
    if [ "$DEPLOYMENT_ENV" = "production" ] || [ "$DEPLOYMENT_ENV" = "staging" ]; then
        echo "[ERROR] SECRET_KEY is still the documented default; $DEPLOYMENT_ENV refuses to start (P0A/G0A)."
        echo "        Generate one with: python3 -c \"import secrets; print(secrets.token_hex(32))\" and set it in .env."
        exit 1
    fi
    NEW_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    # Use a temp file + write-back instead of `sed -i`. When /app/.env is a
    # Docker bind-mount from the host (zero-repo GHCR deploy), `sed -i` fails
    # with "Device or resource busy" because it tries to rename(2) the inode
    # over a mount target. Truncate+write through the mount works fine and
    # propagates the new key back to the host file.
    if [ -f /app/.env ] && [ -w /app/.env ]; then
        TMP=$(mktemp)
        sed "s|SECRET_KEY=.*|SECRET_KEY=${NEW_SECRET}|" /app/.env > "$TMP"
        cat "$TMP" > /app/.env
        rm -f "$TMP"
        echo "[AUTO] Generated random SECRET_KEY (was default)."
        echo "[TIP]  For production, set a persistent SECRET_KEY in backend_api_python/.env"
    else
        export SECRET_KEY="$NEW_SECRET"
        echo "[AUTO] Generated random in-memory SECRET_KEY (default value, no writable .env)."
        echo "[TIP]  Set a persistent SECRET_KEY in backend_api_python/.env for production."
    fi
    CURRENT_SECRET="$NEW_SECRET"
fi

# Make the validated file-derived value authoritative for every child command,
# including workers/health checks that do not load python-dotenv themselves.
export SECRET_KEY="$CURRENT_SECRET"

SECRET_LEN=$(printf '%s' "$CURRENT_SECRET" | wc -c | tr -d ' ')
if [ "$SECRET_LEN" -lt 10 ]; then
    echo "[ERROR] SECRET_KEY is only ${SECRET_LEN} bytes; at least 10 bytes are required."
    echo "        Generate one with: python3 -c \"import secrets; print(secrets.token_hex(32))\""
    echo "        Update .env and restart the stack; users must sign in again."
    exit 1
fi
if [ "$SECRET_LEN" -lt 32 ]; then
    echo "[WARNING] SECRET_KEY is ${SECRET_LEN} bytes; legacy-compatible but 32+ random bytes are recommended."
fi
echo "[OK] SECRET_KEY is configured"

# P0A: staging/production refuse the bootstrap default administrator password.
if [ "$DEPLOYMENT_ENV" = "production" ] || [ "$DEPLOYMENT_ENV" = "staging" ]; then
    ENV_ADMIN_PASSWORD=$(grep -E "^ADMIN_PASSWORD=" /app/.env 2>/dev/null | cut -d'=' -f2- | tr -d '"' | tr -d "'" | xargs || true)
    ENV_ADMIN_PASSWORD=${ENV_ADMIN_PASSWORD:-${ADMIN_PASSWORD:-}}
    if [ -z "$ENV_ADMIN_PASSWORD" ] || [ "$ENV_ADMIN_PASSWORD" = "123456" ]; then
        echo "[ERROR] ADMIN_PASSWORD is unset or the bootstrap default; $DEPLOYMENT_ENV refuses to start (P0A/G0A)."
        echo "        Set a strong ADMIN_PASSWORD in .env before deploying."
        exit 1
    fi
    echo "[OK] ADMIN_PASSWORD is not the bootstrap default"
fi
echo ""

# Keep credential encryption independent from JWT/session key rotation.
# P0A (D-009/D-014): the credential key is ALWAYS persistent or the process
# refuses to start. No in-memory credential key is ever generated — an
# ephemeral key silently bricks every saved broker credential after restart.
# (DEPLOYMENT_ENV was normalized at the top of this script.)

# Optional secret-file injection (Docker secret / ro bind mount). The file
# wins only when the env var itself is absent.
if [ -z "${CREDENTIAL_ENCRYPTION_KEY:-}" ] && [ -n "${CREDENTIAL_ENCRYPTION_KEY_FILE:-}" ] && [ -r "$CREDENTIAL_ENCRYPTION_KEY_FILE" ]; then
    CREDENTIAL_ENCRYPTION_KEY=$(tr -d '\r\n' < "$CREDENTIAL_ENCRYPTION_KEY_FILE")
    export CREDENTIAL_ENCRYPTION_KEY
    echo "[OK] CREDENTIAL_ENCRYPTION_KEY loaded from $CREDENTIAL_ENCRYPTION_KEY_FILE"
fi

CURRENT_CREDENTIAL_KEY=$(grep -E "^CREDENTIAL_ENCRYPTION_KEY=" /app/.env 2>/dev/null | cut -d'=' -f2- | tr -d '"' | tr -d "'" | xargs || true)
CURRENT_CREDENTIAL_KEY=${CURRENT_CREDENTIAL_KEY:-${CREDENTIAL_ENCRYPTION_KEY:-}}
if [ -z "$CURRENT_CREDENTIAL_KEY" ]; then
    if [ "$DEPLOYMENT_ENV" = "production" ] || [ "$DEPLOYMENT_ENV" = "staging" ]; then
        echo "[ERROR] CREDENTIAL_ENCRYPTION_KEY is not configured; $DEPLOYMENT_ENV refuses to start (P0A/G0A)."
        echo "        An ephemeral key would make every saved broker credential and MFA secret unreadable after restart."
        echo "        Generate one with: python3 -c \"import secrets; print(secrets.token_hex(32))\""
        echo "        Provide it via .env or CREDENTIAL_ENCRYPTION_KEY_FILE (Docker secret / ro mount)."
        exit 1
    fi
    # Development: generating a PERSISTENT key keeps the zero-config UX
    # without the data-loss hazard; the in-memory fallback is gone.
    NEW_CREDENTIAL_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    if [ -f /app/.env ] && [ -w /app/.env ]; then
        echo "CREDENTIAL_ENCRYPTION_KEY=${NEW_CREDENTIAL_KEY}" >> /app/.env
        echo "[AUTO] Generated persistent CREDENTIAL_ENCRYPTION_KEY (development)."
    else
        echo "[ERROR] No CREDENTIAL_ENCRYPTION_KEY and no writable /app/.env."
        echo "        Set ALLOW_INSECURE_DEV_KEY=true to run development WITHOUT the ability"
        echo "        to save broker credentials or MFA secrets (P0A insecure-key mode), or"
        echo "        mount a writable .env so a persistent key can be generated."
        export ALLOW_INSECURE_DEV_BLOCKED=1
        # Keep the process alive only for explicit insecure dev usage; the
        # application guard enforces the same rule independently.
        if [ "${ALLOW_INSECURE_DEV_KEY:-}" != "true" ]; then
            exit 1
        fi
    fi
fi

# Prometheus client multiprocess files must start clean for each API container.
if [ -n "${PROMETHEUS_MULTIPROC_DIR:-}" ]; then
    mkdir -p "$PROMETHEUS_MULTIPROC_DIR"
    rm -f "$PROMETHEUS_MULTIPROC_DIR"/*.db
    chown -R quantdinger:quantdinger "$PROMETHEUS_MULTIPROC_DIR" 2>/dev/null || true
fi

# Runtime processes do not need root privileges. The entrypoint keeps root only
# long enough to initialize bind-mounted secrets and volume ownership.
if [ "$(id -u)" = "0" ] && id quantdinger >/dev/null 2>&1; then
    chown -R quantdinger:quantdinger /app/logs /app/data 2>/dev/null || true
    if [ -f /app/.env ]; then
        if chown quantdinger:quantdinger /app/.env 2>/dev/null; then
            chmod 600 /app/.env 2>/dev/null || \
                echo "[WARNING] Could not restrict /app/.env permissions to mode 600."
        else
            echo "[WARNING] Could not grant the runtime user ownership of /app/.env."
            echo "[TIP] System settings will be read-only until /app/.env is writable by UID 10001."
        fi
    fi
    exec gosu quantdinger "$@"
fi

exec "$@"
