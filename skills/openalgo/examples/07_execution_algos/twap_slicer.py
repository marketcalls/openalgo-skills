"""TWAP slicer — slice a parent into N equal time-spaced children.

Each child is a `LimitChaser`. After all children finish, prints the
aggregate VWAP across the parent.

Use when:
- parent order is too large to land in one slice without impact
- urgency is low / medium — you can spend duration_sec working it
- you want disciplined time-weighted execution

Output folder: openalgo_workspace/execution_algos/twap_<SYMBOL>/
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.alerts import notify
from scripts.execution import TWAPConfig, TWAPSlicer
from scripts.openalgo_client import default_strategy_tag, get_client

SYMBOL = "SBIN"
EXCHANGE = "NSE"
ACTION = "BUY"
TOTAL_QUANTITY = 100
SLICES = 5
DURATION_SEC = 300        # 5 minutes
PRODUCT = "MIS"
CHASER_TIMEOUT = 50

client = get_client()
strategy = f"{default_strategy_tag()}_twap"
workdir = Path(f"openalgo_workspace/execution_algos/twap_{SYMBOL.lower()}")
workdir.mkdir(parents=True, exist_ok=True)

mode = client.analyzerstatus().get("data", {}).get("mode", "unknown")
print(f"[{mode.upper()}]  TWAP {ACTION} {TOTAL_QUANTITY} {SYMBOL}  "
      f"{SLICES} slices over {DURATION_SEC}s  (chaser timeout {CHASER_TIMEOUT}s/slice)")

if mode != "analyze":
    if input("Confirm LIVE TWAP? [y/N] ").strip().lower() != "y":
        raise SystemExit("aborted")

twap = TWAPSlicer(client, TWAPConfig(
    symbol=SYMBOL,
    exchange=EXCHANGE,
    action=ACTION,
    total_quantity=TOTAL_QUANTITY,
    slices=SLICES,
    duration_sec=DURATION_SEC,
    product=PRODUCT,
    strategy=strategy,
    chaser_timeout_sec=CHASER_TIMEOUT,
    tick_size=0.05,
))

results = twap.run()
summary = twap.summary()
filled = sum(1 for r in results if r.filled)
unfilled = sum(1 for r in results if not r.filled)

print("\n--- TWAP Summary ---")
print(f"Children placed:    {len(results)}")
print(f"Children filled:    {filled}")
print(f"Children unfilled:  {unfilled}")
print(f"Aggregate VWAP:     Rs {summary['vwap']}" if summary['vwap'] else "VWAP: n/a (no fills)")
print(f"Filled qty:         {summary['filled_qty']} / {TOTAL_QUANTITY}")

# Per-child report
print("\n--- Per-child ---")
for i, r in enumerate(results, 1):
    status = "FILLED" if r.filled else "UNFILLED"
    px = f"Rs {r.average_price}" if r.average_price else "n/a"
    print(f"  slice {i}: {status}  qty {r.filled_qty}  avg {px}")

msg = (
    f"[TWAP COMPLETE]\n"
    f"{ACTION} {TOTAL_QUANTITY} {SYMBOL} over {DURATION_SEC}s\n"
    f"VWAP: Rs {summary['vwap']}   filled {summary['filled_qty']}/{TOTAL_QUANTITY}"
)
notify(client, msg, via=("telegram",))
print(f"\nJournals: {workdir}")
