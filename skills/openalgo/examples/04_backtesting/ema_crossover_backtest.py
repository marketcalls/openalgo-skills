"""EMA(10) / EMA(20) crossover backtest with realistic Indian-market costs.

Loads OHLCV either via `client.history` or direct DuckDB (Historify).
Uses TA-Lib for EMA, openalgo.ta.exrem to clean signals, vectorbt for
portfolio simulation. Benchmarks against NIFTY 50.

Output folder: openalgo_workspace/backtesting/ema_crossover_<SYMBOL>/
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import vectorbt as vbt

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.fees import fees_pct, fixed_fees_inr
from scripts.openalgo_client import get_client, historify_duckdb_path
from scripts.ta_helpers import clean_signals, ema

# ---- config ------------------------------------------------------------

SYMBOL = "SBIN"
EXCHANGE = "NSE"
INTERVAL = "D"
LOOKBACK_YEARS = 3
INIT_CASH = 1_000_000
ALLOCATION = 0.75
FAST = 10
SLOW = 20

BENCHMARK = ("NIFTY", "NSE_INDEX")

USE_DUCKDB = bool(historify_duckdb_path())     # auto-detect

client = get_client()

# ---- Load data ---------------------------------------------------------

end = date.today()
start = end - timedelta(days=365 * LOOKBACK_YEARS)

def load(symbol: str, exchange: str) -> pd.DataFrame:
    if USE_DUCKDB:
        from scripts.duckdb_data import load_ohlcv
        return load_ohlcv(symbol, exchange, start, end)
    df = client.history(
        symbol=symbol, exchange=exchange, interval=INTERVAL,
        start_date=start.isoformat(), end_date=end.isoformat(),
    )
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp")
    else:
        df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_convert(None)
    return df.sort_index()

print(f"Loading {SYMBOL} ({EXCHANGE}) from {start} to {end}   (source={'DuckDB' if USE_DUCKDB else 'REST'})")
df = load(SYMBOL, EXCHANGE)
print(f"  {len(df)} bars")

close = df["close"]

# ---- Signals -----------------------------------------------------------

ema_fast = ema(close, FAST)
ema_slow = ema(close, SLOW)

buy_raw = (ema_fast > ema_slow) & (ema_fast.shift(1) <= ema_slow.shift(1))
sell_raw = (ema_fast < ema_slow) & (ema_fast.shift(1) >= ema_slow.shift(1))
entries, exits = clean_signals(buy_raw, sell_raw)

print(f"  Entries: {entries.sum()}    Exits: {exits.sum()}")

# ---- Backtest ----------------------------------------------------------

pf = vbt.Portfolio.from_signals(
    close, entries, exits,
    init_cash=INIT_CASH, size=ALLOCATION, size_type="percent",
    fees=fees_pct("equity_delivery"), fixed_fees=fixed_fees_inr("equity_delivery"),
    direction="longonly", min_size=1, size_granularity=1, freq="1D",
)

# ---- Benchmark ---------------------------------------------------------

df_bench = load(*BENCHMARK)
bench_close = df_bench["close"].reindex(close.index).ffill().bfill()
pf_bench = vbt.Portfolio.from_holding(
    bench_close, init_cash=INIT_CASH,
    fees=fees_pct("equity_delivery"), freq="1D",
)

# ---- Report ------------------------------------------------------------

print(f"\n--- {SYMBOL} EMA({FAST}/{SLOW}) Backtest ---")
print(pf.stats())

comparison = pd.DataFrame({
    "Strategy": [
        f"{pf.total_return() * 100:.2f}%",
        f"{pf.sharpe_ratio():.2f}",
        f"{pf.sortino_ratio():.2f}",
        f"{pf.max_drawdown() * 100:.2f}%",
        f"{pf.trades.win_rate() * 100:.1f}%",
        f"{pf.trades.count()}",
        f"{pf.trades.profit_factor():.2f}",
    ],
    f"Benchmark ({BENCHMARK[0]})": [
        f"{pf_bench.total_return() * 100:.2f}%",
        f"{pf_bench.sharpe_ratio():.2f}",
        f"{pf_bench.sortino_ratio():.2f}",
        f"{pf_bench.max_drawdown() * 100:.2f}%",
        "-", "-", "-",
    ],
}, index=["Total Return", "Sharpe Ratio", "Sortino Ratio", "Max Drawdown",
          "Win Rate", "Total Trades", "Profit Factor"])
print("\n", comparison.to_string())

# ---- Plain-language summary --------------------------------------------

print(f"\nIn plain English:")
print(f"* You started with Rs {INIT_CASH:,}.")
print(f"* The strategy ended at Rs {pf.value().iloc[-1]:,.0f}  "
      f"(return {pf.total_return() * 100:+.2f}%).")
print(f"* Buy-and-hold {BENCHMARK[0]} would have ended at "
      f"Rs {pf_bench.value().iloc[-1]:,.0f}  ({pf_bench.total_return() * 100:+.2f}%).")
print(f"* Worst temporary loss was Rs {abs(pf.max_drawdown()) * INIT_CASH:,.0f} "
      f"({pf.max_drawdown() * 100:.2f}%).")
print(f"* {pf.trades.count()} trades; you won {pf.trades.win_rate() * 100:.1f}% of them.")

# ---- Save --------------------------------------------------------------

workdir = Path(f"openalgo_workspace/backtesting/ema_crossover_{SYMBOL.lower()}")
workdir.mkdir(parents=True, exist_ok=True)

pf.positions.records_readable.to_csv(workdir / "trades.csv", index=False)
fig = pf.plot(subplots=["value", "underwater", "cum_returns"], template="plotly_dark")
fig.write_html(str(workdir / "equity.html"), include_plotlyjs="cdn")
print(f"\nSaved trades + equity to {workdir}")
