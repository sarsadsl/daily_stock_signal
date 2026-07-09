from __future__ import annotations

from collections.abc import Callable
from datetime import date
from urllib.request import urlopen

from execution_agent.config import ExecutionAgentConfig
from execution_agent.notifier import TelegramNotifier
from execution_agent.open_entry_core import OpenEntryDecision, build_open_entry_decision
from execution_agent.state_store import SQLiteStateStore
from execution_agent.tracking_source import (
    PendingOpenEntry,
    load_tracking_payload_from_text,
    select_pending_open_entries,
)
from send_mwp_c_open_entry_calls import wait_for_realtime_open_snapshot


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


def run_open_entry_cycle(
    entries: list[PendingOpenEntry],
    quote_lookup: Callable[[PendingOpenEntry], float],
    notifier: TelegramNotifier,
    db_path: str,
    dry_run: bool,
) -> list[OpenEntryDecision]:
    store = None if dry_run else SQLiteStateStore(db_path)
    decisions: list[OpenEntryDecision] = []
    for entry in entries:
        decision = build_open_entry_decision(entry, open_price=quote_lookup(entry))
        if store is not None and store.has_processed(decision.call_key):
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
    poll_attempts: int = 20,
    poll_interval_seconds: float = 15.0,
) -> list[OpenEntryDecision]:
    payload = load_tracking_payload_from_text(load_tracking_payload_text(config.tracking_json_url))
    entries = select_pending_open_entries(payload, signal_date=config.signal_date)
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
    return run_open_entry_cycle(
        entries=ready_entries,
        quote_lookup=lambda entry: open_snapshot[(entry.market, entry.stock_no)],
        notifier=notifier or TelegramNotifier(),
        db_path=config.state_db_path,
        dry_run=config.dry_run,
    )


def run_from_env(
    notifier: TelegramNotifier | None = None,
    poll_attempts: int = 20,
    poll_interval_seconds: float = 15.0,
) -> list[OpenEntryDecision]:
    return run_from_config(
        ExecutionAgentConfig.from_env(),
        notifier=notifier,
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
