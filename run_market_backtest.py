#!/usr/bin/env python3
"""Run TSMC and Phison strategy backtests across all currently available CSV files."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


DATA_DIRS = [Path("data/all_twse"), Path("data/all_tpex")]
SINGLE_FILES = [
    Path("data/twse_2330_2025-05-29_2026-05-29.csv"),
    Path("data/tpex_8299_2025-05-29_2026-05-29.csv"),
]


@dataclass
class Row:
    market: str
    stock_no: str
    stock_name: str
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


def read_rows(path: Path) -> list[Row]:
    def to_float(value: str) -> float | None:
        text = value.replace(",", "").strip()
        if not text or text in {"--", "---"}:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    def to_int(value: str) -> int:
        text = value.replace(",", "").strip()
        if not text or text in {"--", "---"}:
            return 0
        return int(float(text))

    with path.open("r", encoding="utf-8-sig", newline="") as csvfile:
        reader = csv.DictReader(csvfile)
        rows = []
        for row in reader:
            open_price = to_float(row["open"])
            high = to_float(row["high"])
            low = to_float(row["low"])
            close = to_float(row["close"])
            if None in {open_price, high, low, close}:
                continue
            rows.append(
                Row(
                    market=row["market"],
                    stock_no=row["stock_no"],
                    stock_name=row["stock_name"],
                    date=row["date"],
                    open=float(open_price),
                    high=float(high),
                    low=float(low),
                    close=float(close),
                    volume=to_int(row["volume_shares"]),
                )
            )
    rows.sort(key=lambda row: row.date)
    return rows


def moving_average(values: list[float], window: int) -> list[float | None]:
    total = 0.0
    output: list[float | None] = []
    for index, value in enumerate(values):
        total += value
        if index >= window:
            total -= values[index - window]
        output.append(total / window if index >= window - 1 else None)
    return output


def value_at(series: list[float | None], index: int) -> float | None:
    return series[index] if 0 <= index < len(series) else None


def is_rising(series: list[float | None], index: int, lookback: int = 5) -> bool:
    now = value_at(series, index)
    before = value_at(series, index - lookback)
    return now is not None and before is not None and now > before


def slope_pct(series: list[float | None], index: int, lookback: int = 20) -> float | None:
    now = value_at(series, index)
    before = value_at(series, index - lookback)
    if now is None or before is None or before == 0:
        return None
    return now / before - 1


def crossed_below(rows: list[Row], series: list[float | None], index: int) -> bool:
    now = value_at(series, index)
    prev = value_at(series, index - 1)
    return now is not None and prev is not None and rows[index].close < now and rows[index - 1].close >= prev


def makes_fresh_pullback_low(rows: list[Row], index: int, lookback: int = 3) -> bool:
    start = max(0, index - lookback)
    if start >= index:
        return False
    return rows[index].low <= min(row.low for row in rows[start:index])


def crossed_between(series_a: list[float | None], series_b: list[float | None], index: int, lookback: int = 5) -> bool:
    start = max(1, index - lookback + 1)
    for cursor in range(start, index + 1):
        now_a = value_at(series_a, cursor)
        now_b = value_at(series_b, cursor)
        prev_a = value_at(series_a, cursor - 1)
        prev_b = value_at(series_b, cursor - 1)
        if None in {now_a, now_b, prev_a, prev_b}:
            continue
        now_diff = float(now_a) - float(now_b)
        prev_diff = float(prev_a) - float(prev_b)
        if now_diff == 0 or prev_diff == 0 or (now_diff > 0) != (prev_diff > 0):
            return True
    return False


def monthly_pullback_structure_ok(indicators: dict[str, list[float | None]], index: int) -> bool:
    ma5 = value_at(indicators["ma5"], index)
    ma10 = value_at(indicators["ma10"], index)
    ma20 = value_at(indicators["ma20"], index)
    if ma5 is None or ma10 is None or ma20 is None or ma20 <= 0:
        return False
    has_monthly_gap = ma10 >= ma20 * 1.05
    recent_monthly_cross = crossed_between(indicators["ma5"], indicators["ma20"], index, 5) or crossed_between(
        indicators["ma10"], indicators["ma20"], index, 5
    )
    return ma5 > ma20 and ma10 > ma20 and has_monthly_gap and not recent_monthly_cross


def prepare(rows: list[Row]) -> dict[str, list[float | None]]:
    closes = [row.close for row in rows]
    volumes = [float(row.volume) for row in rows]
    return {
        "ma5": moving_average(closes, 5),
        "ma10": moving_average(closes, 10),
        "ma20": moving_average(closes, 20),
        "ma60": moving_average(closes, 60),
        "ma120": moving_average(closes, 120),
        "vol20": moving_average(volumes, 20),
    }


def ma_bullish(indicators: dict[str, list[float | None]], index: int) -> bool:
    ma5 = value_at(indicators["ma5"], index)
    ma10 = value_at(indicators["ma10"], index)
    ma20 = value_at(indicators["ma20"], index)
    ma60 = value_at(indicators["ma60"], index)
    return (
        ma5 is not None
        and ma10 is not None
        and ma20 is not None
        and ma60 is not None
        and ma5 > ma10 > ma20 > ma60
    )


def ma_compression(indicators: dict[str, list[float | None]], index: int, threshold: float = 0.05) -> bool:
    check_index = index - 1
    values = [
        value_at(indicators["ma5"], check_index),
        value_at(indicators["ma10"], check_index),
        value_at(indicators["ma20"], check_index),
        value_at(indicators["ma60"], check_index),
    ]
    if any(value is None for value in values):
        return False
    concrete = [float(value) for value in values if value is not None]
    return max(concrete) / min(concrete) - 1 <= threshold


def recent_ma_compression(
    indicators: dict[str, list[float | None]], index: int, lookback: int = 15, threshold: float = 0.09
) -> bool:
    start = max(60, index - lookback)
    return any(ma_compression(indicators, cursor, threshold) for cursor in range(start, index + 1))


def prior_high(rows: list[Row], index: int, lookback: int) -> float | None:
    start = max(0, index - lookback)
    if start >= index:
        return None
    return max(row.high for row in rows[start:index])


def fuzzy_breakout_signal(rows: list[Row], indicators: dict[str, list[float | None]], index: int) -> str | None:
    if index < 60:
        return None
    row = rows[index]
    avg_vol = value_at(indicators["vol20"], index)
    ma5 = value_at(indicators["ma5"], index)
    ma10 = value_at(indicators["ma10"], index)
    ma20 = value_at(indicators["ma20"], index)
    ma60 = value_at(indicators["ma60"], index)
    if avg_vol is None or ma5 is None or ma10 is None or ma20 is None or ma60 is None or avg_vol <= 0:
        return None

    red_k = row.close > row.open
    body_pct = (row.close - row.open) / row.open if row.open else 0
    range_size = row.high - row.low
    close_position = (row.close - row.low) / range_size if range_size > 0 else 1
    volume_ok = row.volume >= avg_vol * 1.5
    strong_red = red_k and body_pct >= 0.03 and close_position >= 0.65
    breakout = (
        (prior_high(rows, index, 20) is not None and row.close >= float(prior_high(rows, index, 20)) * 0.99)
        or (prior_high(rows, index, 5) is not None and row.close >= float(prior_high(rows, index, 5)) * 0.985)
        or (prior_high(rows, index, 3) is not None and row.close >= float(prior_high(rows, index, 3)))
    )
    compression_base = recent_ma_compression(indicators, index, 20, 0.08)
    stands_above_mas = row.close > ma5 and row.close > ma10 and row.close > ma20 and row.close > ma60
    if volume_ok and strong_red and breakout and compression_base and stands_above_mas:
        return "均線糾結後帶量紅K"
    return None


def recent_breakout_observed(rows: list[Row], indicators: dict[str, list[float | None]], index: int) -> bool:
    start = max(60, index - 40)
    return any(fuzzy_breakout_signal(rows, indicators, cursor) for cursor in range(start, index + 1))


def main_uptrend(rows: list[Row], indicators: dict[str, list[float | None]], index: int) -> bool:
    ma20 = value_at(indicators["ma20"], index)
    ma60 = value_at(indicators["ma60"], index)
    ma60_slope = slope_pct(indicators["ma60"], index, 20)
    return (
        ma20 is not None
        and ma60 is not None
        and ma60_slope is not None
        and ma20 > ma60
        and rows[index].close > ma60
        and ma60_slope >= 0.03
        and recent_breakout_observed(rows, indicators, index)
    )


def quarterly_support_gap_reclaim_signal(rows: list[Row], indicators: dict[str, list[float | None]], index: int) -> str | None:
    if index < 120:
        return None
    row = rows[index]
    prev = rows[index - 1]
    ma5 = value_at(indicators["ma5"], index)
    ma10 = value_at(indicators["ma10"], index)
    ma20 = value_at(indicators["ma20"], index)
    ma60 = value_at(indicators["ma60"], index)
    ma120 = value_at(indicators["ma120"], index)
    vol20 = value_at(indicators["vol20"], index)
    if None in {ma5, ma10, ma20, ma60, ma120, vol20}:
        return None

    support_label = ""
    for lookback_index in range(max(120, index - 20), index + 1):
        support_ma10 = value_at(indicators["ma10"], lookback_index)
        support_ma20 = value_at(indicators["ma20"], lookback_index)
        support_ma60 = value_at(indicators["ma60"], lookback_index)
        support_ma120 = value_at(indicators["ma120"], lookback_index)
        if None in {support_ma10, support_ma20, support_ma60, support_ma120}:
            continue
        support_row = rows[lookback_index]
        tests_short_mid = (
            support_row.low <= max(float(support_ma10), float(support_ma20)) * 1.02
            and support_row.close >= min(float(support_ma10), float(support_ma20)) * 0.97
        )
        tests_quarterly = support_row.low <= float(support_ma60) * 1.035 and support_row.close >= float(support_ma60) * 0.97
        if support_row.close > float(support_ma120) and (tests_quarterly or tests_short_mid):
            support_label = "季線" if tests_quarterly else "10/20MA"

    gap_up = row.open >= prev.close * 1.015
    stands_back_on_mas = row.close > ma5 and row.close > ma10 and row.close > ma20
    holds_quarterly = row.close > ma60 and ma60 > ma120
    acceptable_k = row.close >= row.open * 0.995
    volume_alive = row.volume >= float(vol20) * 0.5
    not_too_late = row.close <= ma20 * 1.35
    if support_label and gap_up and stands_back_on_mas and holds_quarterly and acceptable_k and volume_alive and not_too_late:
        return f"{support_label}支撐後跳空站回5/10/20MA"
    return None


def main_uptrend_pullback_signal(rows: list[Row], indicators: dict[str, list[float | None]], index: int) -> str | None:
    if not main_uptrend(rows, indicators, index):
        return None
    ma10 = value_at(indicators["ma10"], index)
    ma20 = value_at(indicators["ma20"], index)
    if ma10 is None or ma20 is None:
        return None

    row = rows[index]
    prev = rows[index - 1]
    touches_20 = row.low <= ma20 * 1.03 and row.close >= ma20 * 0.98
    recovers_20 = row.close >= ma20 and prev.close < value_at(indicators["ma20"], index - 1) if value_at(indicators["ma20"], index - 1) is not None else False
    monthly_structure_ok = monthly_pullback_structure_ok(indicators, index)
    touches_10 = (
        row.low <= ma10 * 1.02
        and row.close >= ma10
        and row.close >= row.open
        and makes_fresh_pullback_low(rows, index, 3)
    )
    if monthly_structure_ok and (touches_20 or recovers_20):
        return "主升段回測月線"
    if touches_10:
        return "主升段回測10MA"
    return None


def tsmc_signal(rows: list[Row], indicators: dict[str, list[float | None]], index: int) -> str | None:
    if index < 60:
        return None
    compression_breakout = fuzzy_breakout_signal(rows, indicators, index)
    if compression_breakout:
        return compression_breakout
    quarterly_gap = quarterly_support_gap_reclaim_signal(rows, indicators, index)
    if quarterly_gap:
        return quarterly_gap
    main_pullback = main_uptrend_pullback_signal(rows, indicators, index)
    if main_pullback:
        return main_pullback
    if main_uptrend(rows, indicators, index) and ma_bullish(indicators, index) and crossed_below(rows, indicators["ma20"], index):
        return "跌破月線且均線多頭"
    if main_uptrend(rows, indicators, index) and crossed_below(rows, indicators["ma60"], index):
        return "季線上揚跌破季線"
    return None


def phison_signal(rows: list[Row], indicators: dict[str, list[float | None]], index: int) -> str | None:
    if index < 60:
        return None
    compression_breakout = fuzzy_breakout_signal(rows, indicators, index)
    if compression_breakout:
        return compression_breakout
    quarterly_gap = quarterly_support_gap_reclaim_signal(rows, indicators, index)
    if quarterly_gap:
        return quarterly_gap
    main_pullback = main_uptrend_pullback_signal(rows, indicators, index)
    if main_pullback:
        return main_pullback
    avg_vol = value_at(indicators["vol20"], index)
    ma20 = value_at(indicators["ma20"], index)
    ma60 = value_at(indicators["ma60"], index)
    prev_ma20 = value_at(indicators["ma20"], index - 1)
    red_k = rows[index].close > rows[index].open
    trend_ok = (
        ma20 is not None
        and ma60 is not None
        and ma20 > ma60
        and rows[index].close > ma60
        and is_rising(indicators["ma60"], index, 10)
    )
    volume_red_k = (
        avg_vol is not None
        and red_k
        and rows[index].volume > avg_vol * 1.8
        and rows[index].close > rows[index - 1].high
    )
    gap_red_k = (
        avg_vol is not None
        and red_k
        and rows[index].open > rows[index - 1].high
        and rows[index].volume > avg_vol * 1.2
    )
    compression_break = ma_compression(indicators, index) and (volume_red_k or gap_red_k)
    ma_rising = (
        trend_ok
        and is_rising(indicators["ma5"], index, 5)
        and is_rising(indicators["ma20"], index, 5)
    )
    first_month_retest = (
        ma20 is not None
        and prev_ma20 is not None
        and rows[index].low <= ma20 * 1.02
        and rows[index].close >= ma20
        and rows[index - 1].low > prev_ma20 * 1.02
    )
    if main_uptrend(rows, indicators, index) and ma_rising and first_month_retest:
        return "周月季線上揚首次回測月線"
    return None


STRATEGIES: dict[str, Callable[[list[Row], dict[str, list[float | None]], int], str | None]] = {
    "台積電策略": tsmc_signal,
    "群聯策略": phison_signal,
}

TRAILING_TAKE_PROFIT_PCT = 0.07


def position_role(reason: str, open_positions: list[dict[str, object]]) -> str:
    has_core_position = any(position.get("position_role") == "母單" for position in open_positions)
    return "加碼單" if has_core_position and "回測" in reason else "母單"


def backtest(rows: list[Row], strategy_name: str) -> list[dict[str, object]]:
    indicators = prepare(rows)
    signal = STRATEGIES[strategy_name]
    trades: list[dict[str, object]] = []
    open_positions: list[dict[str, object]] = []
    min_entry_gap = 10
    last_entry_index = -10_000

    for index in range(1, len(rows)):
        row = rows[index]
        still_open: list[dict[str, object]] = []
        for position in open_positions:
            exit_price: float | None = None
            exit_reason = ""
            if index > int(position["entry_index"]):
                hard_stop = float(position["stop_price"])
                trail_stop = position.get("trail_stop_price")
                if trail_stop is not None and row.low <= float(trail_stop):
                    exit_price = float(trail_stop)
                    exit_reason = "加碼移動停利7%"
                if row.low <= hard_stop and (exit_price is None or hard_stop > exit_price):
                    exit_price = hard_stop
                    exit_reason = "停損"
            if exit_price is not None:
                trades.append(
                    {
                        **position,
                        "exit_index": index,
                        "exit_date": row.date,
                        "exit_price": exit_price,
                        "exit_reason": exit_reason,
                        "return_pct": exit_price / float(position["entry_price"]) - 1,
                    }
                )
            else:
                if position.get("position_role") == "加碼單":
                    highest_price = max(float(position["highest_price"]), row.high)
                    position["highest_price"] = highest_price
                    if highest_price >= float(position["entry_price"]) * (1 + TRAILING_TAKE_PROFIT_PCT):
                        position["trail_stop_price"] = highest_price * (1 - TRAILING_TAKE_PROFIT_PCT)
                still_open.append(position)
        open_positions = still_open

        reason = signal(rows, indicators, index)
        if reason and index - last_entry_index >= min_entry_gap:
            role = position_role(reason, open_positions)
            open_positions.append(
                {
                    "entry_index": index,
                    "entry_date": row.date,
                    "entry_price": row.close,
                    "stop_price": row.close * 0.85,
                    "entry_reason": reason,
                    "position_role": role,
                    "highest_price": row.close,
                    "trail_stop_price": None,
                }
            )
            last_entry_index = index

    if open_positions:
        last_index = len(rows) - 1
        last = rows[last_index]
        for position in open_positions:
            trades.append(
                {
                    **position,
                    "exit_index": last_index,
                    "exit_date": last.date,
                    "exit_price": last.close,
                    "exit_reason": "期末估值",
                    "return_pct": last.close / float(position["entry_price"]) - 1,
                }
            )
    return trades


def csv_files() -> list[Path]:
    seen: set[str] = set()
    files: list[Path] = []
    for path in SINGLE_FILES:
        if path.exists():
            files.append(path)
            seen.add(path.name.split("_", 1)[0])
    for directory in DATA_DIRS:
        if not directory.exists():
            continue
        latest_by_code: dict[str, Path] = {}
        for path in directory.glob("*.csv"):
            if path.name.startswith("_"):
                continue
            code = path.name.split("_", 1)[0]
            current = latest_by_code.get(code)
            if current is None or (path.stat().st_mtime, path.name) > (current.stat().st_mtime, current.name):
                latest_by_code[code] = path
        for code, path in sorted(latest_by_code.items()):
            if code not in seen:
                files.append(path)
                seen.add(code)
    return files


def main() -> int:
    output_dir = Path("reports")
    output_dir.mkdir(exist_ok=True)
    trade_rows: list[dict[str, object]] = []
    files = csv_files()

    for path in files:
        rows = read_rows(path)
        if len(rows) < 60:
            continue
        for strategy_name in STRATEGIES:
            for trade in backtest(rows, strategy_name):
                first = rows[0]
                trade_rows.append(
                    {
                        "market": first.market,
                        "stock_no": first.stock_no,
                        "stock_name": first.stock_name,
                        "strategy": strategy_name,
                        "entry_date": trade["entry_date"],
                        "entry_price": trade["entry_price"],
                        "entry_reason": trade["entry_reason"],
                        "position_role": trade["position_role"],
                        "exit_date": trade["exit_date"],
                        "exit_price": trade["exit_price"],
                        "exit_reason": trade["exit_reason"],
                        "return_pct": trade["return_pct"],
                    }
                )

    trade_rows.sort(key=lambda row: float(row["return_pct"]), reverse=True)
    trade_path = output_dir / "backtest_trades.csv"
    fieldnames = [
        "market",
        "stock_no",
        "stock_name",
        "strategy",
        "entry_date",
        "entry_price",
        "entry_reason",
        "position_role",
        "exit_date",
        "exit_price",
        "exit_reason",
        "return_pct",
    ]
    try:
        with trade_path.open("w", encoding="utf-8-sig", newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(trade_rows)
    except PermissionError:
        trade_path = output_dir / "backtest_trades_multi.csv"
        with trade_path.open("w", encoding="utf-8-sig", newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(trade_rows)

    summary = {
        "files_scanned": len(files),
        "trades": len(trade_rows),
        "stopped": sum(1 for row in trade_rows if row["exit_reason"] == "停損"),
        "trailing_take_profit": sum(1 for row in trade_rows if row["exit_reason"] == "加碼移動停利7%"),
        "open_valued": sum(1 for row in trade_rows if row["exit_reason"] == "期末估值"),
        "profitable": sum(1 for row in trade_rows if float(row["return_pct"]) > 0),
        "losing": sum(1 for row in trade_rows if float(row["return_pct"]) <= 0),
        "trade_csv": str(trade_path),
    }
    summary_path = output_dir / ("backtest_summary_multi.json" if trade_path.name.endswith("_multi.csv") else "backtest_summary.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
