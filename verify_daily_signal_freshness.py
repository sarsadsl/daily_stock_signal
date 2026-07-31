from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from run_market_backtest import STRATEGIES, csv_files, prepare, read_rows


MIN_SIGNAL_VOLUME_SHARES = 1_000_000
REPORT_PATH = Path("reports/daily_signal_alert.csv")
TAIPEI_TZ = timezone(timedelta(hours=8), name="Asia/Taipei")


def resolve_expected_date(expected_date: str, now: datetime | None = None) -> tuple[str, datetime]:
    current = now or datetime.now(TAIPEI_TZ)
    return (expected_date or current.date().isoformat(), current)


def read_report_summary(report_path: Path) -> dict[str, Any]:
    if not report_path.exists():
        return {
            "report_exists": False,
            "latest_report_date": "",
            "report_row_count": 0,
        }

    with report_path.open("r", encoding="utf-8-sig", newline="") as csvfile:
        reader = csv.DictReader(csvfile)
        dates = [row.get("date", "") for row in reader if row.get("date")]

    latest_report_date = max(dates) if dates else ""
    return {
        "report_exists": True,
        "latest_report_date": latest_report_date,
        "report_row_count": len(dates),
    }


def summarize_latest_market() -> dict[str, Any]:
    latest_market_date = ""
    latest_rows: list[tuple[Any, list[Any]]] = []

    for path in csv_files():
        rows = read_rows(path)
        if len(rows) < 60:
            continue
        row = rows[-1]
        row_date = str(row.date)
        if row_date > latest_market_date:
            latest_market_date = row_date
            latest_rows = [(path, rows)]
        elif row_date == latest_market_date:
            latest_rows.append((path, rows))

    latest_symbol_count = len(latest_rows)
    volume_qualified_count = 0
    signal_match_count = 0

    for _, rows in latest_rows:
        row = rows[-1]
        if int(row.volume) < MIN_SIGNAL_VOLUME_SHARES:
            continue
        volume_qualified_count += 1
        indicators = prepare(rows)
        index = len(rows) - 1
        has_signal = any(
            signal(rows, indicators, index)
            for signal in STRATEGIES.values()
        )
        if has_signal:
            signal_match_count += 1

    return {
        "latest_market_date": latest_market_date,
        "latest_symbol_count": latest_symbol_count,
        "volume_qualified_count": volume_qualified_count,
        "signal_match_count": signal_match_count,
    }


def verify_freshness(
    expected_date: str,
    now: datetime | None = None,
    report_path: Path = REPORT_PATH,
    check_report: bool = True,
) -> dict[str, Any]:
    today, current = resolve_expected_date(expected_date, now=now)
    if current.weekday() >= 5:
        return {
            "expected_date": today,
            "skipped": True,
            "reason": "weekend",
        }

    result = {
        "expected_date": today,
        **summarize_latest_market(),
        **read_report_summary(report_path),
    }

    if result["latest_market_date"] != today:
        raise ValueError(
            f"Latest market date mismatch: expected {today}, got {result['latest_market_date']}."
        )
    if result["latest_symbol_count"] <= 0:
        raise ValueError("No latest-date symbols were found in synced market data.")
    if result["volume_qualified_count"] <= 0:
        raise ValueError("No latest-date symbols passed the volume gate.")
    if result["signal_match_count"] <= 0:
        raise ValueError("No latest-date signals were found after sync.")
    if check_report and not result["report_exists"]:
        raise ValueError(f"{report_path.as_posix()} was not generated.")
    if check_report and result["latest_report_date"] != today:
        raise ValueError(
            f"Latest report date mismatch: expected {today}, got {result['latest_report_date']}."
        )
    return result


def print_summary(result: dict[str, Any]) -> None:
    if result.get("skipped"):
        print(f"Weekend in Asia/Taipei; skipping freshness check for {result['expected_date']}.")
        return
    print(f"Expected market date: {result['expected_date']}")
    print(f"Latest market date: {result['latest_market_date']}")
    print(f"Latest-date symbols: {result['latest_symbol_count']}")
    print(f"Volume-qualified latest-date symbols: {result['volume_qualified_count']}")
    print(f"Latest-date signal matches: {result['signal_match_count']}")
    print(f"Report exists: {result['report_exists']}")
    print(f"Latest report date: {result['latest_report_date']}")
    print(f"Report rows with dates: {result['report_row_count']}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify that synced market data and generated signal reports are fresh."
    )
    parser.add_argument(
        "--expected-date",
        default="",
        help="Target market date in YYYY-MM-DD. Leave blank for today in Asia/Taipei.",
    )
    parser.add_argument(
        "--skip-report-check",
        action="store_true",
        help="Validate synced market data only; use before generating the report.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = verify_freshness(args.expected_date, check_report=not args.skip_report_check)
    except ValueError as exc:
        fallback_now = datetime.now(TAIPEI_TZ)
        today, _ = resolve_expected_date(args.expected_date, now=fallback_now)
        debug_result = {
            "expected_date": today,
            **summarize_latest_market(),
            **read_report_summary(REPORT_PATH),
        }
        print_summary(debug_result)
        print(str(exc))
        return 1

    print_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
