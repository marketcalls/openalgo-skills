"""20-level market-depth stream — full book ticks for a single symbol.

Mode 3 with `depth_level=20`. Renders the top-5 of each side per
update; persists every tick to a parquet file for offline analysis.

Output folder: openalgo_workspace/streaming/depth_<SYMBOL>/
"""

from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.openalgo_client import get_client
from scripts.stream import subscribe

SYMBOL = "RELIANCE"
EXCHANGE = "NSE"
DEPTH_LEVEL = 20
PARQUET_BATCH = 100        # flush every N ticks

client = get_client(verbose=True)
instruments = [{"exchange": EXCHANGE, "symbol": SYMBOL}]

workdir = Path(f"openalgo_workspace/streaming/depth_{SYMBOL.lower()}")
workdir.mkdir(parents=True, exist_ok=True)
ts = datetime.now().strftime("%Y%m%d_%H%M%S")
out_path = workdir / f"depth_{ts}.parquet"
print(f"Persisting ticks to {out_path}")

ticks: list[dict] = []
last_print = 0.0


def on_depth(msg):
    global last_print
    d = msg["data"]
    depth = d.get("depth", {})
    buy = depth.get("buy", [])
    sell = depth.get("sell", [])

    row = {
        "ts":       d["timestamp"],
        "symbol":   d["symbol"],
        "ltp":      d["ltp"],
        "best_bid": buy[0]["price"]  if buy  else None,
        "best_ask": sell[0]["price"] if sell else None,
        "bid_qty":  buy[0]["quantity"]  if buy  else None,
        "ask_qty":  sell[0]["quantity"] if sell else None,
        "spread":   ((sell[0]["price"] - buy[0]["price"]) if buy and sell else None),
        "imbalance": (
            sum(b["quantity"] for b in buy) / sum(s["quantity"] for s in sell)
            if buy and sell and sum(s["quantity"] for s in sell) else None
        ),
    }
    ticks.append(row)

    # Print top-of-book every second
    now = time.monotonic()
    if now - last_print >= 1.0:
        if buy and sell:
            print(f"{d['symbol']}  LTP {d['ltp']}  "
                  f"BID {row['best_bid']}x{row['bid_qty']}  "
                  f"ASK {row['best_ask']}x{row['ask_qty']}  "
                  f"spread {row['spread']:.2f}")
        last_print = now

    # Persist in batches
    if len(ticks) >= PARQUET_BATCH:
        pd.DataFrame(ticks).to_parquet(
            out_path,
            engine="pyarrow",
            compression="snappy",
            index=False,
        )
        print(f"  flushed {len(ticks)} ticks")


print(f"Subscribing to {SYMBOL}@{EXCHANGE} depth (level {DEPTH_LEVEL})")
with subscribe(client, instruments, mode="depth", on_data=on_depth, depth_level=DEPTH_LEVEL):
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        if ticks:
            pd.DataFrame(ticks).to_parquet(out_path, engine="pyarrow", index=False)
            print(f"\nfinal flush: {len(ticks)} ticks  -> {out_path}")
