#!/usr/bin/env python3
"""Backtest all signaled stocks over recent trading days."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import types
from pathlib import Path
from typing import Any

plot_kline_stub = types.ModuleType("plot_kline")
plot_kline_stub.plot_chart = lambda *args, **kwargs: None
sys.modules.setdefault("plot_kline", plot_kline_stub)

from alert_signals import group_matches_for_display
from analyze_recent_breakout_backtest import (
    add_capital_metrics,
    available_trading_dates,
    capital_summary,
    performance_for_signal,
    signals_as_of,
    summarize,
)
from run_market_backtest import csv_files, read_rows


REPORT_DIR = Path("reports")
BASE_FILES = {
    "csv": REPORT_DIR / "recent_all_signal_backtest.csv",
    "md": REPORT_DIR / "recent_all_signal_backtest.md",
    "json": REPORT_DIR / "recent_all_signal_backtest.json",
    "html": REPORT_DIR / "recent_all_signal_backtest.html",
}
SMART_FILES = {
    "csv": REPORT_DIR / "recent_all_signal_backtest_smart.csv",
    "md": REPORT_DIR / "recent_all_signal_backtest_smart.md",
    "json": REPORT_DIR / "recent_all_signal_backtest_smart.json",
    "html": REPORT_DIR / "recent_all_signal_backtest_smart.html",
}

PULLBACK_PATTERN = re.compile(r"回測|支撐|月線|季線|跌破月線", re.IGNORECASE)
BREAKOUT_PATTERN = re.compile(r"糾結|帶量紅K|跳空|站回|突破", re.IGNORECASE)


def sort_rows_by_pnl(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def sort_key(row: dict[str, Any]) -> tuple[float, float, str, int]:
        pnl = float(row["pnl"]) if isinstance(row.get("pnl"), (int, float)) else float("-inf")
        ret = float(row["return_pct"]) if isinstance(row.get("return_pct"), (int, float)) else float("-inf")
        return (pnl, ret, str(row["signal_date"]), -int(row["rank"]))

    return sorted(rows, key=sort_key, reverse=True)


def detect_category(item: dict[str, Any]) -> str:
    reasons = " / ".join(str(value) for value in item.get("reasons", []))
    if BREAKOUT_PATTERN.search(reasons):
        return "breakout"
    if PULLBACK_PATTERN.search(reasons):
        return "pullback"
    return "breakout"


def build_rows(days: int, exit_mode: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
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

        grouped = group_matches_for_display(matches)
        day_rows: list[dict[str, Any]] = []
        for rank, item in enumerate(grouped, start=1):
            category = detect_category(item)
            perf = performance_for_signal(item, rows_by_path, latest_date, exit_mode=exit_mode, category=category)
            row = {
                "signal_date": as_of,
                "category": category,
                "rank": rank,
                "market": item["market"],
                "stock_no": item["stock_no"],
                "stock_name": item["stock_name"],
                "signal_close": item["close"],
                "score": item.get("score"),
                "score_label": item.get("score_label"),
                "weighted_score": item.get("weighted_score", ""),
                "reasons": " / ".join(item.get("reasons", [])),
                "strategy_count": len(item.get("reasons", [])),
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
            "smart": "pullback uses 7% hard stop; breakout uses 7% hard stop and activates a 7% trailing stop only after +15% MFE",
        }[exit_mode],
        "signal_scope": "all grouped stocks with any signal on each target trading day",
        "exit_mode": exit_mode,
        "by_day": by_day,
        "overall": summarize(output_rows),
        "capital_per_trade": 100_000,
        "capital_summary": capital_summary(output_rows),
        "unique_stocks": len({row["stock_no"] for row in output_rows}),
    }
    return output_rows, metadata


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    REPORT_DIR.mkdir(exist_ok=True)
    fieldnames = [
        "signal_date",
        "category",
        "rank",
        "market",
        "stock_no",
        "stock_name",
        "signal_close",
        "score",
        "score_label",
        "weighted_score",
        "reasons",
        "strategy_count",
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


def write_markdown(path: Path, rows: list[dict[str, Any]], metadata: dict[str, Any]) -> None:
    lines = [
        "# Recent All Signal Backtest",
        "",
        f"- Latest data date: {metadata['latest_date']}",
        f"- Signal dates: {', '.join(metadata['target_dates'])}",
        f"- Signal scope: {metadata['signal_scope']}",
        f"- Entry rule: {metadata['entry_rule']}",
        f"- Exit rule: {metadata['exit_rule']}",
        "",
        "## Summary",
        "",
        f"- Signal rows: {metadata['overall']['picks']}",
        f"- Unique stocks: {metadata['unique_stocks']}",
        f"- Realized trades: {metadata['overall']['realized']}",
        f"- Avg return: {metadata['overall']['avg_return_pct']}%",
        f"- Win rate: {metadata['overall']['win_rate_pct']}%",
        f"- Total PnL: {metadata['capital_summary']['total_pnl']}",
        "",
        "## Trades",
        "",
        "| Signal Date | Category | Rank | Stock | Reasons | Entry | Exit | Days | Return % | PnL |",
        "|---|---|---:|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        stock = f"{row['stock_no']} {row['stock_name']} ({row['market']})"
        entry = f"{row['entry_date']} @ {row['entry_price']}" if row["entry_date"] else "-"
        exit_text = f"{row['exit_date']} @ {row['exit_price']}" if row["exit_date"] else "-"
        lines.append(
            "| {signal_date} | {category} | {rank} | {stock} | {reasons} | {entry} | {exit} | {holding_days} | {return_pct} | {pnl} |".format(
                signal_date=row["signal_date"],
                category=row["category"],
                rank=row["rank"],
                stock=stock,
                reasons=row["reasons"],
                entry=entry,
                exit=exit_text,
                holding_days=row["holding_days"],
                return_pct=row["return_pct"] if row["return_pct"] != "" else "-",
                pnl=row["pnl"] if row["pnl"] != "" else "-",
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_html(path: Path, rows: list[dict[str, Any]], metadata: dict[str, Any]) -> None:
    summary = metadata["overall"]
    capital = metadata["capital_summary"]
    title = "All Signal Backtest" if metadata["exit_mode"] == "baseline" else "All Signal Backtest Smart"
    table_rows = []
    for row in rows:
        ret = row["return_pct"]
        pnl = row["pnl"]
        tone = "gain" if isinstance(ret, (int, float)) and float(ret) >= 0 else "loss"
        ret_text = f"{float(ret):.2f}%" if isinstance(ret, (int, float)) else "-"
        pnl_text = f"{int(pnl):+,}" if isinstance(pnl, (int, float)) else "-"
        table_rows.append(
            "<tr>"
            f"<td>{row['signal_date']}</td>"
            f"<td>{row['category']}</td>"
            f"<td>{row['rank']}</td>"
            f"<td>{row['stock_no']} {row['stock_name']}</td>"
            f"<td>{row['reasons']}</td>"
            f"<td>{row['entry_date'] or '-'}</td>"
            f"<td>{row['exit_date'] or '-'}</td>"
            f"<td>{row['holding_days']}</td>"
            f"<td class='{tone}'>{ret_text}</td>"
            f"<td class='{tone}'>{pnl_text}</td>"
            "</tr>"
        )
    html_text = f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      --bg: #f5f7fa; --panel: #fff; --text: #172033; --muted: #667085; --line: #d8dee8; --gain: #0f8a5f; --loss: #c2410c;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--bg); color: var(--text); font-family: "Microsoft JhengHei", "Noto Sans TC", "Segoe UI", Arial, sans-serif; }}
    main {{ max-width: 1320px; margin: 0 auto; padding: 28px 18px 48px; }}
    h1 {{ margin: 0 0 6px; font-size: 28px; }}
    h2 {{ margin: 0 0 14px; font-size: 18px; }}
    p {{ margin: 0; color: var(--muted); line-height: 1.6; }}
    .cards {{ display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; margin: 18px 0; }}
    .card {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 16px; box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04); }}
    .card span {{ display: block; font-size: 24px; font-weight: 700; font-variant-numeric: tabular-nums; }}
    .card label {{ display: block; margin-top: 5px; color: var(--muted); font-size: 13px; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; white-space: nowrap; }}
    th, td {{ padding: 10px 9px; border-bottom: 1px solid #eef1f5; text-align: left; }}
    th {{ color: var(--muted); font-weight: 600; background: #fbfcfe; position: sticky; top: 0; }}
    .gain {{ color: var(--gain); }} .loss {{ color: var(--loss); }}
    @media (max-width: 1000px) {{ .cards {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>{title}</h1>
      <p>10 個交易日內，只要有訊號跳出的所有個股；每個股票 / 訊號日一筆，投入 100,000，依 {metadata['latest_date']} 最新收盤估值。出場模式：{metadata['exit_mode']}。</p>
    </header>
    <div class="cards">
      <div class="card"><span>{summary['picks']}</span><label>訊號筆數</label></div>
      <div class="card"><span>{metadata['unique_stocks']}</span><label>個股數</label></div>
      <div class="card"><span>{summary['realized']}</span><label>已進場筆數</label></div>
      <div class="card"><span>{summary['avg_return_pct']}%</span><label>平均報酬</label></div>
      <div class="card"><span>{capital['total_pnl']:+,}</span><label>總損益</label></div>
    </div>
    <section class="card">
      <h2>交易明細</h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th>訊號日</th><th>分類</th><th>排名</th><th>股票</th><th>理由</th><th>進場</th><th>估值日</th><th>天數</th><th>報酬%</th><th>損益</th></tr></thead>
          <tbody>{"".join(table_rows)}</tbody>
        </table>
      </div>
    </section>
  </main>
</body>
</html>
"""
    path.write_text(html_text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest all signaled stocks over recent trading days.")
    parser.add_argument("--days", type=int, default=10, help="Number of recent trading days to include.")
    parser.add_argument("--smart", action="store_true", help="Pullback uses 7% stop; breakout uses 7% stop and trailing activates after +15% MFE.")
    args = parser.parse_args()

    exit_mode = "smart" if args.smart else "baseline"
    files = SMART_FILES if args.smart else BASE_FILES
    rows, metadata = build_rows(days=args.days, exit_mode=exit_mode)
    rows = sort_rows_by_pnl(rows)
    write_csv(files["csv"], rows)
    write_markdown(files["md"], rows, metadata)
    files["json"].write_text(json.dumps({"metadata": metadata, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    build_html(files["html"], rows, metadata)
    print(f"Wrote {files['csv']}")
    print(f"Wrote {files['md']}")
    print(f"Wrote {files['json']}")
    print(f"Wrote {files['html']}")
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
