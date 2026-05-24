"""High-level chained workflows.

These compose `placeorder` -> `poll_until_filled` -> `avg_fill_price` ->
`placeorder` (SL / target) into one call. They are the canonical
"intelligent" patterns the skill is built around — every example that
needs an SL after fill should call one of these rather than re-implement
the response-chasing loop.

Workflows:

- `place_with_sl_target` — entry + immediate SL + optional target,
  with SL/target computed from the *actual* fill price (not the
  intended entry).
- `enter_options_atm_with_sl` — resolve `optionsymbol` -> place ATM
  CE/PE -> SL on filled premium.
- `square_off_with_alert` — `closeposition` -> compute realized P&L
  -> send alert.
- `place_smart_with_position_check` — query `openposition` first,
  resize, then place a smart order.

All workflows accept an optional `journal` (CsvJournal/SqliteJournal)
and `alert_via` tuple — drop them in to get end-to-end logging and
phone alerts without writing glue.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .alerts import alert_order_lifecycle, notify
from .orders import place_with_retry
from .responses import (
    ResponseError,
    avg_fill_price,
    ensure_success,
    extract_orderid,
    poll_until_filled,
)

Side = Literal["BUY", "SELL"]
Product = Literal["CNC", "MIS", "NRML"]


@dataclass
class EntryResult:
    """Outcome of `place_with_sl_target`. Caller inspects to decide cleanup."""

    entry_order_id: str
    entry_avg_price: float
    entry_qty: int
    sl_order_id: str | None = None
    sl_trigger: float | None = None
    target_order_id: str | None = None
    target_price: float | None = None
    alert_ok: bool = True

    @property
    def has_sl(self) -> bool:
        return self.sl_order_id is not None

    @property
    def has_target(self) -> bool:
        return self.target_order_id is not None


def place_with_sl_target(
    client: Any,
    *,
    strategy: str,
    symbol: str,
    exchange: str,
    action: Side,
    quantity: int,
    product: Product,
    price_type: str = "MARKET",
    limit_price: float | None = None,
    sl_pct: float | None = None,
    target_pct: float | None = None,
    sl_abs: float | None = None,
    target_abs: float | None = None,
    fill_poll_interval_sec: float = 0.5,
    fill_timeout_sec: float = 60.0,
    journal: Any = None,
    alert_via: tuple[str, ...] = (),
) -> EntryResult:
    """Place entry, wait for fill, place SL and/or target from average fill price.

    This is the canonical response-aware workflow:

        1. placeorder(...)             -> response contains orderid
        2. orderstatus(orderid)        -> poll until order_status='complete'
        3. response.data.average_price -> the actual fill price
        4. compute SL trigger = fill * (1 - sl_pct/100)   (for BUY)
                  target      = fill * (1 + target_pct/100)
        5. placeorder(SL-M trigger=SL)  -> SL order id
        6. placeorder(LIMIT price=tgt)  -> target order id

    For a SELL entry the SL is above, target is below — directions flip.

    Either `sl_pct` or `sl_abs` (Rupees from fill) sets the stop.
    Same for target. Pass None for either to skip placement of that leg.

    `price_type='MARKET'` is the simplest entry. For LIMIT, pass
    `limit_price` (still anchored to fill for SL/target).
    """
    if action not in {"BUY", "SELL"}:
        raise ValueError(f"action must be BUY or SELL, got {action!r}")
    if (sl_pct is None) == (sl_abs is None) and sl_pct is not None:
        raise ValueError("pass either sl_pct OR sl_abs, not both")
    if (target_pct is None) == (target_abs is None) and target_pct is not None:
        raise ValueError("pass either target_pct OR target_abs, not both")

    # 1. place the entry
    entry_resp = place_with_retry(
        client,
        strategy=strategy, symbol=symbol, exchange=exchange,
        action=action, price_type=price_type, product=product,
        quantity=quantity,
        price=limit_price if limit_price is not None else 0,
    )
    entry_id = extract_orderid(entry_resp)
    if journal:
        journal.write(strategy=strategy, symbol=symbol, exchange=exchange,
                      action=action, event="entry_placed", order_id=entry_id,
                      price=limit_price, quantity=quantity)
    if alert_via:
        alert_order_lifecycle(
            client, via=alert_via,
            placed=dict(strategy=strategy, symbol=symbol, exchange=exchange,
                        action=action, quantity=quantity,
                        price_type=price_type, product=product,
                        price=limit_price, order_id=entry_id),
        )

    # 2 + 3. poll for fill and extract average price
    final_status = poll_until_filled(
        client, order_id=entry_id, strategy=strategy,
        interval_sec=fill_poll_interval_sec, timeout_sec=fill_timeout_sec,
    )
    fill_price = avg_fill_price(final_status)
    filled_qty = int(final_status["data"].get("quantity") or quantity)
    if journal:
        journal.write(strategy=strategy, symbol=symbol, exchange=exchange,
                      action=action, event="entry_filled",
                      order_id=entry_id, average_price=fill_price,
                      quantity=filled_qty)
    if alert_via:
        alert_order_lifecycle(
            client, via=alert_via,
            filled=dict(strategy=strategy, symbol=symbol, action=action,
                        quantity=filled_qty, average_price=fill_price,
                        order_id=entry_id),
        )

    result = EntryResult(
        entry_order_id=entry_id, entry_avg_price=fill_price,
        entry_qty=filled_qty,
    )

    # 4 + 5. SL — opposite side, SL-M trigger off fill
    if sl_pct is not None or sl_abs is not None:
        sl_trigger = _stop_price(fill_price, action, sl_pct, sl_abs, is_stop=True)
        sl_action = "SELL" if action == "BUY" else "BUY"
        sl_resp = place_with_retry(
            client,
            strategy=strategy, symbol=symbol, exchange=exchange,
            action=sl_action, price_type="SL-M", product=product,
            quantity=filled_qty, price=0, trigger_price=sl_trigger,
        )
        try:
            result.sl_order_id = extract_orderid(sl_resp)
            result.sl_trigger = sl_trigger
            if journal:
                journal.write(strategy=strategy, symbol=symbol, exchange=exchange,
                              action=sl_action, event="sl_placed",
                              order_id=result.sl_order_id,
                              trigger_price=sl_trigger, quantity=filled_qty)
        except ResponseError as exc:
            print(f"[workflow] SL placement failed: {exc}")

    # 6. target — opposite side LIMIT at fill +/- target
    if target_pct is not None or target_abs is not None:
        tgt_price = _stop_price(fill_price, action, target_pct, target_abs, is_stop=False)
        tgt_action = "SELL" if action == "BUY" else "BUY"
        tgt_resp = place_with_retry(
            client,
            strategy=strategy, symbol=symbol, exchange=exchange,
            action=tgt_action, price_type="LIMIT", product=product,
            quantity=filled_qty, price=tgt_price,
        )
        try:
            result.target_order_id = extract_orderid(tgt_resp)
            result.target_price = tgt_price
            if journal:
                journal.write(strategy=strategy, symbol=symbol, exchange=exchange,
                              action=tgt_action, event="target_placed",
                              order_id=result.target_order_id,
                              price=tgt_price, quantity=filled_qty)
        except ResponseError as exc:
            print(f"[workflow] target placement failed: {exc}")

    return result


def _stop_price(
    fill: float, action: Side,
    pct: float | None, abs_offset: float | None,
    *, is_stop: bool,
) -> float:
    """Compute SL or target price from fill given pct or absolute offset.

    For a BUY entry:  SL is BELOW fill, target is ABOVE fill.
    For a SELL entry: SL is ABOVE fill, target is BELOW fill.

    Rounded to 0.05 (standard NSE tick); caller can re-round to a
    custom tick if needed.
    """
    delta = (fill * pct / 100) if pct is not None else float(abs_offset or 0)
    if action == "BUY":
        price = fill - delta if is_stop else fill + delta
    else:
        price = fill + delta if is_stop else fill - delta
    return round(price * 20) / 20  # round to nearest 0.05


def enter_options_atm_with_sl(
    client: Any,
    *,
    underlying: str,
    underlying_exchange: str,
    expiry_date: str,
    option_type: Literal["CE", "PE"],
    offset: str,
    quantity: int,
    product: Product = "NRML",
    strategy: str = "atm_entry",
    sl_pct: float = 30.0,
    target_pct: float | None = None,
    alert_via: tuple[str, ...] = (),
    journal: Any = None,
) -> EntryResult:
    """End-to-end ATM options entry: resolve symbol -> place -> wait fill -> SL.

    Uses `optionsymbol` to get the contract for the given offset (ATM /
    ITM1..n / OTM1..n) and `optionchain`-quality metadata in one call,
    then runs `place_with_sl_target` on it.

    `sl_pct` is measured from the premium fill — `BUY 200CE at 100`
    with `sl_pct=30` places an SL-M at 70.
    """
    sym_resp = client.optionsymbol(
        underlying=underlying,
        exchange=underlying_exchange,
        expiry_date=expiry_date,
        offset=offset,
        option_type=option_type,
    )
    ensure_success(sym_resp, "optionsymbol")
    symbol = sym_resp["symbol"]
    target_exchange = sym_resp.get("exchange", "NFO")

    return place_with_sl_target(
        client,
        strategy=strategy,
        symbol=symbol, exchange=target_exchange,
        action="BUY", quantity=quantity, product=product,
        price_type="MARKET",
        sl_pct=sl_pct, target_pct=target_pct,
        alert_via=alert_via, journal=journal,
    )


def square_off_with_alert(
    client: Any,
    *,
    strategy: str = "manual_squareoff",
    alert_via: tuple[str, ...] = ("telegram", "whatsapp"),
) -> dict[str, Any]:
    """Close every open position and broadcast the realized P&L summary.

    Calls `closeposition` then pulls `funds` for the post-square-off
    realized number. Returns the close response for inspection.
    """
    close_resp = client.closeposition(strategy=strategy)
    funds_resp = client.funds()
    data = funds_resp.get("data", {}) if isinstance(funds_resp, dict) else {}
    realized = float(data.get("m2mrealized") or 0)
    unrealized = float(data.get("m2munrealized") or 0)
    cash = float(data.get("availablecash") or 0)
    ob_resp = client.orderbook()
    stats = (ob_resp.get("data", {}) or {}).get("statistics", {})
    completed = int(stats.get("total_completed_orders") or 0)
    pb_resp = client.positionbook()
    open_count = sum(
        1 for p in (pb_resp.get("data") or [])
        if int(p.get("quantity") or 0) != 0
    )

    from .alerts import fmt_daily_pnl
    msg = fmt_daily_pnl(
        realized=realized, unrealized=unrealized,
        available_cash=cash, open_positions=open_count,
        completed_orders=completed,
    )
    notify(client, msg, via=alert_via)
    return close_resp


def place_smart_with_position_check(
    client: Any,
    *,
    strategy: str,
    symbol: str,
    exchange: str,
    action: Side,
    target_position: int,
    product: Product,
    price_type: str = "MARKET",
    price: float | None = None,
    alert_via: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Use `openposition` to size the order, then `placesmartorder`.

    `target_position` is the *desired* net position after the order
    executes (signed: + long, - short). Smart-order computes the
    delta internally; we pass it through but also alert with the
    pre-trade state.
    """
    op = client.openposition(strategy=strategy, symbol=symbol, exchange=exchange, product=product)
    current = int(op.get("quantity") or 0)
    delta = target_position - current
    if delta == 0:
        print(f"[smart] already at target position {current}; no order")
        return {"status": "success", "message": "no-op", "current": current}

    resp = client.placesmartorder(
        strategy=strategy, symbol=symbol, exchange=exchange,
        action=action, price_type=price_type, product=product,
        quantity=abs(delta), position_size=target_position,
        price=price if price is not None else 0,
    )
    if alert_via and resp.get("status") == "success":
        oid = resp.get("orderid") or (resp.get("data") or {}).get("orderid", "?")
        alert_order_lifecycle(
            client, via=alert_via,
            placed=dict(strategy=strategy, symbol=symbol, exchange=exchange,
                        action=action, quantity=abs(delta),
                        price_type=price_type, product=product,
                        price=price, order_id=str(oid)),
        )
    return resp
