"""Candlestick chart with EMA + Supertrend overlays, no weekend gaps.

Output folder: openalgo_workspace/charting/candlestick_<SYMBOL>/
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.openalgo_client import get_client
from scripts.plotting import candlestick_no_gaps
from scripts.ta_helpers import ema, supertrend

# ---- config ------------------------------------------------------------

SYMBOL = "RELIANCE"
EXCHANGE = "NSE"
INTERVAL = "D"
LOOKBACK_DAYS = 180

client = get_client()

# ---- Fetch -------------------------------------------------------------

today = date.today()
start = today - timedelta(days=LOOKBACK_DAYS)
print(f"Fetching {SYMBOL} {INTERVAL} candles from {start} to {today}")

df = client.history(
    symbol=SYMBOL, exchange=EXCHANGE,
    interval=INTERVAL,
    start_date=start.isoformat(),
    end_date=today.isoformat(),
)
if "timestamp" in df.columns:
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.set_index("timestamp")
else:
    df.index = pd.to_datetime(df.index)
if df.index.tz is not None:
    df.index = df.index.tz_convert(None)
df = df.sort_index()
print(f"  {len(df)} bars loaded")

# ---- Indicators --------------------------------------------------------

ema20 = ema(df["close"], 20)
ema50 = ema(df["close"], 50)
st_line, st_dir = supertrend(df["high"], df["low"], df["close"], period=10, multiplier=3.0)

# ---- Plot -------------------------------------------------------------

workdir = Path(f"openalgo_workspace/charting/candlestick_{SYMBOL.lower()}")
workdir.mkdir(parents=True, exist_ok=True)
out = workdir / f"chart_{today}.html"

candlestick_no_gaps(
    df,
    title=f"{SYMBOL} {INTERVAL}   EMA 20/50 + Supertrend(10, 3.0)",
    overlays={
        "EMA 20": ema20,
        "EMA 50": ema50,
        "Supertrend": st_line,
    },
    out=out,
)
df.to_csv(workdir / f"bars_{today}.csv")
print(f"\nSaved: {out}")
