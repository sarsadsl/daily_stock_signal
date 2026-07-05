#!/usr/bin/env python3
"""Send MWP-C formal-tracking open-entry Telegram calls."""

from __future__ import annotations

import argparse
import json
import time
from datetime import date
from pathlib import Path
from typing import Any

from alert_signals import send_message
from fetch_daily_trades import request_json
from run_market_backtest import csv_files, read_rows


TRACKING_PATH = Path("reports/mwp_a_strategy_tracking.json")
CALL_LOG_PATH = Path("reports/mwp_c_open_entry_calls.json")
MIS_API_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
PENDING_NEXT_OPEN_STATUS = "待次日開盤"
MIS_MARKET_PREFIX = {"TWSE": "tse", "TPEX": "otc"}
MIS_MARKET_NAME = {"tse": "TWSE", "otc": "TPEX"}

TradingDates = dict[tuple[str, str], list[str]]


def load_tracking_payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_call_log(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"calls": []}
    return json.loads(path.read_text(encoding="utf-8"))


def write_call_log(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def record_call_key(record: dict[str, Any]) -> str:
    market = str(record.get("market") or "").upper()
    stock_no = str(record.get("stock_no") or "")
    signal_date = str(record.get("signal_date") or "")
    unit_type = str(record.get("unit_type") or "base")
    addon_number = record.get("addon_number")
    addon_part = "-" if addon_number in {None, ""} else str(addon_number)
    return f"{market}:{stock_no}:{signal_date}:{unit_type}:{addon_part}"


def build_trading_dates() -> TradingDates:
    trading_dates: TradingDates = {}
    for path in csv_files():
        rows = read_rows(path)
        if not rows:
            continue
        market = rows[-1].market.upper()
        stock_no = rows[-1].stock_no
        trading_dates[(market, stock_no)] = [row.date for row in rows]
    return trading_dates


def next_trading_date_for_record(record: dict[str, Any], trading_dates: TradingDates) -> str | None:
    market = str(record.get("market") or "").upper()
    stock_no = str(record.get("stock_no") or "")
    signal_date = str(record.get("signal_date") or "")
    dates = trading_dates.get((market, stock_no)) or []
    try:
        signal_index = dates.index(signal_date)
    except ValueError:
        return None
    next_index = signal_index + 1
    return dates[next_index] if next_index < len(dates) else None


def select_pending_open_call_candidates(
    records: list[dict[str, Any]],
    as_of_date: str,
    sent_log: dict[str, Any],
    trading_dates: TradingDates,
) -> list[dict[str, Any]]:
    sent_keys = {str(item.get("key")) for item in sent_log.get("calls", []) if item.get("key")}
    selected: list[dict[str, Any]] = []
    for record in records:
        if str(record.get("status") or "") != PENDING_NEXT_OPEN_STATUS:
            continue
        if not record.get("entry_limit_price"):
            continue
        if next_trading_date_for_record(record, trading_dates) != as_of_date:
            continue
        if record_call_key(record) in sent_keys:
            continue
        selected.append(record)
    return selected


def mis_channel_for_record(record: dict[str, Any]) -> str:
    market = str(record.get("market") or "").upper()
    stock_no = str(record.get("stock_no") or "")
    prefix = MIS_MARKET_PREFIX.get(market)
    if not prefix:
        raise ValueError(f"Unsupported market for MIS quote: {market}")
    return f"{prefix}_{stock_no}.tw"


def is_missing_quote_field(value: Any) -> bool:
    text = str(value or "").strip()
    return not text or set(text) == {"-"}


def fetch_realtime_open_snapshot(records: list[dict[str, Any]], target_date: date) -> dict[tuple[str, str], float]:
    if not records:
        return {}

    channels = [mis_channel_for_record(record) for record in records]
    payload = request_json(
        MIS_API_URL,
        {
            "ex_ch": "|".join(channels),
            "json": "1",
            "delay": "0",
            "_": str(int(time.time() * 1000)),
        },
    )
    target_date_text = target_date.strftime("%Y%m%d")
    snapshot: dict[tuple[str, str], float] = {}
    for item in payload.get("msgArray", []):
        if str(item.get("d") or "") != target_date_text:
            continue
        if is_missing_quote_field(item.get("o")):
            continue
        market = MIS_MARKET_NAME.get(str(item.get("ex") or "").casefold())
        stock_no = str(item.get("c") or "")
        if not market or not stock_no:
            continue
        snapshot[(market, stock_no)] = float(str(item["o"]).replace(",", "").strip())
    return snapshot


def wait_for_realtime_open_snapshot(
    records: list[dict[str, Any]],
    target_date: date,
    max_attempts: int,
    sleep_seconds: float,
) -> dict[tuple[str, str], float]:
    pending_records = list(records)
    snapshot: dict[tuple[str, str], float] = {}
    for attempt in range(max(1, max_attempts)):
        current = fetch_realtime_open_snapshot(pending_records, target_date)
        snapshot.update(current)
        if len(snapshot) >= len({(str(r.get("market") or "").upper(), str(r.get("stock_no") or "")) for r in records}):
            break
        if attempt == max(1, max_attempts) - 1:
            break
        pending_records = [
            record
            for record in pending_records
            if (str(record.get("market") or "").upper(), str(record.get("stock_no") or "")) not in snapshot
        ]
        if not pending_records:
            break
        time.sleep(sleep_seconds)
    return snapshot


def build_open_entry_call_decisions(
    records: list[dict[str, Any]],
    open_snapshot: dict[tuple[str, str], float],
) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    for record in records:
        key = (str(record.get("market") or "").upper(), str(record.get("stock_no") or ""))
        open_price = open_snapshot.get(key)
        if open_price is None:
            continue
        entry_limit_price = float(record.get("entry_limit_price") or 0)
        decisions.append(
            {
                **record,
                "key": record_call_key(record),
                "open_price": open_price,
                "entry_limit_price": entry_limit_price,
                "result": "called" if open_price <= entry_limit_price else "open_failed",
            }
        )
    return decisions


def render_open_entry_call_message(decision: dict[str, Any]) -> str:
    market = str(decision.get("market") or "").upper()
    stock_no = str(decision.get("stock_no") or "")
    stock_name = str(decision.get("stock_name") or "")
    signal_date = str(decision.get("signal_date") or "")
    signal_close = decision.get("signal_close", "-")
    entry_limit_price = decision.get("entry_limit_price", "-")
    open_price = decision.get("open_price", "-")
    return "\n".join(
        [
            "MWP-C 正式追蹤開盤進場提醒",
            f"{market} {stock_no} {stock_name}".strip(),
            f"訊號日 {signal_date}",
            f"D0 收盤 {signal_close}",
            f"進場上限 {entry_limit_price}",
            f"次日開盤 {open_price}",
            "符合正式追蹤次日開盤進場條件。",
        ]
    )


def run_open_entry_calls(
    as_of_date: date,
    dry_run: bool,
    markets: list[str],
    tracking_path: Path = TRACKING_PATH,
    call_log_path: Path = CALL_LOG_PATH,
    trading_dates: TradingDates | None = None,
    poll_attempts: int = 20,
    poll_interval_seconds: float = 15.0,
) -> list[dict[str, Any]]:
    payload = load_tracking_payload(tracking_path)
    sent_log = load_call_log(call_log_path)
    records = payload.get("tracking", {}).get("formal_forward_records", [])
    selected = select_pending_open_call_candidates(
        records,
        as_of_date=as_of_date.isoformat(),
        sent_log=sent_log,
        trading_dates=trading_dates or build_trading_dates(),
    )
    allowed_markets = {market.upper() for market in markets}
    if allowed_markets:
        selected = [record for record in selected if str(record.get("market") or "").upper() in allowed_markets]

    open_snapshot = wait_for_realtime_open_snapshot(
        selected,
        target_date=as_of_date,
        max_attempts=1 if dry_run else poll_attempts,
        sleep_seconds=poll_interval_seconds,
    )
    decisions = build_open_entry_call_decisions(selected, open_snapshot)

    if dry_run:
        for decision in decisions:
            print(
                f"[DRY-RUN] {decision['key']} {decision['result']} "
                f"open={decision['open_price']} limit={decision['entry_limit_price']}"
            )
        return decisions

    calls = sent_log.setdefault("calls", [])
    changed = False
    for decision in decisions:
        call_entry = {
            "key": decision["key"],
            "market": decision["market"],
            "stock_no": decision["stock_no"],
            "signal_date": decision["signal_date"],
            "unit_type": decision.get("unit_type"),
            "addon_number": decision.get("addon_number"),
            "checked_date": as_of_date.isoformat(),
            "open_price": decision["open_price"],
            "entry_limit_price": decision["entry_limit_price"],
            "result": decision["result"],
        }
        if decision["result"] == "called":
            sent_channels = send_message(render_open_entry_call_message(decision), channels={"telegram"})
            if "telegram" not in sent_channels:
                continue
            call_entry["sent_channels"] = sent_channels
        calls.append(call_entry)
        changed = True

    if changed:
        write_call_log(call_log_path, sent_log)
    return decisions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send MWP-C formal-tracking open-entry calls.")
    parser.add_argument("--as-of", help="Trading date in YYYY-MM-DD. Defaults to today.")
    parser.add_argument("--dry-run", action="store_true", help="Print decisions without sending Telegram or writing logs.")
    parser.add_argument("--market", default="twse,tpex", help="Comma-separated markets to fetch realtime opens for.")
    parser.add_argument("--poll-attempts", type=int, default=20, help="Maximum realtime polling attempts before giving up.")
    parser.add_argument("--poll-interval", type=float, default=15.0, help="Seconds to wait between polling attempts.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    as_of_date = date.fromisoformat(args.as_of) if args.as_of else date.today()
    markets = [item.strip().casefold() for item in args.market.split(",") if item.strip()]
    decisions = run_open_entry_calls(
        as_of_date=as_of_date,
        dry_run=args.dry_run,
        markets=markets,
        poll_attempts=args.poll_attempts,
        poll_interval_seconds=args.poll_interval,
    )
    if not decisions:
        print("No MWP-C formal-tracking open-entry decisions for this date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
