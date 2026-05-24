"""Year-to-date % change heatmap.

For each symbol: pull daily history from Jan 1 to today, compute YTD
return, render a Plotly treemap colored by performance.

Output folder: openalgo_workspace/visualization/ytd_heatmap/
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.express as px

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.openalgo_client import get_client

UNIVERSE = [
    ("RELIANCE", "Energy"), ("TCS", "IT"), ("INFY", "IT"), ("WIPRO", "IT"),
    ("HCLTECH", "IT"), ("HDFCBANK", "Banking"), ("ICICIBANK", "Banking"),
    ("AXISBANK", "Banking"), ("KOTAKBANK", "Banking"), ("SBIN", "Banking"),
    ("INDUSINDBK", "Banking"), ("BAJFINANCE", "Finance"), ("BAJAJFINSV", "Finance"),
    ("HDFCLIFE", "Finance"), ("SBILIFE", "Finance"), ("MARUTI", "Auto"),
    ("M&M", "Auto"), ("TATAMOTORS", "Auto"), ("BAJAJ-AUTO", "Auto"),
    ("EICHERMOT", "Auto"), ("HEROMOTOCO", "Auto"), ("ITC", "Consumer"),
    ("HINDUNILVR", "Consumer"), ("NESTLEIND", "Consumer"), ("TITAN", "Consumer"),
    ("TATASTEEL", "Metals"), ("JSWSTEEL", "Metals"), ("HINDALCO", "Metals"),
    ("ONGC", "Energy"), ("COALINDIA", "Energy"), ("NTPC", "Power"),
    ("POWERGRID", "Power"), ("LT", "Infra"), ("ULTRACEMCO", "Materials"),
    ("ASIANPAINT", "Consumer"), ("BHARTIARTL", "Telecom"), ("APOLLOHOSP", "Pharma"),
    ("SUNPHARMA", "Pharma"), ("CIPLA", "Pharma"), ("DRREDDY", "Pharma"),
]

client = get_client()

today = date.today()
start = date(today.year, 1, 1)

rows = []
for symbol, sector in UNIVERSE:
    try:
        df = client.history(
            symbol=symbol, exchange="NSE", interval="D",
            start_date=start.isoformat(), end_date=today.isoformat(),
        )
        if df is None or len(df) < 2:
            continue
        first_close = float(df["close"].iloc[0])
        last_close = float(df["close"].iloc[-1])
        pct = (last_close / first_close - 1) * 100
        rows.append({
            "symbol":  symbol,
            "sector":  sector,
            "start":   first_close,
            "current": last_close,
            "ytd_pct": pct,
            "size":    last_close,
        })
        print(f"  {symbol:<10} {pct:+7.2f}%")
    except Exception as exc:
        print(f"  {symbol:<10} skipped ({exc})")
        continue

df = pd.DataFrame(rows)

# ---- Treemap -----------------------------------------------------------

fig = px.treemap(
    df,
    path=["sector", "symbol"],
    values="size",
    color="ytd_pct",
    color_continuous_scale="RdYlGn",
    color_continuous_midpoint=0,
    title=f"YTD Returns {start.year} (through {today})",
)
fig.update_layout(template="plotly_dark", height=750)
fig.update_traces(textinfo="label+percent parent")

# ---- Save -------------------------------------------------------------

workdir = Path("openalgo_workspace/visualization/ytd_heatmap")
workdir.mkdir(parents=True, exist_ok=True)
out = workdir / f"ytd_{today}.html"
fig.write_html(str(out), include_plotlyjs="cdn")
df.to_csv(workdir / f"data_{today}.csv", index=False)
print(f"\nSaved: {out}")
fig.show()
