#!/usr/bin/env python3
"""PB-V20: fuzzy add-on timing and tighter add-on stops."""

from __future__ import annotations

import hashlib
import html
import json
import statistics
from pathlib import Path
from typing import Any

from analyze_pullback_multitimeframe_search import BENCHMARK_CSV, PBV4_JSON, add_benchmark_return
from analyze_pullback_pb_v19_main_wave_addon import (
    POSITION_SIZE,
    confirmation_reason,
    gap_aware_ma20_core_exit,
    source_base_exit,
    stock_key,
    summarize_packages,
    summarize_units,
    unit_pnl,
)
from analyze_pullback_technical_phenotypes import find_series, make_series_map
from run_market_backtest import Row, csv_files, read_rows


REPORT_DIR = Path("reports")
OUT_JSON = REPORT_DIR / "pullback_pb_v20_fuzzy_addon.json"
OUT_HTML = REPORT_DIR / "pullback_pb_v20_fuzzy_addon.html"
VERSION = "PB-V20.0-fuzzy-addon"

VARIANTS = [
    {
        "id": "v19_immediate_stop7_once",
        "label": "V19 原始立即加碼",
        "entry_policy": "immediate",
        "stop_pct": 0.07,
        "max_addons": 1,
        "delay_days": 0,
        "min_wait": 0,
        "max_wait": 0,
        "ma20_band_pct": None,
        "min_spacing": 999,
    },
    {
        "id": "delay2_stop5_max3",
        "label": "延後2日確認，停損5%，最多3次",
        "entry_policy": "delay",
        "stop_pct": 0.05,
        "max_addons": 3,
        "delay_days": 2,
        "min_wait": 0,
        "max_wait": 0,
        "ma20_band_pct": None,
        "min_spacing": 5,
    },
    {
        "id": "delay3_stop4_max3",
        "label": "延後3日確認，停損4%，最多3次",
        "entry_policy": "delay",
        "stop_pct": 0.04,
        "max_addons": 3,
        "delay_days": 3,
        "min_wait": 0,
        "max_wait": 0,
        "ma20_band_pct": None,
        "min_spacing": 5,
    },
    {
        "id": "retest_ma20_stop5_max3",
        "label": "確認後等MA20附近回測，停損5%，最多3次",
        "entry_policy": "retest",
        "stop_pct": 0.05,
        "max_addons": 3,
        "delay_days": 0,
        "min_wait": 2,
        "max_wait": 8,
        "ma20_band_pct": 0.06,
        "min_spacing": 5,
    },
    {
        "id": "retest_ma20_stop4_max3",
        "label": "確認後等MA20附近回測，停損4%，最多3次",
        "entry_policy": "retest",
        "stop_pct": 0.04,
        "max_addons": 3,
        "delay_days": 0,
        "min_wait": 2,
        "max_wait": 8,
        "ma20_band_pct": 0.06,
        "min_spacing": 5,
    },
    {
        "id": "delay2_retest_stop5_max3",
        "label": "延後2日或回測MA20，停損5%，最多3次",
        "entry_policy": "delay_or_retest",
        "stop_pct": 0.05,
        "max_addons": 3,
        "delay_days": 2,
        "min_wait": 2,
        "max_wait": 8,
        "ma20_band_pct": 0.06,
        "min_spacing": 5,
    },
]


def addon_exit(
    entry: Row,
    rows: list[Row],
    indicators: dict[str, list[float | None]],
    entry_index: int,
    stop_pct: float,
) -> dict[str, Any]:
    hard_stop = entry.open * (1 - stop_pct)
    observed: list[Row] = []
    for cursor in range(entry_index, len(rows)):
        row = rows[cursor]
        observed.append(row)
        if row.open <= hard_stop:
            ret = round((row.open / entry.open - 1) * 100, 2)
            return {
                "exit_date": row.date,
                "exit_price": round(row.open, 4),
                "holding_days": len(observed),
                "return_pct": ret,
                "pnl": unit_pnl(ret),
                "exit_reason": "gap_tight_stop",
                "unresolved": False,
            }
        if row.low <= hard_stop:
            ret = round((hard_stop / entry.open - 1) * 100, 2)
            return {
                "exit_date": row.date,
                "exit_price": round(hard_stop, 4),
                "holding_days": len(observed),
                "return_pct": ret,
                "pnl": unit_pnl(ret),
                "exit_reason": "tight_stop",
                "unresolved": False,
            }
        ma20 = indicators["ma20"][cursor]
        prior_ma20 = indicators["ma20"][cursor - 3] if cursor >= 3 else None
        if len(observed) >= 6 and ma20 and prior_ma20 and row.close < ma20 and ma20 <= prior_ma20:
            ret = round((row.close / entry.open - 1) * 100, 2)
            return {
                "exit_date": row.date,
                "exit_price": round(row.close, 4),
                "holding_days": len(observed),
                "return_pct": ret,
                "pnl": unit_pnl(ret),
                "exit_reason": "ma20_trend_break",
                "unresolved": False,
            }
    ret = round((observed[-1].close / entry.open - 1) * 100, 2)
    return {
        "exit_date": observed[-1].date,
        "exit_price": round(observed[-1].close, 4),
        "holding_days": len(observed),
        "return_pct": ret,
        "pnl": unit_pnl(ret),
        "exit_reason": "latest_close",
        "unresolved": True,
    }


def survives_delay(
    rows: list[Row],
    indicators: dict[str, list[float | None]],
    confirm_index: int,
    delay_days: int,
) -> bool:
    confirm_low = rows[confirm_index].low
    for cursor in range(confirm_index + 1, confirm_index + delay_days + 1):
        ma20 = indicators["ma20"][cursor]
        if ma20 is None:
            return False
        if rows[cursor].close < ma20 or rows[cursor].close < confirm_low:
            return False
    return True


def retest_ok(
    rows: list[Row],
    indicators: dict[str, list[float | None]],
    cursor: int,
    ma20_band_pct: float,
) -> bool:
    ma20 = indicators["ma20"][cursor]
    if ma20 is None:
        return False
    close = rows[cursor].close
    if close < ma20:
        return False
    if close / ma20 - 1 > ma20_band_pct:
        return False
    return rows[cursor].low <= ma20 * (1 + ma20_band_pct)


def find_entry_after_confirmation(
    rows: list[Row],
    indicators: dict[str, list[float | None]],
    confirm_index: int,
    base_exit_index: int,
    variant: dict[str, Any],
) -> dict[str, Any] | None:
    last_index = min(base_exit_index - 1, len(rows) - 2)
    policy = variant["entry_policy"]
    candidates: list[dict[str, Any]] = []
    if policy == "immediate":
        if confirm_index + 1 <= last_index + 1:
            candidates.append({
                "entry_index": confirm_index + 1,
                "entry_trigger_date": rows[confirm_index].date,
                "entry_trigger_type": "immediate",
            })
    if policy in {"delay", "delay_or_retest"}:
        delay_cursor = confirm_index + int(variant["delay_days"])
        if delay_cursor <= last_index and survives_delay(rows, indicators, confirm_index, int(variant["delay_days"])):
            candidates.append({
                "entry_index": delay_cursor + 1,
                "entry_trigger_date": rows[delay_cursor].date,
                "entry_trigger_type": f"delay{variant['delay_days']}",
            })
    if policy in {"retest", "delay_or_retest"}:
        for cursor in range(confirm_index + int(variant["min_wait"]), min(confirm_index + int(variant["max_wait"]), last_index) + 1):
            if retest_ok(rows, indicators, cursor, float(variant["ma20_band_pct"])):
                candidates.append({
                    "entry_index": cursor + 1,
                    "entry_trigger_date": rows[cursor].date,
                    "entry_trigger_type": "ma20_retest",
                })
                break
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: item["entry_index"])[0]


def find_next_addon(
    rows: list[Row],
    indicators: dict[str, list[float | None]],
    signal_index: int,
    base_entry_index: int,
    scan_start: int,
    base_exit_index: int,
    benchmark_rows: list[Row],
    benchmark_dates: dict[str, int],
    variant: dict[str, Any],
) -> dict[str, Any] | None:
    last_confirm = min(base_exit_index - 1, len(rows) - 2)
    for cursor in range(scan_start, last_confirm + 1):
        reason = confirmation_reason(
            rows, indicators, signal_index, base_entry_index, cursor, benchmark_rows, benchmark_dates
        )
        if not reason:
            continue
        entry = find_entry_after_confirmation(rows, indicators, cursor, base_exit_index, variant)
        if not entry:
            continue
        return {
            "confirm_date": rows[cursor].date,
            "confirm_close": round(rows[cursor].close, 4),
            "confirm_reason": reason,
            **entry,
            "addon_entry_date": rows[entry["entry_index"]].date,
            "addon_entry_price": round(rows[entry["entry_index"]].open, 4),
        }
    return None


def split_chronological(rows: list[dict[str, Any]], validation_start: str, test_start: str) -> dict[str, list[dict[str, Any]]]:
    return {
        "train": [row for row in rows if row["signal_date"] < validation_start],
        "validation": [row for row in rows if validation_start <= row["signal_date"] < test_start],
        "test": [row for row in rows if row["signal_date"] >= test_start],
        "full": rows,
        "resolved_full": [row for row in rows if not row.get("unresolved")],
    }


def split_stocks(rows: list[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
    stocks = sorted({stock_key(row) for row in rows})
    ranked = sorted(stocks, key=lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest())
    train_end = round(len(ranked) * 0.60)
    validation_end = round(len(ranked) * 0.80)
    groups = {
        "stock_train": set(ranked[:train_end]),
        "stock_validation": set(ranked[train_end:validation_end]),
        "stock_test": set(ranked[validation_end:]),
    }
    return (
        {name: [row for row in rows if stock_key(row) in symbols] for name, symbols in groups.items()},
        {name: len(symbols) for name, symbols in groups.items()},
    )


def simulate_variant(
    source_trades: list[dict[str, Any]],
    series: dict[tuple[str, str], tuple[list[Row], dict[str, list[float | None]], dict[str, int]]],
    benchmark_rows: list[Row],
    benchmark_dates: dict[str, int],
    validation_start: str,
    test_start: str,
    variant: dict[str, Any],
) -> dict[str, Any]:
    units: list[dict[str, Any]] = []
    packages: list[dict[str, Any]] = []
    for source in source_trades:
        bundle = find_series(series, str(source["market"]), str(source["stock_no"]))
        if not bundle:
            continue
        rows, indicators, dates = bundle
        signal_index = dates.get(source["signal_date"])
        if signal_index is None or signal_index + 1 >= len(rows):
            continue
        base_entry_index = signal_index + 1
        base_entry = rows[base_entry_index]
        base_exit = source_base_exit(source)
        base_exit_index = dates.get(base_exit["exit_date"], len(rows) - 1)
        base_unit = {
            **source,
            "variant": variant["id"],
            "unit_type": "base",
            "entry_date": base_entry.date,
            "entry_price": round(base_entry.open, 4),
            **base_exit,
        }
        add_benchmark_return(base_unit, benchmark_rows, benchmark_dates)
        units.append(base_unit)

        addon_units = []
        scan_start = base_entry_index
        for addon_number in range(1, int(variant["max_addons"]) + 1):
            addon = find_next_addon(
                rows,
                indicators,
                signal_index,
                base_entry_index,
                scan_start,
                base_exit_index,
                benchmark_rows,
                benchmark_dates,
                variant,
            )
            if not addon:
                break
            entry_index = addon["entry_index"]
            addon_entry = rows[entry_index]
            exit_data = addon_exit(
                addon_entry, rows, indicators, entry_index, float(variant["stop_pct"])
            )
            unit = {
                **source,
                "variant": variant["id"],
                "unit_type": "addon",
                "addon_number": addon_number,
                "entry_date": addon_entry.date,
                "entry_price": round(addon_entry.open, 4),
                **addon,
                **exit_data,
            }
            add_benchmark_return(unit, benchmark_rows, benchmark_dates)
            units.append(unit)
            addon_units.append(unit)
            scan_start = entry_index + int(variant["min_spacing"])

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
            "total_capital": total_units * POSITION_SIZE,
            "total_pnl": total_pnl,
            "package_return_pct": round(total_pnl / (total_units * POSITION_SIZE) * 100, 2),
            "unresolved": bool(base_unit.get("unresolved")) or any(row.get("unresolved") for row in addon_units),
        })

    chrono_units = split_chronological(units, validation_start, test_start)
    chrono_packages = split_chronological(packages, validation_start, test_start)
    stock_units, stock_counts = split_stocks(units)
    stock_packages, package_stock_counts = split_stocks(packages)
    addons = [row for row in units if row["unit_type"] == "addon"]
    return {
        "variant": variant,
        "summaries": {
            "chronological_unit": {name: summarize_units(rows) for name, rows in chrono_units.items()},
            "chronological_package": {name: summarize_packages(rows) for name, rows in chrono_packages.items()},
            "stock_unit": {name: summarize_units(rows) for name, rows in stock_units.items()},
            "stock_package": {name: summarize_packages(rows) for name, rows in stock_packages.items()},
            "base_units": summarize_units([row for row in units if row["unit_type"] == "base"]),
            "addon_units": summarize_units(addons),
            "stock_counts": stock_counts,
            "package_stock_counts": package_stock_counts,
        },
        "units": units,
        "packages": packages,
    }


def run() -> dict[str, Any]:
    source_trades = json.loads(PBV4_JSON.read_text(encoding="utf-8"))["trades"]
    series = make_series_map(csv_files())
    benchmark_rows = read_rows(BENCHMARK_CSV)
    benchmark_dates = {row.date: index for index, row in enumerate(benchmark_rows)}
    v8 = json.loads((REPORT_DIR / "pullback_pb_v8_multitimeframe_search.json").read_text(encoding="utf-8"))
    validation_start = v8["split"]["validation_start"]
    test_start = v8["split"]["test_start"]
    variants = [
        simulate_variant(source_trades, series, benchmark_rows, benchmark_dates, validation_start, test_start, variant)
        for variant in VARIANTS
    ]
    return {
        "version": VERSION,
        "methodology": {
            "base": "PB-V4 broad discount-2 pullback base unit, one TWD 100,000 unit each",
            "addon": "one or more TWD 100,000 add-on units after main-wave confirmation, depending on variant",
            "fuzzy_timing": "variants compare immediate entry, delayed confirmation survival, MA20 retest entry, and delay-or-retest entry",
            "tighter_stops": "add-on stops are tested at 7%, 5%, and 4%; base remains original PB-V4 swing exit",
            "validation": "both chronological forward slices and stock-level 60/20/20 holdout are reported",
        },
        "split": {"validation_start": validation_start, "test_start": test_start},
        "variants": variants,
    }


def compact(summary: dict[str, Any], key: str = "units") -> str:
    return (
        f"{summary.get(key, 0)}｜勝率 {summary['win_rate_pct']:.2f}%｜"
        f"平均 {summary['avg_return_pct']:.2f}%｜中位 {summary['median_return_pct']:.2f}%｜"
        f"損益 {summary['total_pnl']:,.0f}"
    )


def render_html(payload: dict[str, Any]) -> str:
    ranked = sorted(
        payload["variants"],
        key=lambda item: (
            item["summaries"]["stock_unit"]["stock_test"]["avg_return_pct"],
            item["summaries"]["stock_unit"]["stock_test"]["win_rate_pct"],
        ),
        reverse=True,
    )
    summary_rows = "".join(
        f"<tr><th>{html.escape(item['variant']['label'])}</th>"
        f"<td>{html.escape(compact(item['summaries']['chronological_unit']['full']))}</td>"
        f"<td>{html.escape(compact(item['summaries']['stock_unit']['stock_test']))}</td>"
        f"<td>{html.escape(compact(item['summaries']['addon_units']))}</td>"
        f"<td>{item['variant']['max_addons']}</td><td>{item['variant']['stop_pct'] * 100:.0f}%</td></tr>"
        for item in ranked
    )
    best = ranked[0]
    top_addons = sorted(
        [row for row in best["units"] if row["unit_type"] == "addon"],
        key=lambda row: row["return_pct"],
        reverse=True,
    )[:30]
    addon_rows = "".join(
        f"<tr><td>{row['signal_date']}</td><td>{html.escape(str(row['stock_no']) + ' ' + str(row['stock_name']))}</td>"
        f"<td>{row['confirm_date']}</td><td>{row.get('entry_trigger_date')}</td><td>{row['entry_date']}</td>"
        f"<td>{html.escape(row.get('entry_trigger_type') or '')}</td>"
        f"<td class=\"num {'pos' if row['return_pct'] > 0 else 'neg'}\">{row['return_pct']:.2f}%</td>"
        f"<td>{row['exit_date']}</td><td>{html.escape(row['exit_reason'])}</td></tr>"
        for row in top_addons
    )
    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PB-V20 模糊加碼測試</title><style>
:root{{--bg:#f6f7f4;--paper:#fff;--ink:#17211d;--muted:#65716b;--line:#dfe5df;--good:#08735d;--bad:#a13e34;--accent:#1f6a73}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 system-ui,"Microsoft JhengHei",sans-serif}}header,main{{max-width:1500px;margin:auto;padding:24px 16px}}header{{border-bottom:1px solid var(--line)}}h1{{margin:0 0 8px;font-size:28px}}h2{{font-size:19px;margin:28px 0 10px}}p{{margin:6px 0;color:var(--muted)}}.cards{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1px;background:var(--line);border:1px solid var(--line);margin-top:20px}}.card{{background:var(--paper);padding:16px}}.card b{{display:block;font-size:20px}}.note{{margin-top:16px;background:#ecf3f2;border-left:4px solid var(--accent);padding:12px 14px}}.table{{overflow:auto;border:1px solid var(--line);background:var(--paper)}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}thead th{{background:#eef1ee;color:var(--muted);font-size:12px}}.num{{text-align:right}}.pos{{color:var(--good);font-weight:800}}.neg{{color:var(--bad);font-weight:800}}code{{background:#eef1ee;padding:1px 4px;border-radius:4px}}@media(max-width:900px){{.cards{{grid-template-columns:1fr}}}}
</style></head><body><header><h1>PB-V20 模糊加碼測試</h1><p>底倉維持 PB-V4，全訊號一份 100,000；加碼測試延後確認、等待 MA20 回測、停損縮緊，以及最多加碼 3 次。</p><div class="cards"><div class="card"><span>股票測試最佳</span><b>{html.escape(best['variant']['label'])}</b><small>{html.escape(compact(best['summaries']['stock_unit']['stock_test']))}</small></div><div class="card"><span>全期</span><b>{best['summaries']['chronological_unit']['full']['avg_return_pct']:.2f}%</b><small>{best['summaries']['chronological_unit']['full']['units']} 份平均報酬</small></div><div class="card"><span>加碼單</span><b>{best['summaries']['addon_units']['win_rate_pct']:.2f}% / {best['summaries']['addon_units']['avg_return_pct']:.2f}%</b><small>{best['summaries']['addon_units']['units']} 份，勝率 / 平均</small></div></div><div class="note"><strong>判讀重點：</strong>排序以股票 20% holdout 的單位平均報酬為主，不用全期最大化來挑。這份報告是研究「延後與模糊加碼是否改善」，不是宣告凍結規則。</div></header><main><h2>變體比較</h2><div class="table"><table><thead><tr><th>版本</th><th>全期單位</th><th>股票測試單位</th><th>加碼單</th><th>最多加碼</th><th>加碼停損</th></tr></thead><tbody>{summary_rows}</tbody></table></div><h2>股票測試最佳版本：加碼單前 30 名</h2><div class="table"><table><thead><tr><th>訊號日</th><th>股票</th><th>確認日</th><th>觸發日</th><th>加碼日</th><th>方式</th><th class="num">報酬</th><th>出場日</th><th>出場</th></tr></thead><tbody>{addon_rows}</tbody></table></div><p>輸出檔：<code>{OUT_JSON}</code>、<code>{OUT_HTML}</code></p></main></body></html>"""


def main() -> None:
    payload = run()
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    compact_output = []
    for item in payload["variants"]:
        compact_output.append({
            "id": item["variant"]["id"],
            "label": item["variant"]["label"],
            "full": item["summaries"]["chronological_unit"]["full"],
            "stock_test": item["summaries"]["stock_unit"]["stock_test"],
            "addons": item["summaries"]["addon_units"],
        })
    print(json.dumps({"html": str(OUT_HTML), "json": str(OUT_JSON), "variants": compact_output}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
