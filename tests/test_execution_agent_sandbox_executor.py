import tempfile
import unittest
from pathlib import Path

from execution_agent.broker_adapter import SandboxOrderResult
from execution_agent.broker_config import BrokerConfig
from execution_agent.open_entry_core import build_open_entry_decision
from execution_agent.sandbox_executor import execute_sandbox_orders
from execution_agent.sandbox_ledger import SandboxLedger
from execution_agent.tracking_source import PendingOpenEntry


class FakeBroker:
    def __init__(self, accepted: bool = True) -> None:
        self.accepted = accepted
        self.requests = []

    def submit_buy_order(self, request):
        self.requests.append(request)
        return SandboxOrderResult(
            call_key=request.call_key,
            accepted=self.accepted,
            broker_order_id=f"fake-{len(self.requests)}",
            submitted_at="2026-07-10T09:00:00+08:00",
            message="accepted" if self.accepted else "rejected",
            status="Filled" if self.accepted else "Failed",
            filled_quantity=request.quantity if self.accepted else 0,
            average_fill_price=request.price if self.accepted else None,
        )

    def refresh_buy_order(self, request, broker_order_id):
        raise AssertionError("filled fake orders should not be reconciled")


class PendingThenFilledBroker:
    def __init__(self) -> None:
        self.submitted = []
        self.refreshed = []

    def submit_buy_order(self, request):
        self.submitted.append(request)
        return SandboxOrderResult(
            call_key=request.call_key,
            accepted=True,
            broker_order_id="pending-1",
            submitted_at="2026-07-10T09:00:00+08:00",
            message="submitted",
            status="Submitted",
        )

    def refresh_buy_order(self, request, broker_order_id):
        self.refreshed.append((request, broker_order_id))
        return SandboxOrderResult(
            call_key=request.call_key,
            accepted=True,
            broker_order_id=broker_order_id,
            submitted_at="2026-07-10T09:01:00+08:00",
            message="filled",
            status="Filled",
            filled_quantity=request.quantity,
            average_fill_price=request.price,
        )


def decision(stock_no="3094", open_price=41.35, limit=41.65):
    entry = PendingOpenEntry(
        market="TWSE",
        stock_no=stock_no,
        stock_name="聯傑",
        signal_date="2026-07-08",
        entry_limit_price=limit,
        signal_close=42.5,
        unit_type="base",
        addon_number=None,
    )
    return build_open_entry_decision(entry, open_price=open_price)


class SandboxExecutorTests(unittest.TestCase):
    def sandbox_config(self) -> BrokerConfig:
        return BrokerConfig.from_env(
            {
                "BROKER_MODE": "sandbox",
                "SANDBOX_ONLY": "1",
                "SHIOAJI_API_KEY": "key",
                "SHIOAJI_SECRET_KEY": "secret",
            }
        )

    def test_submits_only_called_decisions_and_records_positions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = SandboxLedger(str(Path(tmpdir) / "sandbox.db"))
            broker = FakeBroker()
            called = decision()
            failed = decision(stock_no="3090", open_price=300, limit=297.43)

            summary = execute_sandbox_orders(
                [called, failed],
                config=self.sandbox_config(),
                ledger=ledger,
                broker=broker,
            )

            self.assertEqual(summary.submitted, 1)
            self.assertEqual(summary.skipped_non_called, 1)
            self.assertEqual(len(broker.requests), 1)
            self.assertEqual(len(ledger.list_orders()), 1)
            self.assertEqual(len(ledger.list_positions()), 1)

    def test_duplicate_call_key_is_not_resubmitted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = SandboxLedger(str(Path(tmpdir) / "sandbox.db"))
            broker = FakeBroker()
            config = self.sandbox_config()

            execute_sandbox_orders([decision()], config=config, ledger=ledger, broker=broker)
            summary = execute_sandbox_orders([decision()], config=config, ledger=ledger, broker=broker)

            self.assertEqual(summary.skipped_duplicate, 1)
            self.assertEqual(len(broker.requests), 1)
            self.assertEqual(len(ledger.list_orders()), 1)

    def test_pending_order_is_reconciled_without_resubmission(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = SandboxLedger(str(Path(tmpdir) / "sandbox.db"))
            broker = PendingThenFilledBroker()
            config = self.sandbox_config()

            first = execute_sandbox_orders([decision()], config=config, ledger=ledger, broker=broker)
            second = execute_sandbox_orders([decision()], config=config, ledger=ledger, broker=broker)

            self.assertEqual(first.submitted, 1)
            self.assertEqual(second.reconciled, 1)
            self.assertEqual(len(broker.submitted), 1)
            self.assertEqual(len(broker.refreshed), 1)
            self.assertEqual(len(ledger.list_positions()), 1)
