"""Indian-market cost model.

Numbers reflect the regime in force at time of writing (April 2026 SEBI
revisions: STT raised on options sell-side, exchange transaction charges
unchanged on equity). Adjust constants if statutory rates change.

Two calling styles:

1. **For backtests** — use `fees_pct(market, segment)` to get a float
   percentage that multiplies notional (compatible with
   `vbt.Portfolio.from_signals(fees=..., fixed_fees=20)`).

2. **For live order previews** — use `estimate_charges(...)` for a
   detailed breakdown printed alongside the order preview.

All amounts are in INR.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Segment = Literal[
    "equity_delivery",
    "equity_intraday",
    "fno_futures",
    "fno_options",
    "currency_futures",
    "currency_options",
    "commodity_futures",
    "commodity_options",
]


# (broker_per_order, exch_txn_pct, stt_buy_pct, stt_sell_pct,
#  sebi_pct, gst_on_brok_exch, stamp_buy_pct)
_FEE_TABLE: dict[Segment, dict[str, float]] = {
    "equity_delivery": dict(
        broker_per_order=0,
        exch_txn_pct=0.00297,
        stt_buy_pct=0.1,
        stt_sell_pct=0.1,
        sebi_pct=0.0001,
        stamp_buy_pct=0.015,
        gst_on_brok_exch=18,
    ),
    "equity_intraday": dict(
        broker_per_order=20,
        exch_txn_pct=0.00297,
        stt_buy_pct=0,
        stt_sell_pct=0.025,
        sebi_pct=0.0001,
        stamp_buy_pct=0.003,
        gst_on_brok_exch=18,
    ),
    "fno_futures": dict(
        broker_per_order=20,
        exch_txn_pct=0.0019,
        stt_buy_pct=0,
        stt_sell_pct=0.02,
        sebi_pct=0.0001,
        stamp_buy_pct=0.002,
        gst_on_brok_exch=18,
    ),
    "fno_options": dict(
        broker_per_order=20,
        exch_txn_pct=0.03503,
        stt_buy_pct=0,
        stt_sell_pct=0.1,            # raised in 2024; current 2026
        sebi_pct=0.0001,
        stamp_buy_pct=0.003,
        gst_on_brok_exch=18,
    ),
    "currency_futures": dict(
        broker_per_order=20,
        exch_txn_pct=0.0009,
        stt_buy_pct=0,
        stt_sell_pct=0,
        sebi_pct=0.0001,
        stamp_buy_pct=0.0001,
        gst_on_brok_exch=18,
    ),
    "currency_options": dict(
        broker_per_order=20,
        exch_txn_pct=0.035,
        stt_buy_pct=0,
        stt_sell_pct=0,
        sebi_pct=0.0001,
        stamp_buy_pct=0.0001,
        gst_on_brok_exch=18,
    ),
    "commodity_futures": dict(
        broker_per_order=20,
        exch_txn_pct=0.0021,
        stt_buy_pct=0,
        stt_sell_pct=0.01,
        sebi_pct=0.0001,
        stamp_buy_pct=0.002,
        gst_on_brok_exch=18,
    ),
    "commodity_options": dict(
        broker_per_order=20,
        exch_txn_pct=0.05,
        stt_buy_pct=0,
        stt_sell_pct=0.05,
        sebi_pct=0.0001,
        stamp_buy_pct=0.003,
        gst_on_brok_exch=18,
    ),
}


@dataclass
class ChargeBreakdown:
    notional_buy: float
    notional_sell: float
    brokerage: float
    stt: float
    exch_txn: float
    sebi: float
    gst: float
    stamp: float
    total: float


def estimate_charges(
    segment: Segment,
    *,
    buy_price: float,
    sell_price: float,
    quantity: int,
    broker_per_order_override: float | None = None,
) -> ChargeBreakdown:
    """Compute the full charge breakdown for a round-trip trade."""
    f = _FEE_TABLE[segment]
    buy_n = buy_price * quantity
    sell_n = sell_price * quantity

    brokerage = (broker_per_order_override if broker_per_order_override is not None
                 else f["broker_per_order"]) * 2
    stt = (f["stt_buy_pct"] / 100) * buy_n + (f["stt_sell_pct"] / 100) * sell_n
    exch = (f["exch_txn_pct"] / 100) * (buy_n + sell_n)
    sebi = (f["sebi_pct"] / 100) * (buy_n + sell_n)
    gst = (f["gst_on_brok_exch"] / 100) * (brokerage + exch + sebi)
    stamp = (f["stamp_buy_pct"] / 100) * buy_n
    total = brokerage + stt + exch + sebi + gst + stamp

    return ChargeBreakdown(
        notional_buy=buy_n, notional_sell=sell_n,
        brokerage=brokerage, stt=stt, exch_txn=exch,
        sebi=sebi, gst=gst, stamp=stamp, total=total,
    )


def fees_pct(segment: Segment, *, side: str = "round_trip") -> float:
    """Approximate variable fee percentage for vbt backtest fees parameter.

    Excludes the flat brokerage and stamp duty — pass those separately
    via `fixed_fees=` in the vbt portfolio. Used to wire realistic
    transaction costs into vectorbt.from_signals without rebuilding the
    full breakdown for every bar.
    """
    f = _FEE_TABLE[segment]
    var = f["exch_txn_pct"] + f["sebi_pct"]
    if side in {"round_trip", "rt"}:
        var = var + (f["stt_buy_pct"] + f["stt_sell_pct"]) / 2
    elif side == "sell":
        var = var + f["stt_sell_pct"]
    elif side == "buy":
        var = var + f["stt_buy_pct"]
    return var / 100


def fixed_fees_inr(segment: Segment) -> int:
    """The flat per-order brokerage, in INR. Pass to vbt as `fixed_fees`."""
    return int(_FEE_TABLE[segment]["broker_per_order"])
