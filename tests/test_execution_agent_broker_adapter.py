import unittest

from execution_agent.broker_adapter import SandboxOrderRequest, _result_from_trade


def request(quantity: int = 2000) -> SandboxOrderRequest:
    return SandboxOrderRequest(
        call_key="TWSE:3094:2026-07-08:base:-",
        market="TWSE",
        stock_no="3094",
        stock_name="test",
        signal_date="2026-07-08",
        open_price=41.35,
        entry_limit_price=41.65,
        cash_budget=100000,
        quantity=quantity,
        price=41.35,
        order_type="sandbox_buy_open",
    )


class FakeTrade:
    def __init__(self, status: str, deal_quantity: int, deals=None) -> None:
        self.order = type("Order", (), {"id": "order-1"})()
        self.status = type(
            "Status",
            (),
            {
                "status": status,
                "status_code": "00",
                "msg": status,
                "deal_quantity": deal_quantity,
                "deals": deals or [],
            },
        )()


class BrokerAdapterResultTests(unittest.TestCase):
    def test_submitted_trade_is_accepted_but_not_filled(self) -> None:
        result = _result_from_trade(request(), FakeTrade("Submitted", 0))

        self.assertTrue(result.accepted)
        self.assertEqual(result.status, "Submitted")
        self.assertEqual(result.filled_quantity, 0)
        self.assertIsNone(result.average_fill_price)

    def test_common_lot_fill_is_converted_back_to_shares(self) -> None:
        deals = [
            type("Deal", (), {"price": 41.2, "quantity": 1})(),
            type("Deal", (), {"price": 41.4, "quantity": 1})(),
        ]
        result = _result_from_trade(request(), FakeTrade("Filled", 2, deals))

        self.assertTrue(result.accepted)
        self.assertEqual(result.filled_quantity, 2000)
        self.assertAlmostEqual(result.average_fill_price, 41.3)

    def test_failed_trade_is_rejected(self) -> None:
        result = _result_from_trade(request(), FakeTrade("Failed", 0))

        self.assertFalse(result.accepted)
        self.assertEqual(result.status, "Failed")
