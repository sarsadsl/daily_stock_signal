from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import patch

from dashboard_server import sync_daily_market_data, sync_market_data


class DailyMarketSyncTests(unittest.TestCase):
    def test_required_target_date_rejects_fallback_data(self) -> None:
        with patch("dashboard_server.load_symbols", return_value=[]), patch(
            "dashboard_server.fetch_latest_daily_rows",
            return_value=(date(2026, 7, 29), {"twse": {}, "tpex": {}}),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "Market data for 2026-07-30 has not been published; latest available is 2026-07-29",
            ):
                sync_daily_market_data(
                    ["twse", "tpex"],
                    target_date=date(2026, 7, 30),
                    require_target_date=True,
                )

    def test_required_target_date_propagates_sync_failure(self) -> None:
        with patch(
            "dashboard_server.sync_daily_market_data",
            side_effect=RuntimeError("upstream data unavailable"),
        ):
            with self.assertRaisesRegex(RuntimeError, "upstream data unavailable"):
                sync_market_data(
                    ["twse", "tpex"],
                    limit=None,
                    target_date=date(2026, 7, 30),
                    require_target_date=True,
                )


if __name__ == "__main__":
    unittest.main()
