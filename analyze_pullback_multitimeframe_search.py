#!/usr/bin/env python3
"""Constrained multi-timeframe pullback search with chronological holdout."""

from __future__ import annotations

import html
import itertools
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from analyze_pullback_discount2_swing import summarize
from analyze_pullback_technical_phenotypes import (
    find_series,
    make_series_map,
    technical_features,
)
from run_market_backtest import Row, csv_files, prepare, read_rows


REPORT_DIR = Path("reports")
VERSION = "PB-V8.0-multitimeframe-search"
PBV4_JSON = REPORT_DIR / "pullback_pb_v4_0_1y_discount2_swing.json"
BENCHMARK_CSV = Path("data/benchmark_0050_2025-06-02_2026-06-18.csv")
OUT_JSON = REPORT_DIR / "pullback_pb_v8_multitimeframe_search.json"
OUT_HTML = REPORT_DIR / "pullback_pb_v8_multitimeframe_search.html"


STRUCTURE_MODES = ("baseline", "abc", "abc_fast", "leader_retest")
MARKET_MODES = ("all", "0050_up", "0050_strong", "broad_up")
WEEKLY_MODES = ("all", "trend", "pivot", "trend_pivot")
MONTHLY_MODES = ("all", "trend", "pivot")
SIGNAL_MODES = ("all", "strong_close", "controlled", "quality")
TOP_N_VALUES = (0, 3, 5)


LABELS = {
    "baseline": "原始 PB-V4",
    "abc": "ABC 結構",
    "abc_fast": "ABC 快速回檔",
    "leader_retest": "強勢主升後回測",
    "all": "不限",
    "0050_up": "0050 日線多頭",
    "0050_strong": "0050 主升段",
    "broad_up": "0050 主升 + 市場廣度",
    "trend": "趨勢多頭",
    "pivot": "站上三關價中關",
    "trend_pivot": "趨勢 + 三關價",
    "strong_close": "訊號 K 收高",
    "controlled": "貼近月線回測",
    "quality": "收高 + 貼近月線",
}


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def aggregate_bars(rows: list[Row], index: int, period: str) -> list[dict[str, Any]]:
    signal = rows[index]
    signal_key = (
        signal.date[:7]
        if period == "month"
        else f"{__import__('datetime').date.fromisoformat(signal.date).isocalendar().year}-W{__import__('datetime').date.fromisoformat(signal.date).isocalendar().week:02d}"
    )
    groups: dict[str, list[Row]] = {}
    order: list[str] = []
    for row in rows[:index]:
        if period == "month":
            key = row.date[:7]
        else:
            iso = __import__("datetime").date.fromisoformat(row.date).isocalendar()
            key = f"{iso.year}-W{iso.week:02d}"
        if key == signal_key:
            continue
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)
    return [
        {
            "key": key,
            "open": groups[key][0].open,
            "high": max(row.high for row in groups[key]),
            "low": min(row.low for row in groups[key]),
            "close": groups[key][-1].close,
            "volume": sum(row.volume for row in groups[key]),
        }
        for key in order
    ]


def gate_level(close: float, bar: dict[str, Any]) -> int:
    pivot = (bar["high"] + bar["low"] + bar["close"]) / 3
    upper = 2 * pivot - bar["low"]
    lower = 2 * pivot - bar["high"]
    if close >= upper:
        return 2
    if close >= pivot:
        return 1
    if close >= lower:
        return 0
    return -1


def multitimeframe_features(rows: list[Row], index: int) -> dict[str, Any]:
    row = rows[index]
    weeks = aggregate_bars(rows, index, "week")
    months = aggregate_bars(rows, index, "month")
    weekly_closes = [bar["close"] for bar in weeks]
    monthly_closes = [bar["close"] for bar in months]
    wma4 = mean(weekly_closes[-4:]) if len(weekly_closes) >= 4 else None
    wma13 = mean(weekly_closes[-13:]) if len(weekly_closes) >= 13 else None
    prior_wma4 = mean(weekly_closes[-5:-1]) if len(weekly_closes) >= 5 else None
    mma3 = mean(monthly_closes[-3:]) if len(monthly_closes) >= 3 else None
    prior_mma3 = mean(monthly_closes[-4:-1]) if len(monthly_closes) >= 4 else None
    return {
        "weekly_trend": bool(wma4 and wma13 and prior_wma4 and weekly_closes[-1] > wma4 > wma13 and wma4 > prior_wma4),
        "weekly_gate": gate_level(row.close, weeks[-1]) if weeks else -1,
        "weekly_momentum4_pct": round((weekly_closes[-1] / weekly_closes[-5] - 1) * 100, 2) if len(weekly_closes) >= 5 else None,
        "monthly_trend": bool(mma3 and prior_mma3 and monthly_closes[-1] > mma3 >= prior_mma3),
        "monthly_gate": gate_level(row.close, months[-1]) if months else -1,
        "monthly_momentum3_pct": round((monthly_closes[-1] / monthly_closes[-4] - 1) * 100, 2) if len(monthly_closes) >= 4 else None,
    }


def benchmark_features(rows: list[Row]) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    indicators = prepare(rows)
    dates = {row.date: index for index, row in enumerate(rows)}
    output: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        if index < 60:
            continue
        ma20 = indicators["ma20"][index]
        ma60 = indicators["ma60"][index]
        before20 = indicators["ma20"][index - 10]
        output[row.date] = {
            "benchmark_close": row.close,
            "benchmark_above_ma20": bool(ma20 and row.close > ma20),
            "benchmark_up": bool(ma20 and ma60 and row.close > ma20 > ma60),
            "benchmark_strong": bool(
                ma20 and ma60 and before20 and row.close > ma20 > ma60 and ma20 > before20 and row.close > rows[index - 20].close
            ),
            "benchmark_return20_pct": round((row.close / rows[index - 20].close - 1) * 100, 2),
        }
    return output, dates


def market_breadth(
    series: dict[tuple[str, str], tuple[list[Row], dict[str, list[float | None]], dict[str, int]]],
    benchmark_dates: list[str],
) -> dict[str, dict[str, float]]:
    wanted = set(benchmark_dates)
    counts = {date: [0, 0, 0, []] for date in benchmark_dates}
    for rows, indicators, _ in series.values():
        for index, row in enumerate(rows):
            if row.date not in wanted or index < 60:
                continue
            ma20 = indicators["ma20"][index]
            ma60 = indicators["ma60"][index]
            if ma20 is None or ma60 is None:
                continue
            bucket = counts[row.date]
            bucket[0] += 1
            bucket[1] += int(row.close > ma20)
            bucket[2] += int(row.close > ma60)
            bucket[3].append((row.close / rows[index - 20].close - 1) * 100)
    output: dict[str, dict[str, float]] = {}
    for position, date in enumerate(benchmark_dates):
        total, above20, above60, returns20 = counts[date]
        previous = benchmark_dates[max(0, position - 5)]
        previous_total, previous_above20, _, _ = counts[previous]
        breadth20 = above20 / total if total else 0
        prior_breadth20 = previous_above20 / previous_total if previous_total else breadth20
        output[date] = {
            "breadth20": round(breadth20, 4),
            "breadth60": round(above60 / total, 4) if total else 0,
            "breadth20_change5": round(breadth20 - prior_breadth20, 4),
            "median_return20_pct": round(statistics.median(returns20), 2) if returns20 else 0.0,
            "breadth_universe": total,
        }
    return output


def add_benchmark_return(
    trade: dict[str, Any], benchmark_rows: list[Row], benchmark_dates: dict[str, int]
) -> None:
    entry_index = benchmark_dates.get(trade["entry_date"])
    exit_index = benchmark_dates.get(trade["exit_date"])
    if entry_index is None or exit_index is None:
        trade["benchmark_return_pct"] = None
        trade["excess_return_pct"] = None
        return
    benchmark_return = (benchmark_rows[exit_index].close / benchmark_rows[entry_index].open - 1) * 100
    trade["benchmark_return_pct"] = round(benchmark_return, 2)
    trade["excess_return_pct"] = round(float(trade["return_pct"]) - benchmark_return, 2)


def enrich_trades() -> tuple[list[dict[str, Any]], list[Row]]:
    source = json.loads(PBV4_JSON.read_text(encoding="utf-8"))["trades"]
    series = make_series_map(csv_files())
    benchmark_rows = read_rows(BENCHMARK_CSV)
    benchmark_by_date, benchmark_date_index = benchmark_features(benchmark_rows)
    breadth = market_breadth(series, [row.date for row in benchmark_rows])
    output = []
    for original in source:
        bundle = find_series(series, str(original["market"]), str(original["stock_no"]))
        if not bundle:
            continue
        rows, indicators, dates = bundle
        index = dates.get(original["signal_date"])
        market = benchmark_by_date.get(original["signal_date"])
        broad = breadth.get(original["signal_date"])
        if index is None or index < 65 or not market or not broad:
            continue
        trade = dict(original)
        trade.update(technical_features(rows, indicators, index))
        trade.update(multitimeframe_features(rows, index))
        trade.update(market)
        trade.update(broad)
        add_benchmark_return(trade, benchmark_rows, benchmark_date_index)
        output.append(trade)
    return output, benchmark_rows


def abc_passes(trade: dict[str, Any]) -> bool:
    return (
        trade["ab_gain_pct"] >= 15
        and 2 <= trade["peak_age_days"] <= 15
        and 20 <= trade["bc_retrace_pct"] <= 70
        and trade["close_vs_ma60_pct"] >= 0
    )


def matches(trade: dict[str, Any], rule: dict[str, Any]) -> bool:
    structure = rule["structure"]
    if structure != "baseline" and not abc_passes(trade):
        return False
    if structure == "abc_fast" and not (trade["peak_age_days"] <= 8 and trade["bc_retrace_pct"] <= 55):
        return False
    if structure == "leader_retest" and not (trade["ab_gain_pct"] >= 50 and trade["close_vs_ma60_pct"] >= 10):
        return False

    market = rule["market"]
    if market == "0050_up" and not trade["benchmark_up"]:
        return False
    if market == "0050_strong" and not trade["benchmark_strong"]:
        return False
    if market == "broad_up" and not (trade["benchmark_strong"] and trade["breadth20"] >= 0.45 and trade["breadth20_change5"] >= -0.03):
        return False

    weekly = rule["weekly"]
    if weekly in {"trend", "trend_pivot"} and not trade["weekly_trend"]:
        return False
    if weekly in {"pivot", "trend_pivot"} and trade["weekly_gate"] < 1:
        return False

    monthly = rule["monthly"]
    if monthly == "trend" and not trade["monthly_trend"]:
        return False
    if monthly == "pivot" and trade["monthly_gate"] < 1:
        return False

    signal = rule["signal"]
    if signal in {"strong_close", "quality"} and trade["close_location"] < 0.60:
        return False
    if signal in {"controlled", "quality"} and not (0 <= trade["close_vs_ma20_pct"] <= 8):
        return False
    return True


def qualitative_score(trade: dict[str, Any]) -> float:
    retrace_quality = max(0, 1 - abs(trade["bc_retrace_pct"] - 35) / 35)
    return (
        min(trade["ab_gain_pct"], 150) * 0.04
        + min(trade["close_vs_ma60_pct"], 50) * 0.08
        + trade["close_location"] * 5
        + retrace_quality * 4
        + trade["weekly_gate"] * 1.5
        + trade["monthly_gate"]
        + trade["breadth20"] * 3
    )


def select(trades: list[dict[str, Any]], rule: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        if matches(trade, rule):
            grouped[trade["signal_date"]].append(trade)
    selected = []
    for date in sorted(grouped):
        ranked = sorted(grouped[date], key=qualitative_score, reverse=True)
        selected.extend(ranked if rule["top_n"] == 0 else ranked[: rule["top_n"]])
    return selected


def extended_summary(trades: list[dict[str, Any]]) -> dict[str, Any]:
    summary = summarize(trades)
    benchmark_returns = [float(row["benchmark_return_pct"]) for row in trades if row.get("benchmark_return_pct") is not None]
    excess = [float(row["excess_return_pct"]) for row in trades if row.get("excess_return_pct") is not None]
    summary.update(
        {
            "benchmark_avg_return_pct": round(mean(benchmark_returns), 2),
            "avg_excess_return_pct": round(mean(excess), 2),
            "beat_benchmark_rate_pct": round(sum(value > 0 for value in excess) / len(excess) * 100, 2) if excess else 0.0,
        }
    )
    return summary


def rules() -> list[dict[str, Any]]:
    return [
        {
            "structure": structure,
            "market": market,
            "weekly": weekly,
            "monthly": monthly,
            "signal": signal,
            "top_n": top_n,
        }
        for structure, market, weekly, monthly, signal, top_n in itertools.product(
            STRUCTURE_MODES, MARKET_MODES, WEEKLY_MODES, MONTHLY_MODES, SIGNAL_MODES, TOP_N_VALUES
        )
    ]


def date_split(trades: list[dict[str, Any]]) -> tuple[str, str]:
    dates = sorted({trade["signal_date"] for trade in trades})
    return dates[int(len(dates) * 0.60)], dates[int(len(dates) * 0.80)]


def objective(train: dict[str, Any], validation: dict[str, Any]) -> float:
    worst_win = min(train["win_rate_pct"], validation["win_rate_pct"])
    worst_avg = min(train["avg_return_pct"], validation["avg_return_pct"])
    worst_median = min(train["median_return_pct"], validation["median_return_pct"])
    shortfall = max(60 - worst_win, 0) * 0.9 + max(10 - worst_avg, 0) * 2.0
    instability = abs(train["win_rate_pct"] - validation["win_rate_pct"]) * 0.12 + abs(train["avg_return_pct"] - validation["avg_return_pct"]) * 0.6
    sample_bonus = min(train["trades"] + validation["trades"], 80) * 0.05
    return worst_win * 0.35 + worst_avg * 2.2 + worst_median * 0.5 + sample_bonus - shortfall - instability


def rule_label(rule: dict[str, Any]) -> str:
    top = "全部" if rule["top_n"] == 0 else f"每日前 {rule['top_n']}"
    return "｜".join(
        [
            LABELS[rule["structure"]],
            LABELS[rule["market"]],
            LABELS[rule["weekly"]],
            LABELS[rule["monthly"]],
            LABELS[rule["signal"]],
            top,
        ]
    )


def research(trades: list[dict[str, Any]], benchmark_rows: list[Row]) -> dict[str, Any]:
    validation_start, test_start = date_split(trades)
    segments = {
        "train": [row for row in trades if row["signal_date"] < validation_start],
        "validation": [row for row in trades if validation_start <= row["signal_date"] < test_start],
        "test": [row for row in trades if row["signal_date"] >= test_start],
        "full": trades,
    }
    candidates = []
    full_target_hits = []
    for rule in rules():
        selected = {name: select(rows, rule) for name, rows in segments.items()}
        stats = {name: extended_summary(rows) for name, rows in selected.items()}
        if stats["full"]["trades"] >= 30 and stats["full"]["win_rate_pct"] >= 60 and stats["full"]["avg_return_pct"] >= 10:
            full_target_hits.append({"rule": rule, "label": rule_label(rule), "summaries": stats})
        if stats["train"]["trades"] < 20 or stats["validation"]["trades"] < 8:
            continue
        candidates.append({"score": objective(stats["train"], stats["validation"]), "rule": rule, "label": rule_label(rule), "summaries": stats})
    candidates.sort(key=lambda item: item["score"], reverse=True)
    if not candidates:
        raise RuntimeError("No multi-timeframe candidate had enough chronological samples.")
    chosen = candidates[0]
    chosen_trades = {name: select(rows, chosen["rule"]) for name, rows in segments.items()}
    test = chosen["summaries"]["test"]
    target_test = test["trades"] >= 10 and test["win_rate_pct"] >= 60 and test["avg_return_pct"] >= 10

    full_target_hits.sort(
        key=lambda item: (item["summaries"]["full"]["trades"], item["summaries"]["full"]["avg_return_pct"]),
        reverse=True,
    )
    monthly = {
        month: extended_summary([row for row in chosen_trades["full"] if row["signal_date"].startswith(month)])
        for month in sorted({row["signal_date"][:7] for row in chosen_trades["full"]})
    }
    benchmark_start = next(row for row in benchmark_rows if row.date >= min(item["entry_date"] for item in trades))
    benchmark_end = next(row for row in reversed(benchmark_rows) if row.date <= max(item["exit_date"] for item in trades))
    benchmark_hold = round((benchmark_end.close / benchmark_start.open - 1) * 100, 2)
    return {
        "version": VERSION,
        "methodology": {
            "base": "PB-V4 next-open discount-2 entries and exits",
            "candidate_modules": "daily ABC, 0050 regime, all-market breadth, completed weekly/monthly trend, prior-period three-gate pivots, signal-candle quality, daily top-N qualitative ranking",
            "candidate_count": len(rules()),
            "selection": "highest train+validation objective with minimum 20 train and 8 validation trades; final 20% test untouched",
            "target": "at least 60% win rate and 10% average return, with at least 10 test trades",
        },
        "split": {"validation_start": validation_start, "test_start": test_start},
        "universe_trades": len(trades),
        "benchmark": {
            "name": "0050",
            "start_date": benchmark_start.date,
            "end_date": benchmark_end.date,
            "buy_hold_return_pct": benchmark_hold,
        },
        "chosen": chosen,
        "target_met_on_test": target_test,
        "full_target_hit_count": len(full_target_hits),
        "top_full_target_hits": full_target_hits[:20],
        "top_train_validation_candidates": candidates[:20],
        "monthly": monthly,
        "chosen_trades": chosen_trades["full"],
    }


def summary_text(stats: dict[str, Any]) -> str:
    return f"{stats['trades']} 筆｜勝率 {stats['win_rate_pct']:.2f}%｜平均 {stats['avg_return_pct']:.2f}%｜中位 {stats['median_return_pct']:.2f}%"


def render_html(payload: dict[str, Any]) -> str:
    chosen = payload["chosen"]
    segment_labels = {"train": "訓練 60%", "validation": "驗證 20%", "test": "留出測試 20%", "full": "完整一年"}
    cards = "".join(
        f"<article><span>{label}</span><strong>{html.escape(summary_text(chosen['summaries'][name]))}</strong><small>平均超額 {chosen['summaries'][name]['avg_excess_return_pct']:.2f}%｜勝過 0050 {chosen['summaries'][name]['beat_benchmark_rate_pct']:.2f}%</small></article>"
        for name, label in segment_labels.items()
    )
    hit_rows = "".join(
        f"<tr><td>{html.escape(item['label'])}</td><td>{html.escape(summary_text(item['summaries']['full']))}</td><td>{html.escape(summary_text(item['summaries']['test']))}</td></tr>"
        for item in payload["top_full_target_hits"]
    ) or "<tr><td colspan='3'>沒有完整一年同時達到 60% 勝率、10% 平均且至少 30 筆的組合。</td></tr>"
    month_rows = "".join(
        f"<tr><td>{month}</td><td>{html.escape(summary_text(stats))}</td><td>{stats['avg_excess_return_pct']:.2f}%</td></tr>"
        for month, stats in payload["monthly"].items()
    )
    trade_rows = "".join(
        f"<tr><td>{row['signal_date']}</td><td>{html.escape(str(row['stock_no'])+' '+str(row['stock_name']))}</td><td>{row['return_pct']:.2f}%</td><td>{row.get('benchmark_return_pct',0):.2f}%</td><td>{row.get('excess_return_pct',0):.2f}%</td><td>{row['weekly_gate']}</td><td>{row['monthly_gate']}</td></tr>"
        for row in sorted(payload["chosen_trades"], key=lambda item: item["signal_date"], reverse=True)
    )
    status = "留出樣本達標" if payload["target_met_on_test"] else "留出樣本未達標"
    status_class = "pass" if payload["target_met_on_test"] else "fail"
    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PB-V8 多週期主升段研究</title><style>
:root{{--bg:#f4f6f5;--paper:#fff;--ink:#17201d;--muted:#68736e;--line:#dce2df;--good:#08735d;--bad:#a33d31}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 system-ui,"Microsoft JhengHei",sans-serif}}header,main{{max-width:1480px;margin:auto;padding:26px 20px}}header{{border-bottom:1px solid var(--line)}}h1{{margin:0 0 7px;font-size:28px;letter-spacing:0}}h2{{font-size:19px;letter-spacing:0;margin:28px 0 10px}}p,small{{color:var(--muted)}}.status{{display:inline-block;padding:6px 10px;border:1px solid currentColor;font-weight:700}}.pass{{color:var(--good)}}.fail{{color:var(--bad)}}.cards{{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin:18px 0}}article{{background:var(--paper);border:1px solid var(--line);padding:14px;border-radius:6px}}article span,article strong,article small{{display:block}}article strong{{font-size:17px;margin:4px 0}}.rule{{background:#eef4f1;border-left:4px solid var(--good);padding:13px 15px}}.table{{overflow:auto;background:var(--paper);border:1px solid var(--line)}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:left}}th{{font-size:12px;color:var(--muted);background:#eef1ef}}@media(max-width:760px){{.cards{{grid-template-columns:1fr}}header,main{{padding:18px 10px}}h1{{font-size:23px}}}}
</style></head><body><header><h1>PB-V8 多週期主升段研究</h1><p>每日 Pullback 訊號加入 0050 主升段、市場廣度、週月線與三關價，以時間留出樣本檢查能否達到勝率 60%、平均 10%。</p><span class="status {status_class}">{status}</span></header><main>
<div class="rule"><strong>訓練＋驗證選出的規則</strong><br>{html.escape(chosen['label'])}<br><small>共搜尋 {payload['methodology']['candidate_count']} 組可解釋組合；測試區未參與選擇。</small></div>
<div class="cards">{cards}</div><p>0050 同期買進持有：{payload['benchmark']['start_date']} 至 {payload['benchmark']['end_date']}，{payload['benchmark']['buy_hold_return_pct']:.2f}%。</p>
<h2>完整一年達標的探索組合</h2><p>這張表包含測試期資訊，只能說明是否存在候選，不能視為樣本外證明。共 {payload['full_target_hit_count']} 組達標。</p><div class="table"><table><thead><tr><th>規則</th><th>完整一年</th><th>最後 20%</th></tr></thead><tbody>{hit_rows}</tbody></table></div>
<h2>選定規則逐月表現</h2><div class="table"><table><thead><tr><th>月份</th><th>績效</th><th>平均超額</th></tr></thead><tbody>{month_rows}</tbody></table></div>
<h2>選定規則交易明細</h2><div class="table"><table><thead><tr><th>訊號日</th><th>股票</th><th>策略報酬</th><th>同期0050</th><th>超額</th><th>週三關</th><th>月三關</th></tr></thead><tbody>{trade_rows}</tbody></table></div>
</main></body></html>"""


def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    trades, benchmark_rows = enrich_trades()
    payload = research(trades, benchmark_rows)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    print(json.dumps({
        "chosen": payload["chosen"],
        "target_met_on_test": payload["target_met_on_test"],
        "full_target_hit_count": payload["full_target_hit_count"],
        "benchmark": payload["benchmark"],
        "html": str(OUT_HTML),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
