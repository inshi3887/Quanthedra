# ADR-P0A-002: Repository renamed to Quanthedra

- **Status**: Accepted
- **Date**: 2026-09-04

## Context

The candidate baseline was developed as `QuantAnalyInvest` (local directory
and GitHub remote `inshi3887/QuantAnalyInvest`). The owner decided to
publish the repository under the name **Quanthedra**
(`github.com/inshi3887/Quanthedra`).

## Decision

1. The repository moved to `Quanthedra/` (same volume; git history is
   unchanged — commit `b7b2168` and its full content carry over intact).
2. The git remote is now `https://github.com/inshi3887/Quanthedra.git`.
3. **Display-layer rename only** (consistent with the baseline principle
   that product display and internal compatibility identifiers are
   separate, D-004):
   - `README.md` title, `AGENTS.md` heading, `docs/BASELINE.md` title now
     say "Quanthedra".
   - Historical audit records (P0 checklist, manifests, delivery reports,
     plan documents) keep their original wording: they are timestamped
     evidence and are not rewritten retroactively.
4. Per D-004, internal compatibility identifiers are **unchanged**:
   `backend_api_python/` paths, `qd_` table prefixes, `quantdinger-*`
   container names, Celery task names, Compose project names, and the
   `quantdinger_mcp` package stay as-is until a dedicated rename plan is
   approved. CI paths therefore keep working without modification.
5. `Upstream_SOURCES.md`, THIRD_PARTY_NOTICES and license attribution are
   untouched (they describe upstream lineage, not this repository's name).

## Consequences

- Pushing `main` to `inshi3887/Quanthedra` publishes the candidate
  baseline under the new name; the old `QuantAnalyInvest` remote remains
  unused/empty unless the owner repoints it.
- Grep for `QuantAnalyInvest` still hits historical/audit documents by
  design; new top-level user-facing surfaces use Quanthedra.
- A future internal-identifier rename (backend path, `qd_` tables,
  container names) remains out of scope and requires its own ADR and
  migration plan.
