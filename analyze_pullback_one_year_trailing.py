#!/usr/bin/env python3
"""Run a one-year pullback backtest with trailing take-profit.

This preserves the earlier recent-10-day pullback version and creates a new
version using one-year market data with equal capital per trade.
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
import types
from collections import Counter
from pathlib import Path
from typing import Any

plot_kline_stub = types.ModuleType("plot_kline")
plot_kline_stub.plot_chart = lambda *args, **kwargs: None
sys.modules.setdefault("plot_kline", plot_kline_stub)

from alert_signals import group_matches_for_display
from analyze_recent_all_signal_backtest import detect_category
from analyze_recent_breakout_backtest import MIN_SIGNAL_VOLUME_SHARES
from run_market_backtest import STRATEGIES, Row, csv_files, prepare, read_rows, value_at
from signal_scoring import signal_score

REPORT_DIR = Path("reports")
CAPITAL_PER_TRADE = 100_000
HARD_STOP_PCT = 0.07
TRAILING_ACTIVATION_PCT = 0.07
TRAILING_DRAWDOWN_PCT = 0.07
MAX_HOLD_DAYS = 10
MIN_ROWS = 80
VERSION = "PB-V3.0-1y-trailing10d"
V1_JSON = REPORT_DIR / "pullback_pb_v1_0_recent10.json"
OUT_JSON = REPORT_DIR / "pullback_pb_v3_0_1y_trailing10d.json"
OUT_CSV = REPORT_DIR / "pullback_pb_v3_0_1y_trailing10d_trades.csv"
OUT_MD = REPORT_DIR / "pullback_pb_v3_0_1y_trailing10d.md"
COMPARE_JSON = REPORT_DIR / "pullback_v1_vs_v3_1y_trailing_comparison.json"
COMPARE_MD = REPORT_DIR / "pullback_v1_vs_v3_1y_trailing_comparison.md"


def to_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def summarize(trades: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(row["return_pct"]) for row in trades if to_float(row.get("return_pct")) is not None]
    if not values:
        return {
            "trades": 0,
            "win_rate_pct": 0.0,
            "avg_return_pct": 0.0,
            "median_return_pct": 0.0,
            "total_pnl": 0,
            "capital_used": 0,
            "capital_return_pct": 0.0,
            "best_return_pct": 0.0,
            "worst_return_pct": 0.0,
        }
    total_pnl = round(sum(value / 100 * CAPITAL_PER_TRADE for value in values))
    capital_used = len(values) * CAPITAL_PER_TRADE
    return {
        "trades": len(values),
        "win_rate_pct": round(sum(value > 0 for value in values) / len(values) * 100, 2),
        "avg_return_pct": round(sum(values) / len(values), 2),
        "median_return_pct": round(statistics.median(values), 2),
        "total_pnl": total_pnl,
        "capital_used": capital_used,
        "capital_return_pct": round(total_pnl / capital_used * 100, 2),
        "best_return_pct": round(max(values), 2),
        "worst_return_pct": round(min(values), 2),
    }


def variant_filters(trades: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return {
        "all_pullback": trades,
        "next_open_no_chase": [row for row in trades if row["entry_price"] <= row["signal_close"]],
        "next_open_discount_2pct": [row for row in trades if row["entry_price"] <= row["signal_close"] * 0.98],
        "next_open_discount_5pct": [row for row in trades if row["entry_price"] <= row["signal_close"] * 0.95],
    }


def summarize_variants(trades: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {name: summarize(filtered) for name, filtered in variant_filters(trades).items()}


def trailing_exit(entry: Row, exit_candidates: list[Row]) -> dict[str, Any]:
    hard_stop = entry.open * (1 - HARD_STOP_PCT)
    activation_price = entry.open * (1 + TRAILING_ACTIVATION_PCT)
    highest = entry.open
    trailing_stop: float | None = None
    observed: list[Row] = []

    for row in exit_candidates:
        observed.append(row)
        exit_price: float | None = None
        exit_reason = ""

        if row.low <= hard_stop:
            exit_price = hard_stop
            exit_reason = "hard_stop"

        if trailing_stop is not None and row.low <= trailing_stop and (exit_price is None or trailing_stop > exit_price):
            exit_price = trailing_stop
            exit_reason = "trailing_stop"

        if exit_price is not None:
            return {
                "exit_date": row.date,
                "exit_price": round(exit_price, 4),
                "holding_days": len(observed),
                "return_pct": round((exit_price / entry.open - 1) * 100, 2),
                "mfe_pct": round((max(item.high for item in observed) / entry.open - 1) * 100, 2),
                "mae_pct": round((min(item.low for item in observed) / entry.open - 1) * 100, 2),
                "exit_reason": exit_reason,
            }

        highest = max(highest, row.high)
        if highest >= activation_price:
            trailing_stop = max(trailing_stop or 0, highest * (1 - TRAILING_DRAWDOWN_PCT))

    last = exit_candidates[-1]
    return {
        "exit_date": last.date,
        "exit_price": round(last.close, 4),
        "holding_days": len(exit_candidates),
        "return_pct": round((last.close / entry.open - 1) * 100, 2),
        "mfe_pct": round((max(row.high for row in exit_candidates) / entry.open - 1) * 100, 2),
        "mae_pct": round((min(row.low for row in exit_candidates) / entry.open - 1) * 100, 2),
        "exit_reason": "max_hold_close",
    }


def make_match(path: Path, rows: list[Row], indicators: dict[str, list[float | None]], index: int, strategy: str, reason: str) -> dict[str, Any]:
    row = rows[index]
    score_data = signal_score(rows, indicators, index, reason)
    return {
        "market": row.market.upper(),
        "stock_no": row.stock_no,
        "stock_name": row.stock_name,
        "date": row.date,
        "strategy": strategy,
        "reason": reason,
        **score_data,
        "close": row.close,
        "volume": row.volume,
        "ma5": value_at(indicators["ma5"], index),
        "ma10": value_at(indicators["ma10"], index),
        "ma20": value_at(indicators["ma20"], index),
        "ma60": value_at(indicators["ma60"], index),
        "source": str(path),
        "row_index": index,
    }


def run_one_year() -> dict[str, Any]:
    source_files = csv_files()
    series: list[tuple[Path, list[Row], dict[str, list[float | None]]]] = []
    skipped_short = 0
    for path in source_files:
        rows = read_rows(path)
        if len(rows) < MIN_ROWS:
            skipped_short += 1
            continue
        series.append((path, rows, prepare(rows)))

    raw_matches: list[dict[str, Any]] = []
    scanned_stock_dates = 0
    date_scanned: Counter[str] = Counter()
    for path, rows, indicators in series:
        max_signal_index = len(rows) - MAX_HOLD_DAYS - 2
        for index in range(60, max_signal_index + 1):
            row = rows[index]
            scanned_stock_dates += 1
            date_scanned[row.date] += 1
            if row.volume < MIN_SIGNAL_VOLUME_SHARES:
                continue
            for strategy_name, signal in STRATEGIES.items():
                reason = signal(rows, indicators, index)
                if reason:
                    raw_matches.append(make_match(path, rows, indicators, index, strategy_name, reason))

    grouped = group_matches_for_display(raw_matches)
    pullback_items = [item for item in grouped if detect_category(item) == "pullback"]
    rows_by_source = {str(path): rows for path, rows, _ in series}
    trades: list[dict[str, Any]] = []
    for item in pullback_items:
        rows = rows_by_source[str(item["source"])]
        signal_index = int(item["row_index"])
        entry_index = signal_index + 1
        exit_candidates = rows[entry_index : entry_index + MAX_HOLD_DAYS]
        if len(exit_candidates) < MAX_HOLD_DAYS:
            continue
        entry = rows[entry_index]
        perf = trailing_exit(entry, exit_candidates)
        ret = float(perf["return_pct"])
        trade = {
            "version": VERSION,
            "signal_date": item["date"],
            "market": item["market"],
            "stock_no": item["stock_no"],
            "stock_name": item["stock_name"],
            "signal_close": round(float(item["close"]), 4),
            "entry_date": entry.date,
            "entry_price": round(entry.open, 4),
            "exit_date": perf["exit_date"],
            "exit_price": perf["exit_price"],
            "holding_days": perf["holding_days"],
            "return_pct": ret,
            "mfe_pct": perf["mfe_pct"],
            "mae_pct": perf["mae_pct"],
            "capital": CAPITAL_PER_TRADE,
            "pnl": round(ret / 100 * CAPITAL_PER_TRADE),
            "exit_reason": perf["exit_reason"],
            "reasons": " / ".join(item.get("reasons", [])),
            "score": item.get("score"),
            "volume": item.get("volume"),
        }
        trades.append(trade)

    payload = {
        "version": VERSION,
        "description": "One-year pullback backtest with 7% hard stop, 7% trailing activation, 7% trailing drawdown, and 10-trading-day maximum hold.",
        "methodology": {
            "universe": "default one-year all_twse/all_tpex data files",
            "entry_rule": "buy next trading day's open after the signal date",
            "exit_rule": "7% hard stop; after +7% MFE, trailing stop at 7% below highest observed price; otherwise exit at close after 10 trading days",
            "max_holding_days": MAX_HOLD_DAYS,
            "hard_stop_pct": HARD_STOP_PCT * 100,
            "trailing_activation_pct": TRAILING_ACTIVATION_PCT * 100,
            "trailing_drawdown_pct": TRAILING_DRAWDOWN_PCT * 100,
            "capital_per_trade": CAPITAL_PER_TRADE,
            "weighting": "equal capital per trade",
        },
        "funnel": {
            "source_files_found": len(source_files),
            "eligible_one_year_files": len(series),
            "skipped_short_files": skipped_short,
            "scanned_stock_date_observations": scanned_stock_dates,
            "raw_signal_rows_before_grouping": len(raw_matches),
            "grouped_signal_stock_days": len(grouped),
            "grouped_pullback_stock_days": len(pullback_items),
            "realized_pullback_trades": len(trades),
            "unique_pullback_stocks": len({trade["stock_no"] for trade in trades}),
            "date_start": min(date_scanned) if date_scanned else "",
            "date_end": max(date_scanned) if date_scanned else "",
            "signal_dates": len(date_scanned),
        },
        "variants": summarize_variants(trades),
        "by_exit_reason": dict(Counter(trade["exit_reason"] for trade in trades)),
        "by_year": {
            year: summarize([trade for trade in trades if trade["signal_date"].startswith(year)])
            for year in sorted({trade["signal_date"][:4] for trade in trades})
        },
        "trades": trades,
    }
    return payload


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    preferred = [
        "version", "signal_date", "market", "stock_no", "stock_name", "signal_close",
        "entry_date", "entry_price", "exit_date", "exit_price", "holding_days",
        "return_pct", "mfe_pct", "mae_pct", "capital", "pnl", "exit_reason", "reasons",
    ]
    fields = sorted({key for row in rows for key in row})
    ordered = [key for key in preferred if key in fields] + [key for key in fields if key not in preferred]
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=ordered)
        writer.writeheader()
        writer.writerows(rows)


def markdown(payload: dict[str, Any]) -> str:
    labels = {
        "all_pullback": "所有 pullback",
        "next_open_no_chase": "隔日不追高",
        "next_open_discount_2pct": "隔日開低 2%+",
        "next_open_discount_5pct": "隔日開低 5%+",
    }
    lines = [
        f"# {payload['version']}",
        "",
        payload["description"],
        "",
        "## Funnel",
    ]
    for key, value in payload["funnel"].items():
        lines.append(f"- {key}: {value}")
    lines.extend([
        "",
        "## Variant Summary",
        "",
        "| Variant | Trades | Win rate | Avg return | Median return | Capital used | Total PnL |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    for key, summary in payload["variants"].items():
        lines.append(
            f"| {labels[key]} | {summary['trades']} | {summary['win_rate_pct']:.2f}% | "
            f"{summary['avg_return_pct']:.2f}% | {summary['median_return_pct']:.2f}% | "
            f"{summary['capital_used']:,} | {summary['total_pnl']:,} |"
        )
    lines.extend(["", "## Exit Reasons"])
    for key, value in payload["by_exit_reason"].items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines) + "\n"


def comparison(v3: dict[str, Any]) -> dict[str, Any]:
    previous = json.loads(V1_JSON.read_text(encoding="utf-8")) if V1_JSON.exists() else None
    return {
        "versions": [previous.get("version") if previous else None, v3["version"]],
        "capital_per_trade": CAPITAL_PER_TRADE,
        "note": "V1 is the frozen recent-10-day report. V3 uses one-year data and adds trailing take-profit for pullback exits.",
        "variant_comparison": {
            variant: {
                previous["version"] if previous else "previous": previous["variants"].get(variant) if previous else None,
                v3["version"]: v3["variants"].get(variant),
            }
            for variant in v3["variants"]
        },
    }


def comparison_markdown(payload: dict[str, Any]) -> str:
    labels = {
        "all_pullback": "所有 pullback",
        "next_open_no_chase": "隔日不追高",
        "next_open_discount_2pct": "隔日開低 2%+",
        "next_open_discount_5pct": "隔日開低 5%+",
    }
    lines = [
        "# Pullback V1 vs V3 Comparison",
        "",
        f"- 每筆資金: {payload['capital_per_trade']:,}",
        f"- 說明: {payload['note']}",
        "",
        "| Variant | Version | Trades | Win rate | Avg return | Median return | Total PnL |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for variant, versions in payload["variant_comparison"].items():
        for version, summary in versions.items():
            if not summary:
                continue
            lines.append(
                f"| {labels[variant]} | {version} | {summary['trades']} | "
                f"{summary['win_rate_pct']:.2f}% | {summary['avg_return_pct']:.2f}% | "
                f"{summary['median_return_pct']:.2f}% | {summary['total_pnl']:,} |"
            )
    return "\n".join(lines) + "\n"


def main() -> None:
    REPORT_DIR.mkdir(exist_ok=True)
    payload = run_one_year()
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_MD.write_text(markdown(payload), encoding="utf-8")
    write_csv(OUT_CSV, payload["trades"])
    comp = comparison(payload)
    COMPARE_JSON.write_text(json.dumps(comp, ensure_ascii=False, indent=2), encoding="utf-8")
    COMPARE_MD.write_text(comparison_markdown(comp), encoding="utf-8")
    print(json.dumps({
        "version": payload["version"],
        "funnel": payload["funnel"],
        "variants": payload["variants"],
        "by_exit_reason": payload["by_exit_reason"],
        "outputs": [str(OUT_JSON), str(OUT_CSV), str(OUT_MD), str(COMPARE_JSON), str(COMPARE_MD)],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
