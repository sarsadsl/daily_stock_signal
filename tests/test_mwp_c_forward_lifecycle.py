from __future__ import annotations

import unittest
from unittest.mock import patch

import build_mwp_a_strategy_tracking as tracking
from run_market_backtest import Row


def make_series(
    stock_no: str,
    stock_name: str,
    dates: list[str],
    market: str = "TWSE",
) -> tracking.SeriesMap:
    rows = [
        Row(market, stock_no, stock_name, date, 97.0, 101.0, 96.0, 100.0, 100_000)
        for date in dates
    ]
    return {
        (market, stock_no): (
            rows,
            {},
            {row.date: index for index, row in enumerate(rows)},
        )
    }


def candidate(stock_no: str, stock_name: str, date: str, market: str) -> dict[str, object]:
    return {
        "market": market,
        "stock_no": stock_no,
        "stock_name": stock_name,
        "date": date,
        "signal_date": date,
        "close": 100.0,
        "strategy": "pullback",
        "reason": "test",
    }


class ForwardMotherLifecycleTests(unittest.TestCase):
    def assert_candidate_is_blocked(
        self,
        series: tracking.SeriesMap,
        target_date: str,
        records: list[dict[str, object]],
        expected_reason: str,
    ) -> None:
        stock_no = str(records[0]["stock_no"])
        stock_name = "台半" if stock_no == "5425" else "銘異"
        market = str(records[0]["market"])
        with (
            patch.object(tracking, "latest_pullback_matches", return_value=[candidate(stock_no, stock_name, target_date, market)]),
            patch.object(tracking, "ma20_slope5_pct", return_value=1.0),
        ):
            new_mothers, _, blocked = tracking.mother_candidate_rows(
                target_date,
                series,
                [],
                records,
            )

        self.assertEqual(new_mothers, [])
        self.assertEqual(len(blocked), 1)
        self.assertIn(expected_reason, str(blocked[0]["block_reason"]))

    def test_pending_mother_that_enters_today_blocks_a_duplicate_signal(self) -> None:
        """銘異：7/1 訊號在 7/2 進場，不能再建立 7/2 母單。"""
        series = make_series("3060", "銘異", ["2026-07-01", "2026-07-02", "2026-07-03"])
        records = [{
            "id": "TWSE:3060:2026-07-01:base",
            "unit_type": "base",
            "market": "TWSE",
            "stock_no": "3060",
            "signal_date": "2026-07-01",
            "status": "待次日開盤",
            "entry_limit_price": 100.0,
        }]

        self.assert_candidate_is_blocked(series, "2026-07-02", records, "formal buy cooldown")

    def test_exited_mother_still_enforces_same_stock_cooldown(self) -> None:
        """台半：同日停損的 7/13 母單，仍必須擋住當天的新訊號。"""
        series = make_series("5425", "台半", ["2026-07-08", "2026-07-13", "2026-07-14"], "TPEX")
        records = [{
            "id": "TPEX:5425:2026-07-08:base",
            "unit_type": "base",
            "market": "TPEX",
            "stock_no": "5425",
            "signal_date": "2026-07-08",
            "entry_date": "2026-07-13",
            "exit_date": "2026-07-13",
            "status": "已出場",
        }]

        self.assert_candidate_is_blocked(series, "2026-07-13", records, "formal buy cooldown")

    def test_existing_duplicate_mother_is_retired_without_deleting_the_audit_record(self) -> None:
        series = make_series("3060", "銘異", ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-14"])
        records: list[dict[str, object]] = [
            {
                "id": "TWSE:3060:2026-07-01:base",
                "unit_type": "base",
                "market": "TWSE",
                "stock_no": "3060",
                "signal_date": "2026-07-01",
                "entry_date": "2026-07-02",
                "status": "持有中",
                "unresolved": True,
            },
            {
                "id": "TWSE:3060:2026-07-02:base",
                "unit_type": "base",
                "market": "TWSE",
                "stock_no": "3060",
                "signal_date": "2026-07-02",
                "entry_date": "2026-07-03",
                "exit_date": "2026-07-14",
                "status": "已出場",
                "unresolved": False,
            },
        ]

        self.assertTrue(tracking.reconcile_duplicate_forward_mothers(records, series))
        self.assertEqual(records[1]["status"], tracking.FORWARD_DUPLICATE_STATUS)
        self.assertFalse(records[1]["unresolved"])
        self.assertIn("active formal mother", str(records[1]["lifecycle_filter_reject_reason"]))


if __name__ == "__main__":
    unittest.main()
