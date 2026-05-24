# Order Information — Reference

Read-only endpoints for **post-placement** order state. Critical for any
response-aware workflow — every chain that needs the fill price, fill
quantity, or order state passes through `orderstatus`.

| Endpoint | Method | Returns |
|----------|--------|---------|
| Single order state | `client.orderstatus` | `{status, data{...}}` |
| Open position for symbol | `client.openposition` | `{status, quantity}` |

For multi-order queries see `orderbook` / `tradebook` / `positionbook` in [account-services.md](account-services.md).

---

## orderstatus

The single most-chained endpoint in the SDK. After every `placeorder`
or `modifyorder` you generally want to know: did it fill? at what
price? how much? `orderstatus` answers all three.

### Request

```python
client.orderstatus(
    order_id="250828000185002",
    strategy="python",          # must match the strategy used at placement
)
```

### Success Response

```json
{
  "status": "success",
  "data": {
    "action":        "BUY",
    "average_price": 18.95,
    "exchange":      "NSE",
    "order_status":  "complete",
    "orderid":       "250828000185002",
    "price":         0,
    "pricetype":     "MARKET",
    "product":       "MIS",
    "quantity":      "1",
    "symbol":        "YESBANK",
    "timestamp":     "28-Aug-2025 09:59:10",
    "trigger_price": 0
  }
}
```

### `data.order_status` values

| Value | Terminal? | What it means |
|-------|-----------|---------------|
| `open` | no | resting on the exchange book |
| `pending` | no | accepted by broker, en route to exchange |
| `trigger pending` | no | SL / SL-M waiting for trigger |
| `complete` | **yes** | fully filled — `average_price` valid |
| `partially filled` | no | some lots filled, rest still open |
| `cancelled` | **yes** | cancelled by user or by exchange |
| `rejected` | **yes** | rejected with `data.message` carrying the reason |

Broker plugins normalize most values but spellings can drift slightly. Use the helpers below which match case-insensitively.

### Read these fields

| Field | Helper | Used for |
|-------|--------|----------|
| `data.order_status` | `responses.is_filled(resp)` / `responses.is_terminal(resp)` | poll loop guard |
| `data.average_price` | `responses.avg_fill_price(resp)` | SL/target/journal price reference — **the value you compute stop and target from** |
| `data.quantity` | `responses.filled_quantity(resp)` | SL must match this, not the originally-intended quantity |
| `data.timestamp` | direct read | fill timestamp for journal |
| `data.action` | direct read | for log correlation when SL flips the side |

### Polling pattern (response-aware)

The canonical loop that turns "I placed an order" into "I know it filled at X":

```python
from scripts.responses import poll_until_filled, avg_fill_price

# 1. place
resp = client.placeorder(...)
order_id = resp["orderid"]

# 2. poll
status = poll_until_filled(
    client,
    order_id=order_id,
    strategy="python",
    interval_sec=0.5,
    timeout_sec=60.0,
)
# raises ResponseError if rejected/cancelled
# returns the last response (possibly still open) on timeout

# 3. read the fill
fill_price = avg_fill_price(status)
fill_qty   = int(status["data"]["quantity"])
print(f"filled {fill_qty} @ Rs {fill_price}")
```

`poll_until_filled` is in [`scripts/responses.py`](../scripts/responses.py). Always prefer it over hand-written `while True` loops.

### Chains with

- `placeorder` -> `orderstatus` -> SL via `placeorder(SL-M)`
- `placeorder` -> `orderstatus` -> target via `placeorder(LIMIT)`
- `modifyorder` -> `orderstatus` -> confirmed-modified or back-to-open
- See [common-workflows.md](common-workflows.md) for the full recipes

---

## openposition

Returns the **signed** net quantity for one (symbol, exchange, product)
triple — positive = long, negative = short, zero = flat. Designed for
the smart-order pre-check: "what do I already hold before placing?"

### Request

```python
client.openposition(
    strategy="python",
    symbol="YESBANK",
    exchange="NSE",
    product="MIS",
)
```

### Success Response

```json
{ "quantity": "-10", "status": "success" }
```

Note `quantity` is a **string** in the response — coerce to int.

### Read these fields

| Field | Helper | Used for |
|-------|--------|----------|
| `quantity` | `responses.open_position_qty(resp)` | signed int; sizing decisions |
| `status` | `responses.ensure_success(resp)` | distinguish "no position" (status=success, qty=0) from "lookup failed" |

### Chains with

```python
from scripts.responses import open_position_qty

current = open_position_qty(
    client.openposition(strategy="python", symbol="SBIN",
                        exchange="NSE", product="MIS")
)
target = 50
delta = target - current

if delta != 0:
    client.placesmartorder(
        strategy="python", symbol="SBIN", exchange="NSE",
        action="BUY" if delta > 0 else "SELL",
        product="MIS", price_type="MARKET",
        quantity=abs(delta), position_size=target,
    )
```

This pattern is wrapped in [`scripts.workflows.place_smart_with_position_check`](../scripts/workflows.py).

### Common gotcha

`openposition` is per-(symbol, exchange, product). If you trade the
same symbol under both MIS and CNC, those are two separate positions
and need two queries. `positionbook` returns the full set in one call.
