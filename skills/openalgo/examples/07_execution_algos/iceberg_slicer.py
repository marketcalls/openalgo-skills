"""Iceberg slicer — show only `display_quantity` at a fixed limit price.

Workflow: place a child of `display_quantity` at the fixed limit. When
it fills, place the next child. Continue until the parent quantity is
filled or the overall timeout expires.

Use when:
- you have a strong view on a price you're willing to pay (the limit)
- visible quantity must stay small to avoid moving the market

Note: this is a "synthetic" iceberg — the broker sees a sequence of
small orders, not a real venue-native iceberg with reserve quantity.
Anonymity benefit is zero. Queue-position discipline at one price is
the value.

Output folder: openalgo_workspace/execution_algos/iceberg_<SYMBOL>/
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.alerts import notify
from scripts.execution import IcebergConfig, IcebergSlicer
from scripts.openalgo_client import default_strategy_tag, get_client
from scripts.responses import extract_ltp

SYMBOL = "HDFCBANK"
EXCHANGE = "NSE"
ACTION = "BUY"
TOTAL_QTY = 200
DISPLAY_QTY = 25
PRODUCT = "CNC"
LIMIT_PRICE = None        # if None, anchor to current LTP - 0.5% as a "good price"
OVERALL_TIMEOUT_SEC = 600

client = get_client()
strategy = f"{default_strategy_tag()}_iceberg"
workdir = Path(f"openalgo_workspace/execution_algos/iceberg_{SYMBOL.lower()}")
workdir.mkdir(parents=True, exist_ok=True)

# Anchor the limit price if not explicitly set
if LIMIT_PRICE is None:
    ltp = extract_ltp(client.quotes(symbol=SYMBOL, exchange=EXCHANGE))
    if ACTION == "BUY":
        limit = round((ltp * 0.995) * 20) / 20
    else:
        limit = round((ltp * 1.005) * 20) / 20
    print(f"LTP {ltp}, anchored {ACTION} limit at Rs {limit}")
else:
    limit = LIMIT_PRICE

mode = client.analyzerstatus().get("data", {}).get("mode", "unknown")
print(f"[{mode.upper()}]  iceberg {ACTION} {TOTAL_QTY} {SYMBOL} "
      f"display {DISPLAY_QTY} @ Rs {limit}")

if mode != "analyze":
    if input("Confirm LIVE iceberg? [y/N] ").strip().lower() != "y":
        raise SystemExit("aborted")

# ---- Run ---------------------------------------------------------------

ice = IcebergSlicer(client, IcebergConfig(
    symbol=SYMBOL,
    exchange=EXCHANGE,
    action=ACTION,
    total_quantity=TOTAL_QTY,
    display_quantity=DISPLAY_QTY,
    price=limit,
    product=PRODUCT,
    strategy=strategy,
    poll_interval_sec=0.5,
    overall_timeout_sec=OVERALL_TIMEOUT_SEC,
))
result = ice.run()

# ---- Summary -----------------------------------------------------------

print("\n--- Iceberg result ---")
print(f"Filled:           {result['filled_qty']} / {result['target_qty']}")
print(f"Children placed:  {len(result['children'])}")
print(f"Complete:         {result['complete']}")

# Persist child order ids
with (workdir / "child_orders.txt").open("w") as f:
    for c in result["children"]:
        f.write(c + "\n")

msg = (
    f"[ICEBERG {'COMPLETE' if result['complete'] else 'PARTIAL'}]\n"
    f"{ACTION} {SYMBOL} @ Rs {limit}\n"
    f"Filled: {result['filled_qty']} / {result['target_qty']}\n"
    f"Children: {len(result['children'])}"
)
notify(client, msg, via=("telegram",))
print(f"\nLogs: {workdir}")
