from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any


PENDING_NEXT_OPEN_STATUS = "待次日開盤"


@dataclass(frozen=True)
class PendingOpenEntry:
    market: str
    stock_no: str
    stock_name: str
    signal_date: str
    entry_limit_price: float
    signal_close: float
    unit_type: str
    addon_number: int | None


def load_tracking_payload_from_text(raw_text: str) -> dict[str, Any]:
    return json.loads(raw_text)


def select_pending_open_entries(payload: dict[str, Any], signal_date: str) -> list[PendingOpenEntry]:
    rows = payload.get("tracking", {}).get("formal_forward_records", [])
    selected: list[PendingOpenEntry] = []
    for row in rows:
        if str(row.get("status") or "") != PENDING_NEXT_OPEN_STATUS:
            continue
        if str(row.get("signal_date") or "") != signal_date:
            continue
        entry_limit_price = row.get("entry_limit_price")
        if entry_limit_price in {None, ""}:
            continue
        selected.append(
            PendingOpenEntry(
                market=str(row.get("market") or "").upper(),
                stock_no=str(row.get("stock_no") or ""),
                stock_name=str(row.get("stock_name") or ""),
                signal_date=str(row.get("signal_date") or ""),
                entry_limit_price=float(entry_limit_price),
                signal_close=float(row.get("signal_close") or 0.0),
                unit_type=str(row.get("unit_type") or "base"),
                addon_number=row.get("addon_number"),
            )
        )
    return selected
