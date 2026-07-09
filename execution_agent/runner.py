from __future__ import annotations

from collections.abc import Callable

from execution_agent.notifier import TelegramNotifier
from execution_agent.open_entry_core import OpenEntryDecision, build_open_entry_decision
from execution_agent.state_store import SQLiteStateStore
from execution_agent.tracking_source import PendingOpenEntry


def run_open_entry_cycle(
    entries: list[PendingOpenEntry],
    quote_lookup: Callable[[PendingOpenEntry], float],
    notifier: TelegramNotifier,
    db_path: str,
    dry_run: bool,
) -> list[OpenEntryDecision]:
    store = SQLiteStateStore(db_path)
    decisions: list[OpenEntryDecision] = []
    for entry in entries:
        decision = build_open_entry_decision(entry, open_price=quote_lookup(entry))
        if store.has_processed(decision.call_key):
            continue
        if not dry_run and decision.result == "called":
            notifier.send_open_entry_call(decision)
        if not dry_run:
            store.record_decision(decision)
        decisions.append(decision)
    return decisions
