"""Telegram and WhatsApp alert helpers.

The OpenAlgo SDK ships two send-only alert endpoints:

    client.telegram(username, message)
    client.whatsapp(text, to=..., image=..., document=..., username=...,
                    caption=..., filename=..., wait_for_delivery=True)

These wrappers add three things on top:

1. **Pre-formatted templates** for the events traders most often want
   piped to a phone: order placed, order filled, stoploss triggered,
   stoploss/target placed, position closed, scanner results, daily P&L.

2. **Multi-channel dispatch.** `notify(...)` sends to both Telegram and
   WhatsApp when both are configured, so the user gets one call site
   regardless of channel preference.

3. **Failsafe** — alert failures never crash the trading code. They log
   to stderr and return a result dict the caller can inspect.

All templates use plain ASCII (no emojis) per the openalgo-skills
output convention.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class AlertResult:
    telegram: dict[str, Any] | None
    whatsapp: dict[str, Any] | None

    @property
    def ok(self) -> bool:
        t_ok = self.telegram is None or str(self.telegram.get("status", "")).lower() == "success"
        w_ok = self.whatsapp is None or str(self.whatsapp.get("status", "")).lower() == "success"
        return t_ok and w_ok


def _telegram_user() -> str | None:
    return os.environ.get("ALERT_TELEGRAM_USERNAME") or None


def _whatsapp_to() -> str | list[str] | None:
    raw = os.environ.get("ALERT_WHATSAPP_TO") or ""
    raw = raw.strip()
    if not raw:
        return None
    if "," in raw:
        return [s.strip() for s in raw.split(",") if s.strip()]
    return raw


def notify(
    client: Any,
    message: str,
    *,
    via: tuple[str, ...] = ("telegram", "whatsapp"),
    telegram_user: str | None = None,
    whatsapp_to: str | list[str] | None = None,
    image: str | Path | None = None,
    document: str | Path | None = None,
    document_filename: str | None = None,
    caption: str | None = None,
) -> AlertResult:
    """Send `message` to one or both channels.

    Resolution:
    - `via=("telegram",)`         only Telegram
    - `via=("whatsapp",)`         only WhatsApp
    - default                     try both (skips whichever has no destination)

    `image` / `document` are WhatsApp-only (Telegram alert API is text-only).
    """
    tg_resp: dict[str, Any] | None = None
    wa_resp: dict[str, Any] | None = None

    if "telegram" in via:
        user = telegram_user or _telegram_user()
        if user:
            try:
                tg_resp = client.telegram(username=user, message=message)
            except Exception as exc:
                print(f"[alerts] telegram send failed: {exc!r}", file=sys.stderr)
                tg_resp = {"status": "error", "message": repr(exc)}
        else:
            print("[alerts] telegram skipped (no username configured)", file=sys.stderr)

    if "whatsapp" in via:
        to = whatsapp_to if whatsapp_to is not None else _whatsapp_to()
        kwargs: dict[str, Any] = {}
        if image:
            kwargs["image"] = str(image)
            if caption or message:
                kwargs["caption"] = caption or message
        elif document:
            kwargs["document"] = str(document)
            if document_filename:
                kwargs["filename"] = document_filename
        if to:
            kwargs["to"] = to
        try:
            if image and not message:
                wa_resp = client.whatsapp(**kwargs)
            else:
                wa_resp = client.whatsapp(message, **kwargs)
        except Exception as exc:
            print(f"[alerts] whatsapp send failed: {exc!r}", file=sys.stderr)
            wa_resp = {"status": "error", "message": repr(exc)}

    return AlertResult(telegram=tg_resp, whatsapp=wa_resp)


# ---- Pre-built message templates -----------------------------------------


def _ts() -> str:
    return datetime.now().strftime("%d-%b %H:%M:%S")


def fmt_order_placed(
    *,
    strategy: str,
    symbol: str,
    exchange: str,
    action: str,
    quantity: int,
    price_type: str,
    product: str,
    price: float | None,
    order_id: str,
) -> str:
    px = f" @ {price}" if price else ""
    return (
        f"[ORDER PLACED] {_ts()}\n"
        f"Strategy:  {strategy}\n"
        f"{action} {quantity} {symbol} ({exchange}){px}\n"
        f"Type:      {price_type} / {product}\n"
        f"OrderId:   {order_id}"
    )


def fmt_order_filled(
    *,
    strategy: str,
    symbol: str,
    action: str,
    quantity: int,
    average_price: float,
    order_id: str,
    sl_price: float | None = None,
    target_price: float | None = None,
) -> str:
    lines = [
        f"[FILLED] {_ts()}",
        f"Strategy:  {strategy}",
        f"{action} {quantity} {symbol}  avg {average_price}",
        f"OrderId:   {order_id}",
    ]
    if sl_price is not None:
        lines.append(f"SL set:    {sl_price}")
    if target_price is not None:
        lines.append(f"Target:    {target_price}")
    return "\n".join(lines)


def fmt_stoploss_triggered(
    *,
    strategy: str,
    symbol: str,
    sl_price: float,
    fill_price: float,
    pnl: float | None = None,
) -> str:
    lines = [
        f"[STOPLOSS HIT] {_ts()}",
        f"Strategy:  {strategy}",
        f"{symbol}  SL {sl_price} -> filled {fill_price}",
    ]
    if pnl is not None:
        lines.append(f"P&L:       Rs {pnl:,.2f}")
    return "\n".join(lines)


def fmt_target_hit(
    *,
    strategy: str,
    symbol: str,
    target_price: float,
    fill_price: float,
    pnl: float,
) -> str:
    return (
        f"[TARGET HIT] {_ts()}\n"
        f"Strategy:  {strategy}\n"
        f"{symbol}  target {target_price} -> filled {fill_price}\n"
        f"P&L:       Rs {pnl:,.2f}"
    )


def fmt_position_closed(
    *,
    strategy: str,
    symbol: str,
    quantity: int,
    entry: float,
    exit: float,
    pnl: float,
) -> str:
    pct = (exit / entry - 1) * 100 if entry else 0
    return (
        f"[POSITION CLOSED] {_ts()}\n"
        f"Strategy:  {strategy}\n"
        f"{symbol} x {quantity}  entry {entry} -> exit {exit}  ({pct:+.2f}%)\n"
        f"P&L:       Rs {pnl:,.2f}"
    )


def fmt_scanner_results(
    title: str,
    rows: list[dict[str, Any]],
    *,
    fields: list[str] | None = None,
    max_rows: int = 10,
) -> str:
    """Tabular text summary of a scanner output. Trims to `max_rows`."""
    if not rows:
        return f"[SCAN] {title} - no matches"
    if fields is None:
        fields = list(rows[0].keys())[:5]
    out = [f"[SCAN] {title} - {len(rows)} matches"]
    for i, r in enumerate(rows[:max_rows]):
        cells = [f"{f}={r.get(f)}" for f in fields if f in r]
        out.append(f"  {i + 1}. " + " ".join(cells))
    if len(rows) > max_rows:
        out.append(f"  ... and {len(rows) - max_rows} more")
    return "\n".join(out)


def fmt_daily_pnl(
    *,
    realized: float,
    unrealized: float,
    available_cash: float,
    open_positions: int,
    completed_orders: int,
) -> str:
    return (
        f"[DAILY P&L] {_ts()}\n"
        f"Realized:    Rs {realized:,.2f}\n"
        f"Unrealized:  Rs {unrealized:,.2f}\n"
        f"Net:         Rs {realized + unrealized:,.2f}\n"
        f"Available:   Rs {available_cash:,.2f}\n"
        f"Open:        {open_positions} position(s)\n"
        f"Filled:      {completed_orders} order(s)"
    )


def fmt_error(strategy: str, where: str, error: str) -> str:
    return f"[ERROR] {_ts()}\nStrategy: {strategy}\nIn:       {where}\nMessage:  {error}"


# ---- Higher-level convenience --------------------------------------------


def alert_order_lifecycle(
    client: Any,
    *,
    placed: dict[str, Any] | None = None,
    filled: dict[str, Any] | None = None,
    closed: dict[str, Any] | None = None,
    sl_hit: dict[str, Any] | None = None,
    target_hit: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    via: tuple[str, ...] = ("telegram", "whatsapp"),
) -> AlertResult:
    """One-call dispatcher — pass exactly one event kwarg per call.

    Each kwarg accepts the same keys as the matching `fmt_*` template.
    """
    if placed:
        msg = fmt_order_placed(**placed)
    elif filled:
        msg = fmt_order_filled(**filled)
    elif sl_hit:
        msg = fmt_stoploss_triggered(**sl_hit)
    elif target_hit:
        msg = fmt_target_hit(**target_hit)
    elif closed:
        msg = fmt_position_closed(**closed)
    elif error:
        msg = fmt_error(**error)
    else:
        raise ValueError("alert_order_lifecycle requires one event kwarg")
    return notify(client, msg, via=via)


def send_chart(
    client: Any,
    image_path: str | Path,
    caption: str = "",
    *,
    whatsapp_to: str | list[str] | None = None,
) -> AlertResult:
    """Send a chart image via WhatsApp (Telegram alert API is text-only).

    `image_path` must resolve to a file under one of the server's
    configured `WHATSAPP_ATTACHMENT_ROOTS` directories (default
    `<openalgo>/db/attachments/`).
    """
    return notify(
        client, caption, via=("whatsapp",),
        image=image_path, whatsapp_to=whatsapp_to,
    )


def send_report(
    client: Any,
    document_path: str | Path,
    caption: str = "",
    *,
    filename: str | None = None,
    whatsapp_to: str | list[str] | None = None,
) -> AlertResult:
    """Send a PDF / CSV report via WhatsApp."""
    return notify(
        client, caption, via=("whatsapp",),
        document=document_path,
        document_filename=filename or Path(document_path).name,
        whatsapp_to=whatsapp_to,
    )
