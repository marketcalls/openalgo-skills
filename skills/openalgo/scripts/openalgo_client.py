"""OpenAlgo client bootstrap.

Loads credentials from the nearest `.env` (walks up from the calling
script's directory) and returns a ready-to-use `openalgo.api` instance.

Why this layer:
- Centralizes `.env` loading so every example stays identical.
- Lets tests inject a fake client by patching `get_client`.
- Validates that essential env vars are present, with actionable errors.
"""

from __future__ import annotations

import os
from typing import Any

from dotenv import find_dotenv, load_dotenv
from openalgo import api


_DEFAULT_HOST = "http://127.0.0.1:5000"
_DEFAULT_WS = "ws://127.0.0.1:8765"


def _load_env() -> None:
    path = find_dotenv(usecwd=True)
    if path:
        load_dotenv(path, override=False)


def get_client(
    *,
    api_key: str | None = None,
    host: str | None = None,
    ws_url: str | None = None,
    verbose: bool | int = False,
) -> Any:
    """Return an authenticated `openalgo.api` client.

    Resolution order for each setting:
        1. Explicit kwarg passed here
        2. Environment variable (OPENALGO_API_KEY / OPENALGO_HOST / OPENALGO_WS_URL)
        3. Built-in default (host=127.0.0.1:5000, ws=127.0.0.1:8765)

    `api_key` has no default — if neither kwarg nor env var is set we
    raise immediately rather than letting the SDK fail with a less
    helpful 401 later.
    """
    _load_env()

    resolved_key = api_key or os.environ.get("OPENALGO_API_KEY")
    if not resolved_key:
        raise RuntimeError(
            "OPENALGO_API_KEY is not set. Copy .env.sample to .env and "
            "fill in your key, or pass api_key=... explicitly."
        )

    resolved_host = host or os.environ.get("OPENALGO_HOST", _DEFAULT_HOST)
    resolved_ws = ws_url or os.environ.get("OPENALGO_WS_URL", _DEFAULT_WS)

    return api(
        api_key=resolved_key,
        host=resolved_host,
        ws_url=resolved_ws,
        verbose=verbose,
    )


def default_strategy_tag() -> str:
    """Read OPENALGO_DEFAULT_STRATEGY from env, fallback to 'python'.

    The `strategy` field appears on every order in the broker's order
    book and in OpenAlgo's analyzer logs — keep it stable per strategy
    so trades can be reconciled later.
    """
    _load_env()
    return os.environ.get("OPENALGO_DEFAULT_STRATEGY", "python")


def historify_duckdb_path() -> str | None:
    """Resolved Historify DuckDB path, or None if not configured.

    Used by `scripts/duckdb_data.py` for direct (non-REST) market-data
    access. Caller should fall back to `client.history(..., source='db')`
    when this returns None.
    """
    _load_env()
    return os.environ.get("HISTORIFY_DUCKDB_PATH")
