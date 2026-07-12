import tempfile
import unittest
from contextlib import closing
from pathlib import Path
import sqlite3

from execution_agent.broker_adapter import SandboxOrderRequest, SandboxOrderResult
from execution_agent.sandbox_ledger import SandboxLedger


def sample_request() -> SandboxOrderRequest:
    return SandboxOrderRequest(
        call_key="TWSE:3094:2026-07-08:base:-",
        market="TWSE",
        stock_no="3094",
        stock_name="聯傑",
        signal_date="2026-07-08",
        open_price=41.35,
        entry_limit_price=41.65,
        cash_budget=100000,
        quantity=2000,
        price=41.35,
        order_type="sandbox_buy_open",
    )


def accepted_result(request: SandboxOrderRequest) -> SandboxOrderResult:
    return SandboxOrderResult(
        call_key=request.call_key,
        accepted=True,
        broker_order_id="sandbox-1",
        submitted_at="2026-07-10T09:00:00+08:00",
        message="submitted",
        status="Submitted",
        filled_quantity=0,
        average_fill_price=None,
    )


def filled_result(request: SandboxOrderRequest) -> SandboxOrderResult:
    return SandboxOrderResult(
        call_key=request.call_key,
        accepted=True,
        broker_order_id="sandbox-1",
        submitted_at="2026-07-10T09:00:00+08:00",
        message="filled",
        status="Filled",
        filled_quantity=2000,
        average_fill_price=41.3,
    )


class SandboxLedgerTests(unittest.TestCase):
    def test_submitted_order_does_not_create_position_before_fill(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = SandboxLedger(str(Path(tmpdir) / "sandbox.db"))
            request = sample_request()

            ledger.record_order(request, accepted_result(request))

            self.assertTrue(ledger.has_order(request.call_key))
            self.assertEqual(len(ledger.list_orders()), 1)
            self.assertEqual(ledger.list_positions(), [])

    def test_filled_order_creates_position_from_actual_fill(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = SandboxLedger(str(Path(tmpdir) / "sandbox.db"))
            request = sample_request()

            ledger.record_order(request, filled_result(request))

            order = ledger.list_orders()[0]
            position = ledger.list_positions()[0]
            self.assertEqual(order["status"], "Filled")
            self.assertEqual(order["filled_quantity"], 2000)
            self.assertEqual(position["quantity"], 2000)
            self.assertEqual(position["entry_price"], 41.3)

    def test_later_fill_reconciles_existing_partial_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = SandboxLedger(str(Path(tmpdir) / "sandbox.db"))
            request = sample_request()
            partial = SandboxOrderResult(
                call_key=request.call_key,
                accepted=True,
                broker_order_id="sandbox-1",
                submitted_at="2026-07-10T09:00:00+08:00",
                message="part filled",
                status="PartFilled",
                filled_quantity=1000,
                average_fill_price=41.2,
            )

            ledger.record_order(request, partial)
            ledger.record_order(request, filled_result(request))

            positions = ledger.list_positions()
            self.assertEqual(len(positions), 1)
            self.assertEqual(positions[0]["quantity"], 2000)
            self.assertEqual(positions[0]["entry_price"], 41.3)

    def test_migration_removes_legacy_accepted_but_unfilled_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "sandbox.db")
            with closing(sqlite3.connect(db_path)) as conn:
                with conn:
                    conn.executescript(
                        """
                    CREATE TABLE sandbox_orders (
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
                        created_at TEXT NOT NULL
                    );
                    CREATE TABLE sandbox_positions (
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
                    INSERT INTO sandbox_orders VALUES (
                        1, 'legacy-key', 'TWSE', '3094', 'test', '2026-07-08',
                        41.35, 41.65, 100000, 2000, 41.35, 'sandbox_buy_open',
                        'legacy-order', 'accepted', 'accepted', '2026-07-10T09:00:00+08:00'
                    );
                    INSERT INTO sandbox_positions VALUES (
                        1, 'legacy-key', 'TWSE', '3094', 'test', '2026-07-08',
                        41.35, 2000, 'open', '2026-07-10T09:00:00+08:00',
                        '2026-07-10T09:00:00+08:00'
                    );
                        """
                    )

            ledger = SandboxLedger(db_path)

            self.assertEqual(ledger.list_positions(), [])
            order = ledger.list_orders()[0]
            self.assertEqual(order["filled_quantity"], 0)

    def test_record_event_does_not_create_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = SandboxLedger(str(Path(tmpdir) / "sandbox.db"))

            ledger.record_event("key-1", "broker_error", "submit failed")

            self.assertEqual(len(ledger.list_events()), 1)
            self.assertEqual(ledger.list_positions(), [])
