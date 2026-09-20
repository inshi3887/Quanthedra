"""P2 instrument identity — six-market symbol resolution (pure functions).

Rules (plan P2 tasks 2-4):

- ``InstrumentIdentity(market, symbol, canonical_key, exchange,
  asset_class, currency, timezone)`` is the single canonical shape.
- US  : ``AAPL``            -> ``USStock:AAPL``
- CN  : ``600519`` / ``SH600519`` / ``sh600519`` -> ``CNStock:600519``
- HK  : ``hk00700`` / ``00700`` / ``0700.HK``    -> ``HKStock:0700.HK``
  (codes normalise to the >=4-digit display form: ``00700 -> 0700.HK``,
  ``5 -> 0005.HK``)
- JP  : ``7203.T``        -> ``JPStock:7203.T`` (suffix required)
- KR  : ``005930.KS`` / ``035720.KQ``          -> suffix required (KOSPI/KOSDAQ)
- TW  : ``2330.TW`` / ``6488.TWO``             -> suffix required (TWSE/TPEX)

Fail closed (D: 未知市场、裸日韩台歧义代码和空 symbol 必须 fail closed,
不回退 Crypto 或 CN):

- unknown market, empty/blank symbol, bare ``7203`` / ``005930`` / ``2330``
  (no exchange suffix) are rejections with stable
  :class:`~app.services.research.contracts.ReasonCode` values — never a
  guessed identity, never a fallback to another market.

Exchange/calendar/currency metadata is static knowledge, inlined here to
keep the module dependency-free.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .contracts import ContractResult, Market, ReasonCode


@dataclass(frozen=True)
class InstrumentIdentity:
    market: str
    symbol: str          # exchange-native display symbol
    canonical_key: str   # "<market>:<symbol>"
    exchange: str
    asset_class: str
    currency: str
    timezone: str


# ---------------------------------------------------------------------------
# Per-market static metadata
# ---------------------------------------------------------------------------

_US_EXCH = {"exchange": "XNYS/XNAS (primary by feed)", "currency": "USD",
            "timezone": "America/New_York"}

_MARKET_META = {
    Market.US: {**_US_EXCH, "asset_class": "equity"},
    Market.CN: {"exchange": "XSHG/XSHE (by code prefix)", "currency": "CNY",
                "timezone": "Asia/Shanghai", "asset_class": "equity"},
    Market.HK: {"exchange": "XHKG", "currency": "HKD",
                "timezone": "Asia/Hong_Kong", "asset_class": "equity"},
    Market.JP: {"exchange": "XTKS", "currency": "JPY",
                "timezone": "Asia/Tokyo", "asset_class": "equity"},
    Market.KR: {"exchange": "XKRX (KOSPI/KOSDAQ by suffix)", "currency": "KRW",
                "timezone": "Asia/Seoul", "asset_class": "equity"},
    Market.TW: {"exchange": "XTAI (TWSE/TPEX by suffix)", "currency": "TWD",
                "timezone": "Asia/Taipei", "asset_class": "equity"},
}

_CN_PREFIX = {"6": "XSHG", "0": "XSHE", "3": "XSHE"}  # 6xx Shanghai; 0xx/3xx Shenzhen
_JP_SUFFIX = ".T"
_KR_SUFFIXES = {".KS": "KOSPI", ".KQ": "KOSDAQ"}
_TW_SUFFIXES = {".TW": "TWSE", ".TWO": "TPEX"}

_US_SYMBOL_RE = re.compile(r"^[A-Z]{1,5}$")
_CN_CODE_RE = re.compile(r"^\d{6}$")
_HK_DIGITS_RE = re.compile(r"^\d{1,5}$")
_JP_CODE_RE = re.compile(r"^\d{4}$")
_KR_CODE_RE = re.compile(r"^\d{6}$")
_TW_CODE_RE = re.compile(r"^\d{4,6}$")


def _reject(*reasons: str) -> ContractResult:
    return ContractResult.failure(*reasons)


def _build(market: str, symbol: str, canonical_symbol: str) -> ContractResult:
    meta = _MARKET_META[market]
    return ContractResult.success(
        InstrumentIdentity(
            market=market,
            symbol=canonical_symbol,
            canonical_key=f"{market}:{canonical_symbol}",
            exchange=meta["exchange"],
            asset_class=meta["asset_class"],
            currency=meta["currency"],
            timezone=meta["timezone"],
        )
    )


def _resolve_us(raw: str) -> ContractResult:
    symbol = raw.strip().upper()
    if not _US_SYMBOL_RE.match(symbol):
        return _reject(ReasonCode.BAD_SUFFIX)
    return _build(Market.US, raw, symbol)


def _resolve_cn(raw: str) -> ContractResult:
    text = raw.strip()
    code = text.upper()
    for prefix in ("SH", "SZ"):
        if code.startswith(prefix):
            code = code[len(prefix):]
            break
    if not _CN_CODE_RE.match(code):
        return _reject(ReasonCode.BAD_SUFFIX)
    exchange = _CN_PREFIX.get(code[0])
    if exchange is None:
        return _reject(ReasonCode.BAD_SUFFIX)
    return _build(Market.CN, raw, code)


def _resolve_hk(raw: str) -> ContractResult:
    text = raw.strip()
    code = text.upper()
    if code.startswith("HK"):
        code = code[2:]
    if code.upper().endswith(".HK"):
        code = code[:-3]
    if not _HK_DIGITS_RE.match(code):
        return _reject(ReasonCode.BAD_SUFFIX)
    # Canonical display form strips leading zeros down to >= 4 digits
    # (yfinance/exchange convention): 00700 -> 0700, 0005 -> 0005, 1 -> 0001.
    trimmed = code.lstrip("0") or "0"
    padded = trimmed.zfill(4)
    return _build(Market.HK, raw, f"{padded}.HK")


def _resolve_jp(raw: str) -> ContractResult:
    text = raw.strip().upper()
    if not text.endswith(_JP_SUFFIX):
        # Bare Japanese code (7203) is ambiguous by plan rule — reject.
        return _reject(ReasonCode.AMBIGUOUS_SYMBOL if _JP_CODE_RE.match(text)
                       else ReasonCode.BAD_SUFFIX)
    code = text[: -len(_JP_SUFFIX)]
    if not _JP_CODE_RE.match(code):
        return _reject(ReasonCode.BAD_SUFFIX)
    return _build(Market.JP, raw, text)


def _resolve_kr(raw: str) -> ContractResult:
    text = raw.strip().upper()
    for suffix, board in _KR_SUFFIXES.items():
        if text.endswith(suffix):
            code = text[: -len(suffix)]
            if not _KR_CODE_RE.match(code):
                return _reject(ReasonCode.BAD_SUFFIX)
            return _build(Market.KR, raw, text)
    return _reject(
        ReasonCode.AMBIGUOUS_SYMBOL if _KR_CODE_RE.match(text) else ReasonCode.BAD_SUFFIX
    )


def _resolve_tw(raw: str) -> ContractResult:
    text = raw.strip().upper()
    for suffix in _TW_SUFFIXES:
        if text.endswith(suffix):
            code = text[: -len(suffix)]
            if not _TW_CODE_RE.match(code):
                return _reject(ReasonCode.BAD_SUFFIX)
            return _build(Market.TW, raw, text)
    return _reject(
        ReasonCode.AMBIGUOUS_SYMBOL if _TW_CODE_RE.match(text) else ReasonCode.BAD_SUFFIX
    )


_RESOLVERS = {
    Market.US: _resolve_us,
    Market.CN: _resolve_cn,
    Market.HK: _resolve_hk,
    Market.JP: _resolve_jp,
    Market.KR: _resolve_kr,
    Market.TW: _resolve_tw,
}


def resolve_instrument(market: str, raw_symbol: str) -> ContractResult:
    """Resolve ``raw_symbol`` inside ``market`` to a canonical identity.

    Pure: no I/O, idempotent. Any unknown input shape is a failure with
    machine reason codes; there is never a cross-market fallback.
    """
    if market is None or str(market).strip() == "":
        return _reject(ReasonCode.UNKNOWN_MARKET)
    market = str(market).strip()
    # Accept both canonical codes ("USStock") and friendly names ("US").
    aliases = {
        "US": Market.US, "USA": Market.US, "USSTOCK": Market.US,
        "CN": Market.CN, "CHINA": Market.CN, "A-SHARE": Market.CN, "CNSTOCK": Market.CN,
        "HK": Market.HK, "HONGKONG": Market.HK, "HKSTOCK": Market.HK,
        "JP": Market.JP, "JAPAN": Market.JP, "JPSTOCK": Market.JP,
        "KR": Market.KR, "KOREA": Market.KR, "KRSTOCK": Market.KR,
        "TW": Market.TW, "TAIWAN": Market.TW, "TWSTOCK": Market.TW,
    }
    market = aliases.get(market.upper(), market)
    if market not in Market.ALL:
        return _reject(ReasonCode.UNKNOWN_MARKET)

    if raw_symbol is None or str(raw_symbol).strip() == "":
        return _reject(ReasonCode.EMPTY_SYMBOL)

    return _RESOLVERS[market](str(raw_symbol))


def is_bare_ambiguous_code(market: str, raw_symbol: str) -> bool:
    """Diagnostic helper for tests and API 4xx copy: a JP/KR/TW code that is
    numerically well-formed but missing its mandatory exchange suffix."""
    if raw_symbol is None:
        return False
    text = str(raw_symbol).strip().upper()
    if market in (Market.JP, "JP"):
        return bool(_JP_CODE_RE.match(text))
    if market in (Market.KR, "KR"):
        return bool(_KR_CODE_RE.match(text))
    if market in (Market.TW, "TW"):
        return bool(_TW_CODE_RE.match(text))
    return False


__all__ = [
    "InstrumentIdentity",
    "resolve_instrument",
    "is_bare_ambiguous_code",
]
