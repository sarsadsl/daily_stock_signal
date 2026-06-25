#!/usr/bin/env python3
"""Correct PB-V11 rolling scores to use every prior pullback signal."""

from __future__ import annotations

import html
import json
import statistics
from pathlib import Path
from typing import Any, Callable

from analyze_pullback_core_position import stats
from analyze_pullback_discount2_swing import swing_exit
from analyze_pullback_multitimeframe_search import (
    BENCHMARK_CSV,
    add_benchmark_return,
    date_split,
    enrich_trades,
    multitimeframe_features,
)
from analyze_pullback_pb_v13_frozen_3y import simulate_frozen_wide_exit
from analyze_pullback_rolling_climax import add_rolling_climax_scores, variant_rows
from analyze_pullback_technical_phenotypes import find_series, make_series_map, technical_features
from analyze_pullback_versioned import research_csv_files
from run_market_backtest import csv_files, read_rows


REPORT_DIR = Path("reports")
PBV2_JSON = REPORT_DIR / "pullback_pb_v2_0_3y.json"
OUT_JSON = REPORT_DIR / "pullback_pb_v15_all_signal_history.json"
OUT_HTML = REPORT_DIR / "pullback_pb_v15_all_signal_history.html"
VERSION = "PB-V15.0-all-signal-history"


def trade_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row["market"]).upper(),
        str(row["stock_no"]),
        str(row["signal_date"]),
    )


def enrich_all_three_year_signals() -> tuple[
    list[dict[str, Any]],
    dict[tuple[str, str], tuple[Any, Any, Any]],
]:
    series = make_series_map(research_csv_files())
    source = json.loads(PBV2_JSON.read_text(encoding="utf-8"))["trades"]
    deduplicated: dict[tuple[str, str, str], dict[str, Any]] = {}
    for original in source:
        key = trade_key(original)
        if key in deduplicated:
            continue
        bundle = find_series(series, key[0], key[1])
        if not bundle:
            continue
        rows, indicators, dates = bundle
        signal_index = dates.get(key[2])
        if signal_index is None or signal_index < 65:
            continue
        signal = dict(original)
        signal.update(technical_features(rows, indicators, signal_index))
        signal.update(multitimeframe_features(rows, signal_index))
        deduplicated[key] = signal
    signals = list(deduplicated.values())
    add_rolling_climax_scores(signals)
    return signals, series


def attach_prior_only_scores(
    one_year: list[dict[str, Any]],
    historical_signals: list[dict[str, Any]],
) -> dict[str, Any]:
    combined: dict[tuple[str, str, str], dict[str, Any]] = {
        trade_key(row): dict(row) for row in historical_signals
    }
    added = 0
    for row in one_year:
        key = trade_key(row)
        if key not in combined:
            combined[key] = dict(row)
            added += 1
    timeline = list(combined.values())
    add_rolling_climax_scores(timeline)
    scored = {trade_key(row): row for row in timeline}
    missing = 0
    for row in one_year:
        score = scored.get(trade_key(row))
        if not score:
            missing += 1
            continue
        row["climax_score"] = score["climax_score"]
        row["climax_history_count"] = score["climax_history_count"]
        row["climax_flags"] = score["climax_flags"]
    return {
        "combined_signal_count": len(timeline),
        "one_year_unique_signals_added": added,
        "one_year_missing_scores": missing,
    }


def make_pbv4_row(signal: dict[str, Any], performance: dict[str, Any]) -> dict[str, Any]:
    result = {
        **signal,
        **performance,
        "entry_date": performance["entry_date"],
        "entry_price": performance["entry_price"],
        "unresolved": False,
    }
    result["pnl"] = round(result["return_pct"] / 100 * 100_000)
    return result


def replay_three_year(
    historical_signals: list[dict[str, Any]],
    series: dict[tuple[str, str], tuple[Any, Any, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pbv4_rows: list[dict[str, Any]] = []
    wide_rows: list[dict[str, Any]] = []
    for signal in variant_rows(historical_signals, "avoid_score4"):
        bundle = find_series(series, str(signal["market"]), str(signal["stock_no"]))
        if not bundle:
            continue
        rows, _, dates = bundle
        signal_index = dates.get(str(signal["signal_date"]))
        if signal_index is None or signal_index + 21 >= len(rows):
            continue
        entry_index = signal_index + 1
        entry = rows[entry_index]
        if entry.open > float(signal["signal_close"]) * 0.98:
            continue
        pbv4 = swing_exit(entry, rows[entry_index : entry_index + 20])
        pbv4_rows.append(make_pbv4_row(signal, {
            **pbv4,
            "entry_date": entry.date,
            "entry_price": round(entry.open, 4),
        }))
        wide = {
            **signal,
            **simulate_frozen_wide_exit(entry, rows, entry_index),
            "entry_date": entry.date,
            "entry_price": round(entry.open, 4),
        }
        wide["pnl"] = round(wide["return_pct"] / 100 * 100_000)
        wide_rows.append(wide)
    return pbv4_rows, wide_rows


def replay_one_year(
    selected: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    series = make_series_map(csv_files())
    benchmark_rows = read_rows(BENCHMARK_CSV)
    benchmark_dates = {row.date: index for index, row in enumerate(benchmark_rows)}
    pbv4_rows: list[dict[str, Any]] = []
    wide_rows: list[dict[str, Any]] = []
    for trade in selected:
        bundle = find_series(series, str(trade["market"]), str(trade["stock_no"]))
        if not bundle:
            continue
        rows, _, dates = bundle
        signal_index = dates.get(str(trade["signal_date"]))
        if signal_index is None or signal_index + 1 >= len(rows):
            continue
        entry_index = signal_index + 1
        entry = rows[entry_index]
        pbv4_rows.append({**trade, "unresolved": False})
        wide = {
            **trade,
            **simulate_frozen_wide_exit(entry, rows, entry_index),
            "entry_date": entry.date,
            "entry_price": round(entry.open, 4),
        }
        wide["pnl"] = round(wide["return_pct"] / 100 * 100_000)
        add_benchmark_return(wide, benchmark_rows, benchmark_dates)
        wide_rows.append(wide)
    return pbv4_rows, wide_rows


def paired_summary(
    pbv4_rows: list[dict[str, Any]],
    wide_rows: list[dict[str, Any]],
    predicate: Callable[[dict[str, Any]], bool],
) -> dict[str, Any]:
    pbv4 = [row for row in pbv4_rows if predicate(row)]
    wide = [row for row in wide_rows if predicate(row)]
    return {
        "pbv4": stats(pbv4),
        "wide_mark_to_market": stats(wide),
        "wide_resolved": stats([row for row in wide if not row["unresolved"]]),
        "wide_unresolved": stats([row for row in wide if row["unresolved"]]),
    }


def score_diagnostics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for year in sorted({row["signal_date"][:4] for row in rows}):
        group = [row for row in rows if row["signal_date"].startswith(year)]
        histories = [int(row["climax_history_count"]) for row in group]
        output[year] = {
            "signals": len(group),
            "minimum_history": min(histories) if histories else 0,
            "median_history": statistics.median(histories) if histories else 0,
            "score_zero_pct": round(sum(row["climax_score"] == 0 for row in group) / len(group) * 100, 2) if group else 0.0,
        }
    return output


def run() -> dict[str, Any]:
    historical_signals, research_series = enrich_all_three_year_signals()
    one_year, _ = enrich_trades()
    coverage = attach_prior_only_scores(one_year, historical_signals)

    three_pbv4, three_wide = replay_three_year(historical_signals, research_series)
    one_selected = variant_rows(one_year, "avoid_score4")
    one_pbv4, one_wide = replay_one_year(one_selected)
    validation_start, test_start = date_split(one_year)

    one_periods = {
        "full": paired_summary(one_pbv4, one_wide, lambda row: True),
        "train": paired_summary(one_pbv4, one_wide, lambda row: row["signal_date"] < validation_start),
        "validation": paired_summary(
            one_pbv4,
            one_wide,
            lambda row: validation_start <= row["signal_date"] < test_start,
        ),
        "test": paired_summary(one_pbv4, one_wide, lambda row: row["signal_date"] >= test_start),
    }
    three_periods = {
        "full": paired_summary(three_pbv4, three_wide, lambda row: True),
        "pre2026": paired_summary(three_pbv4, three_wide, lambda row: row["signal_date"] < "2026-01-01"),
        "post2026": paired_summary(three_pbv4, three_wide, lambda row: row["signal_date"] >= "2026-01-01"),
    }
    years = sorted({row["signal_date"][:4] for row in three_wide})
    by_year = {
        year: paired_summary(
            three_pbv4,
            three_wide,
            lambda row, y=year: row["signal_date"].startswith(y),
        )
        for year in years
    }
    full = one_periods["full"]["wide_resolved"]
    test = one_periods["test"]["wide_resolved"]
    return {
        "version": VERSION,
        "methodology": {
            "rolling_population": "every prior deduplicated pullback signal, before next-open execution filtering",
            "history": "last 60 prior signals; same-date signals excluded; minimum 30",
            "entry": "PB-V11 ABC/monthly/MA20 base entry, climax score below 4, then next-open discount 2%",
            "exits": "PB-V4 fixed 20-day policy and frozen +15% activation / 18% drawdown wide trail",
            "parameter_search": "none",
        },
        "history_coverage": coverage,
        "historical_raw_signal_count": len(historical_signals),
        "score_diagnostics": score_diagnostics(historical_signals),
        "one_year_split": {"validation_start": validation_start, "test_start": test_start},
        "one_year_periods": one_periods,
        "three_year_periods": three_periods,
        "three_year_by_year": by_year,
        "one_year_target_met": full["trades"] >= 30 and full["win_rate_pct"] >= 60 and full["avg_return_pct"] >= 10,
        "one_year_test_target_met": test["trades"] >= 10 and test["win_rate_pct"] >= 60 and test["avg_return_pct"] >= 10,
        "one_year_trades": one_wide,
        "three_year_trades": three_wide,
    }


def compact(value: dict[str, Any]) -> str:
    return (
        f"{value['trades']} 筆｜勝率 {value['win_rate_pct']:.2f}%｜"
        f"平均 {value['avg_return_pct']:.2f}%｜中位 {value['median_return_pct']:.2f}%｜"
        f"未實現 {value['unresolved']}"
    )


def render_html(payload: dict[str, Any]) -> str:
    one_labels = {"full": "完整一年", "train": "訓練", "validation": "驗證", "test": "最後20%"}
    one_rows = "".join(
        f"<tr><th>{one_labels[key]}</th><td>{html.escape(compact(value['pbv4']))}</td>"
        f"<td>{html.escape(compact(value['wide_mark_to_market']))}</td>"
        f"<td>{html.escape(compact(value['wide_resolved']))}</td></tr>"
        for key, value in payload["one_year_periods"].items()
    )
    year_rows = "".join(
        f"<tr><th>{year}</th><td>{html.escape(compact(value['pbv4']))}</td>"
        f"<td>{html.escape(compact(value['wide_resolved']))}</td></tr>"
        for year, value in payload["three_year_by_year"].items()
    )
    diagnostic_rows = "".join(
        f"<tr><th>{year}</th><td>{value['signals']}</td><td>{value['minimum_history']}</td>"
        f"<td>{value['median_history']}</td><td>{value['score_zero_pct']:.2f}%</td></tr>"
        for year, value in payload["score_diagnostics"].items()
    )
    trade_rows = "".join(
        f"<tr><td>{row['signal_date']}</td><td>{html.escape(str(row['stock_no']) + ' ' + str(row['stock_name']))}</td>"
        f"<td>{row['climax_score']}</td><td>{row['climax_history_count']}</td>"
        f"<td class={'pos' if row['return_pct'] > 0 else 'neg'}>{row['return_pct']:.2f}%</td>"
        f"<td>{row['holding_days']}</td><td>{html.escape(row['exit_reason'])}</td>"
        f"<td>{'是' if row['unresolved'] else '否'}</td></tr>"
        for row in sorted(payload["one_year_trades"], key=lambda item: item["signal_date"], reverse=True)
    )
    full = payload["one_year_periods"]["full"]["wide_resolved"]
    test = payload["one_year_periods"]["test"]["wide_resolved"]
    passed = payload["one_year_target_met"] and payload["one_year_test_target_met"]
    status = "一年與最後20%都達標" if passed else "冷啟動修正後仍未通過完整驗證"
    tone = "pass" if passed else "fail"
    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PB-V15 全訊號歷史修正</title><style>
:root{{--bg:#f4f6f5;--paper:#fff;--ink:#18211e;--muted:#68736f;--line:#dbe2de;--good:#08735d;--bad:#a13e34;--accent:#245b78}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 system-ui,"Microsoft JhengHei",sans-serif}}header,main{{max-width:1500px;margin:auto;padding:26px 20px}}header{{border-bottom:1px solid var(--line)}}h1{{margin:0 0 6px;font-size:28px;letter-spacing:0}}h2{{margin:30px 0 10px;font-size:19px;letter-spacing:0}}p{{margin:6px 0;color:var(--muted)}}.status{{display:inline-block;margin-top:12px;padding:7px 11px;border:1px solid currentColor;font-weight:750}}.pass,.pos{{color:var(--good)}}.fail,.neg{{color:var(--bad)}}.metrics{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1px;margin-top:24px;background:var(--line);border:1px solid var(--line)}}.metric{{background:var(--paper);padding:16px}}.metric strong{{display:block;font-size:20px}}.note{{margin-top:18px;border-left:4px solid var(--accent);background:#edf3f5;padding:13px 15px}}.table{{overflow:auto;border:1px solid var(--line);background:var(--paper)}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:left}}thead th{{font-size:12px;color:var(--muted);background:#eef1ef}}tbody th{{font-weight:650}}@media(max-width:760px){{header,main{{padding:18px 10px}}h1{{font-size:23px}}.metrics{{grid-template-columns:1fr}}}}
</style></head><body><header><h1>PB-V15 全訊號歷史修正</h1><p>先用所有過去 pullback 訊號建立過熱分布，隔日開低 2% 只在最後作為成交條件。</p><span class="status {tone}">{status}</span><div class="metrics"><div class="metric"><span>完整一年，僅已出場</span><strong>{full['win_rate_pct']:.2f}% / {full['avg_return_pct']:.2f}%</strong><small>{full['trades']} 筆，勝率 / 平均報酬</small></div><div class="metric"><span>最後20%，僅已出場</span><strong>{test['win_rate_pct']:.2f}% / {test['avg_return_pct']:.2f}%</strong><small>{test['trades']} 筆，勝率 / 平均報酬</small></div><div class="metric"><span>三年原始歷史</span><strong>{payload['historical_raw_signal_count']:,}</strong><small>去重後 pullback 訊號</small></div></div></header><main><div class="note"><strong>修正重點：</strong>舊版只用隔日開低 2% 的少數成交樣本建立分位數；本版使用每一筆更早的 pullback 訊號，且同一天訊號不互相看見。沒有改動 ABC、過熱分數上限或出場參數。</div><h2>一年資料集</h2><div class="table"><table><thead><tr><th>區間</th><th>PB-V4</th><th>寬停利含未實現</th><th>寬停利僅已出場</th></tr></thead><tbody>{one_rows}</tbody></table></div><h2>三年逐年</h2><div class="table"><table><thead><tr><th>年度</th><th>PB-V4</th><th>寬停利僅已出場</th></tr></thead><tbody>{year_rows}</tbody></table></div><h2>冷啟動稽核</h2><div class="table"><table><thead><tr><th>年度</th><th>原始訊號</th><th>最少歷史</th><th>歷史中位數</th><th>0分比例</th></tr></thead><tbody>{diagnostic_rows}</tbody></table></div><h2>一年交易明細</h2><div class="table"><table><thead><tr><th>訊號日</th><th>股票</th><th>過熱分</th><th>歷史樣本</th><th>報酬</th><th>持有日</th><th>出場</th><th>未實現</th></tr></thead><tbody>{trade_rows}</tbody></table></div></main></body></html>"""


def main() -> None:
    payload = run()
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    print(json.dumps({
        "historical_raw_signal_count": payload["historical_raw_signal_count"],
        "history_coverage": payload["history_coverage"],
        "one_year_full": payload["one_year_periods"]["full"],
        "one_year_test": payload["one_year_periods"]["test"],
        "three_year_resolved_by_year": {
            year: value["wide_resolved"]
            for year, value in payload["three_year_by_year"].items()
        },
        "one_year_target_met": payload["one_year_target_met"],
        "one_year_test_target_met": payload["one_year_test_target_met"],
        "html": str(OUT_HTML),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
