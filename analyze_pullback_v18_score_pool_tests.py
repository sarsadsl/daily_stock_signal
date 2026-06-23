#!/usr/bin/env python3
"""Test V18+ no-limit candidate pools by original signal score buckets."""

from __future__ import annotations

import html
import itertools
import json
from collections import Counter
from pathlib import Path
from typing import Any

from analyze_pullback_plus_random_splits import SEEDS, random_stock_groups, strategy_stats
from analyze_pullback_plus_independent_versions import target_summary
from analyze_pullback_pb_v18_finite_capital import STRESS_SLIPPAGE_EACH_SIDE_PCT, adjusted_rows
from analyze_pullback_v18_unlimited import build_v18_candidate_exits

REPORT_DIR = Path("reports")
OUT_JSON = REPORT_DIR / "pullback_v18_score_pool_tests.json"
OUT_HTML = REPORT_DIR / "pullback_v18_score_pool_tests.html"
OUT_MD = REPORT_DIR / "pullback_v18_score_pool_tests.md"
VERSION = "PB-V18-score-pool-tests"
SCORE_ORDER = [5, 4, 3, 2, 1]


def score_value(row: dict[str, Any]) -> int | None:
    value = row.get("score")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def label_for(scores: tuple[int, ...]) -> str:
    if not scores:
        return "無"
    if set(scores) == {5, 4, 3, 2, 1}:
        return "All scores"
    return "+".join(f"{score}星" for score in scores)


def key_for(scores: tuple[int, ...]) -> str:
    if set(scores) == {5, 4, 3, 2, 1}:
        return "all"
    return "score_" + "_".join(str(score) for score in scores)


def predefined_score_sets() -> list[tuple[int, ...]]:
    # Include all meaningful combinations while keeping the user-facing order interpretable.
    sets: list[tuple[int, ...]] = [
        (5, 4, 3, 2, 1),
        (5,),
        (4,),
        (3,),
        (2,),
        (1,),
        (5, 4),
        (4, 3),
        (3, 2),
        (2, 1),
        (5, 4, 3),
        (4, 3, 2),
        (3, 2, 1),
        (5, 4, 3, 2),
        (4, 3, 2, 1),
        (5, 3),
        (5, 2),
        (4, 2),
        (5, 4, 2),
        (5, 3, 2),
    ]
    # Add remaining non-empty score combinations as an exhaustive safety net.
    for length in range(1, len(SCORE_ORDER) + 1):
        for combo in itertools.combinations(SCORE_ORDER, length):
            if combo not in sets:
                sets.append(combo)
    return sets


def evaluate_score_set(rows: list[dict[str, Any]], scores: tuple[int, ...]) -> dict[str, Any]:
    score_set = set(scores)
    selected = [row for row in rows if score_value(row) in score_set]
    runs = []
    for seed in SEEDS:
        groups, counts = random_stock_groups(selected, seed) if selected else (
            {"stock_train": [], "stock_validation": [], "stock_test": [], "full": []},
            {"stock_train": 0, "stock_validation": 0, "stock_test": 0, "full": 0},
        )
        summaries = {name: target_summary(group_rows) for name, group_rows in groups.items()}
        runs.append({
            "seed": seed,
            "stock_counts": counts,
            "trade_counts": {name: len(group_rows) for name, group_rows in groups.items()},
            "summaries": summaries,
        })
    return {
        "id": key_for(scores),
        "label": label_for(scores),
        "scores": list(scores),
        "trade_count": len(selected),
        "stock_count": len({f"{row.get('market')}:{row.get('stock_no')}" for row in selected}),
        "score_distribution": dict(sorted(Counter(score_value(row) for row in selected).items(), reverse=True)),
        "full": target_summary(selected),
        "random_runs": runs,
        "random_statistics": strategy_stats(runs),
        "trades": selected,
    }


def rank_variants(variants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def rank_key(item: dict[str, Any]) -> tuple[Any, ...]:
        stats = item["random_statistics"]["stock_test"]
        return (
            stats["pass_60win_10avg_count"],
            stats["avg_return_pct"]["mean"],
            stats["win_rate_pct"]["mean"],
            item["full"]["avg_return_pct"],
            item["trade_count"],
        )
    return sorted(variants, key=rank_key, reverse=True)


def run() -> dict[str, Any]:
    gross_rows = build_v18_candidate_exits()
    rows = adjusted_rows(gross_rows, STRESS_SLIPPAGE_EACH_SIDE_PCT)
    variants = [evaluate_score_set(rows, scores) for scores in predefined_score_sets()]
    ranked = rank_variants(variants)
    return {
        "version": VERSION,
        "methodology": {
            "base": "Same as V18+ no-limit: V18 source candidates, avoid_score4 prior-only filter, V17 runner exit, V18 fee/tax assumptions, and +0.10% adverse slippage each side.",
            "changed_only": "Entry pool is filtered by original signal score bucket/combinations. No finite capital, no max positions, no max-new-per-day, and no duplicate-stock capacity filter are applied.",
            "position_size": 100000,
            "splits": "Same 10 random stock-code 60/20/20 seeds used by the plus random split report. Same stock cannot appear in more than one split inside a run.",
            "warning": "This challenges the original score calculation. Results with tiny test samples should not be treated as robust even if averages look high.",
        },
        "universe": {
            "candidate_trades": len(rows),
            "unique_stocks": len({f"{row.get('market')}:{row.get('stock_no')}" for row in rows}),
            "score_distribution": dict(sorted(Counter(score_value(row) for row in rows).items(), reverse=True)),
            "baseline_full": target_summary(rows),
        },
        "variants": variants,
        "ranked_ids": [item["id"] for item in ranked],
    }


def fmt_pct(value: Any) -> str:
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return "-"


def render_html(payload: dict[str, Any]) -> str:
    id_to_variant = {item["id"]: item for item in payload["variants"]}
    ranked = [id_to_variant[item_id] for item_id in payload["ranked_ids"]]
    rows_html = "".join(
        f"<tr>"
        f"<td class='left'><code>{html.escape(item['label'])}</code></td>"
        f"<td>{item['trade_count']}</td>"
        f"<td>{item['stock_count']}</td>"
        f"<td>{fmt_pct(item['full']['win_rate_pct'])}</td>"
        f"<td>{fmt_pct(item['full']['avg_return_pct'])}</td>"
        f"<td>{fmt_pct(item['full']['median_return_pct'])}</td>"
        f"<td>{item['full'].get('unresolved', 0)}</td>"
        f"<td>{item['random_statistics']['stock_test']['trades']['mean']:.1f}</td>"
        f"<td>{fmt_pct(item['random_statistics']['stock_test']['win_rate_pct']['mean'])}</td>"
        f"<td>{fmt_pct(item['random_statistics']['stock_test']['avg_return_pct']['mean'])}</td>"
        f"<td>{item['random_statistics']['stock_test']['pass_60win_10avg_count']} / 10</td>"
        f"</tr>"
        for item in ranked
    )
    top = ranked[0]
    baseline = id_to_variant["all"]
    return f"""<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{VERSION}</title><style>
:root{{--bg:#f6f7fb;--paper:#fff;--ink:#172033;--muted:#667085;--line:#e4e7ec;--good:#08735d;--bad:#b42318;--blue:#2563eb}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 system-ui,'Microsoft JhengHei',sans-serif}}header,main{{max-width:1400px;margin:auto;padding:28px 20px}}header{{border-bottom:1px solid var(--line)}}h1{{margin:0 0 8px;font-size:30px}}h2{{margin:28px 0 10px;font-size:20px}}p{{color:var(--muted)}}.metrics{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1px;background:var(--line);border:1px solid var(--line);margin-top:22px}}.metric{{background:#fff;padding:16px}}.metric span,.metric small{{display:block;color:var(--muted)}}.metric b{{font-size:22px}}.note{{border-left:4px solid var(--blue);background:#eff6ff;padding:12px 14px;margin:18px 0;border-radius:12px}}.warn{{border-left:4px solid var(--bad);background:#fef3f2;padding:12px 14px;margin:18px 0;border-radius:12px}}.table{{overflow:auto;border:1px solid var(--line);background:#fff}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:right;vertical-align:top}}th:first-child,td:first-child{{text-align:left}}thead th{{background:#f8fafc;color:var(--muted);font-size:12px}}@media(max-width:900px){{.metrics{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}@media(max-width:560px){{header,main{{padding:18px 10px}}.metrics{{grid-template-columns:1fr}}}}
</style></head><body><header><h1>{VERSION}</h1><p>把 V18+ no-limit 候選池依原始 signal score 切成不同股池，只改進場股池，其餘條件完全相同。</p><div class='metrics'><div class='metric'><span>V18+ no-limit baseline</span><b>{baseline['trade_count']} 筆</b><small>{baseline['stock_count']} 檔｜Full {baseline['full']['win_rate_pct']:.2f}% / {baseline['full']['avg_return_pct']:.2f}%</small></div><div class='metric'><span>Score distribution</span><b>{html.escape(str(payload['universe']['score_distribution']))}</b><small>這批沒有 1 星</small></div><div class='metric'><span>目前 rank 第一</span><b>{html.escape(top['label'])}</b><small>test mean {top['random_statistics']['stock_test']['win_rate_pct']['mean']:.2f}% / {top['random_statistics']['stock_test']['avg_return_pct']['mean']:.2f}%</small></div><div class='metric'><span>達標次數</span><b>{top['random_statistics']['stock_test']['pass_60win_10avg_count']} / 10</b><small>60% win + 10% avg</small></div></div><div class='warn'><strong>注意：</strong>score 分組後很多測試集只剩幾筆，平均報酬很容易被單一大贏家扭曲。這份報告是用來檢驗「score 是否真的有用」，不是直接挑最高列部署。</div></header><main><h2>Score 股池比較</h2><div class='table'><table><thead><tr><th>股池</th><th>Full 筆數</th><th>股票數</th><th>Full 勝率</th><th>Full 平均</th><th>Full 中位</th><th>未實現</th><th>Test平均筆數</th><th>Test平均勝率</th><th>Test平均報酬</th><th>達標次數</th></tr></thead><tbody>{rows_html}</tbody></table></div></main></body></html>"""


def render_md(payload: dict[str, Any]) -> str:
    id_to_variant = {item["id"]: item for item in payload["variants"]}
    ranked = [id_to_variant[item_id] for item_id in payload["ranked_ids"]]
    lines = [f"# {VERSION}", "", "| Pool | Full trades | Full win | Full avg | Test mean trades | Test mean win | Test mean avg | Pass |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for item in ranked:
        lines.append(
            f"| {item['label']} | {item['trade_count']} | {item['full']['win_rate_pct']:.2f}% | {item['full']['avg_return_pct']:.2f}% | {item['random_statistics']['stock_test']['trades']['mean']:.1f} | {item['random_statistics']['stock_test']['win_rate_pct']['mean']:.2f}% | {item['random_statistics']['stock_test']['avg_return_pct']['mean']:.2f}% | {item['random_statistics']['stock_test']['pass_60win_10avg_count']}/10 |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    payload = run()
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    OUT_MD.write_text(render_md(payload), encoding="utf-8")
    id_to_variant = {item["id"]: item for item in payload["variants"]}
    print(json.dumps({
        "version": VERSION,
        "universe": payload["universe"],
        "top_12": [
            {
                "id": item_id,
                "label": id_to_variant[item_id]["label"],
                "trade_count": id_to_variant[item_id]["trade_count"],
                "full": id_to_variant[item_id]["full"],
                "test": id_to_variant[item_id]["random_statistics"]["stock_test"],
            }
            for item_id in payload["ranked_ids"][:12]
        ],
        "html": str(OUT_HTML),
        "json": str(OUT_JSON),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
