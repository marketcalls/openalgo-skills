"""Stream LTP and fire Telegram alerts on price breaches.

Demonstrates the response-aware streaming pattern: subscribe -> alert
on threshold cross -> deduplicate so we don't spam.

Output folder: openalgo_workspace/streaming/alert_breakouts/
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.alerts import notify
from scripts.openalgo_client import get_client
from scripts.stream import CallbackRouter, subscribe

# ---- config: which symbols, which thresholds ---------------------------

WATCHLIST = [
    # (symbol, exchange, level_up, level_down)
    ("NIFTY",     "NSE_INDEX", 26500.0, 25500.0),
    ("BANKNIFTY", "NSE_INDEX", 58000.0, 56000.0),
    ("RELIANCE",  "NSE",        1400.0, 1300.0),
]

ALERT_COOLDOWN_SEC = 300           # don't re-fire for the same level inside 5 min

client = get_client()
router = CallbackRouter()
workdir = Path("openalgo_workspace/streaming/alert_breakouts")
workdir.mkdir(parents=True, exist_ok=True)
log_path = workdir / f"events_{datetime.now().strftime('%Y%m%d')}.log"

last_alert: dict[str, float] = {}


def make_handler(symbol, up, down):
    def _h(tick):
        d = tick["data"]
        ltp = float(d["ltp"])
        now = time.monotonic()
        key_up = f"{symbol}_UP"
        key_down = f"{symbol}_DOWN"

        if ltp >= up and now - last_alert.get(key_up, 0) > ALERT_COOLDOWN_SEC:
            msg = f"[ALERT] {symbol} crossed UP {up}   LTP {ltp}"
            notify(client, msg, via=("telegram",))
            print(msg)
            with log_path.open("a") as f:
                f.write(f"{datetime.now().isoformat()}  UP   {symbol}  {ltp}\n")
            last_alert[key_up] = now

        elif ltp <= down and now - last_alert.get(key_down, 0) > ALERT_COOLDOWN_SEC:
            msg = f"[ALERT] {symbol} crossed DOWN {down}   LTP {ltp}"
            notify(client, msg, via=("telegram",))
            print(msg)
            with log_path.open("a") as f:
                f.write(f"{datetime.now().isoformat()}  DOWN {symbol}  {ltp}\n")
            last_alert[key_down] = now
    return _h


for symbol, exchange, up, down in WATCHLIST:
    router.register(symbol, make_handler(symbol, up, down))

instruments = [{"exchange": e, "symbol": s} for s, e, _, _ in WATCHLIST]

if not os.environ.get("ALERT_TELEGRAM_USERNAME"):
    print("WARNING: ALERT_TELEGRAM_USERNAME not set in .env — alerts will not deliver")

print(f"Watching {len(WATCHLIST)} symbols. Ctrl-C to stop.")
for symbol, exchange, up, down in WATCHLIST:
    print(f"  {symbol:<10} UP>= {up}    DOWN<= {down}")

with subscribe(client, instruments, mode="ltp", on_data=router.handle):
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\nstopping  ({log_path})")
