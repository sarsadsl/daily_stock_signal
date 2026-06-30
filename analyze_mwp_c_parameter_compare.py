#!/usr/bin/env python3
"""Compare MWP-C mother slope thresholds and add-on MA20 retest bands."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

import analyze_pullback_pb_v23_independent_lifecycle as pbv23
from analyze_mwp_addon_strategy_comparison import strip_heavy
from analyze_mwp_technical_filter_experiment import BASE_VARIANT, build_features, filter_record, ge

REPORT_DIR = Path("reports")
OUT_JSON = REPORT_DIR / "mwp_c_parameter_compare.json"
OUT_HTML = REPORT_DIR / "mwp_c_parameter_compare.html"
OUT_MD = REPORT_DIR / "mwp_c_parameter_compare.md"
VERSION = "MWP-C-parameter-compare"

SLOPE_THRESHOLDS = [0.0, 0.5, 1.0, 2.0, 2.5, 4.0]
ADDON_VARIANTS = [
    {
        "id": "pbv23_max1_band19",
        "label": "現行規則：加碼帶 1.9%",
        "max_addons": 1,
        "min_spacing": 5,
        "ma20_band_pct": 0.019,
    },
    {
        "id": "pbv23_max1_band25",
        "label": "比較規則：加碼帶 2.5%",
        "max_addons": 1,
        "min_spacing": 5,
        "ma20_band_pct": 0.025,
    },
]


def pct(value: Any) -> str:
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return "-"


def fmt_count(value: Any) -> str:
    try:
        return str(int(round(float(value))))
    except (TypeError, ValueError):
        return "-"


def unit_cell(summary: dict[str, Any]) -> str:
    return (
        f"{summary.get('units', 0)}｜勝 {pct(summary.get('win_rate_pct'))}｜"
        f"均 {pct(summary.get('avg_return_pct'))}｜中 {pct(summary.get('median_return_pct'))}｜"
        f"未 {summary.get('unresolved', 0)}"
    )


def random_cell(stats: dict[str, Any], count_key: str = "units") -> str:
    return (
        f"test均 {fmt_count(stats.get(count_key, {}).get('mean'))}｜"
        f"勝均 {pct(stats.get('win_rate_pct', {}).get('mean'))}｜"
        f"報酬均 {pct(stats.get('avg_return_pct', {}).get('mean'))}｜"
        f"p25 {pct(stats.get('avg_return_pct', {}).get('p25'))}｜"
        f"60/10 {fmt_count(stats.get('pass_60win_10avg_count'))}/10"
    )


def simulate_context() -> dict[str, Any]:
    source_trades = json.loads(pbv23.PBV4_JSON.read_text(encoding="utf-8"))["trades"]
    series = pbv23.make_series_map(pbv23.csv_files())
    benchmark_rows = pbv23.read_rows(pbv23.BENCHMARK_CSV)
    benchmark_dates = {row.date: index for index, row in enumerate(benchmark_rows)}
    v8 = json.loads((REPORT_DIR / "pullback_pb_v8_multitimeframe_search.json").read_text(encoding="utf-8"))
    return {
        "source_trades": source_trades,
        "series": series,
        "benchmark_rows": benchmark_rows,
        "benchmark_dates": benchmark_dates,
        "validation_start": v8["split"]["validation_start"],
        "test_start": v8["split"]["test_start"],
    }


def simulate_variant(context: dict[str, Any], variant: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[Any, Any]]:
    result = pbv23.simulate_variant(
        context["source_trades"],
        context["series"],
        context["benchmark_rows"],
        context["benchmark_dates"],
        context["validation_start"],
        context["test_start"],
        variant,
    )
    return result["units"], result["packages"], context["series"]


def mother_slope_records() -> list[dict[str, Any]]:
    context = simulate_context()
    units, packages, series = simulate_variant(context, BASE_VARIANT)
    features = build_features(packages, series)
    records: list[dict[str, Any]] = []
    for threshold in SLOPE_THRESHOLDS:
        label = "現行正式規則：母單 MA20 5 日斜率 > 0" if threshold == 0 else f"比較規則：母單 MA20 5 日斜率 > {threshold:g}"
        record = strip_heavy(filter_record(label, packages, units, features, ge("ma20_slope5_pct", threshold)))
        record["threshold"] = threshold
        record["ma20_band_pct"] = BASE_VARIANT["ma20_band_pct"] * 100
        record["is_current_rule"] = threshold == 0
        records.append(record)
    return records


def addon_band_records() -> list[dict[str, Any]]:
    context = simulate_context()
    records: list[dict[str, Any]] = []
    for variant in ADDON_VARIANTS:
        units, packages, series = simulate_variant(context, variant)
        features = build_features(packages, series)
        record = strip_heavy(
            filter_record(
                f"{variant['label']}（母單斜率固定 > 0）",
                packages,
                units,
                features,
                ge("ma20_slope5_pct", 0),
            )
        )
        record["variant"] = variant
        record["band_pct"] = variant["ma20_band_pct"] * 100
        record["is_current_rule"] = variant["ma20_band_pct"] == BASE_VARIANT["ma20_band_pct"]
        records.append(record)
    return records


def slope_row(record: dict[str, Any]) -> str:
    row_class = " class='focus'" if record.get("is_current_rule") else ""
    return (
        f"<tr{row_class}>"
        f"<th>{html.escape(record['label'])}</th>"
        f"<td>{pct(record.get('threshold'))}</td>"
        f"<td>{html.escape(unit_cell(record['summary']['full_units']))}</td>"
        f"<td>{html.escape(unit_cell(record['summary']['base_units']))}</td>"
        f"<td>{html.escape(unit_cell(record['summary']['addon_units']))}</td>"
        f"<td>{html.escape(random_cell(record['random_unit_stock_test']))}</td>"
        f"<td>{html.escape(random_cell(record['random_package_stock_test'], 'signals'))}</td>"
        f"<td>{pct(record.get('stop_loss_lifecycle_rate_pct'))}</td>"
        f"</tr>"
    )


def band_row(record: dict[str, Any]) -> str:
    row_class = " class='focus'" if record.get("is_current_rule") else ""
    return (
        f"<tr{row_class}>"
        f"<th>{html.escape(record['label'])}</th>"
        f"<td>{pct(record.get('band_pct'))}</td>"
        f"<td>{html.escape(unit_cell(record['summary']['full_units']))}</td>"
        f"<td>{html.escape(unit_cell(record['summary']['base_units']))}</td>"
        f"<td>{html.escape(unit_cell(record['summary']['addon_units']))}</td>"
        f"<td>{html.escape(random_cell(record['random_unit_stock_test']))}</td>"
        f"<td>{html.escape(random_cell(record['random_package_stock_test'], 'signals'))}</td>"
        f"<td>{pct(record.get('stop_loss_lifecycle_rate_pct'))}</td>"
        f"</tr>"
    )


def render_html(payload: dict[str, Any]) -> str:
    slope_rows = "".join(slope_row(record) for record in payload["mother_slope_thresholds"])
    band_rows = "".join(band_row(record) for record in payload["addon_band_comparison"])
    best_slope = payload["best_mother_slope_by_random_avg"]
    best_band = payload["best_addon_band_by_random_avg"]
    return f"""<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{VERSION}</title><style>
:root{{--bg:#f6f7fb;--paper:#fff;--ink:#172033;--muted:#667085;--line:#e4e7ec;--blue:#2563eb;--teal:#0f766e}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 system-ui,'Microsoft JhengHei',sans-serif}}header,main{{max-width:1600px;margin:auto;padding:28px 20px}}header{{border-bottom:1px solid var(--line)}}h1{{margin:0 0 8px;font-size:30px}}h2{{margin:28px 0 10px}}p{{color:var(--muted)}}.note{{border-left:4px solid var(--blue);background:#eff6ff;padding:12px 14px;margin:18px 0;border-radius:12px}}.table{{overflow:auto;border:1px solid var(--line);background:#fff;border-radius:12px;margin:18px 0}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:right;vertical-align:top}}th:first-child,td:first-child{{text-align:left;min-width:300px}}thead th{{background:#f8fafc;color:var(--muted);font-size:12px}}tr.focus th,tr.focus td{{background:#ecfdf5}}code{{background:#eef2ff;padding:2px 6px;border-radius:6px}}@media(max-width:760px){{header,main{{padding:18px 10px}}}}</style></head><body><header><h1>MWP-C 參數比較</h1><p>同一套 corrected-lifecycle MWP-C 框架下，分開比較母單 MA20 斜率門檻與加碼單 MA20 回測帶寬。</p><div class='note'><strong>比較原則：</strong>上半段只改母單斜率門檻，固定加碼帶為 {BASE_VARIANT['ma20_band_pct'] * 100:.1f}%；下半段只改加碼帶寬，固定母單斜率門檻為 <code>MA20 5 日斜率 &gt; 0</code>。<br>母單斜率目前 random unit 平均報酬最佳：<strong>{html.escape(best_slope['label'])}</strong>；加碼帶目前 random unit 平均報酬較佳：<strong>{html.escape(best_band['label'])}</strong>。</div></header><main><h2>母單 MA20 5 日斜率門檻比較</h2><div class='table'><table><thead><tr><th>規則</th><th>斜率門檻</th><th>Full units</th><th>Base units</th><th>Add-on units</th><th>10 random unit stock-test</th><th>10 random package stock-test</th><th>停損生命週期率</th></tr></thead><tbody>{slope_rows}</tbody></table></div><h2>加碼單 MA20 回測帶：現行 1.9% vs 2.5%</h2><div class='table'><table><thead><tr><th>規則</th><th>加碼帶</th><th>Full units</th><th>Base units</th><th>Add-on units</th><th>10 random unit stock-test</th><th>10 random package stock-test</th><th>停損生命週期率</th></tr></thead><tbody>{band_rows}</tbody></table></div><p>JSON: <code>{OUT_JSON}</code>｜MD: <code>{OUT_MD}</code></p></main></body></html>"""


def render_md(payload: dict[str, Any]) -> str:
    lines = [
        "# MWP-C 參數比較",
        "",
        f"- 母單斜率比較固定加碼帶 {BASE_VARIANT['ma20_band_pct'] * 100:.1f}%。",
        "- 加碼帶比較固定母單斜率門檻 `MA20 5 日斜率 > 0`。",
        "",
        "## 母單 MA20 5 日斜率門檻比較",
        "",
        "| 規則 | 斜率門檻 | Full units | Base units | Add-on units | 10 random unit stock-test | 10 random package stock-test | 停損生命週期率 |",
        "|---|---:|---|---|---|---|---|---:|",
    ]
    for record in payload["mother_slope_thresholds"]:
        lines.append(
            f"| {record['label']} | {pct(record.get('threshold'))} | {unit_cell(record['summary']['full_units'])} | {unit_cell(record['summary']['base_units'])} | {unit_cell(record['summary']['addon_units'])} | {random_cell(record['random_unit_stock_test'])} | {random_cell(record['random_package_stock_test'], 'signals')} | {pct(record.get('stop_loss_lifecycle_rate_pct'))} |"
        )
    lines.extend([
        "",
        "## 加碼單 MA20 回測帶比較",
        "",
        "| 規則 | 加碼帶 | Full units | Base units | Add-on units | 10 random unit stock-test | 10 random package stock-test | 停損生命週期率 |",
        "|---|---:|---|---|---|---|---|---:|",
    ])
    for record in payload["addon_band_comparison"]:
        lines.append(
            f"| {record['label']} | {pct(record.get('band_pct'))} | {unit_cell(record['summary']['full_units'])} | {unit_cell(record['summary']['base_units'])} | {unit_cell(record['summary']['addon_units'])} | {random_cell(record['random_unit_stock_test'])} | {random_cell(record['random_package_stock_test'], 'signals')} | {pct(record.get('stop_loss_lifecycle_rate_pct'))} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    slope_records = mother_slope_records()
    band_records = addon_band_records()
    payload = {
        "version": VERSION,
        "methodology": {
            "mother_slope_compare": "Use the same corrected-lifecycle MWP-C baseline (max 1 add-on, MA20 band 1.9%) and only change the mother signal-date MA20 5-day slope threshold.",
            "addon_band_compare": "Keep the mother slope gate fixed at MA20 5-day slope > 0 and only change the add-on MA20 retest band from 1.9% to 2.5%.",
            "random_stock_splits": "10 stock-code random 60/20/20 splits, same helper as other MWP reports.",
        },
        "mother_slope_thresholds": slope_records,
        "addon_band_comparison": band_records,
    }
    payload["best_mother_slope_by_random_avg"] = max(
        slope_records,
        key=lambda row: (
            row["random_unit_stock_test"]["avg_return_pct"]["mean"],
            row["random_unit_stock_test"]["avg_return_pct"]["p25"],
        ),
    )
    payload["best_addon_band_by_random_avg"] = max(
        band_records,
        key=lambda row: (
            row["random_unit_stock_test"]["avg_return_pct"]["mean"],
            row["random_unit_stock_test"]["avg_return_pct"]["p25"],
        ),
    )
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    OUT_MD.write_text(render_md(payload), encoding="utf-8")
    print(
        json.dumps(
            {
                "version": VERSION,
                "best_mother_slope_by_random_avg": {
                    "label": payload["best_mother_slope_by_random_avg"]["label"],
                    "random_avg": payload["best_mother_slope_by_random_avg"]["random_unit_stock_test"]["avg_return_pct"]["mean"],
                    "random_p25": payload["best_mother_slope_by_random_avg"]["random_unit_stock_test"]["avg_return_pct"]["p25"],
                    "full_units": payload["best_mother_slope_by_random_avg"]["summary"]["full_units"],
                },
                "best_addon_band_by_random_avg": {
                    "label": payload["best_addon_band_by_random_avg"]["label"],
                    "random_avg": payload["best_addon_band_by_random_avg"]["random_unit_stock_test"]["avg_return_pct"]["mean"],
                    "random_p25": payload["best_addon_band_by_random_avg"]["random_unit_stock_test"]["avg_return_pct"]["p25"],
                    "full_units": payload["best_addon_band_by_random_avg"]["summary"]["full_units"],
                },
                "html": str(OUT_HTML),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
