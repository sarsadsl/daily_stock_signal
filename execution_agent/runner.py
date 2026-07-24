from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path
from urllib.request import urlopen

from execution_agent.broker_adapter import BrokerAdapter
from execution_agent.broker_config import BrokerConfig
from execution_agent.config import ExecutionAgentConfig
from execution_agent.notifier import TelegramNotifier
from execution_agent.open_entry_core import OpenEntryDecision, build_open_entry_decision
from execution_agent.run_lock import ExecutionAgentAlreadyRunningError, execution_agent_lock
from execution_agent.sandbox_executor import execute_sandbox_orders
from execution_agent.sandbox_ledger import SandboxLedger
from execution_agent.state_store import SQLiteStateStore
from execution_agent.tracking_source import (
    PendingOpenEntry,
    load_tracking_payload_from_text,
)
from send_mwp_c_open_entry_calls import (
    build_trading_dates,
    select_pending_open_call_candidates,
    wait_for_realtime_open_snapshot,
)


def load_tracking_payload_text(tracking_json_url: str) -> str:
    with urlopen(tracking_json_url) as response:
        return response.read().decode("utf-8")


def build_open_snapshot(
    entries: list[PendingOpenEntry],
    signal_date: str,
    dry_run: bool,
    poll_attempts: int = 20,
    poll_interval_seconds: float = 15.0,
) -> dict[tuple[str, str], float]:
    if not entries:
        return {}

    records = [
        {
            "market": entry.market,
            "stock_no": entry.stock_no,
        }
        for entry in entries
    ]
    return wait_for_realtime_open_snapshot(
        records,
        target_date=date.fromisoformat(signal_date),
        max_attempts=1 if dry_run else poll_attempts,
        sleep_seconds=poll_interval_seconds,
    )


def select_entries_for_run_date(
    payload: dict,
    run_date: str,
    trading_dates: dict[tuple[str, str], list[str]] | None = None,
) -> list[PendingOpenEntry]:
    records = payload.get("tracking", {}).get("formal_forward_records", [])
    selected = select_pending_open_call_candidates(
        records,
        as_of_date=run_date,
        sent_log={"calls": []},
        trading_dates=trading_dates or build_trading_dates(),
    )
    return [
        PendingOpenEntry(
            market=str(record.get("market") or "").upper(),
            stock_no=str(record.get("stock_no") or ""),
            stock_name=str(record.get("stock_name") or ""),
            signal_date=str(record.get("signal_date") or ""),
            entry_limit_price=float(record.get("entry_limit_price") or 0.0),
            signal_close=float(record.get("signal_close") or 0.0),
            unit_type=str(record.get("unit_type") or "base"),
            addon_number=record.get("addon_number"),
        )
        for record in selected
    ]


def ensure_db_parent_dir(db_path: str) -> None:
    parent = Path(db_path).parent
    if str(parent) and str(parent) != ".":
        parent.mkdir(parents=True, exist_ok=True)


def run_open_entry_cycle(
    entries: list[PendingOpenEntry],
    quote_lookup: Callable[[PendingOpenEntry], float],
    notifier: TelegramNotifier,
    db_path: str,
    dry_run: bool,
    include_processed_called: bool = False,
) -> list[OpenEntryDecision]:
    if not dry_run:
        ensure_db_parent_dir(db_path)
    store = None if dry_run else SQLiteStateStore(db_path)
    decisions: list[OpenEntryDecision] = []
    for entry in entries:
        decision = build_open_entry_decision(entry, open_price=quote_lookup(entry))
        if store is not None and store.has_processed(decision.call_key):
            if include_processed_called and decision.result == "called":
                decisions.append(decision)
            continue
        if dry_run:
            decisions.append(decision)
            continue
        if decision.result == "called" and not notifier.send_open_entry_call(decision):
            decisions.append(decision)
            continue
        store.record_decision(decision)
        decisions.append(decision)
    return decisions


def run_from_config(
    config: ExecutionAgentConfig,
    notifier: TelegramNotifier | None = None,
    broker_config: BrokerConfig | None = None,
    sandbox_ledger: SandboxLedger | None = None,
    broker: BrokerAdapter | None = None,
    poll_attempts: int = 20,
    poll_interval_seconds: float = 15.0,
) -> list[OpenEntryDecision]:
    if config.dry_run:
        return _run_from_config_unlocked(
            config,
            notifier=notifier,
            broker_config=broker_config,
            sandbox_ledger=sandbox_ledger,
            broker=broker,
            poll_attempts=poll_attempts,
            poll_interval_seconds=poll_interval_seconds,
        )
    ensure_db_parent_dir(config.state_db_path)
    with execution_agent_lock(config.state_db_path):
        return _run_from_config_unlocked(
            config,
            notifier=notifier,
            broker_config=broker_config,
            sandbox_ledger=sandbox_ledger,
            broker=broker,
            poll_attempts=poll_attempts,
            poll_interval_seconds=poll_interval_seconds,
        )


def _run_from_config_unlocked(
    config: ExecutionAgentConfig,
    notifier: TelegramNotifier | None = None,
    broker_config: BrokerConfig | None = None,
    sandbox_ledger: SandboxLedger | None = None,
    broker: BrokerAdapter | None = None,
    poll_attempts: int = 20,
    poll_interval_seconds: float = 15.0,
) -> list[OpenEntryDecision]:
    active_broker_config = None
    active_ledger = None
    should_submit_orders = False
    if not config.dry_run:
        active_broker_config = broker_config or BrokerConfig.from_env()
        should_submit_orders = active_broker_config.should_submit_orders()
    if should_submit_orders:
        active_ledger = sandbox_ledger or SandboxLedger(config.state_db_path)

    decisions: list[OpenEntryDecision] = []
    try:
        payload = load_tracking_payload_from_text(load_tracking_payload_text(config.tracking_json_url))
        entries = select_entries_for_run_date(payload, run_date=config.signal_date)
        open_snapshot = build_open_snapshot(
            entries,
            signal_date=config.signal_date,
            dry_run=config.dry_run,
            poll_attempts=poll_attempts,
            poll_interval_seconds=poll_interval_seconds,
        )
        ready_entries = [
            entry
            for entry in entries
            if (entry.market, entry.stock_no) in open_snapshot
        ]
        decisions = run_open_entry_cycle(
            entries=ready_entries,
            quote_lookup=lambda entry: open_snapshot[(entry.market, entry.stock_no)],
            notifier=notifier or TelegramNotifier(),
            db_path=config.state_db_path,
            dry_run=config.dry_run,
            include_processed_called=should_submit_orders,
        )
    except Exception as primary_error:
        try:
            if (
                should_submit_orders
                and active_broker_config is not None
                and active_ledger is not None
            ):
                execute_sandbox_orders(
                    decisions,
                    config=active_broker_config,
                    ledger=active_ledger,
                    broker=broker,
                )
        except Exception as reconciliation_error:
            raise primary_error from reconciliation_error
        raise
    else:
        if should_submit_orders and active_broker_config is not None and active_ledger is not None:
            execute_sandbox_orders(
                decisions,
                config=active_broker_config,
                ledger=active_ledger,
                broker=broker,
            )
    return decisions


def run_from_env(
    notifier: TelegramNotifier | None = None,
    broker_config: BrokerConfig | None = None,
    sandbox_ledger: SandboxLedger | None = None,
    broker: BrokerAdapter | None = None,
    poll_attempts: int = 20,
    poll_interval_seconds: float = 15.0,
) -> list[OpenEntryDecision]:
    return run_from_config(
        ExecutionAgentConfig.from_env(),
        notifier=notifier,
        broker_config=broker_config,
        sandbox_ledger=sandbox_ledger,
        broker=broker,
        poll_attempts=poll_attempts,
        poll_interval_seconds=poll_interval_seconds,
    )


def main() -> int:
    config = ExecutionAgentConfig.from_env()
    decisions = run_from_config(config)
    if config.dry_run:
        for decision in decisions:
            print(
                f"[DRY-RUN] {decision.call_key} {decision.result} "
                f"open={decision.open_price} limit={decision.entry_limit_price}"
            )
    elif not decisions:
        print("No MWP-C formal-tracking open-entry decisions for this date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
