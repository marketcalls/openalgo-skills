# Analyzer (Sandbox) — Reference

The Analyzer mode flips the OpenAlgo SDK into a simulated execution
environment. Order endpoints return realistic-looking responses (with
fake orderids) but no orders leave the broker layer. Critical safety
infrastructure for iterating on a new strategy.

| Endpoint | Method | Returns | Used for |
|----------|--------|---------|----------|
| Current mode | `client.analyzerstatus()` | `{status, data{analyze_mode, mode, total_logs}}` | branch on mode at startup |
| Toggle on/off | `client.analyzertoggle(mode=True/False)` | `{status, data{...}}` | switch between live and sim |

Inspect simulated trades at `<host>/analyzer` in the web UI. Each call hits an SQLite log (`db/sandbox.db`) with ₹1 Crore sandbox capital.

---

## analyzerstatus

### Request

```python
client.analyzerstatus()
```

### Success Response

```json
{
  "status": "success",
  "data": {
    "analyze_mode": true,
    "mode":         "analyze",
    "total_logs":   2
  }
}
```

When live: `analyze_mode: false`, `mode: "live"`.

### Read these fields

| Field | Used for |
|-------|----------|
| `data.analyze_mode` | bool — `True` means we are in sandbox |
| `data.mode` | string — `"analyze"` or `"live"` for log/alert text |
| `data.total_logs` | how many analyzer logs accumulated this session |

### Banner pattern (top of every strategy)

```python
status = client.analyzerstatus()["data"]
if status["analyze_mode"]:
    print(f"[ANALYZER] simulated mode — orders will NOT reach broker."
          f" logs so far: {status['total_logs']}")
else:
    print("[LIVE] orders WILL execute on the broker. Confirm before placing.")
```

---

## analyzertoggle

### Request

```python
# Switch to analyzer (simulated)
client.analyzertoggle(mode=True)

# Switch back to live
client.analyzertoggle(mode=False)
```

### Success Response

```json
{
  "status": "success",
  "data": {
    "analyze_mode": true,
    "mode":         "analyze",
    "message":      "Analyzer mode switched to analyze",
    "total_logs":   2
  }
}
```

### Pattern — guarded go-live

```python
# 1. Iterate in sandbox
client.analyzertoggle(mode=True)
my_strategy.run()    # places fake orders, inspects analyzer logs

# 2. After review, go live with explicit human confirmation
if input("Strategy reviewed. Go live? [y/N] ").strip().lower() == "y":
    client.analyzertoggle(mode=False)
    my_strategy.run()
```

### Gotcha

`analyzertoggle` is global to the OpenAlgo instance. If another
strategy is also running, toggling affects them too. For per-strategy
sandboxing, run on a separate OpenAlgo instance or use a strategy
flag that no-ops the actual broker call.

---

## When analyzer mode is invaluable

- **First-time strategy live-trading.** Place 10 fake orders, inspect
  the analyzer logs, fix any logic bugs before risking real money.
- **CI / smoke tests** that hit the SDK without polluting the live
  order book.
- **Demonstrating a strategy to a new team member** — toggle on,
  walk through, toggle off when done.

## When NOT to use it

- **Latency-sensitive backtesting.** Analyzer logs to SQLite — too slow
  for high-frequency simulation. Use vectorbt with the
  vectorbt-backtesting-skills package instead.
- **Validating broker-specific edge cases** (lot-size rounding, freeze
  quantity, MTF holdings, etc.). Analyzer simulates the OpenAlgo path,
  not the broker plugin's full validation. Place real test orders for
  exactly 1 share on a liquid stock when you need to verify broker
  behaviour.

---

## Chains with

- `analyzerstatus` at script startup -> log banner -> proceed
- `analyzertoggle(True)` in tests -> run -> `analyzertoggle(False)` in teardown
- See [common-workflows.md](common-workflows.md) — analyzer is the default safety wrapper for every example
