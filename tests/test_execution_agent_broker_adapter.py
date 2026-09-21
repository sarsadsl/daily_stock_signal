import unittest

from execution_agent.broker_adapter import (
    SandboxOrderRequest,
    ShioajiSandboxBrokerAdapter,
    _order_custom_field,
    _result_from_trade,
)
from execution_agent.broker_config import BrokerConfig


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

    def test_unknown_trade_status_is_not_accepted(self) -> None:
        result = _result_from_trade(request(), FakeTrade("Unknown", 0))

        self.assertFalse(result.accepted)


class FakeApi:
    def __init__(self) -> None:
        self.Contracts = type("Contracts", (), {"Stocks": {"3094": "contract-3094"}})()
        self.stock_account = "stock-account"
        self.orders = []
        self.trades = []
        self.logout_calls = 0

    def login(self, **kwargs) -> None:
        return None

    def Order(self, **kwargs):
        order = type("OrderRequest", (), kwargs)()
        self.orders.append(order)
        return order

    def place_order(self, contract, order):
        trade = FakeTrade("PendingSubmit", 0)
        trade.order.custom_field = order.custom_field
        self.trades.append(trade)
        return trade

    def update_status(self, account=None, *, trade=None):
        if trade is not None:
            raise RuntimeError("refresh unavailable")

    def list_trades(self):
        return list(self.trades)

    def logout(self) -> None:
        self.logout_calls += 1
        raise RuntimeError("logout unavailable")


class FakeShioajiModule:
    class constant:
        class Action:
            Buy = "Buy"

        class StockPriceType:
            LMT = "LMT"

        class OrderType:
            ROD = "ROD"

        class StockOrderLot:
            Common = "Common"

    def __init__(self, api: FakeApi) -> None:
        self.api = api

    def Shioaji(self, simulation: bool):
        if not simulation:
            raise AssertionError("sandbox adapter must use simulation mode")
        return self.api


class ShioajiSandboxAdapterTests(unittest.TestCase):
    def test_submit_preserves_order_when_refresh_and_logout_fail(self) -> None:
        api = FakeApi()
        module = FakeShioajiModule(api)
        config = BrokerConfig.from_env(
            {
                "BROKER_MODE": "sandbox",
                "SANDBOX_ONLY": "1",
                "SHIOAJI_API_KEY": "key",
                "SHIOAJI_SECRET_KEY": "secret",
            }
        )
        adapter = ShioajiSandboxBrokerAdapter(config, shioaji_module=module)

        result = adapter.submit_buy_order(request())

        self.assertTrue(result.accepted)
        self.assertEqual(result.broker_order_id, "order-1")
        self.assertEqual(result.status, "PendingSubmit")
        self.assertEqual(len(api.orders[0].custom_field), 6)
        self.assertEqual(api.logout_calls, 1)

    def test_submit_recovers_existing_order_by_custom_field(self) -> None:
        api = FakeApi()
        existing_trade = FakeTrade("Submitted", 0)
        existing_trade.order.custom_field = _order_custom_field(request().call_key)
        api.trades.append(existing_trade)
        module = FakeShioajiModule(api)
        config = BrokerConfig.from_env(
            {
                "BROKER_MODE": "sandbox",
                "SANDBOX_ONLY": "1",
                "SHIOAJI_API_KEY": "key",
                "SHIOAJI_SECRET_KEY": "secret",
            }
        )
        adapter = ShioajiSandboxBrokerAdapter(config, shioaji_module=module)

        result = adapter.submit_buy_order(request())

        self.assertEqual(result.broker_order_id, "order-1")
        self.assertEqual(api.orders, [])
