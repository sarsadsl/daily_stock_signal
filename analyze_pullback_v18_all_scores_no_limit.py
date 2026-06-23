#!/usr/bin/env python3
"""Rerun V18+ no-limit while including all original score buckets from the one-year pullback pool."""

from __future__ import annotations

import html
import json
from collections import Counter
from pathlib import Path
from typing import Any

from analyze_pullback_multitimeframe_search import BENCHMARK_CSV, enrich_trades
from analyze_pullback_pb_v15_all_signal_history import attach_prior_only_scores, enrich_all_three_year_signals
from analyze_pullback_pb_v17_two_stage_runner import replay
from analyze_pullback_pb_v18_finite_capital import STRESS_SLIPPAGE_EACH_SIDE_PCT, adjusted_rows
from analyze_pullback_plus_independent_versions import target_summary
from analyze_pullback_plus_random_splits import SEEDS, random_stock_groups, strategy_stats
from analyze_pullback_technical_phenotypes import make_series_map
from run_market_backtest import csv_files

REPORT_DIR = Path("reports")
OUT_JSON = REPORT_DIR / "pullback_v18_all_scores_no_limit.json"
OUT_HTML = REPORT_DIR / "pullback_v18_all_scores_no_limit.html"
OUT_MD = REPORT_DIR / "pullback_v18_all_scores_no_limit.md"
VERSION = "PB-V18-all-scores-no-limit"


def score_value(row: dict[str, Any]) -> int | None:
    try:
        return int(row.get("score"))
    except (TypeError, ValueError):
        return None


def build_all_score_exits() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    historical, _ = enrich_all_three_year_signals()
    one_year, _ = enrich_trades()
    attach_prior_only_scores(one_year, historical)
    source_distribution = dict(sorted(Counter(score_value(row) for row in one_year).items(), reverse=True))
    gross = replay(one_year, make_series_map(csv_files()), BENCHMARK_CSV)
    stress = adjusted_rows(gross, STRESS_SLIPPAGE_EACH_SIDE_PCT)
    metadata = {
        "source_trades": len(one_year),
        "source_stocks": len({f"{row.get('market')}:{row.get('stock_no')}" for row in one_year}),
        "source_signal_date_start": min(row["signal_date"] for row in one_year) if one_year else None,
        "source_signal_date_end": max(row["signal_date"] for row in one_year) if one_year else None,
        "source_score_distribution": source_distribution,
        "replayed_trades": len(stress),
        "replayed_stocks": len({f"{row.get('market')}:{row.get('stock_no')}" for row in stress}),
        "replayed_signal_date_start": min(row["signal_date"] for row in stress) if stress else None,
        "replayed_signal_date_end": max(row["signal_date"] for row in stress) if stress else None,
        "replayed_score_distribution": dict(sorted(Counter(score_value(row) for row in stress).items(), reverse=True)),
    }
    return stress, metadata


def split_runs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    runs = []
    for seed in SEEDS:
        groups, counts = random_stock_groups(rows, seed)
        summaries = {name: target_summary(group_rows) for name, group_rows in groups.items()}
        runs.append({
            "seed": seed,
            "stock_counts": counts,
            "trade_counts": {name: len(group_rows) for name, group_rows in groups.items()},
            "summaries": summaries,
        })
    return runs


def score_breakdown(rows: list[dict[str, Any]]) -> dict[str, Any]:
    output = {}
    for score in sorted({score_value(row) for row in rows if score_value(row) is not None}, reverse=True):
        selected = [row for row in rows if score_value(row) == score]
        output[str(score)] = {
            "trades": len(selected),
            "stocks": len({f"{row.get('market')}:{row.get('stock_no')}" for row in selected}),
            "summary": target_summary(selected),
        }
    return output


def load_reference() -> dict[str, Any]:
    output: dict[str, Any] = {}
    v18_no_limit_path = REPORT_DIR / "pullback_pb_v18_unlimited.json"
    score_pool_path = REPORT_DIR / "pullback_v18_score_pool_tests.json"
    if v18_no_limit_path.exists():
        ref = json.loads(v18_no_limit_path.read_text(encoding="utf-8"))
        output["v18_no_limit_avoid_score4"] = {
            "universe": ref.get("universe"),
            "statistics": ref.get("statistics"),
        }
    if score_pool_path.exists():
        ref = json.loads(score_pool_path.read_text(encoding="utf-8"))
        output["score_pool_tests"] = {
            "universe": ref.get("universe"),
            "ranked_ids": ref.get("ranked_ids", [])[:10],
        }
    return output


def run() -> dict[str, Any]:
    rows, metadata = build_all_score_exits()
    runs = split_runs(rows)
    return {
        "version": VERSION,
        "methodology": {
            "base": "V18+ no-limit rerun with all one-year enriched pullback score buckets included. The avoid_score4/climax filter is intentionally removed.",
            "kept": [
                "one-year enriched pullback signal pool from enrich_trades()",
                "V17 two-stage runner exit",
                "next-open entry with existing 2% discount condition enforced by V17 replay()",
                "V18 fee/tax model and +0.10% adverse slippage each side",
                "TWD 100,000 standard unit per trade",
                "no finite capital, no max positions, no max-new-per-day, no duplicate-stock capacity filter",
                "same 10 random stock-code 60/20/20 split seeds",
            ],
            "changed_from_v18_no_limit": "Removed avoid_score4 / climax-score candidate filter so every original score bucket from the one-year pullback pool can enter if it passes replay/entry requirements.",
            "warning": "This is a broader diagnostic pool, not the frozen finite-capital V18 strategy.",
        },
        "universe": metadata,
        "full": target_summary(rows),
        "score_breakdown": score_breakdown(rows),
        "random_runs": runs,
        "random_statistics": strategy_stats(runs),
        "reference": load_reference(),
        "trades": rows,
    }


def pct(value: Any) -> str:
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return "-"


def compact(summary: dict[str, Any]) -> str:
    return (
        f"{summary['trades']} 筆｜{summary['win_rate_pct']:.2f}%｜"
        f"平均 {summary['avg_return_pct']:.2f}%｜中位 {summary['median_return_pct']:.2f}%｜"
        f"未實現 {summary.get('unresolved', 0)}"
    )


def render_html(payload: dict[str, Any]) -> str:
    ref = payload.get("reference", {}).get("v18_no_limit_avoid_score4", {})
    ref_universe = ref.get("universe", {}) or {}
    ref_stats = ref.get("statistics", {}) or {}
    ref_test = (ref_stats.get("stock_test") or {})
    ref_full = ref_universe.get("stress_full") or {}
    test = payload["random_statistics"]["stock_test"]
    score_rows = "".join(
        f"<tr><th>{html.escape(score)} 星</th>"
        f"<td>{item['trades']}</td><td>{item['stocks']}</td>"
        f"<td>{pct(item['summary']['win_rate_pct'])}</td>"
        f"<td>{pct(item['summary']['avg_return_pct'])}</td>"
        f"<td>{pct(item['summary']['median_return_pct'])}</td>"
        f"<td>{item['summary'].get('unresolved', 0)}</td></tr>"
        for score, item in payload["score_breakdown"].items()
    )
    run_rows = "".join(
        f"<tr><td>{run['seed']}</td>"
        f"<td>{run['stock_counts']['stock_train']} / {run['stock_counts']['stock_validation']} / {run['stock_counts']['stock_test']}</td>"
        f"<td>{run['summaries']['stock_train']['trades']} / {run['summaries']['stock_validation']['trades']} / {run['summaries']['stock_test']['trades']}</td>"
        f"<td>{pct(run['summaries']['stock_test']['win_rate_pct'])}</td>"
        f"<td>{pct(run['summaries']['stock_test']['avg_return_pct'])}</td>"
        f"<td>{pct(run['summaries']['stock_test']['median_return_pct'])}</td>"
        f"<td>{run['summaries']['stock_test'].get('unresolved', 0)}</td></tr>"
        for run in payload["random_runs"]
    )
    return f"""<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{VERSION}</title><style>
:root{{--bg:#f6f7fb;--paper:#fff;--ink:#172033;--muted:#667085;--line:#e4e7ec;--good:#08735d;--bad:#b42318;--blue:#2563eb}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 system-ui,'Microsoft JhengHei',sans-serif}}header,main{{max-width:1400px;margin:auto;padding:28px 20px}}header{{border-bottom:1px solid var(--line)}}h1{{margin:0 0 8px;font-size:30px}}h2{{margin:28px 0 10px;font-size:20px}}p{{color:var(--muted)}}.metrics{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1px;background:var(--line);border:1px solid var(--line);margin-top:22px}}.metric{{background:#fff;padding:16px}}.metric span,.metric small{{display:block;color:var(--muted)}}.metric b{{font-size:22px}}.note{{border-left:4px solid var(--blue);background:#eff6ff;padding:12px 14px;margin:18px 0;border-radius:12px}}.warn{{border-left:4px solid var(--bad);background:#fef3f2;padding:12px 14px;margin:18px 0;border-radius:12px}}.table{{overflow:auto;border:1px solid var(--line);background:#fff}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:right;vertical-align:top}}th:first-child,td:first-child{{text-align:left}}thead th{{background:#f8fafc;color:var(--muted);font-size:12px}}@media(max-width:900px){{.metrics{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}@media(max-width:560px){{header,main{{padding:18px 10px}}.metrics{{grid-template-columns:1fr}}}}
</style></head><body><header><h1>{VERSION}</h1><p>重測 V18+ no-limit，但移除 avoid_score4，讓一年 pullback 母體中所有原始 score 桶都可以進入測試。</p><div class='metrics'><div class='metric'><span>All-score replayed pool</span><b>{payload['universe']['replayed_trades']} 筆</b><small>{payload['universe']['replayed_stocks']} 檔｜{html.escape(str(payload['universe']['replayed_score_distribution']))}</small></div><div class='metric'><span>All-score full</span><b>{payload['full']['win_rate_pct']:.2f}% / {payload['full']['avg_return_pct']:.2f}%</b><small>中位 {payload['full']['median_return_pct']:.2f}%｜未實現 {payload['full'].get('unresolved', 0)}</small></div><div class='metric'><span>Random stock test mean</span><b>{test['win_rate_pct']['mean']:.2f}% / {test['avg_return_pct']['mean']:.2f}%</b><small>平均 test 筆數 {test['trades']['mean']}｜達標 {test['pass_60win_10avg_count']}/10</small></div><div class='metric'><span>Old avoid_score4 no-limit</span><b>{ref_full.get('win_rate_pct', 0):.2f}% / {ref_full.get('avg_return_pct', 0):.2f}%</b><small>test mean {ref_test.get('win_rate_pct', {}).get('mean', 0)}% / {ref_test.get('avg_return_pct', {}).get('mean', 0)}%</small></div></div><div class='warn'><strong>判讀：</strong>這版不是 frozen V18，而是檢查「avoid_score4 是否過度壓縮股池」。它保留 V17 runner、成本壓力與 no-limit 口徑，只把所有原始 score 桶加回來。</div></header><main><h2>Score breakdown after replay</h2><div class='table'><table><thead><tr><th>Score</th><th>筆數</th><th>股票數</th><th>勝率</th><th>平均</th><th>中位</th><th>未實現</th></tr></thead><tbody>{score_rows}</tbody></table></div><h2>10 次 random stock split</h2><div class='table'><table><thead><tr><th>Seed</th><th>股票 Train / Val / Test</th><th>交易 Train / Val / Test</th><th>Test 勝率</th><th>Test 平均</th><th>Test 中位</th><th>Test 未實現</th></tr></thead><tbody>{run_rows}</tbody></table></div></main></body></html>"""


def render_md(payload: dict[str, Any]) -> str:
    test = payload["random_statistics"]["stock_test"]
    lines = [
        f"# {VERSION}",
        "",
        f"Source one-year pool: {payload['universe']['source_trades']} trades / {payload['universe']['source_stocks']} stocks",
        f"Replayed all-score pool: {payload['universe']['replayed_trades']} trades / {payload['universe']['replayed_stocks']} stocks",
        f"Replayed score distribution: {payload['universe']['replayed_score_distribution']}",
        f"Full: {compact(payload['full'])}",
        f"Random stock test mean: trades {test['trades']['mean']}, win {test['win_rate_pct']['mean']:.2f}%, avg {test['avg_return_pct']['mean']:.2f}%, pass {test['pass_60win_10avg_count']}/10",
        "",
        "| Score | Trades | Win | Avg | Median | Unresolved |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for score, item in payload["score_breakdown"].items():
        summary = item["summary"]
        lines.append(f"| {score} | {item['trades']} | {summary['win_rate_pct']:.2f}% | {summary['avg_return_pct']:.2f}% | {summary['median_return_pct']:.2f}% | {summary.get('unresolved', 0)} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    payload = run()
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    OUT_MD.write_text(render_md(payload), encoding="utf-8")
    test = payload["random_statistics"]["stock_test"]
    print(json.dumps({
        "version": VERSION,
        "universe": payload["universe"],
        "full": payload["full"],
        "score_breakdown": payload["score_breakdown"],
        "random_stock_test": test,
        "reference": payload["reference"].get("v18_no_limit_avoid_score4"),
        "html": str(OUT_HTML),
        "json": str(OUT_JSON),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
