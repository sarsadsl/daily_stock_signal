#!/usr/bin/env python3
"""Build tracking payload for the MWP strategy page.

The historical page URL is still `mwp_a_strategy.html`, but the active content has
been promoted to MWP-C: the return-first capped PB-V23 variant with MA20 slope filter.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPORT_DIR = Path("reports")
BACKTEST_JSON = REPORT_DIR / "mwp_c_return_first_capped.json"
TOP_LISTS_JSON = REPORT_DIR / "daily_signal_top_lists.json"
DAILY_SIGNAL_JSON = REPORT_DIR / "daily_signal_alert.json"
OUT_JSON = REPORT_DIR / "mwp_a_strategy_tracking.json"

STRATEGY_NAME = "報酬率優先低頻加碼策略"
STRATEGY_CODE = "MWP-C"
STRATEGY_CODE_MEANING = "Return-first capped Main Wave Pullback"


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def compact_summary(summary: dict[str, Any] | None) -> dict[str, Any]:
    if not summary:
        return {}
    return {
        key: summary.get(key)
        for key in (
            "trades",
            "units",
            "signals",
            "win_rate_pct",
            "avg_return_pct",
            "median_return_pct",
            "capital_return_pct",
            "best_return_pct",
            "worst_return_pct",
            "unresolved",
            "total_pnl",
            "capital_used",
        )
        if key in summary
    }


def stock_label(row: dict[str, Any]) -> str:
    name = row.get("stock_name") or ""
    return f"{row.get('stock_no', '')} {name}".strip()


def compact_unit(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "market": row.get("market"),
        "stock_no": row.get("stock_no"),
        "stock_name": row.get("stock_name"),
        "label": stock_label(row),
        "signal_date": row.get("signal_date"),
        "entry_date": row.get("entry_date"),
        "entry_price": row.get("entry_price"),
        "exit_date": row.get("exit_date"),
        "exit_price": row.get("exit_price"),
        "exit_reason": row.get("exit_reason"),
        "return_pct": row.get("return_pct"),
        "pnl": row.get("pnl"),
        "unit_type": row.get("unit_type"),
        "addon_number": row.get("addon_number"),
        "unresolved": bool(row.get("unresolved")),
        "holding_days": row.get("holding_days"),
        "source": "historical_backtest_mwp_c",
    }


def compact_package(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "market": row.get("market"),
        "stock_no": row.get("stock_no"),
        "stock_name": row.get("stock_name"),
        "label": stock_label(row),
        "signal_date": row.get("signal_date"),
        "entry_date": row.get("entry_date"),
        "base_return_pct": row.get("base_return_pct"),
        "base_exit_date": row.get("base_exit_date"),
        "base_exit_reason": row.get("base_exit_reason"),
        "addon_count": row.get("addon_count"),
        "total_units": row.get("total_units"),
        "package_return_pct": row.get("package_return_pct"),
        "total_pnl": row.get("total_pnl"),
        "unresolved": bool(row.get("unresolved")),
        "source": "historical_backtest_mwp_c",
    }


def current_daily_date(rows: list[dict[str, Any]]) -> str | None:
    dates = sorted({str(row.get("date")) for row in rows if row.get("date")})
    return dates[-1] if dates else None


def compact_daily_signal(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "market": row.get("market"),
        "stock_no": row.get("stock_no"),
        "stock_name": row.get("stock_name"),
        "label": stock_label(row),
        "date": row.get("date"),
        "strategy": row.get("strategy"),
        "reason": row.get("reason") or "、".join(row.get("reasons") or []),
        "score": row.get("score"),
        "score_label": row.get("score_label"),
        "close": row.get("close"),
        "volume": row.get("volume"),
        "ma20": row.get("ma20"),
        "ma60": row.get("ma60"),
        "volume_ratio": row.get("volume_ratio"),
        "weighted_score": row.get("weighted_score"),
        "chart_path": row.get("chart_path"),
        "tracking_note": "Daily radar pullback candidate. Not yet an exact MWP-C trigger until the MWP-C exact scanner is wired into daily sync.",
    }


def run() -> dict[str, Any]:
    backtest = load_json(BACKTEST_JSON, {})
    top_lists = load_json(TOP_LISTS_JSON, {})
    daily_rows = load_json(DAILY_SIGNAL_JSON, [])

    framework_summary = backtest.get("framework_summary", {})
    units = backtest.get("units", [])
    packages = backtest.get("packages", [])
    baseline = backtest.get("baseline_without_filter", {})

    unresolved_units = [compact_unit(row) for row in units if row.get("unresolved")]
    realized_units = [compact_unit(row) for row in units if not row.get("unresolved")]
    unresolved_packages = [compact_package(row) for row in packages if row.get("unresolved")]
    unresolved_units.sort(key=lambda row: (float(row.get("return_pct") or 0), str(row.get("signal_date") or "")), reverse=True)
    realized_units.sort(key=lambda row: (str(row.get("exit_date") or ""), float(row.get("pnl") or 0)), reverse=True)
    unresolved_packages.sort(key=lambda row: (float(row.get("package_return_pct") or 0), str(row.get("signal_date") or "")), reverse=True)

    pullback_radar = [compact_daily_signal(row) for row in (top_lists.get("pullback") or [])]
    daily_date = current_daily_date(daily_rows if isinstance(daily_rows, list) else [])

    strategy_source = backtest.get("strategy", {})
    strategy = {
        "name": STRATEGY_NAME,
        "code": STRATEGY_CODE,
        "code_meaning": STRATEGY_CODE_MEANING,
        "title": f"{STRATEGY_CODE} {STRATEGY_NAME}",
        "status": "Backtest candidate; ready for forward paper-tracking.",
        "description": "MWP-C 是報酬率優先、低頻、總進場單位壓在 300 以內的主升段回檔加碼策略。它以 PB-V23 原始母單池為基礎，最多加碼 1 次，MA20 retest band 1.9%，並新增 MA20 近 5 日斜率 > 0 的生命週期濾網。",
        "entry_rule": "PB-V23 原始母單池；整個母單生命週期必須通過 MA20 近 5 日斜率 > 0 濾網；若未通過，母單與其所有加碼單都排除。",
        "addon_rule": "每個母單生命週期最多加碼 1 次；加碼條件為 MA20 retest band 1.9%；加碼只允許在母單仍持有時發生；加碼日前 10 個交易日內不得已有同股買進或買進候選訊號；母單出場時仍在場的加碼單同步出場。",
        "risk_rule": "母單 hard stop 7%；加碼單使用 15% close-based catastrophic stop；母單出場會同步結束該生命週期所有仍在場加碼單。",
        "technical_filter": "MA20 近 5 日斜率 > 0",
        "source_title": strategy_source.get("title"),
    }

    return {
        "strategy": strategy,
        "backtest": {
            "baseline_full_units": compact_summary(baseline.get("full_units")),
            "baseline_random_unit_stock_test": baseline.get("random_unit_stock_test"),
            "baseline_random_package_stock_test": baseline.get("random_package_stock_test"),
            "mwp_c_full_units": compact_summary((framework_summary.get("chronological_unit") or {}).get("full")),
            "mwp_c_full_packages": compact_summary((framework_summary.get("chronological_package") or {}).get("full")),
            "mwp_c_base_units": compact_summary(framework_summary.get("base_units")),
            "mwp_c_addon_units": compact_summary(framework_summary.get("addon_units")),
            "mwp_c_random_unit_stock_test": (backtest.get("unit_random_statistics") or {}).get("stock_test"),
            "mwp_c_random_package_stock_test": (backtest.get("package_random_statistics") or {}).get("stock_test"),
            "selected_lifecycles": framework_summary.get("selected_lifecycles"),
            "selected_units": framework_summary.get("selected_units"),
            "excluded_lifecycles": framework_summary.get("excluded_lifecycles"),
            "excluded_units": framework_summary.get("excluded_units"),
            "stop_loss_lifecycle_rate_pct": framework_summary.get("stop_loss_lifecycle_rate_pct"),
            "lifecycle_violations": framework_summary.get("lifecycle_violations"),
            # Backward-compatible aliases used by older dashboard code.
            "no_addon_full": compact_summary(baseline.get("full_units")),
            "no_addon_random_stock_test": baseline.get("random_unit_stock_test"),
            "addon_full_units": compact_summary((framework_summary.get("chronological_unit") or {}).get("full")),
            "addon_base_units": compact_summary(framework_summary.get("base_units")),
            "addon_addon_units": compact_summary(framework_summary.get("addon_units")),
            "addon_random_unit_stock_test": (backtest.get("unit_random_statistics") or {}).get("stock_test"),
            "addon_random_package_stock_test": (backtest.get("package_random_statistics") or {}).get("stock_test"),
        },
        "tracking": {
            "as_of_daily_signal_date": daily_date,
            "formal_forward_records": [],
            "formal_forward_note": "The page is ready for MWP-C forward paper-tracking. Exact MWP-C daily triggers will be appended here after the exact scanner is wired into daily sync.",
            "daily_pullback_radar_candidates": pullback_radar,
            "historical_unresolved_units": unresolved_units,
            "historical_realized_units": realized_units,
            "historical_unresolved_packages": unresolved_packages,
        },
        "source_reports": {
            "backtest": "mwp_c_return_first_capped.json",
            "baseline_reference": "mwp_c_return_first_capped.json#baseline_without_filter",
            "technical_filter_experiment": "mwp_technical_filter_experiment.json",
            "daily_radar": "daily_signal_top_lists.json",
        },
    }


def main() -> None:
    payload = run()
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(OUT_JSON),
        "strategy": payload["strategy"],
        "backtest": payload["backtest"],
        "tracking_counts": {
            "daily_pullback_radar": len(payload["tracking"]["daily_pullback_radar_candidates"]),
            "historical_unresolved_units": len(payload["tracking"]["historical_unresolved_units"]),
            "historical_realized_units": len(payload["tracking"]["historical_realized_units"]),
            "historical_unresolved_packages": len(payload["tracking"]["historical_unresolved_packages"]),
            "formal_forward_records": len(payload["tracking"]["formal_forward_records"]),
        },
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
