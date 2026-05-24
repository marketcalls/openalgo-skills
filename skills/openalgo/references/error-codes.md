# Error Codes & Troubleshooting — Reference

OpenAlgo's REST API returns errors in one shape:

```json
{ "status": "error", "message": "<human-readable reason>" }
```

The HTTP status code adds context but the SDK exposes the parsed dict directly. Match on `status == "error"` first; consult `message` for diagnosis.

| HTTP Code | Typical SDK status | Meaning |
|-----------|-------------------|---------|
| 200 | `"success"` | OK — read the rest of the response |
| 400 | `"error"` | Validation error (bad symbol, missing field, lot violation) |
| 401 | `"error"` | API key missing or invalid |
| 403 | `"error"` | API key valid but lacking permission, or broker session expired |
| 404 | `"error"` | Endpoint or symbol not found |
| 429 | `"error"` | Rate-limited — see [rate-limits.md](rate-limits.md) |
| 500 | `"error"` | Internal — usually a broker plugin issue or upstream timeout |

---

## Common errors and fixes

### "Invalid API key"

```json
{ "status": "error", "message": "Invalid API key" }
```

Check `.env`:
- Is `OPENALGO_API_KEY` set?
- Did you copy the full 64-char key without surrounding quotes / whitespace?
- Did you regenerate the key on `/apikey` and forget to update `.env`?

Verify by hitting a free endpoint:

```python
from scripts.openalgo_client import get_client
client = get_client()
print(client.intervals())
```

If `intervals()` works but order placement does not, see "Broker session expired" below.

### "Broker session expired" / 403 on order placement

OpenAlgo runs on a daily broker session that expires at ~3 AM IST.

1. Log into the OpenAlgo web UI.
2. Re-authenticate with your broker (Zerodha redirect, Dhan OAuth, etc.).
3. The new session token is encrypted into `openalgo.db`.
4. Retry the script.

If the broker requires static IP whitelisting (SEBI mandate from 1 Apr 2026) and the server's IP has changed, orders silently fail at the broker side rather than at OpenAlgo. The fix is on the broker dashboard.

### "Lot size violation" / "quantity is not a multiple of lotsize"

```json
{ "status": "error", "message": "Quantity must be in multiples of 75" }
```

The F&O symbol's lot size has changed (SEBI quarterly revision). Use the
live source rather than the bundled snapshot:

```python
from scripts.lotsize import lot_for_via_symbol_api
lot = lot_for_via_symbol_api(client, "NIFTY30JUN26FUT", "NFO")
```

### "Insufficient funds" / "Insufficient margin"

The broker's pre-trade margin check failed. Run an explicit calc:

```python
from scripts.responses import total_margin_required, available_cash

needed = total_margin_required(client.margin(positions=[...]))
have   = available_cash(client.funds())
print(f"need Rs {needed:,.0f}; have Rs {have:,.0f}; short Rs {needed - have:,.0f}")
```

Reduce lots or pledge collateral. Note CNC orders also need full notional, not just the SPAN.

### "Symbol not found" / unknown symbol

Either:

- The OpenAlgo symbol string is wrong — typo, wrong exchange, expired contract.
  - Use `client.search(query=...)` to fuzzy-match.
- The instrument master is stale.
  - Reload via the web UI: `/master_contract/load`
  - Or pull fresh via `client.instruments(exchange='NFO')` and inspect.

### "trigger_price is required for SL / SL-M"

The SDK requires explicit `trigger_price` for stop orders, even if you
pass `0` for `price` on SL-M:

```python
client.placeorder(
    ...,
    price_type="SL-M",
    quantity="10",
    price="0",
    trigger_price="850.00",     # this is the trigger
)
```

### "Order rejected: market closed"

Check `client.timings(date=today)` and `client.checkholiday(date=today)`.
After-market orders (AMO) require `validity="AMO"` and `amo_time="OPEN"`.

### "Subscription not active" / "Data plan required"

Quote / history / depth / option chain require an active broker data
plan in most cases. Confirm via:

```python
# Many plugins surface this on the broker side; check the broker UI.
# OpenAlgo passes through the error verbatim.
```

For Dhan-style errors `DH-902` or `806` see the dhanhq-skills package — same diagnosis applies (data plan or static IP).

### WebSocket: "Authentication failed"

The WebSocket auth uses the same API key as REST. If REST works but
WebSocket doesn't:

- Check `OPENALGO_WS_URL` — `ws://` for HTTP host, `wss://` for HTTPS.
- For nginx-proxied deployments use the `/ws` path: `wss://yourdomain.com/ws`.
- Verify the WS port (default 8765) is open in your firewall.

### WebSocket: "Unsupported depth level"

```json
{
  "type": "error",
  "code": "UNSUPPORTED_DEPTH_LEVEL",
  "supported_depths": [5, 20]
}
```

The connected broker doesn't support the requested depth. Use a value
from `supported_depths`:

```python
def safe_subscribe_depth(client, instruments, preferred=20):
    for d in (preferred, 20, 5):
        try:
            client.subscribe_depth(instruments, on_data_received=cb, depth_level=d)
            return d
        except Exception as e:
            if "UNSUPPORTED_DEPTH_LEVEL" in str(e):
                continue
            raise
    raise RuntimeError("no supported depth level")
```

---

## Generic error-handling pattern

```python
import time
from scripts.responses import ResponseError, ensure_success
from scripts.alerts    import fmt_error, notify

def safe_call(fn, *args, where: str, strategy: str, retries: int = 3, **kwargs):
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            return ensure_success(fn(*args, **kwargs), action=where)
        except ResponseError as e:
            last_exc = e
            msg_low = str(e).lower()
            if any(t in msg_low for t in ("rate", "429")):
                time.sleep(1 + attempt * 2)
                continue
            if "session" in msg_low or "auth" in msg_low:
                # token / session issue — don't retry; raise loudly
                break
            time.sleep(0.5)
    msg = fmt_error(strategy=strategy, where=where, error=str(last_exc))
    notify(client, msg, via=("telegram",))
    raise last_exc      # re-raise after alert
```

Wrap any non-retried call site:

```python
funds = safe_call(client.funds, where="funds", strategy=STRAT)
```

---

## Log files

OpenAlgo writes JSON-Lines errors to `<openalgo>/log/errors.jsonl`. When
diagnosing a strange error, this is the first place to look — every
ERROR-level log lands here with full traceback and request context.

```bash
tail -50 /srv/openalgo/log/errors.jsonl | jq .
```

Each line contains: `timestamp`, `logger`, `module`, source file/line,
error message, traceback, and (when available) the Flask request
context (method, path, IP).
