"""Conditional bracket — fill first, attach SL only if move > threshold.

A delayed-bracket pattern. After filling, wait until the LTP has
moved at least X% from the fill before attaching the SL. Avoids
getting wicked out by normal entry-bar noise.

Workflow:
  1. placeorder MARKET -> orderstatus poll -> avg_fill_price
  2. quote loop: wait until |LTP - fill| / fill >= MOVE_TRIGGER_PCT
  3. compute SL relative to fill, place SL-M
  4. optionally compute target relative to fill, place LIMIT
  5. alert on each phase

Output folder: openalgo_workspace/execution_algos/conditional_bracket_<SYMBOL>/
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.alerts import notify
from scripts.openalgo_client import default_strategy_tag, get_client
from scripts.orders import place_with_retry
from scripts.responses import (
    avg_fill_price, extract_ltp, extract_orderid, poll_until_filled,
)
from scripts.trade_logger import open_journal

SYMBOL = "RELIANCE"
EXCHANGE = "NSE"
ACTION = "BUY"
QUANTITY = 5
PRODUCT = "MIS"

SL_PCT = 0.8            # SL placed 0.8% below fill
TARGET_PCT = 1.6        # target placed 1.6% above fill
MOVE_TRIGGER_PCT = 0.3  # don't attach SL until LTP has moved 0.3% from fill
MAX_WAIT_SEC = 600
POLL_INTERVAL = 5

client = get_client()
strategy = f"{default_strategy_tag()}_cond_bracket"
workdir = Path(f"openalgo_workspace/execution_algos/conditional_bracket_{SYMBOL.lower()}")
workdir.mkdir(parents=True, exist_ok=True)
journal = open_journal(workdir / "journal.csv")

mode = client.analyzerstatus().get("data", {}).get("mode", "unknown")
print(f"[{mode.upper()}]  conditional bracket  {ACTION} {QUANTITY} {SYMBOL}")
print(f"  fill via MARKET")
print(f"  wait for |LTP - fill| / fill >= {MOVE_TRIGGER_PCT}%")
print(f"  then attach SL @ -{SL_PCT}%   target @ +{TARGET_PCT}%")

# ---- 1. Entry MARKET ---------------------------------------------------

resp = place_with_retry(
    client, strategy=strategy, symbol=SYMBOL, exchange=EXCHANGE,
    action=ACTION, price_type="MARKET", product=PRODUCT,
    quantity=QUANTITY, price=0,
)
entry_id = extract_orderid(resp)
journal.write(strategy=strategy, symbol=SYMBOL, exchange=EXCHANGE,
              action=ACTION, event="entry_placed", order_id=entry_id,
              quantity=QUANTITY)

final = poll_until_filled(
    client, order_id=entry_id, strategy=strategy,
    interval_sec=1.0, timeout_sec=30.0,
)
fill = avg_fill_price(final)
qty = int(final["data"].get("quantity") or QUANTITY)
journal.write(strategy=strategy, symbol=SYMBOL, exchange=EXCHANGE,
              action=ACTION, event="entry_filled", order_id=entry_id,
              average_price=fill, quantity=qty)
print(f"\nfilled {qty} @ Rs {fill}")

# ---- 2. Wait for the threshold move -----------------------------------

print(f"\nwaiting for {MOVE_TRIGGER_PCT}% move from Rs {fill}...")
deadline = time.monotonic() + MAX_WAIT_SEC
triggered = False
while time.monotonic() < deadline:
    time.sleep(POLL_INTERVAL)
    ltp = extract_ltp(client.quotes(symbol=SYMBOL, exchange=EXCHANGE))
    move_pct = abs(ltp - fill) / fill * 100
    print(f"  LTP {ltp}   move {move_pct:+.3f}% from fill")
    if move_pct >= MOVE_TRIGGER_PCT:
        triggered = True
        break

if not triggered:
    msg = f"[CONDITIONAL] {SYMBOL} no move within {MAX_WAIT_SEC}s — no SL attached"
    print("\n" + msg)
    notify(client, msg, via=("telegram",))
    journal.close()
    raise SystemExit()

# ---- 3. Attach SL + target --------------------------------------------

sl_action = "SELL" if ACTION == "BUY" else "BUY"

if ACTION == "BUY":
    sl_trigger = round((fill * (1 - SL_PCT / 100)) * 20) / 20
    target_px = round((fill * (1 + TARGET_PCT / 100)) * 20) / 20
else:
    sl_trigger = round((fill * (1 + SL_PCT / 100)) * 20) / 20
    target_px = round((fill * (1 - TARGET_PCT / 100)) * 20) / 20

sl_resp = place_with_retry(
    client, strategy=strategy, symbol=SYMBOL, exchange=EXCHANGE,
    action=sl_action, price_type="SL-M", product=PRODUCT,
    quantity=qty, price=0, trigger_price=sl_trigger,
)
sl_id = extract_orderid(sl_resp)
journal.write(strategy=strategy, symbol=SYMBOL, exchange=EXCHANGE,
              action=sl_action, event="sl_placed", order_id=sl_id,
              trigger_price=sl_trigger)

tgt_resp = place_with_retry(
    client, strategy=strategy, symbol=SYMBOL, exchange=EXCHANGE,
    action=sl_action, price_type="LIMIT", product=PRODUCT,
    quantity=qty, price=target_px,
)
tgt_id = extract_orderid(tgt_resp)
journal.write(strategy=strategy, symbol=SYMBOL, exchange=EXCHANGE,
              action=sl_action, event="target_placed", order_id=tgt_id,
              price=target_px)

msg = (
    f"[CONDITIONAL BRACKET ARMED]\n"
    f"{ACTION} {qty} {SYMBOL} filled @ Rs {fill}\n"
    f"SL-M trigger: Rs {sl_trigger}   id {sl_id}\n"
    f"Target:       Rs {target_px}    id {tgt_id}"
)
print("\n" + msg)
notify(client, msg, via=("telegram", "whatsapp"))
journal.close()
