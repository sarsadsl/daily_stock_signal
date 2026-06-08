#!/usr/bin/env python3
"""Compare signal-day close entries with next-trading-day open entries."""

from __future__ import annotations

import csv
import json
import random
from collections import defaultdict
from pathlib import Path


CAPITAL_PER_TRADE = 100_000
RANDOM_SEED = 2455
SAMPLE_SIZE = 10
TRADE_PATH = Path("reports/backtest_trades.csv")
DATA_DIRS = [Path("data/all_twse"), Path("data/all_tpex"), Path("data")]
DETAIL_PATH = Path("reports/next_day_entry_compare.csv")
SUMMARY_PATH = Path("reports/next_day_entry_compare_summary.csv")
JSON_PATH = Path("reports/next_day_entry_compare_summary.json")


def to_float(value: str) -> float:
    return float(value.replace(",", "").strip())


def read_trades() -> list[dict[str, str]]:
    with TRADE_PATH.open("r", encoding="utf-8-sig", newline="") as csvfile:
        return list(csv.DictReader(csvfile))


def find_price_file(market: str, stock_no: str) -> Path | None:
    candidates = []
    for directory in DATA_DIRS:
        if not directory.exists():
            continue
        candidates.extend(sorted(directory.glob(f"{stock_no}_*.csv")))
        candidates.extend(sorted(directory.glob(f"{market}_{stock_no}_*.csv")))
    return candidates[0] if candidates else None


def read_prices(path: Path) -> list[dict[str, object]]:
    rows = []
    with path.open("r", encoding="utf-8-sig", newline="") as csvfile:
        for row in csv.DictReader(csvfile):
            try:
                rows.append(
                    {
                        "date": row["date"],
                        "open": to_float(row["open"]),
                        "high": to_float(row["high"]),
                        "low": to_float(row["low"]),
                        "close": to_float(row["close"]),
                    }
                )
            except (KeyError, ValueError):
                continue
    rows.sort(key=lambda row: str(row["date"]))
    return rows


def stock_totals(trades: list[dict[str, str]]) -> dict[tuple[str, str, str], float]:
    totals: dict[tuple[str, str, str], float] = defaultdict(float)
    for trade in trades:
        key = (trade["market"], trade["stock_no"], trade["stock_name"])
        totals[key] += float(trade["return_pct"])
    return totals


def sample_stocks(totals: dict[tuple[str, str, str], float]) -> list[tuple[str, str, str, str, float]]:
    rng = random.Random(RANDOM_SEED)
    winners = [(*key, value) for key, value in totals.items() if value > 0]
    losers = [(*key, value) for key, value in totals.items() if value < 0]
    winners.sort(key=lambda item: item[1])
    losers.sort(key=lambda item: item[1])
    selected_winners = rng.sample(winners, min(SAMPLE_SIZE, len(winners)))
    selected_losers = rng.sample(losers, min(SAMPLE_SIZE, len(losers)))
    return [("positive", *item) for item in selected_winners] + [("negative", *item) for item in selected_losers]


def next_day_trade(trade: dict[str, str], prices: list[dict[str, object]]) -> dict[str, object] | None:
    index_by_date = {str(row["date"]): index for index, row in enumerate(prices)}
    signal_index = index_by_date.get(trade["entry_date"])
    if signal_index is None or signal_index + 1 >= len(prices):
        return None
    entry_index = signal_index + 1
    entry_row = prices[entry_index]
    entry_price = float(entry_row["open"])
    stop_price = entry_price * 0.85

    for cursor in range(entry_index, len(prices)):
        row = prices[cursor]
        if float(row["low"]) <= stop_price:
            return {
                "next_entry_date": row["date"] if cursor == entry_index else entry_row["date"],
                "next_entry_price": entry_price,
                "next_exit_date": row["date"],
                "next_exit_price": stop_price,
                "next_exit_reason": "停損",
                "next_return_pct": stop_price / entry_price - 1,
            }

    last = prices[-1]
    return {
        "next_entry_date": entry_row["date"],
        "next_entry_price": entry_price,
        "next_exit_date": last["date"],
        "next_exit_price": float(last["close"]),
        "next_exit_reason": "期末估值",
        "next_return_pct": float(last["close"]) / entry_price - 1,
    }


def aggregate(rows: list[dict[str, object]]) -> dict[str, object]:
    trade_count = len(rows)
    signal_sum = sum(float(row["signal_return_pct"]) for row in rows)
    next_sum = sum(float(row["next_return_pct"]) for row in rows)
    return {
        "trades": trade_count,
        "signal_invested": trade_count * CAPITAL_PER_TRADE,
        "signal_pnl": signal_sum * CAPITAL_PER_TRADE,
        "signal_return_rate": signal_sum / trade_count if trade_count else 0,
        "next_pnl": next_sum * CAPITAL_PER_TRADE,
        "next_return_rate": next_sum / trade_count if trade_count else 0,
        "return_rate_diff": (next_sum - signal_sum) / trade_count if trade_count else 0,
        "next_stopped": sum(1 for row in rows if row["next_exit_reason"] == "停損"),
        "signal_stopped": sum(1 for row in rows if row["signal_exit_reason"] == "停損"),
    }


def main() -> int:
    trades = read_trades()
    totals = stock_totals(trades)
    selected = sample_stocks(totals)
    selected_keys = {(market, stock_no) for _, market, stock_no, _, _ in selected}
    selected_group = {(market, stock_no): group for group, market, stock_no, _, _ in selected}
    selected_total = {(market, stock_no): total for _, market, stock_no, _, total in selected}
    price_cache: dict[tuple[str, str], list[dict[str, object]]] = {}
    detail_rows = []

    for trade in trades:
        key = (trade["market"], trade["stock_no"])
        if key not in selected_keys:
            continue
        if key not in price_cache:
            path = find_price_file(*key)
            if path is None:
                continue
            price_cache[key] = read_prices(path)
        next_trade = next_day_trade(trade, price_cache[key])
        if next_trade is None:
            continue
        detail_rows.append(
            {
                "sample_group": selected_group[key],
                "market": trade["market"],
                "stock_no": trade["stock_no"],
                "stock_name": trade["stock_name"],
                "stock_total_return_sum": selected_total[key],
                "strategy": trade["strategy"],
                "signal_date": trade["entry_date"],
                "signal_entry_price": trade["entry_price"],
                "signal_exit_date": trade["exit_date"],
                "signal_exit_price": trade["exit_price"],
                "signal_exit_reason": trade["exit_reason"],
                "signal_return_pct": float(trade["return_pct"]),
                **next_trade,
                "return_pct_diff": float(next_trade["next_return_pct"]) - float(trade["return_pct"]),
            }
        )

    DETAIL_PATH.parent.mkdir(exist_ok=True)
    fieldnames = [
        "sample_group",
        "market",
        "stock_no",
        "stock_name",
        "stock_total_return_sum",
        "strategy",
        "signal_date",
        "signal_entry_price",
        "signal_exit_date",
        "signal_exit_price",
        "signal_exit_reason",
        "signal_return_pct",
        "next_entry_date",
        "next_entry_price",
        "next_exit_date",
        "next_exit_price",
        "next_exit_reason",
        "next_return_pct",
        "return_pct_diff",
    ]
    with DETAIL_PATH.open("w", encoding="utf-8-sig", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(detail_rows)

    summary_rows = []
    for key in sorted({(row["sample_group"], row["market"], row["stock_no"], row["stock_name"]) for row in detail_rows}):
        group, market, stock_no, stock_name = key
        stock_rows = [row for row in detail_rows if (row["sample_group"], row["market"], row["stock_no"], row["stock_name"]) == key]
        summary_rows.append(
            {
                "sample_group": group,
                "market": market,
                "stock_no": stock_no,
                "stock_name": stock_name,
                **aggregate(stock_rows),
            }
        )
    total_summary = aggregate(detail_rows)

    with SUMMARY_PATH.open("w", encoding="utf-8-sig", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=list(summary_rows[0].keys()) if summary_rows else [])
        if summary_rows:
            writer.writeheader()
            writer.writerows(summary_rows)

    JSON_PATH.write_text(
        json.dumps(
            {
                "random_seed": RANDOM_SEED,
                "sample_size_each_group": SAMPLE_SIZE,
                "assumption": "訊號日版本用原本收盤進場；隔天版本用下一個交易日開盤進場，停損以隔天進場價-15%重算。",
                "total": total_summary,
                "by_group": {
                    group: aggregate([row for row in detail_rows if row["sample_group"] == group])
                    for group in ["positive", "negative"]
                },
                "summary_csv": str(SUMMARY_PATH),
                "detail_csv": str(DETAIL_PATH),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(JSON_PATH.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
