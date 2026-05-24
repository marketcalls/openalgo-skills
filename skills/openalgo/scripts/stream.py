"""High-level WebSocket helpers.

The raw SDK calls (`client.connect`, `client.subscribe_*`,
`client.unsubscribe_*`, `client.disconnect`) are easy to forget to pair
in finally blocks. `subscribe()` is a context manager that does the
right thing on KeyboardInterrupt, exceptions, and clean exits.

`CallbackRouter` lets a single subscription dispatch to different
handlers per symbol — useful when the same stream feeds a logger, an
alert, and a strategy state machine without writing three sub-streams.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from typing import Any, Literal

Mode = Literal["ltp", "quote", "depth"]
TickHandler = Callable[[dict[str, Any]], None]


@contextmanager
def subscribe(
    client: Any,
    instruments: list[dict[str, str]],
    mode: Mode,
    on_data: TickHandler,
    *,
    depth_level: int | None = None,
):
    """Context manager: connect, subscribe, yield, unsubscribe, disconnect.

    Usage:
        with subscribe(client, [{"exchange": "NSE", "symbol": "RELIANCE"}],
                       mode="ltp", on_data=print):
            time.sleep(60)
    """
    if mode not in {"ltp", "quote", "depth"}:
        raise ValueError(f"mode must be ltp/quote/depth, got {mode!r}")

    client.connect()
    try:
        if mode == "ltp":
            client.subscribe_ltp(instruments, on_data_received=on_data)
        elif mode == "quote":
            client.subscribe_quote(instruments, on_data_received=on_data)
        else:
            kwargs = {"on_data_received": on_data}
            if depth_level is not None:
                kwargs["depth_level"] = depth_level
            client.subscribe_depth(instruments, **kwargs)
        yield
    finally:
        try:
            if mode == "ltp":
                client.unsubscribe_ltp(instruments)
            elif mode == "quote":
                client.unsubscribe_quote(instruments)
            else:
                client.unsubscribe_depth(instruments)
        except Exception:
            pass
        try:
            client.disconnect()
        except Exception:
            pass


def run_until_interrupt(
    client: Any,
    instruments: list[dict[str, str]],
    mode: Mode,
    on_data: TickHandler,
    *,
    depth_level: int | None = None,
    heartbeat_sec: float = 30.0,
) -> None:
    """Subscribe and block until Ctrl-C.

    Prints a one-line heartbeat every `heartbeat_sec` so an idle stream
    is visibly alive (some brokers go quiet for minutes between ticks).
    """
    last_beat = time.monotonic()
    with subscribe(client, instruments, mode, on_data, depth_level=depth_level):
        try:
            while True:
                time.sleep(1)
                now = time.monotonic()
                if now - last_beat >= heartbeat_sec:
                    print(f"[stream] heartbeat  mode={mode}  ts={time.strftime('%H:%M:%S')}")
                    last_beat = now
        except KeyboardInterrupt:
            print("\n[stream] stopping (Ctrl-C)")


class CallbackRouter:
    """Fan-out per-symbol callbacks plus an optional catch-all.

    register("RELIANCE", lambda tick: ...) — fires only for RELIANCE
    register_all(lambda tick: ...) — fires on every tick

    `handle()` is the function to pass into `subscribe(on_data=...)`.
    Catches and logs exceptions in user callbacks so one buggy handler
    does not silently take down the rest of the stream.
    """

    def __init__(self) -> None:
        self._per_symbol: dict[str, list[TickHandler]] = {}
        self._all: list[TickHandler] = []
        self._lock = threading.Lock()

    def register(self, symbol: str, fn: TickHandler) -> None:
        with self._lock:
            self._per_symbol.setdefault(symbol.upper(), []).append(fn)

    def register_all(self, fn: TickHandler) -> None:
        with self._lock:
            self._all.append(fn)

    def handle(self, tick: dict[str, Any]) -> None:
        sym = str(tick.get("data", {}).get("symbol", "")).upper()
        with self._lock:
            handlers = list(self._all) + list(self._per_symbol.get(sym, ()))
        for fn in handlers:
            try:
                fn(tick)
            except Exception as exc:
                print(f"[router] handler error for {sym}: {exc!r}")


def reconnect_loop(
    client_factory: Callable[[], Any],
    instruments: list[dict[str, str]],
    mode: Mode,
    on_data: TickHandler,
    *,
    depth_level: int | None = None,
    max_retries: int = 100,
    backoff_sec: Iterable[float] = (1, 2, 5, 10, 30),
) -> None:
    """Persistent stream — re-creates client and resubscribes on any error.

    `client_factory` is a zero-arg callable that returns a fresh client
    (so a token refresh can be wired into it). Backoff cycles through
    the given sequence, holding at the last value once exhausted.

    Stops after `max_retries` consecutive failures, or on Ctrl-C.
    """
    backoffs = list(backoff_sec)
    failures = 0
    while failures < max_retries:
        client = client_factory()
        try:
            run_until_interrupt(
                client, instruments, mode, on_data, depth_level=depth_level
            )
            return  # clean exit (Ctrl-C inside run_until_interrupt)
        except KeyboardInterrupt:
            return
        except Exception as exc:
            failures += 1
            wait = backoffs[min(failures - 1, len(backoffs) - 1)]
            print(f"[stream] error {exc!r}; retry {failures}/{max_retries} in {wait}s")
            time.sleep(wait)
    print(f"[stream] giving up after {max_retries} failures")
