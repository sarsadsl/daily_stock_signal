from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
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

    def refresh_buy_order(
        self,
        request: SandboxOrderRequest,
        broker_order_id: str,
    ) -> SandboxOrderResult:
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

    def refresh_buy_order(
        self,
        request: SandboxOrderRequest,
        broker_order_id: str,
    ) -> SandboxOrderResult:
        return self.submit_buy_order(request)


class ShioajiSandboxBrokerAdapter(BrokerAdapter):
    def __init__(self, config: BrokerConfig, shioaji_module: Any | None = None) -> None:
        self.config = config
        self._shioaji_module = shioaji_module

    def submit_buy_order(self, request: SandboxOrderRequest) -> SandboxOrderResult:
        sj = self._load_shioaji()

        api = sj.Shioaji(simulation=True)
        try:
            api.login(
                api_key=self.config.shioaji_api_key or "",
                secret_key=self.config.shioaji_secret_key or "",
            )
            api.update_status(api.stock_account)
            existing_trade = _find_trade(
                api.list_trades(),
                broker_order_id="",
                custom_field=_order_custom_field(request.call_key),
            )
            if existing_trade is not None:
                return _result_from_trade(request, existing_trade)
            contract = api.Contracts.Stocks[request.stock_no]
            order = api.Order(
                price=request.price,
                quantity=_shioaji_quantity(request.quantity),
                action=sj.constant.Action.Buy,
                price_type=sj.constant.StockPriceType.LMT,
                order_type=sj.constant.OrderType.ROD,
                order_lot=_shioaji_lot(request.quantity, sj),
                account=api.stock_account,
                custom_field=_order_custom_field(request.call_key),
            )
            trade = api.place_order(contract, order)
            try:
                api.update_status(trade=trade)
            except Exception:
                pass
            return _result_from_trade(request, trade)
        finally:
            _safe_logout(api)

    def refresh_buy_order(
        self,
        request: SandboxOrderRequest,
        broker_order_id: str,
    ) -> SandboxOrderResult:
        sj = self._load_shioaji()
        api = sj.Shioaji(simulation=True)
        try:
            api.login(
                api_key=self.config.shioaji_api_key or "",
                secret_key=self.config.shioaji_secret_key or "",
            )
            api.update_status(api.stock_account)
            trade = _find_trade(
                api.list_trades(),
                broker_order_id=broker_order_id,
                custom_field=_order_custom_field(request.call_key),
            )
            if trade is None:
                raise RuntimeError(f"broker_order_not_found:{broker_order_id}")
            return _result_from_trade(request, trade)
        finally:
            _safe_logout(api)

    def _load_shioaji(self) -> Any:
        if self._shioaji_module is not None:
            return self._shioaji_module
        import shioaji as sj

        return sj


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
    accepted_statuses = {
        "pendingsubmit",
        "presubmitted",
        "submitted",
        "partfilled",
        "filling",
        "filled",
    }
    accepted = raw_status.casefold() in accepted_statuses and operation_code in {"", "00"}

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


def _order_custom_field(call_key: str) -> str:
    return hashlib.sha256(call_key.encode("utf-8")).hexdigest()[:6].upper()


def _find_trade(
    trades: list[Any],
    broker_order_id: str,
    custom_field: str,
) -> Any | None:
    for trade in trades:
        order = getattr(trade, "order", None)
        if broker_order_id and _trade_order_id(trade) == broker_order_id:
            return trade
        if str(getattr(order, "custom_field", "") or "").strip() == custom_field:
            return trade
    return None


def _safe_logout(api: Any) -> None:
    try:
        api.logout()
    except Exception:
        pass
