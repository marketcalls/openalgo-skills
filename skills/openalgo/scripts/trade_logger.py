"""Persistent trade journal.

Writes one row per significant trade event (place, modify, cancel,
fill) to a CSV file. Use the same file across runs to build a long-term
journal that downstream analytics scripts can read.

For higher-volume strategies prefer SQLite — `SqliteJournal` uses the
same surface API.
"""

from __future__ import annotations

import csv
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

_COLUMNS = [
    "ts", "strategy", "symbol", "exchange", "action",
    "event", "order_id", "price", "quantity", "average_price",
    "order_status", "tag", "extra",
]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class CsvJournal:
    """Append-only CSV journal. Thread-safe enough for one writer."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new_file = not self.path.exists()
        self._fh = self.path.open("a", newline="")
        self._w = csv.DictWriter(self._fh, fieldnames=_COLUMNS, extrasaction="ignore")
        if new_file:
            self._w.writeheader()

    def write(self, **fields: Any) -> None:
        row = {c: "" for c in _COLUMNS}
        row.update(fields)
        row["ts"] = row.get("ts") or _now()
        self._w.writerow(row)
        self._fh.flush()

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:
            pass

    def __enter__(self) -> "CsvJournal":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()


class SqliteJournal:
    """SQLite-backed journal — same .write() surface as CsvJournal."""

    _DDL = """
        CREATE TABLE IF NOT EXISTS trades (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            ts            TEXT NOT NULL,
            strategy      TEXT,
            symbol        TEXT,
            exchange      TEXT,
            action        TEXT,
            event         TEXT,
            order_id      TEXT,
            price         REAL,
            quantity      INTEGER,
            average_price REAL,
            order_status  TEXT,
            tag           TEXT,
            extra         TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_trades_ts ON trades(ts);
        CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy);
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.executescript(self._DDL)
        self.conn.commit()

    def write(self, **fields: Any) -> None:
        row = {c: fields.get(c) for c in _COLUMNS}
        row["ts"] = row["ts"] or _now()
        cols = ",".join(_COLUMNS)
        placeholders = ",".join("?" * len(_COLUMNS))
        self.conn.execute(
            f"INSERT INTO trades ({cols}) VALUES ({placeholders})",
            [row[c] for c in _COLUMNS],
        )
        self.conn.commit()

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

    def __enter__(self) -> "SqliteJournal":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()


def open_journal(path: str | Path) -> CsvJournal | SqliteJournal:
    """Pick the backend based on suffix: .db / .sqlite => SQLite, else CSV."""
    p = Path(path)
    if p.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
        return SqliteJournal(p)
    return CsvJournal(p)
