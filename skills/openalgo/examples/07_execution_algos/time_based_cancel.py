"""Place a LIMIT order; cancel if not filled within N seconds.

The simplest "auto-cancel" pattern. Useful for opportunistic entries
where you only want the trade at the specified price within a short
window — beyond that, the conditions that prompted the entry no
longer apply.

Output folder: openalgo_workspace/execution_algos/time_cancel_<SYMBOL>/
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.alerts import notify
from scripts.openalgo_client import default_strategy_tag, get_client
from scripts.orders import cancel_with_retry, place_with_retry
from scripts.responses import (
    avg_fill_price, extract_orderid, is_filled, is_terminal,
)
from scripts.trade_logger import open_journal

SYMBOL = "SBIN"
EXCHANGE = "NSE"
ACTION = "BUY"
QUANTITY = 10
PRODUCT = "MIS"
LIMIT_PRICE = 750.00
HOLD_SECONDS = 60

client = get_client()
strategy = f"{default_strategy_tag()}_time_cancel"
workdir = Path(f"openalgo_workspace/execution_algos/time_cancel_{SYMBOL.lower()}")
workdir.mkdir(parents=True, exist_ok=True)
journal = open_journal(workdir / "journal.csv")

mode = client.analyzerstatus().get("data", {}).get("mode", "unknown")
print(f"[{mode.upper()}]  {ACTION} {QUANTITY} {SYMBOL} @ Rs {LIMIT_PRICE} LIMIT  "
      f"cancel after {HOLD_SECONDS}s")

# ---- Place -------------------------------------------------------------

resp = place_with_retry(
    client,
    strategy=strategy,
    symbol=SYMBOL,
    exchange=EXCHANGE,
    action=ACTION,
    price_type="LIMIT",
    product=PRODUCT,
    quantity=QUANTITY,
    price=LIMIT_PRICE,
)
order_id = extract_orderid(resp)
journal.write(strategy=strategy, symbol=SYMBOL, exchange=EXCHANGE,
              action=ACTION, event="placed", order_id=order_id,
              price=LIMIT_PRICE, quantity=QUANTITY)
print(f"placed {order_id}")

# ---- Wait + check ------------------------------------------------------

deadline = time.monotonic() + HOLD_SECONDS
final_status = None
while time.monotonic() < deadline:
    time.sleep(2)
    status = client.orderstatus(order_id=order_id, strategy=strategy)
    if is_filled(status):
        final_status = status
        break
    if is_terminal(status):
        final_status = status
        print(f"order terminal: {status['data']['order_status']}")
        break

# ---- Outcome -----------------------------------------------------------

if final_status and is_filled(final_status):
    px = avg_fill_price(final_status)
    journal.write(strategy=strategy, symbol=SYMBOL, exchange=EXCHANGE,
                  action=ACTION, event="filled", order_id=order_id,
                  average_price=px)
    msg = f"[TIME-CANCEL FILLED] {ACTION} {QUANTITY} {SYMBOL} @ Rs {px}  order {order_id}"
else:
    cancel_with_retry(client, order_id=order_id, strategy=strategy)
    journal.write(strategy=strategy, symbol=SYMBOL, exchange=EXCHANGE,
                  action=ACTION, event="cancelled_timeout", order_id=order_id)
    msg = (f"[TIME-CANCEL EXPIRED] {ACTION} {QUANTITY} {SYMBOL} @ Rs {LIMIT_PRICE} "
           f"not filled in {HOLD_SECONDS}s — cancelled  ({order_id})")

print("\n" + msg)
notify(client, msg, via=("telegram",))
journal.close()
