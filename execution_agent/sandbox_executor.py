from __future__ import annotations

from dataclasses import dataclass

from execution_agent.broker_adapter import BrokerAdapter, ShioajiSandboxBrokerAdapter
from execution_agent.broker_config import BrokerConfig
from execution_agent.open_entry_core import OpenEntryDecision
from execution_agent.order_sizing import OrderSizingError, build_buy_order_request
from execution_agent.sandbox_ledger import SandboxLedger


@dataclass(frozen=True)
class SandboxExecutionSummary:
    submitted: int = 0
    rejected: int = 0
    skipped_non_called: int = 0
    skipped_duplicate: int = 0
    sizing_rejected: int = 0
    broker_errors: int = 0
    noop: int = 0


def execute_sandbox_orders(
    decisions: list[OpenEntryDecision],
    config: BrokerConfig,
    ledger: SandboxLedger,
    broker: BrokerAdapter | None = None,
) -> SandboxExecutionSummary:
    if not config.should_submit_orders():
        return SandboxExecutionSummary(noop=len(decisions))

    active_broker = broker or ShioajiSandboxBrokerAdapter(config)
    counts = _MutableCounts()
    for decision in decisions:
        if decision.result != "called":
            counts.skipped_non_called += 1
            ledger.record_event(decision.call_key, "skipped_non_called", decision.result)
            continue
        if ledger.has_order(decision.call_key):
            counts.skipped_duplicate += 1
            ledger.record_event(decision.call_key, "skipped_duplicate", "sandbox order already exists")
            continue
        try:
            request = build_buy_order_request(decision, cash_budget=config.order_cash_per_trade)
        except OrderSizingError as exc:
            counts.sizing_rejected += 1
            ledger.record_event(decision.call_key, "sizing_rejected", str(exc))
            continue
        try:
            result = active_broker.submit_buy_order(request)
        except Exception as exc:  # pragma: no cover - covered through behavior, not broker internals
            counts.broker_errors += 1
            ledger.record_event(decision.call_key, "broker_error", _safe_error_message(exc))
            continue

        ledger.record_order(request, result)
        if result.accepted:
            counts.submitted += 1
        else:
            counts.rejected += 1
            ledger.record_event(decision.call_key, "broker_rejected", result.message)

    return counts.to_summary()


@dataclass
class _MutableCounts:
    submitted: int = 0
    rejected: int = 0
    skipped_non_called: int = 0
    skipped_duplicate: int = 0
    sizing_rejected: int = 0
    broker_errors: int = 0

    def to_summary(self) -> SandboxExecutionSummary:
        return SandboxExecutionSummary(
            submitted=self.submitted,
            rejected=self.rejected,
            skipped_non_called=self.skipped_non_called,
            skipped_duplicate=self.skipped_duplicate,
            sizing_rejected=self.sizing_rejected,
            broker_errors=self.broker_errors,
        )


def _safe_error_message(exc: Exception) -> str:
    return f"{type(exc).__name__}: {str(exc).splitlines()[0][:200]}"
