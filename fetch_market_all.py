#!/usr/bin/env python3
"""Batch tasks for fetching daily trades for every TWSE or TPEx listed company."""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from fetch_daily_trades import (
    FIELDS,
    fetch_tpex_month,
    fetch_twse_month,
    month_starts,
    parse_iso_date,
    request_json,
)


TWSE_LIST_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_LIST_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"


@dataclass(frozen=True)
class Symbol:
    code: str
    name: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch one year of daily trades for all stocks.")
    parser.add_argument("--market", required=True, choices=["twse", "tpex"])
    parser.add_argument("--start", help="Start date in YYYY-MM-DD. Defaults to one year before --end.")
    parser.add_argument("--end", default=date.today().isoformat(), help="End date in YYYY-MM-DD.")
    parser.add_argument("--years", type=float, default=1, help="Years to fetch when --start is omitted.")
    parser.add_argument("--output-dir", type=Path, help="Defaults to data/all_{market}.")
    parser.add_argument("--sleep-month", type=float, default=1.0, help="Seconds between monthly requests.")
    parser.add_argument("--sleep-stock", type=float, default=2.0, help="Seconds between stocks.")
    parser.add_argument("--jitter-month", type=float, default=0.0, help="Random extra seconds between monthly requests.")
    parser.add_argument("--jitter-stock", type=float, default=0.0, help="Random extra seconds between stocks.")
    parser.add_argument("--retries", type=int, default=3, help="Retries for a failed monthly request.")
    parser.add_argument("--limit", type=int, help="Fetch only the first N symbols for testing.")
    parser.add_argument("--symbols", type=Path, help="Optional CSV with code,name columns.")
    parser.add_argument("--resume", action="store_true", help="Skip stocks already marked done.")
    parser.add_argument("--dry-run", action="store_true", help="Only write/list the symbol universe.")
    parser.add_argument("--shard-count", type=int, default=1, help="Split symbols across this many workers.")
    parser.add_argument("--shard-index", type=int, default=0, help="Zero-based worker shard index.")
    return parser.parse_args()


def pick_value(item: dict[str, Any], candidates: list[str]) -> str:
    for key in candidates:
        if key in item and str(item[key]).strip():
            return str(item[key]).strip()
    return ""


def listed_stock_symbols(market: str) -> list[Symbol]:
    if market == "twse":
        data = request_json(TWSE_LIST_URL, {})
        symbols = [
            Symbol(
                code=pick_value(item, ["公司代號", "SecuritiesCompanyCode"]),
                name=pick_value(item, ["公司簡稱", "CompanyAbbreviation", "公司名稱"]),
            )
            for item in data
        ]
    else:
        data = request_json(TPEX_LIST_URL, {})
        symbols = [
            Symbol(
                code=pick_value(item, ["SecuritiesCompanyCode", "公司代號"]),
                name=pick_value(item, ["CompanyAbbreviation", "公司簡稱", "CompanyName"]),
            )
            for item in data
        ]

    return sorted(
        [
            symbol
            for symbol in symbols
            if re.fullmatch(r"\d{4}", symbol.code) and symbol.name
        ],
        key=lambda symbol: symbol.code,
    )


def read_symbols(path: Path) -> list[Symbol]:
    with path.open("r", encoding="utf-8-sig", newline="") as csvfile:
        reader = csv.DictReader(csvfile)
        return [
            Symbol(code=row["code"].strip(), name=row.get("name", "").strip())
            for row in reader
            if row.get("code", "").strip()
        ]


def write_symbols(path: Path, symbols: list[Symbol]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=["code", "name"])
        writer.writeheader()
        for symbol in symbols:
            writer.writerow({"code": symbol.code, "name": symbol.name})


def completed_from_csvs(output_dir: Path) -> set[str]:
    done: set[str] = set()
    if not output_dir.exists():
        return done
    for path in output_dir.glob("*.csv"):
        if path.name.startswith("_"):
            continue
        done.add(path.name.split("_", 1)[0])
    return done


def load_checkpoint(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"done": [], "failed": []}
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_checkpoint(checkpoint: dict[str, Any]) -> dict[str, Any]:
    done = set(checkpoint.get("done", []))
    checkpoint["failed"] = [
        item for item in checkpoint.get("failed", []) if item.get("code") not in done
    ]
    checkpoint["done"] = sorted(done)
    return checkpoint


def save_checkpoint(path: Path, checkpoint: dict[str, Any]) -> None:
    path.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def polite_sleep(base_seconds: float, jitter_seconds: float) -> None:
    time.sleep(base_seconds + random.uniform(0, max(0.0, jitter_seconds)))


def fetch_symbol(
    market: str,
    symbol: Symbol,
    start: date,
    end: date,
    sleep_month: float,
    jitter_month: float,
    retries: int,
) -> list[dict[str, Any]]:
    fetch_month = fetch_twse_month if market == "twse" else fetch_tpex_month
    rows: list[dict[str, Any]] = []
    for month in month_starts(start, end):
        for attempt in range(1, retries + 2):
            try:
                rows.extend(fetch_month(symbol.code, symbol.name, month))
                break
            except Exception as exc:
                if "沒有符合條件的資料" in str(exc):
                    break
                if attempt > retries:
                    raise
                polite_sleep(sleep_month * attempt, jitter_month * attempt)
        polite_sleep(sleep_month, jitter_month)
    rows = [row for row in rows if start.isoformat() <= row["date"] <= end.isoformat()]
    rows.sort(key=lambda row: row["date"])
    return rows


def main() -> int:
    args = parse_args()
    end = parse_iso_date(args.end)
    start = parse_iso_date(args.start) if args.start else end - timedelta(days=round(365 * args.years))
    output_dir = args.output_dir or Path("data") / f"all_{args.market}"
    if args.shard_count < 1:
        raise SystemExit("--shard-count must be at least 1")
    if args.shard_index < 0 or args.shard_index >= args.shard_count:
        raise SystemExit("--shard-index must be between 0 and --shard-count - 1")
    checkpoint_name = "_checkpoint.json" if args.shard_count == 1 else f"_checkpoint_{args.shard_index:02d}_of_{args.shard_count:02d}.json"
    checkpoint_path = output_dir / checkpoint_name
    symbols_path = output_dir / "_symbols.csv"

    symbols = read_symbols(args.symbols) if args.symbols else listed_stock_symbols(args.market)
    if args.limit:
        symbols = symbols[: args.limit]
    if args.shard_count > 1:
        symbols = [symbol for offset, symbol in enumerate(symbols) if offset % args.shard_count == args.shard_index]

    output_dir.mkdir(parents=True, exist_ok=True)
    write_symbols(symbols_path, symbols)
    print(f"{args.market.upper()} symbols: {len(symbols)}")
    if args.shard_count > 1:
      print(f"Shard: {args.shard_index + 1}/{args.shard_count}")
    print(f"Universe written to {symbols_path}")
    if args.dry_run:
        return 0

    checkpoint = normalize_checkpoint(load_checkpoint(checkpoint_path))
    done = set(checkpoint.get("done", [])) if args.resume else set()
    if args.resume:
        done |= completed_from_csvs(output_dir)
    failed: list[dict[str, str]] = checkpoint.get("failed", [])

    for index, symbol in enumerate(symbols, start=1):
        if symbol.code in done:
            print(f"[{index}/{len(symbols)}] skip {symbol.code} {symbol.name}")
            continue

        print(f"[{index}/{len(symbols)}] fetch {symbol.code} {symbol.name}")
        try:
            rows = fetch_symbol(
                args.market,
                symbol,
                start,
                end,
                args.sleep_month,
                args.jitter_month,
                args.retries,
            )
            write_csv(output_dir / f"{symbol.code}_{start}_{end}.csv", rows)
            done.add(symbol.code)
            failed = [item for item in failed if item.get("code") != symbol.code]
            checkpoint["done"] = sorted(done)
            checkpoint["failed"] = failed
            save_checkpoint(checkpoint_path, checkpoint)
            print(f"  wrote {len(rows)} rows")
        except Exception as exc:
            message = str(exc)
            failed.append({"code": symbol.code, "name": symbol.name, "error": message})
            checkpoint["failed"] = failed
            checkpoint["done"] = sorted(done)
            save_checkpoint(checkpoint_path, checkpoint)
            print(f"  failed: {message}")
        polite_sleep(args.sleep_stock, args.jitter_stock)

    print(f"Done: {len(done)}; failed: {len(failed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
