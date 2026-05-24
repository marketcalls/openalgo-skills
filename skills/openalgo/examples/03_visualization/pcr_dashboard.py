"""Put-Call Ratio dashboard across multiple underlyings.

For each underlying-expiry combination:
  1. Fetch option chain
  2. Compute PCR(OI) and PCR(volume)
  3. Render a comparison bar chart

Output folder: openalgo_workspace/visualization/pcr_dashboard/
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.openalgo_client import get_client
from scripts.option_analytics import chain_to_df, pcr

UNDERLYINGS = [
    ("NIFTY", "NSE_INDEX"),
    ("BANKNIFTY", "NSE_INDEX"),
    ("FINNIFTY", "NSE_INDEX"),
    ("MIDCPNIFTY", "NSE_INDEX"),
]
EXPIRY = "30JUN26"
STRIKE_COUNT = 30

client = get_client()

rows = []
for underlying, exch in UNDERLYINGS:
    try:
        resp = client.optionchain(
            underlying=underlying, exchange=exch,
            expiry_date=EXPIRY, strike_count=STRIKE_COUNT,
        )
        df = chain_to_df(resp)
        rows.append({
            "underlying": underlying,
            "spot":       df.attrs["underlying_ltp"],
            "atm":        df.attrs["atm_strike"],
            "pcr_oi":     round(pcr(df, basis="oi"), 3),
            "pcr_volume": round(pcr(df, basis="volume"), 3),
            "n_strikes":  len(df["strike"].unique()),
        })
        print(f"  {underlying:<12} spot={df.attrs['underlying_ltp']}  "
              f"PCR(OI)={rows[-1]['pcr_oi']:.2f}  "
              f"PCR(vol)={rows[-1]['pcr_volume']:.2f}")
    except Exception as exc:
        print(f"  {underlying:<12} ERROR: {exc}")
        continue

dashboard = pd.DataFrame(rows)

# ---- Bar chart ---------------------------------------------------------

fig = go.Figure([
    go.Bar(name="PCR (OI)",     x=dashboard["underlying"], y=dashboard["pcr_oi"],
           marker_color="#42a5f5"),
    go.Bar(name="PCR (volume)", x=dashboard["underlying"], y=dashboard["pcr_volume"],
           marker_color="#ef5350"),
])
fig.add_hline(y=1.0, line_dash="dash", line_color="white",
              annotation_text="Neutral PCR = 1.0", annotation_position="top right")
fig.update_layout(
    title=f"Put-Call Ratio Dashboard — {EXPIRY} expiry — {date.today()}",
    template="plotly_dark", height=550, barmode="group",
    xaxis_title="Underlying", yaxis_title="PCR",
)

# ---- Save -------------------------------------------------------------

workdir = Path("openalgo_workspace/visualization/pcr_dashboard")
workdir.mkdir(parents=True, exist_ok=True)
out = workdir / f"pcr_{date.today()}.html"
fig.write_html(str(out), include_plotlyjs="cdn")
dashboard.to_csv(workdir / f"data_{date.today()}.csv", index=False)
print(f"\nSaved: {out}")
fig.show()
