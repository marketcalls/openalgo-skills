"""Market depth ladder — visualize the bid/ask book for one symbol.

Output folder: openalgo_workspace/charting/depth_<SYMBOL>/
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.openalgo_client import get_client
from scripts.plotting import depth_ladder
from scripts.responses import ensure_success

# ---- config ------------------------------------------------------------

SYMBOL = "RELIANCE"
EXCHANGE = "NSE"

client = get_client()

# ---- Fetch -------------------------------------------------------------

resp = client.depth(symbol=SYMBOL, exchange=EXCHANGE)
ensure_success(resp, action="depth")
data = resp["data"]

print(f"\n{SYMBOL}@{EXCHANGE}  LTP {data.get('ltp')}  "
      f"LTQ {data.get('ltq')}  Vol {data.get('volume'):,}")
print(f"Total buy qty:  {data.get('totalbuyqty'):,}")
print(f"Total sell qty: {data.get('totalsellqty'):,}")

# Print top of book
print("\n--- Top of Book ---")
print(f"  BEST BID: {data['bids'][0]['price']} x {data['bids'][0]['quantity']}")
print(f"  BEST ASK: {data['asks'][0]['price']} x {data['asks'][0]['quantity']}")
print(f"  SPREAD:   {data['asks'][0]['price'] - data['bids'][0]['price']:.2f}")

# ---- Plot --------------------------------------------------------------

workdir = Path(f"openalgo_workspace/charting/depth_{SYMBOL.lower()}")
workdir.mkdir(parents=True, exist_ok=True)
ts = datetime.now().strftime("%Y%m%d_%H%M%S")
out = workdir / f"depth_{ts}.html"

depth_ladder(
    data,
    title=f"{SYMBOL}@{EXCHANGE} Depth Ladder  LTP {data['ltp']}  ({ts})",
    out=out,
)
print(f"\nSaved: {out}")
