#!/usr/bin/env python3
"""Fixed V9+ pool with PB-V23 add-ons over the same 10 randomized stock 60/20/20 splits."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from analyze_pullback_multitimeframe_search import BENCHMARK_CSV
from analyze_pullback_pb_v19_main_wave_addon import summarize_packages, summarize_units
from analyze_pullback_plus_independent_versions import target_summary
from analyze_pullback_plus_random_splits import SEEDS, random_stock_groups, strategy_stats
from analyze_pullback_technical_phenotypes import make_series_map
from analyze_pullback_v9_v18_addon_compare import FOCUS_VARIANT, simulate_framework, v9_plus_base_rows
from run_market_backtest import csv_files, read_rows

REPORT_DIR = Path("reports")
NO_ADDON_JSON = REPORT_DIR / "pullback_v9_fixed_random_splits.json"
OUT_JSON = REPORT_DIR / "pullback_v9_fixed_addon_random_splits.json"
OUT_HTML = REPORT_DIR / "pullback_v9_fixed_addon_random_splits.html"
OUT_MD = REPORT_DIR / "pullback_v9_fixed_addon_random_splits.md"
VERSION = "PB-V9-fixed-V23-addon-random-stock-splits"


def random_unit_runs(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    runs = []
    for seed in SEEDS:
        groups, counts = random_stock_groups(units, seed)
        summaries = {name: target_summary(group_rows) for name, group_rows in groups.items()}
        runs.append({
            "seed": seed,
            "stock_counts": counts,
            "trade_counts": {name: len(group_rows) for name, group_rows in groups.items()},
            "summaries": summaries,
        })
    return runs


def random_package_runs(packages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    runs = []
    for seed in SEEDS:
        groups, counts = random_stock_groups(packages, seed)
        summaries = {name: summarize_packages(group_rows) for name, group_rows in groups.items()}
        runs.append({
            "seed": seed,
            "stock_counts": counts,
            "package_counts": {name: len(group_rows) for name, group_rows in groups.items()},
            "summaries": summaries,
        })
    return runs


def package_stats(runs: list[dict[str, Any]]) -> dict[str, Any]:
    # Convert package summaries into the same shape expected by strategy_stats.
    converted = []
    for run in runs:
        converted_summaries = {}
        for split, summary in run["summaries"].items():
            converted_summaries[split] = {
                "trades": summary.get("signals", 0),
                "win_rate_pct": summary.get("win_rate_pct", 0.0),
                "avg_return_pct": summary.get("avg_return_pct", 0.0),
                "median_return_pct": summary.get("median_return_pct", 0.0),
                "unresolved": summary.get("unresolved", 0),
            }
        converted.append({"seed": run["seed"], "summaries": converted_summaries})
    return strategy_stats(converted)


def load_no_addon_reference() -> dict[str, Any] | None:
    if not NO_ADDON_JSON.exists():
        return None
    return json.loads(NO_ADDON_JSON.read_text(encoding="utf-8"))


def run() -> dict[str, Any]:
    series = make_series_map(csv_files())
    benchmark_rows = read_rows(BENCHMARK_CSV)
    benchmark_dates = {row.date: index for index, row in enumerate(benchmark_rows)}
    # Chronological split dates are not used for the random test itself, but simulate_framework requires them for summaries.
    v8 = json.loads((REPORT_DIR / "pullback_pb_v8_multitimeframe_search.json").read_text(encoding="utf-8"))
    validation_start = v8["split"]["validation_start"]
    test_start = v8["split"]["test_start"]
    framework = simulate_framework(
        "v9_fixed_v23_addon_random",
        "V9+ fixed weekly-core mother + V23 add-on",
        v9_plus_base_rows(),
        stress_addons=False,
        validation_start=validation_start,
        test_start=test_start,
        series=series,
        benchmark_rows=benchmark_rows,
        benchmark_dates=benchmark_dates,
    )
    unit_runs = random_unit_runs(framework["units"])
    package_runs = random_package_runs(framework["packages"])
    no_addon = load_no_addon_reference()
    return {
        "version": VERSION,
        "methodology": {
            "purpose": "Keep the fixed V9+ random-stock-split test unchanged, then add PB-V23 add-on conditions only.",
            "fixed_entry": "V9+ entry is fixed: abc_fast / market all / weekly all / monthly trend / signal controlled / top_n 0.",
            "fixed_mother_exit": "weekly_core mother exit is fixed.",
            "addon_logic": "PB-V23 focus add-on logic: MA20 retest, max5/spacing5, scan to available data end, loose-confluence structural close stop with next-open execution, and 15% close-based catastrophic line.",
            "split": "Same 10 seeds and same stock-code 60/20/20 split method as pullback_v9_fixed_random_splits. No rule or exit re-selection per seed.",
            "costs": "V9+ gross framework retained; no additional V18 stress cost is applied to V9 add-ons.",
        },
        "addon_variant": FOCUS_VARIANT,
        "no_addon_reference": {
            "full_summary": no_addon.get("full_summary") if no_addon else None,
            "statistics": no_addon.get("statistics") if no_addon else None,
            "universe": no_addon.get("universe") if no_addon else None,
        },
        "framework_summary": framework["summaries"],
        "unit_random_runs": unit_runs,
        "unit_random_statistics": strategy_stats(unit_runs),
        "package_random_runs": package_runs,
        "package_random_statistics": package_stats(package_runs),
        "units": framework["units"],
        "packages": framework["packages"],
    }


def pct(value: Any) -> str:
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return "-"


def unit_text(summary: dict[str, Any]) -> str:
    total = summary.get("units") or summary.get("trades") or 0
    return f"{total} 份｜{summary['win_rate_pct']:.2f}%｜{summary['avg_return_pct']:.2f}%｜中位 {summary['median_return_pct']:.2f}%｜未實現 {summary.get('unresolved', 0)}"


def package_text(summary: dict[str, Any]) -> str:
    return f"{summary.get('signals', 0)} 組｜{summary['win_rate_pct']:.2f}%｜{summary['avg_return_pct']:.2f}%｜中位 {summary['median_return_pct']:.2f}%"


def random_text(stats: dict[str, Any]) -> str:
    test = stats["stock_test"]
    return f"mean {test['trades']['mean']}｜{test['win_rate_pct']['mean']:.2f}%｜{test['avg_return_pct']['mean']:.2f}%｜pass {test['pass_60win_10avg_count']}/10"


def render_html(payload: dict[str, Any]) -> str:
    no_ref = payload.get("no_addon_reference") or {}
    no_full = no_ref.get("full_summary") or {}
    no_stats = no_ref.get("statistics") or {}
    no_test = (no_stats.get("stock_test") or {}) if no_stats else {}
    fw = payload["framework_summary"]
    unit_stats = payload["unit_random_statistics"]["stock_test"]
    pkg_stats = payload["package_random_statistics"]["stock_test"]
    run_rows = "".join(
        f"<tr><td>{run['seed']}</td>"
        f"<td>{run['trade_counts']['stock_train']} / {run['trade_counts']['stock_validation']} / {run['trade_counts']['stock_test']}</td>"
        f"<td>{pct(run['summaries']['stock_test']['win_rate_pct'])}</td>"
        f"<td>{pct(run['summaries']['stock_test']['avg_return_pct'])}</td>"
        f"<td>{pct(run['summaries']['stock_test']['median_return_pct'])}</td>"
        f"<td>{run['summaries']['stock_test'].get('unresolved', 0)}</td>"
        f"<td>{'YES' if run['summaries']['stock_test']['win_rate_pct'] >= 60 and run['summaries']['stock_test']['avg_return_pct'] >= 10 else 'NO'}</td></tr>"
        for run in payload["unit_random_runs"]
    )
    compare_rows = []
    if no_full and no_test:
        compare_rows.append(
            f"<tr><th>V9+ fixed，不加碼</th><td>{no_full['trades']} 筆｜{no_full['win_rate_pct']:.2f}%｜{no_full['avg_return_pct']:.2f}%｜未實現 {no_full.get('unresolved', 0)}</td><td>mean {no_test['trades']['mean']}｜{no_test['win_rate_pct']['mean']:.2f}%｜{no_test['avg_return_pct']['mean']:.2f}%｜pass {no_test['pass_60win_10avg_count']}/10</td><td>-</td><td>-</td></tr>"
        )
    compare_rows.append(
        f"<tr><th>V9+ fixed + V23 加碼</th><td>{html.escape(unit_text(fw['chronological_unit']['full']))}</td><td>{html.escape(random_text(payload['unit_random_statistics']))}</td><td>{html.escape(unit_text(fw['addon_units']))}</td><td>{html.escape(random_text(payload['package_random_statistics']))}</td></tr>"
    )
    compare_rows_html = "".join(compare_rows)
    return f"""<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{VERSION}</title><style>
:root{{--bg:#f6f7fb;--paper:#fff;--ink:#172033;--muted:#667085;--line:#e4e7ec;--bad:#b42318;--blue:#2563eb}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 system-ui,'Microsoft JhengHei',sans-serif}}header,main{{max-width:1400px;margin:auto;padding:28px 20px}}header{{border-bottom:1px solid var(--line)}}h1{{margin:0 0 8px;font-size:30px}}h2{{margin:28px 0 10px;font-size:20px}}p{{color:var(--muted)}}.metrics{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1px;background:var(--line);border:1px solid var(--line);margin-top:22px}}.metric{{background:#fff;padding:16px}}.metric span,.metric small{{display:block;color:var(--muted)}}.metric b{{font-size:22px}}.warn{{border-left:4px solid var(--bad);background:#fef3f2;padding:12px 14px;margin:18px 0;border-radius:12px}}.table{{overflow:auto;border:1px solid var(--line);background:#fff}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:right;vertical-align:top}}th:first-child,td:first-child{{text-align:left}}thead th{{background:#f8fafc;color:var(--muted);font-size:12px}}@media(max-width:900px){{.metrics{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}@media(max-width:560px){{header,main{{padding:18px 10px}}.metrics{{grid-template-columns:1fr}}}}
</style></head><body><header><h1>{VERSION}</h1><p>固定 V9+ 股池與 weekly_core 出場，沿用同一組 10 次隨機股票 60/20/20 切分，只新增 PB-V23 加碼條件。</p><div class='metrics'><div class='metric'><span>加碼後 Full units</span><b>{fw['chronological_unit']['full']['win_rate_pct']:.2f}% / {fw['chronological_unit']['full']['avg_return_pct']:.2f}%</b><small>{fw['chronological_unit']['full']['units']} 份｜未實現 {fw['chronological_unit']['full'].get('unresolved', 0)}</small></div><div class='metric'><span>Add-on units</span><b>{fw['addon_units']['win_rate_pct']:.2f}% / {fw['addon_units']['avg_return_pct']:.2f}%</b><small>{fw['addon_units']['units']} 份｜未實現 {fw['addon_units'].get('unresolved', 0)}</small></div><div class='metric'><span>Random unit test</span><b>{unit_stats['win_rate_pct']['mean']:.2f}% / {unit_stats['avg_return_pct']['mean']:.2f}%</b><small>pass {unit_stats['pass_60win_10avg_count']}/10｜mean trades {unit_stats['trades']['mean']}</small></div><div class='metric'><span>Random package test</span><b>{pkg_stats['win_rate_pct']['mean']:.2f}% / {pkg_stats['avg_return_pct']['mean']:.2f}%</b><small>pass {pkg_stats['pass_60win_10avg_count']}/10｜mean packages {pkg_stats['trades']['mean']}</small></div></div><div class='warn'><strong>提醒：</strong>這版只改「新增 V23 加碼」，其他 V9+ fixed random split 測試手法不變。若 package test 明顯低於 unit test，代表報酬主要來自少數大波段加碼，而不是每個原始訊號都穩。</div></header><main><h2>不加碼 vs 加碼</h2><div class='table'><table><thead><tr><th>版本</th><th>Full</th><th>Random unit stock-test</th><th>Add-on units</th><th>Random package stock-test</th></tr></thead><tbody>{compare_rows_html}</tbody></table></div><h2>10 次 random unit stock-test</h2><div class='table'><table><thead><tr><th>Seed</th><th>Train / Val / Test units</th><th>Test 勝率</th><th>Test 平均</th><th>Test 中位</th><th>Test 未實現</th><th>Test 達標</th></tr></thead><tbody>{run_rows}</tbody></table></div></main></body></html>"""


def render_md(payload: dict[str, Any]) -> str:
    fw = payload["framework_summary"]
    unit_stats = payload["unit_random_statistics"]["stock_test"]
    pkg_stats = payload["package_random_statistics"]["stock_test"]
    lines = [
        f"# {VERSION}",
        "",
        f"Full units: {unit_text(fw['chronological_unit']['full'])}",
        f"Add-on units: {unit_text(fw['addon_units'])}",
        f"Random unit stock-test: mean trades {unit_stats['trades']['mean']}, win {unit_stats['win_rate_pct']['mean']:.2f}%, avg {unit_stats['avg_return_pct']['mean']:.2f}%, pass {unit_stats['pass_60win_10avg_count']}/10",
        f"Random package stock-test: mean packages {pkg_stats['trades']['mean']}, win {pkg_stats['win_rate_pct']['mean']:.2f}%, avg {pkg_stats['avg_return_pct']['mean']:.2f}%, pass {pkg_stats['pass_60win_10avg_count']}/10",
        "",
        "| Seed | Test units | Test win | Test avg | Test median | Test unresolved | Pass |",
        "|---:|---:|---:|---:|---:|---:|---|",
    ]
    for run in payload["unit_random_runs"]:
        test = run["summaries"]["stock_test"]
        passed = test["win_rate_pct"] >= 60 and test["avg_return_pct"] >= 10
        lines.append(f"| {run['seed']} | {run['trade_counts']['stock_test']} | {test['win_rate_pct']:.2f}% | {test['avg_return_pct']:.2f}% | {test['median_return_pct']:.2f}% | {test.get('unresolved', 0)} | {'YES' if passed else 'NO'} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    payload = run()
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    OUT_MD.write_text(render_md(payload), encoding="utf-8")
    print(json.dumps({
        "version": VERSION,
        "full_units": payload["framework_summary"]["chronological_unit"]["full"],
        "addon_units": payload["framework_summary"]["addon_units"],
        "random_unit_stock_test": payload["unit_random_statistics"]["stock_test"],
        "random_package_stock_test": payload["package_random_statistics"]["stock_test"],
        "html": str(OUT_HTML),
        "json": str(OUT_JSON),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
