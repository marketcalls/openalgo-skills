# Common Workflows — Response-Chained Recipes

This file is the heart of the response-aware design. Every workflow
below shows the full chain:

> `endpoint A` -> read field X from response -> feed into `endpoint B` -> read field Y -> ...

These recipes are also wrapped as one-call functions in [`scripts/workflows.py`](../scripts/workflows.py). Use the helpers in production; consult the explicit step-by-step here when you need to understand or adapt them.

Conventions used throughout:

```python
import os
from dotenv import find_dotenv, load_dotenv
from openalgo import api
from scripts.openalgo_client import get_client, default_strategy_tag
from scripts.responses import (
    ensure_success, extract_orderid, poll_until_filled,
    avg_fill_price, is_filled, extract_ltp, extract_touch,
    open_position_qty, atm_strike_from_chain,
)
from scripts.alerts import notify, alert_order_lifecycle, fmt_daily_pnl
from scripts.trade_logger import open_journal

load_dotenv(find_dotenv(), override=False)
client = get_client()
STRAT = default_strategy_tag()
```

---

## 1. Order then SL/Target on Actual Fill

**The canonical chain.** Place an order, wait for the fill, and place
the SL / target based on the *real* average fill price — never on the
intended entry. This is critical because slippage on a MARKET order
can move the entry by 0.5%+ in volatile names, and a SL computed from
the intended price would be too close to noise.

### Steps

1. `client.placeorder(...)`         -> read `response["orderid"]`
2. `client.orderstatus(orderid)`    -> poll until `data.order_status == "complete"`
3. Read `data.average_price`        -> this is the real fill price
4. Compute `sl_trigger  = fill * (1 - sl_pct/100)`  (for BUY)
5. Compute `target_px   = fill * (1 + target_pct/100)`
6. `client.placeorder(SL-M, action="SELL", trigger_price=sl_trigger)`
7. `client.placeorder(LIMIT, action="SELL", price=target_px)`
8. Alert all three events to phone

### Manual code

```python
# 1. place the entry
entry_resp = client.placeorder(
    strategy=STRAT, symbol="RELIANCE", exchange="NSE",
    action="BUY", price_type="MARKET", product="MIS",
    quantity="10", price="0", trigger_price="0",
)
order_id = extract_orderid(entry_resp)
print(f"placed entry {order_id}")

# 2 + 3. wait until filled, get average price
status = poll_until_filled(client, order_id=order_id,
                           strategy=STRAT, interval_sec=0.5,
                           timeout_sec=30.0)
fill = avg_fill_price(status)         # the value everything else hangs off
qty  = int(status["data"]["quantity"])
print(f"filled {qty} @ Rs {fill}")

# 4 + 5. compute SL and target from the fill
sl_pct, target_pct = 1.0, 2.0          # 1% SL, 2% target
sl_trigger = round((fill * (1 - sl_pct / 100)) * 20) / 20   # round to 0.05
target_px  = round((fill * (1 + target_pct / 100)) * 20) / 20

# 6. SL-M order
sl_resp = client.placeorder(
    strategy=STRAT, symbol="RELIANCE", exchange="NSE",
    action="SELL", price_type="SL-M", product="MIS",
    quantity=str(qty), price="0", trigger_price=str(sl_trigger),
)
sl_id = extract_orderid(sl_resp)

# 7. target LIMIT order
tgt_resp = client.placeorder(
    strategy=STRAT, symbol="RELIANCE", exchange="NSE",
    action="SELL", price_type="LIMIT", product="MIS",
    quantity=str(qty), price=str(target_px), trigger_price="0",
)
tgt_id = extract_orderid(tgt_resp)

# 8. broadcast to phone
alert_order_lifecycle(
    client,
    filled=dict(
        strategy=STRAT, symbol="RELIANCE", action="BUY",
        quantity=qty, average_price=fill, order_id=order_id,
        sl_price=sl_trigger, target_price=target_px,
    ),
    via=("telegram", "whatsapp"),
)

print(f"entry={order_id}  fill={fill}  SL={sl_id}@{sl_trigger}  TGT={tgt_id}@{target_px}")
```

### Helper equivalent

```python
from scripts.workflows import place_with_sl_target

result = place_with_sl_target(
    client,
    strategy=STRAT, symbol="RELIANCE", exchange="NSE",
    action="BUY", quantity=10, product="MIS",
    price_type="MARKET",
    sl_pct=1.0, target_pct=2.0,
    alert_via=("telegram", "whatsapp"),
    journal=open_journal("openalgo_workspace/execution/reliance/journal.csv"),
)

print(result.entry_avg_price, result.sl_order_id, result.target_order_id)
```

---

## 2. ATM Straddle With Percentage SL on Premium

Sell ATM CE + sell ATM PE, then place a SL above each premium fill.
This is the response-aware version of the textbook short-straddle:
because the SL is computed **after** seeing the actual premium fill,
it adapts to whatever IV regime the market is currently in.

### Steps

1. `client.optionsymbol(offset='ATM', option_type='CE')`  -> resolve CE symbol
2. `client.optionsymbol(offset='ATM', option_type='PE')`  -> resolve PE symbol
3. `client.placeorder(SELL, CE_symbol)`                   -> CE entry id
4. `client.placeorder(SELL, PE_symbol)`                   -> PE entry id
5. Poll both `orderstatus`                                -> premiums filled
6. `client.placeorder(BUY, SL-M, trigger = premium * 1.3)` per leg -> SL ids
7. Alert with both legs' premiums and SLs

### Helper equivalent

```python
from scripts.workflows import enter_options_atm_with_sl

ce = enter_options_atm_with_sl(
    client, underlying="NIFTY", underlying_exchange="NSE_INDEX",
    expiry_date="30JUN26", option_type="CE", offset="ATM",
    quantity=75, sl_pct=30.0, alert_via=("whatsapp",),
)
pe = enter_options_atm_with_sl(
    client, underlying="NIFTY", underlying_exchange="NSE_INDEX",
    expiry_date="30JUN26", option_type="PE", offset="ATM",
    quantity=75, sl_pct=30.0, alert_via=("whatsapp",),
)
print(f"straddle CE@{ce.entry_avg_price} SL={ce.sl_trigger}")
print(f"straddle PE@{pe.entry_avg_price} SL={pe.sl_trigger}")
```

---

## 3. Reverse Position on Signal (Long -> Short Flip)

`placesmartorder` handles the math, but the *intelligent* version first
queries `openposition` to know the current state so the alert message
can describe the flip clearly.

### Steps

1. `client.openposition(symbol)`         -> read `quantity` (signed)
2. Compute `delta = target - current`
3. If delta == 0 -> skip (no-op)
4. `client.placesmartorder(quantity=abs(delta), position_size=target)`
5. Alert "flipped LONG 10 -> SHORT 5"

### Manual code

```python
op = client.openposition(strategy=STRAT, symbol="SBIN",
                         exchange="NSE", product="MIS")
current = open_position_qty(op)
target = -5

if current == target:
    print("already at target; no-op")
elif current != target:
    delta = target - current
    resp = client.placesmartorder(
        strategy=STRAT, symbol="SBIN", exchange="NSE",
        action="BUY" if delta > 0 else "SELL",
        price_type="MARKET", product="MIS",
        quantity=abs(delta), position_size=target,
    )
    notify(client, f"SBIN flipped {current:+d} -> {target:+d}", via=("telegram",))
```

### Helper equivalent

```python
from scripts.workflows import place_smart_with_position_check

place_smart_with_position_check(
    client, strategy=STRAT,
    symbol="SBIN", exchange="NSE",
    action="SELL",          # ignored when target_position is sufficient
    target_position=-5,
    product="MIS",
    alert_via=("telegram",),
)
```

---

## 4. Limit-Order Chaser with Phone Alerts

Place a marketable LIMIT at the touch, modify whenever the touch
moves, alert on each phase change. Full implementation lives in
[`scripts/execution.py::LimitChaser`](../scripts/execution.py); here is
the canonical wiring with alerts:

```python
from scripts.execution import LimitChaser, ChaserConfig

state = LimitChaser(
    client,
    ChaserConfig(
        symbol="RELIANCE", exchange="NSE", action="BUY",
        quantity=10, product="MIS", strategy=STRAT,
        tick_size=0.05, timeout_sec=120, on_timeout="market",
        confirm=False,
        journal_path="openalgo_workspace/execution_algos/reliance_chaser/fills.csv",
    ),
).run()

if state.filled:
    notify(
        client,
        f"Chaser filled {state.filled_qty} RELIANCE @ Rs {state.average_price}",
        via=("telegram", "whatsapp"),
    )
else:
    notify(client, "Chaser timeout — no fill", via=("telegram",))
```

The chaser does its own per-modify journaling and analyzer-mode banner.

---

## 5. Daily Cleanup with P&L Alert

End-of-day routine: square off everything, capture realized P&L, send
a one-screen WhatsApp summary.

### Steps

1. `client.closeposition(strategy)`    -> all positions flat
2. `client.funds()`                    -> read `data.m2mrealized`, `data.availablecash`
3. `client.orderbook()`                -> read `data.statistics.total_completed_orders`
4. `client.positionbook()`             -> count rows with non-zero quantity (should be 0)
5. Format and send

### Manual code

```python
close_resp = client.closeposition(strategy=STRAT)

funds = client.funds()
data = funds["data"]
realized   = float(data["m2mrealized"])
unrealized = float(data["m2munrealized"])
cash       = float(data["availablecash"])

ob = client.orderbook()
completed = int(ob["data"]["statistics"]["total_completed_orders"])

pb = client.positionbook()
open_pos = sum(1 for p in pb["data"] if int(p["quantity"]) != 0)

notify(
    client,
    fmt_daily_pnl(
        realized=realized, unrealized=unrealized,
        available_cash=cash, open_positions=open_pos,
        completed_orders=completed,
    ),
    via=("telegram", "whatsapp"),
)
```

### Helper equivalent

```python
from scripts.workflows import square_off_with_alert
square_off_with_alert(client, strategy=STRAT, alert_via=("telegram", "whatsapp"))
```

---

## 6. Scanner -> Top 10 -> Alert with CSV

Run a scan, save results to CSV, send the top 10 by % change via
WhatsApp with the CSV attached as a document.

```python
from datetime import date
from pathlib import Path

from scripts.scanner import Scanner, gainers, volume_surge
from scripts.alerts import fmt_scanner_results, notify, send_report

# 1. build universe + filters
nifty50 = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", ...]
df = (
    Scanner(client)
    .add_many(nifty50, exchange="NSE")
    .with_filter(gainers(threshold_pct=1.0))
    .with_filter(volume_surge(multiplier=1.5))
    .quote_scan()
    .head(10)
)

# 2. persist
workdir = Path("openalgo_workspace/scanners/nifty50_breakouts")
workdir.mkdir(parents=True, exist_ok=True)
csv_path = workdir / f"results_{date.today()}.csv"
df.to_csv(csv_path, index=False)

# 3. summarize + alert
top_rows = df.to_dict("records")
summary = fmt_scanner_results(
    title="NIFTY 50 Gainers + Volume Surge",
    rows=top_rows,
    fields=["symbol", "ltp", "pct_change", "volume"],
    max_rows=10,
)
notify(client, summary, via=("telegram",))
send_report(client, csv_path, caption=summary)
```

---

## 7. Place Order -> Track Until Terminal -> Journal

Verbose journaling pattern for any single-leg trade. Useful inside
scheduled jobs where the operator wants a complete paper trail.

```python
from scripts.trade_logger import open_journal
from scripts.responses import poll_until_filled

journal = open_journal("openalgo_workspace/execution/sbin_eod/journal.sqlite")

# 1. preview + place
resp = client.placeorder(
    strategy="sbin_eod", symbol="SBIN", exchange="NSE",
    action="BUY", price_type="LIMIT", product="CNC",
    quantity="10", price="775.00", trigger_price="0",
)
order_id = extract_orderid(resp)
journal.write(strategy="sbin_eod", symbol="SBIN", exchange="NSE",
              action="BUY", event="placed", order_id=order_id,
              price=775.00, quantity=10)

# 2. wait for terminal
try:
    final = poll_until_filled(client, order_id=order_id,
                              strategy="sbin_eod",
                              interval_sec=1.0, timeout_sec=120)
    journal.write(strategy="sbin_eod", symbol="SBIN", exchange="NSE",
                  action="BUY", event="filled", order_id=order_id,
                  average_price=avg_fill_price(final),
                  quantity=int(final["data"]["quantity"]))
except ResponseError as exc:
    journal.write(strategy="sbin_eod", symbol="SBIN", exchange="NSE",
                  action="BUY", event="rejected_or_cancelled",
                  order_id=order_id, extra=str(exc))

journal.close()
```

---

## 8. Quote-Anchored Marketable LIMIT (safer than MARKET)

Many traders default to MARKET because LIMIT requires picking a price.
Use the quote to pick a sensible limit a few ticks past LTP and you get
the speed of MARKET with bounded slippage.

```python
from scripts.responses import extract_ltp

q = client.quotes(symbol="RELIANCE", exchange="NSE")
ltp = extract_ltp(q)
limit_price = round((ltp * 1.0015) * 20) / 20      # 0.15% above LTP, rounded to 0.05

resp = client.placeorder(
    strategy=STRAT, symbol="RELIANCE", exchange="NSE",
    action="BUY", price_type="LIMIT", product="MIS",
    quantity="5", price=str(limit_price), trigger_price="0",
)
print(extract_orderid(resp), "@", limit_price)
```

---

## 9. Options Chain -> Pick Strike by Delta -> Place

Real strategies pick option strikes by delta target (e.g. 25-delta
strangle), not by offset. Walk the chain, compute Greeks per strike,
pick the closest.

```python
from scripts.option_analytics import chain_to_df, iv_skew

# 1. chain
chain_resp = client.optionchain(
    underlying="NIFTY", exchange="NSE_INDEX",
    expiry_date="30JUN26", strike_count=30,
)
df = chain_to_df(chain_resp)
spot = chain_resp["underlying_ltp"]

# 2. compute Greeks for each CE strike
greeks_df = iv_skew(client, df, side="CE",
                    underlying="NIFTY",
                    underlying_exchange="NSE_INDEX")

# 3. pick the closest CE to 25-delta
target_delta = 0.25
greeks_df["delta_distance"] = (greeks_df["delta"] - target_delta).abs()
picked = greeks_df.sort_values("delta_distance").iloc[0]
ce_strike = picked["strike"]

# 4. fetch the exact symbol via optionsymbol or chain row
ce_row = df[(df["strike"] == ce_strike) & (df["side"] == "CE")].iloc[0]
ce_symbol = ce_row["symbol"]

# 5. place SELL
resp = client.placeorder(
    strategy=STRAT, symbol=ce_symbol, exchange="NFO",
    action="SELL", price_type="MARKET", product="NRML",
    quantity="75", price="0", trigger_price="0",
)
print(extract_orderid(resp), f"sold CE strike {ce_strike} delta {picked['delta']}")
```

---

## 10. Error Handling Across a Long-Running Loop

Strategies that run for hours need every iteration wrapped so one bad
tick does not kill the loop. Combine `ResponseError` with the alerting
helper for "fail loudly, recover automatically":

```python
import time
from scripts.responses import ResponseError
from scripts.alerts import fmt_error, notify

while market_open():
    try:
        # ... strategy iteration ...
        resp = client.quotes(symbol="NIFTY", exchange="NSE_INDEX")
        ltp = extract_ltp(resp)
        # ... decision logic ...
    except ResponseError as exc:
        msg = fmt_error(strategy=STRAT, where="loop", error=str(exc))
        notify(client, msg, via=("telegram",))
    except Exception as exc:
        msg = fmt_error(strategy=STRAT, where="loop:unexpected", error=repr(exc))
        notify(client, msg, via=("telegram",))
    finally:
        time.sleep(15)
```

This pattern combined with `scripts.workflows` lets you assemble production-quality strategies in well under 100 lines.

---

## Index of helper functions used above

| Helper | Module | Purpose |
|--------|--------|---------|
| `get_client()` | `scripts.openalgo_client` | bootstraps from .env |
| `default_strategy_tag()` | "" | reads `OPENALGO_DEFAULT_STRATEGY` |
| `ensure_success(resp)` | `scripts.responses` | raise on status != success |
| `extract_orderid(resp)` | "" | pull orderid from place/modify/cancel |
| `poll_until_filled(...)` | "" | block until terminal or timeout |
| `avg_fill_price(status)` | "" | read filled price from orderstatus |
| `is_filled(status)` | "" | terminal-filled predicate |
| `extract_ltp(quote)` | "" | LTP from quotes endpoint |
| `extract_touch(depth)` | "" | best bid / ask from depth |
| `open_position_qty(op)` | "" | signed qty from openposition |
| `atm_strike_from_chain(chain)` | "" | atm_strike field |
| `place_with_sl_target(...)` | `scripts.workflows` | entry + SL + target wrapped |
| `enter_options_atm_with_sl(...)` | "" | ATM CE/PE entry + SL |
| `square_off_with_alert(...)` | "" | EOD cleanup + alert |
| `place_smart_with_position_check(...)` | "" | smart-order with state pre-check |
| `notify(...)` | `scripts.alerts` | text alert dispatcher |
| `alert_order_lifecycle(...)` | "" | one-call template dispatcher |
| `send_chart(...)` | "" | image alert via WhatsApp |
| `send_report(...)` | "" | document alert via WhatsApp |
| `LimitChaser` | `scripts.execution` | peg-the-touch algo |
| `Scanner` | `scripts.scanner` | multi-symbol pipeline |
| `open_journal(path)` | `scripts.trade_logger` | CSV / SQLite journal |
