"""Basic LTP stream with the subscribe() context manager.

Subscribes to a small list of instruments in Mode 1 (LTP) and prints
each tick. Cleanly unsubscribes on Ctrl-C.

Output folder: openalgo_workspace/streaming/ltp_basic/
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.openalgo_client import get_client
from scripts.stream import subscribe

INSTRUMENTS = [
    {"exchange": "NSE_INDEX", "symbol": "NIFTY"},
    {"exchange": "NSE_INDEX", "symbol": "BANKNIFTY"},
    {"exchange": "NSE",       "symbol": "RELIANCE"},
    {"exchange": "NSE",       "symbol": "SBIN"},
]

client = get_client(verbose=True)


def on_ltp(msg):
    d = msg["data"]
    print(f"{d['symbol']:<12} {d['exchange']:<10} LTP {d['ltp']}  @ {d['timestamp']}")


print(f"Streaming LTP for {len(INSTRUMENTS)} instruments. Ctrl-C to stop.\n")
with subscribe(client, INSTRUMENTS, mode="ltp", on_data=on_ltp):
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nstopping")
