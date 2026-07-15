#!/usr/bin/env python3
"""Build the MWP-C tracking payload.

The public page is now `mwp_c_strategy.html`. This builder keeps two streams separate:

- daily radar: recalculated after each data refresh, only for today's setup/status
- formal forward records: append-only paper-tracking cohorts keyed by signal date
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import analyze_pullback_pb_v23_independent_lifecycle as pbv23
from analyze_mwp_c_consolidation_parameter_sweep import make_base_exit
from alert_signals import group_matches_for_display
from analyze_mwp_technical_filter_experiment import BASE_VARIANT, indicator_pack, value_at
from analyze_recent_all_signal_backtest import detect_category
from analyze_recent_breakout_backtest import MIN_SIGNAL_VOLUME_SHARES
from analyze_pullback_pb_v20_fuzzy_addon import retest_ok
from run_market_backtest import STRATEGIES, Row, csv_files, prepare, read_rows
from signal_scoring import signal_score

REPORT_DIR = Path("reports")
BACKTEST_JSON = REPORT_DIR / "mwp_c_return_first_capped.json"
OUT_JSON = REPORT_DIR / "mwp_a_strategy_tracking.json"
FORWARD_JSON = REPORT_DIR / "mwp_c_forward_records.json"

STRATEGY_NAME = "報酬優先上限型主升段回檔策略"
STRATEGY_CODE = "MWP-C"
STRATEGY_CODE_MEANING = "報酬優先上限型主升段回檔策略"
ENTRY_DISCOUNT_PCT = 0.02
BASE_HARD_STOP_PCT = 0.07
ADDON_CATASTROPHIC_CLOSE_PCT = 0.15
ADDON_LIMIT_PER_MOTHER = int(BASE_VARIANT["max_addons"])
ADDON_MA20_BAND_PCT = float(BASE_VARIANT["ma20_band_pct"])
ADDON_MIN_WAIT = 2
ADDON_MAX_WAIT = 8
COOLDOWN_TRADING_DAYS = 10
BASE_EXIT_POLICY = make_base_exit(30, "high")
FORWARD_ACTIVE_STATUSES = {"持有中", "已進場", "open"}
FORWARD_PENDING_STATUSES = {"待次日開盤", "pending_next_open"}
FORWARD_FAILED_ENTRY_STATUSES = {"次日開盤未達進場條件", "entry_filter_failed"}
FORWARD_DUPLICATE_STATUS = "同股生命週期重複建單（已排除）"


SeriesMap = dict[tuple[str, str], tuple[list[Row], dict[str, list[float | None]], dict[str, int]]]

LEGACY_STATUS_MAP = {
    "pending_next_open": "待次日開盤",
    "open": "持有中",
    "exited": "已出場",
    "entry_filter_failed": "次日開盤未達進場條件",
}


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_status_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    return LEGACY_STATUS_MAP.get(value, value)


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


def stock_key(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row.get("market") or "").upper(), str(row.get("stock_no") or ""))


def lifecycle_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (*stock_key(row), str(row.get("signal_date") or ""))


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


def make_series_map() -> SeriesMap:
    output: SeriesMap = {}
    for path in csv_files():
        rows = read_rows(path)
        if len(rows) < 80:
            continue
        key = (rows[-1].market.upper(), rows[-1].stock_no)
        output[key] = (rows, prepare(rows), {row.date: index for index, row in enumerate(rows)})
    return output


def find_series(series: SeriesMap, market: str, stock_no: str) -> tuple[list[Row], dict[str, list[float | None]], dict[str, int]] | None:
    return pbv23.find_series(series, market, stock_no)


def latest_market_date(series: SeriesMap) -> str | None:
    dates = sorted({rows[-1].date for rows, _, _ in series.values() if rows})
    return dates[-1] if dates else None


def ma20_slope5_pct(rows: list[Row], index: int) -> float | None:
    indicators = indicator_pack(rows)
    ma20 = value_at(indicators["ma20"], index)
    ma20_5 = value_at(indicators["ma20"], index - 5)
    if not ma20 or not ma20_5:
        return None
    return round((ma20 / ma20_5 - 1) * 100, 4)


def make_match(path: Path, rows: list[Row], indicators: dict[str, list[float | None]], index: int, strategy: str, reason: str) -> dict[str, Any]:
    row = rows[index]
    return {
        "market": row.market.upper(),
        "stock_no": row.stock_no,
        "stock_name": row.stock_name,
        "date": row.date,
        "strategy": strategy,
        "reason": reason,
        **signal_score(rows, indicators, index, reason),
        "close": row.close,
        "volume": row.volume,
        "ma5": indicators["ma5"][index],
        "ma10": indicators["ma10"][index],
        "ma20": indicators["ma20"][index],
        "ma60": indicators["ma60"][index],
        "source": str(path),
        "row_index": index,
    }


def latest_pullback_matches(target_date: str) -> list[dict[str, Any]]:
    raw_matches: list[dict[str, Any]] = []
    path_by_stock: dict[tuple[str, str], Path] = {}
    for path in csv_files():
        rows = read_rows(path)
        if len(rows) < 80 or rows[-1].date != target_date:
            continue
        indicators = prepare(rows)
        index = len(rows) - 1
        path_by_stock[(rows[-1].market.upper(), rows[-1].stock_no)] = path
        if rows[index].volume < MIN_SIGNAL_VOLUME_SHARES:
            continue
        for strategy_name, signal in STRATEGIES.items():
            reason = signal(rows, indicators, index)
            if reason:
                raw_matches.append(make_match(path, rows, indicators, index, strategy_name, reason))

    grouped = group_matches_for_display(raw_matches)
    pullbacks = [item for item in grouped if detect_category(item) == "pullback"]
    for item in pullbacks:
        item["source"] = str(path_by_stock.get((str(item.get("market")).upper(), str(item.get("stock_no"))), item.get("source", "")))
        item["row_index"] = len(read_rows(Path(item["source"]))) - 1 if item.get("source") else item.get("row_index")
    return pullbacks


def active_package_by_stock(packages: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    output: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for package in packages:
        if package.get("unresolved"):
            output.setdefault(stock_key(package), []).append(package)
    return output


def recent_historical_buy_block(row: dict[str, Any], packages: list[dict[str, Any]], series: SeriesMap, signal_date: str) -> str | None:
    bundle = find_series(series, str(row.get("market")), str(row.get("stock_no")))
    if not bundle:
        return None
    _, _, dates = bundle
    signal_index = dates.get(signal_date)
    if signal_index is None:
        return None
    candidates = [
        str(package.get("entry_date"))
        for package in packages
        if stock_key(package) == stock_key(row) and str(package.get("entry_date") or "") in dates
    ]
    for date_text in candidates:
        distance = signal_index - dates[date_text]
        if 0 <= distance <= COOLDOWN_TRADING_DAYS:
            return f"same-stock buy cooldown: {date_text}"
    return None


def forward_record_entry_index(
    record: dict[str, Any],
    rows: list[Row],
    dates: dict[str, int],
    target_index: int,
) -> int | None:
    """Return a formal forward record's actual or determinable base-entry index.

    The daily radar is built before forward records are updated for the current
    market date. For a prior pending record, derive today's next-open outcome
    so its same-stock lifecycle can still block a duplicate signal.
    """

    status = normalize_status_text(record.get("status"))
    if status in FORWARD_FAILED_ENTRY_STATUSES or status == FORWARD_DUPLICATE_STATUS:
        return None

    entry_index = dates.get(str(record.get("entry_date") or ""))
    if entry_index is not None:
        return entry_index

    if status not in FORWARD_PENDING_STATUSES:
        return None

    signal_index = dates.get(str(record.get("signal_date") or ""))
    if signal_index is None:
        return None
    expected_entry_index = signal_index + 1
    if expected_entry_index > target_index or expected_entry_index >= len(rows):
        return None

    limit = float(record.get("entry_limit_price") or 0)
    if limit and rows[expected_entry_index].open > limit:
        return None
    return expected_entry_index


def forward_record_lifecycle_block(
    row: dict[str, Any],
    forward_records: list[dict[str, Any]],
    series: SeriesMap,
    signal_date: str,
) -> str | None:
    """Return a same-stock blocker from formal tracking records, if any.

    Backtest packages do not contain forward trades created after the frozen
    backtest date. Those records must therefore participate in both the active
    mother check and the same-stock buy cooldown.
    """

    bundle = find_series(series, str(row.get("market")), str(row.get("stock_no")))
    if not bundle:
        return None
    rows, _, dates = bundle
    target_index = dates.get(signal_date)
    if target_index is None:
        return None

    for record in forward_records:
        if record.get("unit_type") not in {None, "base"} or stock_key(record) != stock_key(row):
            continue
        if str(record.get("signal_date") or "") == signal_date:
            # A same-date rebuild is evaluating the record already created for
            # this candidate, so it must not block itself.
            continue

        status = normalize_status_text(record.get("status"))
        entry_index = forward_record_entry_index(record, rows, dates, target_index)
        entry_date = rows[entry_index].date if entry_index is not None else record.get("entry_date")

        if status in FORWARD_ACTIVE_STATUSES:
            return f"same-stock active formal mother: {entry_date or 'pending entry'}"

        if entry_index is not None:
            distance = target_index - entry_index
            if 0 <= distance <= COOLDOWN_TRADING_DAYS:
                return f"same-stock formal buy cooldown: {entry_date}"
    return None


def reconcile_duplicate_forward_mothers(
    records: list[dict[str, Any]],
    series: SeriesMap,
) -> bool:
    """Retire already-recorded duplicate forward mothers without deleting audit data."""

    changed = False
    accepted_by_stock: dict[tuple[str, str], list[dict[str, Any]]] = {}
    ordered = sorted(
        (record for record in records if record.get("unit_type") in {None, "base"}),
        key=lambda record: (str(record.get("signal_date") or ""), str(record.get("id") or "")),
    )

    for record in ordered:
        status = normalize_status_text(record.get("status"))
        if status in FORWARD_FAILED_ENTRY_STATUSES or status == FORWARD_DUPLICATE_STATUS:
            continue

        bundle = find_series(series, str(record.get("market")), str(record.get("stock_no")))
        if not bundle:
            continue
        rows, _, dates = bundle
        signal_date = str(record.get("signal_date") or "")
        signal_index = dates.get(signal_date)
        if signal_index is None:
            continue
        entry_index = forward_record_entry_index(record, rows, dates, signal_index)
        if entry_index is None:
            continue

        reject_reason = None
        for prior in accepted_by_stock.get(stock_key(record), []):
            prior_entry_index = forward_record_entry_index(prior, rows, dates, signal_index)
            if prior_entry_index is None:
                continue
            prior_exit_index = dates.get(str(prior.get("exit_date") or ""))
            if prior_entry_index <= signal_index and (
                prior_exit_index is None or signal_index <= prior_exit_index
            ):
                reject_reason = f"same-stock active formal mother: {rows[prior_entry_index].date}"
                break
            if 0 <= signal_index - prior_entry_index <= COOLDOWN_TRADING_DAYS:
                reject_reason = f"same-stock formal buy cooldown: {rows[prior_entry_index].date}"
                break

        if reject_reason:
            if record.get("status") != FORWARD_DUPLICATE_STATUS:
                record.update({
                    "status": FORWARD_DUPLICATE_STATUS,
                    "base_status": FORWARD_DUPLICATE_STATUS,
                    "unresolved": False,
                    "lifecycle_filter_reject_reason": reject_reason,
                })
                changed = True
            continue

        accepted_by_stock.setdefault(stock_key(record), []).append(record)
    return changed


def radar_row(kind: str, row: dict[str, Any], **extra: Any) -> dict[str, Any]:
    label = extra.pop("label", None) or stock_label(row)
    return {
        "radar_kind": kind,
        "category": kind,
        "market": row.get("market"),
        "stock_no": row.get("stock_no"),
        "stock_name": row.get("stock_name"),
        "label": label,
        "date": row.get("date") or row.get("signal_date"),
        "signal_date": row.get("signal_date") or row.get("date"),
        "strategy": row.get("strategy"),
        "reason": row.get("reason") or " / ".join(row.get("reasons") or []),
        "score": row.get("score"),
        "score_label": row.get("score_label"),
        "close": row.get("close") or row.get("signal_close"),
        "volume": row.get("volume"),
        "ma20": row.get("ma20"),
        "ma60": row.get("ma60"),
        "ma20_slope5_pct": row.get("ma20_slope5_pct"),
        "entry_limit_price": row.get("entry_limit_price"),
        "next_open": row.get("next_open"),
        "volume_ratio": row.get("volume_ratio"),
        "weighted_score": row.get("weighted_score"),
        "tracking_note": extra.pop("tracking_note", ""),
        **extra,
    }


def mother_candidate_rows(
    target_date: str,
    series: SeriesMap,
    packages: list[dict[str, Any]],
    forward_records: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    new_mothers: list[dict[str, Any]] = []
    watchlist: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    active_by_stock = active_package_by_stock(packages)
    forward_records = forward_records or []

    for item in latest_pullback_matches(target_date):
        bundle = find_series(series, str(item.get("market")), str(item.get("stock_no")))
        if not bundle:
            continue
        rows, _, dates = bundle
        signal_index = dates.get(target_date)
        if signal_index is None:
            continue
        slope = ma20_slope5_pct(rows, signal_index)
        next_open = rows[signal_index + 1].open if signal_index + 1 < len(rows) else None
        max_entry = round(float(item["close"]) * (1 - ENTRY_DISCOUNT_PCT), 4)
        failed: list[str] = []
        if slope is None or slope <= 0:
            failed.append("MA20 5-day slope <= 0")
        if next_open is not None and next_open > max_entry:
            failed.append("次日開盤價未達 2% 折價進場條件")

        enriched = {**item, "ma20_slope5_pct": slope, "entry_limit_price": max_entry, "next_open": next_open}
        active = active_by_stock.get(stock_key(item), [])
        cooldown_reason = recent_historical_buy_block(item, packages, series, target_date)
        forward_block_reason = forward_record_lifecycle_block(item, forward_records, series, target_date)
        if active:
            blocked.append(
                radar_row(
                    "cooldown_blocked",
                    enriched,
                    tracking_note="此檔個股已有母單生命週期仍在進行中，因此本次禁止重複建立新母單。",
                    block_reason=f"同股已有母單，禁止重複建單（母單進場日：{active[0].get('entry_date')}）",
                )
            )
        elif forward_block_reason:
            blocked.append(
                radar_row(
                    "cooldown_blocked",
                    enriched,
                    tracking_note="正式追蹤已有同股母單生命週期或近期買進紀錄，因此本次不建立新母單。",
                    block_reason=forward_block_reason,
                )
            )
        elif cooldown_reason and not failed:
            blocked.append(
                radar_row(
                    "cooldown_blocked",
                    enriched,
                    tracking_note="此檔個股仍在 10 個交易日同股排除期間內，因此本次不建立新母單。",
                    block_reason="同股仍在排除期間內",
                )
            )
        elif failed:
            watchlist.append(
                radar_row(
                    "watchlist_near_miss",
                    enriched,
                    tracking_note="今日有回檔訊號，但尚未完全符合 MWP-C 母單正式條件。",
                    failed_checks=failed,
                )
            )
        else:
            status = "新訊號（隔日開盤進場）" if next_open is None else "已符合進場條件"
            new_mothers.append(
                radar_row(
                    "new_mother_candidate",
                    enriched,
                    tracking_note="今日正式符合 MWP-C 母單條件，會納入今日雷達，並寫入正式追蹤名單。",
                    entry_status=status,
                )
            )
    return new_mothers, watchlist, blocked


def addon_candidate_for_package(
    package: dict[str, Any],
    series: SeriesMap,
    target_date: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if int(package.get("addon_count") or 0) >= ADDON_LIMIT_PER_MOTHER:
        return None, None
    bundle = find_series(series, str(package.get("market")), str(package.get("stock_no")))
    if not bundle:
        return None, None
    rows, indicators, dates = bundle
    latest_index = dates.get(target_date)
    signal_index = dates.get(str(package.get("signal_date")))
    base_entry_index = dates.get(str(package.get("entry_date")))
    if latest_index is None or signal_index is None or base_entry_index is None or latest_index <= base_entry_index:
        return None, None

    blocker_indices = [base_entry_index]
    for date_text in package.get("same_stock_buy_signal_entry_dates") or []:
        if str(date_text) in dates and dates[str(date_text)] < latest_index:
            blocker_indices.append(dates[str(date_text)])
    if any(0 <= latest_index - buy_index <= COOLDOWN_TRADING_DAYS for buy_index in blocker_indices):
        return None, radar_row(
            "cooldown_blocked",
            package,
            date=target_date,
            tracking_note="此檔個股的加碼訊號仍在 10 個交易日同股排除期間內，因此本次不建立加碼單。",
            block_reason="同股加碼排除期間",
        )

    if not retest_ok(rows, indicators, latest_index, ADDON_MA20_BAND_PCT):
        return None, None

    confirm_reason: str | None = None
    confirm_date: str | None = None
    start = max(base_entry_index, latest_index - ADDON_MAX_WAIT)
    end = latest_index - ADDON_MIN_WAIT
    for cursor in range(start, end + 1):
        reason = pbv23.confirmation_reason(rows, indicators, signal_index, base_entry_index, cursor, [], {})
        if reason:
            confirm_reason = reason
            confirm_date = rows[cursor].date
            break
    if not confirm_reason:
        return None, None

    candidate = radar_row(
        "addon_candidate",
        package,
        date=target_date,
        close=rows[latest_index].close,
        ma20=indicators["ma20"][latest_index],
        tracking_note="母單仍在持有中，且今日符合 MWP-C 加碼條件。",
        mother_signal_date=package.get("signal_date"),
        confirm_date=confirm_date,
        confirm_reason=confirm_reason,
        entry_status="新訊號（隔日開盤進場）" if latest_index + 1 >= len(rows) else "已符合進場條件",
        addon_number=int(package.get("addon_count") or 0) + 1,
    )
    return candidate, None


def exit_candidate_for_unit(unit: dict[str, Any], series: SeriesMap, target_date: str) -> dict[str, Any] | None:
    bundle = find_series(series, str(unit.get("market")), str(unit.get("stock_no")))
    if not bundle:
        return None
    rows, indicators, dates = bundle
    latest_index = dates.get(target_date)
    if latest_index is None:
        return None
    latest = rows[latest_index]
    entry_price = float(unit.get("entry_price") or 0)
    if entry_price <= 0:
        return None

    reason = None
    if unit.get("unit_type") == "base":
        signal_index = dates.get(str(unit.get("signal_date") or ""))
        entry_index = dates.get(str(unit.get("entry_date") or ""))
        if signal_index is None or entry_index is None:
            return None
        confirm_index, _ = pbv23.first_confirmation_index(rows, indicators, signal_index, entry_index, [], {})
        exit_data = BASE_EXIT_POLICY(entry=rows[entry_index], rows=rows, indicators=indicators, signal_index=signal_index, entry_index=entry_index, confirm_index=confirm_index)
        if not exit_data.get("unresolved") and str(exit_data.get("exit_date") or "") == target_date:
            exit_reason = str(exit_data.get("exit_reason") or "")
            if "hard_stop" in exit_reason:
                reason = "母單觸發 7% 停損"
            elif "catastrophic" in exit_reason:
                reason = "母單觸發災難停損"
            elif "consolidation_structure_close_break" in exit_reason:
                reason = "母單跌破 MA20 與 30 日整理低點，隔日開盤出場"
    else:
        if latest.close <= entry_price * (1 - ADDON_CATASTROPHIC_CLOSE_PCT):
            reason = "觸發災難停損"
        else:
            ma20 = indicators["ma20"][latest_index]
            structure_low = unit.get("structure_low")
            if ma20 and structure_low and latest.close < float(ma20) and latest.close < float(structure_low):
                reason = "跌破 MA20 與結構低點，隔日開盤出場"

    if not reason:
        return None
    return radar_row(
        "exit_candidate",
        unit,
        date=target_date,
        close=latest.close,
        ma20=indicators["ma20"][latest_index],
        tracking_note="這筆持有部位今日已進入出場觀察狀態。",
        exit_signal=reason,
        unit_type=unit.get("unit_type"),
        addon_number=unit.get("addon_number"),
    )


def build_daily_radar(
    backtest: dict[str, Any],
    series: SeriesMap,
    forward_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    target_date = latest_market_date(series)
    empty = {
        "as_of_date": target_date,
        "new_mother_candidates": [],
        "addon_candidates": [],
        "watchlist_near_misses": [],
        "exit_candidates": [],
        "cooldown_blocked": [],
        "all": [],
    }
    if not target_date:
        return empty

    packages = backtest.get("packages", [])
    units = backtest.get("units", [])
    new_mothers, watchlist, blocked = mother_candidate_rows(
        target_date,
        series,
        packages,
        forward_records,
    )

    addon_candidates: list[dict[str, Any]] = []
    for package in packages:
        if not package.get("unresolved"):
            continue
        candidate, addon_block = addon_candidate_for_package(package, series, target_date)
        if candidate:
            addon_candidates.append(candidate)
        if addon_block:
            blocked.append(addon_block)

    exit_candidates = [
        candidate
        for unit in units
        if unit.get("unresolved")
        for candidate in [exit_candidate_for_unit(unit, series, target_date)]
        if candidate
    ]

    flattened = new_mothers + addon_candidates + watchlist + exit_candidates + blocked
    return {
        "as_of_date": target_date,
        "new_mother_candidates": new_mothers,
        "addon_candidates": addon_candidates,
        "watchlist_near_misses": watchlist,
        "exit_candidates": exit_candidates,
        "cooldown_blocked": blocked,
        "all": flattened,
    }


def forward_record_id(row: dict[str, Any], unit_type: str, addon_number: int | None = None) -> str:
    suffix = f":addon:{addon_number}" if unit_type == "addon" else ":base"
    mother = row.get("mother_signal_date") or row.get("signal_date") or row.get("date")
    return f"{str(row.get('market')).upper()}:{row.get('stock_no')}:{mother}{suffix}"


def append_forward_candidates(records: list[dict[str, Any]], radar: dict[str, Any]) -> bool:
    by_id = {record.get("id"): record for record in records}
    existing = set(by_id)
    changed = False
    for row in radar.get("new_mother_candidates", []):
        record_id = forward_record_id(row, "base")
        if record_id in existing:
            record = by_id[record_id]
            for key in ("signal_close", "entry_limit_price", "ma20_slope5_pct"):
                if record.get(key) is None and row.get(key) is not None:
                    record[key] = row.get(key)
                    changed = True
            continue
        records.append({
            "id": record_id,
            "source": "mwp_c_exact_daily_scanner",
            "status": "待次日開盤",
            "base_status": "待次日開盤",
            "addon_status": "-",
            "unit_type": "base",
            "market": row.get("market"),
            "stock_no": row.get("stock_no"),
            "stock_name": row.get("stock_name"),
            "label": row.get("label"),
            "signal_date": row.get("signal_date"),
            "signal_close": row.get("close"),
            "entry_limit_price": row.get("entry_limit_price"),
            "ma20_slope5_pct": row.get("ma20_slope5_pct"),
            "created_from_radar_date": radar.get("as_of_date"),
            "unresolved": True,
        })
        existing.add(record_id)
        changed = True

    for row in radar.get("addon_candidates", []):
        addon_number = int(row.get("addon_number") or 1)
        record_id = forward_record_id(row, "addon", addon_number)
        if record_id in existing:
            continue
        records.append({
            "id": record_id,
            "source": "mwp_c_exact_daily_scanner",
            "status": "待次日開盤",
            "base_status": "-",
            "addon_status": "待次日開盤",
            "unit_type": "addon",
            "addon_number": addon_number,
            "market": row.get("market"),
            "stock_no": row.get("stock_no"),
            "stock_name": row.get("stock_name"),
            "label": row.get("label"),
            "signal_date": row.get("signal_date"),
            "mother_signal_date": row.get("mother_signal_date"),
            "entry_trigger_date": radar.get("as_of_date"),
            "confirm_date": row.get("confirm_date"),
            "confirm_reason": row.get("confirm_reason"),
            "created_from_radar_date": radar.get("as_of_date"),
            "unresolved": True,
        })
        existing.add(record_id)
        changed = True
    return changed


def update_forward_record(record: dict[str, Any], series: SeriesMap) -> bool:
    if record.get("status") in {"已出場", "次日開盤未達進場條件", FORWARD_DUPLICATE_STATUS}:
        return False
    bundle = find_series(series, str(record.get("market")), str(record.get("stock_no")))
    if not bundle:
        return False
    rows, indicators, dates = bundle
    signal_date = str(record.get("signal_date") or record.get("mother_signal_date") or "")
    signal_index = dates.get(signal_date)
    if signal_index is None:
        return False

    changed = False
    entry_index = dates.get(str(record.get("entry_date") or ""))
    if entry_index is None and signal_index + 1 < len(rows):
        entry_index = signal_index + 1
        entry = rows[entry_index]
        if record.get("unit_type") == "base":
            limit = float(record.get("entry_limit_price") or 0)
            if limit and entry.open > limit:
                record.update({
                    "status": "次日開盤未達進場條件",
                    "base_status": "次日開盤未達進場條件",
                    "entry_date": entry.date,
                    "entry_price": round(entry.open, 4),
                    "unresolved": False,
                })
                return True
        record.update({
            "status": "持有中",
            "base_status": "持有中" if record.get("unit_type") == "base" else record.get("base_status", "-"),
            "addon_status": "持有中" if record.get("unit_type") == "addon" else record.get("addon_status", "-"),
            "entry_date": entry.date,
            "entry_price": round(entry.open, 4),
            "unresolved": True,
        })
        changed = True

    if entry_index is None or record.get("status") != "持有中":
        return changed

    entry = rows[entry_index]
    if record.get("unit_type") == "base":
        confirm_index, confirm_reason = pbv23.first_confirmation_index(rows, indicators, signal_index, entry_index, [], {})
        exit_data = BASE_EXIT_POLICY(entry, rows, indicators, signal_index, entry_index, confirm_index)
        if confirm_reason and not record.get("confirm_reason"):
            record["confirm_reason"] = confirm_reason
            record["confirm_date"] = rows[confirm_index].date if confirm_index is not None else None
            changed = True
    else:
        confirm_index = dates.get(str(record.get("confirm_date") or ""))
        if confirm_index is None:
            return changed
        exit_data = pbv23.structure_addon_exit(entry, rows, indicators, signal_index, entry_index, confirm_index)

    record["unrealized_return_pct"] = round((rows[-1].close / entry.open - 1) * 100, 2)
    changed = True
    if not exit_data.get("unresolved") and exit_data.get("exit_reason") != "latest_close":
        record.update({
            "status": "已出場",
            "base_status": "已出場" if record.get("unit_type") == "base" else record.get("base_status", "-"),
            "addon_status": "已出場" if record.get("unit_type") == "addon" else record.get("addon_status", "-"),
            "exit_date": exit_data.get("exit_date"),
            "exit_price": exit_data.get("exit_price"),
            "exit_reason": exit_data.get("exit_reason"),
            "return_pct": exit_data.get("return_pct"),
            "holding_days": exit_data.get("holding_days"),
            "unresolved": False,
        })
    for key in ("initial_structure_low", "final_structure_low", "dynamic_structure_update_count", "dynamic_structure_policy"):
        if exit_data.get(key) is not None and record.get(key) != exit_data.get(key):
            record[key] = exit_data.get(key)
            changed = True
    return changed


def sync_forward_records(
    radar: dict[str, Any],
    series: SeriesMap,
    records: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if records is None:
        records = load_json(FORWARD_JSON, [])
    changed = append_forward_candidates(records, radar)
    for record in records:
        for key in ("status", "base_status", "addon_status"):
            normalized = normalize_status_text(record.get(key))
            if normalized != record.get(key):
                record[key] = normalized
                changed = True
        changed = update_forward_record(record, series) or changed
    changed = reconcile_duplicate_forward_mothers(records, series) or changed
    records.sort(key=lambda row: (str(row.get("signal_date") or ""), str(row.get("id") or "")), reverse=True)
    if changed or not FORWARD_JSON.exists():
        write_json(FORWARD_JSON, records)
    return records


def build_strategy(backtest: dict[str, Any]) -> dict[str, Any]:
    strategy_source = backtest.get("strategy", {})
    return {
        "name": STRATEGY_NAME,
        "code": STRATEGY_CODE,
        "code_meaning": STRATEGY_CODE_MEANING,
        "title": f"{STRATEGY_CODE} {STRATEGY_NAME}",
        "status": "回測版本已確立，追蹤中。",
        "description": "MWP-C 先從主升段回檔訊號中，保留次日開盤相對訊號日收盤折價 2% 的母單候選，再套用 MA20 5 日斜率濾網與低頻加碼規則。每個母單生命週期最多 1 筆加碼，MA20 回測帶 1.9%，並把母單出場升級成 30 日整理低點保護，正式回測的總進場單位控制在 300 以內。",
        "entry_rule": "母單訊號來自主升段中的回檔買點掃描；股價需出現符合條件的回檔型態，並通過 MA20 5 日斜率大於 0、同股生命週期乾淨、以及 10 個交易日同股排除期間等檢查。正式進場還必須滿足次一交易日開盤價 <= 訊號日收盤價 x 0.98。",
        "main_uptrend_pullback_items": [
            "股價原本就處於主升段：20MA > 60MA，收盤價位於 60MA 之上，且 60MA 近 20 個交易日斜率 >= 3%。",
            "近一段時間曾出現突破或轉強跡象，不是長期弱勢後的隨機反彈。",
            "回檔型態一：回測 20MA 附近後守住，條件可寫成 low <= 20MA x 1.03 且 close >= 20MA x 0.98。",
            "回檔型態二：前一天收盤跌到 20MA 下方，今天重新收回 20MA 之上。",
            "回檔型態三：回測 10MA 後止穩，條件可寫成 low <= 10MA x 1.02、close >= 10MA、close >= open，且最近 3 天形成新的短線回檔低點。",
            "月線回檔型態還要搭配月線結構沒有剛發生明顯轉弱，避免把趨勢已壞掉的個股當成健康回檔。",
        ],
        "entry_rule_items": [
            "必須先出現上面任一種主升段回檔型態。",
            "20MA 5 日斜率 > 0。",
            "同一檔股票不能已有仍在進行中的母單生命週期。",
            "同一檔股票需通過 10 個交易日同股排除期間，避免太密集重複進場。",
            "正式進場還必須滿足次一交易日開盤價 <= 訊號日收盤價 x 0.98。",
        ],
        "addon_rule": "加碼訊號只允許出現在母單仍持有期間；每個母單生命週期最多 1 筆加碼，必須回測 MA20 1.9% 範圍內，且前 10 個交易日不能有同股買進或買進候選。加碼單本身仍沿用原本固定結構低點，不跟著 30 日整理低點一起上移。",
        "risk_rule": "母單有 7% 硬停損；母單只有在盤中高點突破前一段 30 日整理區高點後，才會把那段 30 日區間低點上移成新的防守線；母單收盤跌破 MA20 與最新 30 日整理低點時，隔日開盤出場。加碼單仍採固定結構低點與 15% 收盤災難停損；母單出場時會同步關閉所有加碼單。",
        "risk_rule_items": [
            "母單進場後立即有 7% 硬停損；若隔日跳空低於停損價，則以開盤價出場。",
            "母單若盤中高點突破前一段 30 日整理區高點，就把那段 30 日區間最低 low 上移成新的整理低點防守線。",
            "母單收盤若同時跌破 MA20 與最新 30 日整理低點，採隔日開盤出場。",
            "加碼單仍沿用原本固定結構低點；收盤跌破 MA20 與固定結構低點時出場，另保留 15% 收盤災難停損。",
            "只要母單先出場，所有仍持有中的加碼單都會同步關閉。",
        ],
        "take_profit_rule": "目前沒有獨立的固定百分比停利，也沒有到價就先落袋的機械式停利。MWP-C 的獲利母單原則上續抱，只有在走出新的 30 日整理區並再次突破後，防守線才會往上抬；之後若收盤跌破 MA20 與最新整理低點，才在隔日開盤出場。若到資料截止日仍未觸發，回測就先以最新收盤價估值。",
        "technical_filter": "MA20 5 日斜率大於 0",
        "source_title": strategy_source.get("title"),
    }


def run() -> dict[str, Any]:
    backtest = load_json(BACKTEST_JSON, {})
    framework_summary = backtest.get("framework_summary", {})
    units = backtest.get("units", [])
    packages = backtest.get("packages", [])
    baseline = backtest.get("baseline_without_filter", {})
    series = make_series_map()
    forward_records = load_json(FORWARD_JSON, [])
    radar = build_daily_radar(backtest, series, forward_records)
    forward_records = sync_forward_records(radar, series, forward_records)

    unresolved_units = [compact_unit(row) for row in units if row.get("unresolved")]
    realized_units = [compact_unit(row) for row in units if not row.get("unresolved")]
    unresolved_packages = [compact_package(row) for row in packages if row.get("unresolved")]
    unresolved_units.sort(key=lambda row: (float(row.get("return_pct") or 0), str(row.get("signal_date") or "")), reverse=True)
    realized_units.sort(key=lambda row: (str(row.get("exit_date") or ""), float(row.get("pnl") or 0)), reverse=True)
    unresolved_packages.sort(key=lambda row: (float(row.get("package_return_pct") or 0), str(row.get("signal_date") or "")), reverse=True)

    return {
        "strategy": build_strategy(backtest),
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
            "no_addon_full": compact_summary(baseline.get("full_units")),
            "no_addon_random_stock_test": baseline.get("random_unit_stock_test"),
            "addon_full_units": compact_summary((framework_summary.get("chronological_unit") or {}).get("full")),
            "addon_base_units": compact_summary(framework_summary.get("base_units")),
            "addon_addon_units": compact_summary(framework_summary.get("addon_units")),
            "addon_random_unit_stock_test": (backtest.get("unit_random_statistics") or {}).get("stock_test"),
            "addon_random_package_stock_test": (backtest.get("package_random_statistics") or {}).get("stock_test"),
        },
        "tracking": {
            "as_of_daily_signal_date": radar.get("as_of_date"),
            "daily_mwp_c_radar": radar,
            "daily_pullback_radar_candidates": radar.get("all", []),
            "formal_forward_records": forward_records,
            "formal_forward_note": "這裡只記錄正式追蹤名單。訊號一旦在當日成立，就以該訊號日鎖定 cohort，之後只用未來資料更新進場、持有、出場與報酬，不回頭補做事後挑選。",
            "historical_unresolved_units": unresolved_units,
            "historical_realized_units": realized_units,
            "historical_unresolved_packages": unresolved_packages,
        },
        "source_reports": {
            "backtest": "mwp_c_return_first_capped.json",
            "baseline_reference": "mwp_c_return_first_capped.json#baseline_without_filter",
            "technical_filter_experiment": "mwp_technical_filter_experiment.json",
            "daily_radar": "由 build_mwp_a_strategy_tracking.py 內的 MWP-C 精準掃描器產生",
            "formal_forward_records": "mwp_c_forward_records.json",
        },
    }


def main() -> None:
    payload = run()
    write_json(OUT_JSON, payload)
    radar = payload["tracking"]["daily_mwp_c_radar"]
    print(json.dumps({
        "output": str(OUT_JSON),
        "forward_records": str(FORWARD_JSON),
        "strategy": payload["strategy"]["code"],
        "tracking_counts": {
            "new_mother_candidates": len(radar["new_mother_candidates"]),
            "addon_candidates": len(radar["addon_candidates"]),
            "watchlist_near_misses": len(radar["watchlist_near_misses"]),
            "exit_candidates": len(radar["exit_candidates"]),
            "cooldown_blocked": len(radar["cooldown_blocked"]),
            "formal_forward_records": len(payload["tracking"]["formal_forward_records"]),
            "historical_unresolved_units": len(payload["tracking"]["historical_unresolved_units"]),
            "historical_realized_units": len(payload["tracking"]["historical_realized_units"]),
        },
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
