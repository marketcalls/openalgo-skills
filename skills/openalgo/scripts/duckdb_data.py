"""Direct DuckDB access to the OpenAlgo Historify market-data store.

The Historify DuckDB file (default location `<openalgo>/db/historify.duckdb`)
stores intraday and daily OHLCV in a single `market_data` table keyed by
`symbol`, `exchange`, and epoch `timestamp`. Reading it directly is
considerably faster than `client.history(..., source='db')` when:

- you need many symbols at once
- you need a long lookback window (years)
- you need 1-minute bars and don't want to chunk

For a single symbol / single day, the REST `history` endpoint is fine
and saves the user from managing a file path.

Schema reference:
    market_data(
        symbol         VARCHAR,
        exchange       VARCHAR,
        timestamp      BIGINT,        -- epoch seconds, IST-anchored
        open, high, low, close   DOUBLE,
        volume         BIGINT
    )

If the user's local install uses the legacy custom schema
(`ohlcv` table with date + time columns), the vectorbt-backtesting-skills
package has a fallback loader — link from
[references/duckdb-historify.md](../references/duckdb-historify.md).
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from .openalgo_client import historify_duckdb_path


_IST = "Asia/Kolkata"


def _resolve_path(path: str | Path | None) -> Path:
    p = path or historify_duckdb_path()
    if not p:
        raise RuntimeError(
            "HISTORIFY_DUCKDB_PATH is not set and no path was passed. "
            "Set it in .env to e.g. /srv/openalgo/db/historify.duckdb."
        )
    p = Path(p)
    if not p.exists():
        raise FileNotFoundError(f"Historify DuckDB not found at {p}")
    return p


def _connect(path: str | Path | None = None) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(_resolve_path(path)), read_only=True)


def _to_epoch(dt: date | datetime | str) -> int:
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    if isinstance(dt, date) and not isinstance(dt, datetime):
        dt = datetime.combine(dt, datetime.min.time())
    return int(pd.Timestamp(dt, tz=_IST).timestamp())


def load_ohlcv(
    symbol: str,
    exchange: str,
    start: date | datetime | str,
    end: date | datetime | str,
    *,
    db_path: str | Path | None = None,
    tz_naive: bool = True,
) -> pd.DataFrame:
    """Load a single-symbol OHLCV DataFrame from Historify.

    Returns a DataFrame indexed by tz-naive IST timestamp (matching the
    vectorbt skill's convention so it can be fed directly into
    `vbt.Portfolio.from_signals`). Pass `tz_naive=False` to keep
    timezone-aware timestamps.

    Columns: open, high, low, close, volume.
    """
    sql = """
        SELECT
            timestamp,
            open, high, low, close, volume
        FROM market_data
        WHERE symbol = ?
          AND exchange = ?
          AND timestamp >= ?
          AND timestamp <  ?
        ORDER BY timestamp
    """
    start_ep = _to_epoch(start)
    end_ep = _to_epoch(end)
    con = _connect(db_path)
    try:
        df = con.execute(sql, [symbol.upper(), exchange.upper(), start_ep, end_ep]).fetchdf()
    finally:
        con.close()

    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["timestamp"], unit="s", utc=True).dt.tz_convert(_IST)
    if tz_naive:
        df["ts"] = df["ts"].dt.tz_localize(None)
    df = df.set_index("ts").drop(columns="timestamp")
    df.index.name = "timestamp"
    return df


def load_multi(
    symbols: list[str],
    exchange: str,
    start: date | datetime | str,
    end: date | datetime | str,
    *,
    field: str = "close",
    db_path: str | Path | None = None,
    tz_naive: bool = True,
) -> pd.DataFrame:
    """Load one field across many symbols as a wide DataFrame.

    Common use: pull `close` across NIFTY 50 constituents in one query
    for a heatmap or breadth scanner. Symbols missing data in the
    window become all-NaN columns.
    """
    if field not in {"open", "high", "low", "close", "volume"}:
        raise ValueError(f"field must be one of OHLCV columns, got {field!r}")
    placeholders = ",".join("?" * len(symbols))
    sql = f"""
        SELECT
            symbol,
            timestamp,
            {field} AS val
        FROM market_data
        WHERE exchange = ?
          AND symbol IN ({placeholders})
          AND timestamp >= ?
          AND timestamp <  ?
        ORDER BY timestamp
    """
    params = [exchange.upper(), *[s.upper() for s in symbols], _to_epoch(start), _to_epoch(end)]
    con = _connect(db_path)
    try:
        df = con.execute(sql, params).fetchdf()
    finally:
        con.close()

    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["timestamp"], unit="s", utc=True).dt.tz_convert(_IST)
    if tz_naive:
        df["ts"] = df["ts"].dt.tz_localize(None)
    wide = df.pivot(index="ts", columns="symbol", values="val")
    wide.index.name = "timestamp"
    return wide.reindex(columns=[s.upper() for s in symbols])


def resample_ist(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample 1-minute OHLCV to a higher TF, aligned to NSE 09:15 IST.

    The `origin=` and `offset=` arguments anchor the bars so a `5min`
    resample starts at 09:15, 09:20, 09:25 ... rather than 09:00, 09:05.
    """
    needed = {"open", "high", "low", "close", "volume"}
    missing = needed - set(df.columns)
    if missing:
        raise ValueError(f"resample expects OHLCV columns, missing: {missing}")
    return (
        df.resample(rule, origin="start_day", offset="9h15min", label="right", closed="right")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna()
    )


def list_symbols(exchange: str, *, db_path: str | Path | None = None) -> list[str]:
    """All distinct symbols stored for an exchange — useful for scanner setup."""
    con = _connect(db_path)
    try:
        rows = con.execute(
            "SELECT DISTINCT symbol FROM market_data WHERE exchange = ? ORDER BY symbol",
            [exchange.upper()],
        ).fetchall()
    finally:
        con.close()
    return [r[0] for r in rows]


def date_range(symbol: str, exchange: str, *, db_path: str | Path | None = None) -> dict[str, Any]:
    """Earliest / latest timestamp stored for a symbol — sanity check before backtesting."""
    con = _connect(db_path)
    try:
        row = con.execute(
            """
            SELECT MIN(timestamp), MAX(timestamp), COUNT(*)
            FROM market_data WHERE symbol = ? AND exchange = ?
            """,
            [symbol.upper(), exchange.upper()],
        ).fetchone()
    finally:
        con.close()
    if not row or row[0] is None:
        return {"symbol": symbol, "exchange": exchange, "rows": 0}
    return {
        "symbol": symbol,
        "exchange": exchange,
        "rows": int(row[2]),
        "first": pd.Timestamp(row[0], unit="s", tz=_IST),
        "last": pd.Timestamp(row[1], unit="s", tz=_IST),
    }
