"""Tests for the mock payment provider (``USDT_PAY_PROVIDER=mock``).

Scope:
- provider selection: mock only activates via env; default stays real
- safety guard: mock refuses to run when real receiving addresses exist
- success mode: exact-match simulated transfer, deterministic mock
  order/tx identifiers, configurable confirm delay
- fail mode: never matches, order is expected to expire (simulated
  payment failure)
- timeout mode: provider-error note, order stays pending (simulated
  explorer outage)

Pure-function tests: no network, no DB, no real chain access.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.services.usdt_payment.chains import CHAIN_SPECS
from app.services.usdt_payment.mock_provider import (
    MockPaymentProvider,
    get_mock_provider,
    is_mock_provider_enabled,
    resolve_mock_watcher,
    validate_mock_safety,
)
from app.services.usdt_payment.watchers.base import _REGISTRY, get_watcher


@pytest.fixture(autouse=True)
def _clean_registry():
    """Snapshot and restore the watcher registry around each test so any
    real-module self-registration never leaks between test modules."""
    saved = dict(_REGISTRY)
    yield
    _REGISTRY.clear()
    _REGISTRY.update(saved)


# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------


def test_mock_disabled_by_default(monkeypatch):
    monkeypatch.delenv("USDT_PAY_PROVIDER", raising=False)
    assert is_mock_provider_enabled() is False
    assert resolve_mock_watcher() is None
    # Real chain codes resolve to the live watchers, not the mock.
    fn = get_watcher("TRC20")
    assert fn is not None
    assert getattr(fn, "__self__", None) is None  # plain function, not bound method
    assert "mock" not in getattr(fn, "__module__", "")


def test_mock_enabled_via_env(monkeypatch):
    monkeypatch.setenv("USDT_PAY_PROVIDER", "mock")
    assert is_mock_provider_enabled() is True
    # Safety guard passes because no real addresses are configured.
    monkeypatch.delenv("USDT_TRC20_ADDRESS", raising=False)
    fn = resolve_mock_watcher()
    assert fn is not None
    assert fn.__self__ is get_mock_provider()
    # Every real chain plus the MOCK code resolve to the same mock finder
    # (same provider instance + same underlying function).
    for chain in ("TRC20", "BEP20", "ERC20", "SOL", "MOCK"):
        got = get_watcher(chain)
        assert got is not None, f"mock watcher missing for {chain}"
        assert got.__self__ is fn.__self__ and got.__func__ is fn.__func__
    # The real registry itself stays untouched (stateless resolution).
    assert all("mock" not in getattr(f, "__module__", "") for f in _REGISTRY.values())


def test_mock_refused_when_real_address_configured(monkeypatch):
    """Fail-closed: a real receiving address means mock must not activate."""
    monkeypatch.setenv("USDT_PAY_PROVIDER", "mock")
    monkeypatch.setenv("USDT_TRC20_ADDRESS", "TRealAddressDoNotUseMockHere123")
    ok, reason = validate_mock_safety()
    assert ok is False
    assert "TRC20" in reason
    assert resolve_mock_watcher() is None
    # Whatever resolves for the chain, it must never be the mock when the
    # safety guard refused. (The real watcher may be absent here because the
    # registry fixture resets state and module self-registration only runs on
    # first import — a test-isolation artifact, not production behaviour.)
    fn = get_watcher("TRC20")
    assert fn is None or "mock" not in getattr(fn, "__module__", "")


def test_mock_covers_every_real_chain_code():
    """The mock claims all real chain codes so a mock-mode order on any
    configured chain still resolves a watcher."""
    assert set(MockPaymentProvider.CHAINS) >= set(CHAIN_SPECS.keys())


# ---------------------------------------------------------------------------
# Success mode — simulated payment received
# ---------------------------------------------------------------------------


def test_mock_success_returns_exact_match_transfer(monkeypatch):
    monkeypatch.delenv("MOCK_PAYMENT_MODE", raising=False)
    provider = get_mock_provider()
    amount = Decimal("19.901234")
    tx, note = provider.find_payment("mock_addr_1", amount, datetime.now(timezone.utc))
    assert tx is not None
    assert "mock_ok" in note
    # Exact amount match is the foundation of amount-suffix identification.
    assert tx.value_smallest_unit == int((amount * Decimal(10**6)).to_integral_value())
    assert tx.to_addr == "mock_addr_1"
    assert tx.tx_hash.startswith("mock_tx_")
    assert tx.from_addr.startswith("mock_from_")


def test_mock_tx_identifiers_deterministic_and_unique(monkeypatch):
    """Same (address, amount, seq) -> same tx id; different orders -> unique
    tx ids. This is the "mock order/transaction number" behaviour: stable
    enough to audit a single order's lifecycle, distinct enough to tell
    orders apart."""
    provider = get_mock_provider()
    a1 = provider._synthesize_transfer("addr", Decimal("10"), None, seq=1)
    a2 = provider._synthesize_transfer("addr", Decimal("10"), None, seq=1)
    b = provider._synthesize_transfer("addr", Decimal("10"), None, seq=2)
    c = provider._synthesize_transfer("addr", Decimal("20"), None, seq=1)
    assert a1.tx_hash == a2.tx_hash
    assert a1.tx_hash != b.tx_hash
    assert a1.tx_hash != c.tx_hash


def test_mock_success_respects_delay_setting(monkeypatch):
    monkeypatch.setenv("MOCK_PAYMENT_DELAY_SECONDS", "42")
    provider = get_mock_provider()
    _, note = provider.find_payment("addr", Decimal("5"), None)
    assert "delay=42" in note


# ---------------------------------------------------------------------------
# Fail mode — simulated payment failure (never arrives -> order expires)
# ---------------------------------------------------------------------------


def test_mock_fail_mode_never_matches(monkeypatch):
    monkeypatch.setenv("MOCK_PAYMENT_MODE", "fail")
    provider = get_mock_provider()
    for _ in range(3):
        tx, note = provider.find_payment("addr", Decimal("9.99"), datetime.now(timezone.utc))
        assert tx is None
        assert "mock_no_payment" in note


def test_mock_timeout_mode_reports_provider_error(monkeypatch):
    """Simulated explorer outage: no transfer AND an explicit provider-error
    note, so the reconciler keeps the order pending instead of expiring it
    on a false 'no payment yet'."""
    monkeypatch.setenv("MOCK_PAYMENT_MODE", "timeout")
    provider = get_mock_provider()
    tx, note = provider.find_payment("addr", Decimal("9.99"), None)
    assert tx is None
    assert note == "mock_provider_timeout"


# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("address,amount", [("", Decimal("1")), ("addr", Decimal("0")), ("addr", Decimal("-1"))])
def test_mock_rejects_bad_args(monkeypatch, address, amount):
    provider = get_mock_provider()
    tx, note = provider.find_payment(address, amount, None)
    assert tx is None
    assert note == "mock_bad_args"


# ---------------------------------------------------------------------------
# Provider abstraction contract
# ---------------------------------------------------------------------------


def test_mock_provider_satisfies_payment_provider_protocol():
    from app.services.usdt_payment.mock_provider import PaymentProvider

    provider = get_mock_provider()
    assert isinstance(provider, PaymentProvider)
    assert provider.provider_id() == "mock"
    quote = provider.quote("monthly", Decimal("19.9"), None)
    assert quote.chain == "MOCK"
    assert quote.currency == "USDT"
    assert quote.amount == Decimal("19.9")
