"""Multi-symbol screener-style backtest using direct DuckDB.

Pulls daily close for an entire universe via `load_multi` (one query,
all symbols), runs an EMA crossover on each independently, aggregates
results into a ranked DataFrame.

Use this template to evaluate a strategy across a basket and identify
which symbols it works best on.

Output folder: openalgo_workspace/backtesting/screener_<strategy>/
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import vectorbt as vbt

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.duckdb_data import load_multi
from scripts.fees import fees_pct, fixed_fees_inr
from scripts.openalgo_client import historify_duckdb_path
from scripts.ta_helpers import clean_signals, ema

UNIVERSE = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "BAJFINANCE",
    "BHARTIARTL", "ITC", "HINDUNILVR", "LT", "AXISBANK", "ASIANPAINT", "MARUTI",
    "TITAN", "ULTRACEMCO", "NESTLEIND", "WIPRO", "TECHM", "ADANIENT",
]
LOOKBACK_YEARS = 5
INIT_CASH = 1_000_000
ALLOCATION = 0.75
FAST = 10
SLOW = 20

if not historify_duckdb_path():
    raise SystemExit(
        "This screener requires HISTORIFY_DUCKDB_PATH in .env.\n"
        "Set it to your local Historify duckdb file."
    )

end = date.today()
start = end - timedelta(days=365 * LOOKBACK_YEARS)

print(f"Loading {len(UNIVERSE)} symbols  {start} -> {end}")
close = load_multi(UNIVERSE, exchange="NSE", start=start, end=end, field="close")
print(f"  wide DataFrame: {close.shape}")

rows = []
for sym in UNIVERSE:
    if sym not in close.columns:
        continue
    s = close[sym].dropna()
    if len(s) < SLOW + 10:
        continue

    ema_f = ema(s, FAST)
    ema_s = ema(s, SLOW)
    buy_raw = (ema_f > ema_s) & (ema_f.shift(1) <= ema_s.shift(1))
    sell_raw = (ema_f < ema_s) & (ema_f.shift(1) >= ema_s.shift(1))
    entries, exits = clean_signals(buy_raw, sell_raw)

    pf = vbt.Portfolio.from_signals(
        s, entries, exits,
        init_cash=INIT_CASH, size=ALLOCATION, size_type="percent",
        fees=fees_pct("equity_delivery"), fixed_fees=fixed_fees_inr("equity_delivery"),
        direction="longonly", min_size=1, size_granularity=1, freq="1D",
    )
    rows.append({
        "symbol":   sym,
        "total_pct": pf.total_return() * 100,
        "sharpe":   pf.sharpe_ratio(),
        "max_dd":   pf.max_drawdown() * 100,
        "trades":   pf.trades.count(),
        "win_rate": pf.trades.win_rate() * 100,
        "pf":       pf.trades.profit_factor(),
    })

results = pd.DataFrame(rows).sort_values("sharpe", ascending=False)
print("\n--- Top 5 by Sharpe ---")
print(results.head(5).to_string(index=False))
print("\n--- Bottom 5 by Sharpe ---")
print(results.tail(5).to_string(index=False))

workdir = Path("openalgo_workspace/backtesting/screener_ema_crossover")
workdir.mkdir(parents=True, exist_ok=True)
results.to_csv(workdir / f"results_{end}.csv", index=False)
print(f"\nSaved {len(results)} rows to {workdir}")
