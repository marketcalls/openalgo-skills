# Market Data — Reference

REST endpoints for snapshots and historical bars. For live tick-by-tick
data use [websocket-streaming.md](websocket-streaming.md).

| Endpoint | Method | Returns | Used for |
|----------|--------|---------|----------|
| Single quote | `client.quotes(symbol, exchange)` | `{status, data{ohlc,ltp,...}}` | LTP, OHLC snapshot |
| Batch quotes | `client.multiquotes(symbols=[...])` | `{status, results[]}` | scanners, dashboards |
| Market depth | `client.depth(symbol, exchange)` | `{status, data{asks,bids,...}}` | book imbalance, touch |
| Historical OHLCV | `client.history(...)` | `DataFrame` (special — NOT a dict) | backtest, indicator calc |
| Available intervals | `client.intervals()` | `{status, data{minutes[],hours[],days[],...}}` | UI dropdowns |

Rate limits: 50/sec for general data APIs. Quote endpoints are sometimes
broker-throttled further (~1/sec) — `multiquotes` is preferred for any
multi-symbol need.

---

## quotes

### Request

```python
client.quotes(symbol="RELIANCE", exchange="NSE")
```

### Success Response

```json
{
  "status": "success",
  "data": {
    "open":       1172.0,
    "high":       1196.6,
    "low":        1163.3,
    "ltp":        1187.75,
    "ask":        1188.0,
    "bid":        1187.85,
    "prev_close": 1165.7,
    "volume":     14414545
  }
}
```

`oi` is also present for derivatives.

### Read these fields

| Field | Helper | Used for |
|-------|--------|----------|
| `data.ltp` | `responses.extract_ltp(resp)` | LIMIT price anchor, SL distance, alert text |
| `data.open / high / low` | `responses.extract_ohlc(resp)` | session range stats |
| `data.bid / ask` | direct read | bid-ask spread, marketable-limit pricing |
| `data.prev_close` | direct read | % change calculation |
| `data.volume` | direct read | volume-surge filters |

### Chains with

- `extract_ltp` -> compute marketable LIMIT (`ltp * 1.0015`) -> `placeorder`
- `prev_close` + `ltp` -> `% change` -> scanner filter
- See [common-workflows.md #8](common-workflows.md#8-quote-anchored-marketable-limit-safer-than-market)

---

## multiquotes

The endpoint of choice for any scan. One REST call, dozens of symbols.

### Request

```python
client.multiquotes(symbols=[
    {"symbol": "RELIANCE", "exchange": "NSE"},
    {"symbol": "TCS",      "exchange": "NSE"},
    {"symbol": "INFY",     "exchange": "NSE"},
])
```

### Success Response

```json
{
  "status": "success",
  "results": [
    {
      "symbol":   "RELIANCE",
      "exchange": "NSE",
      "data": {
        "open": 1542.3, "high": 1571.6, "low": 1540.5,
        "ltp": 1569.9, "prev_close": 1539.7,
        "ask": 1569.9, "bid": 0, "oi": 0, "volume": 14054299
      }
    },
    { "symbol": "TCS", "exchange": "NSE", "data": {...} },
    ...
  ]
}
```

### Read these fields

| Field | Helper | Used for |
|-------|--------|----------|
| `results[]` | `responses.multiquotes_to_dict(resp)` -> `{"RELIANCE@NSE": {...}}` | DataFrame conversion |
| Each `results[].data.ltp` | iterate | per-symbol LTP for ranking |
| Each `results[].data.prev_close` | "" | % change column for scanners |

### Chains with

- `Scanner.add_many(symbols)` -> `quote_scan()` (wraps multiquotes + filters)
- See [`scripts/scanner.py`](../scripts/scanner.py)

### Gotcha

Some brokers return zero `bid` or `ask` outside market hours. Always guard with `if data['bid']: ...` before using as a price anchor.

---

## depth

Level-2 market depth. Use for touch-aware limit-order placement and
book-imbalance detection.

### Request

```python
client.depth(symbol="SBIN", exchange="NSE")
```

### Success Response

```json
{
  "status": "success",
  "data": {
    "open": 760.0,
    "high": 774.0,
    "low":  758.15,
    "ltp":  769.6,
    "ltq":  205,
    "prev_close":   746.9,
    "volume":       9362799,
    "oi":           161265750,
    "totalbuyqty":  591351,
    "totalsellqty": 835701,
    "asks": [
      {"price": 769.6,  "quantity": 767},
      {"price": 769.65, "quantity": 115},
      {"price": 769.7,  "quantity": 162},
      {"price": 769.75, "quantity": 1121},
      {"price": 769.8,  "quantity": 430}
    ],
    "bids": [
      {"price": 769.4,  "quantity": 886},
      {"price": 769.35, "quantity": 212},
      {"price": 769.3,  "quantity": 351},
      {"price": 769.25, "quantity": 343},
      {"price": 769.2,  "quantity": 399}
    ]
  }
}
```

`asks[]` and `bids[]` are sorted from best (touch) to worst.

### Read these fields

| Field | Helper | Used for |
|-------|--------|----------|
| `data.bids[0].price` | `responses.extract_touch(resp)["best_bid"]` | LIMIT price for BUY chaser |
| `data.asks[0].price` | `responses.extract_touch(resp)["best_ask"]` | LIMIT price for SELL chaser |
| spread | `extract_touch(resp)["spread"]` | wide spread -> wider stops |
| `data.totalbuyqty` / `totalsellqty` | direct read | order-book imbalance ratio |

### Chains with

- `LimitChaser._touch_price()` calls this every poll cycle
- Depth-imbalance scanners: `totalbuyqty / totalsellqty > 1.5` as a long-side bias indicator

### Available depth levels

Some brokers support deeper books than five. The same `depth` call returns whatever the broker provides; for explicit depth-level control on the WebSocket side, see [websocket-streaming.md](websocket-streaming.md#depth-levels-mode-3).

---

## history

The only endpoint that returns a **pandas DataFrame** rather than a
dict. Indexed by timezone-aware IST timestamp; columns are
`open, high, low, close, volume`.

### Request — from broker API (live)

```python
df = client.history(
    symbol="SBIN",
    exchange="NSE",
    interval="5m",
    start_date="2026-05-01",
    end_date="2026-05-24",
    source="api",       # default; queries the broker directly
)
```

### Request — from Historify DuckDB (stored data)

```python
df = client.history(
    symbol="SBIN",
    exchange="NSE",
    interval="5m",
    start_date="2026-01-01",
    end_date="2026-05-24",
    source="db",        # routes through OpenAlgo Historify
)
```

For bulk multi-symbol pulls, **read the DuckDB file directly** via
[`scripts/duckdb_data.py`](../scripts/duckdb_data.py) — see
[duckdb-historify.md](duckdb-historify.md).

### Success Response (DataFrame)

```
                            close    high     low    open  volume
timestamp
2026-05-01 09:15:00+05:30  772.50  774.00  763.20  766.50  318625
2026-05-01 09:20:00+05:30  773.20  774.95  772.10  772.45  197189
2026-05-01 09:25:00+05:30  775.15  775.60  772.60  773.20  227544
...                           ...     ...     ...     ...     ...
```

### Read these fields

| Field | Used for |
|-------|----------|
| `df.index` | tz-aware IST timestamps — drop tz with `df.index.tz_convert(None)` for vbt |
| `df["close"]` | indicator input, signal generation |
| `df["volume"]` | volume-confirming filters |

### Standard pattern (used in every backtest example)

```python
df = client.history(symbol=SYM, exchange=EXC, interval="D",
                    start_date=start, end_date=end)
if "timestamp" in df.columns:
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.set_index("timestamp")
else:
    df.index = pd.to_datetime(df.index)
if df.index.tz is not None:
    df.index = df.index.tz_convert(None)
df = df.sort_index()
```

### Chains with

- `df["close"]` -> `talib.EMA(close.values, 20)` -> entries / exits
- `df["close"]` -> `openalgo.ta.supertrend(...)` -> direction series
- DataFrame is fed straight into `vbt.Portfolio.from_signals` for backtesting
- See [`examples/04_backtesting/`](../examples/04_backtesting/)

---

## intervals

Lists the broker-supported time-bar intervals for the connected broker.
Useful for building UI dropdowns or validating user-supplied intervals
before calling `history`.

### Request

```python
client.intervals()
```

### Success Response

```json
{
  "status": "success",
  "data": {
    "months":  [],
    "weeks":   [],
    "days":    ["D"],
    "hours":   ["1h"],
    "minutes": ["1m", "3m", "5m", "10m", "15m", "30m"],
    "seconds": []
  }
}
```

### Read these fields

| Field | Used for |
|-------|----------|
| `data.minutes[]` | which 1m/3m/5m/15m the broker supports |
| `data.hours[]` | hourly bars (most brokers only 1h) |
| `data.days[]` | daily bars — almost always `["D"]` |

### Chains with

- Validate user input before `history(interval=...)` to avoid 400s
- Build a strategy template that adapts to whatever the broker offers

---

## Common gotchas

- **`history` is special.** It returns a DataFrame, not a dict. Don't try to read `status` off it.
- **Quotes can return zero `bid`/`ask`** outside market hours or on stale symbols. Always check before using as a price anchor.
- **`multiquotes` order is not guaranteed.** Don't rely on `results[i]` matching `symbols[i]` — match by `symbol` + `exchange`.
- **`depth` levels vary by broker.** Some return 5, some 20, some 50. The shape is the same; just `asks[]` / `bids[]` are different lengths.
- **All timestamps are IST (`Asia/Kolkata`)** in the DataFrame returned by `history`. Drop the timezone for vbt compatibility.
