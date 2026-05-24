# Custom Execution Algorithms — Reference

Three execution primitives that compose the basic SDK calls into
intelligent multi-step algorithms:

| Algo | Class | Use case |
|------|-------|----------|
| Limit-order chaser | `scripts.execution.LimitChaser` | track the touch, modify on move, optional MARKET fallback |
| TWAP slicer | `scripts.execution.TWAPSlicer` | break parent into N equal time-spaced children |
| Iceberg slicer | `scripts.execution.IcebergSlicer` | display only N at a time at a fixed limit |

All three are response-aware: they read `depth`, `orderstatus`, and use
helpers from `scripts.responses` to know when to advance, modify, or
give up.

For the simplest user-facing version of "place + auto-SL + auto-target"
see [`scripts.workflows.place_with_sl_target`](../scripts/workflows.py).

---

## Limit-order chaser

Peg a LIMIT order to the touch. For a BUY, place at `best_bid` and
modify upwards whenever the bid ticks higher. For a SELL, place at
`best_ask` and modify downwards.

The chaser only modifies in the *direction the market is moving against
us* — if a BUY chaser sees the bid tick down, we keep our existing
favorable queue position rather than chase ourselves into a worse
price.

### Algorithm

```
1. depth() -> best_bid (BUY) or best_ask (SELL)        | touch
2. placeorder(LIMIT, action, price=touch)              | initial
3. loop:
       sleep(poll_interval_sec)
       orderstatus(orderid)
         -> if complete: record fill, exit
         -> if reject/cancel: exit
       depth() -> new_touch
       if new_touch moved >= tick_size in unfavourable direction
          AND within max_chase_ticks of initial:
              modifyorder(price=new_touch)
       if deadline reached:
           on_timeout = cancel | market
```

### Config

```python
from scripts.execution import LimitChaser, ChaserConfig

cfg = ChaserConfig(
    symbol="RELIANCE",
    exchange="NSE",
    action="BUY",
    quantity=10,
    product="MIS",
    strategy="reliance_chaser",
    tick_size=0.05,
    poll_interval_sec=1.0,
    timeout_sec=120.0,
    max_chase_ticks=5,
    on_timeout="cancel",    # or "market"
    journal_path="openalgo_workspace/execution_algos/reliance_chase/fills.csv",
    confirm=True,
)
state = LimitChaser(client, cfg).run()
```

### Result fields

```python
state.filled          # bool
state.filled_qty      # int
state.average_price   # float | None
state.initial_price   # float | None
state.current_price   # float | None
state.fills           # list[dict] — per-modify journal entries
state.order_id        # broker order id
```

### Per-event journal

The chaser writes one row per phase to `chaser_<symbol>.csv` (or a
custom path via `cfg.journal_path`). Columns:

```
ts, event, symbol, action, price, qty, order_id, extra
```

Events emitted: `placed`, `modified`, `modify_failed`, `filled`,
`timeout_cancelled`, `timeout_to_market`, `market_filled`, `aborted`, `terminal`.

### When NOT to use a chaser

- **Volatile open / close minutes** — the touch ticks faster than
  `poll_interval_sec`; you will pay modify costs without gaining queue
  priority.
- **Symbols with wide spreads** — chasing across a 1% spread is
  expensive; consider a midpoint LIMIT instead.
- **Very large quantity vs. depth** — a chaser at the touch will eat
  the visible book and slip. Use `TWAPSlicer` or `IcebergSlicer`.

---

## TWAP slicer

Break a parent order into N equal children spread evenly across a
duration. Each child runs through `LimitChaser` so we benefit from
queue position without parking far from the touch.

### Algorithm

```
sizes = [parent_qty // N] * N
sizes[-1] += parent_qty % N           # residual on last child
interval = duration_sec / N

for i, qty in enumerate(sizes):
    LimitChaser(qty, timeout=chaser_timeout_sec).run()
    sleep(max(0, interval - chaser_timeout_sec))
```

### Config

```python
from scripts.execution import TWAPSlicer, TWAPConfig

twap = TWAPSlicer(client, TWAPConfig(
    symbol="SBIN", exchange="NSE", action="BUY",
    total_quantity=1000, slices=10, duration_sec=600.0,
    product="MIS", strategy="sbin_twap",
    chaser_timeout_sec=30.0, tick_size=0.05,
))
results = twap.run()
print(twap.summary())
# {"parent_qty": 1000, "filled_qty": 980, "child_count": 10, "vwap": 776.43}
```

### Result

`twap.results` is a list of `ChaserState` — one per child. `twap.summary()` returns the aggregate parent VWAP across filled children.

### TWAP vs. VWAP-aware sizing

This implementation is **time-weighted only** — slices are equal in
size, evenly spaced. For volume-weighted execution where larger slices
land during higher historical volume periods, pre-compute slice sizes
from `client.history(interval='5m')` of the symbol's typical intraday
profile and pass custom sizes through a small wrapper.

---

## Iceberg slicer

Show only a small "display quantity" of a much larger parent at a
fixed limit price. When one child fills, place the next. Unlike a
venue-native iceberg, the broker sees a sequence of small orders — no
anonymity benefit, but you keep queue position discipline at a fixed
price level.

### Algorithm

```
total_filled = 0
while total_filled < parent_qty AND time_remaining:
    qty = min(display_qty, parent_qty - total_filled)
    placeorder(LIMIT, action, qty, price=fixed_price)
    poll_until_terminal()
        -> if filled: total_filled += qty
        -> else cancel + break
```

### Config

```python
from scripts.execution import IcebergSlicer, IcebergConfig

ice = IcebergSlicer(client, IcebergConfig(
    symbol="HDFCBANK", exchange="NSE", action="BUY",
    total_quantity=5000, display_quantity=500,
    price=1820.00, product="MIS", strategy="hdfc_iceberg",
    poll_interval_sec=0.5, overall_timeout_sec=900.0,
))
result = ice.run()
# {"filled_qty": 4500, "target_qty": 5000, "children": [...], "complete": False}
```

### When the price is not reached

The iceberg gives up rather than chase. If the first child does not
fill within `overall_timeout_sec / 10`, it cancels and stops. Switch
to `LimitChaser` (or its TWAP wrapper) if you need any-price execution.

---

## Composing your own — building blocks

The three algos above are just compositions of these primitives from
[`scripts.responses`](../scripts/responses.py) and
[`scripts.orders`](../scripts/orders.py):

```python
from scripts.orders         import place_with_retry, modify_with_retry, cancel_with_retry, poll_until_terminal
from scripts.responses      import extract_orderid, extract_touch, is_filled, is_terminal, avg_fill_price
from scripts.openalgo_client import get_client

# Pseudocode for your own algo:
client = get_client()
touch = extract_touch(client.depth(symbol="X", exchange="NSE"))
resp = place_with_retry(client, ..., price=touch["best_bid"])
order_id = extract_orderid(resp)

while True:
    status = client.orderstatus(order_id=order_id, strategy="...")
    if is_filled(status):
        fill = avg_fill_price(status)
        break
    if is_terminal(status):
        break
    new_touch = extract_touch(client.depth(symbol="X", exchange="NSE"))
    if my_condition(new_touch):
        modify_with_retry(client, order_id=order_id, ..., price=new_touch["best_bid"])
    time.sleep(1)
```

---

## Other execution patterns you may want

These are not (yet) bundled algos but are straightforward to assemble
from the building blocks:

### Time-based auto-cancel

```python
import time
from scripts.responses import extract_orderid, is_terminal, poll_until_terminal
from scripts.orders import cancel_with_retry, place_with_retry

resp = place_with_retry(client, ..., price_type="LIMIT", price=775.00)
order_id = extract_orderid(resp)
time.sleep(120)                      # park for 2 min
final = client.orderstatus(order_id=order_id, strategy="...")
if not is_terminal(final):
    cancel_with_retry(client, order_id=order_id, strategy="...")
```

### Price-based cancel and replace

```python
target_entry = 776.00
resp = place_with_retry(client, ..., price=target_entry)
order_id = extract_orderid(resp)

while True:
    ltp = extract_ltp(client.quotes(symbol="SBIN", exchange="NSE"))
    if ltp >= target_entry * 1.005:    # ran away
        cancel_with_retry(client, order_id=order_id, strategy="...")
        new_target = round(ltp * 20) / 20
        resp = place_with_retry(client, ..., price=new_target)
        order_id = extract_orderid(resp)
        target_entry = new_target
    final = client.orderstatus(order_id=order_id, strategy="...")
    if is_filled(final):
        break
    time.sleep(1)
```

### Conditional bracket — fill, then attach SL only if move > threshold

```python
fill_price = avg_fill_price(poll_until_filled(client, order_id=..., strategy=...))

# wait for first material move
while True:
    ltp = extract_ltp(client.quotes(symbol="SBIN", exchange="NSE"))
    if abs(ltp - fill_price) / fill_price >= 0.005:    # 0.5% move
        sl = round(fill_price * 0.995 * 20) / 20
        place_with_retry(client, ..., price_type="SL-M",
                         action="SELL", trigger_price=sl, quantity=qty)
        break
    time.sleep(1)
```

These patterns belong in [`examples/07_execution_algos/`](../examples/07_execution_algos/) — copy as starting points.
