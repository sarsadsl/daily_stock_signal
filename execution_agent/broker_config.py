from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os


class BrokerConfigError(ValueError):
    pass


@dataclass(frozen=True)
class BrokerConfig:
    broker_mode: str
    sandbox_only: bool
    shioaji_api_key: str | None
    shioaji_secret_key: str | None
    order_cash_per_trade: float = 100000.0
    order_lot_mode: str = "common_lot_round_down"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "BrokerConfig":
        env = environ if environ is not None else os.environ
        broker_mode = str(env.get("BROKER_MODE") or "noop").strip().lower()
        if broker_mode not in {"noop", "sandbox", "live"}:
            raise BrokerConfigError(f"Unsupported BROKER_MODE: {broker_mode}")
        if broker_mode == "live":
            raise BrokerConfigError("BROKER_MODE=live is not supported in Phase 2")

        sandbox_only = str(env.get("SANDBOX_ONLY") or "").strip() == "1"
        api_key = _blank_to_none(env.get("SHIOAJI_API_KEY"))
        secret_key = _blank_to_none(env.get("SHIOAJI_SECRET_KEY"))
        cash_per_trade = _parse_cash_budget(env.get("ORDER_CASH_PER_TRADE"))
        order_lot_mode = str(env.get("ORDER_LOT_MODE") or "common_lot_round_down").strip()
        if order_lot_mode != "common_lot_round_down":
            raise BrokerConfigError(f"Unsupported ORDER_LOT_MODE: {order_lot_mode}")

        if broker_mode == "sandbox":
            if not sandbox_only:
                raise BrokerConfigError("SANDBOX_ONLY=1 is required for sandbox broker mode")
            if not api_key:
                raise BrokerConfigError("SHIOAJI_API_KEY is required for sandbox broker mode")
            if not secret_key:
                raise BrokerConfigError("SHIOAJI_SECRET_KEY is required for sandbox broker mode")

        return cls(
            broker_mode=broker_mode,
            sandbox_only=sandbox_only,
            shioaji_api_key=api_key,
            shioaji_secret_key=secret_key,
            order_cash_per_trade=cash_per_trade,
            order_lot_mode=order_lot_mode,
        )

    def should_submit_orders(self) -> bool:
        return self.broker_mode == "sandbox" and self.sandbox_only


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _parse_cash_budget(value: str | None) -> float:
    if value is None or str(value).strip() == "":
        return 100000.0
    parsed = float(value)
    if parsed <= 0:
        raise BrokerConfigError("ORDER_CASH_PER_TRADE must be positive")
    return parsed
