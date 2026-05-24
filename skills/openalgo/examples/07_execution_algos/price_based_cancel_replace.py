"""Cancel and replace if LTP moves past a re-anchor threshold.

Different from `LimitChaser`:
- Chaser uses depth (touch) — modifies aggressively every tick move.
- This algo uses LTP — only cancels and *replaces* if LTP runs away
  more than a chosen %, and then re-anchors to the new LTP for the
  next attempt.

Use when you want to participate without paying the touch — willing
to wait at a sticky limit but unwilling to chase if the market runs.

Output folder: openalgo_workspace/execution_algos/price_replace_<SYMBOL>/
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
    avg_fill_price, extract_ltp, extract_orderid, is_filled, is_terminal,
)
from scripts.trade_logger import open_journal

SYMBOL = "RELIANCE"
EXCHANGE = "NSE"
ACTION = "BUY"
QUANTITY = 5
PRODUCT = "MIS"
INITIAL_OFFSET_PCT = -0.20      # try to BUY at LTP - 0.20%
REPLACE_TRIGGER_PCT = 0.30      # re-anchor when LTP runs 0.30% from our last limit
MAX_REPLACEMENTS = 5
TIMEOUT_SEC = 300
POLL_INTERVAL = 2

client = get_client()
strategy = f"{default_strategy_tag()}_replace"
workdir = Path(f"openalgo_workspace/execution_algos/price_replace_{SYMBOL.lower()}")
workdir.mkdir(parents=True, exist_ok=True)
journal = open_journal(workdir / "journal.csv")

mode = client.analyzerstatus().get("data", {}).get("mode", "unknown")
print(f"[{mode.upper()}]  {ACTION} {QUANTITY} {SYMBOL}  "
      f"initial offset {INITIAL_OFFSET_PCT}%  replace if LTP moves {REPLACE_TRIGGER_PCT}%")


def anchor(target_price: float) -> float:
    """Round to NSE tick = 0.05."""
    return round(target_price * 20) / 20


# ---- Initial place -----------------------------------------------------

ltp = extract_ltp(client.quotes(symbol=SYMBOL, exchange=EXCHANGE))
limit = anchor(ltp * (1 + INITIAL_OFFSET_PCT / 100))
print(f"LTP {ltp}   initial LIMIT @ Rs {limit}")

resp = place_with_retry(
    client, strategy=strategy, symbol=SYMBOL, exchange=EXCHANGE,
    action=ACTION, price_type="LIMIT", product=PRODUCT,
    quantity=QUANTITY, price=limit,
)
order_id = extract_orderid(resp)
journal.write(strategy=strategy, symbol=SYMBOL, exchange=EXCHANGE,
              action=ACTION, event="placed", order_id=order_id,
              price=limit, quantity=QUANTITY)

replacements = 0
deadline = time.monotonic() + TIMEOUT_SEC

# ---- Watch / replace loop ---------------------------------------------

while time.monotonic() < deadline and replacements < MAX_REPLACEMENTS:
    time.sleep(POLL_INTERVAL)
    status = client.orderstatus(order_id=order_id, strategy=strategy)
    if is_filled(status):
        px = avg_fill_price(status)
        journal.write(strategy=strategy, symbol=SYMBOL, exchange=EXCHANGE,
                      action=ACTION, event="filled", order_id=order_id,
                      average_price=px)
        msg = (f"[REPLACE FILLED] {ACTION} {QUANTITY} {SYMBOL} @ Rs {px}\n"
               f"replacements used: {replacements}")
        print("\n" + msg)
        notify(client, msg, via=("telegram",))
        journal.close()
        raise SystemExit()
    if is_terminal(status):
        print("order terminal:", status["data"].get("order_status"))
        break

    cur_ltp = extract_ltp(client.quotes(symbol=SYMBOL, exchange=EXCHANGE))
    move_pct = (cur_ltp / limit - 1) * 100

    # For BUY: bad direction = LTP rising past our limit by trigger pct
    if ACTION == "BUY" and move_pct >= REPLACE_TRIGGER_PCT:
        print(f"LTP {cur_ltp} ran {move_pct:+.2f}% past limit {limit} -- re-anchoring")
        cancel_with_retry(client, order_id=order_id, strategy=strategy)
        limit = anchor(cur_ltp * (1 + INITIAL_OFFSET_PCT / 100))
        resp = place_with_retry(
            client, strategy=strategy, symbol=SYMBOL, exchange=EXCHANGE,
            action=ACTION, price_type="LIMIT", product=PRODUCT,
            quantity=QUANTITY, price=limit,
        )
        order_id = extract_orderid(resp)
        replacements += 1
        journal.write(strategy=strategy, symbol=SYMBOL, exchange=EXCHANGE,
                      action=ACTION, event="replaced", order_id=order_id,
                      price=limit)
        print(f"  new LIMIT @ Rs {limit}   order {order_id}")

    # For SELL: bad direction = LTP falling past
    elif ACTION == "SELL" and move_pct <= -REPLACE_TRIGGER_PCT:
        print(f"LTP {cur_ltp} ran {move_pct:+.2f}% past limit {limit} -- re-anchoring")
        cancel_with_retry(client, order_id=order_id, strategy=strategy)
        limit = anchor(cur_ltp * (1 + INITIAL_OFFSET_PCT / 100))
        resp = place_with_retry(
            client, strategy=strategy, symbol=SYMBOL, exchange=EXCHANGE,
            action=ACTION, price_type="LIMIT", product=PRODUCT,
            quantity=QUANTITY, price=limit,
        )
        order_id = extract_orderid(resp)
        replacements += 1

# ---- Timed out without fill --------------------------------------------

cancel_with_retry(client, order_id=order_id, strategy=strategy)
journal.write(strategy=strategy, symbol=SYMBOL, exchange=EXCHANGE,
              action=ACTION, event="abandoned", order_id=order_id,
              extra=f"replacements={replacements}")
msg = (f"[REPLACE ABANDONED] {ACTION} {QUANTITY} {SYMBOL}\n"
       f"replacements used: {replacements}/{MAX_REPLACEMENTS}\n"
       f"last limit: Rs {limit}")
print("\n" + msg)
notify(client, msg, via=("telegram",))
journal.close()
