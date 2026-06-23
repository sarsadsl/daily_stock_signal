#!/usr/bin/env python3
"""Evaluate V18+ without finite capital, max-holding, daily-entry, or duplicate-stock constraints."""

from __future__ import annotations

import html
import json
import statistics
from pathlib import Path
from typing import Any

from analyze_pullback_multitimeframe_search import BENCHMARK_CSV
from analyze_pullback_plus_independent_versions import target_summary
from analyze_pullback_pb_v15_all_signal_history import attach_prior_only_scores, enrich_all_three_year_signals
from analyze_pullback_pb_v17_two_stage_runner import replay
from analyze_pullback_pb_v18_finite_capital import STRESS_SLIPPAGE_EACH_SIDE_PCT, adjusted_rows
from analyze_pullback_plus_random_splits import SEEDS, distribution, random_stock_groups, strategy_stats
from analyze_pullback_rolling_climax import variant_rows
from analyze_pullback_technical_phenotypes import make_series_map
from run_market_backtest import csv_files

REPORT_DIR = Path("reports")
OUT_JSON = REPORT_DIR / "pullback_pb_v18_unlimited.json"
OUT_HTML = REPORT_DIR / "pullback_pb_v18_unlimited.html"
OUT_MD = REPORT_DIR / "pullback_pb_v18_unlimited.md"
VERSION = "PB-V18-plus-unlimited"
POSITION_SIZE = 100_000


def build_v18_candidate_exits() -> list[dict[str, Any]]:
    historical, _ = enrich_all_three_year_signals()
    from analyze_pullback_multitimeframe_search import enrich_trades

    one_year, _ = enrich_trades()
    attach_prior_only_scores(one_year, historical)
    candidates = variant_rows(one_year, "avoid_score4")
    return replay(candidates, make_series_map(csv_files()), BENCHMARK_CSV)


def evaluate_no_limit(seed: int, rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups, counts = random_stock_groups(rows, seed)
    stress_groups = {name: adjusted_rows(group_rows, STRESS_SLIPPAGE_EACH_SIDE_PCT) for name, group_rows in groups.items()}
    gross_summaries = {name: target_summary(group_rows) for name, group_rows in groups.items()}
    stress_summaries = {name: target_summary(group_rows) for name, group_rows in stress_groups.items()}
    return {
        "strategy": "V18+ unlimited",
        "seed": seed,
        "stock_counts": counts,
        "trade_counts": {name: len(group_rows) for name, group_rows in groups.items()},
        "chosen_rule": "fixed V18 candidate source; no finite-capital selection",
        "chosen_exit": "V17 runner with V18 stress cost",
        "gross_summaries": gross_summaries,
        "summaries": stress_summaries,
    }


def run() -> dict[str, Any]:
    exits = build_v18_candidate_exits()
    stress_all = adjusted_rows(exits, STRESS_SLIPPAGE_EACH_SIDE_PCT)
    runs = [evaluate_no_limit(seed, exits) for seed in SEEDS]
    original_random_path = REPORT_DIR / "pullback_plus_random_splits.json"
    original_v18_stats: dict[str, Any] | None = None
    original_v18_runs: list[dict[str, Any]] | None = None
    if original_random_path.exists():
        original = json.loads(original_random_path.read_text(encoding="utf-8"))
        original_v18_stats = original.get("statistics", {}).get("V18+")
        original_v18_runs = original.get("runs_by_strategy", {}).get("V18+")
    return {
        "version": VERSION,
        "methodology": {
            "base": "Same V18 source: one-year enriched pullback signals, prior-only rolling score, avoid_score4 filter, then V17 gap-aware runner exit.",
            "removed_constraints": [
                "TWD 500,000 finite capital cap",
                "max 5 active positions",
                "max 2 new entries per signal date",
                "no duplicate active stock",
                "daily ranking selection capacity limit",
            ],
            "kept": [
                "each accepted signal is still a TWD 100,000 standard simulation unit",
                "same V17 runner exit",
                "same fee/tax model and +0.10% adverse slippage stress used by V18+",
                "same 10 random stock-code 60/20/20 split seeds as pullback_plus_random_splits",
            ],
            "interpretation": "This tests whether V18+'s apparent edge survives after removing capacity/portfolio selection. It is not a finite-capital executable portfolio.",
        },
        "universe": {
            "candidate_trades": len(exits),
            "unique_stocks": len({f"{row.get('market')}:{row.get('stock_no')}" for row in exits}),
            "gross_full": target_summary(exits),
            "stress_full": target_summary(stress_all),
        },
        "runs": runs,
        "statistics": strategy_stats([{"summaries": run["summaries"]} for run in runs]),
        "gross_statistics": strategy_stats([{"summaries": run["gross_summaries"]} for run in runs]),
        "original_v18_finite_reference": {
            "statistics": original_v18_stats,
            "runs": original_v18_runs,
        },
    }


def fmt_pct(value: Any) -> str:
    return f"{float(value):.2f}%"


def fmt_num(value: Any) -> str:
    return f"{float(value):,.0f}"


def render_html(payload: dict[str, Any]) -> str:
    stats = payload["statistics"]
    finite_stats = payload["original_v18_finite_reference"].get("statistics") or {}
    finite_test = finite_stats.get("stock_test", {})
    finite_trade_dist = finite_test.get("trades", {})
    finite_win_dist = finite_test.get("win_rate_pct", {})
    finite_avg_dist = finite_test.get("avg_return_pct", {})
    rows = "".join(
        f"<tr>"
        f"<td>{run['seed']}</td>"
        f"<td>{run['stock_counts']['stock_train']} / {run['stock_counts']['stock_validation']} / {run['stock_counts']['stock_test']}</td>"
        f"<td>{run['summaries']['stock_train']['trades']} / {run['summaries']['stock_validation']['trades']} / {run['summaries']['stock_test']['trades']}</td>"
        f"<td>{fmt_pct(run['summaries']['stock_test']['win_rate_pct'])}</td>"
        f"<td>{fmt_pct(run['summaries']['stock_test']['avg_return_pct'])}</td>"
        f"<td>{fmt_pct(run['summaries']['stock_test']['median_return_pct'])}</td>"
        f"<td>{run['summaries']['stock_test']['unresolved']}</td>"
        f"</tr>"
        for run in payload["runs"]
    )
    test = stats["stock_test"]
    full = stats["full"]
    pass_count = test["pass_60win_10avg_count"]
    status_class = "pass" if pass_count >= 6 else "fail"
    status_text = "通過次數仍達 6/10" if pass_count >= 6 else "移除限制後未維持 V18+ 的 6/10 達標"
    finite_summary_html = ""
    if finite_stats:
        finite_summary_html = f"""
        <div class='metric'><span>原 V18+ finite test</span><strong>{finite_test.get('pass_60win_10avg_count', 0)}/10</strong><small>平均交易 {finite_trade_dist.get('mean', 0)}｜勝率均值 {finite_win_dist.get('mean', 0)}%｜平均報酬均值 {finite_avg_dist.get('mean', 0)}%</small></div>
        """
    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{VERSION}</title><style>
:root{{--bg:#f6f7fb;--paper:#fff;--ink:#172033;--muted:#667085;--line:#e4e7ec;--good:#08735d;--bad:#b42318;--blue:#2563eb}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 system-ui,"Microsoft JhengHei",sans-serif}}header,main{{max-width:1320px;margin:auto;padding:28px 20px}}header{{border-bottom:1px solid var(--line)}}h1{{margin:0 0 8px;font-size:30px}}h2{{margin:28px 0 10px;font-size:20px}}p{{color:var(--muted)}}.status{{display:inline-block;margin-top:10px;padding:7px 11px;border:1px solid currentColor;font-weight:800}}.pass,.pos{{color:var(--good)}}.fail,.neg{{color:var(--bad)}}.metrics{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1px;background:var(--line);border:1px solid var(--line);margin-top:22px}}.metric{{background:var(--paper);padding:15px}}.metric strong{{display:block;font-size:22px}}.metric span,.metric small{{color:var(--muted)}}.note{{border-left:4px solid var(--blue);background:#eff6ff;padding:12px 14px;margin:18px 0;border-radius:12px}}.warn{{border-left:4px solid var(--bad);background:#fef3f2;padding:12px 14px;margin:18px 0;border-radius:12px}}.table{{overflow:auto;border:1px solid var(--line);background:#fff}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:right}}th:first-child,td:first-child{{text-align:left}}thead th{{background:#f8fafc;color:var(--muted);font-size:12px}}@media(max-width:900px){{.metrics{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}@media(max-width:560px){{header,main{{padding:18px 10px}}.metrics{{grid-template-columns:1fr}}}}
</style></head><body><header><h1>{VERSION}</h1><p>移除 V18+ 的有限本金、最大持倉、每日最多進場、同股重複持有等 portfolio 約束後，保留 V18 候選來源、V17 runner exit、費稅與壓力滑價，重新做 10 次 random stock split。</p><span class="status {status_class}">{status_text}</span><div class="metrics"><div class="metric"><span>候選交易 / 股票</span><strong>{payload['universe']['candidate_trades']} / {payload['universe']['unique_stocks']}</strong><small>全部 V18 候選，不再做 portfolio 篩選</small></div><div class="metric"><span>No-limit stock test</span><strong>{pass_count}/10</strong><small>達 60% 勝率與 10% 平均</small></div><div class="metric"><span>No-limit test 平均</span><strong>{test['win_rate_pct']['mean']:.2f}% / {test['avg_return_pct']['mean']:.2f}%</strong><small>交易數均值 {test['trades']['mean']}</small></div>{finite_summary_html}<div class="metric"><span>No-limit full</span><strong>{full['win_rate_pct']['mean']:.2f}% / {full['avg_return_pct']['mean']:.2f}%</strong><small>壓力成本後全樣本</small></div></div></header><main><div class="warn"><strong>解讀：</strong>這不是可執行有限本金 portfolio，而是把所有 V18 候選都當成每筆 100,000 的標準單位。若 no-limit 變差，代表 V18+ 的優勢主要來自資金/持倉/每日進場限制與 ranking selection，而不是候選池本身全部都有同等品質。</div><h2>10 次 random stock split 明細</h2><div class="table"><table><thead><tr><th>Seed</th><th>股票 Train / Val / Test</th><th>交易 Train / Val / Test</th><th>Test 勝率</th><th>Test 平均</th><th>Test 中位</th><th>Test 未實現</th></tr></thead><tbody>{rows}</tbody></table></div></main></body></html>"""


def render_md(payload: dict[str, Any]) -> str:
    stats = payload["statistics"]
    test = stats["stock_test"]
    lines = [
        f"# {VERSION}",
        "",
        "V18+ with finite-capital/position/daily-entry/duplicate-stock constraints removed.",
        "",
        f"Candidate trades: {payload['universe']['candidate_trades']}",
        f"Unique stocks: {payload['universe']['unique_stocks']}",
        f"Stock-test pass count: {test['pass_60win_10avg_count']}/10",
        f"Stock-test mean trades: {test['trades']['mean']}",
        f"Stock-test mean win/avg: {test['win_rate_pct']['mean']:.2f}% / {test['avg_return_pct']['mean']:.2f}%",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    payload = run()
    REPORT_DIR.mkdir(exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    OUT_MD.write_text(render_md(payload), encoding="utf-8")
    print(json.dumps({
        "version": payload["version"],
        "universe": payload["universe"],
        "statistics": payload["statistics"],
        "original_v18_finite_reference": payload["original_v18_finite_reference"].get("statistics"),
        "html": str(OUT_HTML),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
