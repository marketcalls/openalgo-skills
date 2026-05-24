"""Limit-order chaser — peg the touch, modify on move, MARKET on timeout.

The flagship execution algo. Uses `scripts.execution.LimitChaser`:

    1. Read best_bid (BUY) or best_ask (SELL) via client.depth(...)
    2. placeorder(LIMIT, price=touch)              -> entry order id
    3. loop every poll_interval_sec:
         orderstatus(orderid) -> filled? terminal? continue.
         depth(...) -> new touch
         if touch moved 1 tick against us AND within max_chase_ticks:
             modifyorder(price=new_touch)
    4. on timeout: cancel OR convert to MARKET (configurable)

Output folder: openalgo_workspace/execution_algos/limit_chaser_<SYMBOL>/
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.alerts import notify
from scripts.execution import ChaserConfig, LimitChaser
from scripts.openalgo_client import default_strategy_tag, get_client

# ---- config ------------------------------------------------------------

SYMBOL = "RELIANCE"
EXCHANGE = "NSE"
ACTION = "BUY"          # BUY chases the bid; SELL chases the ask
QUANTITY = 5
PRODUCT = "MIS"
TICK_SIZE = 0.05        # NSE equity default
TIMEOUT_SEC = 120
MAX_CHASE_TICKS = 8     # bail if touch moves > 0.40 from initial
ON_TIMEOUT = "market"   # "cancel" or "market"

ALERTS = ("telegram",)

client = get_client()
strategy = f"{default_strategy_tag()}_chaser"

workdir = Path(f"openalgo_workspace/execution_algos/limit_chaser_{SYMBOL.lower()}")
workdir.mkdir(parents=True, exist_ok=True)

mode = client.analyzerstatus().get("data", {}).get("mode", "unknown")
print(f"[{mode.upper()}]  chaser  {ACTION} {QUANTITY} {SYMBOL}  "
      f"tick={TICK_SIZE}  timeout={TIMEOUT_SEC}s  on_timeout={ON_TIMEOUT}")

# ---- Run ---------------------------------------------------------------

chaser = LimitChaser(
    client,
    ChaserConfig(
        symbol=SYMBOL,
        exchange=EXCHANGE,
        action=ACTION,
        quantity=QUANTITY,
        product=PRODUCT,
        strategy=strategy,
        tick_size=TICK_SIZE,
        poll_interval_sec=1.0,
        timeout_sec=TIMEOUT_SEC,
        max_chase_ticks=MAX_CHASE_TICKS,
        on_timeout=ON_TIMEOUT,
        journal_path=str(workdir / "fills.csv"),
        confirm=(mode != "analyze"),
    ),
)
state = chaser.run()

# ---- Summary + alert ---------------------------------------------------

if state.filled:
    msg = (
        f"[CHASER FILLED]\n"
        f"{ACTION} {state.filled_qty} {SYMBOL}\n"
        f"Avg price: Rs {state.average_price}\n"
        f"Initial touch: Rs {state.initial_price}\n"
        f"Last touch:    Rs {state.current_price}\n"
        f"Order id:      {state.order_id}"
    )
else:
    msg = (
        f"[CHASER UNFILLED]\n"
        f"{ACTION} {QUANTITY} {SYMBOL}\n"
        f"Initial touch: Rs {state.initial_price}\n"
        f"Last touch:    Rs {state.current_price}\n"
        f"Timed out after {TIMEOUT_SEC}s   (on_timeout={ON_TIMEOUT})"
    )

print("\n" + msg)
notify(client, msg, via=ALERTS)
print(f"\nJournal: {workdir / 'fills.csv'}")
