from __future__ import annotations

from dataclasses import dataclass

from execution_agent.broker_adapter import (
    BrokerAdapter,
    SandboxOrderRequest,
    ShioajiSandboxBrokerAdapter,
)
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
    reconciled: int = 0


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
    handled_call_keys: set[str] = set()
    for decision in decisions:
        handled_call_keys.add(decision.call_key)
        if decision.result != "called":
            counts.skipped_non_called += 1
            ledger.record_event(decision.call_key, "skipped_non_called", decision.result)
            continue
        existing_order = ledger.get_order(decision.call_key)
        if existing_order is not None:
            if ledger.order_needs_reconciliation(existing_order):
                _reconcile_existing_order(existing_order, active_broker, ledger, counts)
                continue
            counts.skipped_duplicate += 1
            ledger.record_event(decision.call_key, "skipped_duplicate", "sandbox order already exists")
            continue
        try:
            request = build_buy_order_request(decision, cash_budget=config.order_cash_per_trade)
        except OrderSizingError as exc:
            counts.sizing_rejected += 1
            ledger.record_event(decision.call_key, "sizing_rejected", str(exc))
            continue
        ledger.record_submit_intent(request)
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

    for order in ledger.list_orders():
        call_key = str(order.get("call_key") or "")
        if call_key in handled_call_keys or not ledger.order_needs_reconciliation(order):
            continue
        _reconcile_existing_order(order, active_broker, ledger, counts)

    return counts.to_summary()


@dataclass
class _MutableCounts:
    submitted: int = 0
    rejected: int = 0
    skipped_non_called: int = 0
    skipped_duplicate: int = 0
    sizing_rejected: int = 0
    broker_errors: int = 0
    reconciled: int = 0

    def to_summary(self) -> SandboxExecutionSummary:
        return SandboxExecutionSummary(
            submitted=self.submitted,
            rejected=self.rejected,
            skipped_non_called=self.skipped_non_called,
            skipped_duplicate=self.skipped_duplicate,
            sizing_rejected=self.sizing_rejected,
            broker_errors=self.broker_errors,
            reconciled=self.reconciled,
        )


def _safe_error_message(exc: Exception) -> str:
    return f"{type(exc).__name__}: {str(exc).splitlines()[0][:200]}"


def _request_from_order(order: dict) -> SandboxOrderRequest:
    return SandboxOrderRequest(
        call_key=str(order["call_key"]),
        market=str(order["market"]),
        stock_no=str(order["stock_no"]),
        stock_name=str(order["stock_name"]),
        signal_date=str(order["signal_date"]),
        open_price=float(order["open_price"]),
        entry_limit_price=float(order["entry_limit_price"]),
        cash_budget=float(order["cash_budget"]),
        quantity=int(order["quantity"]),
        price=float(order["price"]),
        order_type=str(order["order_type"]),
    )


def _reconcile_existing_order(
    order: dict,
    broker: BrokerAdapter,
    ledger: SandboxLedger,
    counts: _MutableCounts,
) -> None:
    request = _request_from_order(order)
    try:
        if str(order.get("status") or "").casefold() == "submitpending":
            result = broker.submit_buy_order(request)
        else:
            result = broker.refresh_buy_order(
                request,
                str(order.get("broker_order_id") or ""),
            )
    except Exception as exc:
        counts.broker_errors += 1
        ledger.record_event(request.call_key, "broker_reconcile_error", _safe_error_message(exc))
        return
    ledger.record_order(request, result)
    counts.reconciled += 1
