# ADR-P0-002: Mock payment provider for the USDT billing flow

- **Status**: Accepted (dev/test substitution only; real-payment integration
  is out of P0 scope and tracked in the summary below)
- **Date**: 2026-09-02

## Context

The QD baseline ships a USDT on-chain membership billing flow
(`routes/billing.py` -> `services/usdt_payment/service.py`). Payment
confirmation polls third-party block-explorer APIs (TronGrid for TRC20, EVM
explorers for BEP20/ERC20, Solana RPC) through the per-chain watchers in
`services/usdt_payment/watchers/`. Those APIs are quota-limited and
unreachable in offline CI, which blocks exercising the full order lifecycle
(create -> paid -> confirmed -> membership activation) in dev/test.

P0 scope guard: this ADR records a **dev/test substitution only**. It does
not touch the production payment path, does not change the order schema, and
does not weaken any CI rule.

## Decision

1. Introduce `USDT_PAY_PROVIDER` (values `real` | `mock`, default `real`).
   The default keeps upstream behaviour bit-for-bit.
2. Implement `services/usdt_payment/mock_provider.py`:
   - `PaymentProvider` abstract base (quote / find_payment / provider_id) as
     the explicit seam for a future real payment gateway;
   - `MockPaymentProvider` implementing the same watcher signature, returning
     a deterministic exact-match `IncomingTransfer` (mock tx hash/order id
     derived from SHA-256 of address+amount+seq) in `success` mode;
   - `MOCK_PAYMENT_MODE` selects `success` (transfer found), `fail` (never
     matches -> order expires, simulating payment failure), `timeout`
     (explorer-outage note -> order stays pending);
   - `MOCK_PAYMENT_DELAY_SECONDS` simulates the confirmation delay.
3. Wire it statelessly in `watchers/base.get_watcher`: when
   `USDT_PAY_PROVIDER=mock` and the safety guard passes, the mock bound
   method is returned **without mutating the watcher registry**, so
   switching back to `real` can never leak a stale mock binding.
4. Fail-closed safety guard `validate_mock_safety()`: mock is refused while
   any real receiving address (`USDT_TRC20_ADDRESS`, `USDT_BEP20_ADDRESS`,
   `USDT_ERC20_ADDRESS`, `USDT_SOL_ADDRESS`) is configured. Mock never runs
   against real money addresses and must never be enabled in production.
5. Mock never performs network I/O and never reads credentials. Order
   creation, idempotency, expiry, confirmation and membership activation
   keep running through the unchanged `UsdtPaymentService` code path and the
   unchanged `qd_usdt_orders` schema.
6. Add a `MOCK` entry to `CHAIN_SPECS` (`chains.py`) so the simulated chain
   can flow through the unchanged `create_order` validation. It is doubly
   hidden by default: absent from the `USDT_PAY_ENABLED_CHAINS` default list
   AND with no default receiving address (`USDT_MOCK_ADDRESS` env-only), so
   `chain_metadata("MOCK")` is None until an operator explicitly enables
   both in a mock environment. With `USDT_PAY_PROVIDER=real` the MOCK chain
   resolves no watcher: a stray MOCK order can stay pending but can never
   be confirmed.
7. `validate_mock_safety()` excludes the MOCK chain's own address env from
   the real-address refusal check (it is a simulated wallet by definition).
8. Tests: `tests/test_usdt_payment_mock.py` (13 cases: provider selection,
   safety refusal, success/fail/timeout modes, deterministic identifiers,
   argument validation, provider protocol) and
   `tests/test_usdt_payment_mock_service.py` (5 cases: full create -> paid
   -> confirmed -> membership-activation lifecycle, fail -> expired,
   timeout -> stays pending, default-hide guards, registry isolation).

## Consequences

- Dev/test/CI can run the complete billing lifecycle with zero explorer API
  usage and zero network access.
- Production billing is untouched: with `USDT_PAY_PROVIDER` unset the real
  watchers load exactly as before.
- Going live later means (a) unsetting `USDT_PAY_PROVIDER=mock`, (b)
  configuring real receiving addresses (which the safety guard already
  treats as incompatible with mock), and optionally (c) implementing a new
  `PaymentProvider` subclass for a hosted gateway — no changes to the order
  service or routes.
