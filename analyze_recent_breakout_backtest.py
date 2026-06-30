#!/usr/bin/env python3
"""Backtest recent daily top signal watchlist performance."""

from __future__ import annotations

import csv
import argparse
import json
import sys
import types
from pathlib import Path
from typing import Any

plot_kline_stub = types.ModuleType("plot_kline")
plot_kline_stub.plot_chart = lambda *args, **kwargs: None
sys.modules.setdefault("plot_kline", plot_kline_stub)

from alert_signals import (
    MIN_SIGNAL_VOLUME_SHARES,
    strongest_signal_lists,
)
from run_market_backtest import STRATEGIES, Row, csv_files, prepare, read_rows, value_at
from signal_scoring import signal_score


REPORT_DIR = Path("reports")
CSV_REPORT = REPORT_DIR / "recent_top5_signal_backtest.csv"
MD_REPORT = REPORT_DIR / "recent_top5_signal_backtest.md"
JSON_REPORT = REPORT_DIR / "recent_top5_signal_backtest.json"
MANAGED_CSV_REPORT = REPORT_DIR / "recent_top5_signal_backtest_with_trailing.csv"
MANAGED_MD_REPORT = REPORT_DIR / "recent_top5_signal_backtest_with_trailing.md"
MANAGED_JSON_REPORT = REPORT_DIR / "recent_top5_signal_backtest_with_trailing.json"
STOP_ONLY_CSV_REPORT = REPORT_DIR / "recent_top5_signal_backtest_stop_only.csv"
STOP_ONLY_MD_REPORT = REPORT_DIR / "recent_top5_signal_backtest_stop_only.md"
STOP_ONLY_JSON_REPORT = REPORT_DIR / "recent_top5_signal_backtest_stop_only.json"
SMART_CSV_REPORT = REPORT_DIR / "recent_top5_signal_backtest_smart.csv"
SMART_MD_REPORT = REPORT_DIR / "recent_top5_signal_backtest_smart.md"
SMART_JSON_REPORT = REPORT_DIR / "recent_top5_signal_backtest_smart.json"

HARD_STOP_PCT = 0.15
PULLBACK_HARD_STOP_PCT = 0.07
BREAKOUT_HARD_STOP_PCT = 0.15
TRAILING_ACTIVATION_PCT = 0.07
TRAILING_DRAWDOWN_PCT = 0.07
SMART_BREAKOUT_HARD_STOP_PCT = 0.07
SMART_BREAKOUT_TRAILING_ACTIVATION_PCT = 0.15
SMART_BREAKOUT_TRAILING_DRAWDOWN_PCT = 0.07
EXIT_MODES = {"baseline", "trailing", "stop_only", "smart"}
HIGH_BASE_PULLBACK_STRATEGIES = {
    "high_base_pullback",
    "quarterly_support_gap_reclaim_watch",
}
HIGH_BASE_PULLBACK_KEYWORDS = ("高檔", "回測", "回檔", "拉回", "支撐")


def available_trading_dates(rows_by_path: dict[Path, list[Row]]) -> list[str]:
    dates: set[str] = set()
    for rows in rows_by_path.values():
        dates.update(row.date for row in rows)
    return sorted(dates)


def signals_as_of(path: Path, full_rows: list[Row], as_of: str) -> list[dict[str, Any]]:
    rows = [row for row in full_rows if row.date <= as_of]
    if len(rows) < 60 or rows[-1].date != as_of:
        return []

    indicators = prepare(rows)
    index = len(rows) - 1
    row = rows[index]
    if row.volume < MIN_SIGNAL_VOLUME_SHARES:
        return []

    matches: list[dict[str, Any]] = []
    for strategy_name, signal in STRATEGIES.items():
        reason = signal(rows, indicators, index)
        if not reason:
            continue
        score_data = signal_score(rows, indicators, index, reason)
        matches.append(
            {
                "market": row.market.upper(),
                "stock_no": row.stock_no,
                "stock_name": row.stock_name,
                "date": row.date,
                "strategy": strategy_name,
                "reason": reason,
                **score_data,
                "close": row.close,
                "volume": row.volume,
                "ma5": value_at(indicators["ma5"], index),
                "ma10": value_at(indicators["ma10"], index),
                "ma20": value_at(indicators["ma20"], index),
                "ma60": value_at(indicators["ma60"], index),
                "source": str(path),
            }
        )
    return matches


def next_row_after(rows: list[Row], date: str) -> tuple[int, Row] | tuple[None, None]:
    for index, row in enumerate(rows):
        if row.date > date:
            return index, row
    return None, None


def mark_to_latest_performance(
    entry: Row,
    exit_candidates: list[Row],
) -> dict[str, Any]:
    exit_row = exit_candidates[-1]
    high = max(row.high for row in exit_candidates)
    low = min(row.low for row in exit_candidates)
    return {
        "exit_date": exit_row.date,
        "exit_price": round(exit_row.close, 4),
        "holding_days": len(exit_candidates),
        "return_pct": round((exit_row.close / entry.open - 1) * 100, 2),
        "mfe_pct": round((high / entry.open - 1) * 100, 2),
        "mae_pct": round((low / entry.open - 1) * 100, 2),
        "status": "closed_to_latest",
        "exit_reason": "latest_close",
    }


def is_high_base_pullback_signal(item: dict[str, Any]) -> bool:
    strategy = str(item.get("strategy") or "")
    reason = str(item.get("reason") or "")
    reasons = " ".join(str(value) for value in item.get("reasons", []))
    text = f"{reason} {reasons}"
    return strategy in HIGH_BASE_PULLBACK_STRATEGIES or any(keyword in text for keyword in HIGH_BASE_PULLBACK_KEYWORDS)


def risk_policy_for_signal(item: dict[str, Any], category: str | None, exit_mode: str) -> dict[str, Any]:
    is_pullback = category == "pullback"
    is_breakout = category == "breakout"
    high_base_pullback = is_high_base_pullback_signal(item)
    if exit_mode == "smart":
        hard_stop_pct = PULLBACK_HARD_STOP_PCT if is_pullback else SMART_BREAKOUT_HARD_STOP_PCT
        use_trailing = is_breakout
        trailing_activation_pct = SMART_BREAKOUT_TRAILING_ACTIVATION_PCT
        trailing_drawdown_pct = SMART_BREAKOUT_TRAILING_DRAWDOWN_PCT
        policy_label = "pullback_7pct_stop" if is_pullback else "breakout_7pct_stop_trail_after_15pct"
    else:
        hard_stop_pct = PULLBACK_HARD_STOP_PCT if is_pullback else BREAKOUT_HARD_STOP_PCT
        use_trailing = exit_mode == "trailing" and is_breakout and high_base_pullback
        trailing_activation_pct = TRAILING_ACTIVATION_PCT
        trailing_drawdown_pct = TRAILING_DRAWDOWN_PCT
        policy_label = (
            "pullback_7pct_stop"
            if is_pullback
            else "breakout_high_base_trailing"
            if use_trailing
            else "breakout_wide_stop"
        )
    return {
        "hard_stop_pct": hard_stop_pct,
        "trailing_activation_pct": trailing_activation_pct,
        "trailing_drawdown_pct": trailing_drawdown_pct,
        "use_trailing": use_trailing,
        "policy_label": policy_label,
        "high_base_pullback": high_base_pullback,
    }


def trailing_performance(
    entry: Row,
    exit_candidates: list[Row],
    hard_stop_pct: float = HARD_STOP_PCT,
    trailing_activation_pct: float = TRAILING_ACTIVATION_PCT,
    trailing_drawdown_pct: float = TRAILING_DRAWDOWN_PCT,
) -> dict[str, Any]:
    entry_price = entry.open
    hard_stop = entry_price * (1 - hard_stop_pct)
    activation_price = entry_price * (1 + trailing_activation_pct)
    highest_price = entry_price
    trail_stop: float | None = None
    observed_rows: list[Row] = []

    for row in exit_candidates:
        observed_rows.append(row)
        exit_price: float | None = None
        exit_reason = ""

        if row.low <= hard_stop:
            exit_price = hard_stop
            exit_reason = "hard_stop"

        if trail_stop is not None and row.low <= trail_stop and (exit_price is None or trail_stop > exit_price):
            exit_price = trail_stop
            exit_reason = "trailing_stop"

        if exit_price is not None:
            high = max(item.high for item in observed_rows)
            low = min(item.low for item in observed_rows)
            return {
                "exit_date": row.date,
                "exit_price": round(exit_price, 4),
                "holding_days": len(observed_rows),
                "return_pct": round((exit_price / entry_price - 1) * 100, 2),
                "mfe_pct": round((high / entry_price - 1) * 100, 2),
                "mae_pct": round((low / entry_price - 1) * 100, 2),
                "status": "stopped",
                "exit_reason": exit_reason,
            }

        highest_price = max(highest_price, row.high)
        if highest_price >= activation_price:
            trail_stop = max(trail_stop or 0, highest_price * (1 - trailing_drawdown_pct))

    fallback = mark_to_latest_performance(entry, exit_candidates)
    fallback["status"] = "open_to_latest"
    fallback["exit_reason"] = "latest_close"
    return fallback


def stop_only_performance(
    entry: Row,
    exit_candidates: list[Row],
    hard_stop_pct: float = HARD_STOP_PCT,
) -> dict[str, Any]:
    entry_price = entry.open
    hard_stop = entry_price * (1 - hard_stop_pct)
    observed_rows: list[Row] = []

    for row in exit_candidates:
        observed_rows.append(row)
        if row.low <= hard_stop:
            high = max(item.high for item in observed_rows)
            low = min(item.low for item in observed_rows)
            return {
                "exit_date": row.date,
                "exit_price": round(hard_stop, 4),
                "holding_days": len(observed_rows),
                "return_pct": round((hard_stop / entry_price - 1) * 100, 2),
                "mfe_pct": round((high / entry_price - 1) * 100, 2),
                "mae_pct": round((low / entry_price - 1) * 100, 2),
                "status": "stopped",
                "exit_reason": "hard_stop",
            }

    fallback = mark_to_latest_performance(entry, exit_candidates)
    fallback["status"] = "open_to_latest"
    fallback["exit_reason"] = "latest_close"
    return fallback


def performance_for_signal(
    item: dict[str, Any],
    rows_by_path: dict[Path, list[Row]],
    latest_date: str,
    exit_mode: str = "baseline",
    category: str | None = None,
) -> dict[str, Any]:
    if exit_mode not in EXIT_MODES:
        raise ValueError(f"Unsupported exit mode: {exit_mode}")

    source = Path(str(item["source"]))
    rows = rows_by_path[source]
    entry_index, entry = next_row_after(rows, str(item["date"]))
    if entry_index is None or entry is None:
        return {
            "entry_date": "",
            "entry_price": "",
            "exit_date": "",
            "exit_price": "",
            "holding_days": 0,
            "return_pct": "",
            "mfe_pct": "",
            "mae_pct": "",
            "status": "pending_next_open",
        }

    exit_candidates = [row for row in rows[entry_index:] if row.date <= latest_date]
    if not exit_candidates:
        return {
            "entry_date": entry.date,
            "entry_price": entry.open,
            "exit_date": "",
            "exit_price": "",
            "holding_days": 0,
            "return_pct": "",
            "mfe_pct": "",
            "mae_pct": "",
            "status": "no_exit_data",
        }

    policy = risk_policy_for_signal(item, category, exit_mode)
    if exit_mode in {"trailing", "smart"} and policy["use_trailing"]:
        perf = trailing_performance(
            entry,
            exit_candidates,
            hard_stop_pct=policy["hard_stop_pct"],
            trailing_activation_pct=policy["trailing_activation_pct"],
            trailing_drawdown_pct=policy["trailing_drawdown_pct"],
        )
    elif exit_mode in {"stop_only", "smart"}:
        perf = stop_only_performance(entry, exit_candidates, hard_stop_pct=policy["hard_stop_pct"])
    elif exit_mode == "trailing":
        perf = stop_only_performance(entry, exit_candidates, hard_stop_pct=policy["hard_stop_pct"])
    else:
        perf = mark_to_latest_performance(entry, exit_candidates)
    if exit_mode != "baseline":
        perf["risk_policy"] = policy["policy_label"]
        perf["hard_stop_pct"] = round(policy["hard_stop_pct"] * 100, 2)
        perf["trailing_enabled"] = policy["use_trailing"]
    return {
        "entry_date": entry.date,
        "entry_price": round(entry.open, 4),
        **perf,
    }


def add_capital_metrics(rows: list[dict[str, Any]], capital_per_trade: float = 100_000) -> None:
    for row in rows:
        row["capital"] = ""
        row["pnl"] = ""
        row["shares"] = ""
        row["position_value"] = ""
        if isinstance(row.get("return_pct"), (int, float)):
            entry_price = float(row.get("entry_price") or 0)
            exit_price = float(row.get("exit_price") or 0)
            if entry_price <= 0 or exit_price <= 0:
                continue
            shares = capital_per_trade / entry_price
            cost = shares * entry_price
            position_value = shares * exit_price
            row["shares"] = round(shares, 6)
            row["capital"] = round(cost, 2)
            row["position_value"] = round(position_value, 2)
            row["pnl"] = round(position_value - cost, 0)


def build_rows(days: int, top_count: int, exit_mode: str = "baseline") -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if exit_mode not in EXIT_MODES:
        raise ValueError(f"Unsupported exit mode: {exit_mode}")

    rows_by_path = {path: read_rows(path) for path in csv_files()}
    trading_dates = available_trading_dates(rows_by_path)
    latest_date = trading_dates[-1]
    target_dates = trading_dates[-days:]
    output_rows: list[dict[str, Any]] = []
    by_day: dict[str, Any] = {}

    for as_of in target_dates:
        matches: list[dict[str, Any]] = []
        for path, stock_rows in rows_by_path.items():
            matches.extend(signals_as_of(path, stock_rows, as_of))

        top_lists = strongest_signal_lists(matches, count=top_count)
        day_rows: list[dict[str, Any]] = []
        for category, items in top_lists.items():
            for rank, item in enumerate(items, start=1):
                perf = performance_for_signal(item, rows_by_path, latest_date, exit_mode=exit_mode, category=category)
                row = {
                    "category": category,
                    "signal_date": as_of,
                    "rank": rank,
                    "market": item["market"],
                    "stock_no": item["stock_no"],
                    "stock_name": item["stock_name"],
                    "signal_close": item["close"],
                    "weighted_score": item.get("weighted_score"),
                    "score": item.get("score"),
                    "volume_ratio": item.get("volume_ratio"),
                    "ma20_slope_pct": item.get("ma20_slope_pct"),
                    "ma60_slope_pct": item.get("ma60_slope_pct"),
                    **perf,
                }
                output_rows.append(row)
                day_rows.append(row)
        by_day[as_of] = summarize(day_rows)

    add_capital_metrics(output_rows)
    metadata = {
        "latest_date": latest_date,
        "target_dates": target_dates,
        "entry_rule": "buy next trading day's open after the signal date",
        "exit_rule": {
            "baseline": "mark to latest available close",
            "trailing": "pullback uses 7% hard stop; breakout uses 15% hard stop, and only high-base pullback breakout signals activate a 7% trailing take-profit after +7% MFE",
            "stop_only": "pullback uses 7% hard stop; breakout uses 15% hard stop; otherwise mark to latest close",
            "smart": "pullback uses 7% hard stop; breakout uses 7% hard stop, and only activates a 7% trailing stop after +15% MFE",
        }[exit_mode],
        "risk_management": {
            "exit_mode": exit_mode,
            "use_trailing": exit_mode == "trailing",
            "use_stop_only": exit_mode == "stop_only",
            "use_smart": exit_mode == "smart",
            "hard_stop_pct": HARD_STOP_PCT,
            "pullback_hard_stop_pct": PULLBACK_HARD_STOP_PCT,
            "breakout_hard_stop_pct": BREAKOUT_HARD_STOP_PCT,
            "trailing_activation_pct": TRAILING_ACTIVATION_PCT,
            "trailing_drawdown_pct": TRAILING_DRAWDOWN_PCT,
            "trailing_scope": "breakout signals that also look like high-base pullbacks",
            "smart_breakout_hard_stop_pct": SMART_BREAKOUT_HARD_STOP_PCT,
            "smart_breakout_trailing_activation_pct": SMART_BREAKOUT_TRAILING_ACTIVATION_PCT,
            "smart_breakout_trailing_drawdown_pct": SMART_BREAKOUT_TRAILING_DRAWDOWN_PCT,
        },
        "by_day": by_day,
        "overall": summarize(output_rows),
        "by_category": {
            "pullback": summarize([row for row in output_rows if row["category"] == "pullback"]),
            "breakout": summarize([row for row in output_rows if row["category"] == "breakout"]),
        },
        "capital_per_trade": 100_000,
        "capital_summary": capital_summary(output_rows),
    }
    return output_rows, metadata


def capital_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    realized = [row for row in rows if isinstance(row.get("pnl"), (int, float))]
    capital = sum(float(row["capital"]) for row in realized)
    pnl = sum(float(row["pnl"]) for row in realized)
    return {
        "realized_trades": len(realized),
        "deployed_capital": int(capital),
        "total_pnl": int(round(pnl, 0)),
        "portfolio_return_pct": round(pnl / capital * 100, 2) if capital else "",
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    realized = [row for row in rows if isinstance(row.get("return_pct"), (int, float))]
    pending = len(rows) - len(realized)
    if not realized:
        return {
            "picks": len(rows),
            "realized": 0,
            "pending": pending,
            "avg_return_pct": "",
            "win_rate_pct": "",
            "best_return_pct": "",
            "worst_return_pct": "",
        }
    returns = [float(row["return_pct"]) for row in realized]
    wins = [value for value in returns if value > 0]
    return {
        "picks": len(rows),
        "realized": len(realized),
        "pending": pending,
        "avg_return_pct": round(sum(returns) / len(returns), 2),
        "win_rate_pct": round(len(wins) / len(returns) * 100, 2),
        "best_return_pct": round(max(returns), 2),
        "worst_return_pct": round(min(returns), 2),
    }


def write_csv(rows: list[dict[str, Any]], path: Path = CSV_REPORT) -> None:
    REPORT_DIR.mkdir(exist_ok=True)
    fieldnames = [
        "signal_date",
        "category",
        "rank",
        "market",
        "stock_no",
        "stock_name",
        "signal_close",
        "weighted_score",
        "score",
        "volume_ratio",
        "ma20_slope_pct",
        "ma60_slope_pct",
        "entry_date",
        "entry_price",
        "exit_date",
        "exit_price",
        "shares",
        "position_value",
        "holding_days",
        "return_pct",
        "mfe_pct",
        "mae_pct",
        "capital",
        "pnl",
        "status",
        "exit_reason",
        "risk_policy",
        "hard_stop_pct",
        "trailing_enabled",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(rows: list[dict[str, Any]], metadata: dict[str, Any], path: Path = MD_REPORT) -> None:
    lines = [
        "# Recent Top 5 Signal Backtest",
        "",
        f"- Latest data date: {metadata['latest_date']}",
        f"- Signal dates: {', '.join(metadata['target_dates'])}",
        f"- Entry rule: {metadata['entry_rule']}",
        f"- Exit rule: {metadata['exit_rule']}",
        "",
        "## Summary",
        "",
        "| Scope | Picks | Realized | Pending | Avg Return % | Win Rate % | Best % | Worst % |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    overall = metadata["overall"]
    lines.append(summary_row("Overall", overall))
    lines.append(summary_row("Pullback", metadata["by_category"]["pullback"]))
    lines.append(summary_row("Breakout", metadata["by_category"]["breakout"]))
    for date in metadata["target_dates"]:
        lines.append(summary_row(date, metadata["by_day"][date]))

    lines.extend(
        [
            "",
            "## Trades",
            "",
            "| Signal Date | Category | Rank | Stock | Entry | Exit | Days | Return % | MFE % | MAE % | Status | Exit Reason |",
            "|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|---|",
        ]
    )
    for row in rows:
        stock = f"{row['stock_no']} {row['stock_name']} ({row['market']})"
        entry = f"{row['entry_date']} @ {row['entry_price']}" if row["entry_date"] else "-"
        exit_text = f"{row['exit_date']} @ {row['exit_price']}" if row["exit_date"] else "-"
        lines.append(
            "| {signal_date} | {category} | {rank} | {stock} | {entry} | {exit} | {holding_days} | {return_pct} | {mfe_pct} | {mae_pct} | {status} | {exit_reason} |".format(
                signal_date=row["signal_date"],
                category=row["category"],
                rank=row["rank"],
                stock=stock,
                entry=entry,
                exit=exit_text,
                holding_days=row["holding_days"],
                return_pct=row["return_pct"] if row["return_pct"] != "" else "-",
                mfe_pct=row["mfe_pct"] if row["mfe_pct"] != "" else "-",
                mae_pct=row["mae_pct"] if row["mae_pct"] != "" else "-",
                status=row["status"],
                exit_reason=row.get("exit_reason", "-"),
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def summary_row(label: str, summary: dict[str, Any]) -> str:
    return "| {label} | {picks} | {realized} | {pending} | {avg} | {win} | {best} | {worst} |".format(
        label=label,
        picks=summary["picks"],
        realized=summary["realized"],
        pending=summary["pending"],
        avg=summary["avg_return_pct"] if summary["avg_return_pct"] != "" else "-",
        win=summary["win_rate_pct"] if summary["win_rate_pct"] != "" else "-",
        best=summary["best_return_pct"] if summary["best_return_pct"] != "" else "-",
        worst=summary["worst_return_pct"] if summary["worst_return_pct"] != "" else "-",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest recent daily top signal watchlist performance.")
    parser.add_argument("--days", type=int, default=5, help="Number of recent trading days to include.")
    parser.add_argument("--top-count", type=int, default=5, help="Number of ranked items per category per day.")
    parser.add_argument("--trailing", action="store_true", help="Apply hard stop and trailing stop/take-profit exits.")
    parser.add_argument("--stop-only", action="store_true", help="Apply only the hard stop exit.")
    parser.add_argument("--smart", action="store_true", help="Pullback uses 7% stop; breakout uses 7% stop and trailing activates after +15% MFE.")
    args = parser.parse_args()

    if sum(1 for enabled in (args.trailing, args.stop_only, args.smart) if enabled) > 1:
        parser.error("--trailing, --stop-only, and --smart cannot be used together.")

    exit_mode = "trailing" if args.trailing else "stop_only" if args.stop_only else "smart" if args.smart else "baseline"
    rows, metadata = build_rows(days=args.days, top_count=args.top_count, exit_mode=exit_mode)
    csv_path = {
        "baseline": CSV_REPORT,
        "trailing": MANAGED_CSV_REPORT,
        "stop_only": STOP_ONLY_CSV_REPORT,
        "smart": SMART_CSV_REPORT,
    }[exit_mode]
    md_path = {
        "baseline": MD_REPORT,
        "trailing": MANAGED_MD_REPORT,
        "stop_only": STOP_ONLY_MD_REPORT,
        "smart": SMART_MD_REPORT,
    }[exit_mode]
    json_path = {
        "baseline": JSON_REPORT,
        "trailing": MANAGED_JSON_REPORT,
        "stop_only": STOP_ONLY_JSON_REPORT,
        "smart": SMART_JSON_REPORT,
    }[exit_mode]
    write_csv(rows, csv_path)
    write_markdown(rows, metadata, md_path)
    json_path.write_text(
        json.dumps({"metadata": metadata, "rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {csv_path}")
    print(f"Wrote {md_path}")
    print(f"Wrote {json_path}")
    print(json.dumps(metadata["overall"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
