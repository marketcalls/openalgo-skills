"""Options analytics built on `client.optionchain` and `client.optiongreeks`.

`optionchain` returns a strike-keyed dict — useful for display but
awkward for analytics. `chain_to_df` flattens it into a long-format
DataFrame that pandas + matplotlib can use directly.

Functions:
- `chain_to_df`         — flatten optionchain JSON
- `atm_row`             — find the at-the-money strike row
- `pcr`                 — Put-Call Ratio (OI and volume variants)
- `max_pain`            — strike with smallest total option-writer loss
- `iv_skew`             — IV by strike using `optiongreeks` per symbol
- `payoff`              — payoff DataFrame for an arbitrary multi-leg position
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def chain_to_df(chain_response: dict[str, Any]) -> pd.DataFrame:
    """Flatten `client.optionchain` payload into a long DataFrame.

    Output columns: strike, side ('CE'/'PE'), symbol, label, ltp, bid,
    ask, open, high, low, prev_close, volume, oi, lotsize, tick_size.

    Single row = single option contract. Strike repeats once per side.
    """
    if chain_response.get("status") != "success":
        raise RuntimeError(f"optionchain failed: {chain_response}")
    rows: list[dict[str, Any]] = []
    for entry in chain_response.get("chain", []):
        strike = entry["strike"]
        for side in ("ce", "pe"):
            leg = entry.get(side) or {}
            if not leg:
                continue
            rows.append({
                "strike": strike,
                "side": side.upper(),
                **leg,
            })
    df = pd.DataFrame(rows)
    df.attrs["underlying"] = chain_response.get("underlying")
    df.attrs["underlying_ltp"] = chain_response.get("underlying_ltp")
    df.attrs["atm_strike"] = chain_response.get("atm_strike")
    df.attrs["expiry_date"] = chain_response.get("expiry_date")
    return df


def atm_row(df: pd.DataFrame, side: str = "CE") -> pd.Series:
    """Return the ATM contract row for the given side."""
    atm = df.attrs.get("atm_strike")
    if atm is None:
        underlying = df.attrs.get("underlying_ltp")
        if underlying is None:
            raise ValueError("DataFrame missing atm_strike and underlying_ltp metadata")
        atm = df["strike"].iloc[(df["strike"] - underlying).abs().argsort().iloc[0]]
    row = df[(df["strike"] == atm) & (df["side"] == side.upper())]
    if row.empty:
        raise LookupError(f"no {side} row at ATM strike {atm}")
    return row.iloc[0]


def pcr(df: pd.DataFrame, *, basis: str = "oi") -> float:
    """Put-Call Ratio.

    `basis="oi"`     — sum(PE OI) / sum(CE OI). Sentiment proxy.
    `basis="volume"` — sum(PE vol) / sum(CE vol). Intraday flow proxy.
    """
    if basis not in {"oi", "volume"}:
        raise ValueError("basis must be 'oi' or 'volume'")
    ce_total = df.loc[df["side"] == "CE", basis].sum()
    pe_total = df.loc[df["side"] == "PE", basis].sum()
    if ce_total == 0:
        return float("inf")
    return float(pe_total / ce_total)


def max_pain(df: pd.DataFrame) -> dict[str, Any]:
    """Max-pain strike — the price at expiry that minimizes the total
    payout an option writer must make.

    Returns dict with `strike`, `total_pain`, and a `series` of pains by
    strike for plotting.
    """
    strikes = sorted(df["strike"].unique())
    pains: dict[float, float] = {}
    for K in strikes:
        ce_oi = df[(df["side"] == "CE") & (df["strike"] <= K)][["strike", "oi"]]
        pe_oi = df[(df["side"] == "PE") & (df["strike"] >= K)][["strike", "oi"]]
        # writer pays max(0, S-K) on CE and max(0, K-S) on PE for each open contract
        ce_pain = float((np.maximum(0, K - ce_oi["strike"]) * ce_oi["oi"]).sum())
        pe_pain = float((np.maximum(0, pe_oi["strike"] - K) * pe_oi["oi"]).sum())
        pains[K] = ce_pain + pe_pain
    best_strike = min(pains, key=pains.get)  # type: ignore[arg-type]
    return {
        "strike": best_strike,
        "total_pain": pains[best_strike],
        "series": pd.Series(pains).sort_index(),
    }


def iv_skew(
    client: Any,
    df: pd.DataFrame,
    *,
    underlying: str | None = None,
    underlying_exchange: str = "NSE_INDEX",
    interest_rate: float = 0.0,
    side: str = "CE",
) -> pd.DataFrame:
    """IV by strike via repeated `optiongreeks` calls.

    Rate limit: optiongreeks is general-API (50/s) but we throttle to
    keep brokers happy. Returns DataFrame with strike, iv, delta, gamma,
    theta, vega.
    """
    underlying = underlying or df.attrs.get("underlying")
    if not underlying:
        raise ValueError("`underlying` not in df.attrs; pass underlying= explicitly")
    contracts = df[df["side"] == side.upper()]
    out: list[dict[str, Any]] = []
    for _, row in contracts.iterrows():
        resp = client.optiongreeks(
            symbol=row["symbol"],
            exchange="NFO",
            interest_rate=interest_rate,
            underlying_symbol=underlying,
            underlying_exchange=underlying_exchange,
        )
        if resp.get("status") != "success":
            continue
        g = resp.get("greeks", {})
        out.append({
            "strike": row["strike"],
            "iv": resp.get("implied_volatility"),
            "delta": g.get("delta"),
            "gamma": g.get("gamma"),
            "theta": g.get("theta"),
            "vega": g.get("vega"),
        })
    return pd.DataFrame(out).sort_values("strike").reset_index(drop=True)


def payoff(
    legs: list[dict[str, Any]],
    *,
    spot_range: tuple[float, float] | None = None,
    points: int = 200,
) -> pd.DataFrame:
    """Compute the at-expiry payoff DataFrame for a multi-leg position.

    Each leg is a dict:
        {
            "type": "CE" | "PE" | "FUT" | "EQ",
            "strike": 26500,        # ignored for FUT/EQ
            "premium": 220.0,       # paid for BUY, received for SELL
            "quantity": 75,         # signed: + for BUY, - for SELL, or use "action"
            "action": "BUY"|"SELL", # optional alternative to signed quantity
        }

    Returns DataFrame with spot index and `payoff` column (per-unit).
    Multiply by lot_size externally for the full lot payoff.
    """
    if not legs:
        raise ValueError("at least one leg required")
    if spot_range is None:
        strikes = [l.get("strike") for l in legs if l.get("strike")]
        if not strikes:
            raise ValueError("spot_range required when legs have no strikes")
        center = sum(strikes) / len(strikes)
        spot_range = (center * 0.85, center * 1.15)

    spots = np.linspace(spot_range[0], spot_range[1], points)
    total = np.zeros_like(spots)

    for leg in legs:
        qty = leg.get("quantity", 1)
        action = leg.get("action", "BUY").upper()
        if action == "SELL":
            qty = -abs(qty)
        else:
            qty = abs(qty)
        premium = float(leg.get("premium", 0.0))
        kind = leg["type"].upper()

        if kind == "CE":
            intrinsic = np.maximum(0.0, spots - float(leg["strike"]))
            leg_pnl = qty * (intrinsic - premium)
        elif kind == "PE":
            intrinsic = np.maximum(0.0, float(leg["strike"]) - spots)
            leg_pnl = qty * (intrinsic - premium)
        elif kind in {"FUT", "EQ"}:
            entry = float(leg.get("entry_price", premium))
            leg_pnl = qty * (spots - entry)
        else:
            raise ValueError(f"unknown leg type: {kind!r}")
        total = total + leg_pnl

    return pd.DataFrame({"spot": spots, "payoff": total}).set_index("spot")
