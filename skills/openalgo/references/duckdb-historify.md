# DuckDB Historify — Direct Access Reference

OpenAlgo's `Historify` module continuously ingests OHLCV bars (1m and
daily) into a local DuckDB file. Reading that file **directly** is the
fastest path to historical data for bulk pulls — orders of magnitude
quicker than `client.history(..., source="db")` because there is no
HTTP round-trip per query.

| Path | Default location | When to use |
|------|------------------|-------------|
| **REST** | `client.history(..., source="db")` | single-symbol, single-day, ad-hoc |
| **Direct** | `<openalgo>/db/historify.duckdb` via [`scripts.duckdb_data`](../scripts/duckdb_data.py) | bulk multi-symbol, full lookback, backtests |

For live tick data the answer is always WebSocket — see [websocket-streaming.md](websocket-streaming.md).

---

## Setup

Set the path in `.env`:

```bash
HISTORIFY_DUCKDB_PATH=/srv/openalgo/db/historify.duckdb
```

`scripts/duckdb_data.py` reads this automatically via
`scripts.openalgo_client.historify_duckdb_path()`. To override per-call,
pass `db_path=...` to any function.

DuckDB is opened **read-only** — the helper never holds a write lock
while OpenAlgo is also writing.

---

## Schema

```sql
CREATE TABLE market_data (
    symbol      VARCHAR,
    exchange    VARCHAR,
    timestamp   BIGINT,        -- epoch seconds, IST anchored
    open        DOUBLE,
    high        DOUBLE,
    low         DOUBLE,
    close       DOUBLE,
    volume      BIGINT
);

CREATE INDEX idx_market_data_symbol ON market_data(symbol, exchange);
CREATE INDEX idx_market_data_ts     ON market_data(timestamp);
```

(The exact indexes depend on the Historify version, but every install
indexes `(symbol, exchange)` at minimum.)

### Legacy custom schema

Some older or user-customized installs use:

```sql
CREATE TABLE ohlcv (
    symbol   VARCHAR,
    date     DATE,
    time     TIME,
    open     DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
    volume   BIGINT
);
```

If you see this shape, fall back to the resampling pattern documented
in the vectorbt skill's `duckdb-data.md` rule file. The
`scripts.duckdb_data` helpers default to the modern `market_data`
schema — adapt the SQL if needed.

---

## Single-symbol load

```python
from scripts.duckdb_data import load_ohlcv

df = load_ohlcv(
    symbol="SBIN",
    exchange="NSE",
    start="2024-01-01",
    end="2026-05-24",
)
print(df.tail())
```

Returns a `pandas.DataFrame` indexed by tz-naive IST timestamp (so it
plugs straight into vectorbt without `tz_convert(None)` boilerplate).

### Read these fields

| Column | Used for |
|--------|----------|
| `df.index` | tz-naive datetime (IST), ascending |
| `df["close"]` | indicator input, signal generation |
| `df["volume"]` | volume confirmation, VWAP |

---

## Multi-symbol wide load

The one query, many symbols pattern — ideal for breadth scanners,
sector heatmaps, correlation matrices.

```python
from scripts.duckdb_data import load_multi

# Wide DataFrame: index=timestamp, columns=symbols, values=close
close = load_multi(
    symbols=["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"],
    exchange="NSE",
    start="2026-01-01",
    end="2026-05-24",
    field="close",
)
print(close.tail())
```

Columns preserve the input order (with missing symbols filled as NaN
column). Switching `field=` between `open`, `high`, `low`, `close`,
`volume` is one keyword change.

### Use cases

- Equal-weight rebalancing: `close.pct_change().sum(axis=1)` -> daily
  basket returns
- Sector heatmap: `close.iloc[-1] / close.iloc[0] - 1` -> percent
  change vector for a heatmap chart
- Correlation: `close.pct_change().corr()` -> symmetric corr matrix

---

## Resampling — NSE 09:15 IST alignment

A 1-minute DataFrame resampled to 5m needs to start on 09:15:00, not
09:00:00 — otherwise the first bar would span 09:15-09:20 only partially.
`resample_ist` uses `origin="start_day", offset="9h15min"` to align
correctly:

```python
from scripts.duckdb_data import load_ohlcv, resample_ist

m1 = load_ohlcv("NIFTY", "NSE_INDEX", "2026-05-01", "2026-05-24")
m5 = resample_ist(m1, "5min")        # OHLC aggregated correctly
m15 = resample_ist(m1, "15min")
mhour = resample_ist(m1, "60min")
```

OHLC aggregation: `open=first, high=max, low=min, close=last, volume=sum`.

---

## Discovery helpers

What symbols / exchanges are available locally?

```python
from scripts.duckdb_data import list_symbols, date_range

nse_symbols = list_symbols("NSE")            # list[str]
print(len(nse_symbols), "NSE symbols stored")

stats = date_range("SBIN", "NSE")
# {"symbol": "SBIN", "exchange": "NSE", "rows": 1234567,
#  "first": Timestamp(...), "last": Timestamp(...)}
print(stats)
```

`date_range` is critical before any backtest — confirms data exists
for the window you care about and rules out a backtest "succeeding"
on 5 rows.

---

## Why direct beats REST for bulk

| Operation | REST (`source="db"`) | Direct |
|-----------|---------------------|--------|
| 1 symbol, 1 year of daily | ~300ms | ~5ms |
| 50 symbols, 1 year of daily | ~15s | ~50ms |
| 1 symbol, 5 years of 1-min | ~2s | ~50ms |
| All NSE EQ symbols, 1 year | ~10min (50 req-batches) | ~2s |

Round-trips dominate for small queries; the savings compound for any
loop over symbols.

---

## Common patterns

### Backtest setup (paired with vectorbt skill)

```python
import vectorbt as vbt
import talib as tl
from openalgo import ta
from scripts.duckdb_data import load_ohlcv

df = load_ohlcv("SBIN", "NSE", "2024-01-01", "2026-05-24")
close, high, low = df["close"], df["high"], df["low"]

ema_fast = tl.EMA(close.values, timeperiod=10)
ema_slow = tl.EMA(close.values, timeperiod=20)
buy_raw  = (ema_fast > ema_slow) & (pd.Series(ema_fast).shift(1) <= pd.Series(ema_slow).shift(1))
sell_raw = (ema_fast < ema_slow) & (pd.Series(ema_fast).shift(1) >= pd.Series(ema_slow).shift(1))
entries  = ta.exrem(pd.Series(buy_raw, index=close.index).fillna(False),
                    pd.Series(sell_raw, index=close.index).fillna(False))
exits    = ta.exrem(pd.Series(sell_raw, index=close.index).fillna(False),
                    pd.Series(buy_raw, index=close.index).fillna(False))

pf = vbt.Portfolio.from_signals(
    close, entries, exits,
    init_cash=1_000_000, size=0.75, size_type="percent",
    fees=0.00111, fixed_fees=20, direction="longonly",
    min_size=1, size_granularity=1, freq="1D",
)
print(pf.stats())
```

### Cross-sectional ranking

```python
from scripts.duckdb_data import load_multi

universe = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN",
            "BAJFINANCE", "BHARTIARTL", "ITC", "HINDUNILVR"]
close = load_multi(universe, "NSE", "2026-04-01", "2026-05-24", field="close")

# 20-day momentum
mom20 = close.pct_change(20).iloc[-1].sort_values(ascending=False)
print("Top 3 by 20-day momentum:")
print(mom20.head(3))
```

### Pre-flight data check

```python
from scripts.duckdb_data import date_range

for sym in ["SBIN", "RELIANCE", "TCS"]:
    r = date_range(sym, "NSE")
    if r["rows"] < 1000:
        print(f"SKIP {sym}: only {r['rows']} rows")
        continue
    print(f"OK   {sym}: {r['rows']} rows from {r['first'].date()} to {r['last'].date()}")
```

---

## Gotchas

- **Read-only mode required.** `duckdb.connect(path, read_only=True)`
  — if OpenAlgo holds a write lock and you open read-write, you
  collide.
- **Timestamps are epoch seconds, IST-anchored.** When you join with
  other timestamp sources, normalize to either tz-aware UTC or
  tz-naive IST consistently.
- **Resampling without `origin=` is wrong.** A naive `df.resample('5min')`
  starts bars at 00:00, not 09:15 — your 09:15-09:20 bar will be half
  the data of every other bar.
- **DuckDB locks across processes.** Run one query at a time per
  connection, or open multiple connections. `concurrent.futures` with
  shared connections will fail.
- **Custom schema fallback.** Detect with `con.execute("SELECT table_name FROM information_schema.tables").fetchall()` — if `market_data` is absent and `ohlcv` is present, use the legacy path.

---

## Refreshing Historify

OpenAlgo writes to the DuckDB on its own schedule (configured in the
Historify UI). You don't manage the file manually. For an explicit
refresh:

1. Open the `/historify` page in the OpenAlgo web UI.
2. Pick the symbols and intervals to backfill.
3. Trigger the backfill — writes complete on the server side.

After a backfill, the next direct DuckDB query sees the new data
immediately (no client cache to invalidate).
