# Quanthedra Agent Rules

## Repository positioning

Quanthedra (formerly QuantAnalyInvest) is the unified repository for merging:

- **QuantDinger (QD)** — runtime, account, strategy, risk-control, order,
  deployment and permission base. The full QD tree is this repository's
  baseline.
- **daily_stock_analysis (DSA)** — multi-market research capability source.
  DSA is **not** imported as a source tree; its modules migrate Plan-by-Plan
  and every import must be recorded in `UPSTREAM_SOURCES.md`.

## Mandatory reading before any change

1. `DEVELOPMENT_PLAN第八版.md` — the current development plan.
2. `P14_SAFE_PROFILE.md` — mandatory trading-safety profile; overrides the
   development plan on trading-safety conflicts.
3. `../MERGE_DESIGN.md` — upstream architecture contract.
4. `../quant.md` — original project analysis and known risks.
5. This file and `CLAUDE_DEVELOPMENT_PROMPT.md`.

## Conflict priority

User's current explicit instruction
> `P14_SAFE_PROFILE.md`
> `DEVELOPMENT_PLAN第八版.md`
> `../MERGE_DESIGN.md`
> existing code behavior

`P14_SAFE_PROFILE.md` only overrides trading-safety conflicts; other domains
follow the development plan.

## Non-negotiable rules

1. **One Plan at a time.** Do not implement code belonging to later Plans.
   Verify the current Plan's prerequisites and Gate before writing.
2. **Never import upstream Git history.** Only `git archive <recorded-commit>`
   content is a controlled baseline.
3. **Never modify or clean the user's uncommitted changes** in upstream
   repositories; record dirty manifests only.
4. **Trading paths are fail-closed.** Unknown market/account/strategy/price/
   exposure/identity → reject.
5. `user_id` only comes from the authentication context, never client input.
6. Decimal/NUMERIC for all money, price, quantity and fee domain values.
7. LLM output is untrusted research content only — never trusted order
   parameters, never direct order placement.
8. First-phase live is USStock only; CN/HK/JP/KR/TW are research and paper.
9. Keep `RESEARCH_US_LIVE_BRIDGE_ENABLED=false` until G5 is approved.
10. No cross-tenant sharing of a real broker account in the first phase.
11. Tests must not mock away multi-tenancy, idempotency, reservation, state
    machines or order gates; critical paths need PostgreSQL integration tests.
12. Database changes are forward-compatible migrations only; never edit
    published SQL.
13. Every feature flag needs a default, owner, removal condition and coverage
    test.
14. No `git commit`, push, real funds or real broker credentials unless the
    user explicitly requests it.

## Standard checks

Run from the repository root (see `P14_SAFE_PROFILE.md` §11.6 for full
detail):

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

## Completion and reporting

A Plan is complete only when every task and acceptance item in the development
plan has code or test evidence, safe defaults remain off, and the full test
report (commands, exit codes, timings, unrun tests and reasons) is delivered.
Do not automatically start the next Plan.
