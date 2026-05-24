"""Place an entry order and chain SL + target based on the actual fill.

The canonical response-aware execution example. Uses
`scripts.workflows.place_with_sl_target` which internally:

    1. placeorder(MARKET or LIMIT)
    2. orderstatus(...) — poll until 'complete'
    3. read data.average_price from the fill
    4. compute SL  = fill * (1 - sl_pct/100)
       compute TGT = fill * (1 + target_pct/100)
    5. placeorder(SL-M, action=opposite, trigger_price=SL)
    6. placeorder(LIMIT, action=opposite, price=TGT)
    7. journal all three events + alert phone

Output folder: openalgo_workspace/execution/<symbol>_with_sl_target/
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.openalgo_client import default_strategy_tag, get_client
from scripts.trade_logger import open_journal
from scripts.workflows import place_with_sl_target

# ---- config --------------------------------------------------------------

SYMBOL = "SBIN"
EXCHANGE = "NSE"
ACTION = "BUY"
QUANTITY = 10
PRODUCT = "MIS"

SL_PCT = 1.0        # 1% below fill
TGT_PCT = 2.0       # 2% above fill (1:2 R/R)

ALERTS = ("telegram", "whatsapp")

# ---- bootstrap -----------------------------------------------------------

client = get_client()
strategy = default_strategy_tag()

workdir = Path(f"openalgo_workspace/execution/{SYMBOL.lower()}_with_sl_target")
workdir.mkdir(parents=True, exist_ok=True)
journal = open_journal(workdir / "journal.sqlite")

# ---- analyzer banner ----------------------------------------------------

mode = client.analyzerstatus().get("data", {}).get("mode", "unknown")
print(f"[{mode.upper()}]  {ACTION} {QUANTITY} {SYMBOL} @ {EXCHANGE}  "
      f"product={PRODUCT}  SL={SL_PCT}%  target={TGT_PCT}%")

if mode != "analyze":
    if input("Confirm LIVE entry with auto SL+target? [y/N] ").strip().lower() != "y":
        raise SystemExit("aborted")

# ---- execute ------------------------------------------------------------

result = place_with_sl_target(
    client,
    strategy=strategy,
    symbol=SYMBOL,
    exchange=EXCHANGE,
    action=ACTION,
    quantity=QUANTITY,
    product=PRODUCT,
    price_type="MARKET",
    sl_pct=SL_PCT,
    target_pct=TGT_PCT,
    fill_poll_interval_sec=0.5,
    fill_timeout_sec=30.0,
    journal=journal,
    alert_via=ALERTS,
)

# ---- summary -----------------------------------------------------------

print("\n--- Workflow result ---")
print(f"  Entry order: {result.entry_order_id}")
print(f"  Filled qty:  {result.entry_qty}")
print(f"  Fill price:  Rs {result.entry_avg_price}")
print(f"  SL order:    {result.sl_order_id}  trigger Rs {result.sl_trigger}")
print(f"  Target ord:  {result.target_order_id}  price Rs {result.target_price}")
print(f"  Journal:     {workdir / 'journal.sqlite'}")

journal.close()
