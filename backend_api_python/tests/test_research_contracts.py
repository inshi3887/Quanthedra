"""P2 tests: instrument identity, action mapping, contract purity.

Plan acceptance: all markets, aliases, ambiguities and failing inputs
covered as parameterised cases; the functions are pure (idempotent, no
database / network / LLM / order dependency).
"""

from __future__ import annotations

import pytest

from app.services.research.action_mapping import (
    Action,
    PositionState,
    TradeSide,
    map_action_to_candidate,
)
from app.services.research.contracts import Market, ReasonCode
from app.services.research.instrument_identity import (
    InstrumentIdentity,
    resolve_instrument,
)


# ---------------------------------------------------------------------------
# Instrument identity — canonical positive cases (every research market)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "market,raw,expect_symbol",
    [
        (Market.US, "AAPL", "AAPL"),
        (Market.US, "aapl", "AAPL"),          # case-insensitive input
        (Market.CN, "600519", "600519"),
        (Market.CN, "sh600519", "600519"),    # SH prefix stripped
        (Market.CN, "SZ000001", "000001"),    # SZ prefix stripped
        (Market.HK, "hk00700", "0700.HK"),    # plan alias #1
        (Market.HK, "00700", "0700.HK"),      # plan alias #2
        (Market.HK, "0700.HK", "0700.HK"),    # plan alias #3 (canonical)
        (Market.HK, "1", "0001.HK"),          # 1-digit zero-padded to 4
        (Market.HK, "5", "0005.HK"),          # HSBC
        (Market.HK, "700", "0700.HK"),        # bare 3-digit alias
        (Market.JP, "7203.T", "7203.T"),
        (Market.KR, "005930.KS", "005930.KS"),
        (Market.KR, "035720.KQ", "035720.KQ"),
        (Market.TW, "2330.TW", "2330.TW"),
        (Market.TW, "6488.TWO", "6488.TWO"),
    ],
)
def test_resolve_canonical_identities(market, raw, expect_symbol):
    result = resolve_instrument(market, raw)
    assert result.ok, result.reasons
    identity: InstrumentIdentity = result.value
    assert identity.symbol == expect_symbol
    assert identity.canonical_key == f"{market}:{expect_symbol}"
    assert identity.asset_class == "equity"
    assert identity.currency and identity.timezone and identity.exchange


@pytest.mark.parametrize(
    "raw,expect_currency,expect_tz",
    [
        ("AAPL", "USD", "America/New_York"),
        ("600519", "CNY", "Asia/Shanghai"),
        ("hk00700", "HKD", "Asia/Hong_Kong"),
        ("7203.T", "JPY", "Asia/Tokyo"),
        ("005930.KS", "KRW", "Asia/Seoul"),
        ("2330.TW", "TWD", "Asia/Taipei"),
    ],
)
def test_market_metadata(raw, expect_currency, expect_tz):
    identity = resolve_instrument("US" if raw == "AAPL" else "HK" if raw.startswith("hk") else None, raw) \
        if False else None  # placeholder to keep flake quiet
    # resolve with the right market per sample
    market_map = {
        "AAPL": "US", "600519": "CN", "hk00700": "HK",
        "7203.T": "JP", "005930.KS": "KR", "2330.TW": "TW",
    }
    result = resolve_instrument(market_map[raw], raw)
    assert result.ok
    assert result.value.currency == expect_currency
    assert result.value.timezone == expect_tz


def test_cn_exchange_prefix_rule():
    sh = resolve_instrument(Market.CN, "600519").value
    sz = resolve_instrument(Market.CN, "000001").value
    assert "XSHG" in sh.exchange
    assert "XSHE" in sz.exchange


# ---------------------------------------------------------------------------
# Fail-closed cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "market,raw,reason",
    [
        ("XX", "AAPL", ReasonCode.UNKNOWN_MARKET),
        ("Crypto", "BTC", ReasonCode.UNKNOWN_MARKET),   # never falls back to crypto
        ("", "AAPL", ReasonCode.UNKNOWN_MARKET),
        (None, "AAPL", ReasonCode.UNKNOWN_MARKET),
        (Market.US, "", ReasonCode.EMPTY_SYMBOL),
        (Market.US, "   ", ReasonCode.EMPTY_SYMBOL),
        (Market.CN, None, ReasonCode.EMPTY_SYMBOL),
        (Market.JP, "7203", ReasonCode.AMBIGUOUS_SYMBOL),      # bare JP code
        (Market.KR, "005930", ReasonCode.AMBIGUOUS_SYMBOL),    # bare KR code
        (Market.TW, "2330", ReasonCode.AMBIGUOUS_SYMBOL),      # bare TW code
        (Market.KR, "005930.TW", ReasonCode.BAD_SUFFIX),       # wrong suffix
        (Market.TW, "2330.KS", ReasonCode.BAD_SUFFIX),         # wrong suffix
        (Market.JP, "12345.T", ReasonCode.BAD_SUFFIX),         # 5-digit JP
        (Market.CN, "12345", ReasonCode.BAD_SUFFIX),           # 5-digit CN
        (Market.CN, "900519", ReasonCode.BAD_SUFFIX),          # unknown CN board prefix
        (Market.HK, "hkABC", ReasonCode.BAD_SUFFIX),
        (Market.US, "AAPL1", ReasonCode.BAD_SUFFIX),           # digits in US symbol
    ],
)
def test_fail_closed_inputs(market, raw, reason):
    result = resolve_instrument(market, raw)
    assert not result.ok
    assert reason in result.reasons


# ---------------------------------------------------------------------------
# Purity / idempotency
# ---------------------------------------------------------------------------


def test_resolution_is_idempotent():
    once = resolve_instrument(Market.HK, "00700").value
    again = resolve_instrument(Market.HK, once.symbol)   # feed canonical back
    assert again.ok and again.value == once
    # dataclass is immutable
    with pytest.raises(Exception):
        once.symbol = "XXXXX"


def test_no_io_modules():
    """The research contracts package must not import network/DB/LLM libs."""
    import sys

    import app.services.research.action_mapping  # noqa: F401
    import app.services.research.contracts  # noqa: F401
    import app.services.research.instrument_identity  # noqa: F401

    forbidden = ("requests", "psycopg2", "celery", "litellm", "redis")
    for mod in forbidden:
        assert mod not in sys.modules or not _imported_by_research(mod)


def _imported_by_research(mod_name: str) -> bool:
    import inspect

    import app.services.research.action_mapping as am
    import app.services.research.contracts as ct
    import app.services.research.instrument_identity as ii

    for module in (am, ct, ii):
        if mod_name in getattr(module, "__dict__", {}):
            return True
        if mod_name in inspect.getsource(module).lower():
            return True
    return False


# ---------------------------------------------------------------------------
# Action × position matrix
# ---------------------------------------------------------------------------


def test_trade_actions_matrix():
    # buy / add
    assert map_action_to_candidate(Action.BUY, PositionState.FLAT).value.side is TradeSide.OPEN_LONG
    assert map_action_to_candidate(Action.BUY, PositionState.LONG).value.side is TradeSide.ADD_LONG
    assert map_action_to_candidate(Action.ADD, PositionState.FLAT).value.side is TradeSide.OPEN_LONG
    assert map_action_to_candidate(Action.ADD, PositionState.LONG).value.side is TradeSide.ADD_LONG
    # reduce / sell with a position
    assert map_action_to_candidate(Action.REDUCE, PositionState.LONG).value.side is TradeSide.REDUCE_LONG
    assert map_action_to_candidate(Action.SELL, PositionState.LONG).value.side is TradeSide.CLOSE_LONG
    # reduce / sell flat: rejected, NEVER open_short
    r = map_action_to_candidate(Action.SELL, PositionState.FLAT)
    assert not r.ok and ReasonCode.SELL_WITHOUT_POSITION in r.reasons
    r = map_action_to_candidate(Action.REDUCE, PositionState.FLAT)
    assert not r.ok and ReasonCode.SELL_WITHOUT_POSITION in r.reasons


def test_no_short_side_ever_exists():
    """Structural guarantee: no mapping path can yield a short side."""
    sides = {TradeSide.OPEN_LONG, TradeSide.ADD_LONG, TradeSide.REDUCE_LONG, TradeSide.CLOSE_LONG}
    for action in Action:
        for state in PositionState:
            result = map_action_to_candidate(action, state)
            if result.ok:
                assert result.value.side in sides
                assert "short" not in result.value.side.value


@pytest.mark.parametrize("action", [Action.HOLD, Action.WATCH, Action.AVOID, Action.ALERT])
@pytest.mark.parametrize("state", list(PositionState))
def test_non_trade_actions_never_yield_candidates(action, state):
    result = map_action_to_candidate(action, state)
    assert not result.ok
    assert ReasonCode.NON_TRADE_ACTION in result.reasons
    if action is Action.HOLD:
        assert ReasonCode.HOLD_STATE_UNCHANGED in result.reasons


@pytest.mark.parametrize("action", ["BUY", "Buy", "buy", Action.BUY])
def test_action_input_is_case_insensitive(action):
    result = map_action_to_candidate(action, PositionState.FLAT)
    assert result.ok and result.value.side is TradeSide.OPEN_LONG


@pytest.mark.parametrize(
    "action,state",
    [("bogus", PositionState.FLAT), (None, PositionState.FLAT),
     (Action.BUY, "bogus"), (Action.BUY, None),
     (Action.SELL, None), (Action.REDUCE, None)],
)
def test_mapping_fail_closed(action, state):
    result = map_action_to_candidate(action, state)
    assert not result.ok and result.reasons


def test_full_matrix_is_total():
    """Every (action, state) pair returns an answer — no exceptions, no None."""
    for action in Action:
        for state in PositionState:
            result = map_action_to_candidate(action, state)
            assert isinstance(result, object)
            assert (result.ok is True) or (result.reasons)
