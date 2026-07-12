import tempfile
import unittest
from pathlib import Path

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
        quantity=2418,
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

    def test_record_event_does_not_create_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = SandboxLedger(str(Path(tmpdir) / "sandbox.db"))

            ledger.record_event("key-1", "broker_error", "submit failed")

            self.assertEqual(len(ledger.list_events()), 1)
            self.assertEqual(ledger.list_positions(), [])
