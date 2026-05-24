"""F&O lot-size lookup from the bundled snapshot.

The CSV at `skills/openalgo/assets/LotSize.csv` is a quarterly snapshot
of SEBI/exchange lot sizes for the next three expiry months. Treat it
as a starting point — for an authoritative real-time value, call
`client.symbol(symbol=..., exchange='NFO')` and use the returned
`lotsize` and `freeze_qty`.

CSV columns: `Symbol`, `Lot Size (Apr 2026)`, `Lot Size (May 2026)`,
`Lot Size (Jun 2026)`. The CSV uses `-` for symbols no longer in F&O.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

_ASSET_DIR = Path(__file__).resolve().parent.parent / "assets"
_LOTSIZE_CSV = _ASSET_DIR / "LotSize.csv"


@lru_cache(maxsize=1)
def _load() -> pd.DataFrame:
    if not _LOTSIZE_CSV.exists():
        raise FileNotFoundError(
            f"Bundled lot-size CSV missing at {_LOTSIZE_CSV}. "
            "Reinstall the skill or refresh from "
            "/Users/openalgo/test-zerodha/openalgo/docs/prompt/LotSize.md."
        )
    df = pd.read_csv(_LOTSIZE_CSV)
    df["Symbol"] = df["Symbol"].str.upper()
    return df


def load_lot_sizes(month_col: str | None = None) -> pd.DataFrame:
    """Return the lot-size table.

    If `month_col` is given, returns a 2-column frame [Symbol, lot] with
    rows where the value is `-` filtered out and the lot column cast to int.
    """
    df = _load().copy()
    if month_col is None:
        return df
    col = next((c for c in df.columns if month_col.lower() in c.lower()), None)
    if col is None:
        raise KeyError(f"no lot-size column matching {month_col!r}; available: {list(df.columns)}")
    out = df[["Symbol", col]].rename(columns={col: "lot"})
    out = out[out["lot"] != "-"].copy()
    out["lot"] = out["lot"].astype(int)
    return out.reset_index(drop=True)


def get_lot(symbol: str, month_col: str | None = None) -> int:
    """Return lot size for a single F&O underlying.

    `month_col` is a substring match against the column header (e.g. "May",
    "Jun 2026"). Defaults to the first month column (apr 2026 in the
    bundled snapshot).
    """
    df = _load()
    cols = [c for c in df.columns if c != "Symbol"]
    col = cols[0] if month_col is None else next(
        (c for c in cols if month_col.lower() in c.lower()), None
    )
    if col is None:
        raise KeyError(f"no lot-size column matching {month_col!r}; available: {cols}")
    row = df[df["Symbol"] == symbol.upper()]
    if row.empty:
        raise LookupError(f"{symbol!r} not found in lot-size CSV")
    val = row.iloc[0][col]
    if val == "-":
        raise LookupError(f"{symbol!r} is no longer in F&O ({col} column is '-')")
    return int(val)


def nearest_lot(symbol: str, quantity: int, *, month_col: str | None = None) -> int:
    """Round `quantity` down to the nearest multiple of the lot size.

    Returns 0 if quantity is smaller than one lot — the caller decides
    whether to upsize to one lot or skip the trade.
    """
    lot = get_lot(symbol, month_col=month_col)
    return (quantity // lot) * lot


def validate_fno_lot(symbol: str, quantity: int, *, month_col: str | None = None) -> None:
    """Raise ValueError if `quantity` is not a positive multiple of the lot size."""
    lot = get_lot(symbol, month_col=month_col)
    if quantity <= 0 or quantity % lot != 0:
        raise ValueError(
            f"quantity {quantity} is not a positive multiple of {symbol} "
            f"lot size {lot}. Nearest valid: {(quantity // lot) * lot} or "
            f"{((quantity // lot) + 1) * lot}."
        )


def lot_for_via_symbol_api(client: Any, symbol: str, exchange: str = "NFO") -> int:
    """Authoritative lot size from the live broker master.

    Use this when the bundled CSV is stale or the symbol isn't listed in
    it (e.g. newly added contracts). Returns the SDK's `lotsize` field.
    """
    resp = client.symbol(symbol=symbol, exchange=exchange)
    if resp.get("status") != "success":
        raise LookupError(f"symbol lookup failed: {symbol}@{exchange} -> {resp}")
    return int(resp["data"]["lotsize"])
