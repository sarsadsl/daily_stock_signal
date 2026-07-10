from __future__ import annotations

from execution_agent.broker_adapter import SandboxOrderRequest
from execution_agent.open_entry_core import OpenEntryDecision


class OrderSizingError(ValueError):
    pass


def build_buy_order_request(decision: OpenEntryDecision, cash_budget: float) -> SandboxOrderRequest:
    if decision.result != "called":
        raise OrderSizingError("Only called decisions can be converted into sandbox buy orders")
    if cash_budget <= 0:
        raise OrderSizingError("cash_budget must be positive")
    if decision.open_price <= 0:
        raise OrderSizingError("open_price must be positive")

    quantity = int(cash_budget // decision.open_price)
    if quantity <= 0:
        raise OrderSizingError("Calculated quantity must be at least 1")

    return SandboxOrderRequest(
        call_key=decision.call_key,
        market=decision.market,
        stock_no=decision.stock_no,
        stock_name=decision.stock_name,
        signal_date=decision.signal_date,
        open_price=decision.open_price,
        entry_limit_price=decision.entry_limit_price,
        cash_budget=float(cash_budget),
        quantity=quantity,
        price=decision.open_price,
        order_type="sandbox_buy_open",
    )
