#!/usr/bin/env python3
"""Create versioned pullback strategy reports.

PB-V1.0 preserves the existing recent-10-trading-day all-signal smart backtest.
PB-V2.0 reruns the same pullback signal classification on expanded three-year data
with a fixed 10-trading-day evaluation window for fair rolling comparison.
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
import types
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

plot_kline_stub = types.ModuleType("plot_kline")
plot_kline_stub.plot_chart = lambda *args, **kwargs: None
sys.modules.setdefault("plot_kline", plot_kline_stub)

from alert_signals import group_matches_for_display
from analyze_recent_all_signal_backtest import detect_category
from analyze_recent_breakout_backtest import MIN_SIGNAL_VOLUME_SHARES
from run_market_backtest import STRATEGIES, Row, prepare, read_rows, value_at
from signal_scoring import signal_score

REPORT_DIR = Path("reports")
CAPITAL_PER_TRADE = 100_000
PULLBACK_HARD_STOP_PCT = 0.07
V1_VERSION = "PB-V1.0-recent10"
V2_VERSION = "PB-V2.0-3y-fixed10d"
V1_SOURCE_JSON = REPORT_DIR / "recent_all_signal_backtest_smart.json"
V1_SOURCE_CSV = REPORT_DIR / "recent_all_signal_backtest_smart.csv"
V1_JSON = REPORT_DIR / "pullback_pb_v1_0_recent10.json"
V1_CSV = REPORT_DIR / "pullback_pb_v1_0_recent10_trades.csv"
V1_MD = REPORT_DIR / "pullback_pb_v1_0_recent10.md"
V2_JSON = REPORT_DIR / "pullback_pb_v2_0_3y.json"
V2_CSV = REPORT_DIR / "pullback_pb_v2_0_3y_trades.csv"
V2_MD = REPORT_DIR / "pullback_pb_v2_0_3y.md"
COMPARE_JSON = REPORT_DIR / "pullback_version_comparison.json"
COMPARE_MD = REPORT_DIR / "pullback_version_comparison.md"
RESEARCH_DIRS = [Path("data/research_3y_twse"), Path("data/research_3y_tpex")]
MAX_HOLD_DAYS = 10
MIN_ROWS_3Y = 700


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
    returns = [float(item["return_pct"]) for item in trades if to_float(item.get("return_pct")) is not None]
    if not returns:
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
    total_pnl = round(sum(value / 100 * CAPITAL_PER_TRADE for value in returns))
    return {
        "trades": len(returns),
        "win_rate_pct": round(sum(value > 0 for value in returns) / len(returns) * 100, 2),
        "avg_return_pct": round(sum(returns) / len(returns), 2),
        "median_return_pct": round(statistics.median(returns), 2),
        "total_pnl": total_pnl,
        "capital_used": len(returns) * CAPITAL_PER_TRADE,
        "capital_return_pct": round(total_pnl / (len(returns) * CAPITAL_PER_TRADE) * 100, 2),
        "best_return_pct": round(max(returns), 2),
        "worst_return_pct": round(min(returns), 2),
    }


def variant_filters(trades: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return {
        "all_pullback": trades,
        "next_open_no_chase": [
            item for item in trades if float(item["entry_price"]) <= float(item["signal_close"])
        ],
        "next_open_discount_2pct": [
            item for item in trades if float(item["entry_price"]) <= float(item["signal_close"]) * 0.98
        ],
        "next_open_discount_5pct": [
            item for item in trades if float(item["entry_price"]) <= float(item["signal_close"]) * 0.95
        ],
    }


def summarize_variants(trades: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {name: summarize(filtered) for name, filtered in variant_filters(trades).items()}


def read_existing_v1_trades() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    data = json.loads(V1_SOURCE_JSON.read_text(encoding="utf-8"))
    rows = []
    for row in data["rows"]:
        if row.get("category") != "pullback":
            continue
        ret = to_float(row.get("return_pct"))
        entry_price = to_float(row.get("entry_price"))
        signal_close = to_float(row.get("signal_close"))
        if ret is None or entry_price is None or signal_close is None:
            continue
        normalized = dict(row)
        normalized["return_pct"] = ret
        normalized["entry_price"] = entry_price
        normalized["signal_close"] = signal_close
        normalized["capital"] = CAPITAL_PER_TRADE
        normalized["pnl"] = round(ret / 100 * CAPITAL_PER_TRADE)
        rows.append(normalized)
    metadata = data["metadata"]
    payload = {
        "version": V1_VERSION,
        "description": "Frozen current pullback report from recent 10 trading days.",
        "source_report": str(V1_SOURCE_JSON),
        "methodology": {
            "universe": "default one-year all_twse/all_tpex data files",
            "signal_dates": metadata["target_dates"],
            "entry_rule": metadata["entry_rule"],
            "exit_rule": "pullback uses 7% hard stop; if not stopped, marked to latest available close in the existing report",
            "capital_per_trade": CAPITAL_PER_TRADE,
            "weighting": "equal capital per trade",
        },
        "funnel": {
            "unique_stocks_in_report": metadata.get("unique_stocks"),
            "overall_picks": metadata["overall"].get("picks"),
            "overall_realized": metadata["overall"].get("realized"),
            "overall_pending": metadata["overall"].get("pending"),
            "realized_pullback_trades": len(rows),
            "unique_pullback_stocks": len({row["stock_no"] for row in rows}),
        },
        "variants": summarize_variants(rows),
        "trades": rows,
    }
    return rows, payload


def research_csv_files() -> list[Path]:
    latest_by_code: dict[str, Path] = {}
    for directory in RESEARCH_DIRS:
        for path in directory.glob("*.csv"):
            if path.name.startswith("_"):
                continue
            code = path.name.split("_", 1)[0]
            current = latest_by_code.get(code)
            if current is None or (path.stat().st_mtime, path.name) > (current.stat().st_mtime, current.name):
                latest_by_code[code] = path
    return [path for _, path in sorted(latest_by_code.items())]


def stop_only_fixed_window(entry: Row, exit_candidates: list[Row]) -> dict[str, Any]:
    hard_stop = entry.open * (1 - PULLBACK_HARD_STOP_PCT)
    observed: list[Row] = []
    for row in exit_candidates:
        observed.append(row)
        if row.low <= hard_stop:
            return {
                "exit_date": row.date,
                "exit_price": round(hard_stop, 4),
                "holding_days": len(observed),
                "return_pct": round((hard_stop / entry.open - 1) * 100, 2),
                "mfe_pct": round((max(item.high for item in observed) / entry.open - 1) * 100, 2),
                "mae_pct": round((min(item.low for item in observed) / entry.open - 1) * 100, 2),
                "exit_reason": "hard_stop",
            }
    last = exit_candidates[-1]
    return {
        "exit_date": last.date,
        "exit_price": round(last.close, 4),
        "holding_days": len(exit_candidates),
        "return_pct": round((last.close / entry.open - 1) * 100, 2),
        "mfe_pct": round((max(item.high for item in exit_candidates) / entry.open - 1) * 100, 2),
        "mae_pct": round((min(item.low for item in exit_candidates) / entry.open - 1) * 100, 2),
        "exit_reason": "fixed_window_close",
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


def run_v2_3y() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    files = research_csv_files()
    series: list[tuple[Path, list[Row], dict[str, list[float | None]]]] = []
    skipped_short = 0
    for path in files:
        rows = read_rows(path)
        if len(rows) < MIN_ROWS_3Y:
            skipped_short += 1
            continue
        series.append((path, rows, prepare(rows)))

    raw_matches: list[dict[str, Any]] = []
    scanned_stock_dates = 0
    pending_no_future = 0
    date_counts: Counter[str] = Counter()
    date_scanned: Counter[str] = Counter()

    for path, rows, indicators in series:
        # Require a next-day open and a full fixed horizon after entry.
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
                    date_counts[row.date] += 1

    grouped = group_matches_for_display(raw_matches)
    pullback_items = [item for item in grouped if detect_category(item) == "pullback"]
    path_rows = {str(path): rows for path, rows, _ in series}
    trades: list[dict[str, Any]] = []
    for item in pullback_items:
        rows = path_rows[str(item["source"])]
        signal_index = int(item["row_index"])
        entry_index = signal_index + 1
        exit_candidates = rows[entry_index : entry_index + MAX_HOLD_DAYS]
        if len(exit_candidates) < MAX_HOLD_DAYS:
            pending_no_future += 1
            continue
        entry = rows[entry_index]
        perf = stop_only_fixed_window(entry, exit_candidates)
        ret = float(perf["return_pct"])
        trade = {
            "version": V2_VERSION,
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
        "version": V2_VERSION,
        "description": "Three-year rolling pullback backtest using the same pullback signal classification and equal capital per trade.",
        "methodology": {
            "universe": "expanded three-year research directories: data/research_3y_twse and data/research_3y_tpex",
            "min_rows_per_stock": MIN_ROWS_3Y,
            "entry_rule": "buy next trading day's open after the signal date",
            "exit_rule": "pullback uses 7% hard stop; if not stopped, exit at close after 10 trading days",
            "max_holding_days": MAX_HOLD_DAYS,
            "capital_per_trade": CAPITAL_PER_TRADE,
            "weighting": "equal capital per trade",
        },
        "funnel": {
            "source_files_found": len(files),
            "eligible_three_year_files": len(series),
            "skipped_short_files": skipped_short,
            "scanned_stock_date_observations": scanned_stock_dates,
            "raw_signal_rows_before_grouping": len(raw_matches),
            "grouped_signal_stock_days": len(grouped),
            "grouped_pullback_stock_days": len(pullback_items),
            "pending_no_full_10d_future": pending_no_future,
            "realized_pullback_trades": len(trades),
            "unique_pullback_stocks": len({trade["stock_no"] for trade in trades}),
            "date_start": min(date_scanned) if date_scanned else "",
            "date_end": max(date_scanned) if date_scanned else "",
            "signal_dates": len(date_scanned),
        },
        "variants": summarize_variants(trades),
        "by_year": {
            year: summarize([trade for trade in trades if trade["signal_date"].startswith(year)])
            for year in sorted({trade["signal_date"][:4] for trade in trades})
        },
        "exit_reasons": dict(Counter(trade["exit_reason"] for trade in trades)),
        "trades": trades,
    }
    return trades, payload


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = sorted({key for row in rows for key in row})
    preferred = [
        "version",
        "signal_date",
        "market",
        "stock_no",
        "stock_name",
        "signal_close",
        "entry_date",
        "entry_price",
        "exit_date",
        "exit_price",
        "holding_days",
        "return_pct",
        "mfe_pct",
        "mae_pct",
        "capital",
        "pnl",
        "exit_reason",
        "reasons",
        "category",
        "rank",
    ]
    ordered = [key for key in preferred if key in fieldnames] + [key for key in fieldnames if key not in preferred]
    with path.open("w", encoding="utf-8-sig", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=ordered)
        writer.writeheader()
        writer.writerows(rows)


def version_markdown(payload: dict[str, Any]) -> str:
    variants = payload["variants"]
    lines = [
        f"# {payload['version']}",
        "",
        payload["description"],
        "",
        "## Methodology",
    ]
    for key, value in payload["methodology"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Funnel"])
    for key, value in payload["funnel"].items():
        lines.append(f"- {key}: {value}")
    lines.extend([
        "",
        "## Variant Summary",
        "",
        "| Variant | Trades | Win rate | Avg return | Median return | Capital used | Total PnL |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    labels = {
        "all_pullback": "All pullback",
        "next_open_no_chase": "Next open no chase",
        "next_open_discount_2pct": "Next open discount >= 2%",
        "next_open_discount_5pct": "Next open discount >= 5%",
    }
    for key, summary in variants.items():
        lines.append(
            f"| {labels.get(key, key)} | {summary['trades']} | {summary['win_rate_pct']:.2f}% | "
            f"{summary['avg_return_pct']:.2f}% | {summary['median_return_pct']:.2f}% | "
            f"{summary['capital_used']:,} | {summary['total_pnl']:,} |"
        )
    return "\n".join(lines) + "\n"


def comparison_payload(v1: dict[str, Any], v2: dict[str, Any]) -> dict[str, Any]:
    return {
        "versions": [v1["version"], v2["version"]],
        "capital_per_trade": CAPITAL_PER_TRADE,
        "note": "Both reports use equal capital per trade. V1 preserves the existing recent-10-day hold-to-latest report; V2 is a rolling 3-year fixed-10-trading-day evaluation to avoid multi-year hold bias.",
        "funnel_comparison": {
            v1["version"]: v1["funnel"],
            v2["version"]: v2["funnel"],
        },
        "variant_comparison": {
            variant: {
                v1["version"]: v1["variants"].get(variant),
                v2["version"]: v2["variants"].get(variant),
            }
            for variant in sorted(set(v1["variants"]) | set(v2["variants"]))
        },
    }


def comparison_markdown(payload: dict[str, Any]) -> str:
    variant_labels = {
        "all_pullback": "所有 pullback",
        "next_open_no_chase": "隔日不追高",
        "next_open_discount_2pct": "隔日開低 2%+",
        "next_open_discount_5pct": "隔日開低 5%+",
    }
    lines = [
        "# Pullback Version Comparison",
        "",
        f"- 每筆資金: {payload['capital_per_trade']:,}",
        f"- 說明: {payload['note']}",
        "",
        "## Variant Comparison",
        "",
        "| Variant | Version | Trades | Win rate | Avg return | Median return | Total PnL |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for variant, versions in payload["variant_comparison"].items():
        for version, summary in versions.items():
            if not summary:
                continue
            lines.append(
                f"| {variant_labels.get(variant, variant)} | {version} | {summary['trades']} | "
                f"{summary['win_rate_pct']:.2f}% | {summary['avg_return_pct']:.2f}% | "
                f"{summary['median_return_pct']:.2f}% | {summary['total_pnl']:,} |"
            )
    return "\n".join(lines) + "\n"


def main() -> None:
    REPORT_DIR.mkdir(exist_ok=True)
    v1_trades, v1_payload = read_existing_v1_trades()
    v2_trades, v2_payload = run_v2_3y()
    V1_JSON.write_text(json.dumps(v1_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    V2_JSON.write_text(json.dumps(v2_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    V1_MD.write_text(version_markdown(v1_payload), encoding="utf-8")
    V2_MD.write_text(version_markdown(v2_payload), encoding="utf-8")
    write_csv(V1_CSV, v1_trades)
    write_csv(V2_CSV, v2_trades)
    compare = comparison_payload(v1_payload, v2_payload)
    COMPARE_JSON.write_text(json.dumps(compare, ensure_ascii=False, indent=2), encoding="utf-8")
    COMPARE_MD.write_text(comparison_markdown(compare), encoding="utf-8")
    print(json.dumps({
        "v1": {
            "version": v1_payload["version"],
            "funnel": v1_payload["funnel"],
            "variants": v1_payload["variants"],
        },
        "v2": {
            "version": v2_payload["version"],
            "funnel": v2_payload["funnel"],
            "variants": v2_payload["variants"],
            "by_year": v2_payload["by_year"],
        },
        "outputs": [str(V1_JSON), str(V2_JSON), str(COMPARE_JSON), str(COMPARE_MD)],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
