"""Supertrend(10, 3.0) trend-following backtest.

Same realistic-cost + NIFTY-benchmark recipe as the EMA crossover
example, applied to Supertrend signals on daily bars.

Output folder: openalgo_workspace/backtesting/supertrend_<SYMBOL>/
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
from scripts.ta_helpers import clean_signals, supertrend

# ---- config ------------------------------------------------------------

SYMBOL = "RELIANCE"
EXCHANGE = "NSE"
INTERVAL = "D"
LOOKBACK_YEARS = 3
INIT_CASH = 1_000_000
ALLOCATION = 0.75
ATR_PERIOD = 10
ATR_MULT = 3.0

BENCHMARK = ("NIFTY", "NSE_INDEX")

USE_DUCKDB = bool(historify_duckdb_path())
client = get_client()

# ---- Load --------------------------------------------------------------

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

print(f"Loading {SYMBOL} {EXCHANGE} from {start} to {end}")
df = load(SYMBOL, EXCHANGE)
print(f"  {len(df)} bars")

# ---- Supertrend signals ------------------------------------------------

st_line, st_dir = supertrend(df["high"], df["low"], df["close"],
                              period=ATR_PERIOD, multiplier=ATR_MULT)
prev_dir = st_dir.shift(1)
buy_raw  = (st_dir > 0) & (prev_dir <= 0)
sell_raw = (st_dir < 0) & (prev_dir >= 0)
entries, exits = clean_signals(buy_raw, sell_raw)
print(f"  Entries: {entries.sum()}    Exits: {exits.sum()}")

# ---- Backtest ----------------------------------------------------------

pf = vbt.Portfolio.from_signals(
    df["close"], entries, exits,
    init_cash=INIT_CASH, size=ALLOCATION, size_type="percent",
    fees=fees_pct("equity_delivery"), fixed_fees=fixed_fees_inr("equity_delivery"),
    direction="longonly", min_size=1, size_granularity=1, freq="1D",
)

bench = load(*BENCHMARK)
bench_close = bench["close"].reindex(df.index).ffill().bfill()
pf_bench = vbt.Portfolio.from_holding(
    bench_close, init_cash=INIT_CASH, fees=fees_pct("equity_delivery"), freq="1D",
)

# ---- Report ------------------------------------------------------------

print(f"\n--- {SYMBOL} Supertrend({ATR_PERIOD}, {ATR_MULT}) Backtest ---")
comparison = pd.DataFrame({
    "Strategy": [
        f"{pf.total_return() * 100:.2f}%", f"{pf.sharpe_ratio():.2f}",
        f"{pf.sortino_ratio():.2f}", f"{pf.max_drawdown() * 100:.2f}%",
        f"{pf.trades.win_rate() * 100:.1f}%", f"{pf.trades.count()}",
        f"{pf.trades.profit_factor():.2f}",
    ],
    f"Benchmark ({BENCHMARK[0]})": [
        f"{pf_bench.total_return() * 100:.2f}%", f"{pf_bench.sharpe_ratio():.2f}",
        f"{pf_bench.sortino_ratio():.2f}", f"{pf_bench.max_drawdown() * 100:.2f}%",
        "-", "-", "-",
    ],
}, index=["Total Return", "Sharpe", "Sortino", "Max DD",
          "Win Rate", "Total Trades", "Profit Factor"])
print(comparison.to_string())

# ---- Save --------------------------------------------------------------

workdir = Path(f"openalgo_workspace/backtesting/supertrend_{SYMBOL.lower()}")
workdir.mkdir(parents=True, exist_ok=True)
pf.positions.records_readable.to_csv(workdir / "trades.csv", index=False)
fig = pf.plot(subplots=["value", "underwater", "cum_returns"], template="plotly_dark")
fig.write_html(str(workdir / "equity.html"), include_plotlyjs="cdn")
print(f"\nSaved to {workdir}")
