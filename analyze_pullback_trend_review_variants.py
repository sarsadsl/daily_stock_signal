#!/usr/bin/env python3
"""Test PB-V4 max-hold alternatives that review trend before exiting."""

from __future__ import annotations

import html
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import analyze_pullback_discount2_swing as base

REPORT_DIR = Path("reports")
OUT_JSON = REPORT_DIR / "pullback_pb_v6_trend_review_variants.json"
OUT_HTML = REPORT_DIR / "pullback_pb_v6_trend_review_variants.html"
OUT_MD = REPORT_DIR / "pullback_pb_v6_trend_review_variants.md"

VERSION = "PB-V6.0-trend-review-variants"


def ma(rows: list[Any], index: int, window: int) -> float | None:
    if index < window - 1:
        return None
    return sum(row.close for row in rows[index - window + 1 : index + 1]) / window


def previous_swing_low(rows: list[Any], index: int, lookback: int = 20) -> float | None:
    start = max(0, index - lookback)
    values = [row.low for row in rows[start:index]]
    return min(values) if values else None


def condition_ma20(rows: list[Any], index: int) -> bool:
    value = ma(rows, index, 20)
    return value is not None and rows[index].close >= value


def condition_ma10(rows: list[Any], index: int) -> bool:
    value = ma(rows, index, 10)
    return value is not None and rows[index].close >= value


def condition_ma60_structure(rows: list[Any], index: int) -> bool:
    ma20 = ma(rows, index, 20)
    ma60 = ma(rows, index, 60)
    return ma20 is not None and ma60 is not None and rows[index].close >= ma60 and ma20 >= ma60


def condition_swing_low(rows: list[Any], index: int) -> bool:
    low = previous_swing_low(rows, index, 20)
    return low is not None and rows[index].close >= low


def condition_ma20_structure(rows: list[Any], index: int) -> bool:
    ma20 = ma(rows, index, 20)
    ma60 = ma(rows, index, 60)
    if ma20 is None or ma60 is None:
        return False
    return (rows[index].close >= ma20 and ma20 >= ma60) or (rows[index].close >= ma60 * 0.98 and ma20 >= ma60)


VARIANTS: list[dict[str, Any]] = [
    {
        "id": "V6A_ma20_review_exit_ma20",
        "name": "第20日站上MA20才續抱；跌破MA20出場",
        "review_condition": condition_ma20,
        "post_condition": condition_ma20,
        "use_trailing_after_review": True,
    },
    {
        "id": "V6B_ma10_review_exit_ma10",
        "name": "第20日站上MA10才續抱；跌破MA10出場",
        "review_condition": condition_ma10,
        "post_condition": condition_ma10,
        "use_trailing_after_review": True,
    },
    {
        "id": "V6C_ma60_structure_review",
        "name": "第20日仍站上MA60且MA20≥MA60才續抱",
        "review_condition": condition_ma60_structure,
        "post_condition": condition_ma60_structure,
        "use_trailing_after_review": True,
    },
    {
        "id": "V6D_swing_low_review",
        "name": "第20日未跌破前20日低點才續抱；跌破前低出場",
        "review_condition": condition_swing_low,
        "post_condition": condition_swing_low,
        "use_trailing_after_review": True,
    },
    {
        "id": "V6E_ma20_review_no_trailing_after20",
        "name": "第20日站上MA20續抱；之後改用跌破MA20出場，不再用移動停利",
        "review_condition": condition_ma20,
        "post_condition": condition_ma20,
        "use_trailing_after_review": False,
    },
    {
        "id": "V6F_ma20_structure_review",
        "name": "寬鬆趨勢檢查：站上MA20或靠近MA60且MA20≥MA60才續抱",
        "review_condition": condition_ma20_structure,
        "post_condition": condition_ma20_structure,
        "use_trailing_after_review": True,
    },
]


def summarize_holding(trades: list[dict[str, Any]]) -> dict[str, Any]:
    values = [int(row["holding_days"]) for row in trades]
    if not values:
        return {"avg": 0, "median": 0, "max": 0}
    return {
        "avg": round(sum(values) / len(values), 2),
        "median": statistics.median(values),
        "max": max(values),
    }


def trend_review_exit(entry: Any, rows: list[Any], entry_index: int, variant: dict[str, Any]) -> dict[str, Any]:
    hard_stop = entry.open * (1 - base.HARD_STOP_PCT)
    activation_price = entry.open * (1 + base.SWING_TRAILING_ACTIVATION_PCT)
    floor_price = entry.open * (1 + base.SWING_PROFIT_FLOOR_PCT)
    highest = entry.open
    trailing_stop: float | None = None
    observed: list[Any] = []
    reviewed = False

    for offset, row in enumerate(rows[entry_index:], start=1):
        observed.append(row)
        after_review = offset > base.SWING_MAX_HOLD_DAYS or reviewed
        exit_price: float | None = None
        exit_reason = ""

        if row.low <= hard_stop:
            exit_price = hard_stop
            exit_reason = "hard_stop"

        trailing_allowed = (not after_review) or bool(variant["use_trailing_after_review"])
        if trailing_allowed and trailing_stop is not None and row.low <= trailing_stop and (exit_price is None or trailing_stop > exit_price):
            exit_price = trailing_stop
            exit_reason = "trailing_stop"

        if exit_price is not None:
            result = base.build_exit_result(entry, observed, exit_price, exit_reason)
            result["max_hold_review"] = reviewed or offset > base.SWING_MAX_HOLD_DAYS
            return result

        highest = max(highest, row.high)
        if trailing_allowed and highest >= activation_price:
            trailing_stop = max(trailing_stop or 0, highest * (1 - base.SWING_TRAILING_DRAWDOWN_PCT), floor_price)

        if offset >= base.SWING_MAX_HOLD_DAYS:
            absolute_index = entry_index + offset - 1
            condition = variant["review_condition"] if not reviewed else variant["post_condition"]
            if condition(rows, absolute_index):
                reviewed = True
                continue
            result = base.build_exit_result(entry, observed, row.close, "trend_review_close")
            result["max_hold_review"] = True
            return result

    result = base.build_exit_result(entry, observed, rows[-1].close, "latest_close_after_review")
    result["max_hold_review"] = True
    return result


def build_all_trades() -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], dict[str, Any]]:
    pullback_items, rows_by_source, funnel = base.load_pullback_candidates()
    baseline: list[dict[str, Any]] = []
    variants: dict[str, list[dict[str, Any]]] = {variant["id"]: [] for variant in VARIANTS}

    for item in pullback_items:
        rows = rows_by_source[str(item["source"])]
        signal_index = int(item["row_index"])
        entry_index = signal_index + 1
        if entry_index >= len(rows):
            continue
        entry = rows[entry_index]
        if entry.open > float(item["close"]) * (1 - base.ENTRY_DISCOUNT_PCT):
            continue
        swing_candidates = rows[entry_index : entry_index + base.SWING_MAX_HOLD_DAYS]
        if len(swing_candidates) < base.SWING_MAX_HOLD_DAYS:
            continue

        base_trade = base.build_trade(
            item,
            entry,
            base.swing_exit(entry, swing_candidates),
            version="PB-V4-max20",
            exit_style="swing_d2",
        )
        baseline.append(base_trade)

        for variant in VARIANTS:
            perf = trend_review_exit(entry, rows, entry_index, variant)
            trade = base.build_trade(
                item,
                entry,
                perf,
                version=VERSION,
                exit_style=variant["id"],
            )
            trade["max_hold_review"] = bool(perf.get("max_hold_review"))
            variants[variant["id"]].append(trade)

    return baseline, variants, funnel


def compare_rows(baseline: list[dict[str, Any]], variant_trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for base_trade, variant_trade in zip(baseline, variant_trades):
        if base_trade["exit_reason"] != "max_hold_close" and not variant_trade.get("max_hold_review"):
            continue
        rows.append(
            {
                "stock_no": base_trade["stock_no"],
                "stock_name": base_trade["stock_name"],
                "signal_date": base_trade["signal_date"],
                "entry_date": base_trade["entry_date"],
                "entry_price": base_trade["entry_price"],
                "base_exit_date": base_trade["exit_date"],
                "base_exit_reason": base_trade["exit_reason"],
                "base_return_pct": base_trade["return_pct"],
                "base_holding_days": base_trade["holding_days"],
                "variant_exit_date": variant_trade["exit_date"],
                "variant_exit_reason": variant_trade["exit_reason"],
                "variant_return_pct": variant_trade["return_pct"],
                "variant_holding_days": variant_trade["holding_days"],
                "delta_return_pct": round(variant_trade["return_pct"] - base_trade["return_pct"], 2),
                "reasons": base_trade["reasons"],
            }
        )
    return sorted(rows, key=lambda row: row["delta_return_pct"], reverse=True)


def render_html(payload: dict[str, Any]) -> str:
    def fmt_pct(value: Any) -> str:
        return f"{float(value):.2f}%"

    def fmt_money(value: Any) -> str:
        return f"{int(value):,}"

    baseline = payload["baseline_summary"]
    summary_rows = "".join(
        f"<tr>"
        f"<td class='left'>{html.escape(row['name'])}</td>"
        f"<td>{row['trades']}</td>"
        f"<td>{fmt_pct(row['win_rate_pct'])}</td>"
        f"<td>{fmt_pct(row['avg_return_pct'])}</td>"
        f"<td>{fmt_pct(row['median_return_pct'])}</td>"
        f"<td>{fmt_money(row['total_pnl'])}</td>"
        f"<td>{row['reviewed_count']}</td>"
        f"<td>{row['latest_close_after_review_count']}</td>"
        f"<td>{row['exit_reasons']}</td>"
        f"</tr>"
        for row in payload["variant_summaries"]
    )
    best = payload["best_variant"]
    examples = payload["top_examples"].get(best["id"], [])[:15]
    example_rows = "".join(
        f"<tr>"
        f"<td class='left'>{html.escape(row['stock_no'])} {html.escape(str(row['stock_name']))}</td>"
        f"<td>{html.escape(row['signal_date'])}</td>"
        f"<td>{html.escape(row['base_exit_date'])}</td>"
        f"<td>{fmt_pct(row['base_return_pct'])}</td>"
        f"<td>{html.escape(row['variant_exit_date'])}</td>"
        f"<td>{html.escape(row['variant_exit_reason'])}</td>"
        f"<td>{fmt_pct(row['variant_return_pct'])}</td>"
        f"<td>{fmt_pct(row['delta_return_pct'])}</td>"
        f"</tr>"
        for row in examples
    )
    return f"""<!doctype html>
<html lang='zh-Hant'>
<head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<title>{VERSION}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans TC', sans-serif; margin: 0; background: #f6f7fb; color: #172033; line-height: 1.65; }}
main {{ max-width: 1180px; margin: auto; padding: 32px 24px 64px; }}
.card {{ background: #fff; border: 1px solid #e4e7ec; border-radius: 18px; padding: 20px; margin: 18px 0; box-shadow: 0 12px 34px rgba(15,23,42,.06); }}
h1 {{ margin: 0 0 10px; font-size: 34px; }}
table {{ width: 100%; border-collapse: collapse; background: #fff; font-size: 14px; }}
th, td {{ border-bottom: 1px solid #e4e7ec; padding: 10px; text-align: right; vertical-align: top; }}
th {{ background: #f8fafc; }}
.left {{ text-align: left; }}
.note {{ border-left: 4px solid #2563eb; background: #eff6ff; padding: 12px 14px; border-radius: 12px; }}
.warn {{ border-left: 4px solid #b45309; background: #fff7ed; padding: 12px 14px; border-radius: 12px; }}
code {{ background: #f2f4f7; padding: 2px 6px; border-radius: 6px; }}
</style>
</head>
<body><main>
<h1>{VERSION}</h1>
<p class='note'>測試目的：把 PB-V4 的第 20 天 <code>max_hold_close</code> 改成「趨勢檢查」，符合條件就續抱，不符合才出場。</p>
<div class='card'>
<h2>Baseline</h2>
<p>PB-V4 原版：{baseline['trades']} 筆，勝率 {fmt_pct(baseline['win_rate_pct'])}，平均 {fmt_pct(baseline['avg_return_pct'])}，中位數 {fmt_pct(baseline['median_return_pct'])}，總損益 {fmt_money(baseline['total_pnl'])}。</p>
</div>
<div class='card'>
<h2>變體總表</h2>
<table><thead><tr><th class='left'>版本</th><th>交易</th><th>勝率</th><th>平均</th><th>中位數</th><th>總損益</th><th>被趨勢檢查影響</th><th>估到最新收盤</th><th class='left'>出場分布</th></tr></thead><tbody>{summary_rows}</tbody></table>
</div>
<div class='card'>
<h2>目前數字最佳：{html.escape(best['name'])}</h2>
<p class='warn'>平均報酬最高不等於可部署。仍需看勝率、中位數、估值未實現數量，以及後續 holdout / walk-forward。</p>
<table><thead><tr><th class='left'>股票</th><th>訊號日</th><th>PB-V4出場</th><th>PB-V4報酬</th><th>變體出場</th><th class='left'>變體原因</th><th>變體報酬</th><th>差異</th></tr></thead><tbody>{example_rows}</tbody></table>
</div>
</main></body></html>"""


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# {VERSION}",
        "",
        "PB-V4 day-20 max-hold alternatives.",
        "",
        "| Variant | Trades | Win rate | Avg | Median | PnL | Reviewed | Latest close |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in payload["variant_summaries"]:
        lines.append(
            f"| {row['name']} | {row['trades']} | {row['win_rate_pct']:.2f}% | {row['avg_return_pct']:.2f}% | {row['median_return_pct']:.2f}% | {row['total_pnl']:,} | {row['reviewed_count']} | {row['latest_close_after_review_count']} |"
        )
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    baseline, variants, funnel = build_all_trades()
    baseline_summary = base.summarize(baseline)
    variant_summaries = []
    top_examples: dict[str, list[dict[str, Any]]] = {}
    for variant in VARIANTS:
        trades = variants[variant["id"]]
        summary = base.summarize(trades)
        exit_reasons = dict(Counter(row["exit_reason"] for row in trades))
        reviewed_count = sum(1 for row in trades if row.get("max_hold_review"))
        latest_count = exit_reasons.get("latest_close_after_review", 0)
        row = {
            "id": variant["id"],
            "name": variant["name"],
            **summary,
            "holding_days": summarize_holding(trades),
            "reviewed_count": reviewed_count,
            "latest_close_after_review_count": latest_count,
            "exit_reasons": exit_reasons,
        }
        variant_summaries.append(row)
        top_examples[variant["id"]] = compare_rows(baseline, trades)
    best_variant = max(variant_summaries, key=lambda row: (row["avg_return_pct"], row["median_return_pct"], -row["latest_close_after_review_count"]))
    payload = {
        "version": VERSION,
        "methodology": {
            "baseline": "PB-V4 discount-2 swing exit: hard stop -7%, activate trailing at +12%, 12% drawdown with +2% floor, max hold 20 trading days.",
            "test": "Change day-20 forced exit into a trend review. If condition passes, continue; otherwise close at that day's close. Hard stop remains. Trailing stop behavior depends on variant.",
            "capital_per_trade": base.CAPITAL_PER_TRADE,
        },
        "funnel": funnel,
        "baseline_summary": baseline_summary,
        "baseline_exit_reasons": dict(Counter(row["exit_reason"] for row in baseline)),
        "variant_summaries": variant_summaries,
        "best_variant": best_variant,
        "top_examples": top_examples,
    }
    REPORT_DIR.mkdir(exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    OUT_MD.write_text(render_markdown(payload), encoding="utf-8")
    return payload


if __name__ == "__main__":
    result = run()
    print(json.dumps({"baseline_summary": result["baseline_summary"], "best_variant": result["best_variant"], "variant_summaries": result["variant_summaries"]}, ensure_ascii=False, indent=2))
