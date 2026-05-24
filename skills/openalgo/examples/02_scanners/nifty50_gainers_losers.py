"""Top gainers and top losers in NIFTY 50 via `multiquotes`.

Single REST call returns LTP + prev_close for all 50 constituents.
Sorted by % change. Writes CSVs and optionally alerts the top 5.

Output folder: openalgo_workspace/scanners/nifty50_gainers_losers/
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.alerts import fmt_scanner_results, notify
from scripts.openalgo_client import get_client
from scripts.scanner import Scanner, gainers, losers

NIFTY50 = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK", "BAJAJ-AUTO",
    "BAJFINANCE", "BAJAJFINSV", "BEL", "BHARTIARTL", "CIPLA", "COALINDIA", "DRREDDY",
    "EICHERMOT", "ETERNAL", "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO",
    "HINDALCO", "HINDUNILVR", "ICICIBANK", "INDUSINDBK", "INFY", "ITC", "JIOFIN",
    "JSWSTEEL", "KOTAKBANK", "LT", "M&M", "MARUTI", "NESTLEIND", "NTPC", "ONGC",
    "POWERGRID", "RELIANCE", "SBILIFE", "SBIN", "SHRIRAMFIN", "SUNPHARMA", "TATACONSUM",
    "TATAMOTORS", "TATASTEEL", "TCS", "TECHM", "TITAN", "TRENT", "ULTRACEMCO", "WIPRO",
]

ALERT_TOP = 5
ALERTS = ("telegram",)

client = get_client()

# ---- Gainers ------------------------------------------------------------

print("Running scan: gainers >= 1%")
gainers_df = (
    Scanner(client)
    .add_many(NIFTY50, exchange="NSE")
    .with_filter(gainers(threshold_pct=1.0))
    .quote_scan()
)
gainers_df = gainers_df.head(15).reset_index(drop=True)
print(gainers_df[["symbol", "ltp", "prev_close", "pct_change", "volume"]])

# ---- Losers -------------------------------------------------------------

print("\nRunning scan: losers <= -1%")
losers_df = (
    Scanner(client)
    .add_many(NIFTY50, exchange="NSE")
    .with_filter(losers(threshold_pct=1.0))
    .quote_scan()
)
losers_df = losers_df.head(15).reset_index(drop=True)
print(losers_df[["symbol", "ltp", "prev_close", "pct_change", "volume"]])

# ---- Persist + alert ----------------------------------------------------

workdir = Path("openalgo_workspace/scanners/nifty50_gainers_losers")
workdir.mkdir(parents=True, exist_ok=True)

today = date.today().isoformat()
gainers_df.to_csv(workdir / f"gainers_{today}.csv", index=False)
losers_df.to_csv(workdir / f"losers_{today}.csv", index=False)

summary_top_gainers = fmt_scanner_results(
    f"NIFTY 50 Top Gainers ({today})",
    gainers_df.head(ALERT_TOP).to_dict("records"),
    fields=["symbol", "ltp", "pct_change"],
    max_rows=ALERT_TOP,
)
summary_top_losers = fmt_scanner_results(
    f"NIFTY 50 Top Losers ({today})",
    losers_df.head(ALERT_TOP).to_dict("records"),
    fields=["symbol", "ltp", "pct_change"],
    max_rows=ALERT_TOP,
)

notify(client, summary_top_gainers + "\n\n" + summary_top_losers, via=ALERTS)
print(f"\nSaved to {workdir}")
