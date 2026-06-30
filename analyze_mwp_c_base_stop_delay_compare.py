#!/usr/bin/env python3
"""Compare MWP-C mother/base hard-stop timing: entry-day vs day+1 start."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Callable

import analyze_pullback_pb_v23_independent_lifecycle as pbv23
from analyze_mwp_technical_filter_experiment import BASE_VARIANT, build_features, filter_record, ge

REPORT_DIR = Path("reports")
OUT_JSON = REPORT_DIR / "mwp_c_base_stop_delay_compare.json"
OUT_HTML = REPORT_DIR / "mwp_c_base_stop_delay_compare.html"
OUT_MD = REPORT_DIR / "mwp_c_base_stop_delay_compare.md"
VERSION = "MWP-C-base-stop-delay-compare"


def lifecycle_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (str(row.get("market") or "").upper(), str(row.get("stock_no") or ""), str(row.get("signal_date") or ""))


def pct(value: Any) -> str:
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return "-"


def fmt_money(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    sign = "+" if number > 0 else ""
    return f"{sign}{number:,.0f}"


def fmt_count(value: Any) -> str:
    try:
        return str(int(round(float(value))))
    except (TypeError, ValueError):
        return "-"


def unit_cell(summary: dict[str, Any]) -> str:
    return (
        f"{summary.get('units', 0)}｜勝 {pct(summary.get('win_rate_pct'))}｜"
        f"均 {pct(summary.get('avg_return_pct'))}｜中 {pct(summary.get('median_return_pct'))}｜"
        f"損益 {fmt_money(summary.get('total_pnl'))}｜未 {summary.get('unresolved', 0)}"
    )


def random_cell(stats: dict[str, Any], count_key: str = "units") -> str:
    return (
        f"test均 {fmt_count(stats.get(count_key, {}).get('mean'))}｜"
        f"勝均 {pct(stats.get('win_rate_pct', {}).get('mean'))}｜"
        f"報酬均 {pct(stats.get('avg_return_pct', {}).get('mean'))}｜"
        f"p25 {pct(stats.get('avg_return_pct', {}).get('p25'))}"
    )


def base_exit_current(
    entry: pbv23.Row,
    rows: list[pbv23.Row],
    indicators: dict[str, list[float | None]],
    signal_index: int,
    entry_index: int,
    confirm_index: int | None,
) -> dict[str, Any]:
    return pbv23.independent_base_exit(entry, rows, indicators, signal_index, entry_index, confirm_index)


def base_exit_day_plus_one(
    entry: pbv23.Row,
    rows: list[pbv23.Row],
    indicators: dict[str, list[float | None]],
    signal_index: int,
    entry_index: int,
    confirm_index: int | None,
) -> dict[str, Any]:
    hard_stop = entry.open * (1 - pbv23.BASE_HARD_STOP_PCT)
    levels = pbv23.structural_levels(rows, signal_index, confirm_index) if confirm_index is not None else None
    observed: list[pbv23.Row] = []
    for cursor in range(entry_index, len(rows)):
        row = rows[cursor]
        observed.append(row)
        allow_hard_stop = cursor > entry_index
        if allow_hard_stop and row.open <= hard_stop:
            return pbv23.return_result(entry, observed, row.open, "base_gap_hard_stop7")
        if allow_hard_stop and row.low <= hard_stop:
            return pbv23.return_result(entry, observed, hard_stop, "base_hard_stop7")
        if levels is None or cursor <= confirm_index:
            continue
        ma20 = indicators["ma20"][cursor]
        if ma20 is None:
            continue
        if row.close <= entry.open * (1 - pbv23.STRUCTURAL_STOP["catastrophic_close_pct"]):
            return pbv23.close_execution_result(entry, observed, rows, cursor, "next_open", "base_catastrophic_close_stop")
        if row.close < ma20 and row.close < levels["structure_low"]:
            return pbv23.close_execution_result(entry, observed, rows, cursor, "next_open", "base_confluence_structure_close_break")
    return pbv23.return_result(entry, observed, observed[-1].close, "latest_close", unresolved=True)


def simulate_variant_with_base_exit(
    source_trades: list[dict[str, Any]],
    series: dict[tuple[str, str], tuple[list[pbv23.Row], dict[str, list[float | None]], dict[str, int]]],
    benchmark_rows: list[pbv23.Row],
    benchmark_dates: dict[str, int],
    validation_start: str,
    test_start: str,
    variant: dict[str, Any],
    exit_func: Callable[[pbv23.Row, list[pbv23.Row], dict[str, list[float | None]], int, int, int | None], dict[str, Any]],
) -> dict[str, Any]:
    source_trades, mother_lifecycle_diagnostics = pbv23.filter_source_trades_for_mother_lifecycle(
        source_trades, series, benchmark_rows, benchmark_dates
    )
    units: list[dict[str, Any]] = []
    packages: list[dict[str, Any]] = []
    for source in source_trades:
        bundle = pbv23.find_series(series, str(source["market"]), str(source["stock_no"]))
        if not bundle:
            continue
        rows, indicators, dates = bundle
        signal_index = dates.get(source["signal_date"])
        if signal_index is None or signal_index + 1 >= len(rows):
            continue
        base_entry_index = signal_index + 1
        base_entry = rows[base_entry_index]
        confirm_index, confirm_reason_text = pbv23.first_confirmation_index(
            rows, indicators, signal_index, base_entry_index, benchmark_rows, benchmark_dates
        )
        base_levels = pbv23.structural_levels(rows, signal_index, confirm_index) if confirm_index is not None else {}
        base_exit = exit_func(base_entry, rows, indicators, signal_index, base_entry_index, confirm_index)
        base_unit = {
            **source,
            "variant": variant["id"],
            "unit_type": "base",
            "entry_date": base_entry.date,
            "entry_price": round(base_entry.open, 4),
            "confirm_date": rows[confirm_index].date if confirm_index is not None else None,
            "confirm_close": round(rows[confirm_index].close, 4) if confirm_index is not None else None,
            "confirm_reason": confirm_reason_text,
            "confirm_low": round(base_levels.get("confirm_low"), 4) if base_levels else None,
            "pullback_low": round(base_levels.get("pullback_low"), 4) if base_levels else None,
            "structure_low": round(base_levels.get("structure_low"), 4) if base_levels else None,
            **base_exit,
        }
        pbv23.add_benchmark_return(base_unit, benchmark_rows, benchmark_dates)
        units.append(base_unit)

        base_exit_index = dates.get(str(base_unit.get("exit_date")), len(rows) - 1)
        addon_units = pbv23.scan_addons(
            source,
            rows,
            indicators,
            dates,
            signal_index,
            base_entry_index,
            benchmark_rows,
            benchmark_dates,
            variant,
            base_exit_index,
            base_unit,
        )
        units.extend(addon_units)
        total_pnl = base_unit["pnl"] + sum(row["pnl"] for row in addon_units)
        total_units = 1 + len(addon_units)
        packages.append({
            **source,
            "variant": variant["id"],
            "base_return_pct": base_unit["return_pct"],
            "base_exit_date": base_unit["exit_date"],
            "base_exit_reason": base_unit["exit_reason"],
            "addon_count": len(addon_units),
            "addon_added": bool(addon_units),
            "total_units": total_units,
            "total_capital": total_units * pbv23.POSITION_SIZE,
            "total_pnl": total_pnl,
            "package_return_pct": round(total_pnl / (total_units * pbv23.POSITION_SIZE) * 100, 2),
            "unresolved": bool(base_unit.get("unresolved")) or any(row.get("unresolved") for row in addon_units),
        })
    return {
        "units": units,
        "packages": packages,
        "mother_lifecycle_filter": mother_lifecycle_diagnostics,
    }


def build_selected_record(label: str, variant: dict[str, Any], exit_func: Callable[..., dict[str, Any]]) -> dict[str, Any]:
    source_trades = json.loads(pbv23.PBV4_JSON.read_text(encoding="utf-8"))["trades"]
    series = pbv23.make_series_map(pbv23.csv_files())
    benchmark_rows = pbv23.read_rows(pbv23.BENCHMARK_CSV)
    benchmark_dates = {row.date: index for index, row in enumerate(benchmark_rows)}
    v8 = json.loads((REPORT_DIR / "pullback_pb_v8_multitimeframe_search.json").read_text(encoding="utf-8"))
    result = simulate_variant_with_base_exit(
        source_trades,
        series,
        benchmark_rows,
        benchmark_dates,
        v8["split"]["validation_start"],
        v8["split"]["test_start"],
        variant,
        exit_func,
    )
    features = build_features(result["packages"], series)
    record = filter_record(label, result["packages"], result["units"], features, ge("ma20_slope5_pct", 0))
    record["mother_lifecycle_filter"] = result["mother_lifecycle_filter"]
    return record


def stop_stats(record: dict[str, Any]) -> dict[str, Any]:
    base_units = [row for row in record["units"] if row.get("unit_type") == "base"]
    stop_rows = [row for row in base_units if "hard_stop" in str(row.get("exit_reason") or "")]
    same_day_rows = [row for row in stop_rows if str(row.get("entry_date")) == str(row.get("exit_date"))]
    return {
        "base_unit_count": len(base_units),
        "stop_count": len(stop_rows),
        "stop_pnl_total": round(sum(float(row.get("pnl") or 0) for row in stop_rows), 2),
        "stop_avg_return_pct": round(sum(float(row.get("return_pct") or 0) for row in stop_rows) / len(stop_rows), 2) if stop_rows else None,
        "same_day_stop_count": len(same_day_rows),
        "same_day_stop_pnl_total": round(sum(float(row.get("pnl") or 0) for row in same_day_rows), 2),
        "same_day_stop_stock_labels": [str(row.get("label") or row.get("stock_no") or "") for row in same_day_rows[:20]],
    }


def changed_base_outcomes(current: dict[str, Any], delayed: dict[str, Any]) -> dict[str, Any]:
    current_map = {lifecycle_key(row): row for row in current["units"] if row.get("unit_type") == "base"}
    delayed_map = {lifecycle_key(row): row for row in delayed["units"] if row.get("unit_type") == "base"}
    changed = []
    for key, current_row in current_map.items():
        delayed_row = delayed_map.get(key)
        if not delayed_row:
            continue
        if (
            str(current_row.get("exit_date")) != str(delayed_row.get("exit_date"))
            or str(current_row.get("exit_reason")) != str(delayed_row.get("exit_reason"))
            or float(current_row.get("pnl") or 0) != float(delayed_row.get("pnl") or 0)
        ):
            changed.append({
                "label": current_row.get("label"),
                "market": current_row.get("market"),
                "stock_no": current_row.get("stock_no"),
                "signal_date": current_row.get("signal_date"),
                "entry_date": current_row.get("entry_date"),
                "current_exit_date": current_row.get("exit_date"),
                "current_exit_reason": current_row.get("exit_reason"),
                "current_pnl": current_row.get("pnl"),
                "current_return_pct": current_row.get("return_pct"),
                "delayed_exit_date": delayed_row.get("exit_date"),
                "delayed_exit_reason": delayed_row.get("exit_reason"),
                "delayed_pnl": delayed_row.get("pnl"),
                "delayed_return_pct": delayed_row.get("return_pct"),
                "pnl_delta": round(float(delayed_row.get("pnl") or 0) - float(current_row.get("pnl") or 0), 2),
            })
    changed.sort(key=lambda row: float(row.get("pnl_delta") or 0), reverse=True)
    return {
        "count": len(changed),
        "improved_count": sum(float(row.get("pnl_delta") or 0) > 0 for row in changed),
        "worsened_count": sum(float(row.get("pnl_delta") or 0) < 0 for row in changed),
        "total_pnl_delta": round(sum(float(row.get("pnl_delta") or 0) for row in changed), 2),
        "rows": changed,
    }


def render_html(payload: dict[str, Any]) -> str:
    current = payload["current_rule"]
    delayed = payload["delay_rule"]
    delta = payload["delta"]
    changed_rows = "".join(
        f"<tr><td>{html.escape(str(row['label']))}</td><td>{html.escape(str(row['signal_date']))}</td>"
        f"<td>{html.escape(str(row['current_exit_reason']))}<br><small>{html.escape(str(row['current_exit_date']))}</small></td>"
        f"<td>{html.escape(str(row['delayed_exit_reason']))}<br><small>{html.escape(str(row['delayed_exit_date']))}</small></td>"
        f"<td>{fmt_money(row['current_pnl'])}</td><td>{fmt_money(row['delayed_pnl'])}</td><td>{fmt_money(row['pnl_delta'])}</td></tr>"
        for row in payload["changed_base_outcomes"]["rows"][:40]
    )
    return f"""<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{VERSION}</title><style>
:root{{--bg:#f6f7fb;--paper:#fff;--ink:#172033;--muted:#667085;--line:#e4e7ec;--blue:#2563eb}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 system-ui,'Microsoft JhengHei',sans-serif}}header,main{{max-width:1600px;margin:auto;padding:28px 20px}}header{{border-bottom:1px solid var(--line)}}h1{{margin:0 0 8px;font-size:30px}}h2{{margin:28px 0 10px}}p{{color:var(--muted)}}.note{{border-left:4px solid var(--blue);background:#eff6ff;padding:12px 14px;margin:18px 0;border-radius:12px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}}.card{{background:#fff;border:1px solid var(--line);border-radius:14px;padding:14px}}.table{{overflow:auto;border:1px solid var(--line);background:#fff;border-radius:12px;margin:18px 0}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}thead th{{background:#f8fafc;color:var(--muted);font-size:12px}}code{{background:#eef2ff;padding:2px 6px;border-radius:6px}}</style></head><body><header><h1>MWP-C 母單停損時點比較</h1><p>比較目前規則「母單進場當天就允許 7% 停損」與實驗規則「母單從下一個交易日才開始允許 7% 停損」。</p><div class='note'><strong>進場機制確認：</strong>正式 MWP-C 回測是用 <code>PB-V4 discount-2 已通過的母單池</code> 作為來源，再用 <code>訊號後次日開盤價</code> 重建母單進場；不是再額外做一次新的隔日開低 2% 掛單回放。每日 forward 追蹤頁才有「次日開盤需低於訊號日收盤 2%」的正式追蹤門檻。</div></header><main><h2>整體比較</h2><div class='grid'><div class='card'><h3>現行規則</h3><p>{html.escape(unit_cell(current['summary']['full_units']))}</p><p>{html.escape(random_cell(current['random_unit_stock_test']))}</p></div><div class='card'><h3>延後停損規則</h3><p>{html.escape(unit_cell(delayed['summary']['full_units']))}</p><p>{html.escape(random_cell(delayed['random_unit_stock_test']))}</p></div><div class='card'><h3>總損益差</h3><p>{fmt_money(delta['full_total_pnl'])}</p><p>平均報酬差 {pct(delta['full_avg_return_pct'])}｜Random 平均差 {pct(delta['random_avg_return_pct'])}</p></div><div class='card'><h3>停損差異</h3><p>母單停損筆數 {fmt_count(delta['stop_count'])}</p><p>母單停損金額 {fmt_money(delta['stop_pnl_total'])}｜同日停損筆數 {fmt_count(delta['same_day_stop_count'])}</p></div></div><h2>母單停損統計</h2><div class='table'><table><thead><tr><th>版本</th><th>母單數</th><th>母單停損筆數</th><th>母單停損總金額</th><th>母單停損平均報酬</th><th>當天進當天停損筆數</th><th>當天進當天停損總金額</th></tr></thead><tbody><tr><td>現行規則</td><td>{current['stop_stats']['base_unit_count']}</td><td>{current['stop_stats']['stop_count']}</td><td>{fmt_money(current['stop_stats']['stop_pnl_total'])}</td><td>{pct(current['stop_stats']['stop_avg_return_pct'])}</td><td>{current['stop_stats']['same_day_stop_count']}</td><td>{fmt_money(current['stop_stats']['same_day_stop_pnl_total'])}</td></tr><tr><td>延後停損規則</td><td>{delayed['stop_stats']['base_unit_count']}</td><td>{delayed['stop_stats']['stop_count']}</td><td>{fmt_money(delayed['stop_stats']['stop_pnl_total'])}</td><td>{pct(delayed['stop_stats']['stop_avg_return_pct'])}</td><td>{delayed['stop_stats']['same_day_stop_count']}</td><td>{fmt_money(delayed['stop_stats']['same_day_stop_pnl_total'])}</td></tr></tbody></table></div><h2>被改寫的母單結果</h2><div class='note'>共有 {payload['changed_base_outcomes']['count']} 筆母單結果改變，其中改善 {payload['changed_base_outcomes']['improved_count']} 筆、惡化 {payload['changed_base_outcomes']['worsened_count']} 筆，合計損益差 {fmt_money(payload['changed_base_outcomes']['total_pnl_delta'])}。</div><div class='table'><table><thead><tr><th>股票</th><th>訊號日</th><th>現行出場</th><th>延後出場</th><th>現行損益</th><th>延後損益</th><th>差額</th></tr></thead><tbody>{changed_rows}</tbody></table></div><p>JSON: <code>{OUT_JSON}</code>｜MD: <code>{OUT_MD}</code></p></main></body></html>"""


def render_md(payload: dict[str, Any]) -> str:
    current = payload["current_rule"]
    delayed = payload["delay_rule"]
    delta = payload["delta"]
    lines = [
        "# MWP-C 母單停損時點比較",
        "",
        "進場機制確認：正式 MWP-C 回測是用 `PB-V4 discount-2 已通過的母單池` 作為來源，再用 `訊號後次日開盤價` 重建母單進場；每日 forward 追蹤頁才有次日開盤需低於訊號日收盤 2% 的正式追蹤門檻。",
        "",
        "## 整體比較",
        "",
        f"- 現行規則：{unit_cell(current['summary']['full_units'])}",
        f"- 現行規則 random unit：{random_cell(current['random_unit_stock_test'])}",
        f"- 延後停損規則：{unit_cell(delayed['summary']['full_units'])}",
        f"- 延後停損規則 random unit：{random_cell(delayed['random_unit_stock_test'])}",
        f"- 總損益差：{fmt_money(delta['full_total_pnl'])}",
        f"- 平均報酬差：{pct(delta['full_avg_return_pct'])}",
        f"- Random 平均報酬差：{pct(delta['random_avg_return_pct'])}",
        "",
        "## 母單停損統計",
        "",
        f"- 現行規則：母單 {current['stop_stats']['base_unit_count']} 筆；停損 {current['stop_stats']['stop_count']} 筆；停損總金額 {fmt_money(current['stop_stats']['stop_pnl_total'])}；同日停損 {current['stop_stats']['same_day_stop_count']} 筆。",
        f"- 延後停損規則：母單 {delayed['stop_stats']['base_unit_count']} 筆；停損 {delayed['stop_stats']['stop_count']} 筆；停損總金額 {fmt_money(delayed['stop_stats']['stop_pnl_total'])}；同日停損 {delayed['stop_stats']['same_day_stop_count']} 筆。",
        f"- 變化：停損筆數 {fmt_count(delta['stop_count'])}；停損總金額 {fmt_money(delta['stop_pnl_total'])}；同日停損筆數 {fmt_count(delta['same_day_stop_count'])}。",
        "",
        f"改寫的母單結果共 {payload['changed_base_outcomes']['count']} 筆，改善 {payload['changed_base_outcomes']['improved_count']} 筆，惡化 {payload['changed_base_outcomes']['worsened_count']} 筆，損益差合計 {fmt_money(payload['changed_base_outcomes']['total_pnl_delta'])}。",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    current = build_selected_record("現行規則：母單當天可觸發 7% 停損", BASE_VARIANT, base_exit_current)
    delayed = build_selected_record("比較規則：母單從下一交易日才開始 7% 停損", BASE_VARIANT, base_exit_day_plus_one)
    current["stop_stats"] = stop_stats(current)
    delayed["stop_stats"] = stop_stats(delayed)
    changed = changed_base_outcomes(current, delayed)
    payload = {
        "version": VERSION,
        "entry_mechanism_note": "Formal MWP-C backtest rebuilds entry at signal_date + 1 open from the PB-V4 discount-2-qualified source trade pool; daily forward tracking separately applies a next-open <= signal_close * 0.98 gate.",
        "current_rule": current,
        "delay_rule": delayed,
        "delta": {
            "full_total_pnl": round(float(delayed["summary"]["full_units"]["total_pnl"]) - float(current["summary"]["full_units"]["total_pnl"]), 2),
            "full_avg_return_pct": round(float(delayed["summary"]["full_units"]["avg_return_pct"]) - float(current["summary"]["full_units"]["avg_return_pct"]), 4),
            "full_win_rate_pct": round(float(delayed["summary"]["full_units"]["win_rate_pct"]) - float(current["summary"]["full_units"]["win_rate_pct"]), 4),
            "random_avg_return_pct": round(float(delayed["random_unit_stock_test"]["avg_return_pct"]["mean"]) - float(current["random_unit_stock_test"]["avg_return_pct"]["mean"]), 4),
            "random_p25_return_pct": round(float(delayed["random_unit_stock_test"]["avg_return_pct"]["p25"]) - float(current["random_unit_stock_test"]["avg_return_pct"]["p25"]), 4),
            "stop_count": delayed["stop_stats"]["stop_count"] - current["stop_stats"]["stop_count"],
            "stop_pnl_total": round(float(delayed["stop_stats"]["stop_pnl_total"]) - float(current["stop_stats"]["stop_pnl_total"]), 2),
            "same_day_stop_count": delayed["stop_stats"]["same_day_stop_count"] - current["stop_stats"]["same_day_stop_count"],
            "same_day_stop_pnl_total": round(float(delayed["stop_stats"]["same_day_stop_pnl_total"]) - float(current["stop_stats"]["same_day_stop_pnl_total"]), 2),
        },
        "changed_base_outcomes": changed,
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    OUT_MD.write_text(render_md(payload), encoding="utf-8")
    print(json.dumps({
        "version": VERSION,
        "current_full": current["summary"]["full_units"],
        "delayed_full": delayed["summary"]["full_units"],
        "current_stop_stats": current["stop_stats"],
        "delayed_stop_stats": delayed["stop_stats"],
        "delta": payload["delta"],
        "changed_base_outcomes": {
            "count": changed["count"],
            "improved_count": changed["improved_count"],
            "worsened_count": changed["worsened_count"],
            "total_pnl_delta": changed["total_pnl_delta"],
        },
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
