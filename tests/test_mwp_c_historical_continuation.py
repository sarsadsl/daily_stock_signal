from __future__ import annotations

import unittest
from unittest.mock import patch

import build_mwp_a_strategy_tracking as tracking
from run_market_backtest import Row


def series() -> tracking.SeriesMap:
    rows = [
        Row("TWSE", "1234", "測試股", "2026-07-01", 99, 101, 98, 100, 100_000),
        Row("TWSE", "1234", "測試股", "2026-07-02", 100, 102, 99, 101, 100_000),
        Row("TWSE", "1234", "測試股", "2026-07-03", 100, 103, 99, 102, 100_000),
        Row("TWSE", "1234", "測試股", "2026-07-04", 121, 123, 119, 122, 100_000),
    ]
    return {("TWSE", "1234"): (rows, {}, {row.date: index for index, row in enumerate(rows)})}


def unit(kind: str, **extra: object) -> dict[str, object]:
    return {
        "market": "TWSE", "stock_no": "1234", "stock_name": "測試股",
        "signal_date": "2026-07-01", "entry_date": "2026-07-02" if kind == "base" else "2026-07-03",
        "entry_price": 100.0, "exit_date": "2026-06-29", "exit_price": 103.0,
        "exit_reason": "latest_close", "return_pct": 3.0, "pnl": 3_000,
        "holding_days": 5, "unit_type": kind, "unresolved": True, **extra,
    }


class HistoricalContinuationTests(unittest.TestCase):
    def test_historical_positions_do_not_block_formal_radar(self) -> None:
        backtest = {"packages": [{**unit("base")}], "units": [{**unit("base")}]} 
        candidate = {"market": "TWSE", "stock_no": "1234", "stock_name": "測試股", "date": "2026-07-04", "signal_date": "2026-07-04", "close": 122.0, "strategy": "pullback", "reason": "test"}
        with (
            patch.object(tracking, "latest_pullback_matches", return_value=[candidate]),
            patch.object(tracking, "ma20_slope5_pct", return_value=1.0),
        ):
            radar = tracking.build_daily_radar(backtest, series(), [])
        self.assertEqual(len(radar["new_mother_candidates"]), 1)
        self.assertEqual(radar["cooldown_blocked"], [])

    def test_historical_exit_is_realized_and_addon_syncs_with_mother(self) -> None:
        source = [unit("base"), unit("addon", addon_number=1, confirm_date="2026-07-02")]
        base_exit = {"exit_date": "2026-07-04", "exit_price": 90.0, "exit_reason": "base_hard_stop7", "return_pct": -10.0, "pnl": -10_000, "holding_days": 3, "unresolved": False}
        addon_open = {"exit_date": "2026-07-04", "exit_price": 122.0, "exit_reason": "latest_close", "return_pct": 22.0, "pnl": 22_000, "holding_days": 2, "unresolved": True}
        with (
            patch.object(tracking.pbv23, "first_confirmation_index", return_value=(1, "confirmed")),
            patch.object(tracking, "BASE_EXIT_POLICY", return_value=base_exit),
            patch.object(tracking.pbv23, "structure_addon_exit", return_value=addon_open),
        ):
            refreshed = tracking.refresh_historical_unresolved_units(source, series())
        base, addon = refreshed
        self.assertFalse(base["unresolved"])
        self.assertFalse(addon["unresolved"])
        self.assertEqual(addon["exit_date"], "2026-07-04")
        self.assertEqual(addon["exit_price"], 90.0)
        self.assertEqual(addon["exit_reason"], "mother_exit_sync_base_hard_stop7")
        self.assertEqual(addon["valuation_date"], "2026-07-04")
        self.assertEqual(source[0]["exit_date"], "2026-06-29")

    def test_open_historical_unit_uses_latest_close(self) -> None:
        latest = {"exit_date": "2026-07-04", "exit_price": 122.0, "exit_reason": "latest_close", "return_pct": 22.0, "pnl": 22_000, "holding_days": 3, "unresolved": True}
        with (
            patch.object(tracking.pbv23, "first_confirmation_index", return_value=(2, "confirmed")),
            patch.object(tracking, "BASE_EXIT_POLICY", return_value=latest),
        ):
            refreshed = tracking.refresh_historical_unresolved_units([unit("base")], series())
        self.assertTrue(refreshed[0]["unresolved"])
        self.assertEqual(refreshed[0]["latest_close"], 122)
        self.assertEqual(refreshed[0]["historical_source_as_of_date"], "2026-06-29")


if __name__ == "__main__":
    unittest.main()
