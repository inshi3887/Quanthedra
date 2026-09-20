"""P2 research domain contracts — pure data shapes and enumerations.

No I/O, no database, no network, no LLM, no order side effects (plan P2:
无 IO、无订单副作用的稳定领域契约). Everything in this package is a
pure function or an immutable value; import time must stay cheap and
side-effect free.

Market semantics (canonical market codes, suffix rules and ambiguity
handling) live in :mod:`.instrument_identity`; trading-action mapping in
:mod:`.action_mapping`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


# ---------------------------------------------------------------------------
# Markets
# ---------------------------------------------------------------------------


class Market:
    """Canonical research-market codes (stable machine values)."""

    US = "USStock"
    CN = "CNStock"
    HK = "HKStock"
    JP = "JPStock"
    KR = "KRStock"
    TW = "TWStock"

    ALL: Tuple[str, ...] = (US, CN, HK, JP, KR, TW)


# ---------------------------------------------------------------------------
# Reason codes
# ---------------------------------------------------------------------------


class ReasonCode:
    """Stable machine codes for rejections and diagnostics.

    Display text is localised separately (plan P2 task 7); never embed
    human sentences here. Values are dot-namespaced and never renumbered —
    downstream audit logs and tests depend on exact strings.
    """

    # instrument identity
    UNKNOWN_MARKET = "identity.unknown_market"
    EMPTY_SYMBOL = "identity.empty_symbol"
    AMBIGUOUS_SYMBOL = "identity.ambiguous_bare_code"
    BAD_SUFFIX = "identity.bad_suffix"

    # action mapping
    NON_TRADE_ACTION = "action.non_trade_action"
    SELL_WITHOUT_POSITION = "action.sell_without_position"
    SHORT_NOT_ALLOWED = "action.short_not_allowed"
    UNSUPPORTED_MARKET_ACTION = "action.unsupported_market"
    HOLD_STATE_UNCHANGED = "action.hold_state_unchanged"

    # generic
    OK = "ok"


@dataclass(frozen=True)
class ContractResult:
    """Uniform result envelope for pure contract functions.

    ``ok=True`` carries the payload in ``value``; ``ok=False`` carries one
    or more machine reason codes in ``reasons`` (never human text).
    """

    ok: bool
    value: object = None
    reasons: Tuple[str, ...] = ()

    @classmethod
    def success(cls, value) -> "ContractResult":
        return cls(ok=True, value=value)

    @classmethod
    def failure(cls, *reasons: str) -> "ContractResult":
        return cls(ok=False, reasons=reasons or (ReasonCode.OK,))


__all__ = ["Market", "ReasonCode", "ContractResult"]
