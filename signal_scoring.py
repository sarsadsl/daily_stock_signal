#!/usr/bin/env python3
"""Quality scoring for matched stock signals."""

from __future__ import annotations

from typing import Any

from run_market_backtest import Row, slope_pct, value_at


ScoreResult = dict[str, Any]


def clamp_score(value: int) -> int:
    return max(1, min(5, value))


def pct(value: float | None) -> float | None:
    return None if value is None else value * 100


def ratio_text(value: float) -> str:
    return f"{value:.1f}x"


def close_position(row: Row) -> float:
    candle_range = row.high - row.low
    return (row.close - row.low) / candle_range if candle_range > 0 else 1.0


def volume_ratio(rows: list[Row], indicators: dict[str, list[float | None]], index: int) -> float | None:
    vol20 = value_at(indicators["vol20"], index)
    if vol20 is None or vol20 <= 0:
        return None
    return rows[index].volume / float(vol20)


def ma_gap(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b <= 0:
        return None
    return a / b - 1


def first_touch_of_ma(rows: list[Row], series: list[float | None], index: int, lookback: int = 12, band: float = 0.02) -> bool:
    ma_now = value_at(series, index)
    if ma_now is None:
        return False
    if rows[index].low > ma_now * (1 + band):
        return False
    start = max(0, index - lookback)
    for cursor in range(start, index):
        ma = value_at(series, cursor)
        if ma is not None and rows[cursor].low <= ma * (1 + band):
            return False
    return True


def select_anchor_ma(reason: str, indicators: dict[str, list[float | None]], index: int) -> tuple[str, float | None]:
    if "10MA" in reason or "10ma" in reason:
        return "10MA", value_at(indicators["ma10"], index)
    if "季線" in reason or "60MA" in reason:
        return "季線", value_at(indicators["ma60"], index)
    if "月線" in reason or "20MA" in reason:
        return "月線", value_at(indicators["ma20"], index)
    return "月線", value_at(indicators["ma20"], index)


def signal_score(rows: list[Row], indicators: dict[str, list[float | None]], index: int, reason: str) -> ScoreResult:
    row = rows[index]
    ma5 = value_at(indicators["ma5"], index)
    ma10 = value_at(indicators["ma10"], index)
    ma20 = value_at(indicators["ma20"], index)
    ma60 = value_at(indicators["ma60"], index)
    ma120 = value_at(indicators["ma120"], index)
    ma20_slope = slope_pct(indicators["ma20"], index, 10)
    ma60_slope = slope_pct(indicators["ma60"], index, 20)
    vol_ratio = volume_ratio(rows, indicators, index)
    anchor_name, anchor = select_anchor_ma(reason, indicators, index)
    reasons: list[str] = []
    score = 1

    if ma5 is not None and ma10 is not None and ma20 is not None and ma60 is not None and ma5 >= ma10 >= ma20 >= ma60:
        score += 1
        reasons.append("短中期均線維持多頭排列")
    elif ma20 is not None and ma60 is not None and ma20 > ma60:
        reasons.append("月線仍在季線之上")

    if ma20_slope is not None and ma20_slope > 0 and ma60_slope is not None and ma60_slope >= 0.02:
        score += 1
        reasons.append("月線與季線同步上揚")
    elif ma60_slope is not None and ma60_slope >= 0.03:
        score += 1
        reasons.append("季線斜率偏強")

    if ma60 is not None and ma120 is not None and ma60 > ma120:
        reasons.append("季線站在半年線之上")

    if anchor is not None and anchor > 0:
        low_gap = abs(row.low / anchor - 1)
        close_gap = row.close / anchor - 1
        if row.low <= anchor * 1.02 and row.close >= anchor:
            score += 1
            reasons.append(f"回測{anchor_name}後收盤守住")
        elif close_gap >= 0:
            reasons.append(f"收盤仍在{anchor_name}上方")
        if low_gap <= 0.015:
            reasons.append(f"低點貼近{anchor_name}，回測位置乾淨")

    if ("首次" in reason or "回測" in reason) and first_touch_of_ma(rows, indicators["ma20"], index, 12, 0.02):
        score += 1
        reasons.append("近12日首次回測月線區")

    candle_pos = close_position(row)
    body_pct = (row.close - row.open) / row.open if row.open else 0
    if row.close > row.open and candle_pos >= 0.65:
        score += 1
        reasons.append("紅K收在當日相對高位")
    elif row.close >= row.open:
        reasons.append("K棒未轉弱")

    if vol_ratio is not None:
        if 1.2 <= vol_ratio <= 3.0:
            score += 1
            reasons.append(f"量能健康放大至20日均量{ratio_text(vol_ratio)}")
        elif vol_ratio > 3.0:
            reasons.append(f"爆量至20日均量{ratio_text(vol_ratio)}，需留意追高")
        elif vol_ratio >= 0.8:
            reasons.append(f"量能接近20日均量{ratio_text(vol_ratio)}")

    if "均線糾結" in reason:
        gap = ma_gap(max(value for value in [ma5, ma10, ma20, ma60] if value is not None), min(value for value in [ma5, ma10, ma20, ma60] if value is not None)) if None not in {ma5, ma10, ma20, ma60} else None
        if gap is not None and gap <= 0.08:
            score += 1
            reasons.append("均線收斂後轉強")
        if body_pct >= 0.04:
            reasons.append("紅K實體夠大")

    if "跳空" in reason and index > 0:
        gap_up = row.open / rows[index - 1].close - 1 if rows[index - 1].close else 0
        if gap_up >= 0.015 and row.close >= row.open * 0.995:
            score += 1
            reasons.append(f"跳空{gap_up * 100:.1f}%後未明顯回落")

    if ma20 is not None and ma20 > 0 and row.close > ma20 * 1.25:
        score -= 1
        reasons.append("收盤離月線偏遠，追價風險較高")

    final_score = clamp_score(score)
    if not reasons:
        reasons.append("符合基本訊號條件")
    return {
        "score": final_score,
        "score_label": f"{final_score}/5",
        "score_reasons": reasons[:5],
        "volume_ratio": round(vol_ratio, 2) if vol_ratio is not None else None,
        "ma20_slope_pct": round(float(pct(ma20_slope) or 0), 2) if ma20_slope is not None else None,
        "ma60_slope_pct": round(float(pct(ma60_slope) or 0), 2) if ma60_slope is not None else None,
    }
