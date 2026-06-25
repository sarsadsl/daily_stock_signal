#!/usr/bin/env python3
"""Compare all current add-on strategy payloads with 10 randomized stock splits."""

from __future__ import annotations

import html
import json
import statistics
from pathlib import Path
from typing import Any, Callable

from analyze_pullback_pb_v19_main_wave_addon import summarize_packages, summarize_units
from analyze_pullback_plus_random_splits import SEEDS, random_stock_groups

REPORT_DIR = Path("reports")
OUT_JSON = REPORT_DIR / "mwp_addon_strategy_comparison.json"
OUT_HTML = REPORT_DIR / "mwp_addon_strategy_comparison.html"
OUT_MD = REPORT_DIR / "mwp_addon_strategy_comparison.md"
VERSION = "MWP-addon-strategy-comparison-corrected-lifecycle"


def load_json(filename: str) -> dict[str, Any]:
    return json.loads((REPORT_DIR / filename).read_text(encoding="utf-8"))


def distribution(values: list[float]) -> dict[str, float]:
    if not values:
        return {"min": 0.0, "p25": 0.0, "mean": 0.0, "median": 0.0, "p75": 0.0, "max": 0.0, "stdev": 0.0}
    ordered = sorted(values)
    def quantile(q: float) -> float:
        if len(ordered) == 1:
            return ordered[0]
        pos = q * (len(ordered) - 1)
        low = int(pos)
        high = min(low + 1, len(ordered) - 1)
        frac = pos - low
        return ordered[low] * (1 - frac) + ordered[high] * frac
    return {
        "min": round(min(values), 2),
        "p25": round(quantile(0.25), 2),
        "mean": round(statistics.mean(values), 2),
        "median": round(statistics.median(values), 2),
        "p75": round(quantile(0.75), 2),
        "max": round(max(values), 2),
        "stdev": round(statistics.pstdev(values), 2),
    }


def randomized_stats(rows: list[dict[str, Any]], summarizer: Callable[[list[dict[str, Any]]], dict[str, Any]], count_key: str) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    for seed in SEEDS:
        groups, counts = random_stock_groups(rows, seed)
        summaries = {name: summarizer(group_rows) for name, group_rows in groups.items()}
        runs.append({
            "seed": seed,
            "stock_counts": counts,
            "row_counts": {name: len(group_rows) for name, group_rows in groups.items()},
            "summaries": summaries,
        })
    test_summaries = [run["summaries"]["stock_test"] for run in runs]
    return {
        "runs": runs,
        "stock_test": {
            count_key: distribution([float(row.get(count_key, row.get("trades", 0))) for row in test_summaries]),
            "win_rate_pct": distribution([float(row.get("win_rate_pct", 0)) for row in test_summaries]),
            "avg_return_pct": distribution([float(row.get("avg_return_pct", 0)) for row in test_summaries]),
            "median_return_pct": distribution([float(row.get("median_return_pct", 0)) for row in test_summaries]),
            "capital_return_pct": distribution([float(row.get("capital_return_pct", 0)) for row in test_summaries]),
            "pass_60win_10avg_count": sum(float(row.get("win_rate_pct", 0)) >= 60 and float(row.get("avg_return_pct", 0)) >= 10 for row in test_summaries),
            "avg_ge_10_count": sum(float(row.get("avg_return_pct", 0)) >= 10 for row in test_summaries),
            "win_ge_60_count": sum(float(row.get("win_rate_pct", 0)) >= 60 for row in test_summaries),
        },
    }


def lifecycle_violations(units: list[dict[str, Any]]) -> int:
    by_lifecycle: dict[tuple[Any, Any, Any], list[dict[str, Any]]] = {}
    for row in units:
        by_lifecycle.setdefault((row.get("market"), row.get("stock_no"), row.get("signal_date")), []).append(row)
    violations = 0
    for rows in by_lifecycle.values():
        base = [row for row in rows if row.get("unit_type") != "addon"]
        if not base:
            continue
        mother = base[0]
        if mother.get("unresolved"):
            continue
        for addon in [row for row in rows if row.get("unit_type") == "addon"]:
            if addon.get("unresolved") or str(addon.get("exit_date")) > str(mother.get("exit_date")):
                violations += 1
    return violations


def strategy_record(label: str, units: list[dict[str, Any]], packages: list[dict[str, Any]], source: str) -> dict[str, Any]:
    base_units = [row for row in units if row.get("unit_type") != "addon"]
    addon_units = [row for row in units if row.get("unit_type") == "addon"]
    unit_random = randomized_stats(units, summarize_units, "units")
    package_random = randomized_stats(packages, summarize_packages, "signals")
    full_units = summarize_units(units)
    full_packages = summarize_packages(packages)
    addons = summarize_units(addon_units)
    return {
        "label": label,
        "source": source,
        "units": units,
        "packages": packages,
        "summary": {
            "full_units": full_units,
            "base_units": summarize_units(base_units),
            "addon_units": addons,
            "full_packages": full_packages,
            "addon_rate_pct": full_packages.get("addon_rate_pct", 0),
            "base_count": len(base_units),
            "addon_count": len(addon_units),
            "lifecycle_violations": lifecycle_violations(units),
        },
        "random_unit_stock_test": unit_random["stock_test"],
        "random_package_stock_test": package_random["stock_test"],
        "random_unit_runs": unit_random["runs"],
        "random_package_runs": package_random["runs"],
    }


def collect_strategies() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    v23 = load_json("pullback_pb_v23_independent_lifecycle.json")
    for item in v23.get("variants", []):
        variant = item.get("variant", {})
        variant_id = variant.get("id")
        if not variant_id:
            continue
        out.append(strategy_record(
            f"PB-V23 原始母單池 + corrected V23 加碼 {variant_id}",
            item.get("units", []),
            item.get("packages", []),
            "pullback_pb_v23_independent_lifecycle.json",
        ))

    v9 = load_json("pullback_v9_fixed_addon_random_splits.json")
    out.append(strategy_record(
        "V9+ weekly-core 母單 + corrected V23 加碼",
        v9.get("units", []),
        v9.get("packages", []),
        "pullback_v9_fixed_addon_random_splits.json",
    ))

    compare = load_json("pullback_v9_v18_addon_compare.json")
    for framework in compare.get("frameworks", []):
        if framework.get("framework_id") == "v18_unlimited_addon_v23":
            out.append(strategy_record(
                "V18+ no-limit 母單 + corrected V23 加碼（壓力成本）",
                framework.get("units", []),
                framework.get("packages", []),
                "pullback_v9_v18_addon_compare.json",
            ))

    all_scores = load_json("pullback_v18_all_scores_addon.json")
    result = all_scores.get("result", {})
    out.append(strategy_record(
        "V18+ all-score no-limit 母單 + corrected V23 加碼（壓力成本）",
        result.get("units", []),
        result.get("packages", []),
        "pullback_v18_all_scores_addon.json",
    ))
    return out


def strip_heavy(record: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if key not in {"units", "packages", "random_unit_runs", "random_package_runs"}}


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
    return f"{summary.get('units', 0)}｜勝 {pct(summary.get('win_rate_pct'))}｜均 {pct(summary.get('avg_return_pct'))}｜中 {pct(summary.get('median_return_pct'))}｜未 {summary.get('unresolved', 0)}"


def pkg_cell(summary: dict[str, Any]) -> str:
    return f"{summary.get('signals', 0)}｜勝 {pct(summary.get('win_rate_pct'))}｜均 {pct(summary.get('avg_return_pct'))}｜加碼率 {pct(summary.get('addon_rate_pct'))}"


def random_cell(stats: dict[str, Any], count_key: str) -> str:
    return (
        f"test {fmt_count(stats[count_key]['mean'])}｜勝均 {pct(stats['win_rate_pct']['mean'])}｜"
        f"報酬均 {pct(stats['avg_return_pct']['mean'])}｜60/10 {stats['pass_60win_10avg_count']}/10"
    )


def render_html(payload: dict[str, Any]) -> str:
    rows = "".join(
        f"<tr><th>{html.escape(row['label'])}</th>"
        f"<td>{html.escape(unit_cell(row['summary']['full_units']))}</td>"
        f"<td>{html.escape(unit_cell(row['summary']['addon_units']))}</td>"
        f"<td>{html.escape(pkg_cell(row['summary']['full_packages']))}</td>"
        f"<td>{html.escape(random_cell(row['random_unit_stock_test'], 'units'))}</td>"
        f"<td>{html.escape(random_cell(row['random_package_stock_test'], 'signals'))}</td>"
        f"<td>{row['summary']['lifecycle_violations']}</td></tr>"
        for row in payload["strategies"]
    )
    best_unit = payload.get("best_by_random_unit_avg_return", {})
    best_pkg = payload.get("best_by_random_package_pass", {})
    return f"""<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{VERSION}</title><style>
:root{{--bg:#f6f7fb;--paper:#fff;--ink:#172033;--muted:#667085;--line:#e4e7ec;--blue:#2563eb}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 system-ui,'Microsoft JhengHei',sans-serif}}header,main{{max-width:1500px;margin:auto;padding:28px 20px}}header{{border-bottom:1px solid var(--line)}}h1{{margin:0 0 8px;font-size:30px}}p{{color:var(--muted)}}.note{{border-left:4px solid var(--blue);background:#eff6ff;padding:12px 14px;margin:18px 0;border-radius:12px}}.table{{overflow:auto;border:1px solid var(--line);background:#fff}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:right;vertical-align:top}}th:first-child,td:first-child{{text-align:left;min-width:300px}}thead th{{background:#f8fafc;color:var(--muted);font-size:12px}}code{{background:#eef2ff;padding:2px 6px;border-radius:6px}}@media(max-width:760px){{header,main{{padding:18px 10px}}}}
</style></head><body><header><h1>{VERSION}</h1><p>所有目前採 corrected V23 加碼生命週期的策略重跑後比較；每個策略皆做 10 次股票代號 60/20/20 隨機切分測試。</p><div class='note'><strong>修正後共用邏輯：</strong>母單仍持有才可加碼；同股 10 個交易日買進 / 買進候選冷卻；母單出場時仍在場加碼同步出場；加碼單 15% close-based catastrophic stop；母單 7% hard stop。</div><p>Random unit 平均報酬最佳：<strong>{html.escape(best_unit.get('label','-'))}</strong>｜Random package 達標次數最佳：<strong>{html.escape(best_pkg.get('label','-'))}</strong></p></header><main><div class='table'><table><thead><tr><th>策略</th><th>Full unit</th><th>Addon unit</th><th>Full package</th><th>10 random unit stock-test</th><th>10 random package stock-test</th><th>生命週期違規</th></tr></thead><tbody>{rows}</tbody></table></div><p>JSON: <code>{OUT_JSON}</code>｜MD: <code>{OUT_MD}</code></p></main></body></html>"""


def render_md(payload: dict[str, Any]) -> str:
    lines = [
        f"# {VERSION}",
        "",
        "修正後共用邏輯：母單仍持有才可加碼；同股 10 個交易日買進 / 買進候選冷卻；母單出場時仍在場加碼同步出場；加碼單 15% close-based catastrophic stop；母單 7% hard stop。",
        "",
        "| 策略 | Full unit | Addon unit | Full package | 10 random unit stock-test | 10 random package stock-test | 生命週期違規 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in payload["strategies"]:
        lines.append(
            f"| {row['label']} | {unit_cell(row['summary']['full_units'])} | {unit_cell(row['summary']['addon_units'])} | {pkg_cell(row['summary']['full_packages'])} | {random_cell(row['random_unit_stock_test'], 'units')} | {random_cell(row['random_package_stock_test'], 'signals')} | {row['summary']['lifecycle_violations']} |"
        )
    lines.extend([
        "",
        f"Random unit 平均報酬最佳：{payload.get('best_by_random_unit_avg_return', {}).get('label', '-')}",
        f"Random package 60/10 達標次數最佳：{payload.get('best_by_random_package_pass', {}).get('label', '-')}",
    ])
    return "\n".join(lines) + "\n"


def main() -> None:
    strategies = collect_strategies()
    public_strategies = [strip_heavy(row) for row in strategies]
    payload = {
        "version": VERSION,
        "methodology": {
            "random_stock_splits": "10 seeds from analyze_pullback_plus_random_splits.SEEDS, stock-code 60/20/20 split, evaluate stock_test.",
            "corrected_addon_lifecycle": "Add-ons only while mother is open; 10-trading-day same-stock buy/buy-signal cooldown; unresolved or later-exiting add-ons are forced out on resolved mother exit; mother hard stop 7%; add-on catastrophic close line 15%.",
        },
        "strategies": public_strategies,
    }
    payload["best_by_random_unit_avg_return"] = max(public_strategies, key=lambda row: row["random_unit_stock_test"]["avg_return_pct"]["mean"])
    payload["best_by_random_package_pass"] = max(public_strategies, key=lambda row: (row["random_package_stock_test"]["pass_60win_10avg_count"], row["random_package_stock_test"]["avg_return_pct"]["mean"]))
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    OUT_MD.write_text(render_md(payload), encoding="utf-8")
    print(json.dumps({
        "version": VERSION,
        "strategies": [
            {
                "label": row["label"],
                "full_units": row["summary"]["full_units"],
                "addon_units": row["summary"]["addon_units"],
                "random_unit_stock_test": row["random_unit_stock_test"],
                "random_package_stock_test": row["random_package_stock_test"],
                "lifecycle_violations": row["summary"]["lifecycle_violations"],
            }
            for row in public_strategies
        ],
        "html": str(OUT_HTML),
        "json": str(OUT_JSON),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
