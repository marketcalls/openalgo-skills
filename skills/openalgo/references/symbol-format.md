# Symbol Format — Reference

OpenAlgo standardizes financial-instrument identifiers across all 30+
supported brokers. One symbol grammar works everywhere; the broker
plugin handles per-broker translation behind the scenes.

## Grammar

```
Equity:   <BASE>
Futures:  <BASE><DD><MMM><YY>FUT
Options:  <BASE><DD><MMM><YY><STRIKE><CE|PE>
```

- `<BASE>` is the underlying ticker (`INFY`, `RELIANCE`, `NIFTY`, `BANKNIFTY`, ...).
- `<DD>` is two-digit day.
- `<MMM>` is uppercase three-letter month (`JAN`, `FEB`, ..., `DEC`).
- `<YY>` is two-digit year.
- `<STRIKE>` is an integer or decimal — `25000`, `292.5`. No leading zero.
- `<CE|PE>` is Call or Put.

Use [`scripts.symbols`](../scripts/symbols.py) to construct and parse —
never f-string by hand for non-trivial cases.

## Examples

### Equity

| Description | Symbol | Exchange |
|-------------|--------|----------|
| Infosys     | `INFY`     | `NSE` |
| Tata Motors | `TATAMOTORS` | `NSE` or `BSE` |
| SBI         | `SBIN`     | `NSE` |

### Futures

| Description | Symbol | Exchange |
|-------------|--------|----------|
| NIFTY June 2026 | `NIFTY30JUN26FUT` | `NFO` |
| BANKNIFTY June 2026 | `BANKNIFTY30JUN26FUT` | `NFO` |
| SENSEX June 2026 | `SENSEX30JUN26FUT` | `BFO` |
| USDINR June 2026 | `USDINR30JUN26FUT` | `CDS` |
| Crude Mini June 2026 | `CRUDEOILM20JUN26FUT` | `MCX` |
| Government Bond 7.26% 2033 | `726GS203330JUN26FUT` | `NFO` |

### Options

| Description | Symbol | Exchange |
|-------------|--------|----------|
| NIFTY 26500 CE 30-Jun-26 | `NIFTY30JUN2626500CE` | `NFO` |
| BANKNIFTY 58000 PE 30-Jun-26 | `BANKNIFTY30JUN2658000PE` | `NFO` |
| VEDL 292.5 CE 30-Jun-26 | `VEDL30JUN26292.5CE` | `NFO` |
| USDINR 82 CE 30-Jun-26 | `USDINR30JUN2682CE` | `CDS` |
| Crude 6750 CE 30-Jun-26 | `CRUDEOIL30JUN266750CE` | `MCX` |

---

## NSE Index Symbols (`exchange = NSE_INDEX`)

Quote-only — these cannot be ordered directly; trade the corresponding
futures or options chain instead.

| Headline | Sectoral | Strategy / Factor |
|----------|----------|-------------------|
| `NIFTY` | `NIFTYAUTO` | `NIFTY100EQLWGT` |
| `BANKNIFTY` | `NIFTYBANK` | `NIFTY100LIQ15` |
| `FINNIFTY` | `NIFTYCOMMODITIES` | `NIFTY100LOWVOL30` |
| `MIDCPNIFTY` | `NIFTYCONSUMPTION` | `NIFTY100QUALTY30` |
| `NIFTYNXT50` | `NIFTYCPSE` | `NIFTY200QUALTY30` |
| `INDIAVIX` | `NIFTYDIVOPPS50` | `NIFTYGROWSECT15` |
| `NIFTY100` | `NIFTYENERGY` | `NIFTY50DIVPOINT` |
| `NIFTY200` | `NIFTYFMCG` | `NIFTY50EQLWGT` |
| `NIFTY500` | `NIFTYINFRA` | `NIFTYMIDLIQ15` |
| `NIFTYALPHA50` | `NIFTYIT` | `NIFTY50PR1XINV` |
| `NIFTYMIDCAP50` | `NIFTYMEDIA` | `NIFTY50PR2XLEV` |
| `NIFTYMIDCAP100` | `NIFTYMETAL` | `NIFTY50TR1XINV` |
| `NIFTYMIDCAP150` | `NIFTYMNC` | `NIFTY50TR2XLEV` |
| `NIFTYSMLCAP50` | `NIFTYPHARMA` | `NIFTY50VALUE20` |
| `NIFTYSMLCAP100` | `NIFTYPSE` | `NIFTYGS10YR` |
| `NIFTYSMLCAP250` | `NIFTYPSUBANK` | `NIFTYGS10YRCLN` |
| `NIFTYMIDSML400` | `NIFTYPVTBANK` | `NIFTYGS1115YR` |
| `HANGSENGBEESNAV` | `NIFTYREALTY` | `NIFTYGS15YRPLUS` |
| | `NIFTYSERVSECTOR` | `NIFTYGS48YR` |
| | | `NIFTYGS813YR` |
| | | `NIFTYGSCOMPSITE` |

For the full canonical list see `/Users/openalgo/test-zerodha/openalgo/docs/prompt/symbol-format.md`.

## BSE Index Symbols (`exchange = BSE_INDEX`)

```
SENSEX, BANKEX, SENSEX50, BSE100, BSE150MIDCAPINDEX, BSE200,
BSE250LARGEMIDCAPINDEX, BSE400MIDSMALLCAPINDEX, BSE500,
BSEAUTO, BSECAPITALGOODS, BSECARBONEX, BSECONSUMERDURABLES, BSECPSE,
BSEDOLLEX100, BSEDOLLEX200, BSEDOLLEX30, BSEENERGY,
BSEFASTMOVINGCONSUMERGOODS, BSEFINANCIALSERVICES, BSEGREENEX,
BSEHEALTHCARE, BSEINDIAINFRASTRUCTUREINDEX, BSEINDUSTRIALS,
BSEINFORMATIONTECHNOLOGY, BSEIPO, BSELARGECAP, BSEMETAL, BSEMIDCAP,
BSEMIDCAPSELECTINDEX, BSEOIL&GAS, BSEPOWER, BSEPSU, BSEREALTY,
BSESENSEXNEXT50, BSESMALLCAP, BSESMALLCAPSELECTINDEX, BSESMEIPO,
BSETECK, BSETELECOM
```

## NCO Commodity Underlyings (`exchange = NCO`)

NSE Commodities (futures + options). Currently supported by Zerodha only.

```
ALUMINIUMFUTURES, ALUMINIUMMINIFUTURES, BRENTCRUDEOIL, BRENTCRUDEOILMINI,
COPPER, CRUDEDEGUMSOYBEANOIL, ELECTRICITYFUTURES, GOLD, GOLD10GM,
GOLD1GM, GOLDGUINEA8GM, GOLDMINI, LEADFUTURES, LEADMINIFUTURES,
NATURALGASHENRYHUB, NATURALGASMINI, NICKELFUTURES,
PLATTSDATEDBRENTASSESS, SILVER, SILVERMICRO, SILVERMINI,
WTICRUDEOIL, WTICRUDEOILMINI, XAUGOLD, ZINCFUTURES, ZINCMINIFUTURES
```

- NCO Futures example: `ALUMINI20JUN26FUT`
- NCO Options example: `COPPER20JUN261195CE`

## MCX Index Symbols (`exchange = MCX_INDEX`)

Quote-only commodity sectoral indices (Zerodha-sourced):

```
MCXAGRI, MCXBULLDEX, MCXCOMDEX, MCXCOMPDEX, MCXCOPRDEX, MCXCRUDEX,
MCXENERGY, MCXGOLDEX, MCXMETAL, MCXMETLDEX, MCXSILVDEX
```

Tradable futures live on the regular `MCX` exchange — e.g. `MCXBULLDEX27MAY26FUT`.

## Global Index Symbols (`exchange = GLOBAL_INDEX`)

Quote-only feed for global indices. No trading (Zerodha-sourced).

```
AUS200, FRANCE40, GERMANY40, GIFTNIFTY, HANGSENG, JAPAN225,
SHANGHAICHINA, UK100, US100, US10YRYIELD, US30, US500, USCOMPOSITE
```

`GIFTNIFTY` is technically on NSE IFSC (broker code `NSEIX`) but is
exposed under `GLOBAL_INDEX` so all quote-only feeds share one bucket.

---

## Exchange Codes Summary

| Code | Description | Trading? |
|------|-------------|----------|
| `NSE` | NSE Equity | yes |
| `BSE` | BSE Equity | yes |
| `NFO` | NSE F&O | yes |
| `BFO` | BSE F&O | yes |
| `CDS` | NSE Currency Derivatives | yes |
| `BCD` | BSE Currency Derivatives | yes |
| `MCX` | Multi Commodity Exchange | yes |
| `NCDEX` | NCDEX Commodity | yes |
| `NCO` | NSE Commodities (Zerodha only) | yes |
| `NSE_INDEX` | NSE Index | no (quote-only) |
| `BSE_INDEX` | BSE Index | no (quote-only) |
| `MCX_INDEX` | MCX Sectoral Index (Zerodha) | no (quote-only) |
| `GLOBAL_INDEX` | Global Indices (Zerodha) | no (quote-only) |

---

## Helper functions

```python
from scripts.symbols import (
    build_fut_symbol, build_opt_symbol,
    parse_fut_symbol, parse_opt_symbol,
    fmt_expiry, resolve_symbol, search_symbols,
)

# Build
build_fut_symbol("NIFTY", "2026-06-30")               # "NIFTY30JUN26FUT"
build_opt_symbol("NIFTY", "2026-06-30", 26500, "CE")  # "NIFTY30JUN2626500CE"
build_opt_symbol("VEDL", "2026-06-30", 292.5, "PE")   # "VEDL30JUN26292.5PE"
fmt_expiry("2026-06-30")                              # "30JUN26"

# Parse
parse_opt_symbol("NIFTY30JUN2626500CE")
# {"base": "NIFTY", "expiry": date(2026, 6, 30), "strike": 26500,
#  "option_type": "CE", "symbol": "NIFTY30JUN2626500CE"}

parse_fut_symbol("BANKNIFTY30JUN26FUT")
# {"base": "BANKNIFTY", "expiry": date(2026, 6, 30),
#  "symbol": "BANKNIFTY30JUN26FUT"}

# Authoritative lookup (broker round-trip)
data = resolve_symbol(client, "NIFTY30JUN26FUT", "NFO")
# {"lotsize": 75, "tick_size": 10, ...}
```

The `COMMON_INDICES` dict in `scripts/symbols.py` gives you autocomplete-friendly
lists of the most-used index symbols per exchange — handy for building
quick scanners or dropdowns without scrolling through this reference.

---

## Database schema (for SDK contributors)

OpenAlgo's `SymToken` table maps both directions:

| Column | Meaning |
|--------|---------|
| `id` | unique row id |
| `symbol` | OpenAlgo standard symbol |
| `brsymbol` | broker-specific symbol (e.g. `NSE:RELIANCE-EQ`) |
| `name` | full descriptive name |
| `exchange` | OpenAlgo exchange code |
| `brexchange` | broker-specific exchange (e.g. `NSE_FO`) |
| `token` | broker-side instrument token |
| `expiry` | derivative expiry (varies in format) |
| `strike` | option strike (-1 for non-options) |
| `lotsize` | standard lot size |
| `instrumenttype` | `EQ` / `FUT` / `CE` / `PE` / `INDEX` |
| `tick_size` | minimum price increment |

You rarely query this directly — use `client.symbol()`, `client.search()`,
or `client.instruments(exchange)` instead.
