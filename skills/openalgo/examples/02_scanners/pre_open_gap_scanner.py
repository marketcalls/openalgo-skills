"""Pre-open gap scanner — flags symbols with significant gap up/down at open.

Run this within the first 5 minutes of the session. Compares today's
open to yesterday's close.

Workflow:
  1. multiquotes -> ltp, open, prev_close for the universe
  2. compute gap = (open / prev_close - 1) * 100
  3. flag |gap| >= threshold
  4. sort and alert

Output folder: openalgo_workspace/scanners/pre_open_gap/
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.alerts import fmt_scanner_results, notify
from scripts.openalgo_client import get_client
from scripts.scanner import Scanner, gap_up, gap_down

UNIVERSE = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "BAJFINANCE",
    "BHARTIARTL", "ITC", "HINDUNILVR", "LT", "AXISBANK", "ASIANPAINT", "MARUTI",
    "TITAN", "ULTRACEMCO", "NESTLEIND", "WIPRO", "TECHM", "ADANIENT", "ADANIPORTS",
    "JSWSTEEL", "TATASTEEL", "HINDALCO", "COALINDIA", "ONGC", "NTPC", "POWERGRID",
    "TATAMOTORS", "M&M", "EICHERMOT", "HEROMOTOCO", "BAJAJ-AUTO",
]

GAP_THRESHOLD_PCT = 1.5

client = get_client()

# ---- Gap up scan --------------------------------------------------------

up = (
    Scanner(client)
    .add_many(UNIVERSE, exchange="NSE")
    .with_filter(gap_up(min_pct=GAP_THRESHOLD_PCT))
    .quote_scan()
)
print(f"\nGap UP >= {GAP_THRESHOLD_PCT}%   ({len(up)} symbols)")
if not up.empty:
    print(up[["symbol", "open", "prev_close", "gap_pct", "ltp"]].to_string(index=False))

# ---- Gap down scan ------------------------------------------------------

down = (
    Scanner(client)
    .add_many(UNIVERSE, exchange="NSE")
    .with_filter(gap_down(min_pct=GAP_THRESHOLD_PCT))
    .quote_scan()
)
print(f"\nGap DOWN >= {GAP_THRESHOLD_PCT}%   ({len(down)} symbols)")
if not down.empty:
    print(down[["symbol", "open", "prev_close", "gap_pct", "ltp"]].to_string(index=False))

# ---- Persist + alert ----------------------------------------------------

workdir = Path("openalgo_workspace/scanners/pre_open_gap")
workdir.mkdir(parents=True, exist_ok=True)
today = date.today().isoformat()

up.to_csv(workdir / f"gap_up_{today}.csv", index=False)
down.to_csv(workdir / f"gap_down_{today}.csv", index=False)

if not up.empty or not down.empty:
    msg = ""
    if not up.empty:
        msg += fmt_scanner_results(
            f"Gap UP >= {GAP_THRESHOLD_PCT}%",
            up.head(10).to_dict("records"),
            fields=["symbol", "open", "prev_close", "gap_pct"], max_rows=10,
        )
    if not down.empty:
        if msg:
            msg += "\n\n"
        msg += fmt_scanner_results(
            f"Gap DOWN >= {GAP_THRESHOLD_PCT}%",
            down.head(10).to_dict("records"),
            fields=["symbol", "open", "prev_close", "gap_pct"], max_rows=10,
        )
    notify(client, msg, via=("telegram",))

print(f"\nSaved to {workdir}")
