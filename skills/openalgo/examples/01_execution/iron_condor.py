"""Place an iron condor via `optionsmultiorder` and verify each leg.

Iron condor: sell an OTM CE spread + sell an OTM PE spread. Net
short premium, defined risk on both sides.

Workflow:
1. Pre-flight: margin check via `client.margin`
2. Pre-flight: cash check vs. `client.funds`
3. Place 4 legs in one call via `optionsmultiorder`
4. Inspect `results[]` — each leg can independently fail
5. For each successfully placed leg, poll for fill and journal it
6. Send a WhatsApp summary

Output folder: openalgo_workspace/execution/iron_condor_nifty/
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.alerts import notify
from scripts.openalgo_client import default_strategy_tag, get_client
from scripts.responses import (
    avg_fill_price, available_cash, extract_orderids_basket,
    poll_until_filled, total_margin_required,
)
from scripts.trade_logger import open_journal

# ---- config --------------------------------------------------------------

UNDERLYING = "NIFTY"
UNDERLYING_EXCHANGE = "NSE_INDEX"
EXPIRY = "30JUN26"
QUANTITY = 75                     # 1 lot per leg

# Wing widths (offsets from ATM, in strikes)
SHORT_OFFSET = "OTM4"             # short call/put close to spot
LONG_OFFSET = "OTM6"              # long wings further out

ALERTS = ("telegram", "whatsapp")

# ---- bootstrap -----------------------------------------------------------

client = get_client()
strategy = f"{default_strategy_tag()}_iron_condor"

workdir = Path(f"openalgo_workspace/execution/iron_condor_{UNDERLYING.lower()}")
workdir.mkdir(parents=True, exist_ok=True)
journal = open_journal(workdir / "journal.csv")

# ---- 1 + 2. pre-flight margin + cash check -----------------------------

# Build the four legs
LEGS = [
    {"offset": LONG_OFFSET,  "option_type": "CE", "action": "BUY",  "quantity": QUANTITY},
    {"offset": LONG_OFFSET,  "option_type": "PE", "action": "BUY",  "quantity": QUANTITY},
    {"offset": SHORT_OFFSET, "option_type": "CE", "action": "SELL", "quantity": QUANTITY},
    {"offset": SHORT_OFFSET, "option_type": "PE", "action": "SELL", "quantity": QUANTITY},
]

# Margin calculator wants explicit symbols. Resolve via optionsymbol first.
priced_legs = []
for leg in LEGS:
    sym_resp = client.optionsymbol(
        underlying=UNDERLYING, exchange=UNDERLYING_EXCHANGE,
        expiry_date=EXPIRY, offset=leg["offset"], option_type=leg["option_type"],
    )
    priced_legs.append({
        "symbol": sym_resp["symbol"],
        "exchange": sym_resp["exchange"],
        "action": leg["action"],
        "product": "NRML",
        "pricetype": "MARKET",
        "quantity": str(leg["quantity"]),
    })

margin_resp = client.margin(positions=priced_legs)
margin_needed = total_margin_required(margin_resp)
cash = available_cash(client.funds())
print(f"Margin required: Rs {margin_needed:,.2f}")
print(f"Available cash:  Rs {cash:,.2f}")
if margin_needed > cash * 0.9:
    raise SystemExit(f"insufficient buffer: need Rs {margin_needed:,.2f}, have Rs {cash:,.2f}")

# ---- 3. Place the multi-leg order ---------------------------------------

print(f"\nPlacing iron condor: SELL {SHORT_OFFSET}, BUY {LONG_OFFSET}")
for leg in priced_legs:
    journal.write(strategy=strategy, symbol=leg["symbol"], exchange=leg["exchange"],
                  action=leg["action"], event="planned", quantity=int(leg["quantity"]))

resp = client.optionsmultiorder(
    strategy=strategy,
    underlying=UNDERLYING,
    exchange=UNDERLYING_EXCHANGE,
    expiry_date=EXPIRY,
    legs=LEGS,
)

# ---- 4 + 5. Per-leg verification ---------------------------------------

print(f"\nMulti-order response: status={resp.get('status')}, "
      f"underlying_ltp={resp.get('underlying_ltp')}")

success_legs = [r for r in resp.get("results", []) if r.get("status") == "success"]
failed_legs = [r for r in resp.get("results", []) if r.get("status") != "success"]

for leg in success_legs:
    print(f"  leg{leg.get('leg')} {leg.get('action')} {leg.get('symbol')} -> id {leg.get('orderid')}")
    journal.write(strategy=strategy, symbol=leg.get("symbol"), exchange="NFO",
                  action=leg.get("action"), event="placed",
                  order_id=leg.get("orderid"))

if failed_legs:
    print(f"\nWARNING: {len(failed_legs)} legs failed:")
    for f in failed_legs:
        print(f"  leg{f.get('leg')} {f.get('action')} -> {f.get('message')}")

# Poll each successful leg for fill
filled_premium = 0.0
for leg in success_legs:
    try:
        final = poll_until_filled(
            client, order_id=str(leg["orderid"]), strategy=strategy,
            interval_sec=1.0, timeout_sec=30.0,
        )
        px = avg_fill_price(final)
        signed = px * QUANTITY if leg["action"] == "SELL" else -px * QUANTITY
        filled_premium += signed
        journal.write(strategy=strategy, symbol=leg.get("symbol"), exchange="NFO",
                      action=leg.get("action"), event="filled",
                      order_id=leg.get("orderid"),
                      average_price=px, quantity=QUANTITY)
        print(f"    filled {leg['symbol']} @ Rs {px}")
    except Exception as exc:
        print(f"    {leg['symbol']} not filled within timeout: {exc}")

# ---- 6. Alert summary ---------------------------------------------------

summary = (
    f"[IRON CONDOR PLACED]\n"
    f"Underlying:  {UNDERLYING} {EXPIRY}\n"
    f"Short wing:  {SHORT_OFFSET}    Long wing: {LONG_OFFSET}\n"
    f"Legs placed: {len(success_legs)}/4   filled premium: Rs {filled_premium:,.2f}\n"
    f"Margin used: Rs {margin_needed:,.2f}"
)
notify(client, summary, via=ALERTS)
print("\n" + summary)
print(f"Journal: {workdir / 'journal.csv'}")
journal.close()
