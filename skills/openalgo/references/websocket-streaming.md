# WebSocket Streaming — Reference

Real-time tick stream over WebSocket. Three subscription modes (LTP,
Quote, Depth), four depth levels (5/20/30/50), and three verbose
levels (silent / basic / debug).

| SDK Method | Mode | Payload size | Use case |
|-----------|------|--------------|----------|
| `client.subscribe_ltp(instruments, on_data_received)` | 1 (LTP) | smallest | tape, alert triggers |
| `client.subscribe_quote(instruments, on_data_received)` | 2 (Quote) | OHLC + LTP + vol | dashboards, scanners |
| `client.subscribe_depth(instruments, on_data_received, depth_level=5)` | 3 (Depth) | full book | order-book strategies, depth ladders |

Always use the high-level wrapper [`scripts/stream.py::subscribe(...)`](../scripts/stream.py) — it handles connect / auth / unsubscribe / disconnect in a context manager.

---

## URL and authentication

`OPENALGO_WS_URL` from `.env`:

| Setup | URL |
|-------|-----|
| Local development | `ws://127.0.0.1:8765` |
| Production (root domain) | `wss://yourdomain.com/ws` |
| Production (subdomain) | `wss://sub.yourdomain.com/ws` |

Authentication is automatic via the SDK — it sends the API key on
`connect()`. If you go raw (without the SDK) the auth frame is:

```json
{ "action": "authenticate", "api_key": "YOUR_OPENALGO_API_KEY" }
```

---

## Mode 1 — LTP

Smallest payload. Use when you only need the last traded price + tick
timestamp.

### Subscribe

```python
client.connect()

instruments = [
    {"exchange": "NSE_INDEX", "symbol": "NIFTY"},
    {"exchange": "NSE",       "symbol": "RELIANCE"},
]

def on_ltp(msg):
    d = msg["data"]
    print(d["symbol"], d["ltp"], d["timestamp"])

client.subscribe_ltp(instruments, on_data_received=on_ltp)
```

### Tick message format

```json
{
  "type":  "market_data",
  "mode":  1,
  "topic": "RELIANCE.NSE",
  "data": {
    "symbol":    "RELIANCE",
    "exchange":  "NSE",
    "ltp":       1424.0,
    "timestamp": "2026-05-24T10:30:45.123Z"
  }
}
```

### Read these fields

| Field | Used for |
|-------|----------|
| `data.ltp` | price level for SL trigger checks, alert thresholds |
| `data.timestamp` | tick recency / staleness check |
| `data.symbol` / `data.exchange` | routing in `CallbackRouter` |

---

## Mode 2 — Quote

Full OHLC + LTP + volume + change-from-prev. Use for dashboards, live
heatmaps, intraday scanners.

### Subscribe

```python
def on_quote(msg):
    d = msg["data"]
    print(f"{d['symbol']:<10} O {d['open']}  H {d['high']}  L {d['low']}  LTP {d['ltp']}")

client.subscribe_quote(instruments, on_data_received=on_quote)
```

### Tick message format

```json
{
  "type":  "market_data",
  "mode":  2,
  "topic": "RELIANCE.NSE",
  "data": {
    "symbol":              "RELIANCE",
    "exchange":            "NSE",
    "ltp":                 1424.0,
    "change":              6.0,
    "change_percent":      0.42,
    "volume":              100000,
    "open":                1415.0,
    "high":                1432.5,
    "low":                 1408.0,
    "close":               1418.0,
    "last_trade_quantity": 50,
    "avg_trade_price":     1419.35,
    "timestamp":           "2026-05-24T10:30:45.123Z"
  }
}
```

### Read these fields

| Field | Used for |
|-------|----------|
| `data.ltp` + `data.change_percent` | live ranking in a heatmap |
| `data.volume` | volume-surge filters in live scanners |
| `data.avg_trade_price` | VWAP cross signals |
| `data.last_trade_quantity` | tape-reading |

### Polling cached quotes

The SDK keeps the latest quote per (exchange, symbol) in an in-memory
cache. Call `client.get_quotes()` to read the snapshot without waiting
for the next push — useful for one-off polls inside a longer-running
loop:

```python
snap = client.get_quotes()
print(snap["quote"]["NSE"]["RELIANCE"]["ltp"])
```

Shape: `{ "quote": { exchange: { symbol: data_dict } } }`.

---

## Mode 3 — Depth

Full Level-2 order book. The broker plugin determines how deep the book
goes; pass `depth_level` to ask for a specific size.

### Depth levels (mode 3)

| `depth_level` | Levels per side | Typical broker support |
|--------------|------------------|------------------------|
| 5  | 5  | universal (lowest common denominator) |
| 20 | 20 | many — Zerodha, Upstox, Dhan, IIFL... |
| 30 | 30 | some |
| 50 | 50 | a few; Angel One supports for select symbols |

If the requested depth is not supported, the server returns an explicit error rather than silently downgrading.

### Subscribe

```python
def on_depth(msg):
    d = msg["data"]
    print(f"{d['symbol']}  LTP {d['ltp']}")
    for ask in d["depth"]["sell"][:5]:
        print(f"  ASK  {ask['price']}  x {ask['quantity']}")
    for bid in d["depth"]["buy"][:5]:
        print(f"  BID  {bid['price']}  x {bid['quantity']}")

client.subscribe_depth(instruments, on_data_received=on_depth, depth_level=20)
```

### Tick message format (depth_level=5)

```json
{
  "type":  "market_data",
  "mode":  3,
  "depth_level": 5,
  "topic": "RELIANCE.NSE",
  "data": {
    "symbol":   "RELIANCE",
    "exchange": "NSE",
    "ltp":      1424.0,
    "depth": {
      "buy": [
        {"price": 1423.9, "quantity": 50, "orders": 3},
        {"price": 1423.5, "quantity": 35, "orders": 2},
        ...
      ],
      "sell": [
        {"price": 1424.1, "quantity": 47, "orders": 2},
        {"price": 1424.5, "quantity": 39, "orders": 3},
        ...
      ]
    },
    "timestamp":        "2026-05-24T10:30:45.123Z",
    "broker_supported": true
  }
}
```

### Read these fields

| Field | Used for |
|-------|----------|
| `data.depth.buy[]` (sorted best-to-worst) | bid ladder |
| `data.depth.sell[]` (sorted best-to-worst) | ask ladder |
| `data.depth.buy[0].price` | best bid (touch) |
| `data.depth.sell[0].price` | best ask (touch) |
| `data.broker_supported` | tells you if broker delivered the requested depth |

### Error — unsupported depth

```json
{
  "type":              "error",
  "code":              "UNSUPPORTED_DEPTH_LEVEL",
  "message":           "Depth level 50 is not supported by broker Angel for exchange NSE",
  "symbol":            "RELIANCE",
  "exchange":          "NSE",
  "requested_mode":    3,
  "requested_depth":   50,
  "supported_depths":  [5, 20]
}
```

Always provide a fallback (e.g. retry at the highest supported depth).

---

## Verbose levels — SDK logging control

Independent of the data callback. Controls what the SDK itself prints
about connection / auth / subscription lifecycle.

```python
client = api(api_key="...", host="...", ws_url="...", verbose=False)  # silent (default)
client = api(api_key="...", host="...", ws_url="...", verbose=True)   # basic
client = api(api_key="...", host="...", ws_url="...", verbose=2)      # debug
```

| Level | Value | Output |
|-------|-------|--------|
| Silent | `False` / `0` | errors only |
| Basic  | `True` / `1` | `[WS]` `[AUTH]` `[SUB]` `[UNSUB]` events |
| Debug  | `2` | + every tick: `[LTP]`, `[QUOTE]`, `[DEPTH]` |

The `[ERROR]` tag fires at every level. User callbacks (`on_data_received`) are independent — they always run regardless of verbose level.

---

## Subscribe — context manager (preferred)

The raw SDK calls are easy to leave dangling on Ctrl-C. The
`subscribe()` helper handles the full lifecycle:

```python
from scripts.stream import subscribe

instruments = [
    {"exchange": "NSE_INDEX", "symbol": "NIFTY"},
    {"exchange": "NSE",       "symbol": "RELIANCE"},
]

def on_ltp(msg):
    d = msg["data"]
    print(d["symbol"], d["ltp"])

with subscribe(client, instruments, mode="ltp", on_data=on_ltp):
    time.sleep(60)
# auto-unsubscribes and disconnects on exit, even on Ctrl-C / exception
```

Same shape for `mode="quote"` and `mode="depth"` (pass `depth_level=` for depth).

---

## Block-until-Ctrl-C

```python
from scripts.stream import run_until_interrupt

run_until_interrupt(client, instruments, mode="quote", on_data=on_quote)
# prints a heartbeat every 30s; Ctrl-C exits cleanly
```

---

## Reconnect loop — persistent stream

Broker WebSocket connections drop. The `reconnect_loop` helper
re-creates the client and re-subscribes on any error with exponential
backoff:

```python
from scripts.stream import reconnect_loop
from scripts.openalgo_client import get_client

reconnect_loop(
    client_factory=lambda: get_client(verbose=True),
    instruments=instruments,
    mode="ltp",
    on_data=on_ltp,
    max_retries=100,
    backoff_sec=[1, 2, 5, 10, 30],
)
```

`client_factory` is a zero-arg callable returning a fresh client — wire
in token refresh here if your broker rotates credentials daily.

---

## Callback router — per-symbol handlers

When one stream feeds multiple strategies, route per-symbol:

```python
from scripts.stream import CallbackRouter, subscribe

router = CallbackRouter()

# log every tick
router.register_all(lambda tick: print(tick["data"]["symbol"], tick["data"]["ltp"]))

# alert when NIFTY crosses 26000
def nifty_breach(tick):
    if tick["data"]["ltp"] >= 26000:
        client.telegram(username=os.environ["ALERT_TELEGRAM_USERNAME"],
                        message="NIFTY crossed 26000")
router.register("NIFTY", nifty_breach)

# write RELIANCE ticks to parquet
def reliance_recorder(tick):
    ...
router.register("RELIANCE", reliance_recorder)

with subscribe(client, instruments, mode="ltp", on_data=router.handle):
    time.sleep(3600)
```

---

## Heartbeat and reconnection (low-level)

If you go raw without the SDK or wrapper:
- Server sends `ping` every 30s; client must respond `pong` or be disconnected.
- On reconnect: re-authenticate, re-subscribe.
- Some plugins auto-restore subscriptions on reconnect — never rely on this; always re-subscribe explicitly.

The SDK and `subscribe()` helper handle all this for you.

---

## Common gotchas

- **Mode 3 depth shapes differ from REST `depth`**: the WebSocket uses `data.depth.buy[]` / `data.depth.sell[]`, the REST endpoint uses `data.bids[]` / `data.asks[]`. Don't reuse parsers across them.
- **`on_data_received` runs in the SDK's I/O thread.** Don't block inside it — push to a queue or `concurrent.futures` for any heavy work.
- **Subscriptions are per-session.** Reconnect = re-subscribe. Use `reconnect_loop` rather than reinventing.
- **Index symbols are quote-only.** You can subscribe to `NSE_INDEX:NIFTY`, but you cannot place orders on it directly — trade `NIFTYxxxxxFUT` or option chain instead.
