# Account Services — Reference

Read-only endpoints for funds, margin, and the four books (orders /
trades / positions / holdings).

| Endpoint | Method | Returns | Used for |
|----------|--------|---------|----------|
| Available funds | `client.funds()` | `{status, data{availablecash, m2m..., utiliseddebits, collateral}}` | pre-trade sizing |
| Margin calculator | `client.margin(positions=[...])` | `{status, data{total_margin_required, span_margin, exposure_margin}}` | F&O sizing |
| Today's orders | `client.orderbook()` | `{status, data{orders[], statistics{}}}` | day-end reconciliation |
| Today's trades | `client.tradebook()` | `{status, data[]}` | fill-level audit |
| Open positions | `client.positionbook()` | `{status, data[]}` | live P&L, exposure |
| Holdings | `client.holdings()` | `{status, data{holdings[], statistics{}}}` | long-term portfolio |

All endpoints are in the 50/sec general data bucket.

---

## funds

### Request

```python
client.funds()
```

### Success Response

```json
{
  "status": "success",
  "data": {
    "availablecash":   "320.66",
    "collateral":      "0.00",
    "m2mrealized":     "3.27",
    "m2munrealized":   "-7.88",
    "utiliseddebits":  "679.34"
  }
}
```

All values are returned as **strings** — coerce to float.

### Read these fields

| Field | Helper | Used for |
|-------|--------|----------|
| `data.availablecash` | `responses.available_cash(resp)` | "can I afford this trade?" gate |
| `data.m2mrealized` | direct read, `float()` | EOD realized P&L |
| `data.m2munrealized` | direct read, `float()` | live open-position P&L |
| `data.utiliseddebits` | direct read | margin used by open positions |
| `data.collateral` | direct read | pledged stock value backing margin |

### Chains with

- `available_cash` -> compare to `placeorder` notional -> abort if insufficient
- End-of-day P&L digest: see [common-workflows.md #5](common-workflows.md#5-daily-cleanup-with-pl-alert)
- Pre-trade gate:
  ```python
  cash = responses.available_cash(client.funds())
  if quantity * limit_price > cash:
      raise RuntimeError(f"insufficient funds: need {quantity*limit_price}, have {cash}")
  ```

---

## margin

Multi-leg margin calculator. Pass a list of intended positions and the
server returns the SPAN + exposure margin the broker will reserve.
Critical before placing F&O entries, especially multi-leg.

### Request

```python
client.margin(positions=[
    {"symbol": "NIFTY30JUN2625000CE", "exchange": "NFO",
     "action": "BUY",  "product": "NRML", "pricetype": "MARKET", "quantity": "75"},
    {"symbol": "NIFTY30JUN2625500CE", "exchange": "NFO",
     "action": "SELL", "product": "NRML", "pricetype": "MARKET", "quantity": "75"},
])
```

### Success Response

```json
{
  "status": "success",
  "data": {
    "total_margin_required": 91555.7625,
    "span_margin":           0.0,
    "exposure_margin":       91555.7625
  }
}
```

### Read these fields

| Field | Helper | Used for |
|-------|--------|----------|
| `data.total_margin_required` | `responses.total_margin_required(resp)` | gate vs. `available_cash` |
| `data.span_margin` | direct read | SEBI SPAN component |
| `data.exposure_margin` | direct read | exchange exposure component |

### Chains with

```python
needed = responses.total_margin_required(client.margin(positions=legs))
cash   = responses.available_cash(client.funds())

if needed > cash:
    raise RuntimeError(f"need Rs {needed:.0f}, have Rs {cash:.0f}")
client.optionsmultiorder(strategy="iron_condor", legs=legs, ...)
```

### Gotcha

`pricetype="MARKET"` makes the server use the current LTP for the
margin estimate. Use `LIMIT` with a `price` field if you need the
margin for a hypothetical entry away from LTP.

---

## orderbook

All orders placed today (open + completed + cancelled + rejected).

### Request

```python
client.orderbook()
```

### Success Response

```json
{
  "status": "success",
  "data": {
    "orders": [
      {
        "action":        "BUY",
        "symbol":        "RELIANCE",
        "exchange":      "NSE",
        "orderid":       "250408000989443",
        "product":       "MIS",
        "quantity":      "1",
        "price":         1186.0,
        "pricetype":     "MARKET",
        "order_status":  "complete",
        "trigger_price": 0.0,
        "timestamp":     "08-Apr-2025 13:58:03"
      },
      {
        "action":   "BUY",
        "symbol":   "YESBANK",
        ...
        "order_status": "cancelled"
      }
    ],
    "statistics": {
      "total_buy_orders":       2.0,
      "total_sell_orders":      0.0,
      "total_completed_orders": 1.0,
      "total_open_orders":      0.0,
      "total_rejected_orders":  0.0
    }
  }
}
```

### Read these fields

| Field | Used for |
|-------|----------|
| `data.orders[]` | iterate for per-order audit |
| `data.statistics.total_completed_orders` | EOD count for the alert template |
| `data.statistics.total_rejected_orders` | flag a bad day if non-zero |
| Each row's `order_status` | filter for open / completed / cancelled |

### Pandas conversion

```python
import pandas as pd
ob = client.orderbook()
df = pd.DataFrame(ob["data"]["orders"])
print(df[df["order_status"] == "complete"])
```

---

## tradebook

All **fills** today — one row per execution. Some orders generate
multiple trades (partial fills); the tradebook is the ground truth for
P&L calculation.

### Request

```python
client.tradebook()
```

### Success Response

```json
{
  "status": "success",
  "data": [
    {
      "action":        "BUY",
      "symbol":        "RELIANCE",
      "exchange":      "NSE",
      "orderid":       "250408000989443",
      "product":       "MIS",
      "quantity":      0.0,
      "average_price": 1180.1,
      "timestamp":     "13:58:03",
      "trade_value":   1180.1
    },
    {
      "action":        "SELL",
      "symbol":        "NHPC",
      ...
    }
  ]
}
```

Note `data` is a top-level **list**, not nested under `orders`.

### Read these fields

| Field | Used for |
|-------|----------|
| `data[].average_price` | per-fill price for accurate P&L |
| `data[].trade_value` | gross notional (price * qty) |
| `data[].orderid` | link back to the parent order |

### Chains with

```python
import pandas as pd

tb = pd.DataFrame(client.tradebook()["data"])
realised = (
    tb[tb["action"] == "SELL"]["trade_value"].sum()
    - tb[tb["action"] == "BUY"]["trade_value"].sum()
)
```

---

## positionbook

Open positions across segments. One row per (symbol, exchange, product)
even if quantity is zero (residual zero-rows from intraday round-trips
are common).

### Request

```python
client.positionbook()
```

### Success Response

```json
{
  "status": "success",
  "data": [
    {"symbol": "NHPC",     "exchange": "NSE", "product": "MIS",
     "quantity": "-1",  "average_price": "83.74",  "ltp": "83.72", "pnl": "0.02"},
    {"symbol": "RELIANCE", "exchange": "NSE", "product": "MIS",
     "quantity": "0",   "average_price": "0.0",    "ltp": "1189.9","pnl": "5.90"},
    {"symbol": "YESBANK",  "exchange": "NSE", "product": "MIS",
     "quantity": "-104","average_price": "17.2",   "ltp": "17.31", "pnl": "-10.44"}
  ]
}
```

All fields are **strings** — coerce to int / float as needed.

### Read these fields

| Field | Used for |
|-------|----------|
| `data[].quantity` | non-zero = open position |
| `data[].pnl` | unrealized P&L (live) |
| `data[].average_price` | entry reference for SL calc |
| `data[].ltp` | current mark |

### Open-position count

```python
pb = client.positionbook()
open_count = sum(1 for p in pb["data"] if int(p["quantity"]) != 0)
```

### Chains with

- `positionbook` -> filter `qty != 0` -> per-symbol `placeorder(action=opposite)` -> manual square-off (alternative to `closeposition` when you want selective)
- Daily P&L: `pb["data"][i].pnl` rolled up
- Position-aware sizing in strategies

---

## holdings

Long-term equity holdings. Demat positions held via CNC, with
broker-computed P&L vs. average buy price.

### Request

```python
client.holdings()
```

### Success Response

```json
{
  "status": "success",
  "data": {
    "holdings": [
      {"symbol": "RELIANCE",  "exchange": "NSE", "product": "CNC",
       "quantity": 1, "pnl": -149.0, "pnlpercent": -11.1},
      {"symbol": "TATASTEEL", "exchange": "NSE", "product": "CNC",
       "quantity": 1, "pnl":  -15.0, "pnlpercent": -10.41},
      {"symbol": "CANBK",     "exchange": "NSE", "product": "CNC",
       "quantity": 5, "pnl":  -69.0, "pnlpercent": -13.43}
    ],
    "statistics": {
      "totalholdingvalue":   1768.0,
      "totalinvvalue":       2001.0,
      "totalprofitandloss":  -233.15,
      "totalpnlpercentage":  -11.65
    }
  }
}
```

### Read these fields

| Field | Used for |
|-------|----------|
| `data.holdings[]` | iterate for per-symbol position |
| `data.statistics.totalprofitandloss` | portfolio-level P&L |
| `data.statistics.totalpnlpercentage` | portfolio return |

### Chains with

- Daily portfolio digest -> WhatsApp with sector breakdown
- Rebalancing scripts -> read holdings -> compute target weights -> `basketorder`

---

## Putting it together — pre-trade safety check

```python
from scripts.responses import available_cash, total_margin_required

# 1. Cash check
cash = available_cash(client.funds())

# 2. Margin check for the intended F&O legs
margin_resp = client.margin(positions=[
    {"symbol": "NIFTY30JUN2625000CE", "exchange": "NFO",
     "action": "BUY",  "product": "NRML", "pricetype": "MARKET", "quantity": "75"},
])
required = total_margin_required(margin_resp)

if required > cash:
    print(f"REJECT: need {required:.0f}, have {cash:.0f}")
else:
    # 3. Existing exposure check
    pb = client.positionbook()
    open_count = sum(1 for p in pb["data"] if int(p["quantity"]) != 0)
    if open_count >= 5:
        print(f"REJECT: already in {open_count} positions; concentration limit")
    else:
        # 4. Place
        client.placeorder(...)
```

This pattern combines `funds` -> `margin` -> `positionbook` into a
three-step gate that every production strategy should run before
placing F&O orders.
