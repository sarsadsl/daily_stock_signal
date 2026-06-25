#!/usr/bin/env python3
"""Build tracking payload for MWP-A strategy page."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPORT_DIR = Path("reports")
BACKTEST_JSON = REPORT_DIR / "pullback_v9_fixed_addon_random_splits.json"
NO_ADDON_JSON = REPORT_DIR / "pullback_v9_fixed_random_splits.json"
TOP_LISTS_JSON = REPORT_DIR / "daily_signal_top_lists.json"
DAILY_SIGNAL_JSON = REPORT_DIR / "daily_signal_alert.json"
OUT_JSON = REPORT_DIR / "mwp_a_strategy_tracking.json"

STRATEGY_NAME = "主升回檔加碼策略"
STRATEGY_CODE = "MWP-A"
STRATEGY_CODE_MEANING = "Main Wave Pullback Add-on"


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
        "source": "historical_backtest",
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
        "source": "historical_backtest",
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
        "tracking_note": "Daily radar pullback candidate. Not yet an exact MWP-A trigger until the V9+ exact scanner is wired into daily sync.",
    }


def run() -> dict[str, Any]:
    backtest = load_json(BACKTEST_JSON, {})
    no_addon = load_json(NO_ADDON_JSON, {})
    top_lists = load_json(TOP_LISTS_JSON, {})
    daily_rows = load_json(DAILY_SIGNAL_JSON, [])

    framework_summary = backtest.get("framework_summary", {})
    units = backtest.get("units", [])
    packages = backtest.get("packages", [])
    unresolved_units = [compact_unit(row) for row in units if row.get("unresolved")]
    realized_units = [compact_unit(row) for row in units if not row.get("unresolved")]
    unresolved_packages = [compact_package(row) for row in packages if row.get("unresolved")]
    unresolved_units.sort(key=lambda row: (float(row.get("return_pct") or 0), str(row.get("signal_date") or "")), reverse=True)
    realized_units.sort(key=lambda row: (str(row.get("exit_date") or ""), float(row.get("pnl") or 0)), reverse=True)
    unresolved_packages.sort(key=lambda row: (float(row.get("package_return_pct") or 0), str(row.get("signal_date") or "")), reverse=True)

    pullback_radar = [compact_daily_signal(row) for row in (top_lists.get("pullback") or [])]
    daily_date = current_daily_date(daily_rows if isinstance(daily_rows, list) else [])

    return {
        "strategy": {
            "name": STRATEGY_NAME,
            "code": STRATEGY_CODE,
            "code_meaning": STRATEGY_CODE_MEANING,
            "title": f"{STRATEGY_NAME} {STRATEGY_CODE}",
            "status": "Forward paper-trading candidate; not production-ready.",
            "description": "固定 V9+ 股池與 weekly_core 母單出場，使用 PB-V23 MA20 retest 加碼邏輯，目標是追蹤主升段回檔後的大波段機會。",
            "entry_rule": "ABC 快速回檔｜不限大盤｜不限週線｜月線趨勢多頭｜貼近 MA20｜每日全部收；同股母單未出場不得重複開母單，且前 10 個交易日內已有同股買進則跳過。",
            "addon_rule": "母單仍持有時才允許 MA20 retest 加碼；加碼日前 10 個交易日內不得已有同股買進或買進候選訊號；最多 5 次；加碼單用結構共振停損與 15% close-based catastrophic stop；母單停損維持 7%；母單出場時仍在場的加碼單同步出場。",
        },
        "backtest": {
            "no_addon_full": compact_summary(no_addon.get("full_summary")),
            "no_addon_random_stock_test": (no_addon.get("statistics") or {}).get("stock_test"),
            "addon_full_units": compact_summary((framework_summary.get("chronological_unit") or {}).get("full")),
            "addon_base_units": compact_summary(framework_summary.get("base_units")),
            "addon_addon_units": compact_summary(framework_summary.get("addon_units")),
            "addon_random_unit_stock_test": (backtest.get("unit_random_statistics") or {}).get("stock_test"),
            "addon_random_package_stock_test": (backtest.get("package_random_statistics") or {}).get("stock_test"),
        },
        "tracking": {
            "as_of_daily_signal_date": daily_date,
            "formal_forward_records": [],
            "formal_forward_note": "The page is ready for forward tracking. Exact MWP-A daily triggers will be appended here after the V9+ exact scanner is wired into daily sync.",
            "daily_pullback_radar_candidates": pullback_radar,
            "historical_unresolved_units": unresolved_units,
            "historical_realized_units": realized_units,
            "historical_unresolved_packages": unresolved_packages,
        },
        "source_reports": {
            "backtest": "pullback_v9_fixed_addon_random_splits.json",
            "no_addon_reference": "pullback_v9_fixed_random_splits.json",
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
