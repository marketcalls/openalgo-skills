"""Long-running stream with auto-reconnect.

Uses `scripts.stream.reconnect_loop` — wraps `subscribe()` in an
exponential-backoff retry loop. Survives broker WebSocket drops and
network blips that would otherwise kill a naive `client.connect()`
script.

Output folder: openalgo_workspace/streaming/reconnect/
"""

from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.openalgo_client import get_client
from scripts.stream import reconnect_loop

INSTRUMENTS = [
    {"exchange": "NSE_INDEX", "symbol": "NIFTY"},
    {"exchange": "NSE_INDEX", "symbol": "BANKNIFTY"},
    {"exchange": "NSE",       "symbol": "RELIANCE"},
    {"exchange": "NSE",       "symbol": "SBIN"},
    {"exchange": "NSE",       "symbol": "INFY"},
]

workdir = Path("openalgo_workspace/streaming/reconnect")
workdir.mkdir(parents=True, exist_ok=True)
log_path = workdir / f"ticks_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"


def on_quote(msg):
    d = msg["data"]
    line = (f"{d['timestamp']}  {d['symbol']:<12} "
            f"O {d.get('open'):>9} H {d.get('high'):>9} L {d.get('low'):>9} "
            f"LTP {d['ltp']:>9}  V {d.get('volume')}")
    with log_path.open("a") as f:
        f.write(line + "\n")


# `client_factory` returns a fresh client each retry — useful if the
# broker token rotated. Here we just rebuild from .env.
def factory():
    return get_client(verbose=True)


print(f"Persistent stream of {len(INSTRUMENTS)} symbols  ({log_path})")
print("Ctrl-C to stop.\n")

reconnect_loop(
    client_factory=factory,
    instruments=INSTRUMENTS,
    mode="quote",
    on_data=on_quote,
    max_retries=100,
    backoff_sec=[1, 2, 5, 10, 30],
)
