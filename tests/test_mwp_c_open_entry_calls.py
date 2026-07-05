from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from send_mwp_c_open_entry_calls import (
    MIS_API_URL,
    PENDING_NEXT_OPEN_STATUS,
    build_open_entry_call_decisions,
    fetch_realtime_open_snapshot,
    load_call_log,
    record_call_key,
    render_open_entry_call_message,
    run_open_entry_calls,
    select_pending_open_call_candidates,
    wait_for_realtime_open_snapshot,
    write_call_log,
)


class OpenEntryCallSelectionTests(unittest.TestCase):
    def test_selects_only_pending_records_for_actual_next_trading_day(self) -> None:
        records = [
            {
                "market": "TWSE",
                "stock_no": "2330",
                "stock_name": "台積電",
                "signal_date": "2026-07-03",
                "status": "待次日開盤",
                "entry_limit_price": 980.0,
                "unit_type": "base",
            },
            {
                "market": "TWSE",
                "stock_no": "2317",
                "stock_name": "鴻海",
                "signal_date": "2026-07-03",
                "status": "持有中",
                "entry_limit_price": 180.0,
                "unit_type": "base",
            },
            {
                "market": "TPEX",
                "stock_no": "6488",
                "stock_name": "環球晶",
                "signal_date": "2026-07-02",
                "status": "待次日開盤",
                "entry_limit_price": 420.0,
                "unit_type": "base",
            },
        ]
        sent_log = {
            "calls": [
                {"key": "TWSE:2330:2026-07-03:base:-", "result": "called"},
            ]
        }
        trading_dates = {
            ("TWSE", "2330"): ["2026-07-02", "2026-07-03", "2026-07-06"],
            ("TWSE", "2317"): ["2026-07-02", "2026-07-03", "2026-07-06"],
            ("TPEX", "6488"): ["2026-07-01", "2026-07-02", "2026-07-03"],
        }

        selected = select_pending_open_call_candidates(
            records,
            as_of_date="2026-07-03",
            sent_log=sent_log,
            trading_dates=trading_dates,
        )

        self.assertEqual([record["stock_no"] for record in selected], ["6488"])

    def test_selects_latest_local_signal_for_next_day_open_before_d1_csv_exists(self) -> None:
        records = [
            {
                "market": "TWSE",
                "stock_no": "2330",
                "stock_name": "TSMC",
                "signal_date": "2026-07-03",
                "status": PENDING_NEXT_OPEN_STATUS,
                "entry_limit_price": 980.0,
                "unit_type": "base",
            }
        ]
        trading_dates = {
            ("TWSE", "2330"): ["2026-07-02", "2026-07-03"],
            ("TWSE", "2317"): ["2026-07-02", "2026-07-03"],
            ("TPEX", "6488"): ["2026-07-01", "2026-07-03"],
        }

        selected = select_pending_open_call_candidates(
            records,
            as_of_date="2026-07-06",
            sent_log={"calls": []},
            trading_dates=trading_dates,
        )

        self.assertEqual([record["stock_no"] for record in selected], ["2330"])

    def test_record_call_key_includes_unit_identity(self) -> None:
        key = record_call_key(
            {
                "market": "TWSE",
                "stock_no": "2330",
                "signal_date": "2026-07-03",
                "unit_type": "addon",
                "addon_number": 2,
            }
        )

        self.assertEqual(key, "TWSE:2330:2026-07-03:addon:2")


class RealtimeOpenSnapshotTests(unittest.TestCase):
    @patch("send_mwp_c_open_entry_calls.request_json")
    def test_fetch_realtime_open_snapshot_reads_mis_open_for_target_date(self, mock_request_json) -> None:
        records = [
            {"market": "TWSE", "stock_no": "2330"},
            {"market": "TWSE", "stock_no": "2882"},
            {"market": "TPEX", "stock_no": "8299"},
        ]
        mock_request_json.return_value = {
            "msgArray": [
                {"ex": "tse", "c": "2330", "o": "2415.0000", "d": "20260703"},
                {"ex": "tse", "c": "2882", "o": "--", "d": "20260703"},
                {"ex": "otc", "c": "8299", "o": "2200.0000", "d": "20260703"},
                {"ex": "tse", "c": "2317", "o": "180.5000", "d": "20260702"},
            ]
        }

        snapshot = fetch_realtime_open_snapshot(records, date.fromisoformat("2026-07-03"))

        self.assertEqual(
            snapshot,
            {
                ("TWSE", "2330"): 2415.0,
                ("TPEX", "8299"): 2200.0,
            },
        )
        _, params = mock_request_json.call_args.args
        self.assertEqual(mock_request_json.call_args.args[0], MIS_API_URL)
        self.assertEqual(params["json"], "1")
        self.assertEqual(params["delay"], "0")
        self.assertEqual(params["ex_ch"], "tse_2330.tw|tse_2882.tw|otc_8299.tw")

    @patch("send_mwp_c_open_entry_calls.time.sleep")
    @patch("send_mwp_c_open_entry_calls.fetch_realtime_open_snapshot")
    def test_wait_for_realtime_open_snapshot_retries_until_open_available(
        self,
        mock_fetch_realtime_open_snapshot,
        mock_sleep,
    ) -> None:
        records = [{"market": "TWSE", "stock_no": "2330"}]
        mock_fetch_realtime_open_snapshot.side_effect = [
            {},
            {("TWSE", "2330"): 2415.0},
        ]

        snapshot = wait_for_realtime_open_snapshot(
            records,
            target_date=date.fromisoformat("2026-07-03"),
            max_attempts=2,
            sleep_seconds=1.5,
        )

        self.assertEqual(snapshot, {("TWSE", "2330"): 2415.0})
        self.assertEqual(mock_fetch_realtime_open_snapshot.call_count, 2)
        mock_sleep.assert_called_once_with(1.5)


class OpenEntryCallDecisionTests(unittest.TestCase):
    def test_builds_called_and_open_failed_results_from_open_snapshot(self) -> None:
        records = [
            {
                "market": "TWSE",
                "stock_no": "2330",
                "stock_name": "台積電",
                "signal_date": "2026-07-03",
                "entry_limit_price": 980.0,
                "unit_type": "base",
                "signal_close": 1000.0,
            },
            {
                "market": "TWSE",
                "stock_no": "2317",
                "stock_name": "鴻海",
                "signal_date": "2026-07-03",
                "entry_limit_price": 180.0,
                "unit_type": "base",
                "signal_close": 183.0,
            },
        ]
        open_snapshot = {
            ("TWSE", "2330"): 975.0,
            ("TWSE", "2317"): 181.0,
        }

        decisions = build_open_entry_call_decisions(records, open_snapshot)

        self.assertEqual([item["result"] for item in decisions], ["called", "open_failed"])
        self.assertEqual(decisions[0]["open_price"], 975.0)
        self.assertEqual(decisions[1]["open_price"], 181.0)

    def test_render_message_uses_compact_card_style(self) -> None:
        message = render_open_entry_call_message(
            {
                "market": "TWSE",
                "stock_no": "2330",
                "stock_name": "台積電",
                "signal_date": "2026-07-03",
                "signal_close": 1000.0,
                "entry_limit_price": 980.0,
                "open_price": 975.0,
            }
        )

        self.assertEqual(
            message,
            "\n".join(
                [
                    "🚨 MWP-C 正式追蹤",
                    "🏷️ 2330 台積電",
                    "📅 訊號日 2026-07-03",
                    "💵 收盤 1000.0",
                    "🎯 進場上限 980.0",
                    "🟢 次日開盤 975.0",
                ]
            ),
        )
        self.assertNotIn("TWSE", message)
        self.assertNotIn("TPEX", message)
        self.assertNotIn("符合正式追蹤次日開盤進場條件", message)


class OpenEntryCallCliTests(unittest.TestCase):
    def test_call_log_round_trip_uses_calls_array(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "calls.json"
            write_call_log(path, {"calls": [{"key": "TWSE:2330:2026-07-03:base:-", "result": "called"}]})
            payload = load_call_log(path)

        self.assertEqual(payload["calls"][0]["key"], "TWSE:2330:2026-07-03:base:-")

    @patch("send_mwp_c_open_entry_calls.send_message")
    @patch("send_mwp_c_open_entry_calls.wait_for_realtime_open_snapshot")
    @patch("send_mwp_c_open_entry_calls.load_tracking_payload")
    def test_dry_run_does_not_send_telegram_or_write_called_result(
        self,
        mock_load_tracking_payload,
        mock_wait_for_realtime_open_snapshot,
        mock_send_message,
    ) -> None:
        mock_load_tracking_payload.return_value = {
            "tracking": {
                "formal_forward_records": [
                    {
                        "market": "TWSE",
                        "stock_no": "2330",
                        "stock_name": "台積電",
                        "signal_date": "2026-07-03",
                        "status": "待次日開盤",
                        "entry_limit_price": 980.0,
                        "signal_close": 1000.0,
                        "unit_type": "base",
                    }
                ]
            }
        }
        mock_wait_for_realtime_open_snapshot.return_value = {("TWSE", "2330"): 975.0}

        with tempfile.TemporaryDirectory() as tmp_dir:
            log_path = Path(tmp_dir) / "calls.json"
            decisions = run_open_entry_calls(
                as_of_date=date.fromisoformat("2026-07-06"),
                dry_run=True,
                markets=["twse"],
                tracking_path=Path(tmp_dir) / "tracking.json",
                call_log_path=log_path,
                trading_dates={("TWSE", "2330"): ["2026-07-03", "2026-07-06"]},
            )
            self.assertFalse(log_path.exists())

        self.assertEqual(decisions[0]["result"], "called")
        mock_send_message.assert_not_called()


if __name__ == "__main__":
    unittest.main()
