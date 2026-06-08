#!/usr/bin/env python3
"""Sample 100 stocks, backtest entry/stop strategies, and build an HTML viewer."""

from __future__ import annotations

import argparse
import csv
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean, median
from typing import Any, Callable


DATA_DIRS = [Path("data/all_twse"), Path("data/all_tpex")]
REPORT_DIR = Path("reports")
FINAL_EXIT_DATE = "2026-05-29"
VOLUME_SHARES_PER_LOT = 1000
MIN_AVG_VOLUME_LOTS = 1000
LIQUIDITY_LOOKBACK_DAYS = 20
STRATEGY_COOLDOWN_BARS = {
    "strong_breakout": 10,
    "high_base_pullback": 10,
    "quarterly_support_gap_reclaim_watch": 10,
}
TECH_KEYWORDS = (
    "科技",
    "電子",
    "半導體",
    "光電",
    "電腦",
    "通訊",
    "資訊",
    "網通",
    "光學",
    "雲端",
    "APP",
    "精密",
    "矽",
)
NON_TECH_KEYWORDS = (
    "水泥",
    "食品",
    "生技",
    "醫",
    "藥",
    "農",
    "餐",
    "飯店",
    "旅",
    "建設",
    "營造",
    "鋼",
    "鐵",
    "航運",
    "金融",
    "銀行",
    "保險",
    "證",
    "零售",
    "百貨",
    "超商",
    "油",
    "塑",
    "化工",
    "化學",
    "紡",
    "紙",
    "瓦斯",
    "建材",
    "文化",
    "藝術",
    "鞋",
    "服",
    "環保",
    "金屬",
    "可口",
    "能源",
)
TECH_CODE_RANGES = (
    (2300, 2499),
    (3000, 3715),
    (4900, 5499),
    (6100, 6499),
    (8000, 8299),
)
NON_TECH_CODES = {
    "2348",  # 海悅
    "2430",  # 燦坤
    "2450",  # 神腦
    "2707",  # 晶華
    "3040",  # 遠見
    "3073",  # 天方能源
    "3118",  # 進階
    "3164",  # 景岳
    "3224",  # 三顧
    "3557",  # 嘉威
    "3708",  # 上緯投控
    "4142",  # 國光生
    "4930",  # 燦星網
    "5016",  # 松和
    "5206",  # 坤悅
    "5213",  # 亞昕
    "5288",  # 豐祥-KY
    "5292",  # 華懋
    "6177",  # 達麗
    "6198",  # 瑞築
    "6264",  # 富裔
    "6294",  # 智基
    "6461",  # 益得
    "6492",  # 生華科
    "6508",  # 惠光
    "6523",  # 達爾膚
    "6574",  # 霈方
    "6596",  # 寬宏藝術
    "6606",  # 建德工業
    "6615",  # 慧智
    "6617",  # 共信-KY
    "6624",  # 萬年清
    "6649",  # 台生材
    "6655",  # 科定
    "6662",  # 樂斯科
    "6703",  # 軒郁
    "6727",  # 亞泰金屬
    "6753",  # 龍德造船
    "6768",  # 志強-KY
    "7791",  # 皇家可口
    "8083",  # 瑞穎
    "8279",  # 生展
}


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


@dataclass
class Signal:
    strategy: str
    reason: str
    signal_index: int
    stop_price: float
    action: str = "trade"


def clean_float(value: str) -> float | None:
    text = value.replace(",", "").strip()
    if not text or text in {"--", "---"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def clean_int(value: str) -> int:
    parsed = clean_float(value)
    return int(parsed) if parsed is not None else 0


def read_rows(path: Path) -> list[Row]:
    with path.open("r", encoding="utf-8-sig", newline="") as csvfile:
        reader = csv.DictReader(csvfile)
        rows: list[Row] = []
        for item in reader:
            open_price = clean_float(item.get("open", ""))
            high = clean_float(item.get("high", ""))
            low = clean_float(item.get("low", ""))
            close = clean_float(item.get("close", ""))
            if None in {open_price, high, low, close}:
                continue
            rows.append(
                Row(
                    market=item.get("market", ""),
                    stock_no=item.get("stock_no", ""),
                    stock_name=item.get("stock_name", ""),
                    date=item.get("date", ""),
                    open=float(open_price),
                    high=float(high),
                    low=float(low),
                    close=float(close),
                    volume=clean_int(item.get("volume_shares", "")),
                )
            )
    rows.sort(key=lambda row: row.date)
    return rows


def latest_csv_files() -> list[Path]:
    latest: dict[tuple[str, str], tuple[str, float, Path]] = {}
    for directory in DATA_DIRS:
        if not directory.exists():
            continue
        market = directory.name.replace("all_", "")
        for path in directory.glob("*.csv"):
            if path.name.startswith("_"):
                continue
            code = path.name.split("_", 1)[0]
            rows = read_rows(path)
            if not rows:
                continue
            last_date = rows[-1].date
            current = latest.get((market, code))
            candidate = (last_date, path.stat().st_mtime, path)
            if current is None or candidate[:2] > current[:2]:
                latest[(market, code)] = candidate
    return [latest[key][2] for key in sorted(latest)]


def is_tech_stock(row: Row) -> bool:
    if row.stock_no in NON_TECH_CODES:
        return False
    try:
        code = int(row.stock_no)
    except ValueError:
        code = -1
    in_tech_range = any(start <= code <= end for start, end in TECH_CODE_RANGES)
    name_has_tech_keyword = any(keyword in row.stock_name for keyword in TECH_KEYWORDS)
    name_has_non_tech_keyword = any(keyword in row.stock_name for keyword in NON_TECH_KEYWORDS)
    return (in_tech_range or name_has_tech_keyword) and not name_has_non_tech_keyword


def recent_avg_volume_lots(rows: list[Row], final_date: str, lookback: int = LIQUIDITY_LOOKBACK_DAYS) -> float:
    final_index = next((i for i, row in enumerate(rows) if row.date == final_date), len(rows) - 1)
    window = rows[max(0, final_index - lookback + 1) : final_index + 1]
    if len(window) < lookback:
        return 0.0
    return mean(row.volume for row in window) / VOLUME_SHARES_PER_LOT


def moving_average(values: list[float], window: int) -> list[float | None]:
    total = 0.0
    output: list[float | None] = []
    for index, value in enumerate(values):
        total += value
        if index >= window:
            total -= values[index - window]
        output.append(total / window if index >= window - 1 else None)
    return output


def true_range(rows: list[Row]) -> list[float]:
    ranges = [rows[0].high - rows[0].low]
    for index in range(1, len(rows)):
        row = rows[index]
        prev_close = rows[index - 1].close
        ranges.append(max(row.high - row.low, abs(row.high - prev_close), abs(row.low - prev_close)))
    return ranges


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
        "atr20": moving_average(true_range(rows), 20),
    }


def value_at(series: list[float | None], index: int) -> float | None:
    return series[index] if 0 <= index < len(series) else None


def prior_high(rows: list[Row], index: int, lookback: int) -> float | None:
    start = max(0, index - lookback)
    return max((row.high for row in rows[start:index]), default=None)


def prior_low(rows: list[Row], index: int, lookback: int) -> float | None:
    start = max(0, index - lookback)
    return min((row.low for row in rows[start:index]), default=None)


def prior_avg_volume(rows: list[Row], index: int, lookback: int) -> float | None:
    start = max(0, index - lookback)
    values = [row.volume for row in rows[start:index]]
    return mean(values) if len(values) == lookback else None


def rising(series: list[float | None], index: int, lookback: int) -> bool:
    now = value_at(series, index)
    before = value_at(series, index - lookback)
    return now is not None and before is not None and now > before


def clamp(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


def atr_stop(entry_price: float, atr: float | None, multiplier: float, min_pct: float, max_pct: float) -> float:
    risk_pct = clamp(((atr or entry_price * min_pct) * multiplier) / entry_price, min_pct, max_pct)
    return entry_price * (1 - risk_pct)


def strong_breakout(rows: list[Row], ind: dict[str, list[float | None]], index: int) -> Signal | None:
    if index < 60 or index + 1 >= len(rows):
        return None
    row = rows[index]
    ma20 = value_at(ind["ma20"], index)
    ma60 = value_at(ind["ma60"], index)
    atr20 = value_at(ind["atr20"], index)
    high20 = prior_high(rows, index, 20)
    avg_vol5 = prior_avg_volume(rows, index, 5)
    if None in {ma20, ma60, avg_vol5, atr20, high20} or not avg_vol5:
        return None
    body_ok = row.close > row.open and (row.close - row.open) / row.open >= 0.015
    volume_breakout = row.volume >= float(avg_vol5) * 2
    if row.close > float(high20) and row.close > ma20 > ma60 and rising(ind["ma20"], index, 5) and volume_breakout and body_ok:
        entry = rows[index + 1].open
        stop = atr_stop(entry, atr20, multiplier=1.5, min_pct=0.05, max_pct=0.12)
        stop = min(stop, row.low * 0.995) if row.low < entry else stop
        return Signal("strong_breakout", "收盤確認20日新高紅K，成交量大於前5日均量2倍，隔日開盤進場", index, round(stop, 2))
    return None


def high_base_pullback(rows: list[Row], ind: dict[str, list[float | None]], index: int) -> Signal | None:
    if index < 120 or index + 1 >= len(rows):
        return None
    row = rows[index]
    prev = rows[index - 1]
    ma5 = value_at(ind["ma5"], index)
    ma10 = value_at(ind["ma10"], index)
    ma20 = value_at(ind["ma20"], index)
    ma60 = value_at(ind["ma60"], index)
    ma120 = value_at(ind["ma120"], index)
    vol20 = value_at(ind["vol20"], index)
    atr20 = value_at(ind["atr20"], index)
    prev_ma10 = value_at(ind["ma10"], index - 1)
    prev_ma20 = value_at(ind["ma20"], index - 1)
    if None in {ma10, ma20, ma60, ma120, vol20, atr20, prev_ma10, prev_ma20} or not vol20:
        return None

    recent = rows[max(0, index - 9) : index + 1]
    high_offset, high_row = max(enumerate(recent), key=lambda item: item[1].high)
    high_index = index - len(recent) + 1 + high_offset
    days_since_high = index - high_index
    if days_since_high < 1 or days_since_high > 9:
        return None

    drawdown_from_high = row.low / high_row.high - 1
    trend = high_row.close > ma20 > ma60 > ma120 and rising(ind["ma20"], index, 5)
    pulled_back = drawdown_from_high <= -0.025
    tests_ma10 = row.low <= ma10 * 1.015 and row.close >= ma10 * 0.995
    tests_ma20 = row.low <= ma20 * 1.018 and row.close >= ma20 * 0.99
    support_test = tests_ma10 or tests_ma20
    turns_up = row.close > row.open or row.close > prev.close
    not_broken = row.close >= ma20 * 0.99
    quiet_volume = row.volume <= vol20 * 1.4
    if trend and pulled_back and support_test and turns_up and not_broken and quiet_volume:
        entry = rows[index + 1].open
        recent_low = prior_low(rows, index + 1, max(5, days_since_high + 1)) or row.low
        stop = min(recent_low * 0.99, atr_stop(entry, atr20, multiplier=1.15, min_pct=0.04, max_pct=0.095))
        support_name = "10MA" if tests_ma10 else "20MA"
        return Signal(
            "high_base_pullback",
            f"10日內高點回落{abs(drawdown_from_high) * 100:.1f}%，收盤確認測試{support_name}支撐，隔日開盤進場",
            index,
            round(stop, 2),
        )
    return None


def crash_repair(rows: list[Row], ind: dict[str, list[float | None]], index: int) -> Signal | None:
    if index < 80 or index + 1 >= len(rows):
        return None
    row = rows[index]
    prev = rows[index - 1]
    ma20 = value_at(ind["ma20"], index)
    prev_ma20 = value_at(ind["ma20"], index - 1)
    ma60 = value_at(ind["ma60"], index)
    vol20 = value_at(ind["vol20"], index)
    atr20 = value_at(ind["atr20"], index)
    high60 = prior_high(rows, index, 60)
    low20 = prior_low(rows, index + 1, 20)
    if None in {ma20, prev_ma20, ma60, vol20, atr20, high60, low20} or not vol20:
        return None
    drawdown = row.close / float(high60) - 1
    reclaim20 = prev.close < prev_ma20 and row.close > ma20
    strength = row.close > row.open and row.volume >= vol20 * 1.05
    ma_structure_ready = ma20 > ma60 and rising(ind["ma20"], index, 5)
    if drawdown <= -0.18 and reclaim20 and ma_structure_ready and row.close < ma60 * 1.12 and strength:
        entry = rows[index + 1].open
        stop = min(float(low20) * 0.99, atr_stop(entry, atr20, multiplier=1.4, min_pct=0.05, max_pct=0.13))
        return Signal("crash_repair", "收盤確認急跌後重新站回20日線，隔日開盤進場", index, round(stop, 2))
    return None


def ma_bull_turn(rows: list[Row], ind: dict[str, list[float | None]], index: int) -> Signal | None:
    if index < 120 or index + 1 >= len(rows):
        return None
    row = rows[index]
    prev = rows[index - 1]
    ma20 = value_at(ind["ma20"], index)
    ma60 = value_at(ind["ma60"], index)
    prev_ma20 = value_at(ind["ma20"], index - 1)
    prev_ma60 = value_at(ind["ma60"], index - 1)
    ma120 = value_at(ind["ma120"], index)
    vol20 = value_at(ind["vol20"], index)
    atr20 = value_at(ind["atr20"], index)
    if None in {ma20, ma60, prev_ma20, prev_ma60, ma120, vol20, atr20} or not vol20:
        return None

    monthly_crosses_quarterly = prev_ma20 <= prev_ma60 and ma20 > ma60
    averages_turn_up = rising(ind["ma20"], index, 5) and rising(ind["ma60"], index, 10)
    price_confirms = row.close > ma20 and row.close > row.open
    volume_confirms = row.volume >= vol20 * 1.1
    not_too_extended = row.close <= ma20 * 1.12
    long_bias = row.close > ma120
    if monthly_crosses_quarterly and averages_turn_up and price_confirms and volume_confirms and not_too_extended and long_bias:
        entry = rows[index + 1].open
        recent_low = prior_low(rows, index + 1, 15) or row.low
        stop = min(float(recent_low) * 0.99, atr_stop(entry, atr20, multiplier=1.3, min_pct=0.045, max_pct=0.11))
        return Signal("ma_bull_turn", "收盤確認月線突破季線，20MA/60MA翻揚，隔日開盤進場", index, round(stop, 2))
    return None


def ma_reclaim_watch(rows: list[Row], ind: dict[str, list[float | None]], index: int) -> Signal | None:
    if index < 120:
        return None
    row = rows[index]
    prev = rows[index - 1]
    ma5 = value_at(ind["ma5"], index)
    ma10 = value_at(ind["ma10"], index)
    ma20 = value_at(ind["ma20"], index)
    ma60 = value_at(ind["ma60"], index)
    ma120 = value_at(ind["ma120"], index)
    vol20 = value_at(ind["vol20"], index)
    atr20 = value_at(ind["atr20"], index)
    if None in {ma5, ma10, ma20, ma60, ma120, vol20, atr20}:
        return None

    closes_above_all = row.close > ma5 and row.close > ma10 and row.close > ma20 and row.close > ma60 and row.close > ma120
    prev = rows[index - 1]
    prev_ma5 = value_at(ind["ma5"], index - 1)
    prev_ma10 = value_at(ind["ma10"], index - 1)
    prev_ma20 = value_at(ind["ma20"], index - 1)
    prev_ma60 = value_at(ind["ma60"], index - 1)
    prev_ma120 = value_at(ind["ma120"], index - 1)
    if None in {prev_ma5, prev_ma10, prev_ma20, prev_ma60, prev_ma120}:
        return None
    prev_above_all = prev.close > prev_ma5 and prev.close > prev_ma10 and prev.close > prev_ma20 and prev.close > prev_ma60 and prev.close > prev_ma120
    first_reclaim = closes_above_all and not prev_above_all
    red_k = row.close > row.open
    short_mas_rising = rising(ind["ma5"], index, 3) and rising(ind["ma10"], index, 3) and rising(ind["ma20"], index, 5)
    volume_not_dead = row.volume >= vol20 * 0.8
    if first_reclaim and red_k and short_mas_rising and volume_not_dead:
        return Signal(
            "ma_reclaim_watch",
            "首次收盤站上5/10/20/60/120MA，且5/10/20MA上揚，列入觀察，尚非買進訊號",
            index,
            round(row.low * 0.99, 2),
            action="watch",
        )
    return None


def quarterly_support_gap_reclaim_watch(rows: list[Row], ind: dict[str, list[float | None]], index: int) -> Signal | None:
    if index < 120 or index + 1 >= len(rows):
        return None
    row = rows[index]
    prev = rows[index - 1]
    ma5 = value_at(ind["ma5"], index)
    ma10 = value_at(ind["ma10"], index)
    ma20 = value_at(ind["ma20"], index)
    ma60 = value_at(ind["ma60"], index)
    ma120 = value_at(ind["ma120"], index)
    vol20 = value_at(ind["vol20"], index)
    atr20 = value_at(ind["atr20"], index)
    if None in {ma5, ma10, ma20, ma60, ma120, vol20, atr20}:
        return None

    support_index: int | None = None
    support_label = ""
    for lookback_index in range(max(120, index - 20), index + 1):
        support_ma10 = value_at(ind["ma10"], lookback_index)
        support_ma20 = value_at(ind["ma20"], lookback_index)
        support_ma60 = value_at(ind["ma60"], lookback_index)
        support_ma120 = value_at(ind["ma120"], lookback_index)
        if None in {support_ma10, support_ma20, support_ma60, support_ma120}:
            continue
        support_row = rows[lookback_index]
        tests_short_mid = support_row.low <= max(float(support_ma10), float(support_ma20)) * 1.02 and support_row.close >= min(float(support_ma10), float(support_ma20)) * 0.97
        tests_quarterly = support_row.low <= support_ma60 * 1.035 and support_row.close >= support_ma60 * 0.97
        long_bias = support_row.close > support_ma120
        if long_bias and (tests_quarterly or tests_short_mid):
            support_index = lookback_index
            support_label = "季線" if tests_quarterly else "10/20MA"

    if support_index is None:
        return None

    gap_up = row.open >= prev.close * 1.015
    stands_back_on_mas = row.close > ma5 and row.close > ma10 and row.close > ma20
    holds_quarterly = row.close > ma60 and ma60 > ma120
    acceptable_k = row.close >= row.open * 0.995
    volume_alive = row.volume >= vol20 * 0.5
    not_too_late = row.close <= ma20 * 1.35
    if gap_up and stands_back_on_mas and holds_quarterly and acceptable_k and volume_alive and not_too_late:
        support_date = rows[support_index].date
        entry = rows[index + 1].open
        support_low = min(row.low, rows[support_index].low)
        support_stop = support_low * 0.99
        volatility_stop = atr_stop(entry, atr20, multiplier=1.25, min_pct=0.045, max_pct=0.11)
        stop = max(support_stop, volatility_stop)
        return Signal(
            "quarterly_support_gap_reclaim_watch",
            f"{support_label}支撐後跳空站回5/10/20MA，前次支撐日 {support_date}，隔日開盤進場",
            index,
            round(stop, 2),
        )
    return None


STRATEGIES: dict[str, Callable[[list[Row], dict[str, list[float | None]], int], Signal | None]] = {
    "strong_breakout": strong_breakout,
    "high_base_pullback": high_base_pullback,
    "crash_repair": crash_repair,
    "ma_bull_turn": ma_bull_turn,
    "ma_reclaim_watch": ma_reclaim_watch,
    "quarterly_support_gap_reclaim_watch": quarterly_support_gap_reclaim_watch,
}


def trade_from_signal(rows: list[Row], signal: Signal, final_index: int) -> dict[str, Any]:
    if signal.action == "watch":
        return {
            "strategy": signal.strategy,
            "signal_date": rows[signal.signal_index].date,
            "signal_close": rows[signal.signal_index].close,
            "entry_reason": signal.reason,
            "stop_price": signal.stop_price,
            "action": "watch",
        }

    entry_index = signal.signal_index + 1
    entry = rows[entry_index]
    exit_index = final_index
    exit_price = rows[final_index].close
    exit_reason = "final_exit"
    for index in range(entry_index + 1, final_index + 1):
        if rows[index].low <= signal.stop_price:
            exit_index = index
            exit_price = signal.stop_price
            exit_reason = "stop_loss"
            break

    return {
        "strategy": signal.strategy,
        "signal_date": rows[signal.signal_index].date,
        "signal_close": rows[signal.signal_index].close,
        "entry_date": entry.date,
        "entry_price": entry.open,
        "entry_reason": signal.reason,
        "stop_price": signal.stop_price,
        "exit_date": rows[exit_index].date,
        "exit_price": round(exit_price, 2),
        "exit_reason": exit_reason,
        "return_pct": round((exit_price / entry.open - 1) * 100, 2),
        "holding_days": exit_index - entry_index,
        "action": "trade",
        "signal_index": signal.signal_index,
        "entry_index": entry_index,
        "exit_index": exit_index,
    }


def all_strategy_trades(rows: list[Row], strategy: str, final_date: str) -> list[dict[str, Any]]:
    indicators = prepare(rows)
    final_index = next((i for i, row in enumerate(rows) if row.date == final_date), len(rows) - 1)
    if final_index <= 1:
        return []
    signal_fn = STRATEGIES[strategy]
    output: list[dict[str, Any]] = []
    next_allowed_index = 1
    cooldown_bars = STRATEGY_COOLDOWN_BARS.get(strategy, 0)
    for index in range(1, final_index):
        if index < next_allowed_index:
            continue
        candidate = signal_fn(rows, indicators, index)
        if candidate and (candidate.action == "watch" or candidate.signal_index + 1 <= final_index):
            trade = trade_from_signal(rows, candidate, final_index)
            output.append(trade)
            if candidate.action == "trade" and cooldown_bars:
                next_allowed_index = int(trade["exit_index"]) + cooldown_bars + 1
            elif candidate.action == "watch" and cooldown_bars:
                next_allowed_index = candidate.signal_index + cooldown_bars + 1
    return output


def sample_files(
    files: list[Path],
    sample_size: int,
    seed: int,
    final_date: str,
    tech_only: bool = True,
    min_avg_volume_lots: int = MIN_AVG_VOLUME_LOTS,
) -> list[Path]:
    eligible = []
    for path in files:
        rows = read_rows(path)
        enough_history = len(rows) >= 120 and any(row.date == final_date for row in rows)
        liquid_enough = recent_avg_volume_lots(rows, final_date) >= min_avg_volume_lots
        if enough_history and liquid_enough and (not tech_only or is_tech_stock(rows[0])):
            eligible.append(path)
    rng = random.Random(seed)
    if len(eligible) <= sample_size:
        return eligible
    return sorted(rng.sample(eligible, sample_size), key=lambda path: path.name)


def summarize(trades: list[dict[str, Any]]) -> dict[str, Any]:
    def trade_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
        returns = [float(row["return_pct"]) for row in rows]
        winners = [value for value in returns if value > 0]
        losers = [value for value in returns if value <= 0]
        avg_winner = mean(winners) if winners else 0
        avg_loser = mean(losers) if losers else 0
        payoff = avg_winner / abs(avg_loser) if avg_loser < 0 else 0
        big_winners = [value for value in returns if value >= 100]
        return {
            "trades": len(rows),
            "win_rate_pct": round(len(winners) / len(returns) * 100, 2) if returns else 0,
            "avg_return_pct": round(mean(returns), 2) if returns else 0,
            "median_return_pct": round(median(returns), 2) if returns else 0,
            "avg_winner_pct": round(avg_winner, 2) if winners else 0,
            "avg_loser_pct": round(avg_loser, 2) if losers else 0,
            "payoff_ratio": round(payoff, 2) if payoff else 0,
            "big_winner_count": len(big_winners),
            "big_winner_rate_pct": round(len(big_winners) / len(returns) * 100, 2) if returns else 0,
            "max_return_pct": round(max(returns), 2) if returns else 0,
            "max_loss_pct": round(min(returns), 2) if returns else 0,
            "stopped": sum(1 for row in rows if row["exit_reason"] == "stop_loss"),
            "stop_rate_pct": round(sum(1 for row in rows if row["exit_reason"] == "stop_loss") / len(rows) * 100, 2) if rows else 0,
            "final_exits": sum(1 for row in rows if row["exit_reason"] == "final_exit"),
        }

    by_strategy: dict[str, dict[str, Any]] = {}
    for strategy in STRATEGIES:
        rows = [trade for trade in trades if trade["strategy"] == strategy and trade.get("has_trade")]
        by_strategy[strategy] = trade_metrics(rows)
    trade_rows = [row for row in trades if row.get("has_trade")]
    all_metrics = trade_metrics(trade_rows)
    return {
        "total_trade_slots": len(trades),
        "total_trades": all_metrics["trades"],
        "overall_avg_return_pct": all_metrics["avg_return_pct"],
        "overall_median_return_pct": all_metrics["median_return_pct"],
        "overall_win_rate_pct": all_metrics["win_rate_pct"],
        "overall_avg_winner_pct": all_metrics["avg_winner_pct"],
        "overall_avg_loser_pct": all_metrics["avg_loser_pct"],
        "overall_payoff_ratio": all_metrics["payoff_ratio"],
        "overall_big_winner_count": all_metrics["big_winner_count"],
        "overall_big_winner_rate_pct": all_metrics["big_winner_rate_pct"],
        "overall_max_return_pct": all_metrics["max_return_pct"],
        "overall_max_loss_pct": all_metrics["max_loss_pct"],
        "overall_stop_rate_pct": all_metrics["stop_rate_pct"],
        "by_strategy": by_strategy,
    }


def chart_rows(rows: list[Row]) -> list[dict[str, Any]]:
    indicators = prepare(rows)
    output = []
    for index, row in enumerate(rows):
        output.append(
            {
                "date": row.date,
                "open": row.open,
                "high": row.high,
                "low": row.low,
                "close": row.close,
                "volume": row.volume,
                "ma5": value_at(indicators["ma5"], index),
                "ma10": value_at(indicators["ma10"], index),
                "ma20": value_at(indicators["ma20"], index),
                "ma60": value_at(indicators["ma60"], index),
                "ma120": value_at(indicators["ma120"], index),
            }
        )
    return output


HTML_TEMPLATE = r"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>策略抽樣回測</title>
  <style>
    :root { --bg:#f5f7fb; --panel:#fff; --ink:#172033; --muted:#64748b; --line:#d8dee8; --red:#d7263d; --green:#148f62; --blue:#2563eb; --orange:#f97316; --purple:#7c3aed; }
    * { box-sizing:border-box; }
    body { margin:0; min-height:100vh; background:var(--bg); color:var(--ink); font-family:"Microsoft JhengHei","Noto Sans TC",Arial,sans-serif; letter-spacing:0; }
    button, select, input { font:inherit; }
    .topbar { position:sticky; top:0; z-index:4; display:grid; grid-template-columns:1fr auto; gap:12px; align-items:center; padding:12px 16px; background:rgba(255,255,255,.96); border-bottom:1px solid var(--line); }
    h1 { margin:0; font-size:20px; }
    .meta { color:var(--muted); font-size:13px; margin-top:4px; }
    .controls { display:flex; flex-wrap:wrap; gap:8px; justify-content:flex-end; }
    select, input, button { height:36px; border:1px solid var(--line); border-radius:8px; background:#fff; color:var(--ink); padding:0 10px; }
    button { cursor:pointer; }
    button:hover, select:hover, input:hover { border-color:#9aa8bb; }
    .wrap { display:grid; grid-template-columns:minmax(0,1fr) 390px; gap:14px; padding:14px 16px 18px; }
    .chartBox, .side, .summary { background:var(--panel); border:1px solid var(--line); border-radius:8px; }
    .chartBox { min-height:620px; position:relative; overflow:hidden; }
    canvas { width:100%; height:620px; display:block; cursor:crosshair; }
    .tooltip { position:absolute; left:12px; top:12px; max-width:360px; padding:8px 10px; border:1px solid var(--line); border-radius:8px; background:rgba(255,255,255,.96); font-size:13px; line-height:1.55; pointer-events:none; }
    .side { min-width:0; overflow:hidden; }
    .panelHead { display:flex; justify-content:space-between; align-items:center; gap:8px; padding:12px; border-bottom:1px solid var(--line); }
    .panelHead strong { font-size:15px; }
    .stats { display:grid; grid-template-columns:1fr 1fr; gap:8px; padding:12px; border-bottom:1px solid var(--line); }
    .stat { background:#f8fafc; border:1px solid #e6ebf2; border-radius:8px; padding:9px; }
    .label { color:var(--muted); font-size:12px; }
    .value { margin-top:3px; font-weight:700; font-size:18px; }
    table { width:100%; border-collapse:collapse; font-size:13px; }
    th, td { padding:8px 10px; border-bottom:1px solid #edf1f6; text-align:left; white-space:nowrap; }
    th { position:sticky; top:0; background:#f8fafc; color:#475569; z-index:1; }
    tr { cursor:pointer; }
    tr.active { background:#eef5ff; }
    tbody tr:hover { background:#f5f9ff; }
    .clickHint { color:var(--muted); font-size:12px; }
    .tableWrap { max-height:470px; overflow:auto; }
    .summary { margin:0 16px 14px; padding:12px; }
    .summaryGrid { display:grid; grid-template-columns:repeat(4, minmax(0,1fr)); gap:8px; }
    .pill { display:inline-flex; align-items:center; height:24px; border-radius:999px; padding:0 9px; font-size:12px; background:#eef2f7; color:#334155; }
    .good { color:#b91c1c; } .bad { color:#047857; }
    @media (max-width:980px){ .topbar,.wrap{grid-template-columns:1fr;} .controls{justify-content:flex-start;} .summaryGrid{grid-template-columns:1fr 1fr;} }
  </style>
</head>
<body>
  <div class="topbar">
    <div>
      <h1>策略抽樣100檔回測</h1>
      <div class="meta" id="meta"></div>
    </div>
    <div class="controls">
      <input id="search" placeholder="搜尋代號/名稱">
      <select id="strategyFilter"></select>
      <select id="stockSelect"></select>
      <button id="resetZoom" type="button">重設縮放</button>
    </div>
  </div>
  <div class="summary"><div class="summaryGrid" id="summaryGrid"></div></div>
  <div class="wrap">
    <div class="chartBox">
      <canvas id="chart"></canvas>
      <div class="tooltip" id="tooltip"></div>
    </div>
    <aside class="side">
      <div class="panelHead"><strong>訊號清單</strong><span class="clickHint">點擊列切換K線</span><span class="pill" id="countPill"></span></div>
      <div class="stats" id="tradeStats"></div>
      <div class="tableWrap"><table><thead><tr><th>股票</th><th>策略</th><th>進場</th><th>出場</th><th>報酬</th></tr></thead><tbody id="tradeBody"></tbody></table></div>
    </aside>
  </div>
  <script id="payload" type="application/json">__PAYLOAD__</script>
  <script>
    const payload = JSON.parse(document.getElementById('payload').textContent);
    const strategyNames = { strong_breakout:'強勢突破', high_base_pullback:'高檔回測', crash_repair:'急跌修復', ma_bull_turn:'月季線翻多', ma_reclaim_watch:'站上均線觀察', quarterly_support_gap_reclaim_watch:'季線支撐跳空' };
    const trades = payload.trades;
    const stocks = payload.stocks;
    const chart = document.getElementById('chart');
    const ctx = chart.getContext('2d');
    const search = document.getElementById('search');
    const strategyFilter = document.getElementById('strategyFilter');
    const stockSelect = document.getElementById('stockSelect');
    const resetZoom = document.getElementById('resetZoom');
    let selectedKey = trades.find(t => t.has_signal)?.key || stocks[0]?.key;
    let selectedTradeId = trades.find(t => t.has_signal)?.id || null;
    let hoverIndex = null;
    let viewStart = 0;
    let viewEnd = 0;
    let dragStartX = null;
    let dragStartView = null;

    function fmtPct(v){ if(v === null || v === undefined) return '-'; return `${Number(v).toFixed(2)}%`; }
    function cls(v){ return Number(v) >= 0 ? 'good' : 'bad'; }
    function clampNumber(value, low, high){ return Math.min(Math.max(value, low), high); }
    function resetView(){ const stock = selectedStock(); viewStart = 0; viewEnd = stock ? stock.rows.length : 0; hoverIndex = null; }
    function clampView(){
      const stock = selectedStock(); if(!stock) return;
      const len = stock.rows.length;
      const minBars = Math.min(18, len);
      let span = Math.round(viewEnd - viewStart);
      if(!Number.isFinite(span) || span < minBars) span = minBars;
      if(span > len) span = len;
      viewStart = Math.round(viewStart);
      if(viewStart < 0) viewStart = 0;
      if(viewStart + span > len) viewStart = len - span;
      viewEnd = viewStart + span;
    }
    function visibleRows(){
      const stock = selectedStock(); if(!stock) return [];
      if(viewEnd <= viewStart) resetView();
      clampView();
      return stock.rows.slice(viewStart, viewEnd);
    }
    function indexFromMouse(clientX){
      const data = visibleRows(); if(!data.length) return null;
      const rect = chart.getBoundingClientRect();
      const padL = 58, padR = 18;
      const innerW = rect.width - padL - padR;
      const local = (clientX - rect.left - padL) / innerW;
      const localIndex = Math.floor(local * data.length);
      return localIndex >= 0 && localIndex < data.length ? viewStart + localIndex : null;
    }
    function resize(){ const dpr = window.devicePixelRatio || 1; const rect = chart.getBoundingClientRect(); chart.width = Math.floor(rect.width*dpr); chart.height = Math.floor(rect.height*dpr); ctx.setTransform(dpr,0,0,dpr,0,0); draw(); }
    function filteredTrades(){
      const q = search.value.trim().toLowerCase();
      const s = strategyFilter.value;
      return trades.filter(t => t.has_signal && (!s || t.strategy === s) && (!q || `${t.stock_no} ${t.stock_name}`.toLowerCase().includes(q)));
    }
    function selectedStock(){ return stocks.find(s => s.key === selectedKey) || stocks[0]; }
    function selectedTrade(){
      const s = strategyFilter.value;
      const current = trades.find(t => t.id === selectedTradeId);
      if(current && current.key === selectedKey && (!s || current.strategy === s)) return current;
      return filteredTrades().find(t => t.key === selectedKey) || (!s ? trades.find(t => t.key === selectedKey && t.has_signal) : null);
    }
    function initControls(){
      strategyFilter.innerHTML = `<option value="">全部策略</option>` + Object.entries(strategyNames).map(([k,v]) => `<option value="${k}">${v}</option>`).join('');
      stockSelect.innerHTML = stocks.map(s => `<option value="${s.key}">${s.stock_no} ${s.stock_name}</option>`).join('');
      stockSelect.value = selectedKey;
      resetView();
      document.getElementById('meta').textContent = `${payload.tech_only ? '科技股樣本' : '全產業樣本'} ${payload.sample_size} 檔，近${payload.liquidity_lookback_days}日均量 >= ${payload.min_avg_volume_lots}張，固定出場日 ${payload.final_exit_date}，種子 ${payload.seed}`;
    }
    function renderSummary(){
      const selectedStrategy = strategyFilter.value;
      const strategySummary = selectedStrategy ? payload.summary.by_strategy[selectedStrategy] : null;
      const m = strategySummary ? {
        label: strategyNames[selectedStrategy],
        total_trades: strategySummary.trades,
        avg_return_pct: strategySummary.avg_return_pct,
        median_return_pct: strategySummary.median_return_pct,
        win_rate_pct: strategySummary.win_rate_pct,
        avg_winner_pct: strategySummary.avg_winner_pct,
        avg_loser_pct: strategySummary.avg_loser_pct,
        payoff_ratio: strategySummary.payoff_ratio,
        big_winner_count: strategySummary.big_winner_count,
        big_winner_rate_pct: strategySummary.big_winner_rate_pct,
        max_loss_pct: strategySummary.max_loss_pct,
        stop_rate_pct: strategySummary.stop_rate_pct
      } : {
        label: '全部策略',
        total_trades: payload.summary.total_trades,
        avg_return_pct: payload.summary.overall_avg_return_pct,
        median_return_pct: payload.summary.overall_median_return_pct,
        win_rate_pct: payload.summary.overall_win_rate_pct,
        avg_winner_pct: payload.summary.overall_avg_winner_pct,
        avg_loser_pct: payload.summary.overall_avg_loser_pct,
        payoff_ratio: payload.summary.overall_payoff_ratio,
        big_winner_count: payload.summary.overall_big_winner_count,
        big_winner_rate_pct: payload.summary.overall_big_winner_rate_pct,
        max_loss_pct: payload.summary.overall_max_loss_pct,
        stop_rate_pct: payload.summary.overall_stop_rate_pct
      };
      const items = [
        ['統計範圍', m.label],
        ['總交易數', m.total_trades],
        ['平均報酬', fmtPct(m.avg_return_pct)],
        ['中位數報酬', fmtPct(m.median_return_pct)],
        ['勝率', fmtPct(m.win_rate_pct)],
        ['平均贏家', fmtPct(m.avg_winner_pct)],
        ['平均輸家', fmtPct(m.avg_loser_pct)],
        ['賺賠比', Number(m.payoff_ratio || 0).toFixed(2)],
        ['100%+ 飆股', `${m.big_winner_count} 筆 / ${fmtPct(m.big_winner_rate_pct)}`],
        ['最大單筆虧損', fmtPct(m.max_loss_pct)],
        ['停損率', fmtPct(m.stop_rate_pct)]
      ];
      document.getElementById('summaryGrid').innerHTML = items.map(([label,value]) => `<div class="stat"><div class="label">${label}</div><div class="value">${value}</div></div>`).join('');
    }
    function renderTable(){
      const rows = filteredTrades().sort((a,b) => (Number(b.return_pct) || -9999) - (Number(a.return_pct) || -9999));
      document.getElementById('countPill').textContent = `${rows.length} 筆`;
      document.getElementById('tradeBody').innerHTML = rows.map(t => `<tr data-id="${t.id}" class="${t.id===selectedTradeId?'active':''}" title="點擊切換到 ${t.stock_no} ${t.stock_name} 的K線圖">
        <td>${t.stock_no} ${t.stock_name}</td><td>${strategyNames[t.strategy]}${t.has_trade ? '' : '<br><span class="label">觀察</span>'}</td><td>${t.signal_date}<br><span class="label">${t.has_trade ? `隔日 ${t.entry_date}` : '不進場'}</span></td><td>${t.exit_date || '-'}</td><td class="${cls(t.return_pct)}">${t.has_trade ? fmtPct(t.return_pct) : '-'}</td>
      </tr>`).join('');
      document.getElementById('tradeStats').innerHTML = (selectedTrade() ? [
        ['策略', strategyNames[selectedTrade().strategy]],
        ['訊號日', selectedTrade().signal_date],
        ['類型', selectedTrade().has_trade ? '交易' : '觀察'],
        ['停損/觀察低點', selectedTrade().stop_price || '-'],
        ['進場價', selectedTrade().entry_price || '-'],
        ['出場價', selectedTrade().exit_price || '-'],
      ].map(([label,value]) => `<div class="stat"><div class="label">${label}</div><div class="value">${value}</div></div>`).join('') : '');
      document.querySelectorAll('tbody tr').forEach(row => row.addEventListener('click', () => selectTrade(row.dataset.id, true)));
    }
    function selectTrade(tradeId, scrollToChart=false){
      const t = trades.find(x => x.id === tradeId);
      if(!t) return;
      selectedTradeId = t.id;
      selectedKey = t.key;
      stockSelect.value = selectedKey;
      resetView();
      zoomToTrade(t);
      renderTable();
      draw();
      if(scrollToChart){
        document.querySelector('.chartBox')?.scrollIntoView({ behavior:'smooth', block:'start' });
      }
    }
    function zoomToTrade(t){
      const stock = selectedStock(); if(!stock || !t) return;
      const signal = stock.rows.findIndex(d => d.date === t.signal_date);
      const entry = stock.rows.findIndex(d => d.date === t.entry_date);
      const exit = stock.rows.findIndex(d => d.date === t.exit_date);
      const anchors = [signal, entry, exit].filter(v => v >= 0);
      if(!anchors.length) return;
      const left = Math.max(0, Math.min(...anchors) - 12);
      const right = Math.min(stock.rows.length, Math.max(...anchors) + 14);
      viewStart = left;
      viewEnd = Math.max(right, left + 24);
      clampView();
    }
    function draw(){
      const stock = selectedStock(); if(!stock) return;
      const fullData = stock.rows; const data = visibleRows(); const rect = chart.getBoundingClientRect(); const w = rect.width; const h = rect.height;
      ctx.clearRect(0,0,w,h);
      const pad = {l:58,r:18,t:24,b:42}; const innerW = w-pad.l-pad.r; const innerH = h-pad.t-pad.b;
      const priceH = Math.max(260, innerH * 0.72);
      const gapH = 20;
      const volH = Math.max(90, innerH - priceH - gapH);
      const priceBottom = pad.t + priceH;
      const volTop = priceBottom + gapH;
      if(!data.length) return;
      const lows = data.map(d=>d.low), highs = data.map(d=>d.high);
      const volumes = data.map(d=>d.volume || 0);
      const minP = Math.min(...lows)*0.98, maxP = Math.max(...highs)*1.02;
      const maxVol = Math.max(...volumes, 1);
      const x = i => pad.l + (i + .5) * innerW / data.length;
      const y = p => pad.t + (maxP - p) / (maxP - minP) * priceH;
      const volY = v => volTop + (1 - v / maxVol) * volH;
      ctx.strokeStyle = '#e5eaf1'; ctx.lineWidth = 1; ctx.font = '12px Arial'; ctx.fillStyle = '#64748b';
      for(let i=0;i<=5;i++){ const yy=pad.t+priceH*i/5; ctx.beginPath(); ctx.moveTo(pad.l,yy); ctx.lineTo(w-pad.r,yy); ctx.stroke(); const price=maxP-(maxP-minP)*i/5; ctx.fillText(price.toFixed(2),8,yy+4); }
      ctx.strokeStyle = '#e5eaf1'; ctx.beginPath(); ctx.moveTo(pad.l, volTop); ctx.lineTo(w-pad.r, volTop); ctx.stroke();
      ctx.fillStyle = '#64748b'; ctx.fillText(`量 ${Math.round(maxVol / 1000).toLocaleString()}張`, 8, volTop + 12);
      const bw = Math.max(3, innerW / data.length * .58);
      data.forEach((d,i)=>{
        const up=d.close>=d.open;
        ctx.fillStyle=up?'rgba(215,38,61,.42)':'rgba(20,143,98,.42)';
        const barTop = volY(d.volume || 0);
        ctx.fillRect(x(i)-bw/2, barTop, bw, Math.max(1, volTop + volH - barTop));
      });
      data.forEach((d,i)=>{ const up=d.close>=d.open; ctx.strokeStyle=up?'#d7263d':'#148f62'; ctx.fillStyle=ctx.strokeStyle; ctx.beginPath(); ctx.moveTo(x(i),y(d.high)); ctx.lineTo(x(i),y(d.low)); ctx.stroke(); const top=y(Math.max(d.open,d.close)); const bot=y(Math.min(d.open,d.close)); ctx.fillRect(x(i)-bw/2,top,bw,Math.max(1,bot-top)); });
      function line(key,color){ ctx.strokeStyle=color; ctx.lineWidth=1.5; ctx.beginPath(); let started=false; data.forEach((d,i)=>{ if(!d[key]) return; if(!started){ctx.moveTo(x(i),y(d[key])); started=true;} else ctx.lineTo(x(i),y(d[key])); }); ctx.stroke(); }
      line('ma5','#dc2626'); line('ma10','#0f766e'); line('ma20','#2563eb'); line('ma60','#f97316'); line('ma120','#64748b');
      const selectedStrategy = strategyFilter.value;
      const stockTrades = trades.filter(t => t.key === stock.key && t.has_signal && (!selectedStrategy || t.strategy === selectedStrategy));
      stockTrades.forEach(t => {
        const strategyLabel = strategyNames[t.strategy] || t.strategy;
        const siFull = fullData.findIndex(d=>d.date===t.signal_date), eiFull = fullData.findIndex(d=>d.date===t.entry_date), xiFull = fullData.findIndex(d=>d.date===t.exit_date);
        const si = siFull - viewStart, ei = eiFull - viewStart, xi = xiFull - viewStart;
        if(si>=0 && si<data.length){
          const signalY = y(fullData[siFull].high) - 11;
          ctx.fillStyle='#f97316'; ctx.beginPath(); ctx.moveTo(x(si), signalY); ctx.lineTo(x(si)-7, signalY+13); ctx.lineTo(x(si)+7, signalY+13); ctx.closePath(); ctx.fill();
          ctx.fillText(`${strategyLabel} 訊號`, x(si)+8, signalY+6);
        }
        if(t.has_trade && ei>=0 && ei<data.length){ ctx.fillStyle='#7c3aed'; ctx.beginPath(); ctx.arc(x(ei), y(t.entry_price), 6, 0, Math.PI*2); ctx.fill(); ctx.fillText(`${strategyLabel} 進場`, x(ei)+7, y(t.entry_price)-7); }
        if(t.has_trade && xi>=0 && xi<data.length){ ctx.fillStyle=t.exit_reason==='stop_loss'?'#111827':'#db2777'; ctx.beginPath(); ctx.rect(x(xi)-5, y(t.exit_price)-5, 10, 10); ctx.fill(); ctx.fillText(`${strategyLabel} ${t.exit_reason==='stop_loss'?'停損':`${payload.final_exit_date}出場`}`, x(xi)+8, y(t.exit_price)+4); }
        if(t.has_trade && ((siFull >= viewStart && siFull < viewEnd) || (eiFull >= viewStart && eiFull < viewEnd) || (xiFull >= viewStart && xiFull < viewEnd))){
          ctx.strokeStyle='rgba(17,24,39,.22)'; ctx.setLineDash([4,4]); ctx.beginPath(); ctx.moveTo(pad.l,y(t.stop_price)); ctx.lineTo(w-pad.r,y(t.stop_price)); ctx.stroke(); ctx.setLineDash([]);
        }
      });
      ctx.fillStyle = '#64748b'; ctx.fillText(`${viewStart + 1}-${viewEnd} / ${fullData.length} 根  |  滾輪縮放、拖曳平移`, pad.l, h - 16);
      const localHover = hoverIndex === null ? null : hoverIndex - viewStart;
      if(localHover !== null && data[localHover]){ ctx.strokeStyle='rgba(37,99,235,.5)'; ctx.beginPath(); ctx.moveTo(x(localHover),pad.t); ctx.lineTo(x(localHover),volTop + volH); ctx.stroke(); const d=data[localHover]; document.getElementById('tooltip').innerHTML = `${stock.stock_no} ${stock.stock_name}<br>${d.date}<br>開 ${d.open} 高 ${d.high} 低 ${d.low} 收 ${d.close}<br>量 ${(d.volume/1000).toLocaleString(undefined,{maximumFractionDigits:0})} 張`; }
      else { const t=selectedTrade(); document.getElementById('tooltip').innerHTML = t ? (t.has_trade ? `${t.stock_no} ${t.stock_name}<br>${strategyNames[t.strategy]}：${t.entry_reason}<br>訊號 ${t.signal_date} 收盤確認，隔日 ${t.entry_date} 開盤 @ ${t.entry_price}<br>出 ${t.exit_date} @ ${t.exit_price}，停損 ${t.stop_price}<br>報酬 <span class="${cls(t.return_pct)}">${fmtPct(t.return_pct)}</span>` : `${t.stock_no} ${t.stock_name}<br>${strategyNames[t.strategy]}：${t.entry_reason}<br>訊號 ${t.signal_date} 收盤確認，只列觀察，不進場`) : `${stock.stock_no} ${stock.stock_name}`; }
    }
    chart.addEventListener('wheel', e => {
      e.preventDefault();
      const stock = selectedStock(); if(!stock) return;
      const mouseIndex = indexFromMouse(e.clientX) ?? Math.floor((viewStart + viewEnd) / 2);
      const oldSpan = viewEnd - viewStart;
      const factor = e.deltaY < 0 ? 0.78 : 1.28;
      const newSpan = clampNumber(Math.round(oldSpan * factor), Math.min(18, stock.rows.length), stock.rows.length);
      const ratio = oldSpan ? (mouseIndex - viewStart) / oldSpan : 0.5;
      viewStart = Math.round(mouseIndex - newSpan * ratio);
      viewEnd = viewStart + newSpan;
      clampView();
      draw();
    }, { passive:false });
    chart.addEventListener('mousedown', e => { dragStartX = e.clientX; dragStartView = [viewStart, viewEnd]; });
    window.addEventListener('mouseup', () => { dragStartX = null; dragStartView = null; });
    chart.addEventListener('mousemove', e => {
      if(dragStartX !== null && dragStartView){
        const data = visibleRows(); const rect = chart.getBoundingClientRect(); const barsMoved = Math.round((dragStartX - e.clientX) / Math.max(1, rect.width - 76) * data.length);
        viewStart = dragStartView[0] + barsMoved; viewEnd = dragStartView[1] + barsMoved; clampView(); hoverIndex = indexFromMouse(e.clientX); draw(); return;
      }
      hoverIndex = indexFromMouse(e.clientX); draw();
    });
    chart.addEventListener('mouseleave', () => { if(dragStartX === null){ hoverIndex=null; draw(); } });
    search.addEventListener('input', renderTable);
    strategyFilter.addEventListener('change', () => { selectedTradeId = selectedTrade()?.id || null; renderSummary(); renderTable(); draw(); });
    stockSelect.addEventListener('change', () => { selectedKey = stockSelect.value; selectedTradeId = selectedTrade()?.id || null; resetView(); renderTable(); draw(); });
    resetZoom.addEventListener('click', () => { resetView(); draw(); });
    window.addEventListener('resize', resize);
    initControls(); renderSummary(); renderTable(); resize();
  </script>
</body>
</html>
"""


def write_html(payload: dict[str, Any], output_path: Path) -> None:
    html = HTML_TEMPLATE.replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False))
    output_path.write_text(html, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample-size", type=int, default=100)
    parser.add_argument("--seed", type=int, default=529)
    parser.add_argument("--final-date", default=FINAL_EXIT_DATE)
    parser.add_argument("--min-avg-volume-lots", type=int, default=MIN_AVG_VOLUME_LOTS)
    parser.add_argument("--all-industries", action="store_true", help="Disable the default technology-stock universe filter.")
    args = parser.parse_args()

    REPORT_DIR.mkdir(exist_ok=True)
    files = latest_csv_files()
    tech_only = not args.all_industries
    sampled = sample_files(files, args.sample_size, args.seed, args.final_date, tech_only=tech_only, min_avg_volume_lots=args.min_avg_volume_lots)
    stocks: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []

    for path in sampled:
        rows = read_rows(path)
        first = rows[0]
        key = f"{first.market}:{first.stock_no}"
        stocks.append(
            {
                "key": key,
                "market": first.market,
                "stock_no": first.stock_no,
                "stock_name": first.stock_name,
                "source": str(path),
                "rows": chart_rows(rows),
            }
        )
        for strategy in STRATEGIES:
            base = {
                "id": f"{key}:{strategy}",
                "key": key,
                "market": first.market,
                "stock_no": first.stock_no,
                "stock_name": first.stock_name,
                "strategy": strategy,
            }
            strategy_trades = all_strategy_trades(rows, strategy, args.final_date)
            if strategy_trades:
                for trade in strategy_trades:
                    is_trade = trade.get("action", "trade") == "trade"
                    signal_date = trade.get("signal_date", "none")
                    trades.append(
                        {
                            **base,
                            **trade,
                            "id": f"{key}:{strategy}:{signal_date}",
                            "has_signal": True,
                            "has_trade": is_trade,
                        }
                    )
            else:
                trades.append({**base, "has_signal": False, "has_trade": False})

    payload = {
        "sample_size": len(sampled),
        "tech_only": tech_only,
        "min_avg_volume_lots": args.min_avg_volume_lots,
        "liquidity_lookback_days": LIQUIDITY_LOOKBACK_DAYS,
        "seed": args.seed,
        "final_exit_date": args.final_date,
        "strategies": {
            "strong_breakout": "強勢突破：紅K收盤突破20日新高，成交量大於訊號日前5日均量2倍，20MA在60MA上且20MA上彎；隔日開盤進場，ATR停損。持倉期間不重複進場，出場後冷卻10根K棒。",
            "high_base_pullback": "高檔回測：10日內創高後從高點拉回至少2.5%，測試10MA或20MA支撐且收盤守住轉強；隔日開盤進場，近期低點/ATR停損。持倉期間不重複進場，出場後冷卻10根K棒。",
            "crash_repair": "急跌修復：自60日高點回落18%以上後重新站回20MA，且20MA已在60MA上方；隔日開盤進場，20日低點/ATR停損。",
            "ma_bull_turn": "月季線翻多：季線仍在月線上方時不買；等20MA突破60MA，且20MA/60MA同步翻揚，再隔日開盤進場，近期低點/ATR停損。",
            "ma_reclaim_watch": "站上均線觀察：前一日尚未站上全部均線，今日首次收盤站上5/10/20/60/120MA，且5MA/10MA/20MA均上揚，列入觀察清單；連續站上不重複，不進場、不計入報酬。",
            "quarterly_support_gap_reclaim_watch": "季線支撐跳空：20日內測試季線或10/20MA支撐後，今日跳空站回5/10/20MA且守在60MA上方；隔日開盤進場，以支撐低點/ATR設停損。持倉期間不重複進場，出場後冷卻10根K棒。",
        },
        "summary": summarize(trades),
        "stocks": stocks,
        "trades": trades,
    }

    json_path = REPORT_DIR / "three_strategy_sample100.json"
    html_path = Path("three_strategy_sample_dashboard.html")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_html(payload, html_path)

    csv_path = REPORT_DIR / "three_strategy_sample100_trades.csv"
    fieldnames = [
        "market",
        "stock_no",
        "stock_name",
        "strategy",
        "has_signal",
        "has_trade",
        "action",
        "signal_date",
        "entry_date",
        "entry_price",
        "stop_price",
        "exit_date",
        "exit_price",
        "exit_reason",
        "return_pct",
        "holding_days",
        "entry_reason",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(trades)

    print(json.dumps({"json": str(json_path), "csv": str(csv_path), "html": str(html_path), **payload["summary"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
