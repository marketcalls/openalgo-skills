---
name: openalgo
description: >
  OpenAlgo agent skill — comprehensive coverage of the OpenAlgo Python SDK
  for Indian markets (NSE / BSE / NFO / BFO / CDS / BCD / MCX / NCO).
  Use when the user asks to place / modify / cancel orders, build a
  limit-order-chasing or custom execution algo, fetch quotes / depth /
  historical OHLCV (REST or direct DuckDB Historify), pull option chains
  with Greeks, calculate margin or funds, stream live LTP / Quote / Depth
  over WebSocket, build a scanner, render a heatmap / OI chart / candlestick,
  backtest a strategy with vectorbt, send Telegram / WhatsApp alerts,
  or toggle analyzer (sandbox) mode. Also triggers for general questions
  about programmatic trading on Indian exchanges when OpenAlgo is the
  user's platform.
compatibility: >
  Requires Python 3.10+, the OpenAlgo Python SDK
  (`pip install openalgo[indicators]`), and a running OpenAlgo instance
  reachable via REST (`OPENALGO_HOST`) and WebSocket (`OPENALGO_WS_URL`).
  Order placement, modification and cancellation require static IP
  whitelisting at the broker (SEBI mandate from 1 April 2026). Data plan
  status varies by broker. For backtesting and `openalgo.ta`-only work,
  no broker session is required.
---

# OpenAlgo — Trading Skill for Indian Markets

OpenAlgo is a broker-agnostic, self-hosted trading platform. One Python
SDK (`pip install openalgo`) talks to 30+ Indian brokers behind a unified
REST + WebSocket interface. This skill covers the complete SDK surface
plus production-ready helpers and examples for the seven core workflows
traders ask for:

1. **Order execution** — equity, F&O, options-by-offset, multi-leg, basket, split, smart
2. **Custom execution algos** — limit-order chasing, auto-modify, time/price triggered cancel
3. **Scanners** — `multiquotes` + history + filter pipelines
4. **Visualization** — heatmaps, OI charts, seasonality, gainers/losers, PCR dashboards
5. **Backtesting** — vectorbt glue with realistic Indian fees, NIFTY benchmark
6. **Charting** — candles (category x-axis, no weekend gaps), depth ladder, option-chain OI, IV smile
7. **Real-time streaming** — LTP / Quote / Depth WebSocket, reconnect loop, callback routing

## Setup

```bash
pip install -U "openalgo[indicators]"
pip install -r requirements.txt   # includes vectorbt, TA-Lib, plotly, duckdb, dotenv
cp .env.sample .env               # fill in OPENALGO_API_KEY and host/ws URLs
```

Minimal init (every script in this skill starts the same way):

```python
import os
from dotenv import find_dotenv, load_dotenv
from openalgo import api

load_dotenv(find_dotenv(), override=False)

client = api(
    api_key=os.environ["OPENALGO_API_KEY"],
    host=os.environ.get("OPENALGO_HOST", "http://127.0.0.1:5000"),
    ws_url=os.environ.get("OPENALGO_WS_URL", "ws://127.0.0.1:8765"),
)
```

For repo-resident scripts prefer the shared helper:

```python
from scripts.openalgo_client import get_client
client = get_client()
```

## Safety Rules — Always Enforce

1. **Iterate in analyzer mode first.** Toggle `client.analyzertoggle(mode=True)` so the SDK simulates responses without hitting the broker. Switch off only after the strategy is reviewed.
2. **Confirm before live orders.** Print a readable preview (symbol, side, qty, product, price, notional) and wait for user confirmation unless the user has explicitly authorized auto-execution for the current session.
3. **Default to `LIMIT` over `MARKET`.** Quote the symbol first and place a marketable-limit at LTP ± a few ticks. MARKET only when the user explicitly asks.
4. **Validate F&O lot-size multiples.** Load the bundled `assets/LotSize.csv` (or call `client.symbol()` for the current `lotsize`) and reject non-multiples before placement.
5. **Warn on notional > Rs 50,000.** For F&O, use `lotsize × strike` as a worst-case proxy when price is unknown.
6. **Never `CNC` on F&O / commodity / currency.** Only `MIS` (intraday) or `NRML` (overnight) for those segments. `CNC` is equity-delivery only.
7. **Never hardcode API keys.** Always read from `.env` via `find_dotenv()`. Reject scripts that contain literal 64-char hex keys.
8. **Multi-leg execution needs explicit per-leg confirmation** when run live. `optionsmultiorder` and `basketorder` route to the broker as separate orders that can partially fail — handle the `results[]` array, don't trust the top-level `status`.
9. **Rate limits matter.** Order APIs are capped at 10/sec (smart orders 2/sec), data APIs at 50/sec. Use the retry-with-backoff helper in `scripts/orders.py` rather than tight loops.
10. **WebSocket reconnect is the user's responsibility.** Use the `subscribe()` context manager in `scripts/stream.py` — it handles auth, heartbeat, and re-subscription on disconnect.

## File-Output Convention

When this skill **generates** code for a specific action, write outputs
into a per-action subfolder, created on-demand (never pre-created):

```
openalgo_workspace/
├── execution/
│   ├── atm_straddle/             # straddle.py, run.log, trade_journal.csv
│   └── iron_condor/
├── execution_algos/
│   ├── limit_chaser_reliance/    # chaser.py, fills.csv
│   └── twap_slicer_sbin/
├── scanners/
│   ├── rsi_oversold/             # scan.py, results_2026-05-24.csv
│   └── breakout/
├── visualization/
│   └── sector_heatmap/           # heatmap.py, heatmap_2026-05-24.html
├── backtesting/
│   ├── supertrend_sbin/          # backtest.py, trades.csv, equity.html
│   └── ema_crossover_nifty50/
├── charting/
│   └── nifty_option_chain_oi/    # chart.py, oi_27jan26.html
└── streaming/
    └── nifty_depth_stream/       # stream.py, ticks.parquet
```

Each subfolder is self-contained — script, generated data, plots, logs.
The user can `rm -rf` any folder without affecting others.

## Constants — Order Surface

| Category | Values |
|----------|--------|
| **Exchange** | `NSE` `BSE` (equity); `NFO` `BFO` (F&O); `CDS` `BCD` (currency); `MCX` `NCDEX` `NCO` (commodity); `NSE_INDEX` `BSE_INDEX` `MCX_INDEX` `GLOBAL_INDEX` (quote-only) |
| **Action** | `BUY` `SELL` |
| **Product** | `CNC` (equity delivery only), `MIS` (intraday all segments), `NRML` (F&O / commodity overnight) |
| **Price type** | `MARKET`, `LIMIT`, `SL` (stop-loss limit), `SL-M` (stop-loss market) |
| **Validity** | `DAY` (default), `IOC` |
| **Option offset** | `ATM`, `ITM1`..`ITM20`, `OTM1`..`OTM20` (resolved against ATM strike by the SDK) |
| **WS mode** | `1` = LTP, `2` = Quote (OHLC+vol), `3` = Depth (with `depth_level` 5/20/30/50) |
| **WS verbose** | `0`/`False` silent, `1`/`True` connection logs, `2` all data updates |

Full grammar in [references/order-constants.md](references/order-constants.md) and [references/symbol-format.md](references/symbol-format.md). F&O lot sizes ship as a CSV at `assets/LotSize.csv` (see [references/lot-sizes.md](references/lot-sizes.md)).

## Symbol Format Quick-Reference

```
Equity:   RELIANCE                          (just the base symbol)
Futures:  NIFTY30JUN26FUT                   [base][DDMMMYY]FUT
Options:  NIFTY30JUN2626500CE               [base][DDMMMYY][strike][CE/PE]
```

Index quote-only symbols (no trading, use for `quotes`/`history`/`ws`):
`NIFTY` `BANKNIFTY` `FINNIFTY` `MIDCPNIFTY` `NIFTYNXT50` `SENSEX` `BANKEX` (and 80+ more — see [references/symbol-format.md](references/symbol-format.md))

## Complete SDK Method Map

| Group | Method | Doc |
|-------|--------|-----|
| **Order placement** | `placeorder` | [order-management](references/order-management.md) |
| | `placesmartorder` | "" — position-aware sizing |
| | `optionsorder` | "" — by `offset` (ATM/ITMn/OTMn) |
| | `optionsmultiorder` | "" — multi-leg (iron condor, straddle, diagonal) |
| | `basketorder` | "" — list of orders, results[] |
| | `splitorder` | "" — slice large qty into N chunks |
| **Order management** | `modifyorder` | "" |
| | `cancelorder` | "" |
| | `cancelallorder` | "" |
| | `closeposition` | "" — square off all |
| **GTT (REST-only)** | `placegttorder` / `modifygttorder` / `cancelgttorder` / `gttorderbook` | [order-management](references/order-management.md#gtt) |
| **Order info** | `orderstatus` | [order-information](references/order-information.md) |
| | `openposition` | "" — for a specific symbol |
| **Market data** | `quotes` | [market-data](references/market-data.md) |
| | `multiquotes` | "" — up to many symbols, used by scanners |
| | `depth` | "" — full Level-2 book |
| | `history` | "" — `source="api"` (broker) or `source="db"` (Historify DuckDB) |
| | `intervals` | "" |
| **Symbol services** | `symbol` | [symbol-services](references/symbol-services.md) |
| | `search` | "" — fuzzy lookup |
| | `expiry` | "" — F&O expiry dates |
| | `instruments` | "" — full master |
| **Options analytics** | `optionsymbol` | [options-services](references/options-services.md) |
| | `optionchain` | "" — full CE/PE chain with OI |
| | `syntheticfuture` | "" |
| | `optiongreeks` | "" — delta/gamma/theta/vega/rho + IV |
| **Account** | `funds` | [account-services](references/account-services.md) |
| | `margin` | "" — multi-leg margin calculator |
| | `orderbook` | "" |
| | `tradebook` | "" |
| | `positionbook` | "" |
| | `holdings` | "" |
| **Calendar** | `holidays(year)` | [market-calendar](references/market-calendar.md) |
| | `timings(date)` | "" |
| | `checkholiday(date)` | "" |
| **Analyzer** | `analyzerstatus` / `analyzertoggle(mode=True)` | [analyzer-services](references/analyzer-services.md) |
| **Alerts** | `telegram(username, message)` | [alerts](references/alerts.md) |
| | `whatsapp(text, to=..., image=..., document=...)` | "" |
| **WebSocket** | `connect()` / `disconnect()` | [websocket-streaming](references/websocket-streaming.md) |
| | `subscribe_ltp` / `subscribe_quote` / `subscribe_depth` (+ unsubscribe variants) | "" |
| | `get_quotes()` — pulls latest cached snapshot | "" |
| **Indicators** | `from openalgo import ta` → `ta.supertrend`, `ta.donchian`, `ta.ichimoku`, `ta.hma`, `ta.kama`, `ta.alma`, `ta.zlema`, `ta.vwma`, `ta.exrem`, `ta.crossover`, `ta.crossunder`, `ta.flip` | [indicators](references/indicators.md) |

The Python SDK doesn't expose every kwarg in its docstrings — when a parameter is missing or unclear, fall back to the per-endpoint REST docs at `/Users/openalgo/test-zerodha/openalgo/docs/api/<group>/<endpoint>.md`. That tree is parameter-complete.

## Quick Template — Place an Order with Preview + Analyzer Safety

```python
import os
from dotenv import find_dotenv, load_dotenv
from openalgo import api

load_dotenv(find_dotenv(), override=False)
client = api(
    api_key=os.environ["OPENALGO_API_KEY"],
    host=os.environ.get("OPENALGO_HOST", "http://127.0.0.1:5000"),
)

SYMBOL, EXCHANGE = "RELIANCE", "NSE"
ACTION, QTY, PRODUCT = "BUY", 1, "MIS"

# 1. Quote to anchor a marketable limit price (safer than MARKET)
q = client.quotes(symbol=SYMBOL, exchange=EXCHANGE)["data"]
limit_price = round(q["ltp"] * 1.001, 2) if ACTION == "BUY" else round(q["ltp"] * 0.999, 2)
notional = limit_price * QTY

print(f"--- Order Preview ---")
print(f"  {ACTION} {QTY} {SYMBOL} @ LIMIT {limit_price}   notional Rs {notional:,.2f}")
print(f"  Product: {PRODUCT}   LTP: {q['ltp']}")

if input("Proceed? [y/N] ").strip().lower() != "y":
    raise SystemExit("aborted")

response = client.placeorder(
    strategy=os.environ.get("OPENALGO_DEFAULT_STRATEGY", "python"),
    symbol=SYMBOL,
    exchange=EXCHANGE,
    action=ACTION,
    price_type="LIMIT",
    product=PRODUCT,
    quantity=str(QTY),
    price=str(limit_price),
)
print("ORDER:", response)
```

## Quick Template — Stream LTP with Reconnect

```python
import os, time
from dotenv import find_dotenv, load_dotenv
from openalgo import api

load_dotenv(find_dotenv(), override=False)
client = api(
    api_key=os.environ["OPENALGO_API_KEY"],
    host=os.environ.get("OPENALGO_HOST", "http://127.0.0.1:5000"),
    ws_url=os.environ.get("OPENALGO_WS_URL", "ws://127.0.0.1:8765"),
    verbose=True,
)

instruments = [
    {"exchange": "NSE_INDEX", "symbol": "NIFTY"},
    {"exchange": "NSE", "symbol": "RELIANCE"},
]

def on_ltp(msg):
    d = msg["data"]
    print(f"{d['symbol']:<12} LTP {d['ltp']}  @ {d['timestamp']}")

client.connect()
client.subscribe_ltp(instruments, on_data_received=on_ltp)

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    client.unsubscribe_ltp(instruments)
    client.disconnect()
```

## Quick Template — History from Direct DuckDB (Historify)

`client.history(..., source="db")` routes through REST. For bulk
multi-symbol pulls or backtesting, hit the DuckDB file directly:

```python
import os, duckdb, pandas as pd
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(), override=False)
DB = os.environ["HISTORIFY_DUCKDB_PATH"]   # e.g. /srv/openalgo/db/historify.duckdb

con = duckdb.connect(DB, read_only=True)

# Historify schema: table `market_data` with epoch timestamps
df = con.execute("""
    SELECT
        symbol,
        exchange,
        to_timestamp(timestamp) AT TIME ZONE 'Asia/Kolkata' AS ts,
        open, high, low, close, volume
    FROM market_data
    WHERE symbol = ?
      AND exchange = ?
      AND timestamp >= EXTRACT(EPOCH FROM TIMESTAMP '2024-01-01')
    ORDER BY timestamp
""", ["SBIN", "NSE"]).fetchdf()
con.close()

df["ts"] = pd.to_datetime(df["ts"]).dt.tz_localize(None)
df = df.set_index("ts")
print(df.tail())
```

Full Historify usage, multi-symbol joins, and resampling alignment with
NSE 09:15 IST in [references/duckdb-historify.md](references/duckdb-historify.md).

## Indicator Rule (matches vectorbt-backtesting-skills)

- **TA-Lib** for the standard set: `EMA`, `SMA`, `RSI`, `MACD`, `ATR`, `BBANDS`, `ADX`, `STDDEV`, `MOM`.
- **`openalgo.ta`** for: `supertrend`, `donchian`, `ichimoku`, `hma`, `kama`, `alma`, `zlema`, `vwma`.
- **`openalgo.ta`** for signal cleaning: `exrem`, `crossover`, `crossunder`, `flip` — always `.fillna(False)` before `exrem`.

Never use VectorBT's built-in indicators (`vbt.MA.run` etc.).

## Helper Scripts (`scripts/`)

| File | Purpose |
|------|---------|
| `openalgo_client.py` | `get_client()` — bootstraps from `.env` with `find_dotenv()` |
| `symbols.py` | `resolve_symbol`, `build_fut_symbol`, `build_opt_symbol`, `parse_opt_symbol` |
| `lotsize.py` | `load_lot_sizes()`, `nearest_lot(symbol, quantity)`, `validate_fno_lot()` |
| `orders.py` | `preview_order`, `place_with_confirmation`, `retry_on_rate_limit` |
| `execution.py` | `LimitChaser` (peg the touch), `TWAPSlicer`, `IcebergSlicer`, `OrderManager` |
| `option_analytics.py` | `atm_strike`, `pcr`, `max_pain`, `iv_skew`, `payoff_diagram` |
| `scanner.py` | `Scanner` — multi-symbol filter pipeline over `multiquotes` + `history` |
| `stream.py` | `subscribe()` context manager — auth, heartbeat, auto-reconnect |
| `plotting.py` | `candlestick_no_gaps`, `oi_histogram`, `heatmap`, `depth_ladder` |
| `duckdb_data.py` | `load_ohlcv(symbol, ...)` from Historify, multi-symbol bulk pull, resample |
| `fees.py` | Indian market cost model (equity / F&O / intraday / delivery) |
| `ta_helpers.py` | Ergonomic wrappers — TA-Lib + `openalgo.ta` combined |
| `trade_logger.py` | Persistent CSV/SQLite trade journal |

## Examples Catalog (`examples/`)

| Folder | Coverage |
|--------|----------|
| `01_execution/` | Equity, ATM straddle, iron condor, basket rebalance, smart-order sizing, supertrend live, GTT OCO |
| `02_scanners/` | Gainers/losers, breakout, RSI oversold, volume surge, OI change, pre-open gap |
| `03_visualization/` | Sector heatmap, YTD heatmap, CAGR heatmap, seasonality, OI histogram, PCR dashboard |
| `04_backtesting/` | EMA crossover, Supertrend, Opening Range Breakout, multi-symbol screener backtest |
| `05_charting/` | Candlestick with indicators, option chain OI chart, max pain, IV smile, depth ladder |
| `06_streaming/` | LTP, Quote, Depth (20-level), callback router, stream → Telegram alert, reconnect loop |
| `07_execution_algos/` | **Limit-order chaser, TWAP slicer, iceberg via splitorder, time-based cancel, price-based cancel-and-replace, conditional bracket** |

## Reference Files (`references/`)

| Need | File |
|------|------|
| Order placement / modification / cancellation + GTT | [order-management.md](references/order-management.md) |
| Order status & open positions | [order-information.md](references/order-information.md) |
| Quotes, depth, history, intervals | [market-data.md](references/market-data.md) |
| Symbol, search, expiry, instruments | [symbol-services.md](references/symbol-services.md) |
| Option chain, Greeks, synthetic future, ATM/ITM/OTM offsets | [options-services.md](references/options-services.md) |
| Funds, margin, books, holdings | [account-services.md](references/account-services.md) |
| Holidays, timings, holiday check | [market-calendar.md](references/market-calendar.md) |
| Sandbox / analyzer mode | [analyzer-services.md](references/analyzer-services.md) |
| WebSocket protocol, modes, depth_level, verbose | [websocket-streaming.md](references/websocket-streaming.md) |
| Telegram + WhatsApp alerts | [alerts.md](references/alerts.md) |
| `openalgo.ta` complete reference | [indicators.md](references/indicators.md) |
| Custom limit-order execution algos (chaser, TWAP, iceberg) | [execution-algos.md](references/execution-algos.md) |
| Direct DuckDB access to Historify market data | [duckdb-historify.md](references/duckdb-historify.md) |
| Equity / Futures / Options symbol grammar + index lists | [symbol-format.md](references/symbol-format.md) |
| F&O lot sizes (Apr/May/Jun 2026 + how to update) | [lot-sizes.md](references/lot-sizes.md) |
| Constants (exchange, product, price type, action) | [order-constants.md](references/order-constants.md) |
| Rate limits & retry guidance | [rate-limits.md](references/rate-limits.md) |
| Common multi-step recipes | [common-workflows.md](references/common-workflows.md) |
| Error patterns & troubleshooting | [error-codes.md](references/error-codes.md) |

## How to Pick Live vs Analyzer Mode

```python
status = client.analyzerstatus()["data"]
if status["analyze_mode"]:
    print(f"[ANALYZER] simulated mode — orders will not reach broker. logs: {status['total_logs']}")
else:
    print("[LIVE] orders will execute on the broker")
```

While developing a new strategy: `client.analyzertoggle(mode=True)`. When the user is satisfied: ask for explicit go-live confirmation, then `client.analyzertoggle(mode=False)`.

## Output Encoding Rules

- Never put emojis in generated code or log output. Plain ASCII only.
- Plotly charts use `template="plotly_dark"` and candlesticks use `xaxis_type="category"` to skip weekend gaps.
- Trade journals / scan results write to CSV with a date-stamped filename inside the action's workspace folder.
- All datetime indexes are tz-naive after dropping `Asia/Kolkata` (matches the vectorbt skill's convention so dataframes round-trip cleanly).
