#!/usr/bin/env python3
"""Compare MWP-C mother entry gates: next-open direct vs next-open discount 2%."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

import analyze_pullback_pb_v23_independent_lifecycle as pbv23
from analyze_mwp_technical_filter_experiment import BASE_VARIANT, build_features, filter_record, ge
from analyze_pullback_discount2_swing import load_pullback_candidates

REPORT_DIR = Path("reports")
OUT_JSON = REPORT_DIR / "mwp_c_entry_gate_compare.json"
OUT_HTML = REPORT_DIR / "mwp_c_entry_gate_compare.html"
OUT_MD = REPORT_DIR / "mwp_c_entry_gate_compare.md"
VERSION = "MWP-C-entry-gate-compare"
ENTRY_DISCOUNT_PCT = 0.02


def lifecycle_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (str(row.get("market") or "").upper(), str(row.get("stock_no") or ""), str(row.get("signal_date") or ""))


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


def fmt_money(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    sign = "+" if number > 0 else ""
    return f"{sign}{number:,.0f}"


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
        f"p25 {pct(stats.get('avg_return_pct', {}).get('p25'))}"
    )


def load_raw_pullback_source_trades() -> list[dict[str, Any]]:
    items, _rows_by_source, _funnel = load_pullback_candidates()
    source_trades: list[dict[str, Any]] = []
    for item in items:
        source_trades.append({
            "signal_date": item.get("date"),
            "market": item.get("market"),
            "stock_no": item.get("stock_no"),
            "stock_name": item.get("stock_name"),
            "signal_close": item.get("close"),
            "reasons": item.get("reasons") or ([item.get("reason")] if item.get("reason") else []),
            "reason": item.get("reason"),
            "score": item.get("score"),
            "volume": item.get("volume"),
            "source": item.get("source"),
            "row_index": item.get("row_index"),
        })
    return source_trades


def simulate_raw_mwp_c() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[Any, Any]]:
    source_trades = load_raw_pullback_source_trades()
    series = pbv23.make_series_map(pbv23.csv_files())
    benchmark_rows = pbv23.read_rows(pbv23.BENCHMARK_CSV)
    benchmark_dates = {row.date: index for index, row in enumerate(benchmark_rows)}
    v8 = json.loads((REPORT_DIR / "pullback_pb_v8_multitimeframe_search.json").read_text(encoding="utf-8"))
    result = pbv23.simulate_variant(
        source_trades,
        series,
        benchmark_rows,
        benchmark_dates,
        v8["split"]["validation_start"],
        v8["split"]["test_start"],
        BASE_VARIANT,
    )
    return result["units"], result["packages"], series


def passes_next_open_discount(package: dict[str, Any]) -> bool:
    signal_close = package.get("signal_close")
    entry_price = package.get("entry_price")
    try:
        signal_close_value = float(signal_close)
        entry_price_value = float(entry_price)
    except (TypeError, ValueError):
        return False
    if signal_close_value <= 0 or entry_price_value <= 0:
        return False
    return entry_price_value <= signal_close_value * (1 - ENTRY_DISCOUNT_PCT)


def build_record(label: str, packages: list[dict[str, Any]], units: list[dict[str, Any]], features: dict[Any, Any], require_discount: bool) -> dict[str, Any]:
    slope_gate = ge("ma20_slope5_pct", 0)
    if require_discount:
        predicate = lambda package, current_features, current_units: passes_next_open_discount(package) and slope_gate(package, current_features, current_units)
    else:
        predicate = lambda package, current_features, current_units: slope_gate(package, current_features, current_units)
    return filter_record(label, packages, units, features, predicate)


def render_html(payload: dict[str, Any]) -> str:
    direct = payload["next_open_direct"]
    discount = payload["next_open_discount2"]
    delta = payload["delta"]
    return f"""<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{VERSION}</title><style>
:root{{--bg:#f6f7fb;--paper:#fff;--ink:#172033;--muted:#667085;--line:#e4e7ec;--blue:#2563eb}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 system-ui,'Microsoft JhengHei',sans-serif}}header,main{{max-width:1500px;margin:auto;padding:28px 20px}}header{{border-bottom:1px solid var(--line)}}h1{{margin:0 0 8px;font-size:30px}}h2{{margin:28px 0 10px}}p{{color:var(--muted)}}.note{{border-left:4px solid var(--blue);background:#eff6ff;padding:12px 14px;margin:18px 0;border-radius:12px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}}.card{{background:#fff;border:1px solid var(--line);border-radius:14px;padding:14px}}table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--line);border-radius:12px;overflow:hidden}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}thead th{{background:#f8fafc;color:var(--muted);font-size:12px}}code{{background:#eef2ff;padding:2px 6px;border-radius:6px}}</style></head><body><header><h1>MWP-C 進場條件比較</h1><p>同一套 MWP-C 規則下，只改母單進場條件，比較「隔天開盤直接進」與「隔天開盤需折價 2% 才進」。</p><div class='note'><strong>比較母體：</strong>從未加折價門檻的主升段回檔訊號母體開始，固定使用相同的 corrected-lifecycle MWP-C 規則：最多 1 筆加碼、MA20 回測帶 1.9%、母單 MA20 5 日斜率 &gt; 0、同股生命週期過濾與 10 日排除期。這次只改母單進場門檻。</div></header><main><div class='grid'><div class='card'><h3>隔天開盤直接進</h3><p>{html.escape(unit_cell(direct['summary']['full_units']))}</p><p>{html.escape(random_cell(direct['random_unit_stock_test']))}</p></div><div class='card'><h3>隔天開盤折價 2% 才進</h3><p>{html.escape(unit_cell(discount['summary']['full_units']))}</p><p>{html.escape(random_cell(discount['random_unit_stock_test']))}</p></div><div class='card'><h3>樣本差異</h3><p>units 差 {fmt_count(delta['full_units'])}</p><p>母單差 {fmt_count(delta['base_units'])}｜加碼差 {fmt_count(delta['addon_units'])}</p></div><div class='card'><h3>績效差異</h3><p>平均報酬差 {pct(delta['full_avg_return_pct'])}</p><p>總損益差 {fmt_money(delta['full_total_pnl'])}｜Random 平均差 {pct(delta['random_avg_return_pct'])}</p></div></div><h2>明細對照</h2><table><thead><tr><th>版本</th><th>Full units</th><th>Base units</th><th>Add-on units</th><th>Random unit stock-test</th><th>Random package stock-test</th></tr></thead><tbody><tr><td>隔天開盤直接進</td><td>{html.escape(unit_cell(direct['summary']['full_units']))}</td><td>{html.escape(unit_cell(direct['summary']['base_units']))}</td><td>{html.escape(unit_cell(direct['summary']['addon_units']))}</td><td>{html.escape(random_cell(direct['random_unit_stock_test']))}</td><td>{html.escape(random_cell(direct['random_package_stock_test'], 'signals'))}</td></tr><tr><td>隔天開盤折價 2% 才進</td><td>{html.escape(unit_cell(discount['summary']['full_units']))}</td><td>{html.escape(unit_cell(discount['summary']['base_units']))}</td><td>{html.escape(unit_cell(discount['summary']['addon_units']))}</td><td>{html.escape(random_cell(discount['random_unit_stock_test']))}</td><td>{html.escape(random_cell(discount['random_package_stock_test'], 'signals'))}</td></tr></tbody></table><p>JSON: <code>{OUT_JSON}</code>｜MD: <code>{OUT_MD}</code></p></main></body></html>"""


def render_md(payload: dict[str, Any]) -> str:
    direct = payload["next_open_direct"]
    discount = payload["next_open_discount2"]
    delta = payload["delta"]
    lines = [
        "# MWP-C 進場條件比較",
        "",
        "同一套 MWP-C 規則下，只改母單進場條件，比較「隔天開盤直接進」與「隔天開盤需折價 2% 才進」。",
        "",
        f"- 隔天開盤直接進：{unit_cell(direct['summary']['full_units'])}",
        f"- 隔天開盤直接進 random unit：{random_cell(direct['random_unit_stock_test'])}",
        f"- 隔天開盤折價 2% 才進：{unit_cell(discount['summary']['full_units'])}",
        f"- 隔天開盤折價 2% 才進 random unit：{random_cell(discount['random_unit_stock_test'])}",
        "",
        f"- units 差：{fmt_count(delta['full_units'])}",
        f"- 母單差：{fmt_count(delta['base_units'])}",
        f"- 加碼差：{fmt_count(delta['addon_units'])}",
        f"- 平均報酬差：{pct(delta['full_avg_return_pct'])}",
        f"- 總損益差：{fmt_money(delta['full_total_pnl'])}",
        f"- Random 平均報酬差：{pct(delta['random_avg_return_pct'])}",
        f"- Random p25 差：{pct(delta['random_p25_return_pct'])}",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    units, packages, series = simulate_raw_mwp_c()
    features = build_features(packages, series)
    direct = build_record("隔天開盤直接進", packages, units, features, require_discount=False)
    discount = build_record("隔天開盤折價 2% 才進", packages, units, features, require_discount=True)
    payload = {
        "version": VERSION,
        "methodology": {
            "signal_pool": "Raw main-uptrend pullback signal cohort before discount filtering.",
            "shared_rules": "Corrected-lifecycle MWP-C: max 1 add-on, MA20 retest band 1.9%, mother MA20 slope > 0, same-stock lifecycle filter, 10-trading-day same-stock exclusion, synchronized mother/add-on exits.",
        },
        "next_open_direct": direct,
        "next_open_discount2": discount,
        "delta": {
            "full_units": discount["summary"]["full_units"]["units"] - direct["summary"]["full_units"]["units"],
            "base_units": discount["summary"]["base_units"]["units"] - direct["summary"]["base_units"]["units"],
            "addon_units": discount["summary"]["addon_units"]["units"] - direct["summary"]["addon_units"]["units"],
            "full_avg_return_pct": round(float(discount["summary"]["full_units"]["avg_return_pct"]) - float(direct["summary"]["full_units"]["avg_return_pct"]), 4),
            "full_win_rate_pct": round(float(discount["summary"]["full_units"]["win_rate_pct"]) - float(direct["summary"]["full_units"]["win_rate_pct"]), 4),
            "full_total_pnl": round(float(discount["summary"]["full_units"]["total_pnl"]) - float(direct["summary"]["full_units"]["total_pnl"]), 2),
            "random_avg_return_pct": round(float(discount["random_unit_stock_test"]["avg_return_pct"]["mean"]) - float(direct["random_unit_stock_test"]["avg_return_pct"]["mean"]), 4),
            "random_p25_return_pct": round(float(discount["random_unit_stock_test"]["avg_return_pct"]["p25"]) - float(direct["random_unit_stock_test"]["avg_return_pct"]["p25"]), 4),
        },
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    OUT_MD.write_text(render_md(payload), encoding="utf-8")
    print(json.dumps({
        "version": VERSION,
        "next_open_direct": direct["summary"]["full_units"],
        "next_open_discount2": discount["summary"]["full_units"],
        "delta": payload["delta"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
