# QuantAnalyInvest Baseline

> Created by P0 on 2026-08-18. This file is the single source of truth for the
> controlled repository baseline.

## Recorded upstream commits

| Upstream | Commit | Verified HEAD at P0 | Worktree |
| --- | --- | --- | --- |
| QuantDinger | `e64e1c227bf3174e441a42143620179b286387e1` (short `e64e1c2`) | same | Windows mode-only dirty (see `DIRTY_MANIFEST_QUANTDINGER.md`) |
| daily_stock_analysis | `396d43a4c76ffa940e2b9aea7bbe8686343c694a` (short `396d43a4`) | same | dirty; `CLAUDE.md` content indeterminate (see `DIRTY_MANIFEST_DSA.md`) |

## Archive semantics (strict)

- **QuantDinger `e64e1c2`**: exported with `git archive` and extracted into
  this repository root. It **is** the baseline tree, including
  `backend_api_python/`, `.github/`, root `scripts/`, `docs/`, `ops/`,
  `mcp_server/`, all `docker-compose*.yml`, install scripts, root `VERSION`,
  security and OpenAPI configuration.
- **daily_stock_analysis `396d43a4`**: used **only** to build the fixed legacy
  service image (P4). It is **not** archived into this repository. DSA
  functional code migrates module-by-module in P5-P8, with every import
  recorded in `../UPSTREAM_SOURCES.md`.

`git archive <commit>` contains only committed content; uncommitted upstream
changes are never silently included. Dirty manifests are recorded for
traceability, not merged.

## Drift policy

Before any later Plan starts, re-verify each upstream HEAD against this file:

- If HEAD matches the recorded commit → proceed.
- If HEAD has drifted → stop, update this file with the new commit and the
  reason, and get explicit approval before using the new HEAD.

## Environment

- Python: 3.11.6 (runtime target documented as 3.12; current sandbox has
  3.11.6 — recorded, not silently changed)
- Docker: 26.1.3; Docker Compose v2.27.0
- See `P0_ENVIRONMENT.md` for the full snapshot.

## Test entry points

From repository root:

```bash
cd backend_api_python
python -m pytest -m "not integration and not stress" --ignore=tests/release_gate -q
ruff check app scripts tests
cd ..
python scripts/check_version.py
python scripts/check_mojibake.py
docker compose -f docker-compose.yml config -q
docker compose -f docker-compose.yml -f docker-compose.production.yml -f docker-compose.observability.yml config -q
```

Release-gate and integration suites live under
`backend_api_python/tests/release_gate/` and marker-filtered sets; they are
run when the corresponding Plan requires them.
