from __future__ import annotations

import sqlite3

from execution_agent.open_entry_core import OpenEntryDecision


class SQLiteStateStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                create table if not exists open_entry_calls (
                    call_key text primary key,
                    market text not null,
                    stock_no text not null,
                    signal_date text not null,
                    result text not null,
                    entry_limit_price real not null,
                    open_price real not null,
                    created_at text not null default current_timestamp
                )
                """
            )

    def has_processed(self, call_key: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("select 1 from open_entry_calls where call_key = ?", (call_key,)).fetchone()
        return row is not None

    def record_decision(self, decision: OpenEntryDecision) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert or ignore into open_entry_calls
                (call_key, market, stock_no, signal_date, result, entry_limit_price, open_price)
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision.call_key,
                    decision.market,
                    decision.stock_no,
                    decision.signal_date,
                    decision.result,
                    decision.entry_limit_price,
                    decision.open_price,
                ),
            )
