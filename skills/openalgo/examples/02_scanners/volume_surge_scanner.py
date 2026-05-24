"""Volume-surge scanner — symbols trading at > N x their 20-day average.

For each symbol:
  1. Pull 30 days of daily history
  2. Compute 20-day average volume (excluding today)
  3. Flag if today's volume >= average * threshold
  4. Optional: filter to symbols making new 20d high

Output folder: openalgo_workspace/scanners/volume_surge/
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

VOLUME_MULTIPLIER = 3.0
AVG_PERIOD = 20
REQUIRE_NEW_HIGH = False

client = get_client()


def enrich_volume(symbol: str, exchange: str, df: pd.DataFrame) -> dict[str, Any]:
    if len(df) < AVG_PERIOD + 1:
        return {"symbol": symbol, "exchange": exchange, "skip": "need_history"}
    avg = df["volume"].iloc[-AVG_PERIOD - 1:-1].mean()
    today_vol = df["volume"].iloc[-1]
    today_close = df["close"].iloc[-1]
    new_high = today_close >= df["high"].iloc[-AVG_PERIOD - 1:-1].max()
    return {
        "symbol": symbol,
        "ltp":     round(float(today_close), 2),
        "today_vol":  int(today_vol),
        "avg_vol":    int(avg) if pd.notna(avg) else 0,
        "vol_x":      round(float(today_vol / avg), 2) if avg else 0.0,
        "pct_change": round(float((today_close / df["close"].iloc[-2] - 1) * 100), 2)
                      if len(df) > 1 else 0.0,
        "new_high":   bool(new_high),
    }


# ---- Scan ---------------------------------------------------------------

print(f"Scanning {len(UNIVERSE)} symbols for vol >= {VOLUME_MULTIPLIER}x 20-day avg")
df = (
    Scanner(client)
    .add_many(UNIVERSE, exchange="NSE")
    .history_scan(interval="D", lookback_days=AVG_PERIOD + 10,
                  enrich=enrich_volume, max_workers=6)
)

hits = df[df.get("vol_x", 0) >= VOLUME_MULTIPLIER].copy()
if REQUIRE_NEW_HIGH:
    hits = hits[hits["new_high"]]
hits = hits.sort_values("vol_x", ascending=False).reset_index(drop=True)

print(f"\n{len(hits)} surge matches:")
if not hits.empty:
    print(hits[["symbol", "ltp", "pct_change", "vol_x", "new_high"]].to_string(index=False))

# ---- Persist + alert ---------------------------------------------------

workdir = Path("openalgo_workspace/scanners/volume_surge")
workdir.mkdir(parents=True, exist_ok=True)
today = date.today().isoformat()
df.to_csv(workdir / f"all_{today}.csv", index=False)
hits.to_csv(workdir / f"hits_{today}.csv", index=False)

if not hits.empty:
    notify(
        client,
        fmt_scanner_results(
            f"Volume surge >= {VOLUME_MULTIPLIER}x 20d avg",
            hits.head(10).to_dict("records"),
            fields=["symbol", "ltp", "pct_change", "vol_x", "new_high"], max_rows=10,
        ),
        via=("telegram",),
    )

print(f"\nSaved to {workdir}")
