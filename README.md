# OpenAlgo Agent Skills

**OpenAlgo agent skill for NSE / BSE / NFO / BFO / CDS / BCD / MCX / NCO trading.**

Give your AI agent the ability to place live orders, build custom
limit-order execution algos, scan markets, render visualizations,
backtest with vectorbt, render candlestick / option-chain charts, and
stream live LTP / Quote / Depth — all through OpenAlgo's broker-agnostic
[Python SDK](https://docs.openalgo.in/trading-platform/python.md) and
[REST API](https://docs.openalgo.in/api-documentation/v1).

Built for the [Agent Skills](https://agentskills.io) standard. Compatible
with Claude Code, Codex, and any agent that loads `SKILL.md`.

---

## Quick install

```bash
git clone https://github.com/marketcalls/openalgo-skills.git
cd openalgo-skills
cp .env.sample .env                    # fill in OPENALGO_API_KEY + host/ws URLs
pip install -r requirements.txt
```

When using inside Claude Code or any SKILL.md-aware agent, the skill at
`skills/openalgo/SKILL.md` auto-loads. Trigger phrases include
"OpenAlgo", "place an order", "scan NIFTY 50", "stream NIFTY depth",
"backtest a strategy on Historify data", "build a limit-order chaser".

---

## What's included

```
skills/openalgo/
├── SKILL.md                          # entry: setup, safety rules, API surface
│
├── references/                       # parameter-complete deep-dives per service
│   ├── order-management.md           # place/modify/cancel + GTT
│   ├── order-information.md
│   ├── market-data.md                # quotes, multiquotes, depth, history (REST + DB)
│   ├── symbol-services.md
│   ├── options-services.md           # chain, Greeks, synthetic future, offsets
│   ├── account-services.md
│   ├── market-calendar.md
│   ├── analyzer-services.md          # sandbox mode
│   ├── websocket-streaming.md        # 3 modes, depth_level, verbose, reconnect
│   ├── alerts.md                     # Telegram + WhatsApp
│   ├── indicators.md                 # openalgo.ta full reference
│   ├── execution-algos.md            # limit chaser, TWAP, iceberg, conditional
│   ├── duckdb-historify.md           # direct Historify access for backtesting
│   ├── symbol-format.md              # equity / futures / options grammar + index lists
│   ├── lot-sizes.md
│   ├── order-constants.md
│   ├── rate-limits.md
│   ├── common-workflows.md
│   └── error-codes.md
│
├── scripts/                          # composable helper layer
│   ├── openalgo_client.py            # get_client() — bootstraps from .env
│   ├── symbols.py                    # resolve / build / parse equity, fut, opt
│   ├── lotsize.py                    # F&O lot validation
│   ├── orders.py                     # preview, confirm, retry-on-rate-limit
│   ├── execution.py                  # LimitChaser, TWAPSlicer, IcebergSlicer
│   ├── option_analytics.py           # ATM, PCR, max pain, IV skew, payoff
│   ├── scanner.py                    # multi-symbol filter pipeline
│   ├── stream.py                     # subscribe() context manager, reconnect_loop
│   ├── plotting.py                   # candlestick (no weekend gaps), OI charts
│   ├── duckdb_data.py                # direct Historify DuckDB loaders
│   ├── fees.py                       # Indian-market cost model
│   ├── ta_helpers.py                 # TA-Lib + openalgo.ta wrappers
│   └── trade_logger.py               # CSV/SQLite trade journal
│
├── examples/
│   ├── 01_execution/                 # equity, ATM straddle, iron condor, basket, smart order, supertrend live, GTT OCO
│   ├── 02_scanners/                  # gainers/losers, breakout, RSI oversold, volume surge, OI change, pre-open gap
│   ├── 03_visualization/             # sector heatmap, YTD/CAGR heatmaps, seasonality, PCR dashboard, OI histogram
│   ├── 04_backtesting/               # EMA crossover, Supertrend, opening range breakout, multi-symbol screener backtest
│   ├── 05_charting/                  # candlestick + indicators, option chain OI, max pain, IV smile, depth ladder
│   ├── 06_streaming/                 # LTP, quote, 20-level depth, callback router, stream → alert, reconnect loop
│   └── 07_execution_algos/           # limit chaser, TWAP, iceberg, time-based cancel, price-based cancel-and-replace, conditional bracket
│
└── assets/
    ├── LotSize.csv                   # F&O lot sizes snapshot (Apr/May/Jun 2026)
    └── nifty50_constituents.csv      # for scanner / heatmap examples
```

---

## File-output convention

When the skill generates code for a user action, it writes the script
into a per-action subfolder under `openalgo_workspace/`. Each subfolder
is self-contained — script, generated CSVs, plots, logs — so the user
can move, share, or `rm -rf` any single experiment without disturbing
the rest.

```
openalgo_workspace/
├── execution/atm_straddle/         # straddle.py, journal.csv
├── execution_algos/chase_reliance/ # chaser.py, fills.csv
├── scanners/breakout/              # scan.py, results_2026-05-24.csv
├── backtesting/supertrend_sbin/    # backtest.py, equity.html, trades.csv
├── charting/nifty_oi_30jun26/      # chart.py, oi.html
└── streaming/nifty_depth/          # stream.py, ticks.parquet
```

---

## Companion skills

These three packages compose cleanly — same `.env`, same coding style,
same Indian-market cost model:

| Skill | Use for |
|-------|---------|
| **openalgo-skills** (this) | Execution, scanners, streaming, charts, options analytics |
| [vectorbt-backtesting-skills](https://github.com/marketcalls/vectorbt-backtesting-skills) | Backtesting with realistic Indian fees, parameter optimization, walk-forward, QuantStats tearsheets |
| [dhanhq-skills](https://github.com/dhan-oss/dhanhq-skills) | Direct Dhan broker integration (when you specifically need Dhan-native features like super orders / forever orders) |

---

## Requirements

- Python 3.10+
- `pip install openalgo[indicators]`
- A running OpenAlgo instance (default `http://127.0.0.1:5000`)
- Order placement requires static IP whitelisting at your broker (SEBI mandate from 1 April 2026)
- Real-time data depends on your broker's data plan
- For backtesting only: no broker session required — Historify DuckDB is sufficient

---

## License

MIT
