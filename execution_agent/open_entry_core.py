from __future__ import annotations

from dataclasses import dataclass

from execution_agent.tracking_source import PendingOpenEntry


@dataclass(frozen=True)
class OpenEntryDecision:
    call_key: str
    market: str
    stock_no: str
    stock_name: str
    signal_date: str
    entry_limit_price: float
    signal_close: float
    open_price: float
    result: str


def build_open_entry_decision(entry: PendingOpenEntry, open_price: float) -> OpenEntryDecision:
    addon_part = "-" if entry.addon_number in {None, ""} else str(entry.addon_number)
    call_key = f"{entry.market}:{entry.stock_no}:{entry.signal_date}:{entry.unit_type}:{addon_part}"
    result = "called" if open_price <= entry.entry_limit_price else "open_failed"
    return OpenEntryDecision(
        call_key=call_key,
        market=entry.market,
        stock_no=entry.stock_no,
        stock_name=entry.stock_name,
        signal_date=entry.signal_date,
        entry_limit_price=entry.entry_limit_price,
        signal_close=entry.signal_close,
        open_price=open_price,
        result=result,
    )
