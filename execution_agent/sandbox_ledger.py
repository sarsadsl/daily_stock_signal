from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import sqlite3
from typing import Any, Iterator

from execution_agent.broker_adapter import SandboxOrderRequest, SandboxOrderResult


class SandboxLedger:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        parent = Path(db_path).parent
        if str(parent) and str(parent) != ".":
            parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def has_order(self, call_key: str) -> bool:
        return self.get_order(call_key) is not None

    def get_order(self, call_key: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sandbox_orders WHERE call_key = ? LIMIT 1",
                (call_key,),
            ).fetchone()
        return dict(row) if row is not None else None

    @staticmethod
    def order_needs_reconciliation(order: dict[str, Any]) -> bool:
        return str(order.get("status") or "").casefold() in {
            "pendingsubmit",
            "presubmitted",
            "submitted",
            "partfilled",
            "filling",
        }

    def record_order(self, request: SandboxOrderRequest, result: SandboxOrderResult) -> None:
        created_at = _now_iso()
        status = result.status or ("accepted" if result.accepted else "rejected")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sandbox_orders (
                    call_key, market, stock_no, stock_name, signal_date,
                    open_price, entry_limit_price, cash_budget, quantity, price,
                    order_type, broker_order_id, status, message, filled_quantity,
                    filled_price, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(call_key) DO UPDATE SET
                    broker_order_id = excluded.broker_order_id,
                    status = excluded.status,
                    message = excluded.message,
                    filled_quantity = excluded.filled_quantity,
                    filled_price = excluded.filled_price
                """,
                (
                    request.call_key,
                    request.market,
                    request.stock_no,
                    request.stock_name,
                    request.signal_date,
                    request.open_price,
                    request.entry_limit_price,
                    request.cash_budget,
                    request.quantity,
                    request.price,
                    request.order_type,
                    result.broker_order_id,
                    status,
                    result.message,
                    result.filled_quantity,
                    result.average_fill_price,
                    created_at,
                ),
            )
            if result.filled_quantity > 0:
                conn.execute(
                    """
                    INSERT INTO sandbox_positions (
                        call_key, market, stock_no, stock_name, entry_date,
                        entry_price, quantity, status, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(call_key) DO UPDATE SET
                        entry_price = excluded.entry_price,
                        quantity = excluded.quantity,
                        status = excluded.status,
                        updated_at = excluded.updated_at
                    """,
                    (
                        request.call_key,
                        request.market,
                        request.stock_no,
                        request.stock_name,
                        request.signal_date,
                        result.average_fill_price or request.price,
                        result.filled_quantity,
                        "open",
                        created_at,
                        created_at,
                    ),
                )

    def record_event(self, call_key: str, event_type: str, message: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sandbox_events (call_key, event_type, message, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (call_key, event_type, message, _now_iso()),
            )

    def list_orders(self) -> list[dict[str, Any]]:
        return self._list_table("sandbox_orders")

    def list_positions(self) -> list[dict[str, Any]]:
        return self._list_table("sandbox_positions")

    def list_events(self) -> list[dict[str, Any]]:
        return self._list_table("sandbox_events")

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sandbox_orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    call_key TEXT NOT NULL UNIQUE,
                    market TEXT NOT NULL,
                    stock_no TEXT NOT NULL,
                    stock_name TEXT NOT NULL,
                    signal_date TEXT NOT NULL,
                    open_price REAL NOT NULL,
                    entry_limit_price REAL NOT NULL,
                    cash_budget REAL NOT NULL,
                    quantity INTEGER NOT NULL,
                    price REAL NOT NULL,
                    order_type TEXT NOT NULL,
                    broker_order_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT NOT NULL,
                    filled_quantity INTEGER NOT NULL DEFAULT 0,
                    filled_price REAL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sandbox_positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    call_key TEXT NOT NULL UNIQUE,
                    market TEXT NOT NULL,
                    stock_no TEXT NOT NULL,
                    stock_name TEXT NOT NULL,
                    entry_date TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    quantity INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sandbox_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    call_key TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            self._ensure_column(conn, "sandbox_orders", "filled_quantity", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "sandbox_orders", "filled_price", "REAL")
            conn.execute(
                """
                DELETE FROM sandbox_positions
                WHERE call_key IN (
                    SELECT call_key
                    FROM sandbox_orders
                    WHERE filled_quantity = 0
                )
                """
            )

    @staticmethod
    def _ensure_column(
        conn: sqlite3.Connection,
        table_name: str,
        column_name: str,
        definition: str,
    ) -> None:
        columns = {
            str(row[1])
            for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name not in columns:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _list_table(self, table_name: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(f"SELECT * FROM {table_name} ORDER BY id").fetchall()
        return [dict(row) for row in rows]


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat()
