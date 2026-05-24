"""20-day breakout scanner across a universe.

For each symbol:
  1. Fetch daily history (60 days lookback)
  2. Compute 20-day rolling max of close (excluding today)
  3. Flag if current LTP > rolling max
  4. Compute breakout strength (% above resistance)
  5. Add volume confirmation (today's vol > 1.5x 20d avg)

Output folder: openalgo_workspace/scanners/breakout/
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

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
]

LOOKBACK_DAYS = 60
BREAKOUT_WINDOW = 20
VOL_MULT = 1.5

client = get_client()


def enrich_breakout(symbol: str, exchange: str, df: pd.DataFrame) -> dict[str, Any]:
    """For one symbol's daily OHLCV history, compute breakout flags."""
    if len(df) < BREAKOUT_WINDOW + 1:
        return {"symbol": symbol, "exchange": exchange, "skip": "insufficient_history"}

    close = df["close"]
    high = df["high"]
    volume = df["volume"]

    # Resistance = max close over previous N bars (excluding today)
    resistance = high.iloc[:-1].rolling(BREAKOUT_WINDOW).max().iloc[-1]
    today_high = high.iloc[-1]
    today_close = close.iloc[-1]
    avg_vol_20 = volume.iloc[:-1].rolling(BREAKOUT_WINDOW).mean().iloc[-1]
    today_vol = volume.iloc[-1]

    breakout = today_close > resistance and today_high > resistance
    vol_confirm = avg_vol_20 > 0 and today_vol >= avg_vol_20 * VOL_MULT

    return {
        "symbol":        symbol,
        "exchange":      exchange,
        "today_close":   round(float(today_close), 2),
        "resistance":    round(float(resistance), 2),
        "breakout_pct":  round(float((today_close / resistance - 1) * 100), 2),
        "today_vol":     int(today_vol),
        "avg_vol_20":    int(avg_vol_20) if pd.notna(avg_vol_20) else 0,
        "vol_x":         round(float(today_vol / avg_vol_20), 2) if avg_vol_20 else 0.0,
        "breakout":      bool(breakout),
        "vol_confirm":   bool(vol_confirm),
    }


# ---- Run scan -----------------------------------------------------------

print(f"Scanning {len(UNIVERSE)} symbols for {BREAKOUT_WINDOW}-day breakout + volume confirmation")
df = (
    Scanner(client)
    .add_many(UNIVERSE, exchange="NSE")
    .history_scan(
        interval="D",
        lookback_days=LOOKBACK_DAYS,
        enrich=enrich_breakout,
        max_workers=6,
    )
)

# Filter to confirmed breakouts
hits = df[(df.get("breakout", False)) & (df.get("vol_confirm", False))].copy()
hits = hits.sort_values("breakout_pct", ascending=False).reset_index(drop=True)

print(f"\n{len(hits)} confirmed breakouts:")
if not hits.empty:
    print(hits[["symbol", "today_close", "resistance", "breakout_pct", "vol_x"]].to_string(index=False))

# ---- Persist + alert ----------------------------------------------------

workdir = Path("openalgo_workspace/scanners/breakout")
workdir.mkdir(parents=True, exist_ok=True)
today = date.today().isoformat()
df.to_csv(workdir / f"all_{today}.csv", index=False)
hits.to_csv(workdir / f"hits_{today}.csv", index=False)

if not hits.empty:
    summary = fmt_scanner_results(
        f"{BREAKOUT_WINDOW}-Day Breakout + Volume Confirm",
        hits.head(10).to_dict("records"),
        fields=["symbol", "today_close", "resistance", "breakout_pct", "vol_x"],
        max_rows=10,
    )
    notify(client, summary, via=("telegram",))
    print("\n" + summary)

print(f"\nSaved to {workdir}")
