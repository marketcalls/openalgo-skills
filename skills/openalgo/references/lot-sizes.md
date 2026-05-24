# F&O Lot Sizes — Reference

NIFTY F&O is lot-traded. Quantity in any F&O order must be a positive
multiple of the underlying's lot size. The lot is **per-symbol** and
changes periodically based on SEBI / exchange revisions.

| Source | When to use |
|--------|-------------|
| `assets/LotSize.csv` (bundled snapshot) | offline lookups, sizing calculators, scanners |
| `client.symbol(symbol, exchange='NFO').data.lotsize` | placement-time authoritative value |

Always validate at placement time — a stale snapshot is the most common
source of "quantity is not a multiple of lot" rejections.

---

## Bundled snapshot

`assets/LotSize.csv` contains the lot size for the next three F&O
expiry months. Currently (Apr / May / Jun 2026):

```csv
Symbol,Lot Size (Apr 2026),Lot Size (May 2026),Lot Size (Jun 2026)
NIFTY,65,65,65
BANKNIFTY,30,30,30
FINNIFTY,60,60,60
MIDCPNIFTY,120,120,120
NIFTYNXT50,25,25,25
RELIANCE,500,500,500
TCS,175,175,175
INFY,400,400,400
HDFCBANK,550,550,550
ICICIBANK,700,700,700
SBIN,750,750,750
...
```

The CSV format uses `-` for symbols that were in F&O at the time of
the prior month's snapshot but have since been delisted (e.g. recent
illiquid names). Always filter those out.

### Refreshing the snapshot

The CSV is updated quarterly from
`/Users/openalgo/test-zerodha/openalgo/docs/prompt/LotSize.md`. To
refresh after a SEBI revision:

```bash
cp openalgo/docs/prompt/LotSize.md \
   openalgo-skills/skills/openalgo/assets/LotSize.csv
```

---

## Helper API

```python
from scripts.lotsize import (
    load_lot_sizes, get_lot, nearest_lot, validate_fno_lot,
    lot_for_via_symbol_api,
)

# 1. Single lookup (uses bundled snapshot)
get_lot("NIFTY")                  # 65 (Apr 2026 column by default)
get_lot("NIFTY", month_col="May") # 65
get_lot("RELIANCE")               # 500

# 2. Validate before placing
validate_fno_lot("NIFTY", 130)       # OK (130 = 2 lots)
validate_fno_lot("NIFTY", 100)       # raises ValueError: "...nearest valid: 65 or 130"

# 3. Round down to whole lots
nearest_lot("NIFTY", 100)         # 65   (100 // 65 = 1 -> 65)
nearest_lot("NIFTY", 200)         # 195  (200 // 65 = 3 -> 195)

# 4. Live authoritative value (broker round-trip)
lot_for_via_symbol_api(client, "NIFTY30JUN26FUT", "NFO")   # 75

# 5. Full DataFrame
df = load_lot_sizes(month_col="Jun")
print(df.head())
#       Symbol  lot
# 0  BANKNIFTY   30
# 1   FINNIFTY   60
# 2 MIDCPNIFTY  120
# 3      NIFTY   65
# 4 NIFTYNXT50   25
```

---

## Sizing patterns

### Equity-style notional sizing -> nearest lot

```python
from scripts.lotsize import get_lot

notional = 100_000             # Rs target exposure
strike = 26500
premium_est = 200              # rupees per share

lots = max(1, notional // (premium_est * get_lot("NIFTY")))
qty = lots * get_lot("NIFTY")    # 65 for current NIFTY
print(f"placing {lots} lots = {qty} qty")
```

### Risk-based sizing (1% account risk)

```python
account = 1_000_000
risk_pct = 0.01
entry = 220
sl = 180
risk_per_share = entry - sl    # 40

raw_qty = (account * risk_pct) // risk_per_share    # 250
lot = get_lot("RELIANCE")                            # 500 — too small
qty = ((raw_qty // lot) + 1) * lot                   # round up: 500 = 1 lot

if qty * entry > account * 0.5:
    print("REJECT: notional > 50% of account")
```

### Margin-aware sizing for short premium

```python
from scripts.responses import total_margin_required, available_cash

for lots in (1, 2, 3, 4, 5):
    qty = lots * get_lot("NIFTY")
    margin = total_margin_required(client.margin(positions=[
        {"symbol": "NIFTY30JUN2626500CE", "exchange": "NFO",
         "action": "SELL", "product": "NRML", "pricetype": "MARKET",
         "quantity": str(qty)},
    ]))
    if margin > available_cash(client.funds()) * 0.8:
        print(f"max {lots - 1} lots fits in margin")
        break
```

---

## Common gotchas

- **CSV is a snapshot, not gospel.** Always run `validate_fno_lot`
  before placement and treat a lookup miss as "use the live API
  value" rather than failing.
- **Equity = lotsize 1.** Don't blindly call `get_lot` on NSE equity;
  the function raises for non-F&O symbols. Gate on `exchange == 'NFO'`
  (or `BFO`).
- **Index lot != stock lot.** NIFTY lot can differ from BANKNIFTY lot
  by 2x. Never share a lot size constant across underlyings.
- **Freeze quantity vs. lot size.** A single order cannot exceed the
  exchange freeze quantity (e.g. 1800 for NIFTY = 24 lots of 75 each
  in the older 75-lot regime). Use `splitorder` or
  `scripts.execution.IcebergSlicer` for parents above this.
- **Lot revisions take effect on expiry-cycle boundaries.** The Apr
  column applies to all April-expiring contracts, May to May, etc.
  Pick the column matching the expiry you trade.
