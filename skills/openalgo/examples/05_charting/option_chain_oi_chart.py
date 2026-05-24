"""Option chain OI chart — CE/PE side-by-side bars.

The "go-to" chart traders refer to when picking strikes for a
straddle / strangle. Marks the spot price and ATM strike clearly.

Output folder: openalgo_workspace/charting/option_chain_oi_<UNDERLYING>_<EXPIRY>/
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.openalgo_client import get_client
from scripts.option_analytics import chain_to_df
from scripts.plotting import oi_histogram

# ---- config ------------------------------------------------------------

UNDERLYING = "NIFTY"
UNDERLYING_EXCHANGE = "NSE_INDEX"
EXPIRY = "30JUN26"
STRIKE_COUNT = 25
STRIKE_FILTER = 100         # NIFTY 100-point grid; use 200 for BANKNIFTY

client = get_client()

# ---- Fetch + filter ----------------------------------------------------

print(f"Fetching {UNDERLYING} {EXPIRY} chain  (±{STRIKE_COUNT} strikes)")
chain_resp = client.optionchain(
    underlying=UNDERLYING, exchange=UNDERLYING_EXCHANGE,
    expiry_date=EXPIRY, strike_count=STRIKE_COUNT,
)
df = chain_to_df(chain_resp)

if STRIKE_FILTER:
    df = df[df["strike"] % STRIKE_FILTER == 0].copy()

# Preserve metadata after filter
df.attrs.update(chain_to_df(chain_resp).attrs)

print(f"  underlying LTP:  {df.attrs['underlying_ltp']}")
print(f"  ATM strike:      {df.attrs['atm_strike']}")
print(f"  strikes shown:   {len(df['strike'].unique())}")

# ---- Plot --------------------------------------------------------------

workdir = Path(
    f"openalgo_workspace/charting/option_chain_oi_{UNDERLYING.lower()}_{EXPIRY.lower()}"
)
workdir.mkdir(parents=True, exist_ok=True)
out = workdir / f"oi_{date.today()}.html"

oi_histogram(
    df,
    title=f"{UNDERLYING} {EXPIRY} Option Chain OI    "
          f"Spot={df.attrs['underlying_ltp']}  ATM={df.attrs['atm_strike']}",
    out=out,
)
df.to_csv(workdir / f"chain_{date.today()}.csv", index=False)
print(f"\nSaved: {out}")
