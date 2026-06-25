#!/usr/bin/env python3
"""PB-V23: independent base/add-on lifecycle without PB-V4 exit-date coupling."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from analyze_pullback_multitimeframe_search import BENCHMARK_CSV, PBV4_JSON, add_benchmark_return
from analyze_pullback_pb_v19_main_wave_addon import (
    POSITION_SIZE,
    confirmation_reason,
    summarize_packages,
    summarize_units,
    unit_pnl,
)
from analyze_pullback_pb_v20_fuzzy_addon import find_next_addon, split_chronological, split_stocks
from analyze_pullback_pb_v21_addon_stop_variants import return_result
from analyze_pullback_pb_v22_structural_addon_stop import (
    FOCUS_VARIANT_ID as V22_FOCUS_VARIANT_ID,
    chart_payload,
    close_execution_result,
    structural_levels,
    unit_payload,
)
from analyze_pullback_technical_phenotypes import find_series, make_series_map
from pullback_lifecycle_filters import filter_same_stock_mother_entries
from run_market_backtest import Row, csv_files, read_rows


REPORT_DIR = Path("reports")
OUT_JSON = REPORT_DIR / "pullback_pb_v23_independent_lifecycle.json"
OUT_HTML = REPORT_DIR / "pullback_pb_v23_independent_lifecycle.html"
VERSION = "PB-V23.0-independent-lifecycle"
FOCUS_VARIANT_ID = "independent_max5_spacing5"

BASE_HARD_STOP_PCT = 0.07
ADDON_BUY_COOLDOWN_TRADING_DAYS = 10
STRUCTURAL_STOP = {
    "id": "confluence_struct_close_next_open",
    "execute": "next_open",
    "catastrophic_close_pct": 0.15,
    "require_confluence": True,
}

ENTRY_VARIANT = {
    "entry_policy": "retest",
    "delay_days": 0,
    "min_wait": 2,
    "max_wait": 8,
    "ma20_band_pct": 0.06,
}

VARIANTS = [
    {
        "id": "independent_max3_spacing5",
        "label": "獨立生命週期：最多3次加碼，間隔5日",
        "max_addons": 3,
        "min_spacing": 5,
    },
    {
        "id": FOCUS_VARIANT_ID,
        "label": "獨立生命週期：最多5次加碼，間隔5日",
        "max_addons": 5,
        "min_spacing": 5,
    },
    {
        "id": "independent_max8_spacing5",
        "label": "獨立生命週期：最多8次加碼，間隔5日",
        "max_addons": 8,
        "min_spacing": 5,
    },
    {
        "id": "independent_max5_spacing10",
        "label": "獨立生命週期：最多5次加碼，間隔10日",
        "max_addons": 5,
        "min_spacing": 10,
    },
]


def first_confirmation_index(
    rows: list[Row],
    indicators: dict[str, list[float | None]],
    signal_index: int,
    base_entry_index: int,
    benchmark_rows: list[Row],
    benchmark_dates: dict[str, int],
) -> tuple[int | None, str | None]:
    for cursor in range(base_entry_index, len(rows) - 1):
        reason = confirmation_reason(rows, indicators, signal_index, base_entry_index, cursor, benchmark_rows, benchmark_dates)
        if reason:
            return cursor, reason
    return None, None


def independent_base_exit(
    entry: Row,
    rows: list[Row],
    indicators: dict[str, list[float | None]],
    signal_index: int,
    entry_index: int,
    confirm_index: int | None,
) -> dict[str, Any]:
    hard_stop = entry.open * (1 - BASE_HARD_STOP_PCT)
    levels = structural_levels(rows, signal_index, confirm_index) if confirm_index is not None else None
    observed: list[Row] = []
    for cursor in range(entry_index, len(rows)):
        row = rows[cursor]
        observed.append(row)
        if row.open <= hard_stop:
            return return_result(entry, observed, row.open, "base_gap_hard_stop7")
        if row.low <= hard_stop:
            return return_result(entry, observed, hard_stop, "base_hard_stop7")
        if levels is None or cursor <= confirm_index:
            continue
        ma20 = indicators["ma20"][cursor]
        if ma20 is None:
            continue
        if row.close <= entry.open * (1 - STRUCTURAL_STOP["catastrophic_close_pct"]):
            return close_execution_result(entry, observed, rows, cursor, "next_open", "base_catastrophic_close_stop")
        if row.close < ma20 and row.close < levels["structure_low"]:
            return close_execution_result(entry, observed, rows, cursor, "next_open", "base_confluence_structure_close_break")
    return return_result(entry, observed, observed[-1].close, "latest_close", unresolved=True)


def structure_addon_exit(
    entry: Row,
    rows: list[Row],
    indicators: dict[str, list[float | None]],
    signal_index: int,
    entry_index: int,
    confirm_index: int,
) -> dict[str, Any]:
    levels = structural_levels(rows, signal_index, confirm_index)
    catastrophic_close = entry.open * (1 - STRUCTURAL_STOP["catastrophic_close_pct"])
    observed: list[Row] = []
    for cursor in range(entry_index, len(rows)):
        row = rows[cursor]
        observed.append(row)
        ma20 = indicators["ma20"][cursor]
        if ma20 is None:
            continue
        if row.close <= catastrophic_close:
            return close_execution_result(entry, observed, rows, cursor, "next_open", "addon_catastrophic_close_stop")
        if row.close < ma20 and row.close < levels["structure_low"]:
            return close_execution_result(entry, observed, rows, cursor, "next_open", "addon_confluence_structure_close_break")
    return return_result(entry, observed, observed[-1].close, "latest_close", unresolved=True)


def sync_addon_exit_with_mother(
    exit_data: dict[str, Any],
    entry: Row,
    entry_index: int,
    base_exit_index: int | None,
    base_exit_data: dict[str, Any] | None,
    dates: dict[str, int],
) -> dict[str, Any]:
    """Force an add-on to close when the mother/base unit closes.

    Add-ons are subordinate to the mother lifecycle. If the mother has a resolved exit and
    an add-on would otherwise remain open or exit later, the add-on is closed on the mother
    exit date using the mother exit execution price.
    """
    if base_exit_index is None or not base_exit_data or base_exit_data.get("unresolved"):
        return exit_data
    exit_index = dates.get(str(exit_data.get("exit_date")))
    if exit_index is not None and exit_index <= base_exit_index and not exit_data.get("unresolved"):
        return exit_data
    base_exit_price = float(base_exit_data.get("exit_price") or 0)
    if not base_exit_price:
        base_exit_price = entry.close
    ret = round((base_exit_price / entry.open - 1) * 100, 2)
    return {
        **exit_data,
        "independent_exit_date": exit_data.get("exit_date"),
        "independent_exit_price": exit_data.get("exit_price"),
        "independent_exit_reason": exit_data.get("exit_reason"),
        "independent_return_pct": exit_data.get("return_pct"),
        "exit_date": base_exit_data.get("exit_date"),
        "exit_price": round(base_exit_price, 4),
        "holding_days": max(1, base_exit_index - entry_index + 1),
        "return_pct": ret,
        "pnl": unit_pnl(ret),
        "exit_reason": f"mother_exit_sync_{base_exit_data.get('exit_reason') or 'mother_exit'}",
        "unresolved": False,
        "mother_exit_sync": True,
    }


def scan_addons(
    source: dict[str, Any],
    rows: list[Row],
    indicators: dict[str, list[float | None]],
    dates: dict[str, int],
    signal_index: int,
    base_entry_index: int,
    benchmark_rows: list[Row],
    benchmark_dates: dict[str, int],
    variant: dict[str, Any],
    base_exit_index: int | None = None,
    base_exit_data: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    entry_variant = {**ENTRY_VARIANT, **variant}
    # Add-ons are only valid while the mother/base unit is still alive.
    # If the mother has already exited, a later entry must be treated as a new mother setup,
    # not as an add-on attached to the closed lifecycle.
    scan_limit_index = min(base_exit_index if base_exit_index is not None else len(rows) - 1, len(rows) - 1)
    if scan_limit_index <= base_entry_index:
        return []
    scan_start = base_entry_index
    addon_units: list[dict[str, Any]] = []
    buy_indices = [base_entry_index]
    same_stock_buy_signal_indices = [
        dates[str(date)]
        for date in (source.get("same_stock_buy_signal_entry_dates") or [])
        if str(date) in dates
    ]
    addon_number = 1
    while addon_number <= int(variant["max_addons"]):
        addon = find_next_addon(
            rows,
            indicators,
            signal_index,
            base_entry_index,
            scan_start,
            scan_limit_index,
            benchmark_rows,
            benchmark_dates,
            entry_variant,
        )
        if not addon:
            break
        entry_index = addon["entry_index"]
        if base_exit_index is not None and entry_index >= base_exit_index:
            break
        blocker_indices = buy_indices + [index for index in same_stock_buy_signal_indices if index < entry_index]
        if any(0 <= entry_index - buy_index <= ADDON_BUY_COOLDOWN_TRADING_DAYS for buy_index in blocker_indices):
            # A valid add-on cannot occur if the same stock had any buy or buy-signal
            # candidate in the previous 10 trading days. Skip this candidate and keep
            # looking later in the same mother lifecycle.
            scan_start = entry_index + 1
            continue
        confirm_index = dates.get(addon["confirm_date"])
        if confirm_index is None:
            break
        entry = rows[entry_index]
        levels = structural_levels(rows, signal_index, confirm_index)
        exit_data = structure_addon_exit(entry, rows, indicators, signal_index, entry_index, confirm_index)
        exit_data = sync_addon_exit_with_mother(exit_data, entry, entry_index, base_exit_index, base_exit_data, dates)
        unit = {
            **source,
            "variant": variant["id"],
            "unit_type": "addon",
            "addon_number": addon_number,
            "entry_date": entry.date,
            "entry_price": round(entry.open, 4),
            "confirm_low": round(levels["confirm_low"], 4),
            "pullback_low": round(levels["pullback_low"], 4),
            "structure_low": round(levels["structure_low"], 4),
            **addon,
            **exit_data,
        }
        add_benchmark_return(unit, benchmark_rows, benchmark_dates)
        addon_units.append(unit)
        buy_indices.append(entry_index)
        addon_number += 1
        scan_start = entry_index + max(int(variant["min_spacing"]), ADDON_BUY_COOLDOWN_TRADING_DAYS + 1)
    return addon_units


def filter_source_trades_for_mother_lifecycle(
    source_trades: list[dict[str, Any]],
    series: dict[tuple[str, str], tuple[list[Row], dict[str, list[float | None]], dict[str, int]]],
    benchmark_rows: list[Row],
    benchmark_dates: dict[str, int],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    raw_buy_dates_by_stock: dict[tuple[str, str], list[str]] = {}
    for source in source_trades:
        market = str(source.get("market") or "").upper()
        stock_no = str(source.get("stock_no") or "")
        bundle = find_series(series, market, stock_no)
        if not bundle:
            continue
        rows, indicators, dates = bundle
        signal_index = dates.get(str(source.get("signal_date")))
        if signal_index is None or signal_index + 1 >= len(rows):
            continue
        base_entry_index = signal_index + 1
        base_entry = rows[base_entry_index]
        confirm_index, _ = first_confirmation_index(
            rows, indicators, signal_index, base_entry_index, benchmark_rows, benchmark_dates
        )
        base_exit = independent_base_exit(base_entry, rows, indicators, signal_index, base_entry_index, confirm_index)
        key = (market, stock_no)
        raw_buy_dates_by_stock.setdefault(key, []).append(base_entry.date)
        prepared.append({
            **source,
            "market": market,
            "stock_no": stock_no,
            "entry_date": base_entry.date,
            "entry_price": round(base_entry.open, 4),
            "exit_date": base_exit.get("exit_date"),
            "exit_reason": base_exit.get("exit_reason"),
        })

    accepted, diagnostics = filter_same_stock_mother_entries(
        prepared, series, find_series, cooldown_trading_days=ADDON_BUY_COOLDOWN_TRADING_DAYS
    )
    for row in accepted:
        key = (str(row.get("market") or "").upper(), str(row.get("stock_no") or ""))
        row["same_stock_buy_signal_entry_dates"] = sorted(set(raw_buy_dates_by_stock.get(key, [])))
        row["mother_lifecycle_filter"] = "same-stock active mother and 10-trading-day cooldown"
    diagnostics["raw_buy_signal_dates_by_stock_count"] = len(raw_buy_dates_by_stock)
    return accepted, diagnostics


def simulate_variant(
    source_trades: list[dict[str, Any]],
    series: dict[tuple[str, str], tuple[list[Row], dict[str, list[float | None]], dict[str, int]]],
    benchmark_rows: list[Row],
    benchmark_dates: dict[str, int],
    validation_start: str,
    test_start: str,
    variant: dict[str, Any],
) -> dict[str, Any]:
    source_trades, mother_lifecycle_diagnostics = filter_source_trades_for_mother_lifecycle(
        source_trades, series, benchmark_rows, benchmark_dates
    )
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
        confirm_index, confirm_reason_text = first_confirmation_index(
            rows, indicators, signal_index, base_entry_index, benchmark_rows, benchmark_dates
        )
        base_levels = structural_levels(rows, signal_index, confirm_index) if confirm_index is not None else {}
        base_exit = independent_base_exit(base_entry, rows, indicators, signal_index, base_entry_index, confirm_index)
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
        add_benchmark_return(base_unit, benchmark_rows, benchmark_dates)
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
    base_units = [row for row in units if row["unit_type"] == "base"]
    delta_units = [row for row in units if str(row.get("stock_no")) == "2308"]
    return {
        "variant": {**ENTRY_VARIANT, **STRUCTURAL_STOP, **variant},
        "summaries": {
            "chronological_unit": {name: summarize_units(rows) for name, rows in chrono_units.items()},
            "chronological_package": {name: summarize_packages(rows) for name, rows in chrono_packages.items()},
            "stock_unit": {name: summarize_units(rows) for name, rows in stock_units.items()},
            "stock_package": {name: summarize_packages(rows) for name, rows in stock_packages.items()},
            "base_units": summarize_units(base_units),
            "addon_units": summarize_units(addons),
            "stock_counts": stock_counts,
            "package_stock_counts": package_stock_counts,
            "mother_lifecycle_filter": mother_lifecycle_diagnostics,
        },
        "units": units,
        "packages": packages,
        "delta_units": delta_units,
    }


def v22_reference() -> dict[str, Any] | None:
    path = REPORT_DIR / "pullback_pb_v22_structural_addon_stop.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    for item in payload.get("variants", []):
        if item.get("variant", {}).get("id") == V22_FOCUS_VARIANT_ID:
            return {
                "id": "v22_pbv4_coupled_reference",
                "label": "V22 對照：PB-V4 出場日截斷，最多3次",
                "full": item["summaries"]["chronological_unit"]["full"],
                "stock_test": item["summaries"]["stock_unit"]["stock_test"],
                "addons": item["summaries"]["addon_units"],
                "delta_units": [row for row in item.get("units", []) if str(row.get("stock_no")) == "2308"],
            }
    return None


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
            "base": "Base unit enters next open after the PB-V4 source signal, then exits only by its own -7% hard stop, close-based MA20+structure failure, or latest close. PB-V4 exit date is not read.",
            "addon_entry": "PB-V20 MA20-retest add-on timing is kept, but the scan end is the available data end instead of the PB-V4 base exit date.",
            "addon_exit": "Add-on units use the PB-V22 loose structural stop: exit only after close below both MA20 and the signal-to-confirmation structure low, next open; plus a close-based 15% catastrophic stop.",
            "structure_low": "Current structure low is min(low) from signal date through the confirmation candle, inclusive. It is a window low, not a swing-low/ABC parser.",
            "validation": "Chronological 60/20/20 and deterministic stock-level 60/20/20 splits are reported.",
        },
        "split": {"validation_start": validation_start, "test_start": test_start},
        "v22_reference": v22_reference(),
        "variants": variants,
    }


def compact(summary: dict[str, Any], key: str = "units") -> str:
    return (
        f"{summary.get(key, 0)} | 勝率 {summary['win_rate_pct']:.2f}% | "
        f"平均 {summary['avg_return_pct']:.2f}% | 中位 {summary['median_return_pct']:.2f}% | "
        f"損益 {summary['total_pnl']:,.0f}"
    )


def row_class(value: Any) -> str:
    try:
        return "pos" if float(value) >= 0 else "neg"
    except (TypeError, ValueError):
        return ""


def fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "-"
    if isinstance(value, (int, float)):
        return f"{value:,.{digits}f}" if isinstance(value, float) else f"{value:,}"
    return html.escape(str(value))


def units_table(rows: list[dict[str, Any]], limit: int | None = None) -> str:
    shown = rows if limit is None else rows[:limit]
    body = "".join(
        "<tr>"
        f"<td>{html.escape(str(row.get('stock_no')))} {html.escape(str(row.get('stock_name', '')))}</td>"
        f"<td>{'加碼#' + str(row.get('addon_number')) if row.get('unit_type') == 'addon' else '母單'}</td>"
        f"<td>{html.escape(str(row.get('signal_date')))}</td>"
        f"<td>{html.escape(str(row.get('confirm_date') or '-'))}</td>"
        f"<td>{html.escape(str(row.get('entry_date')))}</td>"
        f"<td>{html.escape(str(row.get('exit_date')))}</td>"
        f"<td class='num'>{fmt(row.get('entry_price'))}</td>"
        f"<td class='num'>{fmt(row.get('exit_price'))}</td>"
        f"<td class='num {row_class(row.get('return_pct'))}'>{fmt(row.get('return_pct'))}%</td>"
        f"<td class='num {row_class(row.get('pnl'))}'>{fmt(row.get('pnl'), 0)}</td>"
        f"<td class='num'>{fmt(row.get('structure_low'))}</td>"
        f"<td>{html.escape(str(row.get('exit_reason')))}</td>"
        "</tr>"
        for row in shown
    )
    if not body:
        body = "<tr><td colspan='12'>無資料</td></tr>"
    return (
        "<div class='table'><table><thead><tr>"
        "<th>股票</th><th>單位</th><th>訊號</th><th>確認</th><th>進場</th><th>出場/估值</th>"
        "<th class='num'>進場</th><th class='num'>出場</th><th class='num'>報酬</th><th class='num'>損益</th><th class='num'>結構低</th><th>原因</th>"
        "</tr></thead><tbody>" + body + "</tbody></table></div>"
    )


def render_html(payload: dict[str, Any]) -> str:
    comparison = []
    ref = payload.get("v22_reference")
    if ref:
        comparison.append({"label": ref["label"], "full": ref["full"], "stock_test": ref["stock_test"], "addons": ref["addons"]})
    for item in payload["variants"]:
        comparison.append({
            "label": item["variant"]["label"],
            "full": item["summaries"]["chronological_unit"]["full"],
            "stock_test": item["summaries"]["stock_unit"]["stock_test"],
            "addons": item["summaries"]["addon_units"],
        })
    comparison_rows = "".join(
        f"<tr><th>{html.escape(row['label'])}</th><td>{html.escape(compact(row['full']))}</td>"
        f"<td>{html.escape(compact(row['stock_test']))}</td><td>{html.escape(compact(row['addons']))}</td></tr>"
        for row in comparison
    )
    focus = next(item for item in payload["variants"] if item["variant"]["id"] == FOCUS_VARIANT_ID)
    focus_units = sorted(
        focus["units"],
        key=lambda row: (row["signal_date"], str(row["stock_no"]), 0 if row["unit_type"] == "base" else 1, row.get("addon_number") or 0),
    )
    focus_addons = [row for row in focus_units if row["unit_type"] == "addon"]
    delta_units = sorted(focus["delta_units"], key=lambda row: (row["entry_date"], row.get("addon_number") or 0))
    ref_delta = sorted((ref or {}).get("delta_units", []), key=lambda row: (row.get("entry_date", ""), row.get("addon_number") or 0))
    return f"""<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>PB-V23 獨立生命週期</title><style>
:root{{--bg:#f7f7f2;--paper:#fff;--ink:#17211d;--muted:#65716b;--line:#dfe5df;--good:#08735d;--bad:#a13e34;--accent:#1f6a73}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 system-ui,'Microsoft JhengHei',sans-serif}}header,main{{max-width:1480px;margin:auto;padding:24px 16px}}header{{border-bottom:1px solid var(--line)}}h1{{margin:0 0 8px;font-size:28px}}h2{{font-size:19px;margin:28px 0 10px}}p{{margin:6px 0;color:var(--muted)}}.cards{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1px;background:var(--line);border:1px solid var(--line);margin-top:18px}}.card{{background:var(--paper);padding:16px}}.card b{{display:block;font-size:21px}}.note{{margin-top:16px;background:#ecf3f2;border-left:4px solid var(--accent);padding:12px 14px}}.table{{overflow:auto;border:1px solid var(--line);background:var(--paper)}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}thead th{{background:#eef1ee;color:var(--muted);font-size:12px}}.num{{text-align:right}}.pos{{color:var(--good);font-weight:800}}.neg{{color:var(--bad);font-weight:800}}code{{background:#eef1ee;padding:1px 4px;border-radius:4px}}@media(max-width:900px){{.cards{{grid-template-columns:1fr 1fr}}header,main{{padding:18px 10px}}}}
</style></head><body><header><h1>PB-V23 獨立生命週期測試</h1><p>這版專門修正限制污染：母單與加碼單都不再讀取 PB-V4 出場日期；加碼規則維持 PB-V22 寬鬆結構停損，只測「最多加碼次數 / 間隔」的限制差異。</p><div class='cards'><div class='card'><span>焦點版本</span><b>max5 / spacing5</b><small>同樣每份 TWD 100,000</small></div><div class='card'><span>全期單位</span><b>{focus['summaries']['chronological_unit']['full']['avg_return_pct']:.2f}%</b><small>{focus['summaries']['chronological_unit']['full']['units']} 份，勝率 {focus['summaries']['chronological_unit']['full']['win_rate_pct']:.2f}%</small></div><div class='card'><span>母單</span><b>{focus['summaries']['base_units']['avg_return_pct']:.2f}%</b><small>{focus['summaries']['base_units']['units']} 份，獨立出場</small></div><div class='card'><span>加碼單</span><b>{focus['summaries']['addon_units']['avg_return_pct']:.2f}%</b><small>{focus['summaries']['addon_units']['units']} 份，勝率 {focus['summaries']['addon_units']['win_rate_pct']:.2f}%</small></div></div><div class='note'><strong>前波結構低點算法：</strong><code>pullback_low = min(low[signal_date..confirm_date])</code>，<code>confirm_low = low[confirm_date]</code>，<code>structure_low = min(confirm_low, pullback_low)</code>。因為 pullback_low 已包含確認K，所以目前實質上就是「訊號日至確認K的最低低點」，不是完整 swing low 或 ABC 波自動辨識。</div></header><main><h2>限制差異比較</h2><div class='table'><table><thead><tr><th>版本</th><th>全期單位</th><th>股票測試單位</th><th>加碼單</th></tr></thead><tbody>{comparison_rows}</tbody></table></div><h2>台達電 2308 對照</h2><p>上方是 V22 被 PB-V4 截斷時的台達電紀錄；下方是 V23 放開掃描期間後的台達電紀錄。</p><h3>V22 對照</h3>{units_table(ref_delta)}<h3>V23 焦點版</h3>{units_table(delta_units)}<h2>V23 焦點版所有加碼單</h2>{units_table(focus_addons)}<h2>V23 焦點版全部單位</h2>{units_table(focus_units)}<p>輸出檔：<code>{OUT_JSON}</code>、<code>{OUT_HTML}</code></p></main></body></html>"""


def main() -> None:
    payload = run()
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    compact_output = []
    if payload.get("v22_reference"):
        compact_output.append(payload["v22_reference"])
    for item in payload["variants"]:
        compact_output.append({
            "id": item["variant"]["id"],
            "label": item["variant"]["label"],
            "full": item["summaries"]["chronological_unit"]["full"],
            "stock_test": item["summaries"]["stock_unit"]["stock_test"],
            "addons": item["summaries"]["addon_units"],
            "delta_units": len(item["delta_units"]),
        })
    print(json.dumps({"html": str(OUT_HTML), "json": str(OUT_JSON), "variants": compact_output}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
