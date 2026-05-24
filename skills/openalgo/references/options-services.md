# Options Services — Reference

Four endpoints, all built around OpenAlgo's offset-based options
addressing (`ATM`, `ITM1`..`ITM20`, `OTM1`..`OTM20`):

| Endpoint | Method | Returns | Used for |
|----------|--------|---------|----------|
| Single option lookup | `client.optionsymbol(...)` | `{status, symbol, exchange, lotsize, tick_size, freeze_qty, underlying_ltp}` | resolve ATM/ITM/OTM to a concrete symbol |
| Full option chain | `client.optionchain(...)` | `{status, underlying, underlying_ltp, expiry_date, atm_strike, chain[]}` | OI charts, IV smile, max-pain |
| Synthetic future | `client.syntheticfuture(...)` | `{status, atm_strike, synthetic_future_price, expiry, underlying, underlying_ltp}` | cash-future basis proxy when no future exists |
| Option Greeks | `client.optiongreeks(...)` | `{status, greeks{...}, implied_volatility, option_price, strike, ...}` | delta hedging, IV-based strike selection |

For expiry-date listing see [`client.expiry()`](symbol-services.md#expiry) in symbol-services.

---

## optionsymbol

Resolve an offset (`ATM`, `OTM5`, `ITM2`, ...) to a concrete tradable
contract for a given underlying and expiry. This is the cheapest way
to discover a single contract — `optionchain` is heavier and returns
many strikes at once.

### Request

```python
client.optionsymbol(
    underlying="NIFTY",
    exchange="NSE_INDEX",       # underlying exchange (index)
    expiry_date="30JUN26",      # DDMMMYY
    offset="ATM",               # ATM | ITM1..ITM20 | OTM1..OTM20
    option_type="CE",           # CE | PE
)
```

### Success Response

```json
{
  "status":         "success",
  "symbol":         "NIFTY30JUN2626500CE",
  "exchange":       "NFO",
  "lotsize":        75,
  "tick_size":      5,
  "freeze_qty":     1800,
  "underlying_ltp": 26512.45
}
```

### Read these fields

| Field | Helper | Used for |
|-------|--------|----------|
| `symbol` | `responses.find_offset_symbol(resp)` | feed straight into `placeorder` |
| `exchange` | direct read (always `NFO`/`BFO`) | placement requires this, NOT the underlying exchange |
| `lotsize` | direct read | quantity sizing — multiply lots by this |
| `tick_size` | direct read | round limit prices |
| `freeze_qty` | direct read | split via `client.splitorder` if quantity exceeds |
| `underlying_ltp` | direct read | distance-from-spot check |

### Chains with

- `optionsymbol` -> `placeorder(LIMIT or MARKET, symbol, exchange='NFO')` -> SL workflow
- See [common-workflows.md #2](common-workflows.md#2-atm-straddle-with-percentage-sl-on-premium)

### Why use this over `optionsorder`?

`optionsorder` does the resolution + placement in one call. Use it when
you trust the spot at call time. Use `optionsymbol` + `placeorder`
when you need to:
- show the resolved symbol to the user first
- compute notional / margin before placing
- separate lookup from execution (e.g. cache the symbol across many orders)

---

## optionchain

Full strike-by-strike chain for one expiry. Returns CE + PE legs side
by side, plus the underlying spot and the ATM strike already computed
by the server.

### Request

```python
client.optionchain(
    underlying="NIFTY",
    exchange="NSE_INDEX",
    expiry_date="30JUN26",
    strike_count=10,            # optional; omit for full chain
)
```

`strike_count` is the count of strikes returned on **each side** of ATM
(so `strike_count=10` returns up to 21 strikes including ATM). Omit for
the entire expiry — expensive for monthly NIFTY (200+ strikes).

### Success Response

```json
{
  "status":         "success",
  "underlying":     "NIFTY",
  "underlying_ltp": 26512.45,
  "expiry_date":    "30JUN26",
  "atm_strike":     26500.0,
  "chain": [
    {
      "strike": 26400.0,
      "ce": {
        "symbol":     "NIFTY30JUN2626400CE",
        "label":      "ITM2",
        "ltp":        490, "bid": 490, "ask": 491,
        "open": 540, "high": 571, "low": 444.75, "prev_close": 496.8,
        "volume": 1195800, "oi": 0,
        "lotsize": 75, "tick_size": 0.05
      },
      "pe": {
        "symbol":     "NIFTY30JUN2626400PE",
        "label":      "OTM2",
        "ltp": 193, "bid": 191.2, "ask": 193, ...
      }
    },
    { "strike": 26450.0, "ce": {...}, "pe": {...} },
    { "strike": 26500.0, "ce": {"label": "ATM", ...}, "pe": {"label": "ATM", ...} },
    ...
  ]
}
```

### Read these fields

| Field | Helper | Used for |
|-------|--------|----------|
| `atm_strike` | `responses.atm_strike_from_chain(resp)` | center of straddle / strangle |
| `underlying_ltp` | `responses.underlying_ltp(resp)` | distance-to-strike calculations |
| `chain[]` | `option_analytics.chain_to_df(resp)` -> long-format DataFrame | analytics |
| `chain[].ce.oi` / `pe.oi` | `option_analytics.pcr(df, basis='oi')` | put-call ratio |
| `chain[].ce.symbol` | `option_analytics.find_strike_row(resp, strike)['ce']['symbol']` | direct placement |
| `chain[].ce.label` (`ATM`, `ITM3`, `OTM2`) | direct read | UI labels |

### Chains with

- `optionchain` -> `chain_to_df` -> `payoff(legs)` -> chart
- `optionchain` -> `pcr` / `max_pain` -> alert
- `optionchain` -> select strike by `delta` via `iv_skew` -> place
- See [common-workflows.md #9](common-workflows.md#9-options-chain---pick-strike-by-delta---place)

### Common gotcha

The `oi` field returns 0 for some brokers' chain endpoints — Open
Interest comes through a different field on those plugins. Always
verify the value with a known-active strike (the ATM should have OI in
the 1L+ range on NIFTY).

---

## syntheticfuture

Calculates the synthetic forward price from the option chain (Call +
Strike - Put). Useful when there is no listed future for the expiry
you care about, or as a sanity check vs. the listed futures price.

### Request

```python
client.syntheticfuture(
    underlying="NIFTY",
    exchange="NSE_INDEX",
    expiry_date="30JUN26",
)
```

### Success Response

```json
{
  "status":                  "success",
  "underlying":              "NIFTY",
  "underlying_ltp":          26210.05,
  "atm_strike":              26200.0,
  "synthetic_future_price":  26280.05,
  "expiry":                  "30JUN26"
}
```

### Read these fields

| Field | Used for |
|-------|----------|
| `synthetic_future_price` | proxy for cash-future basis |
| `underlying_ltp` | spot for comparison |
| `atm_strike` | reference strike used in the calculation |

### Chains with

- Basis = `synthetic_future_price - underlying_ltp`; persistent positive basis = contango / dividend gap.
- For listed futures comparison: `client.quotes(symbol=f"{underlying}{expiry}FUT", exchange="NFO")` and diff.

---

## optiongreeks

Black-Scholes Greeks for a single option contract. The server computes
delta / gamma / theta / vega / rho + implied volatility from the
contract's LTP and the underlying's spot at the moment of the call.

### Request

```python
client.optiongreeks(
    symbol="NIFTY30JUN2626500CE",
    exchange="NFO",
    interest_rate=0.00,
    underlying_symbol="NIFTY",
    underlying_exchange="NSE_INDEX",
)
```

`interest_rate` is annual, fraction (e.g. `0.07` for 7%). Pass `0.0` to use the SDK default.

### Success Response

```json
{
  "status":              "success",
  "symbol":              "NIFTY30JUN2626500CE",
  "exchange":            "NFO",
  "expiry_date":         "30-Jun-2026",
  "days_to_expiry":      37.5071,
  "option_type":         "CE",
  "option_price":        435,
  "strike":              26500.0,
  "underlying":          "NIFTY",
  "spot_price":          26512.45,
  "implied_volatility":  15.6,
  "interest_rate":       0.0,
  "greeks": {
    "delta": 0.4967,
    "gamma": 0.000352,
    "theta": -7.919,
    "vega":  28.9489,
    "rho":   9.733994
  }
}
```

### Read these fields

| Field | Used for |
|-------|----------|
| `greeks.delta` | strike selection by target delta (25-delta strangle, 50-delta = ATM) |
| `greeks.gamma` | risk-of-risk; spikes near ATM close to expiry |
| `greeks.theta` | daily decay; the income side of premium-selling |
| `greeks.vega` | IV sensitivity; size positions to a vol target |
| `implied_volatility` | IV smile / skew comparison across strikes |
| `days_to_expiry` | time-decay scaling for theta-based strategies |

### Chains with

- For each strike in `optionchain` -> `optiongreeks` -> build IV smile (see `option_analytics.iv_skew`)
- Filter `optionchain` rows by delta band -> pick strike -> place
- See [common-workflows.md #9](common-workflows.md#9-options-chain---pick-strike-by-delta---place)

### Rate-limit note

`optiongreeks` is in the general 50/sec bucket but the server-side
computation is heavier than `quotes`. When iterating across a full
chain, throttle to ~10/sec to be a good citizen. The `iv_skew` helper
already does this internally.
