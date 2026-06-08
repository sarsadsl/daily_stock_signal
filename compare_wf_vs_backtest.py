#!/usr/bin/env python3
"""Compare walk-forward drill results with regular backtests on the same sample."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable


CAPITAL_PER_TRADE = 100_000
WF_SUMMARY_PATH = Path("reports/walk_forward_drill_summary.csv")
WF_DETAIL_PATH = Path("reports/walk_forward_drill_trades.csv")
BACKTEST_DETAIL_PATH = Path("reports/backtest_trades.csv")
OUTPUT_CSV = Path("reports/wf_vs_backtest_compare.csv")
OUTPUT_JSON = Path("reports/wf_vs_backtest_compare.json")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as csvfile:
        return list(csv.DictReader(csvfile))


def safe_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def summarize(trades: Iterable[dict[str, object]]) -> dict[str, object]:
    rows = list(trades)
    return_sum = sum(safe_float(row.get("return_pct")) for row in rows)
    trades_count = len(rows)
    invested = trades_count * CAPITAL_PER_TRADE
    pnl = return_sum * CAPITAL_PER_TRADE
    return {
        "trades": trades_count,
        "invested": invested,
        "pnl": pnl,
        "total_return": pnl / invested if invested else 0.0,
        "win_rate": sum(1 for row in rows if safe_float(row.get("return_pct")) > 0) / trades_count if trades_count else 0.0,
        "stopped": sum(1 for row in rows if row.get("exit_reason") == "停損"),
        "trailing_take_profit": sum(1 for row in rows if row.get("exit_reason") == "加碼移動停利7%"),
        "open_valued": sum(1 for row in rows if row.get("exit_reason") == "期末估值"),
    }


def main() -> int:
    wf_summary = read_csv(WF_SUMMARY_PATH)
    wf_detail = read_csv(WF_DETAIL_PATH)
    backtest_detail = read_csv(BACKTEST_DETAIL_PATH)

    wf_trades_by_sample: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in wf_detail:
        wf_trades_by_sample[(row["stock_no"], row["chosen_strategy"], row["drill_today"])].append(row)

    full_by_stock_strategy: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in backtest_detail:
        full_by_stock_strategy[(row["stock_no"], row["strategy"])].append(row)

    compare_rows: list[dict[str, object]] = []
    for row in wf_summary:
        key = (row["stock_no"], row["chosen_strategy"])
        drill_today = row["drill_today"]
        full_trades = full_by_stock_strategy.get(key, [])
        full_after_today = [trade for trade in full_trades if trade["entry_date"] >= drill_today]
        wf_stats = summarize(wf_trades_by_sample.get((row["stock_no"], row["chosen_strategy"], drill_today), []))
        full_stats = summarize(full_trades)
        after_today_stats = summarize(full_after_today)
        compare_rows.append(
            {
                "market": row["market"],
                "stock_no": row["stock_no"],
                "stock_name": row["stock_name"],
                "chosen_strategy": row["chosen_strategy"],
                "drill_today": drill_today,
                "final_date": row["final_date"],
                "wf_trades": wf_stats["trades"],
                "wf_total_return": wf_stats["total_return"],
                "wf_win_rate": wf_stats["win_rate"],
                "wf_pnl": wf_stats["pnl"],
                "full_trades": full_stats["trades"],
                "full_total_return": full_stats["total_return"],
                "full_win_rate": full_stats["win_rate"],
                "full_pnl": full_stats["pnl"],
                "after_today_trades": after_today_stats["trades"],
                "after_today_total_return": after_today_stats["total_return"],
                "after_today_win_rate": after_today_stats["win_rate"],
                "after_today_pnl": after_today_stats["pnl"],
                "return_gap_full_minus_wf": safe_float(full_stats["total_return"]) - safe_float(wf_stats["total_return"]),
                "return_gap_after_today_minus_wf": safe_float(after_today_stats["total_return"])
                - safe_float(wf_stats["total_return"]),
            }
        )

    def aggregate(prefix: str, rows: list[dict[str, object]]) -> dict[str, object]:
        trades = sum(int(row[f"{prefix}_trades"]) for row in rows)
        pnl = sum(safe_float(row[f"{prefix}_pnl"]) for row in rows)
        invested = trades * CAPITAL_PER_TRADE
        weighted_wins = 0
        for row in rows:
            count = int(row[f"{prefix}_trades"])
            weighted_wins += safe_float(row[f"{prefix}_win_rate"]) * count
        return {
            "trades": trades,
            "invested": invested,
            "pnl": pnl,
            "total_return": pnl / invested if invested else 0.0,
            "win_rate": weighted_wins / trades if trades else 0.0,
        }

    summary = {
        "sample_rows": len(compare_rows),
        "unique_stocks": len({row["stock_no"] for row in compare_rows}),
        "duplicate_stocks": {
            stock_no: count
            for stock_no, count in Counter(row["stock_no"] for row in compare_rows).items()
            if count > 1
        },
        "wf": aggregate("wf", compare_rows),
        "full_same_stocks_chosen_strategy": aggregate("full", compare_rows),
        "full_after_drill_today_same_stocks_chosen_strategy": aggregate("after_today", compare_rows),
    }

    OUTPUT_CSV.parent.mkdir(exist_ok=True)
    with OUTPUT_CSV.open("w", encoding="utf-8-sig", newline="") as csvfile:
        fieldnames = list(compare_rows[0].keys()) if compare_rows else []
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(compare_rows)

    OUTPUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
