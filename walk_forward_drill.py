#!/usr/bin/env python3
"""Walk-forward signal drill on a random 20-stock sample.

The first half of each stock's data is used as a training window to choose
between the current TSMC and Phison strategies. The second half is the test
window. A random date inside the test window is treated as "today's close";
from that date forward, the simulator checks signals one day at a time and
marks open trades to the final available close.
"""

from __future__ import annotations

import csv
import json
import random
from pathlib import Path

import run_market_backtest as rb


RANDOM_SEED = 20260530
SAMPLE_SIZE = 20
CAPITAL_PER_TRADE = 100_000
DATA_DIRS = [Path("data/all_twse"), Path("data/all_tpex")]
DETAIL_PATH = Path("reports/walk_forward_drill_trades.csv")
SUMMARY_PATH = Path("reports/walk_forward_drill_summary.csv")
JSON_PATH = Path("reports/walk_forward_drill_summary.json")
STRATEGY_NAMES = list(rb.STRATEGIES.keys())


def csv_files() -> list[Path]:
    files: list[Path] = []
    for directory in DATA_DIRS:
        if not directory.exists():
            continue
        files.extend(path for path in sorted(directory.glob("*.csv")) if not path.name.startswith("_"))
    return files


def avg_return(trades: list[dict[str, object]]) -> float:
    if not trades:
        return 0.0
    return sum(float(trade["return_pct"]) for trade in trades) / len(trades)


def choose_strategy(train_rows: list[rb.Row]) -> tuple[str, dict[str, object]]:
    scores = {}
    for strategy_name in rb.STRATEGIES:
        trades = rb.backtest(train_rows, strategy_name)
        scores[strategy_name] = {
            "trades": len(trades),
            "avg_return": avg_return(trades),
            "total_return_sum": sum(float(trade["return_pct"]) for trade in trades),
        }
    if all(score["trades"] == 0 for score in scores.values()):
        chosen = STRATEGY_NAMES[1] if train_rows[0].market == "tpex" and len(STRATEGY_NAMES) > 1 else STRATEGY_NAMES[0]
    else:
        chosen = max(scores, key=lambda name: (scores[name]["avg_return"], scores[name]["trades"]))
    return chosen, scores


def walk_forward(rows: list[rb.Row], strategy_name: str, start_index: int) -> list[dict[str, object]]:
    indicators = rb.prepare(rows)
    signal = rb.STRATEGIES[strategy_name]
    trades: list[dict[str, object]] = []
    open_positions: list[dict[str, object]] = []
    last_entry_index = -10_000
    final_index = len(rows) - 1
    final_row = rows[final_index]

    for index in range(start_index, len(rows)):
        row = rows[index]

        still_open: list[dict[str, object]] = []
        for position in open_positions:
            exit_price: float | None = None
            exit_reason = ""
            if index > int(position["entry_index"]):
                hard_stop = float(position["stop_price"])
                trail_stop = position.get("trail_stop_price")
                if trail_stop is not None and row.low <= float(trail_stop):
                    exit_price = float(trail_stop)
                    exit_reason = "加碼移動停利7%"
                if row.low <= hard_stop and (exit_price is None or hard_stop > exit_price):
                    exit_price = hard_stop
                    exit_reason = "停損"
            if exit_price is not None:
                trades.append(
                    {
                        **position,
                        "exit_index": index,
                        "exit_date": row.date,
                        "exit_price": exit_price,
                        "exit_reason": exit_reason,
                        "return_pct": exit_price / float(position["entry_price"]) - 1,
                    }
                )
            else:
                if position.get("position_role") == "加碼單":
                    highest_price = max(float(position["highest_price"]), row.high)
                    position["highest_price"] = highest_price
                    if highest_price >= float(position["entry_price"]) * (1 + rb.TRAILING_TAKE_PROFIT_PCT):
                        position["trail_stop_price"] = highest_price * (1 - rb.TRAILING_TAKE_PROFIT_PCT)
                still_open.append(position)
        open_positions = still_open

        reason = signal(rows, indicators, index)
        if reason and index - last_entry_index >= 10:
            role = rb.position_role(reason, open_positions)
            open_positions.append(
                {
                    "entry_index": index,
                    "entry_date": row.date,
                    "entry_price": row.close,
                    "stop_price": row.close * 0.85,
                    "entry_reason": reason,
                    "position_role": role,
                    "highest_price": row.close,
                    "trail_stop_price": None,
                }
            )
            last_entry_index = index

    for position in open_positions:
        trades.append(
            {
                **position,
                "exit_index": final_index,
                "exit_date": final_row.date,
                "exit_price": final_row.close,
                "exit_reason": "期末估值",
                "return_pct": final_row.close / float(position["entry_price"]) - 1,
            }
        )
    return trades


def summarize_trades(trades: list[dict[str, object]]) -> dict[str, object]:
    return_sum = sum(float(trade["return_pct"]) for trade in trades)
    return {
        "test_trades": len(trades),
        "invested": len(trades) * CAPITAL_PER_TRADE,
        "pnl": return_sum * CAPITAL_PER_TRADE,
        "avg_return": return_sum / len(trades) if trades else 0.0,
        "stopped": sum(1 for trade in trades if trade["exit_reason"] == "停損"),
        "trailing_take_profit": sum(1 for trade in trades if trade["exit_reason"] == "加碼移動停利7%"),
        "open_valued": sum(1 for trade in trades if trade["exit_reason"] == "期末估值"),
    }


def main() -> int:
    rng = random.Random(RANDOM_SEED)
    candidates = []
    for path in csv_files():
        rows = rb.read_rows(path)
        if len(rows) >= 160:
            candidates.append((path, rows))
    rng.shuffle(candidates)

    detail_rows = []
    summary_rows = []
    skipped_no_trade = 0

    for path, rows in candidates:
        if len(summary_rows) >= SAMPLE_SIZE:
            break
        split_index = len(rows) // 2
        train_rows = rows[:split_index]
        test_start = split_index
        drill_start = rng.randint(test_start, len(rows) - 1)
        chosen, scores = choose_strategy(train_rows)
        trades = walk_forward(rows, chosen, drill_start)
        if not trades:
            skipped_no_trade += 1
            continue
        summary = summarize_trades(trades)
        first = rows[0]
        summary_rows.append(
            {
                "market": first.market,
                "stock_no": first.stock_no,
                "stock_name": first.stock_name,
                "train_start": rows[0].date,
                "train_end": rows[split_index - 1].date,
                "test_start": rows[test_start].date,
                "drill_today": rows[drill_start].date,
                "final_date": rows[-1].date,
                "chosen_strategy": chosen,
                "tsmc_train_trades": scores[STRATEGY_NAMES[0]]["trades"],
                "tsmc_train_avg_return": scores[STRATEGY_NAMES[0]]["avg_return"],
                "phison_train_trades": scores[STRATEGY_NAMES[1]]["trades"] if len(STRATEGY_NAMES) > 1 else 0,
                "phison_train_avg_return": scores[STRATEGY_NAMES[1]]["avg_return"] if len(STRATEGY_NAMES) > 1 else 0,
                **summary,
            }
        )
        for trade in trades:
            detail_rows.append(
                {
                    "market": first.market,
                    "stock_no": first.stock_no,
                    "stock_name": first.stock_name,
                    "chosen_strategy": chosen,
                    "drill_today": rows[drill_start].date,
                    "entry_date": trade["entry_date"],
                    "entry_price": trade["entry_price"],
                    "entry_reason": trade["entry_reason"],
                    "position_role": trade["position_role"],
                    "exit_date": trade["exit_date"],
                    "exit_price": trade["exit_price"],
                    "exit_reason": trade["exit_reason"],
                    "return_pct": trade["return_pct"],
                }
            )

    DETAIL_PATH.parent.mkdir(exist_ok=True)
    with DETAIL_PATH.open("w", encoding="utf-8-sig", newline="") as csvfile:
        fieldnames = [
            "market",
            "stock_no",
            "stock_name",
            "chosen_strategy",
            "drill_today",
            "entry_date",
            "entry_price",
            "entry_reason",
            "position_role",
            "exit_date",
            "exit_price",
            "exit_reason",
            "return_pct",
        ]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(detail_rows)

    with SUMMARY_PATH.open("w", encoding="utf-8-sig", newline="") as csvfile:
        fieldnames = [
            "market",
            "stock_no",
            "stock_name",
            "train_start",
            "train_end",
            "test_start",
            "drill_today",
            "final_date",
            "chosen_strategy",
            "tsmc_train_trades",
            "tsmc_train_avg_return",
            "phison_train_trades",
            "phison_train_avg_return",
            "test_trades",
            "invested",
            "pnl",
            "avg_return",
            "stopped",
            "trailing_take_profit",
            "open_valued",
        ]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary_rows)

    total_trades = sum(int(row["test_trades"]) for row in summary_rows)
    total_pnl = sum(float(row["pnl"]) for row in summary_rows)
    total_invested = sum(float(row["invested"]) for row in summary_rows)
    final_dates = [str(row["final_date"]) for row in summary_rows if row.get("final_date")]
    final_date_text = max(final_dates) if final_dates else "最後資料日"
    result = {
        "random_seed": RANDOM_SEED,
        "sample_size": len(summary_rows),
        "skipped_no_trade": skipped_no_trade,
        "assumption": f"每檔前50%資料選策略；後50%隨機一天當今天收盤，之後逐日檢查訊號與停損，沒有交易就重抽；最後以{final_date_text}或個股最後資料日估值。",
        "total_trades": total_trades,
        "total_invested": total_invested,
        "total_pnl": total_pnl,
        "total_return": total_pnl / total_invested if total_invested else 0.0,
        "summary_csv": str(SUMMARY_PATH),
        "detail_csv": str(DETAIL_PATH),
    }
    JSON_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
