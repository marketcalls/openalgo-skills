# Symbol Services — Reference

| Endpoint | Method | Returns | Used for |
|----------|--------|---------|----------|
| Symbol metadata | `client.symbol(symbol, exchange)` | `{status, data{lotsize, tick_size, expiry, ...}}` | resolve OpenAlgo symbol to broker token + sizing |
| Fuzzy search | `client.search(query, exchange=None)` | `{status, data[], message}` | autocomplete, derivative lookup |
| F&O expiries | `client.expiry(symbol, exchange, instrumenttype)` | `{status, data[]}` | enumerate available expiries |
| All instruments | `client.instruments(exchange)` | `DataFrame` | bulk universe building |

---

## symbol

The authoritative way to convert an OpenAlgo symbol to the underlying
broker token, get the lot size, freeze quantity, tick size, and expiry
for derivatives.

### Request

```python
client.symbol(symbol="NIFTY30JUN26FUT", exchange="NFO")
```

### Success Response

```json
{
  "status": "success",
  "data": {
    "id":             57900,
    "symbol":         "NIFTY30JUN26FUT",
    "name":           "NIFTY",
    "brsymbol":       "NIFTY FUT 30 JUN 26",
    "exchange":       "NFO",
    "brexchange":     "NSE_FO",
    "token":          "NSE_FO|49543",
    "expiry":         "30-JUN-26",
    "freeze_qty":     1800,
    "instrumenttype": "FUT",
    "lotsize":        75,
    "strike":         0,
    "tick_size":      10
  }
}
```

### Read these fields

| Field | Helper | Used for |
|-------|--------|----------|
| `data.lotsize` | `scripts.lotsize.lot_for_via_symbol_api(client, symbol, exchange)` | F&O sizing (live, authoritative) |
| `data.freeze_qty` | direct read | trigger `splitorder` above this |
| `data.tick_size` | direct read | round LIMIT prices |
| `data.expiry` | direct read | calendar arithmetic (DD-MMM-YY format) |
| `data.token` | direct read | rarely needed — internal broker reference |
| `data.brsymbol` | direct read | what the broker calls the contract |
| `data.brexchange` | direct read | broker-side exchange code |

### Chains with

- Pre-flight lookup before any F&O order: `symbol` -> `validate_fno_lot(quantity, lot=data.lotsize)` -> `placeorder`
- Compare `data.expiry` to today's date for days-to-expiry calculations
- Verify a contract is still tradable (returns error after expiry)

### When to use this vs. the bundled CSV

- `scripts.lotsize.get_lot(symbol)` reads `assets/LotSize.csv` — fast, no API call, but a quarterly snapshot.
- `client.symbol(...).data.lotsize` is **always current** but costs an API call. Use it for newly listed underlyings or when the CSV value looks stale.

---

## search

Fuzzy match by name fragments. Designed for "I know the underlying and
strike but not the exact symbol string" use cases.

### Request

```python
client.search(query="NIFTY 26500 JUN CE", exchange="NFO")
```

### Success Response

```json
{
  "status": "success",
  "message": "Found 7 matching symbols",
  "data": [
    {
      "brexchange":     "NSE_FO",
      "brsymbol":       "NIFTY 26500 CE 30 JUN 26",
      "exchange":       "NFO",
      "expiry":         "30-JUN-26",
      "freeze_qty":     1800,
      "instrumenttype": "CE",
      "lotsize":        75,
      "name":           "NIFTY",
      "strike":         26500,
      "symbol":         "NIFTY30JUN2626500CE",
      "tick_size":      5,
      "token":          "NSE_FO|71399"
    },
    { ...other matching contracts... }
  ]
}
```

### Read these fields

| Field | Used for |
|-------|----------|
| `data[].symbol` | OpenAlgo symbol — feed into `placeorder` |
| `data[].lotsize` | sizing |
| `data[].expiry` | filter to the expiry you want |
| `data[].strike` | filter to specific strike |

### Patterns

```python
from scripts.symbols import search_symbols

matches = search_symbols(client, query="BANKNIFTY 58000 CE", exchange="NFO")
this_month = [m for m in matches if m["expiry"].endswith("JUN-26")]
print(this_month[0]["symbol"])
```

### Gotcha

Search is *fuzzy* — `query="NIFTY"` returns BANKNIFTY, FINNIFTY,
MIDCPNIFTY etc. Always filter the returned list by `name` if you need
an exact underlying match.

---

## expiry

List available F&O expiry dates for an underlying. Use to programmatically pick "next monthly", "next weekly", etc.

### Request

```python
client.expiry(
    symbol="NIFTY",
    exchange="NFO",
    instrumenttype="options",       # options | futures
    strike_count=10,                # optional — limit OI scan radius
)
```

### Success Response

```json
{
  "status": "success",
  "message": "Found 18 expiry dates for NIFTY options in NFO",
  "data": [
    "10-JUL-25", "17-JUL-25", "24-JUL-25", "31-JUL-25",
    "07-AUG-25", "28-AUG-25", "25-SEP-25",
    "24-DEC-25", "26-MAR-26", "25-JUN-26",
    "31-DEC-26", "24-JUN-27", "30-DEC-27",
    "29-JUN-28", "28-DEC-28", "28-JUN-29",
    "27-DEC-29", "25-JUN-30"
  ]
}
```

### Read these fields

| Field | Used for |
|-------|----------|
| `data[]` | list of `DD-MMM-YY` strings, sorted nearest-first |

### Convert to OpenAlgo format

The expiry endpoint returns `DD-MMM-YY` (with dashes). Options /
futures endpoints expect `DDMMMYY` (no dashes). Convert:

```python
expiries = client.expiry(symbol="NIFTY", exchange="NFO", instrumenttype="options")["data"]
# "30-JUN-26" -> "30JUN26"
next_monthly = expiries[0].replace("-", "")
```

### Pick the nearest weekly / monthly

```python
from datetime import datetime

raw = client.expiry(symbol="NIFTY", exchange="NFO", instrumenttype="options")["data"]
expiries = [datetime.strptime(e, "%d-%b-%y").date() for e in raw]
weekly_next = expiries[0]
# Last Thursday of the month is the monthly. Filter for it:
monthlies = [
    e for e in expiries
    if all((e + (next_day - e)).month != e.month
           for next_day in [datetime(e.year, e.month, e.day + i).date()
                             for i in range(1, 8)
                             if e.day + i <= 28 or e.day + i <= last_day_of_month(e)])
]
```

(Or just take the last expiry that is in the current month — usually the monthly.)

### Chains with

- `expiry` -> pick the nearest weekly -> `optionsymbol(offset='ATM')` -> `optionsorder`
- `expiry` -> `optionchain(expiry_date=...)` for a specific expiry

---

## instruments

The full instrument master for one exchange, returned as a pandas
**DataFrame**. Heavy — NSE has ~3000 rows, NFO ~50,000+. Cache the
output to a parquet file rather than re-pulling each session.

### Request

```python
df = client.instruments(exchange="NSE")
```

### Returned columns

```
brexchange         (broker exchange code)
brsymbol           (broker symbol)
exchange           (OpenAlgo exchange code)
expiry             (None for equity)
instrumenttype     (EQ, FUT, CE, PE, INDEX, etc.)
lotsize            (1 for equity, lot for derivatives)
name               (full descriptive name)
strike             (-1 for non-options)
symbol             (OpenAlgo symbol)
tick_size          (minimum price increment)
token              (broker-side token)
```

### Read these fields

| Field | Used for |
|-------|----------|
| `df["symbol"]` | universe construction for scanners |
| `df["instrumenttype"]` | filter to EQ / FUT / CE / PE |
| `df["lotsize"]` | dense per-symbol lot lookup |
| `df["tick_size"]` | accurate LIMIT-price rounding |

### Common patterns

```python
# All NSE equity
eq = client.instruments(exchange="NSE")
eq = eq[eq["instrumenttype"] == "EQ"]

# All NFO option contracts for NIFTY 30JUN26
nfo = client.instruments(exchange="NFO")
nifty_jun = nfo[
    (nfo["name"] == "NIFTY")
    & nfo["instrumenttype"].isin(["CE", "PE"])
    & (nfo["expiry"] == "30-JUN-26")
].sort_values("strike")
print(nifty_jun[["symbol", "strike", "instrumenttype", "lotsize"]].head(20))
```

### Caching to parquet

```python
import os, time
from pathlib import Path

cache = Path("openalgo_workspace/_cache/nse_instruments.parquet")
cache.parent.mkdir(parents=True, exist_ok=True)

if not cache.exists() or time.time() - cache.stat().st_mtime > 86400:
    df = client.instruments(exchange="NSE")
    df.to_parquet(cache)
else:
    import pandas as pd
    df = pd.read_parquet(cache)
```

A cached instrument master is the foundation for any scanner or
heatmap that runs every minute — re-fetching this every cycle would
hammer the broker for no benefit.

---

## Putting it together

```python
# Goal: place an ATM straddle on NIFTY for the next monthly expiry

# 1. enumerate expiries
expiries = client.expiry(symbol="NIFTY", exchange="NFO",
                         instrumenttype="options")["data"]

# 2. pick next monthly (here: 30-JUN-26 in DD-MMM-YY)
next_monthly = "30-JUN-26"
exp_oa = next_monthly.replace("-", "")     # "30JUN26"

# 3. resolve ATM CE + ATM PE
ce = client.optionsymbol(underlying="NIFTY", exchange="NSE_INDEX",
                         expiry_date=exp_oa, offset="ATM", option_type="CE")
pe = client.optionsymbol(underlying="NIFTY", exchange="NSE_INDEX",
                         expiry_date=exp_oa, offset="ATM", option_type="PE")

# 4. sanity check lot sizes match
assert ce["lotsize"] == pe["lotsize"]
lot = int(ce["lotsize"])                   # 75 for NIFTY

# 5. sell both ATM legs (short straddle)
client.optionsmultiorder(
    strategy="short_straddle",
    underlying="NIFTY", exchange="NSE_INDEX",
    expiry_date=exp_oa,
    legs=[
        {"offset": "ATM", "option_type": "CE", "action": "SELL", "quantity": lot},
        {"offset": "ATM", "option_type": "PE", "action": "SELL", "quantity": lot},
    ],
)
```
