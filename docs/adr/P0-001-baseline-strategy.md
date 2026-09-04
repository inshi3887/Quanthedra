# ADR-P0-001: Baseline strategy for QuantAnalyInvest

- **Status**: Pending approval (P0; awaiting human review before Git commit)
- **Date**: 2026-08-18

## Context

QuantAnalyInvest merges QuantDinger (trading base) and daily_stock_analysis
(research source). The development plan (8th edition, P0) requires a
reproducible baseline that does not change QD behavior and does not silently
absorb uncommitted upstream work.

## Decision

1. Initialize a fresh Git repository (`main`), importing **no** upstream
   history (D-002).
2. Baseline = `git archive e64e1c2` of QuantDinger extracted to the repository
   root (D-001, D-004): the full tree including CI, Compose, ops and MCP.
3. daily_stock_analysis is **not** archived into the repository. Commit
   `396d43a4` is recorded for the future fixed legacy image (P4) and for
   module-by-module migration in P5-P8 (D-005).
4. Dirty manifests are recorded for both upstream repositories. They are
   traceability artifacts only; uncommitted changes are never merged
   silently, and any intentional local change needs a separate patch + hash +
   human approval record.
5. Root-level governance files are added without altering QD behavior:
   `AGENTS.md`, `THIRD_PARTY_NOTICES.md`, prefixed `README.md`, merged
   `.gitignore`.
6. No renames of `backend_api_python`, `qd_` tables, Celery task names,
   container names or compatibility environment variables.
7. Synchronize the committed OpenAPI artifact with the routes already present
   in the recorded QD baseline. The generated contract adds only
   `/api/indicator/chart-preview`, `/api/strategies/position-ownership`, and
   `/api/strategies/position-ownership/repair`; no runtime route is added or
   removed by P0. This governed P0 correction keeps the existing OpenAPI CI
   exact-diff gate enabled instead of weakening or bypassing it.

## Consequences

- CI paths referencing `backend_api_python/` keep working unchanged.
- License attribution is explicit: Apache-2.0 (QD), MIT (DSA), Apache-2.0
  derived DSA screening notices.
- Future Plans have a single, verifiable baseline anchor
  (`docs/BASELINE.md`) and a mandatory import log (`UPSTREAM_SOURCES.md`).
