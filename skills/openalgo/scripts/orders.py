"""Order placement helpers: preview, confirm, place, retry-on-rate-limit.

These wrap `client.placeorder`, `client.modifyorder`, `client.cancelorder`
with three repeatedly-needed behaviours:

1. **Preview before placement** — a structured printout so the user sees
   exactly what is about to hit the broker. Compatible with both
   interactive (REPL / notebook) and unattended (cron / scheduler) use.

2. **Retry on rate-limit** — OpenAlgo caps order APIs at 10/sec
   (smart-orders at 2/sec). A transient 429 should not kill a strategy.
   We retry with exponential backoff, capped at three attempts.

3. **Type coercion** — the SDK accepts both int and string for quantity
   / price / trigger_price; we normalize to string so payloads survive
   the request layer's strict validation under all brokers.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Literal

# Live-order rate guidance — keep in sync with references/rate-limits.md
_RETRY_DELAYS_SEC = (0.5, 1.5, 3.5)
_RATELIMIT_HINTS = ("rate", "429", "too many")


@dataclass
class OrderPreview:
    strategy: str
    symbol: str
    exchange: str
    action: Literal["BUY", "SELL"]
    quantity: int
    price_type: Literal["MARKET", "LIMIT", "SL", "SL-M"]
    product: Literal["CNC", "MIS", "NRML"]
    price: float | None = None
    trigger_price: float | None = None
    notional: float | None = None
    note: str | None = None

    def render(self) -> str:
        lines = [
            "--- Order Preview ---",
            f"  strategy:    {self.strategy}",
            f"  side:        {self.action} {self.quantity} {self.symbol} @ {self.exchange}",
            f"  type:        {self.price_type} ({self.product})",
        ]
        if self.price is not None:
            lines.append(f"  price:       {self.price}")
        if self.trigger_price is not None:
            lines.append(f"  trigger:     {self.trigger_price}")
        if self.notional is not None:
            lines.append(f"  notional:    Rs {self.notional:,.2f}")
        if self.note:
            lines.append(f"  note:        {self.note}")
        return "\n".join(lines)


def preview_order(
    *,
    strategy: str,
    symbol: str,
    exchange: str,
    action: str,
    quantity: int,
    price_type: str,
    product: str,
    price: float | None = None,
    trigger_price: float | None = None,
    note: str | None = None,
) -> OrderPreview:
    """Build a structured preview. Caller `print(preview.render())` and confirms."""
    notional = None
    if price and quantity:
        notional = float(price) * int(quantity)
    return OrderPreview(
        strategy=strategy,
        symbol=symbol,
        exchange=exchange,
        action=action.upper(),  # type: ignore[arg-type]
        quantity=int(quantity),
        price_type=price_type.upper(),  # type: ignore[arg-type]
        product=product.upper(),  # type: ignore[arg-type]
        price=price,
        trigger_price=trigger_price,
        notional=notional,
        note=note,
    )


def confirm_interactive(preview: OrderPreview) -> bool:
    """Print the preview and ask y/N on stdin. Returns True only on explicit 'y'."""
    print(preview.render())
    return input("Proceed? [y/N] ").strip().lower() == "y"


def place_with_retry(client: Any, **kwargs: Any) -> dict[str, Any]:
    """`client.placeorder` with exponential backoff on rate-limit responses.

    All numeric kwargs (quantity, price, trigger_price, disclosed_quantity)
    are coerced to str — the SDK is happy either way but broker adapters
    are sometimes stricter.
    """
    payload = _stringify_numeric(kwargs)
    last_resp: dict[str, Any] = {}
    for attempt, delay in enumerate((0.0, *_RETRY_DELAYS_SEC)):
        if delay:
            time.sleep(delay)
        last_resp = client.placeorder(**payload)
        if not _looks_rate_limited(last_resp):
            return last_resp
    return last_resp


def place_with_confirmation(
    client: Any,
    preview: OrderPreview,
    *,
    auto_confirm: bool = False,
) -> dict[str, Any] | None:
    """End-to-end: print preview, gate on confirmation, place with retry.

    Returns None if the user declined (or the analyzer is off and
    auto_confirm wasn't set). Returns the SDK response dict otherwise.
    """
    if not auto_confirm and not confirm_interactive(preview):
        print("aborted by user")
        return None
    return place_with_retry(
        client,
        strategy=preview.strategy,
        symbol=preview.symbol,
        exchange=preview.exchange,
        action=preview.action,
        price_type=preview.price_type,
        product=preview.product,
        quantity=preview.quantity,
        price=preview.price if preview.price is not None else 0,
        trigger_price=preview.trigger_price if preview.trigger_price is not None else 0,
    )


def modify_with_retry(client: Any, **kwargs: Any) -> dict[str, Any]:
    payload = _stringify_numeric(kwargs)
    last_resp: dict[str, Any] = {}
    for delay in (0.0, *_RETRY_DELAYS_SEC):
        if delay:
            time.sleep(delay)
        last_resp = client.modifyorder(**payload)
        if not _looks_rate_limited(last_resp):
            return last_resp
    return last_resp


def cancel_with_retry(client: Any, *, order_id: str, strategy: str) -> dict[str, Any]:
    last_resp: dict[str, Any] = {}
    for delay in (0.0, *_RETRY_DELAYS_SEC):
        if delay:
            time.sleep(delay)
        last_resp = client.cancelorder(order_id=order_id, strategy=strategy)
        if not _looks_rate_limited(last_resp):
            return last_resp
    return last_resp


def is_terminal_status(order_status: str) -> bool:
    """`complete`, `rejected`, `cancelled` are terminal — won't change after.

    Broker-side spellings vary slightly across plugins. Match
    case-insensitively against known terminal substrings.
    """
    s = order_status.lower()
    return any(t in s for t in ("complete", "reject", "cancel"))


def poll_until_terminal(
    client: Any,
    *,
    order_id: str,
    strategy: str,
    interval_sec: float = 1.0,
    timeout_sec: float = 60.0,
) -> dict[str, Any]:
    """Poll `orderstatus` until terminal or `timeout_sec` elapsed.

    Returns the last status response. Caller decides whether to
    modify / cancel / give up based on the order_status field.
    """
    deadline = time.monotonic() + timeout_sec
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = client.orderstatus(order_id=order_id, strategy=strategy)
        if last.get("status") == "success":
            status = last["data"].get("order_status", "")
            if is_terminal_status(status):
                return last
        time.sleep(interval_sec)
    return last


def _stringify_numeric(d: dict[str, Any]) -> dict[str, Any]:
    out = dict(d)
    for k in ("quantity", "price", "trigger_price", "disclosed_quantity", "splitsize"):
        if k in out and out[k] is not None and not isinstance(out[k], str):
            out[k] = str(out[k])
    return out


def _looks_rate_limited(resp: dict[str, Any]) -> bool:
    if resp.get("status") == "success":
        return False
    msg = str(resp.get("message", "")).lower()
    return any(hint in msg for hint in _RATELIMIT_HINTS)
