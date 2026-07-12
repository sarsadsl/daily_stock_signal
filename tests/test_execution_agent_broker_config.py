import unittest

from execution_agent.broker_config import BrokerConfig, BrokerConfigError


class BrokerConfigTests(unittest.TestCase):
    def test_defaults_to_noop_without_credentials(self) -> None:
        config = BrokerConfig.from_env({})

        self.assertEqual(config.broker_mode, "noop")
        self.assertFalse(config.should_submit_orders())
        self.assertEqual(config.order_cash_per_trade, 100000.0)

    def test_rejects_live_mode(self) -> None:
        with self.assertRaisesRegex(BrokerConfigError, "live"):
            BrokerConfig.from_env({"BROKER_MODE": "live"})

    def test_sandbox_requires_sandbox_only_and_credentials(self) -> None:
        with self.assertRaisesRegex(BrokerConfigError, "SANDBOX_ONLY"):
            BrokerConfig.from_env(
                {
                    "BROKER_MODE": "sandbox",
                    "SHIOAJI_API_KEY": "key",
                    "SHIOAJI_SECRET_KEY": "secret",
                }
            )

        with self.assertRaisesRegex(BrokerConfigError, "SHIOAJI_API_KEY"):
            BrokerConfig.from_env({"BROKER_MODE": "sandbox", "SANDBOX_ONLY": "1"})

    def test_accepts_sandbox_mode_when_guarded(self) -> None:
        config = BrokerConfig.from_env(
            {
                "BROKER_MODE": "sandbox",
                "SANDBOX_ONLY": "1",
                "SHIOAJI_API_KEY": "key",
                "SHIOAJI_SECRET_KEY": "secret",
                "ORDER_CASH_PER_TRADE": "50000",
            }
        )

        self.assertTrue(config.should_submit_orders())
        self.assertEqual(config.order_cash_per_trade, 50000.0)

    def test_rejects_unknown_order_lot_mode(self) -> None:
        with self.assertRaisesRegex(BrokerConfigError, "ORDER_LOT_MODE"):
            BrokerConfig.from_env({"ORDER_LOT_MODE": "unsupported"})
