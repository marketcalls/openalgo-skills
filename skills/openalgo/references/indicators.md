# Indicators (`openalgo.ta`) — Reference

`openalgo.ta` is the indicator + signal-helper library bundled with the
OpenAlgo SDK. Install with the `[indicators]` extra:

```bash
pip install -U "openalgo[indicators]"
```

It complements rather than replaces TA-Lib. The skill's rule is:

| Category | Use |
|----------|-----|
| Standard indicators (EMA, SMA, RSI, MACD, ATR, BBANDS, ADX, STDDEV, MOM) | **TA-Lib** |
| Specialty indicators (Supertrend, Donchian, Ichimoku, HMA, KAMA, ALMA, ZLEMA, VWMA) | **openalgo.ta** |
| Signal cleaning (exrem, crossover, crossunder, flip) | **openalgo.ta** |

Why not VectorBT's built-in indicators? They allocate aggressively and
do not match TA-Lib numerically. Stick to TA-Lib + openalgo.ta for
backtest -> live consistency.

Use [`scripts/ta_helpers.py`](../scripts/ta_helpers.py) for ergonomic
wrappers — it hides the `pd.Series(tl.EMA(close.values, ...))` boilerplate.

---

## Signal Helpers

The four signal helpers are the most important functions in the
library — they turn raw True/False arrays from indicators into clean
entry / exit signals that vectorbt and live strategies can use without
re-firing on every bar of the same regime.

### `exrem` — Excess Signal Removal

Keeps only the first signal of one type before the *other* type fires.
Use this on every entry/exit pair before passing into `from_signals`.

```python
from openalgo import ta

# raw signals: BUY BUY BUY SELL SELL BUY
# after exrem: BUY ___ ___ SELL ___  BUY

entries = ta.exrem(buy_raw.fillna(False), sell_raw.fillna(False))
exits   = ta.exrem(sell_raw.fillna(False), buy_raw.fillna(False))
```

Always `.fillna(False)` before `exrem` — NaN propagates and breaks the
exclusion logic.

### `crossover` / `crossunder`

```python
cross_up   = ta.crossover(close, upper_band)    # close went from <= upper to > upper
cross_down = ta.crossunder(close, lower_band)   # close went from >= lower to < lower
```

Returns a boolean Series; True on the bar where the cross occurred.

### `flip` — Regime Detection

```python
# True from when trigger_on fires until trigger_off fires
in_bull = ta.flip(close > sma200, close < sma200)
```

Use for "we're in regime X" gates rather than for entries.

---

## Specialty Indicators

### `supertrend`

```python
from scripts.ta_helpers import supertrend

st_line, st_dir = supertrend(df["high"], df["low"], df["close"],
                              period=10, multiplier=3.0)
# st_dir = +1 when trend is up, -1 when down
buy_raw  = (st_dir > 0) & (st_dir.shift(1) <= 0)   # turn up
sell_raw = (st_dir < 0) & (st_dir.shift(1) >= 0)   # turn down
```

### `donchian`

```python
from scripts.ta_helpers import donchian

upper, lower, mid = donchian(df["high"], df["low"], period=20)
breakout = ta.crossover(df["close"], upper)         # 20-day breakout
```

### `ichimoku`

```python
from scripts.ta_helpers import ichimoku

ich = ichimoku(df["high"], df["low"], df["close"],
               tenkan=9, kijun=26, senkou_b=52)
# ich.tenkan, ich.kijun, ich.senkou_a, ich.senkou_b, ich.chikou
in_cloud_up = (df["close"] > ich["senkou_a"]) & (df["close"] > ich["senkou_b"])
```

### `hma`, `kama`, `alma`, `zlema`, `vwma`

```python
from scripts.ta_helpers import hma, kama, alma, zlema, vwma

trend_hma   = hma(df["close"], period=21)
adaptive_ma = kama(df["close"], period=10)
arnaud_ma   = alma(df["close"], period=9, offset=0.85, sigma=6.0)
zero_lag    = zlema(df["close"], period=14)
volume_ma   = vwma(df["close"], df["volume"], period=20)
```

---

## TA-Lib (standard set)

The ergonomic wrappers in `scripts/ta_helpers.py`:

```python
from scripts.ta_helpers import ema, sma, rsi, atr, macd, bbands, adx, stddev, mom

ema20  = ema(df["close"], 20)
rsi14  = rsi(df["close"], 14)
atr14  = atr(df["high"], df["low"], df["close"], 14)
macd_df= macd(df["close"], 12, 26, 9)        # columns: macd, signal, hist
bb     = bbands(df["close"], 20, 2.0)        # columns: upper, mid, lower
```

Raw TA-Lib usage if you need parameters the wrapper does not expose:

```python
import talib as tl
import pandas as pd

vals = tl.EMA(close.values, timeperiod=20)
ema  = pd.Series(vals, index=close.index)
```

Always wrap back into a `pd.Series` with the original index — TA-Lib
returns a NumPy array.

---

## Combining for live signals

```python
from scripts.ta_helpers import ema, rsi, supertrend, clean_signals

df = client.history(symbol="SBIN", exchange="NSE", interval="5m",
                    start_date="2026-05-01", end_date="2026-05-24")
df.index = pd.to_datetime(df.index).tz_localize(None)

# Indicators
e20 = ema(df["close"], 20)
e50 = ema(df["close"], 50)
r14 = rsi(df["close"], 14)
st_line, st_dir = supertrend(df["high"], df["low"], df["close"], 10, 3.0)

# Raw signals: EMA crossover + RSI confirm + Supertrend filter
buy_raw  = (e20 > e50) & (e20.shift(1) <= e50.shift(1)) & (r14 > 50) & (st_dir > 0)
sell_raw = (e20 < e50) & (e20.shift(1) >= e50.shift(1)) & (r14 < 50)

# Clean for vbt-compatible entries/exits
entries, exits = clean_signals(buy_raw, sell_raw)

# Live: look at the latest CLOSED bar (not the partial current one)
if entries.iloc[-2]:
    print("BUY signal on", entries.index[-2])
elif exits.iloc[-2]:
    print("SELL signal on", exits.index[-2])
```

---

## Indicator -> Order chain

```python
from scripts.responses import extract_orderid
from scripts.workflows  import place_with_sl_target

if entries.iloc[-2]:
    # ATR-based SL — stop 1.5x ATR below entry
    atr14 = atr(df["high"], df["low"], df["close"], 14).iloc[-2]
    last_close = df["close"].iloc[-2]
    sl_abs_rs = 1.5 * atr14

    result = place_with_sl_target(
        client,
        strategy="ema_supertrend_5m",
        symbol="SBIN", exchange="NSE",
        action="BUY", quantity=10, product="MIS",
        price_type="MARKET",
        sl_abs=sl_abs_rs,
        target_abs=sl_abs_rs * 2,    # 1:2 R/R
        alert_via=("telegram", "whatsapp"),
    )
    print(f"entry {result.entry_avg_price}  SL {result.sl_trigger}  TGT {result.target_price}")
```

This is the canonical **indicator -> response-aware entry -> auto SL/target** pattern. The indicator decides; `workflows.place_with_sl_target` handles all the response chasing.

---

## Common gotchas

- **Always pass `pd.Series` to `openalgo.ta`** functions, not raw arrays. TA-Lib accepts arrays; `openalgo.ta` requires the Series for index preservation.
- **`.fillna(False)` before `exrem`.** Bears repeating — the most common bug is forgetting this and getting empty signals.
- **`crossover` returns a one-bar pulse**, not a regime. For "are we in cross-up state right now?", use `flip` instead.
- **Don't compute on the live partial bar.** Always evaluate signals on `iloc[-2]` (last fully-closed bar) inside an intraday loop. The `-1` bar is forming and its OHLC will change.
- **Backtest -> live numerical parity** requires identical indicator implementations. Stick to TA-Lib + `openalgo.ta` — do not mix in `pandas-ta` or `vbt.RSI.run` for the same backtest+live pair.
