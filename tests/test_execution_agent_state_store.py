import tempfile
import unittest

from execution_agent.open_entry_core import build_open_entry_decision
from execution_agent.state_store import SQLiteStateStore
from execution_agent.tracking_source import PendingOpenEntry


class StateStoreTests(unittest.TestCase):
    def test_record_decision_makes_call_key_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SQLiteStateStore(f"{tmpdir}/agent.db")
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

            self.assertFalse(store.has_processed(decision.call_key))
            store.record_decision(decision)
            self.assertTrue(store.has_processed(decision.call_key))
