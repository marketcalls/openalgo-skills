# Market Calendar — Reference

Holiday and trading-hours queries for the Indian exchanges (NSE, BSE,
NFO, BFO, CDS, BCD, MCX). Useful for skipping non-trading days in
scheduled jobs and computing days-to-expiry correctly.

| Endpoint | Method | Returns | Used for |
|----------|--------|---------|----------|
| Year of holidays | `client.holidays(year=2026)` | `{status, data[]}` | calendar visualization, skip-list |
| Single-day timings | `client.timings(date='2026-05-24')` | `{status, data[]}` | per-day session start/end (epoch ms) |
| Is `date` a holiday | `client.checkholiday(date='2026-05-24')` | `{status, ...}` | quick boolean gate |

---

## holidays

### Request

```python
client.holidays(year=2026)
```

### Success Response (truncated)

```json
{
  "status": "success",
  "data": [
    {
      "closed_exchanges": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX"],
      "date":             "2026-01-26",
      "description":      "Republic Day",
      "holiday_type":     "TRADING_HOLIDAY",
      "open_exchanges":   []
    },
    {
      "closed_exchanges": [],
      "date":             "2026-02-19",
      "description":      "Chhatrapati Shivaji Maharaj Jayanti",
      "holiday_type":     "SETTLEMENT_HOLIDAY",
      "open_exchanges":   []
    },
    {
      "closed_exchanges": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD"],
      "date":             "2026-03-10",
      "description":      "Holi",
      "holiday_type":     "TRADING_HOLIDAY",
      "open_exchanges":   [
        {"end_time": 1741677900000, "exchange": "MCX",
         "start_time": 1741624200000}
      ]
    }
  ]
}
```

### Read these fields

| Field | Used for |
|-------|----------|
| `data[].date` | ISO `YYYY-MM-DD` |
| `data[].closed_exchanges[]` | which exchanges are shut |
| `data[].holiday_type` | `TRADING_HOLIDAY` (no trading) vs. `SETTLEMENT_HOLIDAY` (trading open, banks shut) |
| `data[].open_exchanges[]` | partial-day rules (e.g. MCX open on Holi afternoon) |

### Convert to a pandas Series

```python
import pandas as pd

raw = client.holidays(year=2026)["data"]
df = pd.DataFrame(raw)
trading_off = df[
    (df["holiday_type"] == "TRADING_HOLIDAY")
    & df["closed_exchanges"].apply(lambda x: "NSE" in x)
]
print(trading_off[["date", "description"]])
```

### Chains with

- Build a per-year holiday set at session start -> skip cron-scheduled jobs on those dates
- Compute accurate days-to-expiry by subtracting holiday count from raw calendar days

---

## timings

### Request

```python
client.timings(date="2026-05-24")
```

### Success Response

```json
{
  "status": "success",
  "data": [
    {"end_time": 1766138400000, "exchange": "NSE", "start_time": 1766115900000},
    {"end_time": 1766138400000, "exchange": "BSE", "start_time": 1766115900000},
    {"end_time": 1766138400000, "exchange": "NFO", "start_time": 1766115900000},
    {"end_time": 1766138400000, "exchange": "BFO", "start_time": 1766115900000},
    {"end_time": 1766168700000, "exchange": "MCX", "start_time": 1766115000000},
    {"end_time": 1766143800000, "exchange": "BCD", "start_time": 1766115000000},
    {"end_time": 1766143800000, "exchange": "CDS", "start_time": 1766115000000}
  ]
}
```

`start_time` and `end_time` are **epoch milliseconds, IST-anchored**.

### Read these fields

| Field | Used for |
|-------|----------|
| `data[].exchange` | which exchange — filter to the one you trade |
| `data[].start_time` | session open (ms epoch) |
| `data[].end_time` | session close (ms epoch) |

### Convert to local datetimes

```python
import pandas as pd

tt = client.timings(date="2026-05-24")["data"]
df = pd.DataFrame(tt)
df["start"] = pd.to_datetime(df["start_time"], unit="ms", utc=True).dt.tz_convert("Asia/Kolkata")
df["end"]   = pd.to_datetime(df["end_time"],   unit="ms", utc=True).dt.tz_convert("Asia/Kolkata")
print(df[["exchange", "start", "end"]])
```

Typical NSE / BSE: `09:15` to `15:30`. MCX runs longer: `09:00` to `23:30/23:55` depending on session.

### Chains with

- Pre-market preparation cron -> read `timings(today)` -> sleep until `start_time` -> kick off intraday loop
- End-of-day cleanup -> read `end_time` -> schedule `closeposition` 5 minutes before
- `examples/01_execution/intraday_loop_with_session.py` demonstrates the full pattern

---

## checkholiday

Returns whether a specific date is a holiday on the connected
broker's exchanges. Simpler than parsing `holidays(year)` for a
single-day check.

### Request

```python
client.checkholiday(date="2026-05-24")
```

### Response

The exact shape varies by broker plugin — generally returns
`{status, is_holiday, exchanges_closed: [...], description: "..."}`.
Always gate on `is_holiday` boolean:

```python
resp = client.checkholiday(date="2026-05-24")
if resp.get("is_holiday"):
    print(f"Holiday: {resp.get('description')}")
    raise SystemExit("market closed today; skipping run")
```

For programmatic correctness, prefer pulling the full year via
`holidays()` once and querying your own set — it cuts API calls and
handles partial-day exchanges more cleanly.

---

## Pattern — robust scheduled job

```python
from datetime import datetime
import time, pandas as pd

today = datetime.now().strftime("%Y-%m-%d")

# 1. holiday check
hols = client.holidays(year=datetime.now().year)["data"]
trading_off = {
    h["date"] for h in hols
    if h["holiday_type"] == "TRADING_HOLIDAY" and "NSE" in h["closed_exchanges"]
}
if today in trading_off:
    raise SystemExit(f"NSE closed today ({today}); strategy not running")

# 2. wait for market open
tt = pd.DataFrame(client.timings(date=today)["data"])
nse_open = pd.to_datetime(tt[tt["exchange"] == "NSE"].iloc[0]["start_time"], unit="ms", utc=True)
nse_open_local = nse_open.tz_convert("Asia/Kolkata").to_pydatetime()
wait = (nse_open_local - datetime.now(tz=nse_open_local.tzinfo)).total_seconds()
if wait > 0:
    time.sleep(wait)

# 3. run intraday strategy
run_strategy_until(nse_close_local)
```

This is the boilerplate every scheduled OpenAlgo strategy needs at startup.
