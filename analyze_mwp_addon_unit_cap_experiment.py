#!/usr/bin/env python3
"""Search add-on variants that keep total entries under a unit cap."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

import analyze_pullback_pb_v23_independent_lifecycle as pbv23
from analyze_mwp_addon_strategy_comparison import strategy_record, strip_heavy

REPORT_DIR = Path("reports")
OUT_JSON = REPORT_DIR / "mwp_addon_unit_cap_experiment.json"
OUT_HTML = REPORT_DIR / "mwp_addon_unit_cap_experiment.html"
OUT_MD = REPORT_DIR / "mwp_addon_unit_cap_experiment.md"
VERSION = "MWP-addon-unit-cap-experiment"
UNIT_CAP = 300

PBV23_CAP_VARIANTS = [
    {"id": "pbv23_no_addon", "label": "PB-V23 原始母單池，不加碼", "max_addons": 0, "min_spacing": 5, "ma20_band_pct": 0.06},
    {"id": "pbv23_max1_band6", "label": "PB-V23 原始母單池，最多加碼1次，MA20 band 6%", "max_addons": 1, "min_spacing": 5, "ma20_band_pct": 0.06},
    {"id": "pbv23_max1_band4", "label": "PB-V23 原始母單池，最多加碼1次，MA20 band 4%", "max_addons": 1, "min_spacing": 5, "ma20_band_pct": 0.04},
    {"id": "pbv23_max1_band3", "label": "PB-V23 原始母單池，最多加碼1次，MA20 band 3%", "max_addons": 1, "min_spacing": 5, "ma20_band_pct": 0.03},
    {"id": "pbv23_max1_band2", "label": "PB-V23 原始母單池，最多加碼1次，MA20 band 2%", "max_addons": 1, "min_spacing": 5, "ma20_band_pct": 0.02},
    {"id": "pbv23_max1_band19", "label": "PB-V23 原始母單池，最多加碼1次，MA20 band 1.9%", "max_addons": 1, "min_spacing": 5, "ma20_band_pct": 0.019},
    {"id": "pbv23_max1_band18", "label": "PB-V23 原始母單池，最多加碼1次，MA20 band 1.8%", "max_addons": 1, "min_spacing": 5, "ma20_band_pct": 0.018},
    {"id": "pbv23_max1_band15", "label": "PB-V23 原始母單池，最多加碼1次，MA20 band 1.5%", "max_addons": 1, "min_spacing": 5, "ma20_band_pct": 0.015},
    {"id": "pbv23_max2_band3", "label": "PB-V23 原始母單池，最多加碼2次，MA20 band 3%", "max_addons": 2, "min_spacing": 5, "ma20_band_pct": 0.03},
    {"id": "pbv23_max2_band2", "label": "PB-V23 原始母單池，最多加碼2次，MA20 band 2%", "max_addons": 2, "min_spacing": 5, "ma20_band_pct": 0.02},
    {"id": "pbv23_max2_band15", "label": "PB-V23 原始母單池，最多加碼2次，MA20 band 1.5%", "max_addons": 2, "min_spacing": 5, "ma20_band_pct": 0.015},
]


def load_json(filename: str) -> dict[str, Any]:
    return json.loads((REPORT_DIR / filename).read_text(encoding="utf-8"))


def simulate_pbv23_cap_variants() -> list[dict[str, Any]]:
    source_trades = json.loads(pbv23.PBV4_JSON.read_text(encoding="utf-8"))["trades"]
    series = pbv23.make_series_map(pbv23.csv_files())
    benchmark_rows = pbv23.read_rows(pbv23.BENCHMARK_CSV)
    benchmark_dates = {row.date: index for index, row in enumerate(benchmark_rows)}
    v8 = load_json("pullback_pb_v8_multitimeframe_search.json")
    validation_start = v8["split"]["validation_start"]
    test_start = v8["split"]["test_start"]
    records = []
    for variant in PBV23_CAP_VARIANTS:
        result = pbv23.simulate_variant(
            source_trades,
            series,
            benchmark_rows,
            benchmark_dates,
            validation_start,
            test_start,
            variant,
        )
        record = strategy_record(
            variant["label"],
            result["units"],
            result["packages"],
            "simulated: PB-V23 cap experiment",
        )
        record["variant"] = result["variant"]
        records.append(record)
    return records


def load_existing_under_cap_baselines() -> list[dict[str, Any]]:
    records = []
    v9 = load_json("pullback_v9_fixed_addon_random_splits.json")
    records.append(strategy_record(
        "V9+ weekly-core + corrected V23 加碼（現有低頻對照）",
        v9.get("units", []),
        v9.get("packages", []),
        "pullback_v9_fixed_addon_random_splits.json",
    ))

    compare = load_json("pullback_v9_v18_addon_compare.json")
    for framework in compare.get("frameworks", []):
        if framework.get("framework_id") == "v18_unlimited_addon_v23":
            records.append(strategy_record(
                "V18+ no-limit + corrected V23 加碼（現有低頻對照）",
                framework.get("units", []),
                framework.get("packages", []),
                "pullback_v9_v18_addon_compare.json",
            ))

    all_scores = load_json("pullback_v18_all_scores_addon.json")
    result = all_scores.get("result", {})
    records.append(strategy_record(
        "V18+ all-score no-limit + corrected V23 加碼（現有低頻對照）",
        result.get("units", []),
        result.get("packages", []),
        "pullback_v18_all_scores_addon.json",
    ))
    return records


def decorate(record: dict[str, Any]) -> dict[str, Any]:
    summary = record["summary"]
    full_units = summary["full_units"]["units"]
    addon_units = summary["addon_units"]["units"]
    base_units = summary["base_units"]["units"]
    record["unit_cap"] = UNIT_CAP
    record["under_cap"] = full_units <= UNIT_CAP
    record["cap_room"] = UNIT_CAP - full_units
    record["addon_units_per_base"] = round(addon_units / max(1, base_units), 3)
    record["score_return_first"] = round(
        record["random_unit_stock_test"]["avg_return_pct"]["mean"]
        + 0.35 * record["random_unit_stock_test"]["avg_return_pct"]["p25"]
        + 0.05 * record["random_unit_stock_test"]["win_rate_pct"]["mean"],
        4,
    )
    return record


def fmt_pct(value: Any) -> str:
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return "-"


def fmt_num(value: Any) -> str:
    try:
        return str(int(round(float(value))))
    except (TypeError, ValueError):
        return "-"


def table_row(record: dict[str, Any]) -> str:
    full = record["summary"]["full_units"]
    addon = record["summary"]["addon_units"]
    package = record["summary"]["full_packages"]
    random_unit = record["random_unit_stock_test"]
    random_package = record["random_package_stock_test"]
    cap = "✅" if record["under_cap"] else "❌"
    return (
        f"<tr><th>{html.escape(record['label'])}</th>"
        f"<td>{cap}</td>"
        f"<td>{full['units']}</td>"
        f"<td>{record['summary']['base_units']['units']}</td>"
        f"<td>{addon['units']}</td>"
        f"<td>{fmt_pct(full['avg_return_pct'])}</td>"
        f"<td>{fmt_pct(full['win_rate_pct'])}</td>"
        f"<td>{fmt_pct(random_unit['avg_return_pct']['mean'])}</td>"
        f"<td>{fmt_pct(random_unit['avg_return_pct']['p25'])}</td>"
        f"<td>{fmt_pct(random_unit['win_rate_pct']['mean'])}</td>"
        f"<td>{random_unit['avg_ge_10_count']}/10</td>"
        f"<td>{fmt_pct(random_package['avg_return_pct']['mean'])}</td>"
        f"<td>{fmt_pct(package.get('avg_return_pct'))}</td>"
        f"<td>{record['summary']['lifecycle_violations']}</td></tr>"
    )


def render_html(payload: dict[str, Any]) -> str:
    rows = "".join(table_row(row) for row in payload["strategies"])
    best = payload.get("best_under_cap_return_first", {})
    return f"""<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{VERSION}</title><style>
:root{{--bg:#f6f7fb;--paper:#fff;--ink:#172033;--muted:#667085;--line:#e4e7ec;--blue:#2563eb}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 system-ui,'Microsoft JhengHei',sans-serif}}header,main{{max-width:1600px;margin:auto;padding:28px 20px}}header{{border-bottom:1px solid var(--line)}}h1{{margin:0 0 8px;font-size:30px}}p{{color:var(--muted)}}.note{{border-left:4px solid var(--blue);background:#eff6ff;padding:12px 14px;margin:18px 0;border-radius:12px}}.table{{overflow:auto;border:1px solid var(--line);background:#fff;border-radius:12px}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:right;vertical-align:top}}th:first-child,td:first-child{{text-align:left;min-width:330px}}thead th{{background:#f8fafc;color:var(--muted);font-size:12px}}code{{background:#eef2ff;padding:2px 6px;border-radius:6px}}@media(max-width:760px){{header,main{{padding:18px 10px}}}}
</style></head><body><header><h1>{VERSION}</h1><p>目標：報酬率優先，但總進場 units（母單 + 加碼單）壓在 {UNIT_CAP} 以內。每個候選皆做 10 次股票代號 60/20/20 隨機切分測試。</p><div class='note'><strong>推薦：</strong>{html.escape(best.get('label','-'))}。Random unit 平均報酬 {fmt_pct(best.get('random_unit_stock_test',{}).get('avg_return_pct',{}).get('mean'))}，p25 {fmt_pct(best.get('random_unit_stock_test',{}).get('avg_return_pct',{}).get('p25'))}，總 units {best.get('summary',{}).get('full_units',{}).get('units','-')}。</div></header><main><div class='table'><table><thead><tr><th>策略</th><th>&lt;=300</th><th>總units</th><th>母單</th><th>加碼</th><th>Full平均</th><th>Full勝率</th><th>Random unit平均</th><th>Random unit p25</th><th>Random unit勝率</th><th>Avg&gt;=10次數</th><th>Random package平均</th><th>Full package平均</th><th>生命週期違規</th></tr></thead><tbody>{rows}</tbody></table></div><p>JSON: <code>{OUT_JSON}</code>｜MD: <code>{OUT_MD}</code></p></main></body></html>"""


def md_row(record: dict[str, Any]) -> str:
    full = record["summary"]["full_units"]
    addon = record["summary"]["addon_units"]
    random_unit = record["random_unit_stock_test"]
    random_package = record["random_package_stock_test"]
    return (
        f"| {record['label']} | {'Y' if record['under_cap'] else 'N'} | {full['units']} | "
        f"{record['summary']['base_units']['units']} | {addon['units']} | {fmt_pct(full['avg_return_pct'])} | "
        f"{fmt_pct(random_unit['avg_return_pct']['mean'])} | {fmt_pct(random_unit['avg_return_pct']['p25'])} | "
        f"{fmt_pct(random_unit['win_rate_pct']['mean'])} | {random_unit['avg_ge_10_count']}/10 | "
        f"{fmt_pct(random_package['avg_return_pct']['mean'])} | {record['summary']['lifecycle_violations']} |"
    )


def render_md(payload: dict[str, Any]) -> str:
    lines = [
        f"# {VERSION}",
        "",
        f"目標：報酬率優先，但總進場 units（母單 + 加碼單）壓在 {UNIT_CAP} 以內。",
        "",
        "| 策略 | <=300 | 總units | 母單 | 加碼 | Full平均 | Random unit平均 | Random unit p25 | Random unit勝率 | Avg>=10次數 | Random package平均 | 生命週期違規 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    lines.extend(md_row(row) for row in payload["strategies"])
    best = payload.get("best_under_cap_return_first", {})
    lines.extend([
        "",
        f"推薦：{best.get('label','-')}",
        f"推薦理由：總 units {best.get('summary',{}).get('full_units',{}).get('units','-')}，Random unit 平均報酬 {fmt_pct(best.get('random_unit_stock_test',{}).get('avg_return_pct',{}).get('mean'))}，p25 {fmt_pct(best.get('random_unit_stock_test',{}).get('avg_return_pct',{}).get('p25'))}。",
    ])
    return "\n".join(lines) + "\n"


def main() -> None:
    simulated = simulate_pbv23_cap_variants()
    baselines = load_existing_under_cap_baselines()
    records = [decorate(row) for row in simulated + baselines]
    records.sort(
        key=lambda row: (
            not row["under_cap"],
            -float(row["random_unit_stock_test"]["avg_return_pct"]["mean"]),
            -float(row["random_unit_stock_test"]["avg_return_pct"]["p25"]),
        )
    )
    public_records = [strip_heavy(row) for row in records]
    under_cap = [row for row in public_records if row["under_cap"]]
    payload = {
        "version": VERSION,
        "unit_cap": UNIT_CAP,
        "methodology": {
            "objective": "Return first, total unit count under cap, including base and add-on units.",
            "random_stock_splits": "10 seeds from analyze_pullback_plus_random_splits.SEEDS, stock-code 60/20/20 split, evaluate stock_test.",
            "candidate_changes": "PB-V23 original mother pool candidates vary max_addons and MA20 retest band; existing V9/V18 lower-frequency corrected add-on strategies are included as baselines.",
        },
        "strategies": public_records,
        "best_under_cap_return_first": max(under_cap, key=lambda row: row["score_return_first"]) if under_cap else None,
        "best_under_cap_random_unit_avg": max(under_cap, key=lambda row: row["random_unit_stock_test"]["avg_return_pct"]["mean"]) if under_cap else None,
        "best_under_cap_random_unit_p25": max(under_cap, key=lambda row: row["random_unit_stock_test"]["avg_return_pct"]["p25"]) if under_cap else None,
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    OUT_MD.write_text(render_md(payload), encoding="utf-8")
    print(json.dumps({
        "version": VERSION,
        "unit_cap": UNIT_CAP,
        "best": payload["best_under_cap_return_first"],
        "strategies": [
            {
                "label": row["label"],
                "under_cap": row["under_cap"],
                "units": row["summary"]["full_units"]["units"],
                "base": row["summary"]["base_units"]["units"],
                "addons": row["summary"]["addon_units"]["units"],
                "full_avg": row["summary"]["full_units"]["avg_return_pct"],
                "random_unit_avg_mean": row["random_unit_stock_test"]["avg_return_pct"]["mean"],
                "random_unit_avg_p25": row["random_unit_stock_test"]["avg_return_pct"]["p25"],
                "random_unit_win_mean": row["random_unit_stock_test"]["win_rate_pct"]["mean"],
            }
            for row in public_records
        ],
        "html": str(OUT_HTML),
        "json": str(OUT_JSON),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
