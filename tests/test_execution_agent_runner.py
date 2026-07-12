import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import execution_agent.runner as runner
from execution_agent.broker_adapter import SandboxOrderResult
from execution_agent.state_store import SQLiteStateStore
from execution_agent.tracking_source import PENDING_NEXT_OPEN_STATUS, PendingOpenEntry


class FakeNotifier:
    def __init__(self, should_succeed: bool = True) -> None:
        self.sent: list[str] = []
        self.should_succeed = should_succeed

    def send_open_entry_call(self, decision) -> bool:
        self.sent.append(decision.call_key)
        return self.should_succeed


class FakeBroker:
    def __init__(self) -> None:
        self.requests = []

    def submit_buy_order(self, request):
        self.requests.append(request)
        return SandboxOrderResult(
            call_key=request.call_key,
            accepted=True,
            broker_order_id=f"fake-{len(self.requests)}",
            submitted_at="2026-07-10T09:00:00+08:00",
            message="accepted",
            status="Filled",
            filled_quantity=request.quantity,
            average_fill_price=request.price,
        )


class RunnerTests(unittest.TestCase):
    def test_run_open_entry_cycle_records_called_and_sends_notification(self) -> None:
        entries = [
            PendingOpenEntry(
                market="TWSE",
                stock_no="3094",
                stock_name="???",
                signal_date="2026-07-08",
                entry_limit_price=41.65,
                signal_close=42.5,
                unit_type="base",
                addon_number=None,
            )
        ]

        def quote_lookup(entry: PendingOpenEntry) -> float:
            self.assertEqual(entry.stock_no, "3094")
            return 41.35

        notifier = FakeNotifier()
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "agent.db"
            decisions = runner.run_open_entry_cycle(
                entries=entries,
                quote_lookup=quote_lookup,
                notifier=notifier,
                db_path=str(db_path),
                dry_run=False,
            )

            self.assertTrue(db_path.exists())
            store = SQLiteStateStore(str(db_path))
            self.assertTrue(store.has_processed("TWSE:3094:2026-07-08:base:-"))

        self.assertEqual([item.result for item in decisions], ["called"])
        self.assertEqual(notifier.sent, ["TWSE:3094:2026-07-08:base:-"])

    def test_run_open_entry_cycle_dry_run_does_not_notify_or_create_state_db(self) -> None:
        entries = [
            PendingOpenEntry(
                market="TWSE",
                stock_no="3094",
                stock_name="???",
                signal_date="2026-07-08",
                entry_limit_price=41.65,
                signal_close=42.5,
                unit_type="base",
                addon_number=None,
            )
        ]
        notifier = FakeNotifier()

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "agent.db"
            decisions = runner.run_open_entry_cycle(
                entries=entries,
                quote_lookup=lambda entry: 41.35,
                notifier=notifier,
                db_path=str(db_path),
                dry_run=True,
            )

            self.assertFalse(db_path.exists())

        self.assertEqual([item.result for item in decisions], ["called"])
        self.assertEqual(notifier.sent, [])

    def test_run_open_entry_cycle_retries_called_decision_after_telegram_failure(self) -> None:
        entries = [
            PendingOpenEntry(
                market="TWSE",
                stock_no="3094",
                stock_name="???",
                signal_date="2026-07-08",
                entry_limit_price=41.65,
                signal_close=42.5,
                unit_type="base",
                addon_number=None,
            )
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "agent.db"
            failed_notifier = FakeNotifier(should_succeed=False)
            runner.run_open_entry_cycle(
                entries=entries,
                quote_lookup=lambda entry: 41.35,
                notifier=failed_notifier,
                db_path=str(db_path),
                dry_run=False,
            )

            store = SQLiteStateStore(str(db_path))
            self.assertFalse(store.has_processed("TWSE:3094:2026-07-08:base:-"))

            successful_notifier = FakeNotifier(should_succeed=True)
            decisions = runner.run_open_entry_cycle(
                entries=entries,
                quote_lookup=lambda entry: 41.35,
                notifier=successful_notifier,
                db_path=str(db_path),
                dry_run=False,
            )

            self.assertTrue(store.has_processed("TWSE:3094:2026-07-08:base:-"))

        self.assertEqual(failed_notifier.sent, ["TWSE:3094:2026-07-08:base:-"])
        self.assertEqual(successful_notifier.sent, ["TWSE:3094:2026-07-08:base:-"])
        self.assertEqual([item.result for item in decisions], ["called"])

    def test_main_runs_from_env_in_dry_run_mode(self) -> None:
        payload_text = json.dumps(
            {
                "tracking": {
                    "formal_forward_records": [
                        {
                            "market": "TWSE",
                            "stock_no": "3094",
                            "stock_name": "???",
                            "signal_date": "2026-07-07",
                            "status": PENDING_NEXT_OPEN_STATUS,
                            "entry_limit_price": 41.65,
                            "signal_close": 42.5,
                            "unit_type": "base",
                            "addon_number": None,
                        }
                    ]
                }
            }
        )

        main = getattr(runner, "main", None)
        self.assertTrue(callable(main))

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "agent.db"
            with patch.dict(
                os.environ,
                {
                    "TRACKING_JSON_URL": "https://example.test/tracking.json",
                    "STATE_DB_PATH": str(db_path),
                    "SIGNAL_DATE": "2026-07-08",
                    "DRY_RUN": "1",
                },
                clear=True,
            ):
                with patch.object(runner, "load_tracking_payload_text", return_value=payload_text, create=True):
                    with patch.object(
                        runner,
                        "build_trading_dates",
                        return_value={("TWSE", "3094"): ["2026-07-07", "2026-07-08"]},
                        create=True,
                    ):
                        with patch.object(
                            runner,
                            "wait_for_realtime_open_snapshot",
                            return_value={("TWSE", "3094"): 41.35},
                            create=True,
                        ):
                            exit_code = main()

            self.assertFalse(db_path.exists())

        self.assertEqual(exit_code, 0)

    def test_run_from_config_uses_next_trading_date_selection_semantics(self) -> None:
        payload_text = json.dumps(
            {
                "tracking": {
                    "formal_forward_records": [
                        {
                            "market": "TWSE",
                            "stock_no": "3094",
                            "stock_name": "???",
                            "signal_date": "2026-07-08",
                            "status": PENDING_NEXT_OPEN_STATUS,
                            "entry_limit_price": 41.65,
                            "signal_close": 42.5,
                            "unit_type": "base",
                            "addon_number": None,
                        }
                    ]
                }
            }
        )

        config = runner.ExecutionAgentConfig(
            tracking_json_url="https://example.test/tracking.json",
            state_db_path="state/agent.db",
            signal_date="2026-07-09",
            dry_run=True,
        )

        with patch.object(runner, "load_tracking_payload_text", return_value=payload_text):
            with patch.object(
                runner,
                "build_trading_dates",
                return_value={("TWSE", "3094"): ["2026-07-08", "2026-07-09"]},
                create=True,
            ):
                with patch.object(
                    runner,
                    "wait_for_realtime_open_snapshot",
                    return_value={("TWSE", "3094"): 41.35},
                    create=True,
                ):
                    decisions = runner.run_from_config(config, notifier=FakeNotifier())

        self.assertEqual([item.call_key for item in decisions], ["TWSE:3094:2026-07-08:base:-"])

    def test_run_open_entry_cycle_creates_parent_directory_for_db_path(self) -> None:
        entries = [
            PendingOpenEntry(
                market="TWSE",
                stock_no="3094",
                stock_name="???",
                signal_date="2026-07-08",
                entry_limit_price=41.65,
                signal_close=42.5,
                unit_type="base",
                addon_number=None,
            )
        ]
        notifier = FakeNotifier()

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "state" / "agent.db"
            decisions = runner.run_open_entry_cycle(
                entries=entries,
                quote_lookup=lambda entry: 41.35,
                notifier=notifier,
                db_path=str(db_path),
                dry_run=False,
            )

            self.assertTrue(db_path.parent.exists())
            self.assertTrue(db_path.exists())

        self.assertEqual([item.result for item in decisions], ["called"])

    def test_run_from_config_executes_sandbox_orders_when_enabled(self) -> None:
        payload_text = json.dumps(
            {
                "tracking": {
                    "formal_forward_records": [
                        {
                            "market": "TWSE",
                            "stock_no": "3094",
                            "stock_name": "聯傑",
                            "signal_date": "2026-07-08",
                            "status": PENDING_NEXT_OPEN_STATUS,
                            "entry_limit_price": 41.65,
                            "signal_close": 42.5,
                            "unit_type": "base",
                            "addon_number": None,
                        }
                    ]
                }
            }
        )
        broker_config = runner.BrokerConfig.from_env(
            {
                "BROKER_MODE": "sandbox",
                "SANDBOX_ONLY": "1",
                "SHIOAJI_API_KEY": "key",
                "SHIOAJI_SECRET_KEY": "secret",
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            config = runner.ExecutionAgentConfig(
                tracking_json_url="https://example.test/tracking.json",
                state_db_path=str(Path(tmpdir) / "agent.db"),
                signal_date="2026-07-09",
                dry_run=False,
            )
            ledger = runner.SandboxLedger(str(Path(tmpdir) / "sandbox.db"))
            broker = FakeBroker()
            with patch.object(runner, "load_tracking_payload_text", return_value=payload_text):
                with patch.object(
                    runner,
                    "build_trading_dates",
                    return_value={("TWSE", "3094"): ["2026-07-08", "2026-07-09"]},
                    create=True,
                ):
                    with patch.object(
                        runner,
                        "wait_for_realtime_open_snapshot",
                        return_value={("TWSE", "3094"): 41.35},
                        create=True,
                    ):
                        decisions = runner.run_from_config(
                            config,
                            notifier=FakeNotifier(),
                            broker_config=broker_config,
                            sandbox_ledger=ledger,
                            broker=broker,
                        )

            self.assertEqual([item.result for item in decisions], ["called"])
            self.assertEqual(len(broker.requests), 1)
            self.assertEqual(len(ledger.list_orders()), 1)
