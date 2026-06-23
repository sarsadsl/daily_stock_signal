#!/usr/bin/env python3
"""Compare PB-V23 add-on lifecycle on top of V9+ and V18+ no-limit base frameworks."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from analyze_pullback_multitimeframe_search import BENCHMARK_CSV, add_benchmark_return, enrich_trades, select
from analyze_pullback_pb_v19_main_wave_addon import POSITION_SIZE, summarize_packages, summarize_units
from analyze_pullback_pb_v20_fuzzy_addon import split_chronological, split_stocks
from analyze_pullback_pb_v23_independent_lifecycle import FOCUS_VARIANT_ID as V23_FOCUS_ID
from analyze_pullback_pb_v23_independent_lifecycle import VARIANTS as V23_VARIANTS
from analyze_pullback_pb_v23_independent_lifecycle import scan_addons
from analyze_pullback_plus_independent_versions import V9_ENTRY_RULE, compute_independent_exits, rule_label, target_summary
from analyze_pullback_technical_phenotypes import find_series, make_series_map
from analyze_pullback_v18_unlimited import build_v18_candidate_exits
from analyze_pullback_pb_v18_finite_capital import STRESS_SLIPPAGE_EACH_SIDE_PCT, adjusted_rows
from run_market_backtest import csv_files, read_rows

REPORT_DIR = Path("reports")
OUT_JSON = REPORT_DIR / "pullback_v9_v18_addon_compare.json"
OUT_HTML = REPORT_DIR / "pullback_v9_v18_addon_compare.html"
OUT_MD = REPORT_DIR / "pullback_v9_v18_addon_compare.md"
VERSION = "PB-V9-V18-addon-compare"
FOCUS_VARIANT = next(row for row in V23_VARIANTS if row["id"] == V23_FOCUS_ID)


def load_v23_reference() -> dict[str, Any] | None:
    path = REPORT_DIR / "pullback_pb_v23_independent_lifecycle.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    for item in payload.get("variants", []):
        if item.get("variant", {}).get("id") == V23_FOCUS_ID:
            return item
    return None


def v9_plus_base_rows() -> list[dict[str, Any]]:
    enriched, _ = enrich_trades()
    selected_features = select(enriched, V9_ENTRY_RULE)
    selected_keys = {(row["signal_date"], row["market"], row["stock_no"]) for row in selected_features}
    independent = compute_independent_exits(enriched)
    # Deterministic V9+ selected weekly_core in the plus-version report.
    rows = [
        row for row in independent["weekly_core"]
        if (row["signal_date"], row["market"], row["stock_no"]) in selected_keys
    ]
    for row in rows:
        row["base_framework"] = "V9+ weekly_core"
        row["base_framework_note"] = "V9+ deterministic entry cohort with weekly-core independent mother exit"
    return rows


def v18_unlimited_base_rows() -> list[dict[str, Any]]:
    gross_rows = build_v18_candidate_exits()
    stress_rows = adjusted_rows(gross_rows, STRESS_SLIPPAGE_EACH_SIDE_PCT)
    for row in stress_rows:
        row["base_framework"] = "V18+ no-limit stress"
        row["base_framework_note"] = "V18 candidate pool without finite-capital/position/day-entry constraints; V17 runner exit with V18 stress costs"
    return stress_rows


def addon_key(row: dict[str, Any]) -> tuple[str, str, str, int]:
    return (
        str(row.get("signal_date")),
        str(row.get("market")),
        str(row.get("stock_no")),
        int(row.get("addon_number") or 0),
    )


def apply_stress_to_addons(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    adjusted = adjusted_rows(rows, STRESS_SLIPPAGE_EACH_SIDE_PCT)
    # adjusted_rows copies rows but does not preserve explicit gross field in summaries by itself; keep label for clarity.
    for row in adjusted:
        row["stress_adjusted"] = True
    return adjusted


def simulate_framework(
    framework_id: str,
    label: str,
    base_rows: list[dict[str, Any]],
    *,
    stress_addons: bool,
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
            "framework": framework_id,
            "framework_label": label,
            "variant": FOCUS_VARIANT["id"],
            "unit_type": "base",
            "addon_number": 0,
        }
        if "pnl" not in base_unit:
            base_unit["pnl"] = round(float(base_unit["return_pct"]) / 100 * POSITION_SIZE)
        units.append(base_unit)

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
        )
        if stress_addons:
            addon_units = apply_stress_to_addons(addon_units)
        for addon in addon_units:
            addon["framework"] = framework_id
            addon["framework_label"] = label
            addon["variant"] = FOCUS_VARIANT["id"]
        units.extend(addon_units)
        total_units = 1 + len(addon_units)
        total_pnl = base_unit["pnl"] + sum(row["pnl"] for row in addon_units)
        packages.append({
            **source,
            "framework": framework_id,
            "framework_label": label,
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
        "framework_id": framework_id,
        "label": label,
        "stress_addons": stress_addons,
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


def compact(summary: dict[str, Any], key: str = "units") -> str:
    count = summary.get(key, summary.get("signals", summary.get("trades", 0)))
    return f"{count}｜{summary['win_rate_pct']:.2f}%｜{summary['avg_return_pct']:.2f}%｜中位 {summary['median_return_pct']:.2f}%｜未實現 {summary.get('unresolved', 0)}"


def compare_record(label: str, item: dict[str, Any]) -> dict[str, Any]:
    s = item["summaries"]
    return {
        "label": label,
        "full_units": s["chronological_unit"]["full"],
        "stock_test_units": s["stock_unit"]["stock_test"],
        "base_units": s["base_units"],
        "addon_units": s["addon_units"],
        "full_packages": s["chronological_package"]["full"],
        "stock_test_packages": s["stock_package"]["stock_test"],
    }


def run() -> dict[str, Any]:
    series = make_series_map(csv_files())
    benchmark_rows = read_rows(BENCHMARK_CSV)
    benchmark_dates = {row.date: index for index, row in enumerate(benchmark_rows)}
    v8 = json.loads((REPORT_DIR / "pullback_pb_v8_multitimeframe_search.json").read_text(encoding="utf-8"))
    validation_start = v8["split"]["validation_start"]
    test_start = v8["split"]["test_start"]
    v23_ref = load_v23_reference()
    v9 = simulate_framework(
        "v9_plus_addon_v23",
        "V9+ weekly-core 母單 + V23 加碼",
        v9_plus_base_rows(),
        stress_addons=False,
        validation_start=validation_start,
        test_start=test_start,
        series=series,
        benchmark_rows=benchmark_rows,
        benchmark_dates=benchmark_dates,
    )
    v18 = simulate_framework(
        "v18_unlimited_addon_v23",
        "V18+ no-limit 母單 + V23 加碼（壓力成本）",
        v18_unlimited_base_rows(),
        stress_addons=True,
        validation_start=validation_start,
        test_start=test_start,
        series=series,
        benchmark_rows=benchmark_rows,
        benchmark_dates=benchmark_dates,
    )
    comparisons = []
    if v23_ref:
        comparisons.append(compare_record("PB-V23 原版：PB-V4 母單 + V23 加碼", v23_ref))
    comparisons.append(compare_record(v9["label"], v9))
    comparisons.append(compare_record(v18["label"], v18))
    return {
        "version": VERSION,
        "methodology": {
            "goal": "Add PB-V23-style add-ons to V9+ and V18+ no-limit base frameworks and compare with PB-V23.",
            "addon_logic": "Same as PB-V23 focus variant: PB-V20 MA20-retest add-on timing, max5 spacing5, scan to available data end, PB-V22 loose confluence structural stop, next-open execution after close-based break, 15% close-based catastrophic line.",
            "v9_base": "V9+ deterministic entry cohort using weekly-core independent mother exit. Gross return, no extra costs applied.",
            "v18_base": "V18+ no-limit candidate pool using V17 runner mother exit and V18 fee/tax/slippage stress. Add-ons also receive the same stress adjustment.",
            "split": {"validation_start": validation_start, "test_start": test_start},
        },
        "v23_reference_available": bool(v23_ref),
        "comparisons": comparisons,
        "frameworks": [v9, v18],
    }


def render_html(payload: dict[str, Any]) -> str:
    rows = "".join(
        f"<tr><th>{html.escape(row['label'])}</th>"
        f"<td>{html.escape(compact(row['full_units']))}</td>"
        f"<td>{html.escape(compact(row['stock_test_units']))}</td>"
        f"<td>{html.escape(compact(row['base_units']))}</td>"
        f"<td>{html.escape(compact(row['addon_units']))}</td>"
        f"<td>{html.escape(compact(row['full_packages'], 'signals'))}</td>"
        f"<td>{html.escape(compact(row['stock_test_packages'], 'signals'))}</td></tr>"
        for row in payload["comparisons"]
    )
    cards = "".join(
        f"<div class='card'><span>{html.escape(item['label'])}</span>"
        f"<b>{item['summaries']['chronological_unit']['full']['avg_return_pct']:.2f}%</b>"
        f"<small>{item['summaries']['chronological_unit']['full']['units']} units｜addons {item['summaries']['addon_units']['units']}｜stock test {item['summaries']['stock_unit']['stock_test']['avg_return_pct']:.2f}%</small></div>"
        for item in payload["frameworks"]
    )
    return f"""<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{VERSION}</title><style>
:root{{--bg:#f6f7fb;--paper:#fff;--ink:#172033;--muted:#667085;--line:#e4e7ec;--good:#08735d;--bad:#b42318;--blue:#2563eb}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 system-ui,'Microsoft JhengHei',sans-serif}}header,main{{max-width:1400px;margin:auto;padding:28px 20px}}header{{border-bottom:1px solid var(--line)}}h1{{margin:0 0 8px;font-size:30px}}h2{{margin:28px 0 10px;font-size:20px}}p{{color:var(--muted)}}.cards{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1px;background:var(--line);border:1px solid var(--line);margin-top:22px}}.card{{background:#fff;padding:16px}}.card span,.card small{{display:block;color:var(--muted)}}.card b{{font-size:24px}}.note{{border-left:4px solid var(--blue);background:#eff6ff;padding:12px 14px;margin:18px 0;border-radius:12px}}.warn{{border-left:4px solid var(--bad);background:#fef3f2;padding:12px 14px;margin:18px 0;border-radius:12px}}.table{{overflow:auto;border:1px solid var(--line);background:#fff}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:right;vertical-align:top}}th:first-child,td:first-child{{text-align:left}}thead th{{background:#f8fafc;color:var(--muted);font-size:12px}}@media(max-width:800px){{.cards{{grid-template-columns:1fr}}header,main{{padding:18px 10px}}}}
</style></head><body><header><h1>{VERSION}</h1><p>把 PB-V23 的加碼邏輯套到 V9+ 與 V18+ no-limit 母單架構上，並與 PB-V23 原版比較。</p><div class='cards'>{cards}</div><div class='note'><strong>加碼邏輯固定：</strong>{html.escape(payload['methodology']['addon_logic'])}</div><div class='warn'><strong>注意：</strong>V9+ 是毛報酬口徑；V18+ no-limit 保留 V18 成本與 +0.10% 雙邊壓力滑價。PB-V23 原版為舊報告口徑，主要用來看同一套加碼邏輯在不同母單池上的相對變化。</div></header><main><h2>總表</h2><div class='table'><table><thead><tr><th>架構</th><th>Full 全部單位</th><th>Stock test 單位</th><th>母單</th><th>加碼單</th><th>Full package</th><th>Stock test package</th></tr></thead><tbody>{rows}</tbody></table></div><h2>檔案</h2><p>JSON: <code>{OUT_JSON}</code>｜HTML: <code>{OUT_HTML}</code></p></main></body></html>"""


def render_md(payload: dict[str, Any]) -> str:
    lines = [f"# {VERSION}", "", "| Framework | Full units | Stock test units | Base units | Addon units |", "|---|---:|---:|---:|---:|"]
    for row in payload["comparisons"]:
        lines.append(
            f"| {row['label']} | {compact(row['full_units'])} | {compact(row['stock_test_units'])} | {compact(row['base_units'])} | {compact(row['addon_units'])} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    payload = run()
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    OUT_MD.write_text(render_md(payload), encoding="utf-8")
    print(json.dumps({
        "version": VERSION,
        "comparisons": payload["comparisons"],
        "html": str(OUT_HTML),
        "json": str(OUT_JSON),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
