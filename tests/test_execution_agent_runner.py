import tempfile
import unittest

from execution_agent.runner import run_open_entry_cycle
from execution_agent.tracking_source import PendingOpenEntry


class FakeNotifier:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def send_open_entry_call(self, decision) -> bool:
        self.sent.append(decision.call_key)
        return True


class RunnerTests(unittest.TestCase):
    def test_run_open_entry_cycle_records_called_and_sends_notification(self) -> None:
        entries = [
            PendingOpenEntry(
                market="TWSE",
                stock_no="3094",
                stock_name="???",
                signal_date="2026-07-08",
                entry_limit_price=41.65,
                signal_close=42.5,
                unit_type="base",
                addon_number=None,
            )
        ]

        def quote_lookup(entry: PendingOpenEntry) -> float:
            self.assertEqual(entry.stock_no, "3094")
            return 41.35

        notifier = FakeNotifier()
        with tempfile.TemporaryDirectory() as tmpdir:
            decisions = run_open_entry_cycle(
                entries=entries,
                quote_lookup=quote_lookup,
                notifier=notifier,
                db_path=f"{tmpdir}/agent.db",
                dry_run=False,
            )

        self.assertEqual([item.result for item in decisions], ["called"])
        self.assertEqual(notifier.sent, ["TWSE:3094:2026-07-08:base:-"])

    def test_run_open_entry_cycle_dry_run_does_not_notify_or_record(self) -> None:
        entries = [
            PendingOpenEntry(
                market="TWSE",
                stock_no="3094",
                stock_name="???",
                signal_date="2026-07-08",
                entry_limit_price=41.65,
                signal_close=42.5,
                unit_type="base",
                addon_number=None,
            )
        ]
        notifier = FakeNotifier()

        with tempfile.TemporaryDirectory() as tmpdir:
            decisions = run_open_entry_cycle(
                entries=entries,
                quote_lookup=lambda entry: 41.35,
                notifier=notifier,
                db_path=f"{tmpdir}/agent.db",
                dry_run=True,
            )

        self.assertEqual([item.result for item in decisions], ["called"])
        self.assertEqual(notifier.sent, [])
