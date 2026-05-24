"""Place a single equity LIMIT order with quote-anchored pricing.

Workflow:
1. Quote the symbol to get current LTP
2. Compute a marketable LIMIT a few ticks past LTP (safer than MARKET)
3. Show a preview, ask for confirmation
4. Place via place_with_retry (handles transient rate limits)
5. Print the resulting orderid

Output folder: openalgo_workspace/execution/place_equity_<SYMBOL>/
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make scripts/ importable when running this file directly
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.openalgo_client import default_strategy_tag, get_client
from scripts.orders import OrderPreview, confirm_interactive, place_with_retry
from scripts.responses import extract_ltp, extract_orderid

# ---- config --------------------------------------------------------------

SYMBOL = "RELIANCE"
EXCHANGE = "NSE"
ACTION = "BUY"
QUANTITY = 1
PRODUCT = "MIS"               # MIS (intraday) | CNC (delivery)
SLIPPAGE_PCT = 0.15           # marketable-limit cushion past LTP

# ---- bootstrap -----------------------------------------------------------

client = get_client()
strategy = default_strategy_tag()

# ---- 1. Quote ------------------------------------------------------------

quote_resp = client.quotes(symbol=SYMBOL, exchange=EXCHANGE)
ltp = extract_ltp(quote_resp)
print(f"LTP {SYMBOL}@{EXCHANGE} = Rs {ltp}")

# ---- 2. Compute limit price ---------------------------------------------

if ACTION == "BUY":
    raw_price = ltp * (1 + SLIPPAGE_PCT / 100)
else:
    raw_price = ltp * (1 - SLIPPAGE_PCT / 100)
limit_price = round(raw_price * 20) / 20      # NSE tick = 0.05

# ---- 3. Preview + confirm -----------------------------------------------

preview = OrderPreview(
    strategy=strategy,
    symbol=SYMBOL,
    exchange=EXCHANGE,
    action=ACTION,
    quantity=QUANTITY,
    price_type="LIMIT",
    product=PRODUCT,
    price=limit_price,
    notional=limit_price * QUANTITY,
    note=f"LTP {ltp}; slippage cushion {SLIPPAGE_PCT}%",
)
if not confirm_interactive(preview):
    raise SystemExit("aborted by user")

# ---- 4. Place ------------------------------------------------------------

response = place_with_retry(
    client,
    strategy=strategy,
    symbol=SYMBOL,
    exchange=EXCHANGE,
    action=ACTION,
    price_type="LIMIT",
    product=PRODUCT,
    quantity=QUANTITY,
    price=limit_price,
)

# ---- 5. Read the response -----------------------------------------------

try:
    order_id = extract_orderid(response)
    print(f"\nORDER PLACED  id={order_id}  {ACTION} {QUANTITY} {SYMBOL} @ Rs {limit_price}")
except Exception as exc:
    print(f"\nORDER FAILED: {exc}\nRaw response: {response}")
    raise
