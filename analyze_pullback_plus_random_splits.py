#!/usr/bin/env python3
"""Run pullback plus strategies over 10 randomized stock 60/20/20 splits."""

from __future__ import annotations

import html
import json
import random
import statistics
from pathlib import Path
from typing import Any

from analyze_pullback_multitimeframe_search import enrich_trades, rule_label, rules, select
from analyze_pullback_plus_independent_versions import (
    INDEPENDENT_EXIT_LABELS,
    V9_ENTRY_RULE,
    compute_independent_exits,
    run_v14_plus,
    run_v18_plus,
    selection_score,
    target_summary,
)


REPORT_DIR = Path("reports")
OUT_JSON = REPORT_DIR / "pullback_plus_random_splits.json"
OUT_HTML = REPORT_DIR / "pullback_plus_random_splits.html"
SEEDS = list(range(2026062301, 2026062311))
SPLIT_RATIO = (0.60, 0.20, 0.20)


def stock_key(row: dict[str, Any]) -> str:
    return f"{row.get('market')}:{row.get('stock_no')}"


def random_stock_groups(rows: list[dict[str, Any]], seed: int) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
    stocks = sorted({stock_key(row) for row in rows})
    rng = random.Random(seed)
    rng.shuffle(stocks)
    train_end = round(len(stocks) * SPLIT_RATIO[0])
    validation_end = round(len(stocks) * (SPLIT_RATIO[0] + SPLIT_RATIO[1]))
    split_sets = {
        "stock_train": set(stocks[:train_end]),
        "stock_validation": set(stocks[train_end:validation_end]),
        "stock_test": set(stocks[validation_end:]),
    }
    return (
        {name: [row for row in rows if stock_key(row) in keys] for name, keys in split_sets.items()} | {"full": rows},
        {name: len(keys) for name, keys in split_sets.items()} | {"full": len(stocks)},
    )


def choose_v8_for_seed(independent_exits: dict[str, list[dict[str, Any]]], seed: int) -> dict[str, Any]:
    runner_rows = independent_exits["v17_runner"]
    groups, counts = random_stock_groups(runner_rows, seed)
    candidates = []
    for rule in rules():
        selected = {name: select(group_rows, rule) for name, group_rows in groups.items()}
        summaries = {name: target_summary(group_rows) for name, group_rows in selected.items()}
        if summaries["stock_train"]["trades"] < 20 or summaries["stock_validation"]["trades"] < 8:
            continue
        candidates.append({
            "score": selection_score(summaries["stock_train"], summaries["stock_validation"]),
            "rule": rule,
            "label": rule_label(rule),
            "summaries": summaries,
        })
    chosen = max(candidates, key=lambda item: item["score"])
    return {
        "strategy": "V8+",
        "seed": seed,
        "stock_counts": counts,
        "chosen_rule": chosen["label"],
        "chosen_exit": INDEPENDENT_EXIT_LABELS["v17_runner"],
        "candidate_count": len(candidates),
        "summaries": chosen["summaries"],
    }


def choose_v9_for_seed(enriched: list[dict[str, Any]], independent_exits: dict[str, list[dict[str, Any]]], seed: int) -> dict[str, Any]:
    selected_features = select(enriched, V9_ENTRY_RULE)
    selected_keys = {(row["signal_date"], row["market"], row["stock_no"]) for row in selected_features}
    candidates = []
    for style, rows in independent_exits.items():
        style_rows = [row for row in rows if (row["signal_date"], row["market"], row["stock_no"]) in selected_keys]
        groups, counts = random_stock_groups(style_rows, seed)
        summaries = {name: target_summary(group_rows) for name, group_rows in groups.items()}
        candidates.append({
            "score": selection_score(summaries["stock_train"], summaries["stock_validation"]),
            "exit_style": style,
            "exit_label": INDEPENDENT_EXIT_LABELS[style],
            "stock_counts": counts,
            "summaries": summaries,
        })
    chosen = max(candidates, key=lambda item: item["score"])
    return {
        "strategy": "V9+",
        "seed": seed,
        "stock_counts": chosen["stock_counts"],
        "chosen_rule": rule_label(V9_ENTRY_RULE),
        "chosen_exit": chosen["exit_label"],
        "chosen_exit_style": chosen["exit_style"],
        "summaries": chosen["summaries"],
    }


def choose_v10_for_seed(independent_exits: dict[str, list[dict[str, Any]]], seed: int) -> dict[str, Any]:
    candidates = []
    for style, rows in independent_exits.items():
        groups, counts = random_stock_groups(rows, seed)
        for rule in rules():
            selected = {name: select(group_rows, rule) for name, group_rows in groups.items()}
            summaries = {name: target_summary(group_rows) for name, group_rows in selected.items()}
            if summaries["stock_train"]["trades"] < 20 or summaries["stock_validation"]["trades"] < 8:
                continue
            if min(summaries["stock_train"]["win_rate_pct"], summaries["stock_validation"]["win_rate_pct"]) < 55:
                continue
            candidates.append({
                "score": selection_score(summaries["stock_train"], summaries["stock_validation"]),
                "rule": rule,
                "label": rule_label(rule),
                "exit_style": style,
                "exit_label": INDEPENDENT_EXIT_LABELS[style],
                "stock_counts": counts,
                "summaries": summaries,
            })
    chosen = max(candidates, key=lambda item: item["score"])
    return {
        "strategy": "V10+",
        "seed": seed,
        "stock_counts": chosen["stock_counts"],
        "chosen_rule": chosen["label"],
        "chosen_exit": chosen["exit_label"],
        "chosen_exit_style": chosen["exit_style"],
        "candidate_count": len(candidates),
        "summaries": chosen["summaries"],
    }


def evaluate_fixed_strategy_rows(strategy: str, rows: list[dict[str, Any]], seed: int) -> dict[str, Any]:
    groups, counts = random_stock_groups(rows, seed)
    summaries = {name: target_summary(group_rows) for name, group_rows in groups.items()}
    return {
        "strategy": strategy,
        "seed": seed,
        "stock_counts": counts,
        "chosen_rule": "fixed",
        "chosen_exit": "fixed",
        "summaries": summaries,
    }


def flatten_metric(runs: list[dict[str, Any]], split: str, metric: str) -> list[float]:
    return [float(run["summaries"][split][metric]) for run in runs]


def distribution(values: list[float]) -> dict[str, float]:
    if not values:
        return {"min": 0.0, "p25": 0.0, "mean": 0.0, "median": 0.0, "p75": 0.0, "max": 0.0, "stdev": 0.0}
    sorted_values = sorted(values)
    def q(index: float) -> float:
        if len(sorted_values) == 1:
            return sorted_values[0]
        pos = index * (len(sorted_values) - 1)
        low = int(pos)
        high = min(low + 1, len(sorted_values) - 1)
        frac = pos - low
        return sorted_values[low] * (1 - frac) + sorted_values[high] * frac
    return {
        "min": round(min(values), 2),
        "p25": round(q(0.25), 2),
        "mean": round(statistics.mean(values), 2),
        "median": round(statistics.median(values), 2),
        "p75": round(q(0.75), 2),
        "max": round(max(values), 2),
        "stdev": round(statistics.pstdev(values), 2),
    }


def strategy_stats(runs: list[dict[str, Any]]) -> dict[str, Any]:
    test_avg = flatten_metric(runs, "stock_test", "avg_return_pct")
    test_win = flatten_metric(runs, "stock_test", "win_rate_pct")
    test_trades = flatten_metric(runs, "stock_test", "trades")
    full_avg = flatten_metric(runs, "full", "avg_return_pct")
    full_win = flatten_metric(runs, "full", "win_rate_pct")
    pass_60_10 = [run for run in runs if run["summaries"]["stock_test"]["win_rate_pct"] >= 60 and run["summaries"]["stock_test"]["avg_return_pct"] >= 10]
    avg_10_only = [run for run in runs if run["summaries"]["stock_test"]["avg_return_pct"] >= 10]
    win_60_only = [run for run in runs if run["summaries"]["stock_test"]["win_rate_pct"] >= 60]
    return {
        "runs": len(runs),
        "stock_test": {
            "trades": distribution(test_trades),
            "win_rate_pct": distribution(test_win),
            "avg_return_pct": distribution(test_avg),
            "pass_60win_10avg_count": len(pass_60_10),
            "avg_ge_10_count": len(avg_10_only),
            "win_ge_60_count": len(win_60_only),
        },
        "full": {
            "win_rate_pct": distribution(full_win),
            "avg_return_pct": distribution(full_avg),
        },
    }


def run() -> dict[str, Any]:
    enriched, _ = enrich_trades()
    independent_exits = compute_independent_exits(enriched)
    v14_payload = run_v14_plus()
    v14_rows = []
    # Reconstruct V14 selected rows from the full summary source by reusing its fixed report is not enough;
    # run_v14_plus returns summaries only, so import its wide rows through the report helper again.
    from analyze_pullback_pb_v13_frozen_3y import build_trade_sets
    from analyze_pullback_pb_v14_market_gate import add_market_gate as add_v14_market_gate
    _, wide_rows = build_trade_sets()
    add_v14_market_gate(wide_rows)
    v14_rows = [row for row in wide_rows if row.get("primary_uptrend")]

    from analyze_pullback_pb_v15_all_signal_history import attach_prior_only_scores, enrich_all_three_year_signals
    from analyze_pullback_pb_v17_two_stage_runner import replay
    from analyze_pullback_pb_v18_finite_capital import STRESS_SLIPPAGE_EACH_SIDE_PCT, adjusted_rows, select_finite_portfolio
    from analyze_pullback_rolling_climax import variant_rows
    from analyze_pullback_technical_phenotypes import make_series_map
    from run_market_backtest import csv_files
    from analyze_pullback_multitimeframe_search import BENCHMARK_CSV
    historical, _ = enrich_all_three_year_signals()
    v18_source = [dict(row) for row in enriched]
    attach_prior_only_scores(v18_source, historical)
    v18_candidates = variant_rows(v18_source, "avoid_score4")
    v18_exits = replay(v18_candidates, make_series_map(csv_files()), BENCHMARK_CSV)

    runs_by_strategy = {"V8+": [], "V9+": [], "V10+": [], "V14+": [], "V18+": []}
    for seed in SEEDS:
        runs_by_strategy["V8+"].append(choose_v8_for_seed(independent_exits, seed))
        runs_by_strategy["V9+"].append(choose_v9_for_seed(enriched, independent_exits, seed))
        runs_by_strategy["V10+"].append(choose_v10_for_seed(independent_exits, seed))
        runs_by_strategy["V14+"].append(evaluate_fixed_strategy_rows("V14+", v14_rows, seed))
        groups, counts = random_stock_groups(v18_exits, seed)
        portfolios = {name: select_finite_portfolio(group_rows) for name, group_rows in groups.items()}
        stress_summaries = {name: target_summary(adjusted_rows(rows, STRESS_SLIPPAGE_EACH_SIDE_PCT)) for name, rows in portfolios.items()}
        runs_by_strategy["V18+"].append({
            "strategy": "V18+",
            "seed": seed,
            "stock_counts": counts,
            "chosen_rule": "fixed V18 ranking/finite positions",
            "chosen_exit": "V17 runner with V18 stress cost",
            "portfolio_counts": {name: len(rows) for name, rows in portfolios.items()},
            "summaries": stress_summaries,
        })

    return {
        "version": "PB-plus-random-stock-splits-10x",
        "methodology": {
            "splits": "10 random stock-code 60/20/20 splits. Same stock cannot appear in more than one split inside a run.",
            "seeds": SEEDS,
            "selection": "V8+/V9+/V10+ select rules using each run's train+validation only. V14+/V18+ are fixed and only re-evaluated by split.",
            "position_size": 100000,
            "note": "This is validation resampling, not strategy retuning.",
        },
        "unused_v14_deterministic_reference": v14_payload["summaries"],
        "runs_by_strategy": runs_by_strategy,
        "statistics": {strategy: strategy_stats(runs) for strategy, runs in runs_by_strategy.items()},
    }


def fmt_dist(dist: dict[str, float], suffix: str = "%") -> str:
    return (
        f"平均 {dist['mean']:.2f}{suffix} / 中位 {dist['median']:.2f}{suffix} / "
        f"P25-P75 {dist['p25']:.2f}~{dist['p75']:.2f}{suffix} / 範圍 {dist['min']:.2f}~{dist['max']:.2f}{suffix}"
    )


def render_html(payload: dict[str, Any]) -> str:
    stat_rows = []
    for strategy, stats in payload["statistics"].items():
        test = stats["stock_test"]
        full = stats["full"]
        stat_rows.append(
            f"<tr><th>{html.escape(strategy)}</th>"
            f"<td>{html.escape(fmt_dist(test['trades'], ' 份'))}</td>"
            f"<td>{html.escape(fmt_dist(test['win_rate_pct']))}</td>"
            f"<td>{html.escape(fmt_dist(test['avg_return_pct']))}</td>"
            f"<td>{test['pass_60win_10avg_count']} / {stats['runs']}</td>"
            f"<td>{test['avg_ge_10_count']} / {stats['runs']}</td>"
            f"<td>{html.escape(fmt_dist(full['win_rate_pct']))}<br>{html.escape(fmt_dist(full['avg_return_pct']))}</td></tr>"
        )
    detail_rows = []
    for strategy, runs in payload["runs_by_strategy"].items():
        for run in runs:
            test = run["summaries"]["stock_test"]
            train = run["summaries"]["stock_train"]
            validation = run["summaries"]["stock_validation"]
            full = run["summaries"]["full"]
            detail_rows.append(
                f"<tr><th>{html.escape(strategy)}</th><td>{run['seed']}</td>"
                f"<td>{html.escape(run.get('chosen_exit', ''))}</td>"
                f"<td>{train['trades']} / {train['win_rate_pct']:.2f}% / {train['avg_return_pct']:.2f}%</td>"
                f"<td>{validation['trades']} / {validation['win_rate_pct']:.2f}% / {validation['avg_return_pct']:.2f}%</td>"
                f"<td>{test['trades']} / {test['win_rate_pct']:.2f}% / {test['avg_return_pct']:.2f}%</td>"
                f"<td>{full['trades']} / {full['win_rate_pct']:.2f}% / {full['avg_return_pct']:.2f}%</td></tr>"
            )
    return f"""<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Pullback Plus 10次隨機股票切分</title><style>
:root{{--bg:#f7f7f2;--paper:#fff;--ink:#17211d;--muted:#65716b;--line:#dfe5df;--accent:#1f6a73;--warn:#9a5b13}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 system-ui,'Microsoft JhengHei',sans-serif}}header,main{{max-width:1500px;margin:auto;padding:24px 16px}}header{{border-bottom:1px solid var(--line)}}h1{{margin:0 0 8px;font-size:28px}}h2{{font-size:19px;margin:28px 0 10px}}p{{margin:6px 0;color:var(--muted)}}.note{{margin-top:16px;background:#ecf3f2;border-left:4px solid var(--accent);padding:12px 14px}}.warn{{margin-top:16px;background:#fff7ed;border-left:4px solid var(--warn);padding:12px 14px;color:#7c2d12}}.table{{overflow:auto;border:1px solid var(--line);background:var(--paper)}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}thead th{{background:#eef1ee;color:var(--muted);font-size:12px}}code{{background:#eef1ee;padding:1px 4px;border-radius:4px}}@media(max-width:900px){{header,main{{padding:18px 10px}}}}
</style></head><body><header><h1>Pullback Plus 10次隨機股票切分</h1><p>每次先把股票代號隨機打散，再切成 60% 訓練、20% 驗證、20% 測試；同一檔股票在單次切分中不會跨組。</p><div class='note'><strong>方法：</strong>V8+/V9+/V10+ 每個 seed 都只用該次訓練+驗證選規則，再看測試組。V14+/V18+ 是固定策略，只做 10 次不同股票切分評估。這是穩定性統計，不是新調參。</div></header><main><h2>10次測試集統計</h2><div class='table'><table><thead><tr><th>策略</th><th>測試交易數</th><th>測試勝率</th><th>測試平均報酬</th><th>測試達 60% / 10%</th><th>測試平均 >= 10%</th><th>全期分布</th></tr></thead><tbody>{''.join(stat_rows)}</tbody></table></div><div class='warn'><strong>判讀：</strong>如果一個策略只在全期漂亮，但 10 次隨機股票測試中很少同時達到 60% 勝率與 10% 平均，代表它仍偏向樣本內強、跨股票穩定性不足。</div><h2>每次切分明細</h2><div class='table'><table><thead><tr><th>策略</th><th>Seed</th><th>出場/模式</th><th>訓練</th><th>驗證</th><th>測試</th><th>全體</th></tr></thead><tbody>{''.join(detail_rows)}</tbody></table></div><p>輸出檔：<code>{OUT_JSON}</code>、<code>{OUT_HTML}</code></p></main></body></html>"""


def main() -> None:
    payload = run()
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    concise = {strategy: stats["stock_test"] for strategy, stats in payload["statistics"].items()}
    print(json.dumps({"html": str(OUT_HTML), "json": str(OUT_JSON), "stock_test": concise}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
