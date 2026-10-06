from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from market_calendar import fetch_twse_calendar, is_twse_trading_day, missing_trading_dates, resolve_target_date, write_github_output


class MarketCalendarTests(unittest.TestCase):
    def test_retries_temporary_calendar_request_failures(self) -> None:
        payload = {"stat": "ok", "data": []}
        with patch(
            "market_calendar.request_json",
            side_effect=[RuntimeError("HTTP 307 from TWSE"), payload],
        ), patch("market_calendar.time.sleep") as sleep:
            self.assertEqual(fetch_twse_calendar(2026), [])

        sleep.assert_called_once_with(5)

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

    def test_delayed_scheduled_run_uses_previous_market_date(self) -> None:
        now = datetime(2026, 10, 6, 2, 57, tzinfo=timezone(timedelta(hours=8)))
        self.assertEqual(resolve_target_date("", now=now), date(2026, 10, 5))

    def test_normal_evening_run_uses_today(self) -> None:
        now = datetime(2026, 10, 6, 10, 0, tzinfo=timezone.utc)
        self.assertEqual(resolve_target_date("", now=now), date(2026, 10, 6))

    def test_explicit_backfill_date_is_not_changed(self) -> None:
        now = datetime(2026, 10, 6, 2, 57, tzinfo=timezone(timedelta(hours=8)))
        self.assertEqual(resolve_target_date("2026-09-29", now=now), date(2026, 9, 29))

    def test_writes_github_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "github-output"
            write_github_output(output, date(2026, 7, 30), True)
            self.assertEqual(
                output.read_text(encoding="utf-8"),
                "target_date=2026-07-30\nis_trading_day=true\n",
            )

    def test_missing_dates_skip_weekends_and_holidays(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tracking = Path(tmpdir) / "tracking.json"
            tracking.write_text('{"tracking":{"as_of_daily_signal_date":"2026-09-24"}}', encoding="utf-8")
            with patch("market_calendar.is_twse_trading_day", side_effect=lambda day: day.isoformat() in {
                "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02"
            }):
                self.assertEqual(
                    missing_trading_dates(tracking, date(2026, 10, 5)),
                    [date(2026, 9, 29), date(2026, 9, 30), date(2026, 10, 1), date(2026, 10, 2)],
                )

    def test_backfill_cannot_move_tracking_backwards(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tracking = Path(tmpdir) / "tracking.json"
            tracking.write_text('{"tracking":{"as_of_daily_signal_date":"2026-10-05"}}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "precedes completed tracking date"):
                missing_trading_dates(tracking, date(2026, 9, 29))


if __name__ == "__main__":
    unittest.main()
