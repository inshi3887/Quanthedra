"""Mock payment provider — simulated confirmation for offline/dev/test use.

Why this exists
---------------
The real USDT confirmation path depends on third-party block-explorer APIs
(TronGrid / Etherscan-like / Solana RPC). Those APIs have quota limits and
are unreachable in offline CI. ``USDT_PAY_PROVIDER=mock`` swaps the chain
watcher for a deterministic simulator so the *whole* order lifecycle
(create -> paid -> confirmed -> membership activation) can be exercised
without touching a real chain or a real payment.

This module is the explicit seam for the future real-payment integration:
the domain code always talks to the same watcher interface
(``get_watcher(chain)``), so going live only means registering real
watchers for the chain codes the mock currently claims.

Safety
------
- Mock mode must never be enabled together with real receiving addresses.
  ``validate_mock_safety()`` refuses to run when a chain that mock claims
  also has a real address configured, fail-closed.
- The mock never calls the network and never reads credentials.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Optional, Tuple

from app.utils.logger import get_logger

from .chains import CHAIN_SPECS
from .watchers.base import IncomingTransfer, WatcherResult

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Payment provider abstraction (the seam for future real payment gateways)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PaymentQuote:
    """What the user is asked to pay, normalized across providers."""

    chain: str
    currency: str
    amount: Decimal


class PaymentProvider:
    """Interface every payment provider must satisfy.

    The USDT flow uses the per-chain watcher registry, which is already the
    functional seam for "how do we learn a payment happened". This Protocol
    documents that contract explicitly so a future hosted-gateway provider
    (Stripe/Paddle/alipay etc.) can be slotted in by implementing the same
    three operations instead of diverging into a second billing path.
    """

    def quote(self, plan: str, base_amount: Decimal, chain: Optional[str]) -> PaymentQuote:
        """Return the payable quote for a plan."""
        raise NotImplementedError

    def find_payment(
        self,
        address: str,
        amount: Decimal,
        created_at,
    ) -> WatcherResult:
        """Return (transfer, note): did the money arrive?"""
        raise NotImplementedError

    def provider_id(self) -> str:
        """Stable identifier used in audit logs and order metadata."""
        raise NotImplementedError


class MockPaymentProvider(PaymentProvider):
    """Simulated provider.

    Behaviour is controlled by env, read at call time so tests can flip
    outcomes without reimporting:

    - ``MOCK_PAYMENT_MODE``: ``success`` (default) | ``fail`` | ``timeout``
      - ``success``: first scan of an order finds an exact-match transfer
        after a simulated delay, then confirmation proceeds.
      - ``fail``: never finds a transfer, so the order expires —
        simulates the payer never sending money.
      - ``timeout``: returns a provider-error note without a transfer —
        simulates the block-explorer being down; order stays pending.
    - ``MOCK_PAYMENT_DELAY_SECONDS``: simulated confirm delay (default 0).
    """

    CHAINS = ("TRC20", "BEP20", "ERC20", "SOL", "MOCK")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tx_seq = 0

    # ------------------------------------------------------------ provider api

    def provider_id(self) -> str:
        return "mock"

    def quote(self, plan: str, base_amount: Decimal, chain: Optional[str]) -> PaymentQuote:
        chain = (chain or "MOCK").upper()
        return PaymentQuote(chain=chain, currency="USDT", amount=base_amount)

    def find_payment(
        self,
        address: str,
        amount: Decimal,
        created_at,
    ) -> WatcherResult:
        mode = (os.getenv("MOCK_PAYMENT_MODE", "success") or "success").strip().lower()
        if (address or "").strip() == "" or amount <= 0:
            return None, "mock_bad_args"

        if mode == "timeout":
            return None, "mock_provider_timeout"

        if mode == "fail":
            return None, "mock_no_payment(mode=fail)"

        # mode == success: synthesize an exact-match transfer once.
        with self._lock:
            self._tx_seq += 1
            seq = self._tx_seq
        return self._synthesize_transfer(address, amount, created_at, seq), (
            f"mock_ok seq={seq} delay={self._delay_seconds()}"
        )

    # ---------------------------------------------------------------- helpers

    def _delay_seconds(self) -> int:
        try:
            return max(0, int(float(os.getenv("MOCK_PAYMENT_DELAY_SECONDS", "0") or 0)))
        except ValueError:
            return 0

    def _synthesize_transfer(
        self,
        address: str,
        amount: Decimal,
        created_at,
        seq: int,
    ) -> IncomingTransfer:
        """Deterministic pseudo-random tx for auditability: the same
        (address, amount, seq) always yields the same hashes."""
        feed = f"mock:{address}:{amount}:{seq}".encode()
        tx_hash = "mock_tx_" + hashlib.sha256(feed).hexdigest()[:40]
        from_addr = "mock_from_" + hashlib.sha256(b"from" + feed).hexdigest()[:20]
        # 6 decimals mirrors TRC20/ERC20 USDT precision.
        value = int((amount * Decimal(10**6)).to_integral_value())
        block_ms = int(time.time() * 1000)
        raw = {
            "provider": "mock",
            "tx_hash": tx_hash,
            "value_raw": str(value),
            "decimals": 6,
        }
        return IncomingTransfer(
            tx_hash=tx_hash,
            block_timestamp_ms=block_ms,
            from_addr=from_addr,
            to_addr=address,
            value_smallest_unit=value,
            raw=raw,
        )


# ---------------------------------------------------------------------------
# Watcher resolution: mock replaces the chain lookup without mutating the
# real registry, so provider switches can never leak stale mock bindings
# ---------------------------------------------------------------------------


_PROVIDER: Optional[PaymentProvider] = None
_PROVIDER_LOCK = threading.Lock()
_WARNED_MOCK_ACTIVE = False


def get_mock_provider() -> MockPaymentProvider:
    global _PROVIDER
    with _PROVIDER_LOCK:
        if _PROVIDER is None:
            _PROVIDER = MockPaymentProvider()
    return _PROVIDER


def is_mock_provider_enabled() -> bool:
    """True when ``USDT_PAY_PROVIDER=mock``."""
    return (os.getenv("USDT_PAY_PROVIDER", "real").strip().lower() == "mock")


def validate_mock_safety() -> Tuple[bool, str]:
    """Fail-closed guard: mock must not run against real receiving addresses.

    Returns (ok, reason). ``ok=False`` means mock mode must not be used.
    The mock chain's own address env (USDT_MOCK_ADDRESS) is excluded: it is
    a simulated wallet address, not a real one.
    """
    for code, spec in CHAIN_SPECS.items():
        if code == "MOCK":
            continue
        real_address = (os.getenv(spec.address_env, "") or "").strip()
        if real_address:
            return False, f"mock_provider_conflict:{code}:{spec.address_env}_is_set"
    return True, "ok"


def resolve_mock_watcher():
    """Return the mock payment finder when provider=mock and safe, else None.

    - Only active with the explicit ``USDT_PAY_PROVIDER=mock`` opt-in.
    - Fail-closed: if any real receiving address is configured, mock is
      refused (returns None, so the real watcher path — or nothing — runs).
    - Stateless by design: the bound method is returned directly instead of
      being registered into the shared watcher registry, so flipping the
      provider back to live cannot leave a stale mock binding behind.
    """
    global _WARNED_MOCK_ACTIVE
    if not is_mock_provider_enabled():
        return None
    ok, reason = validate_mock_safety()
    if not ok:
        logger.error("Mock payment provider refused: %s", reason)
        return None
    if not _WARNED_MOCK_ACTIVE:
        _WARNED_MOCK_ACTIVE = True
        logger.warning(
            "USDT payment provider = MOCK (simulated payments, no chain access). "
            "Never enable USDT_PAY_PROVIDER=mock with real receiving addresses."
        )
    return get_mock_provider().find_payment
