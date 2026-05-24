"""Rebalance a basket of equity positions to a target weight.

Workflow:
1. Read current holdings via `client.holdings()`
2. Compute target rupee allocation per symbol (equal-weight or custom)
3. For each symbol: quote -> compute delta qty (target - current)
4. Place all rebalancing orders in one `basketorder` call
5. Verify per-leg success; alert summary

Output folder: openalgo_workspace/execution/basket_rebalance/
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.alerts import notify
from scripts.openalgo_client import default_strategy_tag, get_client
from scripts.responses import (
    available_cash, ensure_success, extract_ltp, extract_orderids_basket,
)
from scripts.trade_logger import open_journal

# ---- config --------------------------------------------------------------

TARGET_WEIGHTS = {     # symbol -> portfolio weight (must sum <= 1.0)
    "RELIANCE":   0.20,
    "TCS":        0.15,
    "INFY":       0.15,
    "HDFCBANK":   0.20,
    "ICICIBANK":  0.15,
    "SBIN":       0.15,
}
EXCHANGE = "NSE"
PRODUCT = "CNC"
TARGET_DEPLOYED_PCT = 90       # use 90% of available cash; keep 10% buffer

ALERTS = ("telegram",)

# ---- bootstrap -----------------------------------------------------------

client = get_client()
strategy = f"{default_strategy_tag()}_rebalance"
workdir = Path("openalgo_workspace/execution/basket_rebalance")
workdir.mkdir(parents=True, exist_ok=True)
journal = open_journal(workdir / "journal.csv")

# ---- 1. Current holdings -------------------------------------------------

holdings = client.holdings()
holdings_data = (holdings.get("data") or {}).get("holdings", []) if isinstance(holdings, dict) else []
current_qty = {h["symbol"].upper(): int(h["quantity"]) for h in holdings_data
               if h.get("exchange") == EXCHANGE and h.get("product") == PRODUCT}
print(f"Current holdings on {EXCHANGE}/{PRODUCT}: {current_qty}")

# ---- 2. Compute target rupee allocation ---------------------------------

cash = available_cash(client.funds())
holdings_value = sum(float(h.get("pnl", 0)) + float(h.get("quantity", 0)) * float(h.get("average_price", 0))
                     for h in holdings_data)
deployable = (cash + holdings_value) * TARGET_DEPLOYED_PCT / 100
print(f"Available cash: Rs {cash:,.2f}   estimated total: Rs {cash + holdings_value:,.2f}")
print(f"Deploying:      Rs {deployable:,.2f}")

# ---- 3. Build per-symbol orders -----------------------------------------

orders_to_place = []
for symbol, weight in TARGET_WEIGHTS.items():
    target_rs = deployable * weight
    quote = client.quotes(symbol=symbol, exchange=EXCHANGE)
    ltp = extract_ltp(quote)
    target_qty = int(target_rs // ltp)
    current = current_qty.get(symbol, 0)
    delta = target_qty - current

    print(f"  {symbol:<10} LTP {ltp:>8.2f}  current {current:>5d}  target {target_qty:>5d}  delta {delta:>+5d}")
    if delta == 0:
        continue

    orders_to_place.append({
        "symbol": symbol,
        "exchange": EXCHANGE,
        "action": "BUY" if delta > 0 else "SELL",
        "quantity": abs(delta),
        "pricetype": "MARKET",
        "product": PRODUCT,
    })
    journal.write(strategy=strategy, symbol=symbol, exchange=EXCHANGE,
                  action="BUY" if delta > 0 else "SELL", event="planned",
                  quantity=abs(delta), price=ltp)

# ---- 4. Confirm + place as a basket -------------------------------------

if not orders_to_place:
    print("\nPortfolio already at target weights. Nothing to do.")
    raise SystemExit()

print(f"\nPlacing {len(orders_to_place)} orders as a basket.")
if input("Confirm? [y/N] ").strip().lower() != "y":
    raise SystemExit("aborted")

resp = client.basketorder(orders=orders_to_place)
ensure_success(resp, action="basketorder")
success_ids = extract_orderids_basket(resp)
print(f"\n{len(success_ids)}/{len(orders_to_place)} legs placed successfully")

# ---- 5. Per-leg journal + alert -----------------------------------------

for leg, oid in zip(orders_to_place, success_ids):
    journal.write(strategy=strategy, symbol=leg["symbol"], exchange=EXCHANGE,
                  action=leg["action"], event="placed", order_id=oid,
                  quantity=leg["quantity"])

failed = [r for r in resp.get("results", []) if r.get("status") != "success"]
summary = (
    f"[REBALANCE COMPLETE]\n"
    f"Symbols changed: {len(orders_to_place)}\n"
    f"Legs filled OK:  {len(success_ids)}\n"
    f"Legs failed:     {len(failed)}\n"
    f"Deployed:        Rs {deployable:,.2f}"
)
notify(client, summary, via=ALERTS)
print("\n" + summary)
print(f"Journal: {workdir / 'journal.csv'}")

journal.close()
