"""Symbol construction and parsing for OpenAlgo's standardized symbology.

OpenAlgo uses one universal symbol grammar across 30+ brokers:

    Equity:   RELIANCE
    Futures:  NIFTY30DEC25FUT                  [base][DDMMMYY]FUT
    Options:  NIFTY30DEC2526200CE              [base][DDMMMYY][strike][CE/PE]

Strike supports decimals (`VEDL25APR24292.5CE`). Expiry codes are upper-
case three-letter months with two-digit day and two-digit year.

For lookups against the broker's master, prefer `client.symbol()` or
`client.search()` — they return the canonical lotsize / freeze_qty /
tick_size, which these string builders cannot know.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

_MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
_OPT_RE = re.compile(r"^([A-Z]+)(\d{2})([A-Z]{3})(\d{2})(\d+(?:\.\d+)?)(CE|PE)$")
_FUT_RE = re.compile(r"^([A-Z]+)(\d{2})([A-Z]{3})(\d{2})FUT$")


def fmt_expiry(d: date | datetime | str) -> str:
    """Format any date-like into OpenAlgo's DDMMMYY (e.g. `30DEC25`).

    Accepts:
        - date / datetime
        - ISO strings ("2025-12-30")
        - already-formatted strings ("30DEC25") — passed through after validation
    """
    if isinstance(d, str):
        s = d.strip().upper()
        if len(s) == 7 and s[2:5] in _MONTHS and s[:2].isdigit() and s[5:].isdigit():
            return s
        d = datetime.fromisoformat(s.lower())  # let it raise if malformed
    if isinstance(d, datetime):
        d = d.date()
    return f"{d.day:02d}{_MONTHS[d.month - 1]}{d.year % 100:02d}"


def build_fut_symbol(base: str, expiry: date | datetime | str) -> str:
    """`NIFTY` + `2025-12-30` -> `NIFTY30DEC25FUT`."""
    return f"{base.upper()}{fmt_expiry(expiry)}FUT"


def build_opt_symbol(
    base: str,
    expiry: date | datetime | str,
    strike: int | float,
    opt_type: str,
) -> str:
    """`NIFTY`, `2025-12-30`, `26200`, `CE` -> `NIFTY30DEC2526200CE`.

    `strike` is rendered as int when whole, else with a single decimal
    place (matches the OpenAlgo standard, e.g. `VEDL25APR24292.5CE`).
    """
    if opt_type.upper() not in {"CE", "PE"}:
        raise ValueError(f"opt_type must be CE or PE, got {opt_type!r}")
    if float(strike) == int(strike):
        strike_str = str(int(strike))
    else:
        strike_str = f"{float(strike):g}"
    return f"{base.upper()}{fmt_expiry(expiry)}{strike_str}{opt_type.upper()}"


def parse_opt_symbol(symbol: str) -> dict[str, Any]:
    """Inverse of `build_opt_symbol`. Returns parsed components or raises ValueError."""
    m = _OPT_RE.match(symbol.upper())
    if not m:
        raise ValueError(f"not an OpenAlgo options symbol: {symbol!r}")
    base, dd, mmm, yy, strike, ot = m.groups()
    expiry = date(2000 + int(yy), _MONTHS.index(mmm) + 1, int(dd))
    return {
        "base": base,
        "expiry": expiry,
        "strike": float(strike) if "." in strike else int(strike),
        "option_type": ot,
        "symbol": symbol.upper(),
    }


def parse_fut_symbol(symbol: str) -> dict[str, Any]:
    """Inverse of `build_fut_symbol`. Returns base + expiry or raises ValueError."""
    m = _FUT_RE.match(symbol.upper())
    if not m:
        raise ValueError(f"not an OpenAlgo futures symbol: {symbol!r}")
    base, dd, mmm, yy = m.groups()
    expiry = date(2000 + int(yy), _MONTHS.index(mmm) + 1, int(dd))
    return {"base": base, "expiry": expiry, "symbol": symbol.upper()}


def resolve_symbol(client: Any, symbol: str, exchange: str) -> dict[str, Any]:
    """Look up a symbol via the OpenAlgo `symbol` endpoint and return the data block.

    Raises if the symbol is unknown — better than letting downstream
    code silently miss lotsize/tick_size.
    """
    resp = client.symbol(symbol=symbol, exchange=exchange)
    if resp.get("status") != "success":
        raise LookupError(f"symbol lookup failed: {symbol}@{exchange} -> {resp}")
    return resp["data"]


def search_symbols(client: Any, query: str, exchange: str | None = None) -> list[dict[str, Any]]:
    """Wraps `client.search` and returns the list of matches (or [] on failure)."""
    kw = {"query": query}
    if exchange:
        kw["exchange"] = exchange
    resp = client.search(**kw)
    if resp.get("status") != "success":
        return []
    return resp.get("data", [])


# Common index quote-only underlyings, kept short by design — the full
# list lives in references/symbol-format.md. Use this for autocomplete
# in scanners and dashboards.
COMMON_INDICES = {
    "NSE_INDEX": [
        "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50",
        "INDIAVIX", "NIFTYIT", "NIFTYAUTO", "NIFTYPHARMA", "NIFTYFMCG",
        "NIFTYMETAL", "NIFTYREALTY", "NIFTYENERGY",
    ],
    "BSE_INDEX": ["SENSEX", "BANKEX", "SENSEX50"],
    "GLOBAL_INDEX": [
        "US30", "US500", "US100", "JAPAN225", "HANGSENG",
        "GERMANY40", "FRANCE40", "UK100", "GIFTNIFTY",
    ],
}
