from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from execution_agent.broker_config import BrokerConfig


@dataclass(frozen=True)
class SandboxOrderRequest:
    call_key: str
    market: str
    stock_no: str
    stock_name: str
    signal_date: str
    open_price: float
    entry_limit_price: float
    cash_budget: float
    quantity: int
    price: float
    order_type: str


@dataclass(frozen=True)
class SandboxOrderResult:
    call_key: str
    accepted: bool
    broker_order_id: str
    submitted_at: str
    message: str
    status: str = ""
    filled_quantity: int = 0
    average_fill_price: float | None = None


class BrokerAdapter:
    def submit_buy_order(self, request: SandboxOrderRequest) -> SandboxOrderResult:
        raise NotImplementedError


class NoopBrokerAdapter(BrokerAdapter):
    def submit_buy_order(self, request: SandboxOrderRequest) -> SandboxOrderResult:
        return SandboxOrderResult(
            call_key=request.call_key,
            accepted=False,
            broker_order_id="",
            submitted_at=datetime.now().astimezone().isoformat(),
            message="noop broker adapter did not submit order",
            status="Noop",
        )


class ShioajiSandboxBrokerAdapter(BrokerAdapter):
    def __init__(self, config: BrokerConfig) -> None:
        self.config = config

    def submit_buy_order(self, request: SandboxOrderRequest) -> SandboxOrderResult:
        import shioaji as sj

        api = sj.Shioaji(simulation=True)
        try:
            api.login(
                api_key=self.config.shioaji_api_key or "",
                secret_key=self.config.shioaji_secret_key or "",
            )
            contract = api.Contracts.Stocks[request.stock_no]
            order = api.Order(
                price=request.price,
                quantity=_shioaji_quantity(request.quantity),
                action=sj.constant.Action.Buy,
                price_type=sj.constant.StockPriceType.LMT,
                order_type=sj.constant.OrderType.ROD,
                order_lot=_shioaji_lot(request.quantity, sj),
                account=api.stock_account,
            )
            trade = api.place_order(contract, order)
            api.update_status(trade=trade)
            return _result_from_trade(request, trade)
        finally:
            api.logout()


def _shioaji_quantity(quantity: int) -> int:
    if quantity >= 1000:
        return max(1, quantity // 1000)
    return quantity


def _shioaji_lot(quantity: int, shioaji_module: Any) -> Any:
    if quantity >= 1000:
        return shioaji_module.constant.StockOrderLot.Common
    return shioaji_module.constant.StockOrderLot.Odd


def _trade_order_id(trade: Any) -> str:
    order = getattr(trade, "order", None)
    if order is not None:
        order_id = getattr(order, "id", None)
        if order_id:
            return str(order_id)
    status = getattr(trade, "status", None)
    if status is not None:
        order_id = getattr(status, "id", None)
        if order_id:
            return str(order_id)
    return ""


def _result_from_trade(request: SandboxOrderRequest, trade: Any) -> SandboxOrderResult:
    status = getattr(trade, "status", None)
    raw_status = _enum_value(getattr(status, "status", "")) or "Unknown"
    operation = getattr(trade, "operation", None)
    operation_code = str(getattr(operation, "op_code", "") or "").strip()
    failed_statuses = {"failed", "cancelled", "inactive"}
    accepted = raw_status.casefold() not in failed_statuses and operation_code in {"", "00"}

    broker_quantity = int(getattr(status, "deal_quantity", 0) or 0)
    filled_quantity = broker_quantity * 1000 if request.quantity >= 1000 else broker_quantity
    filled_quantity = min(request.quantity, filled_quantity)
    average_fill_price = _average_fill_price(status, request)

    operation_message = str(getattr(operation, "op_msg", "") or "").strip()
    status_message = str(getattr(status, "msg", "") or "").strip()
    message = operation_message or status_message or raw_status
    return SandboxOrderResult(
        call_key=request.call_key,
        accepted=accepted,
        broker_order_id=_trade_order_id(trade),
        submitted_at=datetime.now().astimezone().isoformat(),
        message=message,
        status=raw_status,
        filled_quantity=filled_quantity,
        average_fill_price=average_fill_price,
    )


def _enum_value(value: Any) -> str:
    raw = getattr(value, "value", value)
    text = str(raw or "").strip()
    return text.rsplit(".", 1)[-1]


def _average_fill_price(status: Any, request: SandboxOrderRequest) -> float | None:
    deals = list(getattr(status, "deals", None) or [])
    weighted_total = 0.0
    total_quantity = 0
    for deal in deals:
        quantity = int(getattr(deal, "quantity", 0) or 0)
        price = float(getattr(deal, "price", 0.0) or 0.0)
        if quantity > 0 and price > 0:
            weighted_total += price * quantity
            total_quantity += quantity
    if total_quantity:
        return weighted_total / total_quantity
    if int(getattr(status, "deal_quantity", 0) or 0) > 0:
        return request.price
    return None
