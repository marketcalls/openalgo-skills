"""Multi-symbol scanning pipeline.

A `Scanner` collects a universe (list of {symbol, exchange} dicts),
fetches quotes in batch via `multiquotes`, then runs a chain of
filter / enrich callables to produce a final DataFrame.

Designed for daily-run-once scans (gainers, breakouts, OI deltas) but
the same primitives work intraday — just re-run on a timer.

Two scan styles are supported:

1. **Quote-only**: fast (single REST call) — use for live LTP filters
   like "% change > 2", "volume > avg_volume * 3", "VWAP cross".
2. **Quote + history**: fetches OHLCV for each shortlisted symbol and
   computes indicator filters (RSI < 30, close > 20-day high, etc.).
   Slower — uses `concurrent.futures` for parallel REST.
"""

from __future__ import annotations

import concurrent.futures
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import pandas as pd

QuoteFilter = Callable[[pd.DataFrame], pd.DataFrame]


@dataclass
class Scanner:
    """Stateful scanner. Build the universe, register filters, run."""

    client: Any
    universe: list[dict[str, str]] = field(default_factory=list)
    filters: list[QuoteFilter] = field(default_factory=list)

    # ---- universe construction ----

    def add(self, symbol: str, exchange: str = "NSE") -> "Scanner":
        self.universe.append({"symbol": symbol.upper(), "exchange": exchange.upper()})
        return self

    def add_many(self, symbols: list[str], exchange: str = "NSE") -> "Scanner":
        for s in symbols:
            self.add(s, exchange)
        return self

    def with_filter(self, fn: QuoteFilter) -> "Scanner":
        self.filters.append(fn)
        return self

    # ---- runs ----

    def quote_scan(self) -> pd.DataFrame:
        """Fetch `multiquotes` and apply all registered filters in order."""
        if not self.universe:
            raise RuntimeError("scanner universe is empty; call .add() first")
        resp = self.client.multiquotes(symbols=self.universe)
        if resp.get("status") != "success":
            raise RuntimeError(f"multiquotes failed: {resp}")
        rows = []
        for item in resp.get("results", []):
            data = item.get("data", {}) or {}
            row = {
                "symbol": item.get("symbol"),
                "exchange": item.get("exchange"),
                "ltp": data.get("ltp"),
                "open": data.get("open"),
                "high": data.get("high"),
                "low": data.get("low"),
                "prev_close": data.get("prev_close"),
                "volume": data.get("volume"),
                "bid": data.get("bid"),
                "ask": data.get("ask"),
                "oi": data.get("oi"),
            }
            if row["prev_close"] and row["ltp"]:
                row["pct_change"] = (row["ltp"] / row["prev_close"] - 1) * 100
            rows.append(row)
        df = pd.DataFrame(rows)
        for f in self.filters:
            df = f(df)
        return df.reset_index(drop=True)

    def history_scan(
        self,
        *,
        interval: str = "D",
        lookback_days: int = 60,
        enrich: Callable[[str, str, pd.DataFrame], dict[str, Any]],
        max_workers: int = 8,
    ) -> pd.DataFrame:
        """Pull history for each symbol in the universe and apply `enrich`.

        `enrich(symbol, exchange, ohlcv_df)` returns a flat dict that
        becomes one row of the output. Run in parallel — keep the
        function pure (no shared state) or use locks.
        """
        end = date.today()
        start = end - timedelta(days=lookback_days)

        def _one(item: dict[str, str]) -> dict[str, Any] | None:
            try:
                df = self.client.history(
                    symbol=item["symbol"],
                    exchange=item["exchange"],
                    interval=interval,
                    start_date=start.isoformat(),
                    end_date=end.isoformat(),
                )
            except Exception as exc:
                return {"symbol": item["symbol"], "error": repr(exc)}
            if isinstance(df, dict) or df is None or len(df) == 0:
                return None
            try:
                if "timestamp" in df.columns:
                    df = df.set_index(pd.to_datetime(df["timestamp"]).dt.tz_localize(None))
                else:
                    df.index = pd.to_datetime(df.index).tz_localize(None)
                row = enrich(item["symbol"], item["exchange"], df)
                row.setdefault("symbol", item["symbol"])
                row.setdefault("exchange", item["exchange"])
                return row
            except Exception as exc:
                return {"symbol": item["symbol"], "error": repr(exc)}

        rows: list[dict[str, Any]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            for res in pool.map(_one, self.universe):
                if res is not None:
                    rows.append(res)
                # respect API rate limit (50/s general) — small pause every 10
                if len(rows) % 10 == 0:
                    time.sleep(0.2)
        return pd.DataFrame(rows)


# Common reusable filters --------------------------------------------------


def gainers(threshold_pct: float = 1.0) -> QuoteFilter:
    return lambda df: df[df["pct_change"] >= threshold_pct].sort_values("pct_change", ascending=False)


def losers(threshold_pct: float = 1.0) -> QuoteFilter:
    return lambda df: df[df["pct_change"] <= -threshold_pct].sort_values("pct_change")


def above_open(margin_pct: float = 0.0) -> QuoteFilter:
    def _f(df: pd.DataFrame) -> pd.DataFrame:
        return df[df["ltp"] >= df["open"] * (1 + margin_pct / 100)]
    return _f


def below_open(margin_pct: float = 0.0) -> QuoteFilter:
    def _f(df: pd.DataFrame) -> pd.DataFrame:
        return df[df["ltp"] <= df["open"] * (1 - margin_pct / 100)]
    return _f


def volume_surge(multiplier: float, *, on: str = "volume") -> QuoteFilter:
    """Keep rows where current `volume` exceeds `multiplier` x median of universe.

    Lightweight cross-sectional proxy when no per-symbol historical
    average is available in the multiquotes response.
    """
    def _f(df: pd.DataFrame) -> pd.DataFrame:
        median = df[on].median()
        if not median:
            return df
        return df[df[on] >= median * multiplier]
    return _f


def gap_up(min_pct: float = 0.5) -> QuoteFilter:
    def _f(df: pd.DataFrame) -> pd.DataFrame:
        gap = (df["open"] / df["prev_close"] - 1) * 100
        return df.assign(gap_pct=gap)[gap >= min_pct].sort_values("gap_pct", ascending=False)
    return _f


def gap_down(min_pct: float = 0.5) -> QuoteFilter:
    def _f(df: pd.DataFrame) -> pd.DataFrame:
        gap = (df["open"] / df["prev_close"] - 1) * 100
        return df.assign(gap_pct=gap)[gap <= -min_pct].sort_values("gap_pct")
    return _f
