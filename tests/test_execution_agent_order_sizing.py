import unittest

from execution_agent.open_entry_core import build_open_entry_decision
from execution_agent.order_sizing import OrderSizingError, build_buy_order_request
from execution_agent.tracking_source import PendingOpenEntry


def called_decision():
    entry = PendingOpenEntry(
        market="TWSE",
        stock_no="3094",
        stock_name="聯傑",
        signal_date="2026-07-08",
        entry_limit_price=41.65,
        signal_close=42.5,
        unit_type="base",
        addon_number=None,
    )
    return build_open_entry_decision(entry, open_price=41.35)


class OrderSizingTests(unittest.TestCase):
    def test_builds_buy_request_without_exceeding_cash_budget(self) -> None:
        request = build_buy_order_request(called_decision(), cash_budget=100000)

        self.assertEqual(request.call_key, "TWSE:3094:2026-07-08:base:-")
        self.assertEqual(request.stock_no, "3094")
        self.assertEqual(request.quantity, 2000)
        self.assertEqual(request.price, 41.35)
        self.assertLessEqual(request.quantity * request.price, 100000)

    def test_keeps_odd_lot_quantity_below_one_thousand_shares(self) -> None:
        request = build_buy_order_request(called_decision(), cash_budget=30000)

        self.assertEqual(request.quantity, 725)

    def test_rejects_non_called_decision(self) -> None:
        decision = called_decision()
        failed = type(decision)(**{**decision.__dict__, "result": "open_failed"})

        with self.assertRaisesRegex(OrderSizingError, "called"):
            build_buy_order_request(failed, cash_budget=100000)

    def test_rejects_budget_too_small_for_one_share(self) -> None:
        with self.assertRaisesRegex(OrderSizingError, "quantity"):
            build_buy_order_request(called_decision(), cash_budget=10)
