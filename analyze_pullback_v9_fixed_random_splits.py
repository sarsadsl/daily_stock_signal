#!/usr/bin/env python3
"""Fixed V9+ pool randomized 60/20/20 stock split tests."""

from __future__ import annotations

import html
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from analyze_pullback_multitimeframe_search import enrich_trades, rule_label, select
from analyze_pullback_technical_phenotypes import find_series, make_series_map
from analyze_pullback_plus_independent_versions import (
    INDEPENDENT_EXIT_LABELS,
    V9_ENTRY_RULE,
    compute_independent_exits,
    target_summary,
)
from analyze_pullback_plus_random_splits import SEEDS, random_stock_groups, strategy_stats, stock_key
from pullback_lifecycle_filters import filter_same_stock_mother_entries
from run_market_backtest import csv_files

REPORT_DIR = Path("reports")
OUT_JSON = REPORT_DIR / "pullback_v9_fixed_random_splits.json"
OUT_HTML = REPORT_DIR / "pullback_v9_fixed_random_splits.html"
OUT_MD = REPORT_DIR / "pullback_v9_fixed_random_splits.md"
VERSION = "PB-V9-fixed-random-stock-splits"
FIXED_EXIT_STYLE = "weekly_core"


def stock_name(row: dict[str, Any]) -> str:
    return str(row.get("stock_name") or row.get("name") or "")


def stock_listing(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = stock_key(row)
        grouped.setdefault(
            key,
            {
                "key": key,
                "market": row.get("market"),
                "stock_no": row.get("stock_no"),
                "stock_name": stock_name(row),
                "trades": 0,
                "signal_dates": [],
            },
        )
        grouped[key]["trades"] += 1
        grouped[key]["signal_dates"].append(row.get("signal_date"))
    return sorted(grouped.values(), key=lambda item: (str(item["market"]), str(item["stock_no"])))


def build_fixed_v9_rows() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    enriched, _ = enrich_trades()
    selected_features = select(enriched, V9_ENTRY_RULE)
    selected_keys = {(row["signal_date"], row["market"], row["stock_no"]) for row in selected_features}
    independent_exits = compute_independent_exits(enriched)
    rows = [
        row
        for row in independent_exits[FIXED_EXIT_STYLE]
        if (row["signal_date"], row["market"], row["stock_no"]) in selected_keys
    ]
    raw_row_count = len(rows)
    series = make_series_map(csv_files())
    rows, lifecycle_diagnostics = filter_same_stock_mother_entries(rows, series, find_series, cooldown_trading_days=10)
    metadata = {
        "entry_rule": V9_ENTRY_RULE,
        "entry_label": rule_label(V9_ENTRY_RULE),
        "exit_style": FIXED_EXIT_STYLE,
        "exit_label": INDEPENDENT_EXIT_LABELS[FIXED_EXIT_STYLE],
        "trades": len(rows),
        "raw_trades_before_lifecycle_filter": raw_row_count,
        "lifecycle_filter": {
            "rule": "Reject same-stock mother/base entries while a prior mother is still open, or when another accepted same-stock buy occurred in the prior 10 trading days.",
            "input_rows": lifecycle_diagnostics["input_rows"],
            "accepted_rows": lifecycle_diagnostics["accepted_rows"],
            "rejected_rows": lifecycle_diagnostics["rejected_rows"],
            "cooldown_trading_days": lifecycle_diagnostics["cooldown_trading_days"],
            "rejection_counts": lifecycle_diagnostics["rejection_counts"],
            "rejected_examples": lifecycle_diagnostics["rejected_examples"],
        },
        "stocks": len({stock_key(row) for row in rows}),
        "signal_date_start": min(row["signal_date"] for row in rows) if rows else None,
        "signal_date_end": max(row["signal_date"] for row in rows) if rows else None,
        "score_distribution": dict(sorted(Counter(row.get("score") for row in rows).items(), reverse=True)),
        "stock_listing": stock_listing(rows),
    }
    return rows, metadata


def random_runs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for seed in SEEDS:
        groups, counts = random_stock_groups(rows, seed)
        summaries = {name: target_summary(group_rows) for name, group_rows in groups.items()}
        stock_lists = {name: stock_listing(group_rows) for name, group_rows in groups.items() if name != "full"}
        output.append({
            "seed": seed,
            "stock_counts": counts,
            "trade_counts": {name: len(group_rows) for name, group_rows in groups.items()},
            "summaries": summaries,
            "stock_lists": stock_lists,
        })
    return output


def run() -> dict[str, Any]:
    rows, metadata = build_fixed_v9_rows()
    runs = random_runs(rows)
    return {
        "version": VERSION,
        "methodology": {
            "purpose": "Test the fixed V9+ pool with 10 randomized stock-code 60/20/20 splits.",
            "fixed_entry": "V9+ entry is fixed; no entry rule re-selection per seed.",
            "fixed_exit": "weekly_core is fixed; no exit style re-selection per seed.",
            "split": "Stocks, not trades, are randomly split into 60% train, 20% validation, 20% test for each seed. The same stock cannot appear in more than one split within a seed.",
            "target": "Observe robustness against the 60% win-rate / 10% average-return target.",
        },
        "universe": metadata,
        "full_summary": target_summary(rows),
        "runs": runs,
        "statistics": strategy_stats(runs),
        "trades": rows,
    }


def pct(value: Any) -> str:
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return "-"


def summary_text(summary: dict[str, Any]) -> str:
    return (
        f"{summary['trades']} 筆｜{summary['win_rate_pct']:.2f}%｜"
        f"平均 {summary['avg_return_pct']:.2f}%｜中位 {summary['median_return_pct']:.2f}%｜"
        f"未實現 {summary.get('unresolved', 0)}"
    )


def render_html(payload: dict[str, Any]) -> str:
    stats = payload["statistics"]["stock_test"]
    run_rows = "".join(
        f"<tr><td>{run['seed']}</td>"
        f"<td>{run['stock_counts']['stock_train']} / {run['stock_counts']['stock_validation']} / {run['stock_counts']['stock_test']}</td>"
        f"<td>{run['trade_counts']['stock_train']} / {run['trade_counts']['stock_validation']} / {run['trade_counts']['stock_test']}</td>"
        f"<td>{pct(run['summaries']['stock_train']['win_rate_pct'])} / {pct(run['summaries']['stock_train']['avg_return_pct'])}</td>"
        f"<td>{pct(run['summaries']['stock_validation']['win_rate_pct'])} / {pct(run['summaries']['stock_validation']['avg_return_pct'])}</td>"
        f"<td>{pct(run['summaries']['stock_test']['win_rate_pct'])} / {pct(run['summaries']['stock_test']['avg_return_pct'])}</td>"
        f"<td>{run['summaries']['stock_test'].get('unresolved', 0)}</td>"
        f"<td>{'YES' if run['summaries']['stock_test']['win_rate_pct'] >= 60 and run['summaries']['stock_test']['avg_return_pct'] >= 10 else 'NO'}</td></tr>"
        for run in payload["runs"]
    )
    stock_rows = "".join(
        f"<tr><td>{html.escape(str(item['market']))}</td><td>{html.escape(str(item['stock_no']))}</td><td>{html.escape(item['stock_name'])}</td><td>{item['trades']}</td><td>{html.escape(', '.join(map(str, item['signal_dates'])))}</td></tr>"
        for item in payload["universe"]["stock_listing"]
    )
    return f"""<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{VERSION}</title><style>
:root{{--bg:#f6f7fb;--paper:#fff;--ink:#172033;--muted:#667085;--line:#e4e7ec;--bad:#b42318;--blue:#2563eb}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 system-ui,'Microsoft JhengHei',sans-serif}}header,main{{max-width:1400px;margin:auto;padding:28px 20px}}header{{border-bottom:1px solid var(--line)}}h1{{margin:0 0 8px;font-size:30px}}h2{{margin:28px 0 10px;font-size:20px}}p{{color:var(--muted)}}.metrics{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1px;background:var(--line);border:1px solid var(--line);margin-top:22px}}.metric{{background:#fff;padding:16px}}.metric span,.metric small{{display:block;color:var(--muted)}}.metric b{{font-size:22px}}.warn{{border-left:4px solid var(--bad);background:#fef3f2;padding:12px 14px;margin:18px 0;border-radius:12px}}.table{{overflow:auto;border:1px solid var(--line);background:#fff}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:right;vertical-align:top}}th:first-child,td:first-child{{text-align:left}}thead th{{background:#f8fafc;color:var(--muted);font-size:12px}}@media(max-width:900px){{.metrics{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}@media(max-width:560px){{header,main{{padding:18px 10px}}.metrics{{grid-template-columns:1fr}}}}
</style></head><body><header><h1>{VERSION}</h1><p>固定 V9+ 股池與 weekly_core 出場，做 10 次股票隨機 60/20/20 切分。</p><div class='metrics'><div class='metric'><span>V9+ full</span><b>{payload['full_summary']['win_rate_pct']:.2f}% / {payload['full_summary']['avg_return_pct']:.2f}%</b><small>{payload['full_summary']['trades']} 筆｜{payload['universe']['stocks']} 檔｜未實現 {payload['full_summary'].get('unresolved', 0)}</small></div><div class='metric'><span>Random test mean</span><b>{stats['win_rate_pct']['mean']:.2f}% / {stats['avg_return_pct']['mean']:.2f}%</b><small>平均 test 筆數 {stats['trades']['mean']}</small></div><div class='metric'><span>Pass 60/10</span><b>{stats['pass_60win_10avg_count']} / 10</b><small>avg>=10：{stats['avg_ge_10_count']} / 10｜win>=60：{stats['win_ge_60_count']} / 10</small></div><div class='metric'><span>Rule</span><b>V9+ fixed</b><small>{html.escape(payload['universe']['entry_label'])}｜{html.escape(payload['universe']['exit_label'])}</small></div></div><div class='warn'><strong>部署提醒：</strong>這份報告只測 V9+ 股池隨機股票切分穩定度。若 test pass 次數不足，不能因 full sample 平均報酬高就部署。</div></header><main><h2>10 次隨機 stock split 結果</h2><div class='table'><table><thead><tr><th>Seed</th><th>股票 Train / Val / Test</th><th>交易 Train / Val / Test</th><th>Train 勝率/平均</th><th>Val 勝率/平均</th><th>Test 勝率/平均</th><th>Test 未實現</th><th>Test 達標</th></tr></thead><tbody>{run_rows}</tbody></table></div><h2>V9+ 完整股池</h2><div class='table'><table><thead><tr><th>市場</th><th>代號</th><th>名稱</th><th>交易數</th><th>signal dates</th></tr></thead><tbody>{stock_rows}</tbody></table></div></main></body></html>"""


def render_md(payload: dict[str, Any]) -> str:
    stats = payload["statistics"]["stock_test"]
    lines = [
        f"# {VERSION}",
        "",
        f"Entry: {payload['universe']['entry_label']}",
        f"Exit: {payload['universe']['exit_label']}",
        f"Full: {summary_text(payload['full_summary'])}",
        f"Random stock-test mean: trades {stats['trades']['mean']}, win {stats['win_rate_pct']['mean']:.2f}%, avg {stats['avg_return_pct']['mean']:.2f}%, pass {stats['pass_60win_10avg_count']}/10",
        "",
        "| Seed | Train/Val/Test trades | Test win | Test avg | Test median | Test unresolved | Pass |",
        "|---:|---:|---:|---:|---:|---:|---|",
    ]
    for run in payload["runs"]:
        test = run["summaries"]["stock_test"]
        passed = test["win_rate_pct"] >= 60 and test["avg_return_pct"] >= 10
        lines.append(
            f"| {run['seed']} | {run['trade_counts']['stock_train']} / {run['trade_counts']['stock_validation']} / {run['trade_counts']['stock_test']} | {test['win_rate_pct']:.2f}% | {test['avg_return_pct']:.2f}% | {test['median_return_pct']:.2f}% | {test.get('unresolved', 0)} | {'YES' if passed else 'NO'} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    payload = run()
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    OUT_MD.write_text(render_md(payload), encoding="utf-8")
    print(json.dumps({
        "version": VERSION,
        "universe": {k: v for k, v in payload["universe"].items() if k != "stock_listing"},
        "full_summary": payload["full_summary"],
        "statistics": payload["statistics"],
        "html": str(OUT_HTML),
        "json": str(OUT_JSON),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
