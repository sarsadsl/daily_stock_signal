import unittest

from execution_agent.open_entry_core import build_open_entry_decision
from execution_agent.tracking_source import PendingOpenEntry


class OpenEntryCoreTests(unittest.TestCase):
    def test_build_open_entry_decision_marks_called_when_open_is_below_limit(self) -> None:
        entry = PendingOpenEntry(
            market="TWSE",
            stock_no="3094",
            stock_name="?臬?",
            signal_date="2026-07-08",
            entry_limit_price=41.65,
            signal_close=42.5,
            unit_type="base",
            addon_number=None,
        )

        decision = build_open_entry_decision(entry, open_price=41.35)

        self.assertEqual(decision.result, "called")
        self.assertEqual(decision.call_key, "TWSE:3094:2026-07-08:base:-")
