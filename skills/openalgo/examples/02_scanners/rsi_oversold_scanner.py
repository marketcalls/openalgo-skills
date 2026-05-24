"""RSI oversold scanner — finds stocks with RSI(14) <= 30.

Daily timeframe. Useful for mean-reversion setups and dip-buying.

Output folder: openalgo_workspace/scanners/rsi_oversold/
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import talib as tl

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.alerts import fmt_scanner_results, notify
from scripts.openalgo_client import get_client
from scripts.scanner import Scanner

UNIVERSE = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "BAJFINANCE",
    "BHARTIARTL", "ITC", "HINDUNILVR", "LT", "AXISBANK", "ASIANPAINT", "MARUTI",
    "TITAN", "ULTRACEMCO", "NESTLEIND", "WIPRO", "TECHM", "ADANIENT", "ADANIPORTS",
    "JSWSTEEL", "TATASTEEL", "HINDALCO", "COALINDIA", "ONGC", "NTPC", "POWERGRID",
    "TATAMOTORS", "M&M", "EICHERMOT", "HEROMOTOCO", "BAJAJ-AUTO",
]

RSI_PERIOD = 14
OVERSOLD_THRESHOLD = 30
BEAR_TREND_FILTER = True   # only flag if 50DMA is below 200DMA (downtrending mean revert)

client = get_client()


def enrich_rsi(symbol: str, exchange: str, df: pd.DataFrame) -> dict[str, Any]:
    if len(df) < 220:
        return {"symbol": symbol, "exchange": exchange, "skip": "need_220_bars"}
    close = df["close"]
    rsi = pd.Series(tl.RSI(close.values, timeperiod=RSI_PERIOD), index=close.index)
    sma50 = pd.Series(tl.SMA(close.values, timeperiod=50), index=close.index)
    sma200 = pd.Series(tl.SMA(close.values, timeperiod=200), index=close.index)

    return {
        "symbol":  symbol,
        "ltp":     round(float(close.iloc[-1]), 2),
        "rsi":     round(float(rsi.iloc[-1]), 2),
        "rsi_5d_min": round(float(rsi.iloc[-5:].min()), 2),
        "sma50":   round(float(sma50.iloc[-1]), 2),
        "sma200":  round(float(sma200.iloc[-1]), 2),
        "trend":   "down" if sma50.iloc[-1] < sma200.iloc[-1] else "up",
    }


# ---- Scan ---------------------------------------------------------------

print(f"Scanning {len(UNIVERSE)} symbols for RSI({RSI_PERIOD}) <= {OVERSOLD_THRESHOLD}")
df = (
    Scanner(client)
    .add_many(UNIVERSE, exchange="NSE")
    .history_scan(interval="D", lookback_days=400, enrich=enrich_rsi, max_workers=6)
)
df = df[df.get("skip").isna() if "skip" in df.columns else True]

oversold = df[df["rsi"] <= OVERSOLD_THRESHOLD].copy()
if BEAR_TREND_FILTER:
    oversold = oversold[oversold["trend"] == "down"]

oversold = oversold.sort_values("rsi").reset_index(drop=True)
print(f"\n{len(oversold)} oversold matches:")
if not oversold.empty:
    print(oversold[["symbol", "ltp", "rsi", "rsi_5d_min", "sma50", "sma200", "trend"]].to_string(index=False))

# ---- Persist + alert ----------------------------------------------------

workdir = Path("openalgo_workspace/scanners/rsi_oversold")
workdir.mkdir(parents=True, exist_ok=True)
today = date.today().isoformat()
df.to_csv(workdir / f"all_{today}.csv", index=False)
oversold.to_csv(workdir / f"oversold_{today}.csv", index=False)

if not oversold.empty:
    notify(
        client,
        fmt_scanner_results(
            f"RSI({RSI_PERIOD}) <= {OVERSOLD_THRESHOLD}",
            oversold.head(10).to_dict("records"),
            fields=["symbol", "ltp", "rsi"], max_rows=10,
        ),
        via=("telegram",),
    )

print(f"\nSaved to {workdir}")
