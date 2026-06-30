#!/usr/bin/env python3
"""Verify that the daily MWP-C radar is fully locked into forward records."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def latest_signal_date(path: Path) -> str:
    with path.open("r", encoding="utf-8-sig", newline="") as csvfile:
        dates = sorted(
            {
                str(row.get("date") or "")
                for row in csv.DictReader(csvfile)
                if row.get("date")
            }
        )
    if not dates:
        raise ValueError(f"No signal dates found in {path}")
    return dates[-1]


def candidate_record_ids(radar: dict[str, Any]) -> list[str]:
    record_ids: list[str] = []
    for row in radar.get("new_mother_candidates", []):
        record_ids.append(
            f"{str(row.get('market')).upper()}:{row.get('stock_no')}:"
            f"{row.get('signal_date') or row.get('date')}:base"
        )
    for row in radar.get("addon_candidates", []):
        mother_date = (
            row.get("mother_signal_date")
            or row.get("signal_date")
            or row.get("date")
        )
        addon_number = int(row.get("addon_number") or 1)
        record_ids.append(
            f"{str(row.get('market')).upper()}:{row.get('stock_no')}:"
            f"{mother_date}:addon:{addon_number}"
        )
    return record_ids


def verify_forward_records(
    expected_date: str,
    tracking: dict[str, Any],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    tracking_payload = tracking.get("tracking") or {}
    radar = tracking_payload.get("daily_mwp_c_radar") or {}
    tracking_dates = {
        str(tracking_payload.get("as_of_daily_signal_date") or ""),
        str(radar.get("as_of_date") or ""),
    }
    if tracking_dates != {expected_date}:
        raise ValueError(
            f"Tracking date mismatch: expected {expected_date}, got "
            f"{sorted(date for date in tracking_dates if date)}"
        )

    record_ids = [str(row.get("id") or "") for row in records]
    duplicate_ids = sorted(
        record_id
        for record_id, count in Counter(record_ids).items()
        if record_id and count > 1
    )
    if duplicate_ids:
        raise ValueError(f"Duplicate forward record IDs: {duplicate_ids}")

    expected_ids = candidate_record_ids(radar)
    missing_ids = sorted(set(expected_ids) - set(record_ids))
    if missing_ids:
        raise ValueError(f"Missing forward record IDs: {missing_ids}")

    return {
        "expected_date": expected_date,
        "mother_candidates": len(radar.get("new_mother_candidates", [])),
        "addon_candidates": len(radar.get("addon_candidates", [])),
        "candidate_records": len(expected_ids),
        "forward_records": len(records),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-date", default="")
    parser.add_argument(
        "--daily-report",
        type=Path,
        default=Path("reports/daily_signal_alert.csv"),
    )
    parser.add_argument(
        "--tracking",
        type=Path,
        default=Path("reports/mwp_a_strategy_tracking.json"),
    )
    parser.add_argument(
        "--forward-records",
        type=Path,
        default=Path("reports/mwp_c_forward_records.json"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    expected_date = args.expected_date or latest_signal_date(args.daily_report)
    result = verify_forward_records(
        expected_date,
        load_json(args.tracking),
        load_json(args.forward_records),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
