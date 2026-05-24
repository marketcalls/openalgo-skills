"""Max-pain chart — total option-writer pain by strike.

Max pain = strike at which option writers collectively pay the
smallest total payout if the underlying expires there. Often used
as a magnet for where price might pin on expiry day.

Output folder: openalgo_workspace/charting/max_pain_<UNDERLYING>_<EXPIRY>/
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import plotly.graph_objects as go

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.openalgo_client import get_client
from scripts.option_analytics import chain_to_df, max_pain

# ---- config ------------------------------------------------------------

UNDERLYING = "NIFTY"
UNDERLYING_EXCHANGE = "NSE_INDEX"
EXPIRY = "30JUN26"
STRIKE_COUNT = 40
STRIKE_FILTER = 100

client = get_client()

# ---- Fetch + compute ---------------------------------------------------

print(f"Fetching {UNDERLYING} {EXPIRY} chain  (±{STRIKE_COUNT} strikes)")
chain_resp = client.optionchain(
    underlying=UNDERLYING, exchange=UNDERLYING_EXCHANGE,
    expiry_date=EXPIRY, strike_count=STRIKE_COUNT,
)
df = chain_to_df(chain_resp)
if STRIKE_FILTER:
    df = df[df["strike"] % STRIKE_FILTER == 0].copy()
df.attrs.update(chain_to_df(chain_resp).attrs)

mp = max_pain(df)
spot = df.attrs["underlying_ltp"]

print(f"  spot:        {spot}")
print(f"  max pain:    {mp['strike']:.0f}")
print(f"  total pain:  Rs {mp['total_pain']:,.0f}")

# ---- Plot -------------------------------------------------------------

series = mp["series"]
fig = go.Figure(go.Bar(
    x=series.index, y=series.values,
    marker_color=["#42a5f5" if k != mp["strike"] else "#ef5350" for k in series.index],
    name="Pain at strike",
))
fig.add_vline(x=spot, line_dash="dash", line_color="white",
              annotation_text=f"Spot {spot}", annotation_position="top right")
fig.add_vline(x=mp["strike"], line_dash="dot", line_color="orange",
              annotation_text=f"Max Pain {mp['strike']:.0f}", annotation_position="top left")
fig.update_layout(
    title=f"{UNDERLYING} {EXPIRY} Max Pain Profile    "
          f"Spot={spot}  MaxPain={mp['strike']:.0f}",
    template="plotly_dark", height=550,
    xaxis_title="Strike", yaxis_title="Total Option-Writer Pain (Rs)",
)

# ---- Save -------------------------------------------------------------

workdir = Path(f"openalgo_workspace/charting/max_pain_{UNDERLYING.lower()}_{EXPIRY.lower()}")
workdir.mkdir(parents=True, exist_ok=True)
out = workdir / f"max_pain_{date.today()}.html"
fig.write_html(str(out), include_plotlyjs="cdn")
series.to_csv(workdir / f"pain_series_{date.today()}.csv", header=["pain"])
print(f"\nSaved: {out}")
fig.show()
