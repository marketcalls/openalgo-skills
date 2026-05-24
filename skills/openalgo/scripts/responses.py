"""Response-navigation helpers.

The OpenAlgo SDK returns dicts whose shape varies slightly across
endpoints (some put the payload under `data`, some at top level, some
under `results`). These helpers normalize that — every getter raises a
clear `ResponseError` instead of letting downstream code see `None`
and crash with a confusing AttributeError.

The functions here are the canonical extractors. Every chained workflow
in `references/common-workflows.md` and `examples/` calls them. When the
SDK changes a field name, fix it here once and every example updates.

Shape map (current SDK):

| Endpoint            | Top-level keys              | Payload location |
|---------------------|-----------------------------|------------------|
| placeorder          | status, orderid             | top level        |
| modifyorder         | status, orderid             | top level        |
| cancelorder         | status, orderid             | top level        |
| placesmartorder     | status, orderid             | top level        |
| optionsorder        | status, orderid, symbol,    | top level        |
|                     |   underlying, exchange,     |                  |
|                     |   underlying_ltp, mode      |                  |
| optionsmultiorder   | status, underlying, results | top + results[]  |
| basketorder         | status, results             | top + results[]  |
| splitorder          | status, results             | top + results[]  |
| orderstatus         | status, data                | data.{...}       |
| openposition        | status, quantity            | top level        |
| quotes              | status, data                | data.{ohlc, ltp} |
| multiquotes         | status, results             | results[i].data  |
| depth               | status, data                | data.{asks, bids}|
| history             | DataFrame                   | (special — df)   |
| optionchain         | status, chain, underlying,  | chain[] + meta   |
|                     |   underlying_ltp, atm_strike|                  |
| optionsymbol        | status, symbol, exchange,   | top level        |
|                     |   lotsize, tick_size, ...   |                  |
| optiongreeks        | status, greeks, iv, ...     | top level        |
| funds               | status, data                | data.{...}       |
| margin              | status, data                | data.{...}       |
| orderbook           | status, data                | data.orders[]    |
| tradebook           | status, data                | data[]           |
| positionbook        | status, data                | data[]           |
| holdings            | status, data                | data.holdings[]  |
| analyzerstatus      | status, data                | data.{...}       |
| analyzertoggle      | status, data                | data.{...}       |

Errors uniformly look like: `{"status": "error", "message": "..."}`.
"""

from __future__ import annotations

import time
from typing import Any


class ResponseError(RuntimeError):
    """Raised when an OpenAlgo response indicates failure or is missing fields."""

    def __init__(self, message: str, response: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.response = response or {}


# ---- generic ---------------------------------------------------------------


def ensure_success(resp: dict[str, Any], action: str = "request") -> dict[str, Any]:
    """Raise ResponseError if status != 'success'. Returns the original dict."""
    if not isinstance(resp, dict):
        raise ResponseError(f"{action} returned non-dict: {type(resp).__name__}", None)
    if str(resp.get("status", "")).lower() != "success":
        raise ResponseError(
            f"{action} failed: {resp.get('message') or resp}", resp,
        )
    return resp


def get_data(resp: dict[str, Any]) -> dict[str, Any]:
    """Return `response['data']` if present, else the response itself."""
    if "data" in resp and isinstance(resp["data"], dict):
        return resp["data"]
    return resp


# ---- order placement ------------------------------------------------------


def extract_orderid(resp: dict[str, Any]) -> str:
    """Pull the orderid from a place/modify/cancel response.

    Some plugins return it at top level, some under `data.orderid`,
    some inside `data` for placesmartorder. We try all three.
    """
    ensure_success(resp, "placeorder/modifyorder/cancelorder")
    if "orderid" in resp:
        return str(resp["orderid"])
    data = resp.get("data") or {}
    if isinstance(data, dict) and "orderid" in data:
        return str(data["orderid"])
    raise ResponseError("no orderid in response", resp)


def extract_orderids_basket(resp: dict[str, Any]) -> list[str]:
    """Return orderids from a basketorder / optionsmultiorder / splitorder response.

    Each leg in `results[]` may individually be success or failure —
    skip the failures rather than raise, and let the caller decide.
    """
    ensure_success(resp, "basketorder/optionsmultiorder/splitorder")
    out: list[str] = []
    for leg in resp.get("results", []):
        if str(leg.get("status", "")).lower() == "success" and "orderid" in leg:
            out.append(str(leg["orderid"]))
    return out


def options_order_details(resp: dict[str, Any]) -> dict[str, Any]:
    """For `optionsorder`, return {orderid, symbol, underlying, underlying_ltp, offset, option_type, exchange, mode}."""
    ensure_success(resp, "optionsorder")
    keys = ("orderid", "symbol", "underlying", "underlying_ltp",
            "offset", "option_type", "exchange", "mode")
    return {k: resp.get(k) for k in keys}


# ---- order status / fill detection ---------------------------------------


def is_filled(status_resp: dict[str, Any]) -> bool:
    """True if `orderstatus.data.order_status` indicates complete."""
    if str(status_resp.get("status", "")).lower() != "success":
        return False
    s = str((status_resp.get("data") or {}).get("order_status", "")).lower()
    return "complete" in s


def is_terminal(status_resp: dict[str, Any]) -> bool:
    """True if order is in a final state (complete / rejected / cancelled)."""
    if str(status_resp.get("status", "")).lower() != "success":
        return False
    s = str((status_resp.get("data") or {}).get("order_status", "")).lower()
    return any(t in s for t in ("complete", "reject", "cancel"))


def avg_fill_price(status_resp: dict[str, Any]) -> float:
    """Return `data.average_price` from an `orderstatus` response.

    Raises ResponseError if the order is not yet filled or the field is
    missing — callers should `poll_until_filled` first.
    """
    ensure_success(status_resp, "orderstatus")
    data = status_resp.get("data") or {}
    if not is_filled(status_resp):
        raise ResponseError(
            f"order not filled (order_status={data.get('order_status')!r})",
            status_resp,
        )
    price = data.get("average_price")
    if price in (None, 0, "0", ""):
        raise ResponseError("average_price missing in filled order", status_resp)
    return float(price)


def filled_quantity(status_resp: dict[str, Any]) -> int:
    ensure_success(status_resp, "orderstatus")
    data = status_resp.get("data") or {}
    if not is_filled(status_resp):
        return 0
    return int(data.get("quantity") or 0)


def poll_until_filled(
    client: Any,
    *,
    order_id: str,
    strategy: str,
    interval_sec: float = 0.5,
    timeout_sec: float = 60.0,
) -> dict[str, Any]:
    """Block until the order is filled, terminal, or `timeout_sec` elapses.

    Returns the final `orderstatus` response. Raises `ResponseError` if
    the order rejected or cancelled. Returns the last response (which
    may still be open) on timeout — caller decides what to do.
    """
    deadline = time.monotonic() + timeout_sec
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = client.orderstatus(order_id=order_id, strategy=strategy)
        if is_filled(last):
            return last
        if is_terminal(last):
            raise ResponseError(
                f"order terminal but not filled: {(last.get('data') or {}).get('order_status')!r}",
                last,
            )
        time.sleep(interval_sec)
    return last  # timed out, still open


# ---- market data ----------------------------------------------------------


def extract_ltp(quote_resp: dict[str, Any]) -> float:
    """Pull ltp from a `quotes` response."""
    ensure_success(quote_resp, "quotes")
    data = quote_resp.get("data") or {}
    ltp = data.get("ltp")
    if ltp is None:
        raise ResponseError("ltp missing in quotes response", quote_resp)
    return float(ltp)


def extract_ohlc(quote_resp: dict[str, Any]) -> dict[str, float]:
    ensure_success(quote_resp, "quotes")
    data = quote_resp.get("data") or {}
    return {k: float(data[k]) for k in ("open", "high", "low", "ltp") if k in data}


def extract_touch(depth_resp: dict[str, Any]) -> dict[str, float]:
    """Best bid and best ask from a `depth` response."""
    ensure_success(depth_resp, "depth")
    data = depth_resp.get("data") or {}
    bids = data.get("bids") or []
    asks = data.get("asks") or []
    if not bids or not asks:
        raise ResponseError("depth response missing bids/asks", depth_resp)
    return {
        "best_bid": float(bids[0]["price"]),
        "best_ask": float(asks[0]["price"]),
        "spread":   float(asks[0]["price"]) - float(bids[0]["price"]),
        "ltp":      float(data.get("ltp") or 0),
    }


# ---- options --------------------------------------------------------------


def atm_strike_from_chain(chain_resp: dict[str, Any]) -> float:
    ensure_success(chain_resp, "optionchain")
    atm = chain_resp.get("atm_strike")
    if atm is None:
        raise ResponseError("atm_strike missing in optionchain response", chain_resp)
    return float(atm)


def underlying_ltp(chain_resp: dict[str, Any]) -> float:
    ensure_success(chain_resp, "optionchain")
    ltp = chain_resp.get("underlying_ltp")
    if ltp is None:
        raise ResponseError("underlying_ltp missing in optionchain", chain_resp)
    return float(ltp)


def find_strike_row(chain_resp: dict[str, Any], strike: float) -> dict[str, Any]:
    """Return the chain[] entry for a specific strike, or raise."""
    ensure_success(chain_resp, "optionchain")
    for entry in chain_resp.get("chain", []):
        if float(entry["strike"]) == float(strike):
            return entry
    raise ResponseError(f"strike {strike} not in chain", chain_resp)


def find_offset_symbol(option_sym_resp: dict[str, Any]) -> str:
    """Return the resolved symbol from an `optionsymbol` response."""
    ensure_success(option_sym_resp, "optionsymbol")
    sym = option_sym_resp.get("symbol")
    if not sym:
        raise ResponseError("symbol missing in optionsymbol response", option_sym_resp)
    return str(sym)


# ---- account --------------------------------------------------------------


def available_cash(funds_resp: dict[str, Any]) -> float:
    ensure_success(funds_resp, "funds")
    data = funds_resp.get("data") or {}
    return float(data.get("availablecash") or 0)


def total_margin_required(margin_resp: dict[str, Any]) -> float:
    ensure_success(margin_resp, "margin")
    data = margin_resp.get("data") or {}
    return float(data.get("total_margin_required") or 0)


def open_position_qty(open_pos_resp: dict[str, Any]) -> int:
    """Signed quantity (-ve = short, +ve = long). 0 if no position."""
    if str(open_pos_resp.get("status", "")).lower() != "success":
        return 0
    return int(open_pos_resp.get("quantity") or 0)


# ---- multiquotes ----------------------------------------------------------


def multiquotes_to_dict(mq_resp: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Flatten `multiquotes` into {symbol_at_exchange: data}."""
    ensure_success(mq_resp, "multiquotes")
    out: dict[str, dict[str, Any]] = {}
    for item in mq_resp.get("results", []):
        key = f"{item.get('symbol')}@{item.get('exchange')}"
        out[key] = item.get("data") or {}
    return out
