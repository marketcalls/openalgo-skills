"""Sector heatmap of NIFTY 50 — % change of each constituent on one chart.

Single `multiquotes` call + a Plotly treemap-style heatmap.

Output folder: openalgo_workspace/visualization/sector_heatmap/
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

NIFTY50 = [
    ("ADANIENT", "Energy"), ("ADANIPORTS", "Infra"), ("APOLLOHOSP", "Pharma"),
    ("ASIANPAINT", "Consumer"), ("AXISBANK", "Banking"), ("BAJAJ-AUTO", "Auto"),
    ("BAJFINANCE", "Finance"), ("BAJAJFINSV", "Finance"), ("BEL", "Defence"),
    ("BHARTIARTL", "Telecom"), ("CIPLA", "Pharma"), ("COALINDIA", "Energy"),
    ("DRREDDY", "Pharma"), ("EICHERMOT", "Auto"), ("ETERNAL", "Consumer"),
    ("GRASIM", "Materials"), ("HCLTECH", "IT"), ("HDFCBANK", "Banking"),
    ("HDFCLIFE", "Finance"), ("HEROMOTOCO", "Auto"), ("HINDALCO", "Metals"),
    ("HINDUNILVR", "Consumer"), ("ICICIBANK", "Banking"), ("INDUSINDBK", "Banking"),
    ("INFY", "IT"), ("ITC", "Consumer"), ("JIOFIN", "Finance"),
    ("JSWSTEEL", "Metals"), ("KOTAKBANK", "Banking"), ("LT", "Infra"),
    ("M&M", "Auto"), ("MARUTI", "Auto"), ("NESTLEIND", "Consumer"),
    ("NTPC", "Power"), ("ONGC", "Energy"), ("POWERGRID", "Power"),
    ("RELIANCE", "Energy"), ("SBILIFE", "Finance"), ("SBIN", "Banking"),
    ("SHRIRAMFIN", "Finance"), ("SUNPHARMA", "Pharma"), ("TATACONSUM", "Consumer"),
    ("TATAMOTORS", "Auto"), ("TATASTEEL", "Metals"), ("TCS", "IT"),
    ("TECHM", "IT"), ("TITAN", "Consumer"), ("TRENT", "Consumer"),
    ("ULTRACEMCO", "Materials"), ("WIPRO", "IT"),
]

client = get_client()

print(f"Fetching quotes for {len(NIFTY50)} symbols")
resp = client.multiquotes(symbols=[{"symbol": s, "exchange": "NSE"} for s, _ in NIFTY50])
if resp.get("status") != "success":
    raise SystemExit(f"multiquotes failed: {resp}")

sector_map = dict(NIFTY50)

rows = []
for item in resp["results"]:
    data = item.get("data") or {}
    ltp = data.get("ltp")
    prev = data.get("prev_close")
    if not ltp or not prev:
        continue
    rows.append({
        "symbol":  item["symbol"],
        "sector":  sector_map.get(item["symbol"], "Other"),
        "ltp":     float(ltp),
        "prev":    float(prev),
        "pct":     (float(ltp) / float(prev) - 1) * 100,
        "weight":  float(ltp),       # use price as size proxy; replace with market cap if available
    })

df = pd.DataFrame(rows)
print(df.sort_values("pct", ascending=False).head(10))

# ---- Treemap ------------------------------------------------------------

fig = px.treemap(
    df,
    path=["sector", "symbol"],
    values="weight",
    color="pct",
    color_continuous_scale="RdYlGn",
    color_continuous_midpoint=0,
    title=f"NIFTY 50 Heatmap — {date.today()}",
)
fig.update_layout(template="plotly_dark", height=700)
fig.update_traces(textinfo="label+value+percent parent")

# ---- Save --------------------------------------------------------------

workdir = Path("openalgo_workspace/visualization/sector_heatmap")
workdir.mkdir(parents=True, exist_ok=True)
out = workdir / f"heatmap_{date.today()}.html"
fig.write_html(str(out), include_plotlyjs="cdn")
df.to_csv(workdir / f"data_{date.today()}.csv", index=False)
print(f"\nSaved: {out}")
fig.show()
