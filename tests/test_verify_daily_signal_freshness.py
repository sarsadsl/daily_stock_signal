from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from verify_daily_signal_freshness import verify_freshness


def make_row(
    stock_no: str,
    date: str,
    volume: int,
    market: str = "TWSE",
    stock_name: str = "Test",
) -> SimpleNamespace:
    return SimpleNamespace(
        market=market,
        stock_no=stock_no,
        stock_name=stock_name,
        date=date,
        volume=volume,
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.0,
    )


def make_history(
    stock_no: str,
    latest_date: str,
    latest_volume: int,
    market: str = "TWSE",
    stock_name: str = "Test",
) -> list[SimpleNamespace]:
    rows = [
        make_row(
            stock_no=stock_no,
            date="2026-06-30",
            volume=500_000,
            market=market,
            stock_name=stock_name,
        )
        for _ in range(59)
    ]
    rows.append(
        make_row(
            stock_no=stock_no,
            date=latest_date,
            volume=latest_volume,
            market=market,
            stock_name=stock_name,
        )
    )
    return rows


class DailySignalFreshnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 7, 1, 20, 30)

    def test_fails_when_latest_market_date_is_stale(self) -> None:
        rows_by_path = {
            "a.csv": make_history("2330", "2026-06-30", 2_000_000),
        }

        with patch("verify_daily_signal_freshness.csv_files", return_value=["a.csv"]), patch(
            "verify_daily_signal_freshness.read_rows",
            side_effect=lambda path: rows_by_path[path],
        ), patch("verify_daily_signal_freshness.prepare", return_value={}), patch(
            "verify_daily_signal_freshness.STRATEGIES",
            {"demo": lambda rows, indicators, index: "signal"},
        ):
            with self.assertRaisesRegex(ValueError, "Latest market date mismatch"):
                verify_freshness("2026-07-01", now=self.now)

    def test_fails_when_latest_market_has_no_signals(self) -> None:
        rows_by_path = {
            "a.csv": make_history("2330", "2026-07-01", 2_000_000),
            "b.csv": make_history("2317", "2026-07-01", 3_000_000),
        }

        with patch("verify_daily_signal_freshness.csv_files", return_value=["a.csv", "b.csv"]), patch(
            "verify_daily_signal_freshness.read_rows",
            side_effect=lambda path: rows_by_path[path],
        ), patch("verify_daily_signal_freshness.prepare", return_value={}), patch(
            "verify_daily_signal_freshness.STRATEGIES",
            {"demo": lambda rows, indicators, index: None},
        ):
            with self.assertRaisesRegex(ValueError, "No latest-date signals were found"):
                verify_freshness("2026-07-01", now=self.now)

    def test_passes_with_latest_date_signals_and_report_date(self) -> None:
        rows_by_path = {
            "a.csv": make_history("2330", "2026-07-01", 2_000_000),
            "b.csv": make_history("2317", "2026-07-01", 900_000),
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "daily_signal_alert.csv"
            with report_path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["date"])
                writer.writeheader()
                writer.writerow({"date": "2026-07-01"})

            with patch(
                "verify_daily_signal_freshness.csv_files",
                return_value=["a.csv", "b.csv"],
            ), patch(
                "verify_daily_signal_freshness.read_rows",
                side_effect=lambda path: rows_by_path[path],
            ), patch("verify_daily_signal_freshness.prepare", return_value={}), patch(
                "verify_daily_signal_freshness.STRATEGIES",
                {"demo": lambda rows, indicators, index: "signal" if rows[index].stock_no == "2330" else None},
            ):
                result = verify_freshness(
                    "2026-07-01",
                    now=self.now,
                    report_path=report_path,
                )

        self.assertEqual(result["expected_date"], "2026-07-01")
        self.assertEqual(result["latest_market_date"], "2026-07-01")
        self.assertEqual(result["latest_symbol_count"], 2)
        self.assertEqual(result["volume_qualified_count"], 1)
        self.assertEqual(result["signal_match_count"], 1)
        self.assertEqual(result["latest_report_date"], "2026-07-01")


if __name__ == "__main__":
    unittest.main()
