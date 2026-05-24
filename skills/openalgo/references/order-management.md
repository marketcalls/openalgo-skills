# Order Management — Reference

Covers the **execution** side of the SDK: place, modify, cancel, square-off, and GTT.

| Endpoint | Method | Sync | Returns |
|----------|--------|------|---------|
| Place regular order | `client.placeorder` | yes | `{orderid, status}` |
| Place position-aware order | `client.placesmartorder` | yes | `{orderid, status}` |
| Place options-by-offset | `client.optionsorder` | yes | `{orderid, status, symbol, underlying, underlying_ltp, exchange, offset, option_type, mode?}` |
| Place multi-leg options | `client.optionsmultiorder` | yes | `{status, underlying, underlying_ltp, results[]}` |
| Place basket | `client.basketorder` | yes | `{status, results[]}` |
| Place split | `client.splitorder` | yes | `{status, split_size, total_quantity, results[]}` |
| Modify order | `client.modifyorder` | yes | `{orderid, status}` |
| Cancel order | `client.cancelorder` | yes | `{orderid, status}` |
| Cancel all | `client.cancelallorder` | yes | `{status, message, canceled_orders[], failed_cancellations[]}` |
| Close all positions | `client.closeposition` | yes | `{status, message}` |
| GTT place | `client.placegttorder` | yes | `{status, gtt_order_id}` (REST) |
| GTT modify | `client.modifygttorder` | yes | `{status, gtt_order_id}` (REST) |
| GTT cancel | `client.cancelgttorder` | yes | `{status}` (REST) |
| GTT list | `client.gttorderbook` | yes | `{status, data[]}` (REST) |

Order placement requires static IP whitelisting at the broker side (SEBI mandate from 1-Apr-2026). Smart-orders are capped at 2/sec; regular orders 10/sec.

---

## placeorder

### Request

```python
client.placeorder(
    strategy="python",          # tag stored on broker order book + analyzer logs
    symbol="RELIANCE",
    exchange="NSE",             # NSE / BSE / NFO / BFO / CDS / BCD / MCX / NCO
    action="BUY",               # BUY | SELL
    price_type="LIMIT",         # MARKET | LIMIT | SL | SL-M
    product="MIS",              # CNC (equity delivery) | MIS (intraday) | NRML (F&O carry)
    quantity="10",              # string or int
    price="1250.00",            # required for LIMIT and SL
    trigger_price="0",          # required for SL and SL-M
    disclosed_quantity="0",     # optional iceberg disclosure
)
```

### Success Response

```json
{ "orderid": "250408000989443", "status": "success" }
```

### Error Response

```json
{ "status": "error", "message": "<reason>" }
```

Common reasons: invalid symbol, lot-size violation, insufficient margin, rate-limited, static-IP not whitelisted.

### Read these fields

| Field | Helper | Used for |
|-------|--------|----------|
| `orderid` | `responses.extract_orderid(resp)` | next-step: `orderstatus`, `modifyorder`, `cancelorder` |
| `status` | `responses.ensure_success(resp)` | gate every chain on this |

### Chains with

- `orderstatus(orderid, strategy)` -> poll until terminal
- `responses.avg_fill_price(status)` -> compute SL / target
- See [common-workflows.md](common-workflows.md#order-then-sl-target-on-actual-fill)

---

## placesmartorder

Position-aware variant. The SDK reconciles the order against the user's
current open position before sending — useful for reversal flips
(long -> short) without computing the delta yourself.

### Request

```python
client.placesmartorder(
    strategy="python",
    symbol="TATAMOTORS",
    exchange="NSE",
    action="SELL",
    price_type="MARKET",
    product="MIS",
    quantity=1,
    position_size=5,            # desired net position after this order
)
```

### Success Response

```json
{ "orderid": "250408000997543", "status": "success" }
```

Same field map as `placeorder` — uses `responses.extract_orderid`.

---

## optionsorder

Places an options order specified by `offset` from ATM rather than by
explicit symbol. The SDK resolves the symbol against the current spot
internally and returns both the resolved option symbol and the
underlying LTP at resolution time.

### Request

```python
client.optionsorder(
    strategy="python",
    underlying="NIFTY",
    exchange="NSE_INDEX",       # underlying exchange — index for NIFTY/BANKNIFTY/etc.
    expiry_date="30JUN26",      # DDMMMYY uppercase
    offset="ATM",               # ATM | ITM1..ITM20 | OTM1..OTM20
    option_type="CE",           # CE | PE
    action="BUY",
    quantity=75,                # must be a multiple of lot_size
    pricetype="MARKET",         # MARKET | LIMIT
    product="NRML",
    splitsize=0,                # 0 = no split, >0 = chunk each child
)
```

### Success Response

```json
{
  "exchange": "NFO",
  "offset": "ATM",
  "option_type": "CE",
  "orderid": "26063000000006",
  "status": "success",
  "symbol": "NIFTY30JUN2626500CE",
  "underlying": "NIFTY30JUN26FUT",
  "underlying_ltp": 26512.45,
  "mode": "analyze"
}
```

`mode` appears when the call is routed through analyzer (sandbox).

### Read these fields

| Field | Helper | Used for |
|-------|--------|----------|
| `orderid` | `responses.extract_orderid(resp)` | next-step status / SL |
| `symbol` | `responses.options_order_details(resp)["symbol"]` | log the actual contract; pass to SL placement |
| `exchange` | `responses.options_order_details(resp)["exchange"]` | always `NFO`/`BFO` after resolution |
| `underlying_ltp` | "" | risk sizing — distance to strike |

### Chains with

- `optionsymbol` -> `optionsorder` -> `orderstatus` -> SL via `placeorder(SL-M)`
- Full recipe in [common-workflows.md](common-workflows.md#atm-straddle-with-percentage-sl)

---

## optionsmultiorder

Places multiple option legs in one call — iron condor, straddle,
strangle, vertical/diagonal spread. Each leg can have a different
expiry (diagonal); otherwise omit per-leg expiry and pass top-level.

### Request — Iron Condor

```python
client.optionsmultiorder(
    strategy="iron_condor_test",
    underlying="NIFTY",
    exchange="NSE_INDEX",
    expiry_date="30JUN26",
    legs=[
        {"offset": "OTM6", "option_type": "CE", "action": "BUY",  "quantity": 75},
        {"offset": "OTM6", "option_type": "PE", "action": "BUY",  "quantity": 75},
        {"offset": "OTM4", "option_type": "CE", "action": "SELL", "quantity": 75},
        {"offset": "OTM4", "option_type": "PE", "action": "SELL", "quantity": 75},
    ],
)
```

### Request — Diagonal Spread (per-leg expiry)

```python
client.optionsmultiorder(
    strategy="diagonal_test",
    underlying="NIFTY",
    exchange="NSE_INDEX",
    legs=[
        {"offset": "ITM2", "option_type": "CE", "action": "BUY",
         "quantity": 75, "expiry_date": "30JUN26"},
        {"offset": "OTM2", "option_type": "CE", "action": "SELL",
         "quantity": 75, "expiry_date": "28MAY26"},
    ],
)
```

### Success Response

```json
{
  "status": "success",
  "underlying": "NIFTY",
  "underlying_ltp": 26512.45,
  "results": [
    { "leg": 1, "action": "BUY",  "orderid": "26063000000006",
      "status": "success", "symbol": "NIFTY30JUN2626850CE",
      "offset": "OTM6", "option_type": "CE", "mode": "analyze" },
    { "leg": 2, "action": "BUY",  "orderid": "26063000000007",
      "status": "success", "symbol": "NIFTY30JUN2626150PE",
      "offset": "OTM6", "option_type": "PE", "mode": "analyze" },
    ...
  ]
}
```

### Read these fields

| Field | Helper | Used for |
|-------|--------|----------|
| `results[].orderid` | `responses.extract_orderids_basket(resp)` | track each leg independently |
| `results[].symbol` | iterate manually | log / SL per leg |
| `results[].status` | check per-leg | a leg can fail while top-level reports success |

### Critical gotcha

The top-level `status: "success"` does **not** mean all legs succeeded — partial fills are possible. Always iterate `results[]` and handle the failed legs explicitly. Use `responses.extract_orderids_basket` which already filters to successful legs.

---

## basketorder

Generic batch placement. Each order in the list is independent and may
target any segment.

```python
client.basketorder(orders=[
    {"symbol": "BHEL",   "exchange": "NSE", "action": "BUY",
     "quantity": 1, "pricetype": "MARKET", "product": "MIS"},
    {"symbol": "ZOMATO", "exchange": "NSE", "action": "SELL",
     "quantity": 1, "pricetype": "MARKET", "product": "MIS"},
])
```

Response same shape as `optionsmultiorder` — `results[]` array, per-leg `orderid` and `status`. Same `extract_orderids_basket` helper applies.

---

## splitorder

Splits a single large quantity into N child orders of fixed size each.
Useful for circumventing freeze-quantity limits on F&O lots.

```python
client.splitorder(
    strategy="python",
    symbol="YESBANK",
    exchange="NSE",
    action="SELL",
    quantity=105,
    splitsize=20,
    price_type="MARKET",
    product="MIS",
)
```

### Success Response

```json
{
  "status": "success",
  "split_size": 20,
  "total_quantity": 105,
  "results": [
    {"order_num": 1, "orderid": "250408001021467", "quantity": 20, "status": "success"},
    {"order_num": 2, "orderid": "250408001021459", "quantity": 20, "status": "success"},
    {"order_num": 3, "orderid": "250408001021466", "quantity": 20, "status": "success"},
    {"order_num": 4, "orderid": "250408001021470", "quantity": 20, "status": "success"},
    {"order_num": 5, "orderid": "250408001021471", "quantity": 20, "status": "success"},
    {"order_num": 6, "orderid": "250408001021472", "quantity":  5, "status": "success"}
  ]
}
```

`splitorder` is one-shot — for a true iceberg with display-quantity refilling, use `scripts.execution.IcebergSlicer`.

---

## modifyorder

```python
client.modifyorder(
    order_id="250408001002736",
    strategy="python",
    symbol="YESBANK",
    exchange="NSE",
    action="BUY",
    price_type="LIMIT",
    product="CNC",
    quantity=1,
    price=16.5,
)
```

Returns `{orderid, status}`. Note that broker plugins differ on whether all fields are required vs only the changing ones — pass the full set to be safe.

Used heavily by [`scripts.execution.LimitChaser`](../scripts/execution.py) which calls `modifyorder` every time the touch moves.

---

## cancelorder / cancelallorder

```python
client.cancelorder(order_id="250408001002736", strategy="python")
client.cancelallorder(strategy="python")
```

`cancelallorder` returns lists of `canceled_orders[]` and `failed_cancellations[]`. Always inspect `failed_cancellations` — a 0-length list means total success.

---

## closeposition

Squares off every open position across segments. Useful as the end-of-day cleanup step in intraday strategies.

```python
client.closeposition(strategy="python")
```

Use [`scripts.workflows.square_off_with_alert`](../scripts/workflows.py) to also fetch and broadcast realized/unrealized P&L afterwards.

---

## GTT (Good-Till-Triggered) — REST-only

The Python SDK does not yet wrap GTT. Call the REST endpoints directly with `httpx`/`requests`. See `/Users/openalgo/test-zerodha/openalgo/docs/api/order-management/placegttorder.md` for parameter schema. The skill provides a thin wrapper in [`scripts.gtt`](../scripts/) if you need OCO triggers.

---

## End-to-end response-chaining recipes

These live in their own file: [common-workflows.md](common-workflows.md). The canonical examples:

- `Order then SL/target on actual fill` — `placeorder` -> `orderstatus` (poll) -> `avg_fill_price` -> SL/target placement
- `ATM straddle with percentage SL` — `optionsymbol` -> `optionsorder` (CE+PE) -> fills -> SL on each leg
- `Reverse on signal` — `openposition` -> compute delta -> `placesmartorder` -> alert
- `Daily cleanup with P&L alert` — `closeposition` -> `funds` -> `positionbook` -> formatted alert

All recipes are also wired into [`scripts.workflows`](../scripts/workflows.py) as one-call functions.
