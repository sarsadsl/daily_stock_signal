from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

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
        raise NotImplementedError("Shioaji sandbox submission is implemented in the executor task")
