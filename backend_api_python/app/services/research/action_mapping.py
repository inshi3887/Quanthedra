"""P2 action mapping — research verdicts to allowed trade intents (pure).

Rules (plan P2 tasks 5-6):

- Action enum: ``buy / add / hold / reduce / sell / watch / avoid / alert``.
- A full action × position-state matrix decides, per (action, position),
  whether a trade candidate may exist and which side it may carry.
- Stock ``sell`` NEVER becomes ``open_short`` — with no position it is a
  rejection (:attr:`ReasonCode.SELL_WITHOUT_POSITION`).
- ``hold / watch / avoid / alert`` never produce a trade candidate
  (:attr:`ReasonCode.NON_TRADE_ACTION`); ``hold`` additionally reports
  :attr:`ReasonCode.HOLD_STATE_UNCHANGED` for observability.

The mapped side values reuse the spot-long vocabulary the downstream
strategy layer speaks (``open_long`` / ``add_long`` / ``reduce_long`` /
``close_long``); shorts are structurally unreachable from this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

from .contracts import ContractResult, ReasonCode


class Action(str, Enum):
    BUY = "buy"
    ADD = "add"
    HOLD = "hold"
    REDUCE = "reduce"
    SELL = "sell"
    WATCH = "watch"
    AVOID = "avoid"
    ALERT = "alert"


class PositionState(str, Enum):
    """Whether the portfolio currently holds the instrument."""

    FLAT = "flat"            # no position
    LONG = "long"            # existing spot-long position
    # SHORT is intentionally absent: research spot flow never assumes a
    # short book; presenting one here would invite mapping sell -> short.


class TradeSide(str, Enum):
    """Candidate trade intents this module may emit (spot-long only)."""

    OPEN_LONG = "open_long"
    ADD_LONG = "add_long"
    REDUCE_LONG = "reduce_long"
    CLOSE_LONG = "close_long"


_NON_TRADE_ACTIONS = frozenset(
    {Action.HOLD, Action.WATCH, Action.AVOID, Action.ALERT}
)


@dataclass(frozen=True)
class TradeCandidate:
    side: TradeSide
    action: Action
    position_state: PositionState


def _candidate(side: TradeSide, action: Action, state: PositionState) -> ContractResult:
    return ContractResult.success(
        TradeCandidate(side=side, action=action, position_state=state)
    )


def _reject(*reasons: str) -> ContractResult:
    return ContractResult.failure(*reasons)


def _resolve_action(action) -> Optional[Action]:
    if isinstance(action, Action):
        return action
    if action is None:
        return None
    try:
        return Action(str(action).strip().lower())
    except ValueError:
        return None


def _resolve_state(state) -> Optional[PositionState]:
    if isinstance(state, PositionState):
        return state
    if state is None:
        return None
    try:
        return PositionState(str(state).strip().lower())
    except ValueError:
        return None


def map_action_to_candidate(action, position_state) -> ContractResult:
    """Map (research action, current position state) -> trade candidate.

    Full matrix (rows = action, cols = position):

    ============  ==================  ==========================
    action        FLAT                LONG
    ============  ==================  ==========================
    buy           open_long           add_long
    add           open_long           add_long
    hold          — (non-trade)       — (non-trade)
    reduce        sell_without_pos    reduce_long
    sell          sell_without_pos    close_long
    watch         — (non-trade)       — (non-trade)
    avoid         — (non-trade)       — (non-trade)
    alert         — (non-trade)       — (non-trade)
    ============  ==================  ==========================

    Failure cells return machine reason codes; ``sell``/``reduce`` on a
    flat book never fabricate a short (plan P2 task 6). Unknown enum
    inputs fail closed with :attr:`ReasonCode.NON_TRADE_ACTION` /
    ``identity.unknown_market``-style stability (dedicated codes below).
    """
    resolved_action = _resolve_action(action)
    if resolved_action is None:
        return _reject(ReasonCode.NON_TRADE_ACTION)

    resolved_state = _resolve_state(position_state)
    if resolved_state is None:
        return _reject(ReasonCode.SELL_WITHOUT_POSITION if resolved_action in
                       (Action.REDUCE, Action.SELL) else ReasonCode.NON_TRADE_ACTION)

    if resolved_action in _NON_TRADE_ACTIONS:
        reasons = [ReasonCode.NON_TRADE_ACTION]
        if resolved_action is Action.HOLD:
            reasons.append(ReasonCode.HOLD_STATE_UNCHANGED)
        return _reject(*reasons)

    if resolved_state is PositionState.FLAT:
        if resolved_action in (Action.BUY, Action.ADD):
            return _candidate(TradeSide.OPEN_LONG, resolved_action, resolved_state)
        # reduce/sell on flat: no position to exit; NEVER open_short.
        return _reject(ReasonCode.SELL_WITHOUT_POSITION)

    # PositionState.LONG
    if resolved_action in (Action.BUY, Action.ADD):
        return _candidate(TradeSide.ADD_LONG, resolved_action, resolved_state)
    if resolved_action is Action.REDUCE:
        return _candidate(TradeSide.REDUCE_LONG, resolved_action, resolved_state)
    # Action.SELL
    return _candidate(TradeSide.CLOSE_LONG, resolved_action, resolved_state)


def trade_capable_actions() -> Tuple[Action, ...]:
    """Actions that can ever yield a candidate (diagnostic/export helper)."""
    return (Action.BUY, Action.ADD, Action.REDUCE, Action.SELL)


__all__ = [
    "Action",
    "PositionState",
    "TradeSide",
    "TradeCandidate",
    "map_action_to_candidate",
    "trade_capable_actions",
]
