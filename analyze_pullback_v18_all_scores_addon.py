#!/usr/bin/env python3
"""Apply PB-V23 add-on lifecycle to the all-score V18+ no-limit mother pool."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from analyze_pullback_pb_v19_main_wave_addon import POSITION_SIZE, summarize_packages, summarize_units
from analyze_pullback_pb_v20_fuzzy_addon import split_chronological, split_stocks
from analyze_pullback_pb_v23_independent_lifecycle import FOCUS_VARIANT_ID as V23_FOCUS_ID
from analyze_pullback_pb_v23_independent_lifecycle import VARIANTS as V23_VARIANTS
from analyze_pullback_pb_v23_independent_lifecycle import scan_addons
from analyze_pullback_pb_v18_finite_capital import STRESS_SLIPPAGE_EACH_SIDE_PCT, adjusted_rows
from analyze_pullback_plus_independent_versions import target_summary
from analyze_pullback_plus_random_splits import SEEDS, random_stock_groups, strategy_stats
from analyze_pullback_technical_phenotypes import find_series, make_series_map
from analyze_pullback_v18_all_scores_no_limit import build_all_score_exits
from pullback_lifecycle_filters import filter_same_stock_mother_entries
from run_market_backtest import read_rows, csv_files
from analyze_pullback_multitimeframe_search import BENCHMARK_CSV

REPORT_DIR = Path("reports")
OUT_JSON = REPORT_DIR / "pullback_v18_all_scores_addon.json"
OUT_HTML = REPORT_DIR / "pullback_v18_all_scores_addon.html"
OUT_MD = REPORT_DIR / "pullback_v18_all_scores_addon.md"
VERSION = "PB-V18-all-scores-v23-addon"
FOCUS_VARIANT = next(row for row in V23_VARIANTS if row["id"] == V23_FOCUS_ID)


def score_value(row: dict[str, Any]) -> int | None:
    try:
        return int(row.get("score"))
    except (TypeError, ValueError):
        return None


def apply_stress_to_addons(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    adjusted = adjusted_rows(rows, STRESS_SLIPPAGE_EACH_SIDE_PCT)
    for row in adjusted:
        row["stress_adjusted"] = True
    return adjusted


def simulate_all_score_addons(
    base_rows: list[dict[str, Any]],
    *,
    validation_start: str,
    test_start: str,
    series: dict[Any, Any],
    benchmark_rows: list[Any],
    benchmark_dates: dict[str, int],
) -> dict[str, Any]:
    units: list[dict[str, Any]] = []
    packages: list[dict[str, Any]] = []
    for source in base_rows:
        bundle = find_series(series, str(source["market"]), str(source["stock_no"]))
        if not bundle:
            continue
        rows, indicators, dates = bundle
        signal_index = dates.get(str(source["signal_date"]))
        if signal_index is None or signal_index + 1 >= len(rows):
            continue
        base_entry_index = signal_index + 1
        base_unit = {
            **source,
            "framework": "v18_all_scores_addon",
            "framework_label": "V18+ all-score no-limit + V23 add-on",
            "variant": FOCUS_VARIANT["id"],
            "unit_type": "base",
            "addon_number": 0,
        }
        if "pnl" not in base_unit:
            base_unit["pnl"] = round(float(base_unit["return_pct"]) / 100 * POSITION_SIZE)
        units.append(base_unit)

        base_exit_index = dates.get(str(base_unit.get("exit_date")), len(rows) - 1)
        addon_units = scan_addons(
            source,
            rows,
            indicators,
            dates,
            signal_index,
            base_entry_index,
            benchmark_rows,
            benchmark_dates,
            FOCUS_VARIANT,
            base_exit_index,
            base_unit,
        )
        addon_units = apply_stress_to_addons(addon_units)
        for addon in addon_units:
            addon["framework"] = "v18_all_scores_addon"
            addon["framework_label"] = "V18+ all-score no-limit + V23 add-on"
            addon["variant"] = FOCUS_VARIANT["id"]
        units.extend(addon_units)

        total_units = 1 + len(addon_units)
        total_pnl = base_unit["pnl"] + sum(row["pnl"] for row in addon_units)
        packages.append({
            **source,
            "framework": "v18_all_scores_addon",
            "framework_label": "V18+ all-score no-limit + V23 add-on",
            "variant": FOCUS_VARIANT["id"],
            "base_return_pct": base_unit["return_pct"],
            "base_exit_date": base_unit.get("exit_date"),
            "base_exit_reason": base_unit.get("exit_reason"),
            "addon_count": len(addon_units),
            "addon_added": bool(addon_units),
            "total_units": total_units,
            "total_capital": total_units * POSITION_SIZE,
            "total_pnl": total_pnl,
            "package_return_pct": round(total_pnl / (total_units * POSITION_SIZE) * 100, 2),
            "unresolved": bool(base_unit.get("unresolved")) or any(bool(row.get("unresolved")) for row in addon_units),
        })

    chrono_units = split_chronological(units, validation_start, test_start)
    chrono_packages = split_chronological(packages, validation_start, test_start)
    stock_units, stock_counts = split_stocks(units)
    stock_packages, package_stock_counts = split_stocks(packages)
    base_units = [row for row in units if row["unit_type"] == "base"]
    addon_units = [row for row in units if row["unit_type"] == "addon"]
    return {
        "variant": FOCUS_VARIANT,
        "source_base_trades": len(base_rows),
        "summaries": {
            "chronological_unit": {name: summarize_units(rows) for name, rows in chrono_units.items()},
            "chronological_package": {name: summarize_packages(rows) for name, rows in chrono_packages.items()},
            "stock_unit": {name: summarize_units(rows) for name, rows in stock_units.items()},
            "stock_package": {name: summarize_packages(rows) for name, rows in stock_packages.items()},
            "base_units": summarize_units(base_units),
            "addon_units": summarize_units(addon_units),
            "stock_counts": stock_counts,
            "package_stock_counts": package_stock_counts,
        },
        "units": units,
        "packages": packages,
    }


def random_stock_unit_runs(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
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


def load_reference() -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, filename in {
        "all_scores_no_addon": "pullback_v18_all_scores_no_limit.json",
        "avoid_score4_addon": "pullback_v9_v18_addon_compare.json",
        "pb_v23": "pullback_pb_v23_independent_lifecycle.json",
    }.items():
        path = REPORT_DIR / filename
        if path.exists():
            output[key] = json.loads(path.read_text(encoding="utf-8"))
    return output


def compact_units(summary: dict[str, Any]) -> str:
    return (
        f"{summary.get('units', summary.get('trades', 0))}｜{summary['win_rate_pct']:.2f}%｜"
        f"{summary['avg_return_pct']:.2f}%｜中位 {summary['median_return_pct']:.2f}%｜"
        f"未實現 {summary.get('unresolved', 0)}"
    )


def compact_packages(summary: dict[str, Any]) -> str:
    return (
        f"{summary.get('signals', 0)}｜{summary['win_rate_pct']:.2f}%｜"
        f"{summary['avg_return_pct']:.2f}%｜中位 {summary['median_return_pct']:.2f}%"
    )


def run() -> dict[str, Any]:
    base_rows, metadata = build_all_score_exits()
    raw_base_count = len(base_rows)
    series = make_series_map(csv_files())
    raw_buy_dates_by_stock: dict[tuple[str, str], list[str]] = {}
    for row in base_rows:
        raw_buy_dates_by_stock.setdefault((str(row.get("market") or "").upper(), str(row.get("stock_no") or "")), []).append(str(row.get("entry_date")))
    base_rows, lifecycle_diagnostics = filter_same_stock_mother_entries(base_rows, series, find_series, cooldown_trading_days=10)
    for row in base_rows:
        row["same_stock_buy_signal_entry_dates"] = sorted(set(raw_buy_dates_by_stock.get((str(row.get("market") or "").upper(), str(row.get("stock_no") or "")), [])))
    benchmark_rows = read_rows(BENCHMARK_CSV)
    benchmark_dates = {row.date: index for index, row in enumerate(benchmark_rows)}
    v8_path = REPORT_DIR / "pullback_pb_v8_multitimeframe_search.json"
    v8 = json.loads(v8_path.read_text(encoding="utf-8"))
    validation_start = v8["split"]["validation_start"]
    test_start = v8["split"]["test_start"]
    result = simulate_all_score_addons(
        base_rows,
        validation_start=validation_start,
        test_start=test_start,
        series=series,
        benchmark_rows=benchmark_rows,
        benchmark_dates=benchmark_dates,
    )
    random_runs = random_stock_unit_runs(result["units"])
    return {
        "version": VERSION,
        "methodology": {
            "base": "All-score V18+ no-limit mother pool: one-year enriched pullback pool with avoid_score4 removed, V17 runner mother exit, V18 fee/tax/slippage stress, no finite capital/max position/day-entry/duplicate-stock capacity limits.",
            "addon_logic": "Corrected PB-V23 focus add-on: add-ons only while the mother/base unit is still open; add-on entries are blocked by same-stock 10-trading-day buy/buy-signal cooldown; any still-open add-on is force-closed when the mother/base unit exits; PB-V20 MA20-retest timing, max5/spacing5, PB-V22 loose confluence structural stop with next-open execution, and 15% close-based catastrophic line for add-ons only.",
            "changed_from_previous_all_score": "Adds V23 add-on units. Mother units are unchanged from pullback_v18_all_scores_no_limit.",
            "split": {"validation_start": validation_start, "test_start": test_start},
        },
        "universe": {**metadata, "raw_base_rows_before_lifecycle_filter": raw_base_count, "lifecycle_filter": lifecycle_diagnostics},
        "result": result,
        "random_stock_unit_runs": random_runs,
        "random_stock_unit_statistics": strategy_stats(random_runs),
        "reference": load_reference(),
    }


def pct(value: Any) -> str:
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return "-"


def comparison_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    all_no_addon = payload.get("reference", {}).get("all_scores_no_addon")
    if all_no_addon:
        rows.append({
            "label": "All-score no-limit：不加碼",
            "full_units": all_no_addon["full"],
            "stock_test_units": all_no_addon["random_statistics"]["stock_test"],
            "addon_units": None,
            "full_packages": None,
            "stock_test_packages": None,
        })
    avoid_addon = payload.get("reference", {}).get("avoid_score4_addon")
    if avoid_addon:
        for item in avoid_addon.get("comparisons", []):
            if "V18+ no-limit" in item.get("label", ""):
                rows.append({
                    "label": "avoid_score4 V18+ no-limit + V23 加碼",
                    "full_units": item["full_units"],
                    "stock_test_units": item["stock_test_units"],
                    "addon_units": item["addon_units"],
                    "full_packages": item["full_packages"],
                    "stock_test_packages": item["stock_test_packages"],
                })
                break
    result = payload["result"]
    s = result["summaries"]
    rows.append({
        "label": "All-score V18+ no-limit + V23 加碼",
        "full_units": s["chronological_unit"]["full"],
        "stock_test_units": s["stock_unit"]["stock_test"],
        "addon_units": s["addon_units"],
        "full_packages": s["chronological_package"]["full"],
        "stock_test_packages": s["stock_package"]["stock_test"],
    })
    return rows


def stock_test_text(summary: dict[str, Any]) -> str:
    if "trades" in summary and isinstance(summary["trades"], int):
        return compact_units(summary)
    if "trades" in summary and isinstance(summary["trades"], dict):
        return (
            f"mean trades {summary['trades']['mean']}｜"
            f"win {summary['win_rate_pct']['mean']:.2f}%｜"
            f"avg {summary['avg_return_pct']['mean']:.2f}%｜"
            f"pass {summary['pass_60win_10avg_count']}/10"
        )
    return str(summary)


def render_html(payload: dict[str, Any]) -> str:
    rows = comparison_rows(payload)
    table_rows = "".join(
        f"<tr><th>{html.escape(row['label'])}</th>"
        f"<td>{html.escape(compact_units(row['full_units']))}</td>"
        f"<td>{html.escape(stock_test_text(row['stock_test_units']))}</td>"
        f"<td>{html.escape(compact_units(row['addon_units'])) if row.get('addon_units') else '-'}</td>"
        f"<td>{html.escape(compact_packages(row['full_packages'])) if row.get('full_packages') else '-'}</td>"
        f"<td>{html.escape(compact_packages(row['stock_test_packages'])) if row.get('stock_test_packages') else '-'}</td></tr>"
        for row in rows
    )
    s = payload["result"]["summaries"]
    rand = payload["random_stock_unit_statistics"]["stock_test"]
    return f"""<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{VERSION}</title><style>
:root{{--bg:#f6f7fb;--paper:#fff;--ink:#172033;--muted:#667085;--line:#e4e7ec;--good:#08735d;--bad:#b42318;--blue:#2563eb}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 system-ui,'Microsoft JhengHei',sans-serif}}header,main{{max-width:1400px;margin:auto;padding:28px 20px}}header{{border-bottom:1px solid var(--line)}}h1{{margin:0 0 8px;font-size:30px}}h2{{margin:28px 0 10px;font-size:20px}}p{{color:var(--muted)}}.metrics{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1px;background:var(--line);border:1px solid var(--line);margin-top:22px}}.metric{{background:#fff;padding:16px}}.metric span,.metric small{{display:block;color:var(--muted)}}.metric b{{font-size:22px}}.note{{border-left:4px solid var(--blue);background:#eff6ff;padding:12px 14px;margin:18px 0;border-radius:12px}}.warn{{border-left:4px solid var(--bad);background:#fef3f2;padding:12px 14px;margin:18px 0;border-radius:12px}}.table{{overflow:auto;border:1px solid var(--line);background:#fff}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:right;vertical-align:top}}th:first-child,td:first-child{{text-align:left}}thead th{{background:#f8fafc;color:var(--muted);font-size:12px}}@media(max-width:900px){{.metrics{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}@media(max-width:560px){{header,main{{padding:18px 10px}}.metrics{{grid-template-columns:1fr}}}}
</style></head><body><header><h1>{VERSION}</h1><p>把 PB-V23 加碼邏輯套到 222 筆 all-score V18+ no-limit 母體上。</p><div class='metrics'><div class='metric'><span>Full units</span><b>{s['chronological_unit']['full']['units']}</b><small>{s['chronological_unit']['full']['win_rate_pct']:.2f}% / {s['chronological_unit']['full']['avg_return_pct']:.2f}%</small></div><div class='metric'><span>Add-ons</span><b>{s['addon_units']['units']}</b><small>{s['addon_units']['win_rate_pct']:.2f}% / {s['addon_units']['avg_return_pct']:.2f}%｜unresolved {s['addon_units'].get('unresolved', 0)}</small></div><div class='metric'><span>Deterministic stock test</span><b>{s['stock_unit']['stock_test']['units']}</b><small>{s['stock_unit']['stock_test']['win_rate_pct']:.2f}% / {s['stock_unit']['stock_test']['avg_return_pct']:.2f}%</small></div><div class='metric'><span>Random stock test mean</span><b>{rand['win_rate_pct']['mean']:.2f}% / {rand['avg_return_pct']['mean']:.2f}%</b><small>pass {rand['pass_60win_10avg_count']}/10｜mean trades {rand['trades']['mean']}</small></div></div><div class='warn'><strong>注意：</strong>這版雖然 full 平均因大量未實現加碼單大幅拉高，但 random stock test 平均勝率仍不到 60%，且未實現比例很高。</div></header><main><h2>對照表</h2><div class='table'><table><thead><tr><th>架構</th><th>Full units</th><th>Stock test units</th><th>Add-on units</th><th>Full packages</th><th>Stock test packages</th></tr></thead><tbody>{table_rows}</tbody></table></div></main></body></html>"""


def render_md(payload: dict[str, Any]) -> str:
    s = payload["result"]["summaries"]
    rand = payload["random_stock_unit_statistics"]["stock_test"]
    return "\n".join([
        f"# {VERSION}",
        "",
        f"Full units: {compact_units(s['chronological_unit']['full'])}",
        f"Stock test units: {compact_units(s['stock_unit']['stock_test'])}",
        f"Add-on units: {compact_units(s['addon_units'])}",
        f"Full packages: {compact_packages(s['chronological_package']['full'])}",
        f"Stock test packages: {compact_packages(s['stock_package']['stock_test'])}",
        f"Random stock test mean: trades {rand['trades']['mean']}, win {rand['win_rate_pct']['mean']:.2f}%, avg {rand['avg_return_pct']['mean']:.2f}%, pass {rand['pass_60win_10avg_count']}/10",
        "",
    ])


def main() -> None:
    payload = run()
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    OUT_MD.write_text(render_md(payload), encoding="utf-8")
    s = payload["result"]["summaries"]
    print(json.dumps({
        "version": VERSION,
        "full_units": s["chronological_unit"]["full"],
        "stock_test_units": s["stock_unit"]["stock_test"],
        "addon_units": s["addon_units"],
        "full_packages": s["chronological_package"]["full"],
        "stock_test_packages": s["stock_package"]["stock_test"],
        "random_stock_unit_statistics": payload["random_stock_unit_statistics"]["stock_test"],
        "html": str(OUT_HTML),
        "json": str(OUT_JSON),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
