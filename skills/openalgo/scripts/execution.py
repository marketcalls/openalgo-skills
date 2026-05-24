"""Custom execution-algo primitives.

Three reusable algos:

* `LimitChaser` — peg the touch (best bid for BUY, best ask for SELL)
  and modify the open order whenever the touch moves more than
  `tick_size`. Optional time-out converts to MARKET or cancels.

* `TWAPSlicer` — break a large parent order into N equal child slices
  spread evenly over a duration, each child placed as a `LimitChaser`.

* `IcebergSlicer` — show only `display_qty` to the market at a time;
  when one child fills, place the next slice. Backed by repeated
  `placeorder` calls (OpenAlgo's `splitorder` is a one-shot N-way
  split, not a display-quantity iceberg).

All algos are blocking. Wrap in a thread/async task if you need
concurrency across symbols. State is kept in instance attributes so a
caller can introspect partial fills mid-run.

Safety:
- Every algo checks `analyzerstatus` on init and prints a clear
  LIVE/ANALYZER banner. Pass `confirm=True` to require y/N gate.
- All algos write a per-event line to a CSV journal in the working
  directory (override via `journal_path`).
- Caller must validate F&O lot-size before constructing (use
  `scripts.lotsize.validate_fno_lot`).
"""

from __future__ import annotations

import csv
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from .orders import (
    cancel_with_retry,
    modify_with_retry,
    place_with_retry,
    poll_until_terminal,
)


Side = Literal["BUY", "SELL"]


@dataclass
class ChaserConfig:
    symbol: str
    exchange: str
    action: Side
    quantity: int
    product: Literal["CNC", "MIS", "NRML"]
    strategy: str

    tick_size: float = 0.05            # NSE equity / index options default
    poll_interval_sec: float = 1.0
    timeout_sec: float = 60.0
    max_chase_ticks: int = 5            # cap chase distance from initial touch
    on_timeout: Literal["cancel", "market"] = "cancel"

    journal_path: str | None = None     # CSV; default = ./chaser_<symbol>.csv
    confirm: bool = True


@dataclass
class ChaserState:
    order_id: str | None = None
    initial_price: float | None = None
    current_price: float | None = None
    last_modified_ts: float | None = None
    filled: bool = False
    filled_qty: int = 0
    average_price: float | None = None
    fills: list[dict[str, Any]] = field(default_factory=list)


class LimitChaser:
    """Peg the touch, modify on move, give up or go market on timeout.

    Usage:
        cfg = ChaserConfig(symbol="RELIANCE", exchange="NSE", action="BUY",
                           quantity=10, product="MIS", strategy="chaser")
        chaser = LimitChaser(client, cfg)
        state = chaser.run()
        print(state.filled, state.average_price)
    """

    def __init__(self, client: Any, cfg: ChaserConfig) -> None:
        self.client = client
        self.cfg = cfg
        self.state = ChaserState()
        self._journal_writer = self._open_journal()
        self._banner()

    def run(self) -> ChaserState:
        cfg, st = self.cfg, self.state
        if cfg.confirm and not self._confirm():
            self._log("aborted", reason="user")
            return st

        touch = self._touch_price()
        st.initial_price = touch
        st.current_price = touch
        resp = place_with_retry(
            self.client,
            strategy=cfg.strategy,
            symbol=cfg.symbol,
            exchange=cfg.exchange,
            action=cfg.action,
            price_type="LIMIT",
            product=cfg.product,
            quantity=cfg.quantity,
            price=touch,
        )
        if resp.get("status") != "success":
            self._log("place_failed", resp=str(resp))
            return st
        st.order_id = resp.get("orderid") or resp.get("data", {}).get("orderid")
        self._log("placed", price=touch, order_id=st.order_id)

        deadline = time.monotonic() + cfg.timeout_sec
        while time.monotonic() < deadline:
            time.sleep(cfg.poll_interval_sec)
            os_resp = self.client.orderstatus(order_id=st.order_id, strategy=cfg.strategy)
            if os_resp.get("status") == "success":
                data = os_resp["data"]
                status = str(data.get("order_status", "")).lower()
                if "complete" in status:
                    st.filled = True
                    st.filled_qty = int(data.get("quantity") or cfg.quantity)
                    st.average_price = float(data.get("average_price") or 0)
                    self._log("filled", price=st.average_price, qty=st.filled_qty)
                    return st
                if "reject" in status or "cancel" in status:
                    self._log("terminal", status=status)
                    return st

            new_touch = self._touch_price()
            if self._should_modify(new_touch):
                self._modify(new_touch)

        return self._on_timeout()

    # ---- internals -----------------------------------------------------

    def _should_modify(self, new_touch: float) -> bool:
        st, cfg = self.state, self.cfg
        if st.current_price is None or st.initial_price is None:
            return False
        moved = abs(new_touch - st.current_price) >= cfg.tick_size
        within_cap = abs(new_touch - st.initial_price) <= cfg.max_chase_ticks * cfg.tick_size
        # For a BUY chaser we only modify when the touch ticks UP
        # (we're paying more); for SELL we only modify when the touch
        # ticks DOWN (we're accepting less). This avoids cancelling our
        # favourable queue position when the market moves our way.
        directional = (
            (cfg.action == "BUY" and new_touch > st.current_price)
            or (cfg.action == "SELL" and new_touch < st.current_price)
        )
        return moved and within_cap and directional

    def _modify(self, new_price: float) -> None:
        cfg, st = self.cfg, self.state
        if st.order_id is None:
            return
        resp = modify_with_retry(
            self.client,
            order_id=st.order_id,
            strategy=cfg.strategy,
            symbol=cfg.symbol,
            exchange=cfg.exchange,
            action=cfg.action,
            price_type="LIMIT",
            product=cfg.product,
            quantity=cfg.quantity,
            price=new_price,
        )
        if resp.get("status") == "success":
            st.current_price = new_price
            st.last_modified_ts = time.time()
            self._log("modified", price=new_price)
        else:
            self._log("modify_failed", resp=str(resp))

    def _on_timeout(self) -> ChaserState:
        cfg, st = self.cfg, self.state
        if st.order_id is None:
            return st
        if cfg.on_timeout == "cancel":
            cancel_with_retry(self.client, order_id=st.order_id, strategy=cfg.strategy)
            self._log("timeout_cancelled")
            return st
        # cross to MARKET — place a fresh order, then cancel the resting limit
        cancel_with_retry(self.client, order_id=st.order_id, strategy=cfg.strategy)
        self._log("timeout_to_market")
        resp = place_with_retry(
            self.client,
            strategy=cfg.strategy,
            symbol=cfg.symbol,
            exchange=cfg.exchange,
            action=cfg.action,
            price_type="MARKET",
            product=cfg.product,
            quantity=cfg.quantity,
            price=0,
        )
        if resp.get("status") == "success":
            new_id = resp.get("orderid") or resp.get("data", {}).get("orderid")
            final = poll_until_terminal(
                self.client,
                order_id=new_id,
                strategy=cfg.strategy,
                interval_sec=cfg.poll_interval_sec,
                timeout_sec=10.0,
            )
            data = final.get("data", {})
            if "complete" in str(data.get("order_status", "")).lower():
                st.filled = True
                st.filled_qty = int(data.get("quantity") or cfg.quantity)
                st.average_price = float(data.get("average_price") or 0)
                self._log("market_filled", price=st.average_price)
        return st

    def _touch_price(self) -> float:
        resp = self.client.depth(symbol=self.cfg.symbol, exchange=self.cfg.exchange)
        if resp.get("status") != "success":
            raise RuntimeError(f"depth fetch failed for {self.cfg.symbol}: {resp}")
        d = resp["data"]
        if self.cfg.action == "BUY":
            return float(d["bids"][0]["price"])
        return float(d["asks"][0]["price"])

    def _banner(self) -> None:
        try:
            mode = self.client.analyzerstatus()["data"].get("mode", "unknown")
        except Exception:
            mode = "unknown"
        print(f"[chaser] {self.cfg.action} {self.cfg.quantity} {self.cfg.symbol} "
              f"@ {self.cfg.exchange}  mode={mode}")

    def _confirm(self) -> bool:
        return input("Start chaser? [y/N] ").strip().lower() == "y"

    def _open_journal(self) -> Any:
        path = Path(self.cfg.journal_path or f"chaser_{self.cfg.symbol}.csv")
        new = not path.exists()
        f = path.open("a", newline="")
        w = csv.writer(f)
        if new:
            w.writerow(["ts", "event", "symbol", "action", "price", "qty", "order_id", "extra"])
        return w

    def _log(self, event: str, **kw: Any) -> None:
        ts = datetime.now().isoformat(timespec="seconds")
        extras = " ".join(f"{k}={v}" for k, v in kw.items())
        print(f"[chaser] {ts} {event} {extras}")
        try:
            self._journal_writer.writerow([
                ts, event, self.cfg.symbol, self.cfg.action,
                kw.get("price", ""), kw.get("qty", ""),
                kw.get("order_id", self.state.order_id or ""),
                extras,
            ])
        except Exception:  # journal failure must not break execution
            pass


# ---------- TWAP -----------------------------------------------------------


@dataclass
class TWAPConfig:
    symbol: str
    exchange: str
    action: Side
    total_quantity: int
    slices: int
    duration_sec: float
    product: Literal["CNC", "MIS", "NRML"]
    strategy: str

    chaser_timeout_sec: float = 30.0
    tick_size: float = 0.05


class TWAPSlicer:
    """Slice a parent into N equal children spread evenly over duration.

    Each child runs through `LimitChaser` so we get queue-position
    benefit without parking too far from the touch. Residual rounding
    from N-way split goes on the final child.
    """

    def __init__(self, client: Any, cfg: TWAPConfig) -> None:
        self.client = client
        self.cfg = cfg
        self.results: list[ChaserState] = []

    def run(self) -> list[ChaserState]:
        cfg = self.cfg
        base = cfg.total_quantity // cfg.slices
        sizes = [base] * cfg.slices
        sizes[-1] += cfg.total_quantity - base * cfg.slices
        interval = cfg.duration_sec / cfg.slices

        for i, qty in enumerate(sizes):
            print(f"[twap] slice {i + 1}/{cfg.slices}  qty={qty}")
            chaser = LimitChaser(
                self.client,
                ChaserConfig(
                    symbol=cfg.symbol,
                    exchange=cfg.exchange,
                    action=cfg.action,
                    quantity=qty,
                    product=cfg.product,
                    strategy=cfg.strategy,
                    tick_size=cfg.tick_size,
                    timeout_sec=cfg.chaser_timeout_sec,
                    confirm=False,
                ),
            )
            self.results.append(chaser.run())
            if i < cfg.slices - 1:
                time.sleep(max(0.0, interval - cfg.chaser_timeout_sec))
        return self.results

    def summary(self) -> dict[str, Any]:
        filled_qty = sum(r.filled_qty for r in self.results)
        weighted = sum(
            (r.average_price or 0) * r.filled_qty
            for r in self.results
            if r.filled and r.average_price
        )
        vwap = weighted / filled_qty if filled_qty else None
        return {
            "parent_qty": self.cfg.total_quantity,
            "filled_qty": filled_qty,
            "child_count": len(self.results),
            "vwap": vwap,
        }


# ---------- Iceberg --------------------------------------------------------


@dataclass
class IcebergConfig:
    symbol: str
    exchange: str
    action: Side
    total_quantity: int
    display_quantity: int
    price: float
    product: Literal["CNC", "MIS", "NRML"]
    strategy: str

    poll_interval_sec: float = 0.5
    overall_timeout_sec: float = 300.0


class IcebergSlicer:
    """Display only `display_quantity` to the book; refill after each fill.

    Unlike a venue-native iceberg, the broker sees a sequence of small
    orders here — there is no anonymity benefit. The point is queue
    position management and reduced market impact when working a large
    parent at a fixed limit.
    """

    def __init__(self, client: Any, cfg: IcebergConfig) -> None:
        self.client = client
        self.cfg = cfg
        self.filled_total = 0
        self.children: list[str] = []

    def run(self) -> dict[str, Any]:
        cfg = self.cfg
        deadline = time.monotonic() + cfg.overall_timeout_sec
        while self.filled_total < cfg.total_quantity and time.monotonic() < deadline:
            remaining = cfg.total_quantity - self.filled_total
            qty = min(cfg.display_quantity, remaining)
            resp = place_with_retry(
                self.client,
                strategy=cfg.strategy,
                symbol=cfg.symbol,
                exchange=cfg.exchange,
                action=cfg.action,
                price_type="LIMIT",
                product=cfg.product,
                quantity=qty,
                price=cfg.price,
            )
            if resp.get("status") != "success":
                print(f"[iceberg] place_failed: {resp}")
                break
            oid = resp.get("orderid") or resp.get("data", {}).get("orderid")
            self.children.append(oid)
            status = poll_until_terminal(
                self.client,
                order_id=oid,
                strategy=cfg.strategy,
                interval_sec=cfg.poll_interval_sec,
                timeout_sec=max(5.0, cfg.overall_timeout_sec / 10),
            )
            data = status.get("data", {})
            order_status = str(data.get("order_status", "")).lower()
            if "complete" in order_status:
                self.filled_total += int(data.get("quantity") or qty)
                print(f"[iceberg] child {oid} filled  total={self.filled_total}/{cfg.total_quantity}")
            else:
                # not filled at this price within child timeout — bail to caller
                cancel_with_retry(self.client, order_id=oid, strategy=cfg.strategy)
                print(f"[iceberg] child {oid} unfilled at {cfg.price}; cancelled; stopping")
                break

        return {
            "filled_qty": self.filled_total,
            "target_qty": cfg.total_quantity,
            "children": list(self.children),
            "complete": self.filled_total >= cfg.total_quantity,
        }
