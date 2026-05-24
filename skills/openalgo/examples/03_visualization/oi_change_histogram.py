"""Side-by-side CE / PE Open Interest histogram for an option chain.

Output folder: openalgo_workspace/visualization/oi_histogram_<UNDERLYING>_<EXPIRY>/
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.openalgo_client import get_client
from scripts.option_analytics import chain_to_df, pcr, max_pain
from scripts.plotting import oi_histogram

# ---- config ------------------------------------------------------------

UNDERLYING = "NIFTY"
UNDERLYING_EXCHANGE = "NSE_INDEX"
EXPIRY = "30JUN26"
STRIKE_COUNT = 30           # 30 strikes either side of ATM
STRIKE_FILTER = 100         # filter to round strikes (NIFTY 100-point grid)

client = get_client()

# ---- Fetch chain --------------------------------------------------------

print(f"Fetching {UNDERLYING} {EXPIRY} option chain (±{STRIKE_COUNT} strikes around ATM)")
chain_resp = client.optionchain(
    underlying=UNDERLYING,
    exchange=UNDERLYING_EXCHANGE,
    expiry_date=EXPIRY,
    strike_count=STRIKE_COUNT,
)
df = chain_to_df(chain_resp)
print(f"  underlying: {df.attrs['underlying']} @ {df.attrs['underlying_ltp']}")
print(f"  ATM strike: {df.attrs['atm_strike']}")
print(f"  strikes:    {len(df['strike'].unique())}")

# Filter to round strikes only (no 50-point in-between)
if STRIKE_FILTER:
    df = df[df["strike"] % STRIKE_FILTER == 0].copy()
    print(f"  after {STRIKE_FILTER}-point filter: {len(df['strike'].unique())} strikes")

# ---- Compute PCR + max-pain --------------------------------------------

pcr_oi = pcr(df, basis="oi")
pcr_vol = pcr(df, basis="volume")
mp = max_pain(df)
print(f"\n  PCR (OI):     {pcr_oi:.2f}")
print(f"  PCR (volume): {pcr_vol:.2f}")
print(f"  Max pain:     {mp['strike']:.0f}")

# ---- Plot --------------------------------------------------------------

workdir = Path(f"openalgo_workspace/visualization/oi_histogram_{UNDERLYING.lower()}_{EXPIRY.lower()}")
workdir.mkdir(parents=True, exist_ok=True)
out = workdir / f"oi_{date.today()}.html"

oi_histogram(
    df,
    title=f"{UNDERLYING} {EXPIRY} — OI Histogram   "
          f"PCR(OI)={pcr_oi:.2f}  MaxPain={mp['strike']:.0f}  "
          f"Spot={df.attrs['underlying_ltp']}",
    out=out,
)

# Also save the raw chain data
df.to_csv(workdir / f"chain_{date.today()}.csv", index=False)
print(f"\nSaved: {out}")
