# Order Constants — Reference

Every value used in the order endpoints' enum fields. Use these exact
strings — case sensitive in some broker plugins.

## Exchange

| Code | Description | Trading? |
|------|-------------|----------|
| `NSE` | National Stock Exchange (Equity) | yes |
| `BSE` | Bombay Stock Exchange (Equity) | yes |
| `NFO` | NSE Futures & Options | yes |
| `BFO` | BSE Futures & Options | yes |
| `CDS` | NSE Currency Derivatives | yes |
| `BCD` | BSE Currency Derivatives | yes |
| `MCX` | Multi Commodity Exchange | yes |
| `NCDEX` | NCDEX Commodity | yes |
| `NCO` | NSE Commodities — futures + options (Zerodha only) | yes |
| `NSE_INDEX` | NSE Index | no (quote-only) |
| `BSE_INDEX` | BSE Index | no (quote-only) |
| `MCX_INDEX` | MCX Sectoral Index (Zerodha) | no (quote-only) |
| `GLOBAL_INDEX` | Global indices: US30, JAPAN225, HANGSENG, GIFTNIFTY (Zerodha) | no (quote-only) |

## Action

| Code | Meaning |
|------|---------|
| `BUY` | Buy / long entry / cover short / take delivery |
| `SELL` | Sell / short entry / square long / give delivery |

## Product Type

| Code | Meaning | Allowed Segments |
|------|---------|------------------|
| `CNC` | Cash and Carry (Equity Delivery) | `NSE`, `BSE` only |
| `MIS` | Margin Intraday Square-off | every tradable segment |
| `NRML` | Normal (F&O / commodity / currency carry) | `NFO`, `BFO`, `CDS`, `BCD`, `MCX`, `NCO` |

### Critical rule

| Segment | Allowed `product` |
|---------|-------------------|
| `NSE`, `BSE` | `CNC`, `MIS` |
| `NFO`, `BFO`, `CDS`, `BCD`, `MCX`, `NCDEX`, `NCO` | `MIS`, `NRML` |

Never `CNC` on F&O, commodity, or currency — the broker rejects it. Some plugins also support `MTF` (margin trading facility) for equity; check the broker docs.

## Price Type

| Code | Meaning | Fields required |
|------|---------|-----------------|
| `MARKET` | Market order — fills at best available | (none extra) |
| `LIMIT` | Limit order — at price or better | `price` |
| `SL` | Stop-loss LIMIT order | `trigger_price`, `price` |
| `SL-M` | Stop-loss MARKET order | `trigger_price` |

### SL vs. SL-M

- `SL` triggers a LIMIT order at `price` when `trigger_price` is hit.
  Use when you want bounded slippage at the stop level.
- `SL-M` triggers a MARKET order at the trigger. Guaranteed exit in
  fast markets but slippage is unbounded.

### Setting trigger_price relative to action

For a long position:
- Stop-loss action = `SELL`; `trigger_price < current LTP` (below entry)
- For `SL`: `price <= trigger_price` (`price` is your max-loss-acceptable level)

For a short position:
- Stop-loss action = `BUY`; `trigger_price > current LTP` (above entry)
- For `SL`: `price >= trigger_price`

## Validity

| Code | Meaning |
|------|---------|
| `DAY` | Order persists until end of session (most common) |
| `IOC` | Immediate-Or-Cancel — fill what you can right now, cancel the rest |

`DAY` is the SDK default if you omit the `validity` field.

## Option Offset (for `optionsorder` / `optionsmultiorder`)

| Code | Meaning |
|------|---------|
| `ATM` | At-The-Money — strike closest to spot |
| `ITM1` | 1 strike In-The-Money |
| `ITM2`..`ITM20` | 2..20 strikes In-The-Money |
| `OTM1` | 1 strike Out-of-The-Money |
| `OTM2`..`OTM20` | 2..20 strikes Out-of-The-Money |

Strike spacing depends on the underlying (50 for NIFTY, 100 for BANKNIFTY, etc.) — the SDK resolves this internally.

## WebSocket Modes

| Mode | Tag | Payload |
|------|-----|---------|
| 1 | LTP | last traded price + timestamp |
| 2 | Quote | OHLC + LTP + volume + change |
| 3 | Depth | full bid / ask book (with `depth_level` 5/20/30/50) |

## WebSocket Verbose Levels

| Value | Mode | Output |
|-------|------|--------|
| `False` / `0` | Silent | errors only |
| `True` / `1` | Basic | connection, auth, subscribe events |
| `2` | Debug | every tick |

---

## Quick lookup tables

### Product matrix

```
Segment       | CNC  | MIS  | NRML
--------------+------+------+------
NSE  / BSE    | YES  | YES  | NO
NFO  / BFO    | NO   | YES  | YES
CDS  / BCD    | NO   | YES  | YES
MCX  / NCDEX  | NO   | YES  | YES
NCO           | NO   | YES  | YES
```

### Order-type matrix

```
Price Type | price | trigger_price
-----------+-------+--------------
MARKET     | 0     | 0
LIMIT      | req   | 0
SL         | req   | req
SL-M       | 0     | req
```

---

## Validating before placement

```python
ALLOWED_PRODUCTS = {
    "NSE": {"CNC", "MIS"},
    "BSE": {"CNC", "MIS"},
    "NFO": {"MIS", "NRML"},
    "BFO": {"MIS", "NRML"},
    "MCX": {"MIS", "NRML"},
    "NCDEX": {"MIS", "NRML"},
    "NCO": {"MIS", "NRML"},
    "CDS": {"MIS", "NRML"},
    "BCD": {"MIS", "NRML"},
}

def validate_constants(exchange, product, price_type, price=0, trigger_price=0):
    if product not in ALLOWED_PRODUCTS.get(exchange, set()):
        raise ValueError(f"{product} not allowed on {exchange}")
    if price_type == "LIMIT" and price <= 0:
        raise ValueError("LIMIT requires price > 0")
    if price_type == "SL" and (price <= 0 or trigger_price <= 0):
        raise ValueError("SL requires both price and trigger_price")
    if price_type == "SL-M" and trigger_price <= 0:
        raise ValueError("SL-M requires trigger_price")
```

The OpenAlgo MCP server ships a `validate_order_constants` tool that
implements this check server-side — use it from agent contexts where
the validation logic should not run client-side.
