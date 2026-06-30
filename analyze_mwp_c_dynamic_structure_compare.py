#!/usr/bin/env python3
"""Compare fixed structure-low vs dynamic pivot-low exits for MWP-C."""

from __future__ import annotations

import html
import json
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import analyze_pullback_pb_v23_independent_lifecycle as pbv23
from analyze_mwp_addon_strategy_comparison import strip_heavy
from analyze_mwp_technical_filter_experiment import BASE_VARIANT, build_features, filter_record, ge

REPORT_DIR = Path("reports")
OUT_JSON = REPORT_DIR / "mwp_c_dynamic_structure_compare.json"
OUT_HTML = REPORT_DIR / "mwp_c_dynamic_structure_compare.html"
OUT_MD = REPORT_DIR / "mwp_c_dynamic_structure_compare.md"
VERSION = "MWP-C-dynamic-structure-compare"

PIVOT_LEFT_BARS = 2
PIVOT_RIGHT_BARS = 2
PROFIT_GATE_PCT = 0.15


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


def with_structure_meta(
    exit_data: dict[str, Any],
    initial_structure_low: float | None,
    final_structure_low: float | None,
    updates: list[dict[str, Any]],
    policy_name: str,
    activation_price: float | None = None,
    activated: bool | None = None,
) -> dict[str, Any]:
    return {
        **exit_data,
        "initial_structure_low": round(initial_structure_low, 4) if initial_structure_low is not None else None,
        "final_structure_low": round(final_structure_low, 4) if final_structure_low is not None else None,
        "dynamic_structure_updates": updates,
        "dynamic_structure_update_count": len(updates),
        "dynamic_structure_policy": policy_name,
        "dynamic_structure_activation_price": round(activation_price, 4) if activation_price is not None else None,
        "dynamic_structure_activated": activated,
    }


def is_pivot_low(rows: list[pbv23.Row], pivot_index: int, left: int = PIVOT_LEFT_BARS, right: int = PIVOT_RIGHT_BARS) -> bool:
    if pivot_index - left < 0 or pivot_index + right >= len(rows):
        return False
    center_low = rows[pivot_index].low
    if not all(center_low < rows[pivot_index - offset].low for offset in range(1, left + 1)):
        return False
    if not all(center_low <= rows[pivot_index + offset].low for offset in range(1, right + 1)):
        return False
    return True


def dynamic_structure_exit(
    entry: pbv23.Row,
    rows: list[pbv23.Row],
    indicators: dict[str, list[float | None]],
    signal_index: int,
    entry_index: int,
    confirm_index: int | None,
    *,
    unit_prefix: str,
    catastrophic_close_pct: float,
    allow_hard_stop: bool,
    policy_name: str,
    profit_gate_pct: float | None = None,
) -> dict[str, Any]:
    levels = pbv23.structural_levels(rows, signal_index, confirm_index) if confirm_index is not None else None
    initial_structure_low = float(levels["structure_low"]) if levels else None
    current_structure_low = initial_structure_low
    activation_price = entry.open * (1 + profit_gate_pct) if profit_gate_pct is not None else None
    activated = profit_gate_pct is None
    hard_stop = entry.open * (1 - pbv23.BASE_HARD_STOP_PCT) if allow_hard_stop else None
    updates: list[dict[str, Any]] = []
    observed: list[pbv23.Row] = []
    for cursor in range(entry_index, len(rows)):
        row = rows[cursor]
        observed.append(row)
        if allow_hard_stop and hard_stop is not None:
            if row.open <= hard_stop:
                return with_structure_meta(
                    pbv23.return_result(entry, observed, row.open, f"{unit_prefix}_gap_hard_stop7"),
                    initial_structure_low,
                    current_structure_low,
                    updates,
                    policy_name,
                    activation_price,
                    activated,
                )
            if row.low <= hard_stop:
                return with_structure_meta(
                    pbv23.return_result(entry, observed, hard_stop, f"{unit_prefix}_hard_stop7"),
                    initial_structure_low,
                    current_structure_low,
                    updates,
                    policy_name,
                    activation_price,
                    activated,
                )

        if not activated and activation_price is not None and row.high >= activation_price:
            activated = True

        pivot_index = cursor - PIVOT_RIGHT_BARS
        if (
            activated
            and current_structure_low is not None
            and confirm_index is not None
            and pivot_index > confirm_index
            and pivot_index >= entry_index
            and is_pivot_low(rows, pivot_index)
        ):
            pivot_low = rows[pivot_index].low
            if pivot_low > current_structure_low:
                current_structure_low = pivot_low
                updates.append({
                    "pivot_date": rows[pivot_index].date,
                    "pivot_low": round(pivot_low, 4),
                    "confirmed_on": row.date,
                    "structure_low_after_update": round(current_structure_low, 4),
                })

        if current_structure_low is None or confirm_index is None or cursor <= confirm_index:
            continue
        ma20 = indicators["ma20"][cursor]
        if ma20 is None:
            continue
        if row.close <= entry.open * (1 - catastrophic_close_pct):
            return with_structure_meta(
                pbv23.close_execution_result(entry, observed, rows, cursor, "next_open", f"{unit_prefix}_catastrophic_close_stop"),
                initial_structure_low,
                current_structure_low,
                updates,
                policy_name,
                activation_price,
                activated,
            )
        if row.close < ma20 and row.close < current_structure_low:
            return with_structure_meta(
                pbv23.close_execution_result(entry, observed, rows, cursor, "next_open", f"{unit_prefix}_pivot_structure_close_break"),
                initial_structure_low,
                current_structure_low,
                updates,
                policy_name,
                activation_price,
                activated,
            )
    return with_structure_meta(
        pbv23.return_result(entry, observed, observed[-1].close, "latest_close", unresolved=True),
        initial_structure_low,
        current_structure_low,
        updates,
        policy_name,
        activation_price,
        activated,
    )


def base_exit_fixed(
    entry: pbv23.Row,
    rows: list[pbv23.Row],
    indicators: dict[str, list[float | None]],
    signal_index: int,
    entry_index: int,
    confirm_index: int | None,
) -> dict[str, Any]:
    return with_structure_meta(
        pbv23.independent_base_exit(entry, rows, indicators, signal_index, entry_index, confirm_index),
        float(pbv23.structural_levels(rows, signal_index, confirm_index)["structure_low"]) if confirm_index is not None else None,
        float(pbv23.structural_levels(rows, signal_index, confirm_index)["structure_low"]) if confirm_index is not None else None,
        [],
        "fixed_structure_low",
    )


def addon_exit_fixed(
    entry: pbv23.Row,
    rows: list[pbv23.Row],
    indicators: dict[str, list[float | None]],
    signal_index: int,
    entry_index: int,
    confirm_index: int | None,
) -> dict[str, Any]:
    if confirm_index is None:
        return pbv23.return_result(entry, [rows[entry_index]], rows[entry_index].close, "latest_close", unresolved=True)
    return with_structure_meta(
        pbv23.structure_addon_exit(entry, rows, indicators, signal_index, entry_index, confirm_index),
        float(pbv23.structural_levels(rows, signal_index, confirm_index)["structure_low"]),
        float(pbv23.structural_levels(rows, signal_index, confirm_index)["structure_low"]),
        [],
        "fixed_structure_low",
    )


def base_exit_dynamic_pivot(
    entry: pbv23.Row,
    rows: list[pbv23.Row],
    indicators: dict[str, list[float | None]],
    signal_index: int,
    entry_index: int,
    confirm_index: int | None,
) -> dict[str, Any]:
    return dynamic_structure_exit(
        entry,
        rows,
        indicators,
        signal_index,
        entry_index,
        confirm_index,
        unit_prefix="base",
        catastrophic_close_pct=pbv23.STRUCTURAL_STOP["catastrophic_close_pct"],
        allow_hard_stop=True,
        policy_name="pivot_swing_low_dynamic",
    )


def addon_exit_dynamic_pivot(
    entry: pbv23.Row,
    rows: list[pbv23.Row],
    indicators: dict[str, list[float | None]],
    signal_index: int,
    entry_index: int,
    confirm_index: int | None,
) -> dict[str, Any]:
    return dynamic_structure_exit(
        entry,
        rows,
        indicators,
        signal_index,
        entry_index,
        confirm_index,
        unit_prefix="addon",
        catastrophic_close_pct=pbv23.STRUCTURAL_STOP["catastrophic_close_pct"],
        allow_hard_stop=False,
        policy_name="pivot_swing_low_dynamic",
    )


def base_exit_profit_gated_pivot(
    entry: pbv23.Row,
    rows: list[pbv23.Row],
    indicators: dict[str, list[float | None]],
    signal_index: int,
    entry_index: int,
    confirm_index: int | None,
) -> dict[str, Any]:
    return dynamic_structure_exit(
        entry,
        rows,
        indicators,
        signal_index,
        entry_index,
        confirm_index,
        unit_prefix="base",
        catastrophic_close_pct=pbv23.STRUCTURAL_STOP["catastrophic_close_pct"],
        allow_hard_stop=True,
        policy_name="profit_gated_pivot_swing_low_dynamic",
        profit_gate_pct=PROFIT_GATE_PCT,
    )


def addon_exit_profit_gated_pivot(
    entry: pbv23.Row,
    rows: list[pbv23.Row],
    indicators: dict[str, list[float | None]],
    signal_index: int,
    entry_index: int,
    confirm_index: int | None,
) -> dict[str, Any]:
    return dynamic_structure_exit(
        entry,
        rows,
        indicators,
        signal_index,
        entry_index,
        confirm_index,
        unit_prefix="addon",
        catastrophic_close_pct=pbv23.STRUCTURAL_STOP["catastrophic_close_pct"],
        allow_hard_stop=False,
        policy_name="profit_gated_pivot_swing_low_dynamic",
        profit_gate_pct=PROFIT_GATE_PCT,
    )


def filter_source_trades_for_mother_lifecycle_with_base_exit(
    source_trades: list[dict[str, Any]],
    series: dict[tuple[str, str], tuple[list[pbv23.Row], dict[str, list[float | None]], dict[str, int]]],
    benchmark_rows: list[pbv23.Row],
    benchmark_dates: dict[str, int],
    base_exit_func: Callable[[pbv23.Row, list[pbv23.Row], dict[str, list[float | None]], int, int, int | None], dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    raw_buy_dates_by_stock: dict[tuple[str, str], list[str]] = {}
    for source in source_trades:
        market = str(source.get("market") or "").upper()
        stock_no = str(source.get("stock_no") or "")
        bundle = pbv23.find_series(series, market, stock_no)
        if not bundle:
            continue
        rows, indicators, dates = bundle
        signal_index = dates.get(str(source.get("signal_date")))
        if signal_index is None or signal_index + 1 >= len(rows):
            continue
        base_entry_index = signal_index + 1
        base_entry = rows[base_entry_index]
        confirm_index, _ = pbv23.first_confirmation_index(
            rows, indicators, signal_index, base_entry_index, benchmark_rows, benchmark_dates
        )
        base_exit = base_exit_func(base_entry, rows, indicators, signal_index, base_entry_index, confirm_index)
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
    accepted, diagnostics = pbv23.filter_same_stock_mother_entries(
        prepared, series, pbv23.find_series, cooldown_trading_days=pbv23.ADDON_BUY_COOLDOWN_TRADING_DAYS
    )
    for row in accepted:
        key = (str(row.get("market") or "").upper(), str(row.get("stock_no") or ""))
        row["same_stock_buy_signal_entry_dates"] = sorted(set(raw_buy_dates_by_stock.get(key, [])))
        row["mother_lifecycle_filter"] = "same-stock active mother and 10-trading-day cooldown"
    diagnostics["raw_buy_signal_dates_by_stock_count"] = len(raw_buy_dates_by_stock)
    return accepted, diagnostics


def scan_addons_with_exit_policy(
    source: dict[str, Any],
    rows: list[pbv23.Row],
    indicators: dict[str, list[float | None]],
    dates: dict[str, int],
    signal_index: int,
    base_entry_index: int,
    benchmark_rows: list[pbv23.Row],
    benchmark_dates: dict[str, int],
    variant: dict[str, Any],
    addon_exit_func: Callable[[pbv23.Row, list[pbv23.Row], dict[str, list[float | None]], int, int, int | None], dict[str, Any]],
    base_exit_index: int | None = None,
    base_exit_data: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    entry_variant = {**pbv23.ENTRY_VARIANT, **variant}
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
        addon = pbv23.find_next_addon(
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
        if any(0 <= entry_index - buy_index <= pbv23.ADDON_BUY_COOLDOWN_TRADING_DAYS for buy_index in blocker_indices):
            scan_start = entry_index + 1
            continue
        confirm_index = dates.get(addon["confirm_date"])
        if confirm_index is None:
            break
        entry = rows[entry_index]
        levels = pbv23.structural_levels(rows, signal_index, confirm_index)
        exit_data = addon_exit_func(entry, rows, indicators, signal_index, entry_index, confirm_index)
        exit_data = pbv23.sync_addon_exit_with_mother(exit_data, entry, entry_index, base_exit_index, base_exit_data, dates)
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
        pbv23.add_benchmark_return(unit, benchmark_rows, benchmark_dates)
        addon_units.append(unit)
        buy_indices.append(entry_index)
        addon_number += 1
        scan_start = entry_index + max(int(variant["min_spacing"]), pbv23.ADDON_BUY_COOLDOWN_TRADING_DAYS + 1)
    return addon_units


def simulate_variant_with_exit_policy(
    source_trades: list[dict[str, Any]],
    series: dict[tuple[str, str], tuple[list[pbv23.Row], dict[str, list[float | None]], dict[str, int]]],
    benchmark_rows: list[pbv23.Row],
    benchmark_dates: dict[str, int],
    validation_start: str,
    test_start: str,
    variant: dict[str, Any],
    base_exit_func: Callable[[pbv23.Row, list[pbv23.Row], dict[str, list[float | None]], int, int, int | None], dict[str, Any]],
    addon_exit_func: Callable[[pbv23.Row, list[pbv23.Row], dict[str, list[float | None]], int, int, int | None], dict[str, Any]],
) -> dict[str, Any]:
    source_trades, mother_lifecycle_diagnostics = filter_source_trades_for_mother_lifecycle_with_base_exit(
        source_trades, series, benchmark_rows, benchmark_dates, base_exit_func
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
        base_exit = base_exit_func(base_entry, rows, indicators, signal_index, base_entry_index, confirm_index)
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
        addon_units = scan_addons_with_exit_policy(
            source,
            rows,
            indicators,
            dates,
            signal_index,
            base_entry_index,
            benchmark_rows,
            benchmark_dates,
            variant,
            addon_exit_func,
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
        "validation_start": validation_start,
        "test_start": test_start,
    }


def exit_family_counts(record: dict[str, Any]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for row in record["units"]:
        if row.get("unresolved"):
            counter["latest_close_unresolved"] += 1
            continue
        reason = str(row.get("exit_reason") or "")
        if "hard_stop" in reason:
            counter["hard_stop"] += 1
        elif "catastrophic" in reason:
            counter["catastrophic_close_stop"] += 1
        elif "structure_close_break" in reason:
            counter["structure_break"] += 1
        elif reason.startswith("mother_exit_sync_"):
            counter["mother_exit_sync"] += 1
        else:
            counter[reason or "other"] += 1
    return dict(counter)


def structure_update_stats(record: dict[str, Any]) -> dict[str, Any]:
    units = record["units"]
    updated = [row for row in units if int(row.get("dynamic_structure_update_count") or 0) > 0]
    raised = [
        row for row in units
        if row.get("final_structure_low") is not None
        and row.get("initial_structure_low") is not None
        and float(row["final_structure_low"]) > float(row["initial_structure_low"])
    ]
    return {
        "updated_units": len(updated),
        "raised_structure_units": len(raised),
        "avg_updates_per_updated_unit": round(sum(int(row.get("dynamic_structure_update_count") or 0) for row in updated) / len(updated), 2) if updated else 0.0,
        "base_updated_units": sum(row.get("unit_type") == "base" for row in updated),
        "addon_updated_units": sum(row.get("unit_type") == "addon" for row in updated),
    }


def changed_units(reference: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    ref_map = {
        (lifecycle_key(row), str(row.get("unit_type") or ""), int(row.get("addon_number") or 0)): row
        for row in reference["units"]
    }
    cand_map = {
        (lifecycle_key(row), str(row.get("unit_type") or ""), int(row.get("addon_number") or 0)): row
        for row in candidate["units"]
    }
    changed: list[dict[str, Any]] = []
    for key, ref_row in ref_map.items():
        cand_row = cand_map.get(key)
        if not cand_row:
            continue
        if (
            str(ref_row.get("exit_date")) != str(cand_row.get("exit_date"))
            or str(ref_row.get("exit_reason")) != str(cand_row.get("exit_reason"))
            or float(ref_row.get("pnl") or 0) != float(cand_row.get("pnl") or 0)
        ):
            changed.append({
                "label": ref_row.get("label"),
                "market": ref_row.get("market"),
                "stock_no": ref_row.get("stock_no"),
                "unit_type": ref_row.get("unit_type"),
                "addon_number": ref_row.get("addon_number"),
                "signal_date": ref_row.get("signal_date"),
                "entry_date": ref_row.get("entry_date"),
                "reference_exit_date": ref_row.get("exit_date"),
                "reference_exit_reason": ref_row.get("exit_reason"),
                "reference_return_pct": ref_row.get("return_pct"),
                "reference_pnl": ref_row.get("pnl"),
                "candidate_exit_date": cand_row.get("exit_date"),
                "candidate_exit_reason": cand_row.get("exit_reason"),
                "candidate_return_pct": cand_row.get("return_pct"),
                "candidate_pnl": cand_row.get("pnl"),
                "pnl_delta": round(float(cand_row.get("pnl") or 0) - float(ref_row.get("pnl") or 0), 2),
            })
    changed.sort(key=lambda row: float(row.get("pnl_delta") or 0), reverse=True)
    return {
        "count": len(changed),
        "improved_count": sum(float(row.get("pnl_delta") or 0) > 0 for row in changed),
        "worsened_count": sum(float(row.get("pnl_delta") or 0) < 0 for row in changed),
        "total_pnl_delta": round(sum(float(row.get("pnl_delta") or 0) for row in changed), 2),
        "top_improved": changed[:10],
        "top_worsened": list(reversed(changed[-10:])),
    }


def build_record(
    label: str,
    description: str,
    base_exit_func: Callable[[pbv23.Row, list[pbv23.Row], dict[str, list[float | None]], int, int, int | None], dict[str, Any]],
    addon_exit_func: Callable[[pbv23.Row, list[pbv23.Row], dict[str, list[float | None]], int, int, int | None], dict[str, Any]],
) -> dict[str, Any]:
    source_trades = json.loads(pbv23.PBV4_JSON.read_text(encoding="utf-8"))["trades"]
    series = pbv23.make_series_map(pbv23.csv_files())
    benchmark_rows = pbv23.read_rows(pbv23.BENCHMARK_CSV)
    benchmark_dates = {row.date: index for index, row in enumerate(benchmark_rows)}
    v8 = json.loads((REPORT_DIR / "pullback_pb_v8_multitimeframe_search.json").read_text(encoding="utf-8"))
    result = simulate_variant_with_exit_policy(
        source_trades,
        series,
        benchmark_rows,
        benchmark_dates,
        v8["split"]["validation_start"],
        v8["split"]["test_start"],
        BASE_VARIANT,
        base_exit_func,
        addon_exit_func,
    )
    features = build_features(result["packages"], series)
    record = filter_record(label, result["packages"], result["units"], features, ge("ma20_slope5_pct", 0))
    record["description"] = description
    record["mother_lifecycle_filter"] = result["mother_lifecycle_filter"]
    record["exit_family_counts"] = exit_family_counts(record)
    record["structure_update_stats"] = structure_update_stats(record)
    return record


def summary_delta(candidate: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    return {
        "full_units": int(candidate["summary"]["full_units"]["units"]) - int(baseline["summary"]["full_units"]["units"]),
        "base_units": int(candidate["summary"]["base_units"]["units"]) - int(baseline["summary"]["base_units"]["units"]),
        "addon_units": int(candidate["summary"]["addon_units"]["units"]) - int(baseline["summary"]["addon_units"]["units"]),
        "full_avg_return_pct": round(float(candidate["summary"]["full_units"]["avg_return_pct"]) - float(baseline["summary"]["full_units"]["avg_return_pct"]), 4),
        "full_win_rate_pct": round(float(candidate["summary"]["full_units"]["win_rate_pct"]) - float(baseline["summary"]["full_units"]["win_rate_pct"]), 4),
        "full_total_pnl": round(float(candidate["summary"]["full_units"]["total_pnl"]) - float(baseline["summary"]["full_units"]["total_pnl"]), 2),
        "random_avg_return_pct": round(float(candidate["random_unit_stock_test"]["avg_return_pct"]["mean"]) - float(baseline["random_unit_stock_test"]["avg_return_pct"]["mean"]), 4),
        "random_p25_return_pct": round(float(candidate["random_unit_stock_test"]["avg_return_pct"]["p25"]) - float(baseline["random_unit_stock_test"]["avg_return_pct"]["p25"]), 4),
    }


def render_html(payload: dict[str, Any]) -> str:
    baseline = payload["strategies"][0]
    comparison_rows = "".join(
        f"<tr><th>{html.escape(row['label'])}</th>"
        f"<td>{html.escape(unit_cell(row['summary']['full_units']))}</td>"
        f"<td>{html.escape(unit_cell(row['summary']['base_units']))}</td>"
        f"<td>{html.escape(unit_cell(row['summary']['addon_units']))}</td>"
        f"<td>{html.escape(random_cell(row['random_unit_stock_test']))}</td>"
        f"<td>{fmt_count(row['structure_update_stats']['updated_units'])}</td>"
        f"<td>{fmt_count(row['structure_update_stats']['raised_structure_units'])}</td>"
        f"<td>{fmt_count(row['exit_family_counts'].get('structure_break', 0))}</td>"
        f"<td>{fmt_count(row['exit_family_counts'].get('hard_stop', 0))}</td></tr>"
        for row in payload["strategies"]
    )
    delta_rows = "".join(
        f"<tr><th>{html.escape(row['label'])}</th>"
        f"<td>{fmt_count(row['delta_vs_fixed']['full_units'])}</td>"
        f"<td>{pct(row['delta_vs_fixed']['full_avg_return_pct'])}</td>"
        f"<td>{pct(row['delta_vs_fixed']['full_win_rate_pct'])}</td>"
        f"<td>{fmt_money(row['delta_vs_fixed']['full_total_pnl'])}</td>"
        f"<td>{pct(row['delta_vs_fixed']['random_avg_return_pct'])}</td>"
        f"<td>{pct(row['delta_vs_fixed']['random_p25_return_pct'])}</td>"
        f"<td>{fmt_count(row['changed_vs_fixed']['count'])}</td></tr>"
        for row in payload["strategies"][1:]
    )
    change_blocks = []
    for row in payload["strategies"][1:]:
        improved = "".join(
            f"<tr><td>{html.escape(str(item['label']))}</td><td>{html.escape(str(item['unit_type']))}</td>"
            f"<td>{html.escape(str(item['signal_date']))}</td><td>{html.escape(str(item['reference_exit_date']))}<br><small>{html.escape(str(item['reference_exit_reason']))}</small></td>"
            f"<td>{html.escape(str(item['candidate_exit_date']))}<br><small>{html.escape(str(item['candidate_exit_reason']))}</small></td>"
            f"<td>{fmt_money(item['pnl_delta'])}</td></tr>"
            for item in row["changed_vs_fixed"]["top_improved"][:8]
        ) or "<tr><td colspan='6'>-</td></tr>"
        worsened = "".join(
            f"<tr><td>{html.escape(str(item['label']))}</td><td>{html.escape(str(item['unit_type']))}</td>"
            f"<td>{html.escape(str(item['signal_date']))}</td><td>{html.escape(str(item['reference_exit_date']))}<br><small>{html.escape(str(item['reference_exit_reason']))}</small></td>"
            f"<td>{html.escape(str(item['candidate_exit_date']))}<br><small>{html.escape(str(item['candidate_exit_reason']))}</small></td>"
            f"<td>{fmt_money(item['pnl_delta'])}</td></tr>"
            for item in row["changed_vs_fixed"]["top_worsened"][:8]
        ) or "<tr><td colspan='6'>-</td></tr>"
        change_blocks.append(
            f"<h2>{html.escape(row['label'])} 變動案例</h2>"
            f"<div class='note'>共 {row['changed_vs_fixed']['count']} 筆單位結果改寫，改善 {row['changed_vs_fixed']['improved_count']} 筆、惡化 {row['changed_vs_fixed']['worsened_count']} 筆，合計損益差 {fmt_money(row['changed_vs_fixed']['total_pnl_delta'])}。</div>"
            f"<div class='grid'><div class='card'><h3>改善較多的例子</h3><div class='table'><table><thead><tr><th>股票</th><th>類型</th><th>訊號日</th><th>固定版出場</th><th>動態版出場</th><th>損益差</th></tr></thead><tbody>{improved}</tbody></table></div></div>"
            f"<div class='card'><h3>惡化較多的例子</h3><div class='table'><table><thead><tr><th>股票</th><th>類型</th><th>訊號日</th><th>固定版出場</th><th>動態版出場</th><th>損益差</th></tr></thead><tbody>{worsened}</tbody></table></div></div></div>"
        )
    return f"""<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{VERSION}</title><style>
:root{{--bg:#f6f7fb;--paper:#fff;--ink:#172033;--muted:#667085;--line:#e4e7ec;--blue:#2563eb}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 system-ui,'Microsoft JhengHei',sans-serif}}header,main{{max-width:1650px;margin:auto;padding:28px 20px}}header{{border-bottom:1px solid var(--line)}}h1{{margin:0 0 8px;font-size:30px}}h2{{margin:28px 0 10px}}p{{color:var(--muted)}}.note{{border-left:4px solid var(--blue);background:#eff6ff;padding:12px 14px;margin:18px 0;border-radius:12px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px}}.card{{background:#fff;border:1px solid var(--line);border-radius:14px;padding:14px}}.table{{overflow:auto;border:1px solid var(--line);background:#fff;border-radius:12px}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}thead th{{background:#f8fafc;color:var(--muted);font-size:12px}}code{{background:#eef2ff;padding:2px 6px;border-radius:6px}}</style></head><body><header><h1>MWP-C 動態結構低點比較</h1><p>比較目前固定 structure_low，與兩種會隨走勢上移的 pivot swing low 版本。</p><div class='note'><strong>Pivot 定義：</strong>左右各 {PIVOT_LEFT_BARS}/{PIVOT_RIGHT_BARS} 根 K 確認的局部低點。第三版另加 <code>浮盈達 {int(PROFIT_GATE_PCT * 100)}%</code> 後才啟用動態抬高。三版都固定使用相同的 corrected-lifecycle MWP-C 框架：PB-V4 discount-2 母單池、MA20 5 日斜率 &gt; 0、最多 1 筆加碼、MA20 回測帶 1.9%、同股生命週期過濾與母單同步關閉加碼。</div><div class='grid'><div class='card'><h3>{html.escape(baseline['label'])}</h3><p>{html.escape(unit_cell(baseline['summary']['full_units']))}</p><p>{html.escape(random_cell(baseline['random_unit_stock_test']))}</p></div>{''.join(f"<div class='card'><h3>{html.escape(row['label'])}</h3><p>{html.escape(unit_cell(row['summary']['full_units']))}</p><p>{html.escape(random_cell(row['random_unit_stock_test']))}</p></div>" for row in payload['strategies'][1:])}</div></header><main><h2>整體比較</h2><div class='table'><table><thead><tr><th>版本</th><th>Full units</th><th>Base units</th><th>Add-on units</th><th>Random unit stock-test</th><th>有動態更新的單位</th><th>真的抬高結構低點的單位</th><th>結構轉弱出場</th><th>硬停損</th></tr></thead><tbody>{comparison_rows}</tbody></table></div><h2>相對固定版差異</h2><div class='table'><table><thead><tr><th>版本</th><th>Units 差</th><th>Full 平均差</th><th>Full 勝率差</th><th>總損益差</th><th>Random 平均差</th><th>Random p25 差</th><th>結果被改寫的單位</th></tr></thead><tbody>{delta_rows}</tbody></table></div>{''.join(change_blocks)}<p>JSON: <code>{OUT_JSON}</code>｜MD: <code>{OUT_MD}</code></p></main></body></html>"""


def render_md(payload: dict[str, Any]) -> str:
    lines = [
        "# MWP-C 動態結構低點比較",
        "",
        f"- Pivot 定義：左右各 {PIVOT_LEFT_BARS}/{PIVOT_RIGHT_BARS} 根 K 確認的局部低點。",
        f"- 第三版動態啟動門檻：浮盈達 {int(PROFIT_GATE_PCT * 100)}% 後才開始上移結構低點。",
        "",
        "## 整體結果",
    ]
    for row in payload["strategies"]:
        lines.extend([
            f"### {row['label']}",
            f"- 說明：{row['description']}",
            f"- Full units：{unit_cell(row['summary']['full_units'])}",
            f"- Base units：{unit_cell(row['summary']['base_units'])}",
            f"- Add-on units：{unit_cell(row['summary']['addon_units'])}",
            f"- Random unit stock-test：{random_cell(row['random_unit_stock_test'])}",
            f"- 動態更新單位：{row['structure_update_stats']['updated_units']}，抬高結構低點單位：{row['structure_update_stats']['raised_structure_units']}",
            f"- 出場組成：{json.dumps(row['exit_family_counts'], ensure_ascii=False)}",
            "",
        ])
    lines.append("## 相對固定版差異")
    for row in payload["strategies"][1:]:
        delta = row["delta_vs_fixed"]
        changed = row["changed_vs_fixed"]
        lines.extend([
            f"### {row['label']}",
            f"- Units 差：{delta['full_units']}",
            f"- Full 平均差：{pct(delta['full_avg_return_pct'])}",
            f"- Full 勝率差：{pct(delta['full_win_rate_pct'])}",
            f"- 總損益差：{fmt_money(delta['full_total_pnl'])}",
            f"- Random 平均差：{pct(delta['random_avg_return_pct'])}",
            f"- Random p25 差：{pct(delta['random_p25_return_pct'])}",
            f"- 被改寫單位：{changed['count']}，改善 {changed['improved_count']}，惡化 {changed['worsened_count']}，合計損益差 {fmt_money(changed['total_pnl_delta'])}",
            "",
        ])
    return "\n".join(lines) + "\n"


def main() -> None:
    strategies = [
        build_record(
            "固定 structure_low（現行版）",
            "結構低點固定鎖在訊號日至確認K區間最低 low，不會隨後續上漲而上移。",
            base_exit_fixed,
            addon_exit_fixed,
        ),
        build_record(
            "pivot swing low 動態上移",
            "用左右各 2 根 K 確認的局部低點作為新的 swing low，只允許 structure_low 往上抬高，不往下降。",
            base_exit_dynamic_pivot,
            addon_exit_dynamic_pivot,
        ),
        build_record(
            "浮盈達 15% 後才啟用 pivot swing low",
            "前段先保留原始結構空間，等單位曾出現至少 15% 浮盈後，才開始用 pivot swing low 抬高 structure_low。",
            base_exit_profit_gated_pivot,
            addon_exit_profit_gated_pivot,
        ),
    ]
    baseline = strategies[0]
    for row in strategies[1:]:
        row["delta_vs_fixed"] = summary_delta(row, baseline)
        row["changed_vs_fixed"] = changed_units(baseline, row)
    payload = {
        "version": VERSION,
        "pivot_definition": {
            "left_bars": PIVOT_LEFT_BARS,
            "right_bars": PIVOT_RIGHT_BARS,
            "profit_gate_pct": round(PROFIT_GATE_PCT * 100, 2),
        },
        "shared_rules": "Formal MWP-C framework held fixed: PB-V4 discount-2 mother pool, MA20 5-day slope > 0, max 1 add-on, MA20 retest band 1.9%, same-stock lifecycle filter, mother exit synchronizes remaining add-ons.",
        "strategies": [strip_heavy(row) for row in strategies],
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    OUT_MD.write_text(render_md(payload), encoding="utf-8")
    print(json.dumps({
        "output": str(OUT_JSON),
        "html": str(OUT_HTML),
        "strategies": [
            {
                "label": row["label"],
                "full_units": row["summary"]["full_units"],
                "random_unit_stock_test": row["random_unit_stock_test"],
                "structure_update_stats": row["structure_update_stats"],
                "delta_vs_fixed": row.get("delta_vs_fixed"),
            }
            for row in payload["strategies"]
        ],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
