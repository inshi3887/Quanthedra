"""Service-level integration tests for the mock payment provider.

These exercise the *full* order lifecycle through ``UsdtPaymentService``
with ``USDT_PAY_PROVIDER=mock``:

    create_order (MOCK chain) -> simulated transfer found by the watcher
    -> status=paid -> confirm delay elapsed -> status=confirmed
    -> membership activation via billing.purchase_membership

Failure paths:
    - ``MOCK_PAYMENT_MODE=fail``: watcher never matches -> order expires
      once its window closes (simulated 'payer never sent money').
    - ``MOCK_PAYMENT_MODE=timeout``: explorer-outage note. Log-only by
      upstream design: the service cannot distinguish 'no transfer yet'
      from 'explorer down', so an *unexpired* order simply stays pending.

The DB layer is an extended in-memory stand-in (same shape as
``test_usdt_payment_idempotency.py``); no Postgres, no network, no real
chain. The point is to prove the mock seam plugs into the real service
flow — not just the watcher function in isolation.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, List
from unittest.mock import patch as _patch

import pytest

from app.services.usdt_payment.service import UsdtPaymentService
from app.services.usdt_payment.watchers.base import _REGISTRY, get_watcher

# Reuse the in-memory DB row store from the idempotency suite.
from tests.test_usdt_payment_idempotency import _MemCursor, _MemDb


class _FlowCursor(_MemCursor):
    """Extends the create-order cursor with the reconciler statements:
    paid/confirmed/expired transitions and the confirm pre-check."""

    def execute(self, sql: str, params=()) -> None:
        sql_u = " ".join(sql.split()).upper()
        params = tuple(params or ())
        if sql_u.startswith("UPDATE QD_USDT_ORDERS SET STATUS='PAID'"):
            tx_hash, paid_at, order_id = params[:3]
            for r in self.db.rows:
                if r.get("id") == order_id and r.get("status") in ("pending", "expired"):
                    r["status"] = "paid"
                    r["tx_hash"] = tx_hash
                    r["paid_at"] = paid_at
            self._last_result = []
            return
        if sql_u.startswith("UPDATE QD_USDT_ORDERS SET STATUS='CONFIRMED'"):
            (order_id,) = params
            for r in self.db.rows:
                if r.get("id") == order_id and r.get("status") in ("paid", "pending"):
                    r["status"] = "confirmed"
                    r["confirmed_at"] = datetime.now(timezone.utc)
            self._last_result = []
            return
        if sql_u.startswith("UPDATE QD_USDT_ORDERS SET STATUS='EXPIRED'"):
            (order_id,) = params
            for r in self.db.rows:
                if r.get("id") == order_id and r.get("status") == "pending":
                    r["status"] = "expired"
            self._last_result = []
            return
        if sql_u.startswith("SELECT STATUS FROM QD_USDT_ORDERS"):
            (order_id,) = params
            row = next((r for r in self.db.rows if r.get("id") == order_id), None)
            self._last_result = [{"status": row["status"]}] if row else []
            return
        super().execute(sql, params)


class _FlowDb(_MemDb):
    def cursor(self) -> _FlowCursor:
        return _FlowCursor(self)


@pytest.fixture(autouse=True)
def _mock_mode(monkeypatch):
    """Enable the mock provider with a dedicated simulated chain."""
    monkeypatch.setenv("USDT_PAY_ENABLED", "true")
    monkeypatch.setenv("USDT_PAY_PROVIDER", "mock")
    monkeypatch.setenv("USDT_PAY_ENABLED_CHAINS", "MOCK")
    monkeypatch.setenv("USDT_MOCK_ADDRESS", "mock_wallet_address_0001")
    monkeypatch.setenv("MOCK_PAYMENT_MODE", "success")
    monkeypatch.setenv("MOCK_PAYMENT_DELAY_SECONDS", "0")
    monkeypatch.delenv("USDT_PAY_CONFIRM_SECONDS", raising=False)
    yield


@pytest.fixture
def svc():
    db = _FlowDb()

    @contextmanager
    def _ctx():
        yield db

    with _patch("app.services.usdt_payment.service.get_db_connection", _ctx):
        yield UsdtPaymentService(), db


# ---------------------------------------------------------------------------
# Lifecycle: create -> paid -> confirmed -> activation
# ---------------------------------------------------------------------------


def test_mock_full_lifecycle_confirms_and_activates(svc):
    service, db = svc
    activated: List[dict] = []

    with _patch.object(service.billing, "purchase_membership") as pm:

        def _record(user_id, plan, record_membership_order=False, fulfillment_ref=""):
            activated.append(
                {"user_id": user_id, "plan": plan, "fulfillment_ref": fulfillment_ref}
            )
            return True, "ok", {}

        pm.side_effect = _record

        ok, msg, order = service.create_order(7, "monthly", chain="MOCK")
        assert ok is True, msg
        assert order["chain"] == "MOCK"
        assert order["status"] == "pending"
        assert order["address"] == "mock_wallet_address_0001"

        row = db.rows[0]
        # Pass 1: the mock watcher finds the simulated transfer; the order
        # becomes paid with a mock tx id. Confirmation waits out the
        # (default 30s) confirm delay.
        service._refresh_one_order(row)
        assert row["status"] == "paid", f"expected paid, got {row['status']}"
        assert (row["tx_hash"] or "").startswith("mock_tx_")
        assert row["paid_at"] is not None
        assert activated == []

        # Pass 2: confirm delay elapsed (rewind paid_at in the in-memory
        # row instead of sleeping) -> confirmed + membership activated.
        row["paid_at"] = datetime.now(timezone.utc) - timedelta(seconds=120)
        service._refresh_one_order(row)
        assert row["status"] == "confirmed", f"expected confirmed, got {row['status']}"
        assert row["confirmed_at"] is not None
        assert len(activated) == 1
        assert activated[0]["user_id"] == 7
        assert activated[0]["plan"] == "monthly"
        assert activated[0]["fulfillment_ref"] == f"usdt_order:{row['id']}"


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


def test_mock_fail_mode_expires_order(svc, monkeypatch):
    """MOCK_PAYMENT_MODE=fail: watcher never matches; once the window
    closes the order expires (simulated payment failure)."""
    monkeypatch.setenv("MOCK_PAYMENT_MODE", "fail")
    service, db = svc

    ok, msg, order = service.create_order(8, "yearly", chain="MOCK")
    assert ok is True
    row = db.rows[0]

    # While the window is open: no match, stays pending.
    service._refresh_one_order(row)
    assert row["status"] == "pending"

    # After the window closes: pending -> expired.
    row["expires_at"] = datetime.now(timezone.utc) - timedelta(minutes=1)
    service._refresh_one_order(row)
    assert row["status"] == "expired"


def test_mock_timeout_mode_keeps_unexpired_order_pending(svc, monkeypatch):
    """MOCK_PAYMENT_MODE=timeout simulates an explorer outage: the refresh
    records the provider-error note in logs; an unexpired order simply
    stays pending (no confirm, no expiry)."""
    monkeypatch.setenv("MOCK_PAYMENT_MODE", "timeout")
    service, db = svc

    ok, msg, order = service.create_order(9, "lifetime", chain="MOCK")
    assert ok is True
    row = db.rows[0]

    service._refresh_one_order(row)
    assert row["status"] == "pending"
    assert row["tx_hash"] == ""
    assert row["paid_at"] is None


# ---------------------------------------------------------------------------
# Guard rails
# ---------------------------------------------------------------------------


def test_mock_chain_hidden_when_not_enabled(svc, monkeypatch):
    """With MOCK absent from USDT_PAY_ENABLED_CHAINS, create_order must
    reject it (doubly-locked default hide, ADR-P0-002). The exact reason
    depends on filter order: with TRC20 also disabled the enabled list is
    empty -> 'no_chain_configured'; with a live chain enabled, MOCK
    resolves no metadata -> 'chain_not_available'. Both are fail-closed."""
    service, _ = svc
    monkeypatch.setenv("USDT_PAY_ENABLED_CHAINS", "TRC20")
    ok, msg, out = service.create_order(10, "monthly", chain="MOCK")
    assert ok is False
    assert msg in ("no_chain_configured", "chain_not_available")
    # Address lock: MOCK enabled but its simulated receiving address unset
    # (with TRC20 address present so the picker list is non-empty).
    monkeypatch.setenv("USDT_PAY_ENABLED_CHAINS", "TRC20,MOCK")
    monkeypatch.setenv("USDT_TRC20_ADDRESS", "TTestAddressOnlyForListingCheck")
    monkeypatch.delenv("USDT_MOCK_ADDRESS", raising=False)
    ok, msg, out = service.create_order(10, "monthly", chain="MOCK")
    assert ok is False
    assert msg == "chain_not_available"


def test_mock_watcher_resolves_without_real_modules():
    """get_watcher returns the bound mock finder with an empty registry —
    no real watcher module import, hence zero chance of chain HTTP calls."""
    saved = dict(_REGISTRY)
    _REGISTRY.clear()
    try:
        fn = get_watcher("MOCK")
        assert fn is not None
        assert fn.__self__ is not None  # bound MockPaymentProvider method
        # Real chain codes resolve to the same provider-wide mock finder.
        trc = get_watcher("TRC20")
        assert trc is not None and trc.__self__ is fn.__self__
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(saved)
