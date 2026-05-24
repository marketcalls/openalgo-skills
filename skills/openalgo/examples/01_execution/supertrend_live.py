"""Live Supertrend strategy on a single symbol.

Strategy:
- 5-minute bars
- Supertrend(10, 3.0) line + direction
- BUY when direction flips +1, SELL when it flips -1
- Position-aware: uses placesmartorder so the SDK reconciles current state

Workflow each tick (15 s sleep):
1. history(...) -> last 7 days of 5m bars
2. supertrend(...) -> latest direction
3. extract signal on the last fully closed bar (iloc[-2])
4. if signal flips, placesmartorder + alert

Output folder: openalgo_workspace/execution/supertrend_<SYMBOL>/
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.alerts import notify
from scripts.openalgo_client import default_strategy_tag, get_client
from scripts.ta_helpers import supertrend
from scripts.trade_logger import open_journal

# ---- config --------------------------------------------------------------

SYMBOL = "RELIANCE"
EXCHANGE = "NSE"
PRODUCT = "MIS"
INTERVAL = "5m"
QUANTITY = 1

ATR_PERIOD = 10
ATR_MULT = 3.0

POLL_SECONDS = 15

ALERTS = ("telegram",)

# ---- bootstrap -----------------------------------------------------------

client = get_client()
strategy = f"{default_strategy_tag()}_supertrend"
workdir = Path(f"openalgo_workspace/execution/supertrend_{SYMBOL.lower()}")
workdir.mkdir(parents=True, exist_ok=True)
journal = open_journal(workdir / "journal.csv")

mode = client.analyzerstatus().get("data", {}).get("mode", "unknown")
print(f"[{mode.upper()}] Supertrend({ATR_PERIOD}, {ATR_MULT}) on {SYMBOL} {INTERVAL} {EXCHANGE}")

position = 0     # tracked locally; placesmartorder uses position_size to reconcile

# ---- main loop -----------------------------------------------------------

try:
    while True:
        try:
            end = datetime.now().strftime("%Y-%m-%d")
            start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

            df = client.history(symbol=SYMBOL, exchange=EXCHANGE,
                                interval=INTERVAL,
                                start_date=start, end_date=end)
            if df is None or len(df) < ATR_PERIOD + 2:
                print("not enough bars; sleeping")
                time.sleep(POLL_SECONDS)
                continue

            # Normalize timestamp index
            if "timestamp" in df.columns:
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                df = df.set_index("timestamp")
            else:
                df.index = pd.to_datetime(df.index)
            if df.index.tz is not None:
                df.index = df.index.tz_convert(None)
            df = df.sort_index()

            # Compute supertrend
            st_line, st_dir = supertrend(df["high"], df["low"], df["close"],
                                          period=ATR_PERIOD, multiplier=ATR_MULT)
            # Signal on last fully-closed bar
            cur_dir = int(st_dir.iloc[-2])
            prev_dir = int(st_dir.iloc[-3])

            ltp = float(df["close"].iloc[-1])
            print(f"{df.index[-2].strftime('%H:%M')}  close={ltp}  "
                  f"st_line={st_line.iloc[-2]:.2f}  dir={cur_dir:+d}  pos={position}")

            # Detect flip and act
            if cur_dir > 0 and prev_dir <= 0 and position <= 0:
                position = QUANTITY
                resp = client.placesmartorder(
                    strategy=strategy, symbol=SYMBOL, exchange=EXCHANGE,
                    action="BUY", price_type="MARKET", product=PRODUCT,
                    quantity=QUANTITY, position_size=position,
                )
                journal.write(strategy=strategy, symbol=SYMBOL, exchange=EXCHANGE,
                              action="BUY", event="signal_flip_up",
                              price=ltp, quantity=QUANTITY,
                              order_id=str(resp.get("orderid", "")))
                notify(client, f"SUPERTREND BUY {SYMBOL} @ Rs {ltp}  qty {QUANTITY}", via=ALERTS)

            elif cur_dir < 0 and prev_dir >= 0 and position >= 0:
                position = -QUANTITY
                resp = client.placesmartorder(
                    strategy=strategy, symbol=SYMBOL, exchange=EXCHANGE,
                    action="SELL", price_type="MARKET", product=PRODUCT,
                    quantity=QUANTITY, position_size=position,
                )
                journal.write(strategy=strategy, symbol=SYMBOL, exchange=EXCHANGE,
                              action="SELL", event="signal_flip_down",
                              price=ltp, quantity=QUANTITY,
                              order_id=str(resp.get("orderid", "")))
                notify(client, f"SUPERTREND SELL {SYMBOL} @ Rs {ltp}  qty {QUANTITY}", via=ALERTS)

        except Exception as exc:
            print(f"[loop] {exc!r}")
            notify(client, f"Supertrend error: {exc}", via=ALERTS)

        time.sleep(POLL_SECONDS)

except KeyboardInterrupt:
    print("\nstopped by user")
    journal.close()
