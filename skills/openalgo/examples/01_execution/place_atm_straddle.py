"""Place a short ATM straddle on NIFTY with auto-SL on each leg.

Strategy: sell ATM CE + sell ATM PE for the same expiry. Profit if
NIFTY stays near the strike at expiry; loss if it moves either way
past the breakevens. The SL on each leg adapts to the *actual* fill
premium — not the intended quantity — using the response-aware
workflow `enter_options_atm_with_sl`.

Output folder: openalgo_workspace/execution/atm_straddle_nifty/
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.openalgo_client import default_strategy_tag, get_client
from scripts.responses import ResponseError
from scripts.trade_logger import open_journal
from scripts.workflows import enter_options_atm_with_sl

# ---- config --------------------------------------------------------------

UNDERLYING = "NIFTY"
UNDERLYING_EXCHANGE = "NSE_INDEX"
EXPIRY = "30JUN26"
QUANTITY = 75                  # 1 NIFTY lot at current SEBI lot size
PRODUCT = "NRML"

SL_PCT = 30.0                  # SL placed 30% above each filled premium
ALERTS = ("telegram", "whatsapp")

# ---- bootstrap -----------------------------------------------------------

client = get_client()
strategy = f"{default_strategy_tag()}_atm_straddle"

workdir = Path("openalgo_workspace/execution/atm_straddle_nifty")
workdir.mkdir(parents=True, exist_ok=True)
journal = open_journal(workdir / "journal.csv")

# ---- pre-flight: confirm analyzer or live mode --------------------------

mode_info = client.analyzerstatus().get("data", {})
banner = "[ANALYZER]" if mode_info.get("analyze_mode") else "[LIVE]"
print(f"{banner}  short ATM straddle on {UNDERLYING} {EXPIRY}  qty {QUANTITY} per leg")
if not mode_info.get("analyze_mode"):
    if input("Confirm LIVE placement? [y/N] ").strip().lower() != "y":
        raise SystemExit("aborted")

# ---- Leg 1: SELL ATM CE --------------------------------------------------

print("\n--- CE LEG ---")
try:
    ce_state = enter_options_atm_with_sl(
        client,
        underlying=UNDERLYING,
        underlying_exchange=UNDERLYING_EXCHANGE,
        expiry_date=EXPIRY,
        option_type="CE",
        offset="ATM",
        quantity=QUANTITY,
        product=PRODUCT,
        strategy=strategy + "_ce",
        sl_pct=SL_PCT,
        alert_via=ALERTS,
        journal=journal,
    )
    print(f"CE filled @ Rs {ce_state.entry_avg_price}   SL trigger Rs {ce_state.sl_trigger}")
except ResponseError as exc:
    print(f"CE LEG FAILED: {exc}")
    raise

# ---- Leg 2: SELL ATM PE --------------------------------------------------

print("\n--- PE LEG ---")
try:
    pe_state = enter_options_atm_with_sl(
        client,
        underlying=UNDERLYING,
        underlying_exchange=UNDERLYING_EXCHANGE,
        expiry_date=EXPIRY,
        option_type="PE",
        offset="ATM",
        quantity=QUANTITY,
        product=PRODUCT,
        strategy=strategy + "_pe",
        sl_pct=SL_PCT,
        alert_via=ALERTS,
        journal=journal,
    )
    print(f"PE filled @ Rs {pe_state.entry_avg_price}   SL trigger Rs {pe_state.sl_trigger}")
except ResponseError as exc:
    print(f"PE LEG FAILED: {exc}  -- consider cancelling CE leg manually")
    raise

# ---- Summary ------------------------------------------------------------

total_premium = (ce_state.entry_avg_price + pe_state.entry_avg_price) * QUANTITY
max_loss_proxy = total_premium * (SL_PCT / 100) * 2     # both SLs hit
print(f"\nStraddle entered.")
print(f"  premium collected: Rs {total_premium:,.2f}")
print(f"  worst-case (both SLs hit): Rs {max_loss_proxy:,.2f}")
print(f"  journal: {workdir / 'journal.csv'}")

journal.close()
