#!/usr/bin/env python3
"""One-year pullback backtest focused on next-open discount entries and wider swing exits."""

from __future__ import annotations

import csv
import html
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
from run_market_backtest import STRATEGIES, Row, csv_files, prepare, read_rows
from signal_scoring import signal_score


REPORT_DIR = Path("reports")
CAPITAL_PER_TRADE = 100_000
MIN_ROWS = 80

ENTRY_DISCOUNT_PCT = 0.02
HARD_STOP_PCT = 0.07

BASELINE_MAX_HOLD_DAYS = 10
BASELINE_TRAILING_ACTIVATION_PCT = 0.07
BASELINE_TRAILING_DRAWDOWN_PCT = 0.07

SWING_MAX_HOLD_DAYS = 20
SWING_TRAILING_ACTIVATION_PCT = 0.12
SWING_TRAILING_DRAWDOWN_PCT = 0.12
SWING_PROFIT_FLOOR_PCT = 0.02

VERSION = "PB-V4.0-1y-discount2-swing"
OUT_JSON = REPORT_DIR / "pullback_pb_v4_0_1y_discount2_swing.json"
OUT_CSV = REPORT_DIR / "pullback_pb_v4_0_1y_discount2_swing_trades.csv"
OUT_MD = REPORT_DIR / "pullback_pb_v4_0_1y_discount2_swing.md"
OUT_HTML = REPORT_DIR / "pullback_pb_v4_0_1y_discount2_swing.html"


def summarize(trades: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(row["return_pct"]) for row in trades]
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


def pct(value: float) -> str:
    return f"{value:.2f}%"


def money(value: int) -> str:
    return f"{value:,}"


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
        "source": str(path),
        "row_index": index,
    }


def load_pullback_candidates() -> tuple[list[dict[str, Any]], dict[str, list[Row]], dict[str, Any]]:
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
    for path, rows, indicators in series:
        max_signal_index = len(rows) - SWING_MAX_HOLD_DAYS - 2
        for index in range(60, max_signal_index + 1):
            row = rows[index]
            scanned_stock_dates += 1
            if row.volume < MIN_SIGNAL_VOLUME_SHARES:
                continue
            for strategy_name, signal in STRATEGIES.items():
                reason = signal(rows, indicators, index)
                if reason:
                    raw_matches.append(make_match(path, rows, indicators, index, strategy_name, reason))

    grouped = group_matches_for_display(raw_matches)
    pullback_items = [item for item in grouped if detect_category(item) == "pullback"]
    rows_by_source = {str(path): rows for path, rows, _ in series}
    funnel = {
        "source_files_found": len(source_files),
        "eligible_one_year_files": len(series),
        "skipped_short_files": skipped_short,
        "scanned_stock_date_observations": scanned_stock_dates,
        "raw_signal_rows_before_grouping": len(raw_matches),
        "grouped_signal_stock_days": len(grouped),
        "grouped_pullback_stock_days": len(pullback_items),
    }
    return pullback_items, rows_by_source, funnel


def baseline_exit(entry: Row, exit_candidates: list[Row]) -> dict[str, Any]:
    hard_stop = entry.open * (1 - HARD_STOP_PCT)
    activation_price = entry.open * (1 + BASELINE_TRAILING_ACTIVATION_PCT)
    highest = entry.open
    trailing_stop: float | None = None
    observed: list[Row] = []

    for row in exit_candidates[:BASELINE_MAX_HOLD_DAYS]:
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
            return build_exit_result(entry, observed, exit_price, exit_reason)

        highest = max(highest, row.high)
        if highest >= activation_price:
            trailing_stop = max(trailing_stop or 0, highest * (1 - BASELINE_TRAILING_DRAWDOWN_PCT))

    return build_exit_result(entry, exit_candidates[:BASELINE_MAX_HOLD_DAYS], exit_candidates[BASELINE_MAX_HOLD_DAYS - 1].close, "max_hold_close")


def swing_exit(entry: Row, exit_candidates: list[Row]) -> dict[str, Any]:
    hard_stop = entry.open * (1 - HARD_STOP_PCT)
    activation_price = entry.open * (1 + SWING_TRAILING_ACTIVATION_PCT)
    floor_price = entry.open * (1 + SWING_PROFIT_FLOOR_PCT)
    highest = entry.open
    trailing_stop: float | None = None
    observed: list[Row] = []

    for row in exit_candidates[:SWING_MAX_HOLD_DAYS]:
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
            return build_exit_result(entry, observed, exit_price, exit_reason)

        highest = max(highest, row.high)
        if highest >= activation_price:
            trailing_stop = max(trailing_stop or 0, highest * (1 - SWING_TRAILING_DRAWDOWN_PCT), floor_price)

    return build_exit_result(entry, exit_candidates[:SWING_MAX_HOLD_DAYS], exit_candidates[SWING_MAX_HOLD_DAYS - 1].close, "max_hold_close")


def build_exit_result(entry: Row, observed: list[Row], exit_price: float, exit_reason: str) -> dict[str, Any]:
    return {
        "exit_date": observed[-1].date,
        "exit_price": round(exit_price, 4),
        "holding_days": len(observed),
        "return_pct": round((exit_price / entry.open - 1) * 100, 2),
        "mfe_pct": round((max(item.high for item in observed) / entry.open - 1) * 100, 2),
        "mae_pct": round((min(item.low for item in observed) / entry.open - 1) * 100, 2),
        "exit_reason": exit_reason,
    }


def build_trade(item: dict[str, Any], entry: Row, perf: dict[str, Any], *, version: str, exit_style: str) -> dict[str, Any]:
    ret = float(perf["return_pct"])
    return {
        "version": version,
        "exit_style": exit_style,
        "signal_date": item["date"],
        "market": item["market"],
        "stock_no": item["stock_no"],
        "stock_name": item["stock_name"],
        "signal_close": round(float(item["close"]), 4),
        "entry_date": entry.date,
        "entry_price": round(entry.open, 4),
        "entry_discount_pct": round((entry.open / float(item["close"]) - 1) * 100, 2),
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


def run_backtest() -> dict[str, Any]:
    pullback_items, rows_by_source, funnel = load_pullback_candidates()
    baseline_trades: list[dict[str, Any]] = []
    swing_trades: list[dict[str, Any]] = []

    for item in pullback_items:
        rows = rows_by_source[str(item["source"])]
        signal_index = int(item["row_index"])
        entry_index = signal_index + 1
        if entry_index >= len(rows):
            continue
        entry = rows[entry_index]
        if entry.open > float(item["close"]) * (1 - ENTRY_DISCOUNT_PCT):
            continue

        baseline_candidates = rows[entry_index : entry_index + BASELINE_MAX_HOLD_DAYS]
        swing_candidates = rows[entry_index : entry_index + SWING_MAX_HOLD_DAYS]
        if len(baseline_candidates) < BASELINE_MAX_HOLD_DAYS or len(swing_candidates) < SWING_MAX_HOLD_DAYS:
            continue

        baseline_trades.append(
            build_trade(item, entry, baseline_exit(entry, baseline_candidates), version=VERSION, exit_style="baseline_d2")
        )
        swing_trades.append(
            build_trade(item, entry, swing_exit(entry, swing_candidates), version=VERSION, exit_style="swing_d2")
        )

    baseline_map = {(row["signal_date"], row["market"], row["stock_no"]): row for row in baseline_trades}
    deltas: list[dict[str, Any]] = []
    for trade in swing_trades:
        key = (trade["signal_date"], trade["market"], trade["stock_no"])
        previous = baseline_map[key]
        deltas.append(
            {
                "signal_date": trade["signal_date"],
                "market": trade["market"],
                "stock_no": trade["stock_no"],
                "stock_name": trade["stock_name"],
                "signal_close": trade["signal_close"],
                "entry_price": trade["entry_price"],
                "entry_discount_pct": trade["entry_discount_pct"],
                "baseline_return_pct": previous["return_pct"],
                "swing_return_pct": trade["return_pct"],
                "delta_return_pct": round(trade["return_pct"] - previous["return_pct"], 2),
                "baseline_exit_reason": previous["exit_reason"],
                "swing_exit_reason": trade["exit_reason"],
                "swing_holding_days": trade["holding_days"],
                "score": trade["score"],
                "reasons": trade["reasons"],
            }
        )

    deltas.sort(key=lambda row: row["delta_return_pct"], reverse=True)
    funnel["discount2_realized_trades"] = len(swing_trades)
    funnel["discount2_unique_stocks"] = len({row["stock_no"] for row in swing_trades})
    payload = {
        "version": VERSION,
        "description": "One-year pullback backtest that only enters when next open is at least 2% below the signal close, then uses a wider swing exit to reduce premature trailing-stop shakeouts.",
        "methodology": {
            "universe": "default one-year all_twse/all_tpex data files",
            "entry_rule": "buy next trading day's open only when open <= signal close * 0.98",
            "baseline_exit_rule": "7% hard stop; after +7% MFE, 7% trailing stop; max hold 10 trading days",
            "swing_exit_rule": "7% hard stop; after +12% MFE, 12% trailing stop with a +2% profit floor; max hold 20 trading days",
            "capital_per_trade": CAPITAL_PER_TRADE,
            "weighting": "equal capital per trade",
        },
        "funnel": funnel,
        "baseline_summary": summarize(baseline_trades),
        "swing_summary": summarize(swing_trades),
        "baseline_exit_reasons": dict(Counter(row["exit_reason"] for row in baseline_trades)),
        "swing_exit_reasons": dict(Counter(row["exit_reason"] for row in swing_trades)),
        "top_improvements": deltas[:20],
        "top_regressions": sorted(deltas, key=lambda row: row["delta_return_pct"])[:20],
        "trades": swing_trades,
    }
    return payload


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    preferred = [
        "version", "exit_style", "signal_date", "market", "stock_no", "stock_name", "signal_close",
        "entry_date", "entry_price", "entry_discount_pct", "exit_date", "exit_price", "holding_days",
        "return_pct", "mfe_pct", "mae_pct", "capital", "pnl", "exit_reason", "score", "reasons",
    ]
    fields = sorted({key for row in rows for key in row})
    ordered = [key for key in preferred if key in fields] + [key for key in fields if key not in preferred]
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=ordered)
        writer.writeheader()
        writer.writerows(rows)


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# {payload['version']}",
        "",
        payload["description"],
        "",
        "## Summary",
        "",
        "| Version | Trades | Win rate | Avg return | Median return | Total PnL |",
        "|---|---:|---:|---:|---:|---:|",
        f"| Baseline discount-2 | {payload['baseline_summary']['trades']} | {payload['baseline_summary']['win_rate_pct']:.2f}% | {payload['baseline_summary']['avg_return_pct']:.2f}% | {payload['baseline_summary']['median_return_pct']:.2f}% | {payload['baseline_summary']['total_pnl']:,} |",
        f"| Swing discount-2 | {payload['swing_summary']['trades']} | {payload['swing_summary']['win_rate_pct']:.2f}% | {payload['swing_summary']['avg_return_pct']:.2f}% | {payload['swing_summary']['median_return_pct']:.2f}% | {payload['swing_summary']['total_pnl']:,} |",
        "",
        "## Funnel",
    ]
    for key, value in payload["funnel"].items():
        lines.append(f"- {key}: {value}")
    lines.extend([
        "",
        "## Exit Reason Comparison",
        "",
        f"- baseline: {payload['baseline_exit_reasons']}",
        f"- swing: {payload['swing_exit_reasons']}",
        "",
        "## Top Improvements",
    ])
    for row in payload["top_improvements"][:10]:
        lines.append(
            f"- {row['signal_date']} {row['stock_no']} {row['stock_name']}: "
            f"{row['baseline_return_pct']:.2f}% -> {row['swing_return_pct']:.2f}% "
            f"({row['delta_return_pct']:+.2f} pts)"
        )
    return "\n".join(lines) + "\n"


def render_html(payload: dict[str, Any]) -> str:
    baseline = payload["baseline_summary"]
    swing = payload["swing_summary"]
    improvement_rows = "".join(
        "<tr>"
        f"<td>{row['signal_date']}</td>"
        f"<td>{html.escape(row['stock_no'] + ' ' + row['stock_name'])}</td>"
        f"<td>{pct(row['entry_discount_pct'])}</td>"
        f"<td>{pct(row['baseline_return_pct'])}</td>"
        f"<td>{pct(row['swing_return_pct'])}</td>"
        f"<td>{pct(row['delta_return_pct'])}</td>"
        f"<td>{html.escape(row['baseline_exit_reason'])}</td>"
        f"<td>{html.escape(row['swing_exit_reason'])}</td>"
        "</tr>"
        for row in payload["top_improvements"][:15]
    )
    regression_rows = "".join(
        "<tr>"
        f"<td>{row['signal_date']}</td>"
        f"<td>{html.escape(row['stock_no'] + ' ' + row['stock_name'])}</td>"
        f"<td>{pct(row['entry_discount_pct'])}</td>"
        f"<td>{pct(row['baseline_return_pct'])}</td>"
        f"<td>{pct(row['swing_return_pct'])}</td>"
        f"<td>{pct(row['delta_return_pct'])}</td>"
        f"<td>{html.escape(row['baseline_exit_reason'])}</td>"
        f"<td>{html.escape(row['swing_exit_reason'])}</td>"
        "</tr>"
        for row in payload["top_regressions"][:15]
    )
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{payload['version']}</title>
  <style>
    :root {{
      --ink: #15202b;
      --muted: #617487;
      --line: #d7dfe7;
      --panel: #f5f7f9;
      --accent: #0f766e;
      --warn: #9a3412;
      --bg: #ffffff;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: "Microsoft JhengHei", "Noto Sans TC", system-ui, sans-serif; color: var(--ink); background: var(--bg); }}
    header, main {{ max-width: 1180px; margin: auto; padding: 28px 24px; }}
    header {{ border-bottom: 1px solid var(--line); }}
    h1 {{ margin: 0 0 10px; font-size: 28px; }}
    h2 {{ margin: 28px 0 12px; font-size: 20px; }}
    p {{ margin: 0; color: var(--muted); line-height: 1.6; }}
    .cards {{ display: grid; grid-template-columns: repeat(2, minmax(240px, 1fr)); gap: 14px; margin-top: 20px; }}
    .card {{ border: 1px solid var(--line); border-radius: 8px; padding: 16px; background: var(--panel); }}
    .card strong {{ display: block; font-size: 22px; margin: 6px 0; }}
    .delta {{ color: var(--accent); font-weight: 700; }}
    .warn {{ color: var(--warn); font-weight: 700; }}
    .rulebox {{ display: grid; grid-template-columns: repeat(2, minmax(240px, 1fr)); gap: 14px; margin-top: 18px; }}
    .table-wrap {{ overflow: auto; border: 1px solid var(--line); border-radius: 8px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: right; white-space: nowrap; }}
    th {{ background: #eef2f6; }}
    th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) {{ text-align: left; }}
    .funnel {{ columns: 2; margin: 14px 0 0; padding-left: 18px; color: var(--muted); }}
    @media (max-width: 760px) {{
      header, main {{ padding: 20px 16px; }}
      .cards, .rulebox {{ grid-template-columns: 1fr; }}
      .funnel {{ columns: 1; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>{payload['version']}</h1>
    <p>{html.escape(payload['description'])}</p>
    <div class="rulebox">
      <div class="card">
        <span>進場</span>
        <strong>隔天開低 2% 才買</strong>
        <p>只保留 next open 小於等於訊號收盤價的 98% 的 pullback，避免追到已經反彈一段的弱勢回抽。</p>
      </div>
      <div class="card">
        <span>出場</span>
        <strong>先讓它跑，再開始保護</strong>
        <p>保留 7% 停損，但把移動停利改成 +12% 才啟動、12% 回撤才出，並給 +2% 利潤底線，最長持有 20 天。</p>
      </div>
    </div>
  </header>
  <main>
    <div class="cards">
      <section class="card">
        <span>Baseline discount-2</span>
        <strong>{pct(baseline['avg_return_pct'])}</strong>
        <div>勝率 {pct(baseline['win_rate_pct'])}</div>
        <div>中位數 {pct(baseline['median_return_pct'])}</div>
        <div>總損益 {money(baseline['total_pnl'])}</div>
      </section>
      <section class="card">
        <span>Swing discount-2</span>
        <strong>{pct(swing['avg_return_pct'])}</strong>
        <div>勝率 {pct(swing['win_rate_pct'])}</div>
        <div>中位數 {pct(swing['median_return_pct'])}</div>
        <div>總損益 {money(swing['total_pnl'])}</div>
      </section>
    </div>
    <p style="margin-top:16px;">這版的取向不是提高每一筆的命中率，而是減少過早被震出場，讓真正走出波段的 pullback 有機會把後面那一段吃到。</p>
    <ul class="funnel">
      {''.join(f'<li>{html.escape(key)}: {value}</li>' for key, value in payload['funnel'].items())}
    </ul>
    <h2>改善最多的交易</h2>
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>訊號日</th><th>個股</th><th>折價</th><th>舊版</th><th>新版</th><th>差異</th><th>舊出場</th><th>新出場</th></tr>
        </thead>
        <tbody>{improvement_rows}</tbody>
      </table>
    </div>
    <h2>退步最多的交易</h2>
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>訊號日</th><th>個股</th><th>折價</th><th>舊版</th><th>新版</th><th>差異</th><th>舊出場</th><th>新出場</th></tr>
        </thead>
        <tbody>{regression_rows}</tbody>
      </table>
    </div>
  </main>
</body>
</html>"""


def main() -> None:
    REPORT_DIR.mkdir(exist_ok=True)
    payload = run_backtest()
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_MD.write_text(render_markdown(payload), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    write_csv(OUT_CSV, payload["trades"])
    print(json.dumps({
        "version": payload["version"],
        "baseline_summary": payload["baseline_summary"],
        "swing_summary": payload["swing_summary"],
        "outputs": [str(OUT_JSON), str(OUT_CSV), str(OUT_MD), str(OUT_HTML)],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
