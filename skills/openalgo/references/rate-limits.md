# Rate Limits — Reference

OpenAlgo enforces differentiated rate limits to protect both itself
and the upstream broker APIs. Exceeding a limit returns 429
`{"status": "error", "message": "rate limit ..."}` — never crash;
always retry with backoff.

| API Class | Rate (req/sec) | Notes |
|-----------|---------------:|-------|
| Order Management | 10 | place / modify / cancel / close |
| Smart Orders | 2 | `placesmartorder` only — heavier server-side |
| General APIs | 50 | quotes / depth / history / books / option chain etc. |
| Webhooks | 100 / min | inbound webhook deliveries (different ceiling shape) |

These are the platform-level limits. The connected broker may have its
own — see [error-codes.md](error-codes.md) for plugin-specific 429s.

---

## Built-in retry policy

`scripts/orders.py` retries on transient rate-limit responses with
fixed backoff:

```python
_RETRY_DELAYS_SEC = (0.5, 1.5, 3.5)   # exponential-ish; total wait < 6s
```

`place_with_retry`, `modify_with_retry`, `cancel_with_retry` use this.
After three retries it returns the last failing response — caller
inspects `status` / `message` and decides whether to give up or escalate.

The matching `_looks_rate_limited(resp)` heuristic matches on substrings
`"rate"`, `"429"`, `"too many"` in the message field, since brokers
phrase the error inconsistently.

---

## Tactical guidance

### Place-and-track loops

A tight loop placing-and-cancelling will saturate the order-management
bucket inside 1 second. Sleep at least 100ms between placements, or
batch with `basketorder`:

```python
# DON'T
for sym in nifty50:
    client.placeorder(...)

# DO
client.basketorder(orders=[
    {"symbol": s, ...} for s in nifty50
])
```

### Scanners

`multiquotes` lets you fetch many symbols in one request — much
better than looping `quotes`:

```python
# DON'T (50 requests, hits 50/sec ceiling on a busy box)
for sym in universe:
    client.quotes(symbol=sym, exchange="NSE")

# DO (single request, no rate concerns)
client.multiquotes(symbols=[{"symbol": s, "exchange": "NSE"} for s in universe])
```

### Option chain Greeks across all strikes

`optiongreeks` is one call per strike. Throttle to ~10/sec:

```python
import time
for strike in strikes:
    r = client.optiongreeks(...)
    time.sleep(0.1)
```

`scripts.option_analytics.iv_skew` already does this internally.

### Live polling loops

A 1-second poll on `orderstatus` is fine; 100ms can saturate. The
`poll_until_filled` default is 500ms which fits inside the limits
comfortably.

---

## Detecting rate-limit responses

The SDK does not currently raise a typed exception for 429 — the
response is a normal dict with `status="error"` and a descriptive
`message`. Always inspect:

```python
resp = client.placeorder(...)
if resp.get("status") != "success":
    msg = resp.get("message", "").lower()
    if any(t in msg for t in ("rate", "429", "too many")):
        time.sleep(2)
        resp = client.placeorder(...)
    else:
        raise RuntimeError(f"order failed: {resp}")
```

Or use the helpers in `scripts/orders.py` which embed this logic.

---

## WebSocket throttling

Subscriptions themselves do not count against REST rate limits.
However:

- Some brokers cap **total subscribed symbols per WebSocket session**
  (default 1000 per connection in OpenAlgo, configurable via
  `MAX_SYMBOLS_PER_WEBSOCKET`).
- A single OpenAlgo instance can hold up to `MAX_WEBSOCKET_CONNECTIONS`
  (default 3) broker connections, so 3000 symbols max in stock config.
- Per-symbol tick throttling kicks in for clients that can't keep up —
  the proxy drops stale ticks to prevent flooding. Tune by
  `WEBSOCKET_THROTTLE_MS` if you need every tick.

For >3000 symbols you need a custom broker plugin config or a second
OpenAlgo instance.

---

## Production checklist

- [ ] Every `placeorder` call goes through `place_with_retry`
- [ ] Every `modifyorder` / `cancelorder` likewise
- [ ] Scanners batched via `multiquotes`, not `quotes` loops
- [ ] `orderstatus` poll interval ≥ 500ms (use `poll_until_filled` defaults)
- [ ] Greek scans throttled to ≤ 10/sec
- [ ] Webhook publishers respect 100/min cap
- [ ] Long-running strategy wrapped in `try/except ResponseError`, alerts on failure
