#!/usr/bin/env python3
"""Build the deployable MWP-C return-first capped strategy report.

MWP-C is the return-first capped variant selected after the unit-cap and technical-filter
experiments:
- PB-V23 original mother pool
- max 1 add-on per mother lifecycle
- MA20 retest band 1.9%
- whole-lifecycle filter: signal-date MA20 5-trading-day slope > 0
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from analyze_mwp_addon_strategy_comparison import strategy_record
from analyze_mwp_technical_filter_experiment import (
    BASE_VARIANT,
    build_features,
    filter_record,
    ge,
    simulate_baseline,
)

REPORT_DIR = Path("reports")
OUT_JSON = REPORT_DIR / "mwp_c_return_first_capped.json"
OUT_HTML = REPORT_DIR / "mwp_c_return_first_capped.html"
OUT_MD = REPORT_DIR / "mwp_c_return_first_capped.md"
VERSION = "MWP-C-return-first-capped-ma20-slope"
STRATEGY_CODE = "MWP-C"

FILTER_LABEL = "MA20 近 5 日斜率 > 0"


def compact_random(stats: dict[str, Any]) -> dict[str, Any]:
    return stats.get("stock_test", stats)


def pct(value: Any) -> str:
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return "-"


def fmt(value: Any) -> str:
    if value is None:
        return "-"
    return str(value)


def lifecycle_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (str(row.get("market") or "").upper(), str(row.get("stock_no") or ""), str(row.get("signal_date") or ""))


def filtered_units_and_packages() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    units, packages, series = simulate_baseline()
    features = build_features(packages, series)
    record = filter_record(FILTER_LABEL, packages, units, features, ge("ma20_slope5_pct", 0))
    selected_keys = {lifecycle_key(package) for package in record["packages"]}
    selected_units = [unit for unit in units if lifecycle_key(unit) in selected_keys]
    selected_packages = [package for package in packages if lifecycle_key(package) in selected_keys]
    baseline_record = strategy_record("baseline：不加 MA20 斜率濾網", units, packages, "simulated baseline")
    return selected_units, selected_packages, record, baseline_record


def build_payload() -> dict[str, Any]:
    units, packages, record, baseline_record = filtered_units_and_packages()
    summary = record["summary"]
    baseline_summary = baseline_record["summary"]
    payload = {
        "version": VERSION,
        "strategy": {
            "code": STRATEGY_CODE,
            "name": "Return-first capped MWP with MA20 slope filter",
            "title": "MWP-C 報酬率優先低頻加碼策略",
            "status": "Backtest candidate; ready for remote/code review.",
            "base_pool": "PB-V23 original mother pool",
            "addon_rule": "Max 1 add-on per mother lifecycle; MA20 retest band 1.9%; add-ons only while mother is open; 10-trading-day same-stock buy/buy-signal cooldown; add-ons sync-exit when mother exits.",
            "technical_filter": FILTER_LABEL,
            "risk_rule": "Mother hard stop 7%; add-on close-based catastrophic stop 15%; mother exit synchronizes remaining add-ons.",
        },
        "methodology": {
            "unit_cap_goal": "Keep total entries under 300 units, including mother/base and add-on units.",
            "selected_variant": BASE_VARIANT,
            "filter_level": "Whole mother lifecycle/package. If the mother lifecycle fails the filter, its base and all add-ons are excluded.",
            "random_stock_splits": "10 stock-code random 60/20/20 splits via the same helper used by MWP comparison reports.",
        },
        "baseline_without_filter": {
            "full_units": baseline_summary["full_units"],
            "base_units": baseline_summary["base_units"],
            "addon_units": baseline_summary["addon_units"],
            "full_packages": baseline_summary["full_packages"],
            "random_unit_stock_test": baseline_record["random_unit_stock_test"],
            "random_package_stock_test": baseline_record["random_package_stock_test"],
        },
        "framework_summary": {
            "chronological_unit": {"full": summary["full_units"]},
            "chronological_package": {"full": summary["full_packages"]},
            "base_units": summary["base_units"],
            "addon_units": summary["addon_units"],
            "lifecycle_violations": summary["lifecycle_violations"],
            "selected_lifecycles": record["selected_lifecycles"],
            "selected_units": record["selected_units"],
            "excluded_lifecycles": record["excluded_lifecycles"],
            "excluded_units": record["excluded_units"],
            "stop_loss_lifecycle_rate_pct": record["stop_loss_lifecycle_rate_pct"],
        },
        "unit_random_statistics": {"stock_test": record["random_unit_stock_test"]},
        "package_random_statistics": {"stock_test": record["random_package_stock_test"]},
        "units": units,
        "packages": packages,
        "source_reports": {
            "unit_cap_experiment": "mwp_addon_unit_cap_experiment.json",
            "technical_filter_experiment": "mwp_technical_filter_experiment.json",
        },
    }
    return payload


def unit_cell(summary: dict[str, Any]) -> str:
    return f"{summary.get('units', 0)}｜勝 {pct(summary.get('win_rate_pct'))}｜均 {pct(summary.get('avg_return_pct'))}｜中 {pct(summary.get('median_return_pct'))}｜未 {summary.get('unresolved', 0)}"


def random_cell(stats: dict[str, Any], key: str = "units") -> str:
    return f"test均 {fmt(stats.get(key, {}).get('mean'))}｜報酬均 {pct(stats.get('avg_return_pct', {}).get('mean'))}｜p25 {pct(stats.get('avg_return_pct', {}).get('p25'))}｜勝均 {pct(stats.get('win_rate_pct', {}).get('mean'))}"


def render_html(payload: dict[str, Any]) -> str:
    strategy = payload["strategy"]
    summary = payload["framework_summary"]
    baseline = payload["baseline_without_filter"]
    return f"""<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{VERSION}</title><style>
:root{{--bg:#f6f7fb;--paper:#fff;--ink:#172033;--muted:#667085;--line:#e4e7ec;--blue:#2563eb}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 system-ui,'Microsoft JhengHei',sans-serif}}header,main{{max-width:1300px;margin:auto;padding:28px 20px}}header{{border-bottom:1px solid var(--line)}}h1{{margin:0 0 8px;font-size:30px}}p{{color:var(--muted)}}.note{{border-left:4px solid var(--blue);background:#eff6ff;padding:12px 14px;margin:18px 0;border-radius:12px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}}.card{{background:#fff;border:1px solid var(--line);border-radius:14px;padding:14px}}table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--line);border-radius:12px;overflow:hidden}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}thead th{{background:#f8fafc;color:var(--muted);font-size:12px}}code{{background:#eef2ff;padding:2px 6px;border-radius:6px}}
</style></head><body><header><h1>{html.escape(strategy['title'])}</h1><p>{html.escape(strategy['name'])}</p><div class='note'><strong>正式加入濾網：</strong>{html.escape(strategy['technical_filter'])}。總 units {summary['selected_units']}，生命週期 {summary['selected_lifecycles']}，生命週期違規 {summary['lifecycle_violations']}。</div></header><main><section class='grid'><div class='card'><h2>Full units</h2><p>{html.escape(unit_cell(summary['chronological_unit']['full']))}</p></div><div class='card'><h2>Base units</h2><p>{html.escape(unit_cell(summary['base_units']))}</p></div><div class='card'><h2>Add-on units</h2><p>{html.escape(unit_cell(summary['addon_units']))}</p></div><div class='card'><h2>Random stock-test</h2><p>{html.escape(random_cell(payload['unit_random_statistics']['stock_test']))}</p></div></section><h2>與未加濾網 baseline 比較</h2><table><thead><tr><th>版本</th><th>Full units</th><th>Random unit stock-test</th><th>Package stock-test</th></tr></thead><tbody><tr><td>Baseline 無 MA20 斜率濾網</td><td>{html.escape(unit_cell(baseline['full_units']))}</td><td>{html.escape(random_cell(baseline['random_unit_stock_test']))}</td><td>{html.escape(random_cell(baseline['random_package_stock_test'], 'signals'))}</td></tr><tr><td>MWP-C 加 MA20 斜率濾網</td><td>{html.escape(unit_cell(summary['chronological_unit']['full']))}</td><td>{html.escape(random_cell(payload['unit_random_statistics']['stock_test']))}</td><td>{html.escape(random_cell(payload['package_random_statistics']['stock_test'], 'signals'))}</td></tr></tbody></table><h2>策略規則</h2><ul><li>{html.escape(strategy['base_pool'])}</li><li>{html.escape(strategy['addon_rule'])}</li><li>{html.escape(strategy['risk_rule'])}</li></ul><p>JSON: <code>{OUT_JSON}</code>｜MD: <code>{OUT_MD}</code></p></main></body></html>"""


def render_md(payload: dict[str, Any]) -> str:
    summary = payload["framework_summary"]
    baseline = payload["baseline_without_filter"]
    lines = [
        f"# {VERSION}",
        "",
        f"策略：{payload['strategy']['title']}",
        f"正式濾網：{payload['strategy']['technical_filter']}",
        "",
        "## 結果",
        f"- Full units: {unit_cell(summary['chronological_unit']['full'])}",
        f"- Base units: {unit_cell(summary['base_units'])}",
        f"- Add-on units: {unit_cell(summary['addon_units'])}",
        f"- Random unit stock-test: {random_cell(payload['unit_random_statistics']['stock_test'])}",
        f"- Random package stock-test: {random_cell(payload['package_random_statistics']['stock_test'], 'signals')}",
        f"- Lifecycle violations: {summary['lifecycle_violations']}",
        "",
        "## Baseline comparison",
        f"- Baseline full units: {unit_cell(baseline['full_units'])}",
        f"- Baseline random unit stock-test: {random_cell(baseline['random_unit_stock_test'])}",
        "",
        "## Rules",
        f"- {payload['strategy']['base_pool']}",
        f"- {payload['strategy']['addon_rule']}",
        f"- {payload['strategy']['risk_rule']}",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    payload = build_payload()
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    OUT_MD.write_text(render_md(payload), encoding="utf-8")
    print(json.dumps({
        "output": str(OUT_JSON),
        "html": str(OUT_HTML),
        "strategy": payload["strategy"],
        "full_units": payload["framework_summary"]["chronological_unit"]["full"],
        "base_units": payload["framework_summary"]["base_units"],
        "addon_units": payload["framework_summary"]["addon_units"],
        "random_unit_stock_test": payload["unit_random_statistics"]["stock_test"],
        "lifecycle_violations": payload["framework_summary"]["lifecycle_violations"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
