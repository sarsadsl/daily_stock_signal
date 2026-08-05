"""Resolve Taiwan market trading dates from the official TWSE calendar."""

from __future__ import annotations

import argparse
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fetch_daily_trades import parse_iso_date, request_json


TAIPEI_TZ = timezone(timedelta(hours=8), name="Asia/Taipei")
TWSE_HOLIDAY_URL = "https://www.twse.com.tw/holidaySchedule/holidaySchedule"
TRADING_DAY_MARKERS = ("開始交易", "最後交易日")
CALENDAR_REQUEST_ATTEMPTS = 3
CALENDAR_RETRY_DELAY_SECONDS = 5


def resolve_target_date(value: str, now: datetime | None = None) -> date:
    if value:
        return parse_iso_date(value)
    return (now or datetime.now(TAIPEI_TZ)).date()


def fetch_twse_calendar(year: int) -> list[list[str]]:
    for attempt in range(1, CALENDAR_REQUEST_ATTEMPTS + 1):
        try:
            payload: dict[str, Any] = request_json(
                TWSE_HOLIDAY_URL,
                {"response": "json", "queryYear": str(year - 1911)},
            )
            break
        except RuntimeError:
            if attempt == CALENDAR_REQUEST_ATTEMPTS:
                raise
            delay = CALENDAR_RETRY_DELAY_SECONDS * attempt
            print(
                f"TWSE holiday calendar request failed (attempt "
                f"{attempt}/{CALENDAR_REQUEST_ATTEMPTS}); retrying in {delay}s."
            )
            time.sleep(delay)

    if payload.get("stat") != "ok":
        raise RuntimeError(f"TWSE holiday calendar returned {payload.get('stat')!r}.")
    return payload.get("data", [])


def is_twse_trading_day(target_date: date) -> bool:
    if target_date.weekday() >= 5:
        return False

    entries = [
        row
        for row in fetch_twse_calendar(target_date.year)
        if row and row[0] == target_date.isoformat()
    ]
    if not entries:
        return True

    return any(
        any(marker in " ".join(str(value) for value in row[1:]) for marker in TRADING_DAY_MARKERS)
        for row in entries
    )


def write_github_output(path: Path, target_date: date, is_trading_day: bool) -> None:
    with path.open("a", encoding="utf-8") as output:
        output.write(f"target_date={target_date.isoformat()}\n")
        output.write(f"is_trading_day={'true' if is_trading_day else 'false'}\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Resolve whether a Taiwan market date is an official TWSE trading day."
    )
    parser.add_argument("--date", default="", help="Target date in YYYY-MM-DD. Defaults to today in Asia/Taipei.")
    parser.add_argument("--github-output", type=Path, help="Optional GitHub Actions output file.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    target_date = resolve_target_date(args.date)
    is_trading_day = is_twse_trading_day(target_date)
    print(f"Target market date: {target_date.isoformat()}")
    print(f"TWSE trading day: {'yes' if is_trading_day else 'no'}")
    if args.github_output:
        write_github_output(args.github_output, target_date, is_trading_day)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
