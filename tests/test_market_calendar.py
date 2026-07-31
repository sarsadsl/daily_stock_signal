from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from market_calendar import is_twse_trading_day, resolve_target_date, write_github_output


class MarketCalendarTests(unittest.TestCase):
    def test_weekends_do_not_request_the_calendar(self) -> None:
        with patch("market_calendar.fetch_twse_calendar") as calendar:
            self.assertFalse(is_twse_trading_day(date(2026, 8, 1)))
        calendar.assert_not_called()

    def test_official_holiday_is_not_a_trading_day(self) -> None:
        with patch(
            "market_calendar.fetch_twse_calendar",
            return_value=[["2026-10-09", "國慶日", "補假"]],
        ):
            self.assertFalse(is_twse_trading_day(date(2026, 10, 9)))

    def test_calendar_trading_marker_is_a_trading_day(self) -> None:
        with patch(
            "market_calendar.fetch_twse_calendar",
            return_value=[["2026-02-23", "農曆春節後開始交易日", "開始交易"]],
        ):
            self.assertTrue(is_twse_trading_day(date(2026, 2, 23)))

    def test_resolves_blank_date_in_taipei_time(self) -> None:
        now = datetime(2026, 7, 30, 23, 30)
        self.assertEqual(resolve_target_date("", now=now), date(2026, 7, 30))

    def test_writes_github_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "github-output"
            write_github_output(output, date(2026, 7, 30), True)
            self.assertEqual(
                output.read_text(encoding="utf-8"),
                "target_date=2026-07-30\nis_trading_day=true\n",
            )


if __name__ == "__main__":
    unittest.main()
