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
            return SandboxOrderResult(
                call_key=request.call_key,
                accepted=True,
                broker_order_id=_trade_order_id(trade),
                submitted_at=datetime.now().astimezone().isoformat(),
                message="accepted",
            )
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
