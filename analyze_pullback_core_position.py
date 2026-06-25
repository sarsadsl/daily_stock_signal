#!/usr/bin/env python3
"""Test tactical/core position management on the frozen PB-V8 entry rule."""

from __future__ import annotations

import html
import json
from datetime import date
from pathlib import Path
from typing import Any

from analyze_pullback_discount2_swing import summarize
from analyze_pullback_multitimeframe_search import (
    BENCHMARK_CSV,
    PBV4_JSON,
    add_benchmark_return,
    enrich_trades,
    extended_summary,
    find_series,
    make_series_map,
    select,
)
from run_market_backtest import Row, csv_files, read_rows


REPORT_DIR = Path("reports")
VERSION = "PB-V9.0-core-position"
OUT_JSON = REPORT_DIR / "pullback_pb_v9_core_position.json"
OUT_HTML = REPORT_DIR / "pullback_pb_v9_core_position.html"

ENTRY_RULE = {
    "structure": "abc_fast",
    "market": "all",
    "weekly": "all",
    "monthly": "trend",
    "signal": "controlled",
    "top_n": 0,
}

EXIT_STYLES = (
    "pbv4",
    "ma20_core",
    "weekly_core",
    "wide_trail",
    "hybrid50_ma20",
    "hybrid50_weekly",
    "hybrid30_tactical70_weekly",
    "hybrid50_wide",
    "hybrid30_tactical70_wide",
)

EXIT_LABELS = {
    "pbv4": "PB-V4 全部戰術倉",
    "ma20_core": "MA20 核心倉",
    "weekly_core": "週線核心倉",
    "wide_trail": "+20% 後回撤 15%",
    "hybrid50_ma20": "50% PB-V4 + 50% MA20",
    "hybrid50_weekly": "50% PB-V4 + 50% 週線",
    "hybrid30_tactical70_weekly": "30% PB-V4 + 70% 週線",
    "hybrid50_wide": "50% PB-V4 + 50% 寬幅移動停利",
    "hybrid30_tactical70_wide": "30% PB-V4 + 70% 寬幅移動停利",
}


def exit_result(entry: Row, observed: list[Row], price: float, reason: str, unresolved: bool = False) -> dict[str, Any]:
    return {
        "exit_date": observed[-1].date,
        "exit_price": round(price, 4),
        "holding_days": len(observed),
        "return_pct": round((price / entry.open - 1) * 100, 2),
        "exit_reason": reason,
        "unresolved": unresolved,
    }


def ma20_core_exit(entry: Row, rows: list[Row], indicators: dict[str, list[float | None]], entry_index: int) -> dict[str, Any]:
    hard_stop = entry.open * 0.93
    observed: list[Row] = []
    for cursor in range(entry_index, len(rows)):
        row = rows[cursor]
        observed.append(row)
        if row.low <= hard_stop:
            return exit_result(entry, observed, hard_stop, "hard_stop")
        ma20 = indicators["ma20"][cursor]
        prior_ma20 = indicators["ma20"][cursor - 3] if cursor >= 3 else None
        if len(observed) >= 10 and ma20 and prior_ma20 and row.close < ma20 and ma20 <= prior_ma20:
            return exit_result(entry, observed, row.close, "ma20_trend_break")
    return exit_result(entry, observed, observed[-1].close, "latest_close", unresolved=True)


def week_key(value: str) -> tuple[int, int]:
    iso = date.fromisoformat(value).isocalendar()
    return iso.year, iso.week


def completed_week_closes(rows: list[Row], cursor: int) -> list[float]:
    groups: list[list[Row]] = []
    current_key: tuple[int, int] | None = None
    for row in rows[: cursor + 1]:
        key = week_key(row.date)
        if key != current_key:
            groups.append([])
            current_key = key
        groups[-1].append(row)
    return [group[-1].close for group in groups]


def weekly_core_exit(entry: Row, rows: list[Row], entry_index: int) -> dict[str, Any]:
    hard_stop = entry.open * 0.93
    observed: list[Row] = []
    for cursor in range(entry_index, len(rows)):
        row = rows[cursor]
        observed.append(row)
        if row.low <= hard_stop:
            return exit_result(entry, observed, hard_stop, "hard_stop")
        is_week_end = cursor == len(rows) - 1 or week_key(rows[cursor + 1].date) != week_key(row.date)
        if len(observed) < 10 or not is_week_end:
            continue
        closes = completed_week_closes(rows, cursor)
        if len(closes) < 5:
            continue
        wma4 = sum(closes[-4:]) / 4
        prior_wma4 = sum(closes[-5:-1]) / 4
        if row.close < wma4 and wma4 <= prior_wma4:
            return exit_result(entry, observed, row.close, "weekly_trend_break")
    return exit_result(entry, observed, observed[-1].close, "latest_close", unresolved=True)


def wide_trail_exit(entry: Row, rows: list[Row], entry_index: int) -> dict[str, Any]:
    hard_stop = entry.open * 0.93
    activation = entry.open * 1.20
    highest = entry.open
    trailing: float | None = None
    observed: list[Row] = []
    for row in rows[entry_index:]:
        observed.append(row)
        if row.low <= hard_stop:
            return exit_result(entry, observed, hard_stop, "hard_stop")
        if trailing is not None and row.low <= trailing:
            return exit_result(entry, observed, trailing, "wide_trailing_stop")
        highest = max(highest, row.high)
        if highest >= activation:
            trailing = max(trailing or 0, highest * 0.85, entry.open * 1.02)
    return exit_result(entry, observed, observed[-1].close, "latest_close", unresolved=True)


def hybrid_result(tactical: dict[str, Any], core: dict[str, Any], tactical_weight: float, label: str) -> dict[str, Any]:
    core_weight = 1 - tactical_weight
    return_pct = tactical["return_pct"] * tactical_weight + core["return_pct"] * core_weight
    return {
        "exit_date": core["exit_date"],
        "exit_price": core["exit_price"],
        "holding_days": max(tactical["holding_days"], core["holding_days"]),
        "return_pct": round(return_pct, 2),
        "exit_reason": label,
        "unresolved": core["unresolved"],
    }


def rebuild_exits(base_trades: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    source_payload = json.loads(PBV4_JSON.read_text(encoding="utf-8"))
    source_by_key = {
        (row["signal_date"], row["market"], row["stock_no"]): row
        for row in source_payload["trades"]
    }
    series = make_series_map(csv_files())
    benchmark_rows = read_rows(BENCHMARK_CSV)
    benchmark_dates = {row.date: index for index, row in enumerate(benchmark_rows)}
    output = {style: [] for style in EXIT_STYLES}
    for trade in base_trades:
        source = source_by_key[(trade["signal_date"], trade["market"], trade["stock_no"])]
        bundle = find_series(series, str(trade["market"]), str(trade["stock_no"]))
        if not bundle:
            continue
        rows, indicators, dates = bundle
        signal_index = dates.get(trade["signal_date"])
        if signal_index is None or signal_index + 1 >= len(rows):
            continue
        entry_index = signal_index + 1
        entry = rows[entry_index]
        tactical = {
            "exit_date": source["exit_date"],
            "exit_price": source["exit_price"],
            "holding_days": source["holding_days"],
            "return_pct": source["return_pct"],
            "exit_reason": source["exit_reason"],
            "unresolved": False,
        }
        ma20 = ma20_core_exit(entry, rows, indicators, entry_index)
        weekly = weekly_core_exit(entry, rows, entry_index)
        wide = wide_trail_exit(entry, rows, entry_index)
        results = {
            "pbv4": tactical,
            "ma20_core": ma20,
            "weekly_core": weekly,
            "wide_trail": wide,
            "hybrid50_ma20": hybrid_result(tactical, ma20, 0.50, "50% PB-V4 + 50% MA20"),
            "hybrid50_weekly": hybrid_result(tactical, weekly, 0.50, "50% PB-V4 + 50% weekly"),
            "hybrid30_tactical70_weekly": hybrid_result(tactical, weekly, 0.30, "30% PB-V4 + 70% weekly"),
            "hybrid50_wide": hybrid_result(tactical, wide, 0.50, "50% PB-V4 + 50% wide trail"),
            "hybrid30_tactical70_wide": hybrid_result(tactical, wide, 0.30, "30% PB-V4 + 70% wide trail"),
        }
        for style, result in results.items():
            row = {**trade, **result, "exit_style": style}
            row["pnl"] = round(row["return_pct"] / 100 * 100_000)
            add_benchmark_return(row, benchmark_rows, benchmark_dates)
            output[style].append(row)
    return output


def stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result = extended_summary(rows)
    result["unresolved"] = sum(bool(row.get("unresolved")) for row in rows)
    return result


def objective(train: dict[str, Any], validation: dict[str, Any]) -> float:
    worst_win = min(train["win_rate_pct"], validation["win_rate_pct"])
    worst_avg = min(train["avg_return_pct"], validation["avg_return_pct"])
    instability = abs(train["avg_return_pct"] - validation["avg_return_pct"]) * 0.7
    unresolved_penalty = (train["unresolved"] + validation["unresolved"]) * 0.2
    return worst_win * 0.4 + worst_avg * 2.5 - max(60 - worst_win, 0) - max(10 - worst_avg, 0) * 2 - instability - unresolved_penalty


def research() -> dict[str, Any]:
    enriched, _ = enrich_trades()
    selected = select(enriched, ENTRY_RULE)
    exits = rebuild_exits(selected)
    v8 = json.loads((REPORT_DIR / "pullback_pb_v8_multitimeframe_search.json").read_text(encoding="utf-8"))
    validation_start = v8["split"]["validation_start"]
    test_start = v8["split"]["test_start"]
    summaries: dict[str, Any] = {}
    for style, rows in exits.items():
        segments = {
            "train": [row for row in rows if row["signal_date"] < validation_start],
            "validation": [row for row in rows if validation_start <= row["signal_date"] < test_start],
            "test": [row for row in rows if row["signal_date"] >= test_start],
            "full": rows,
        }
        summaries[style] = {name: stats(segment) for name, segment in segments.items()}
        summaries[style]["resolved_full"] = stats([row for row in rows if not row["unresolved"]])
        summaries[style]["unresolved_full"] = stats([row for row in rows if row["unresolved"]])
        summaries[style]["selection_score"] = objective(summaries[style]["train"], summaries[style]["validation"])
    chosen_style = max(EXIT_STYLES, key=lambda style: summaries[style]["selection_score"])
    chosen = summaries[chosen_style]
    test = chosen["test"]
    target_met = test["trades"] >= 10 and test["win_rate_pct"] >= 60 and test["avg_return_pct"] >= 10
    full_hits = [
        style for style in EXIT_STYLES
        if summaries[style]["full"]["trades"] >= 30
        and summaries[style]["full"]["win_rate_pct"] >= 60
        and summaries[style]["full"]["avg_return_pct"] >= 10
    ]
    realized_full_hits = [
        style for style in EXIT_STYLES
        if summaries[style]["resolved_full"]["trades"] >= 30
        and summaries[style]["resolved_full"]["win_rate_pct"] >= 60
        and summaries[style]["resolved_full"]["avg_return_pct"] >= 10
    ]
    return {
        "version": VERSION,
        "entry_rule": ENTRY_RULE,
        "entry_trade_count": len(selected),
        "split": {"validation_start": validation_start, "test_start": test_start},
        "exit_labels": EXIT_LABELS,
        "summaries": summaries,
        "chosen_exit": chosen_style,
        "target_met_on_test": target_met,
        "full_target_hits": full_hits,
        "realized_full_target_hits": realized_full_hits,
        "unresolved_policy": "positions without a confirmed trend/trailing exit are marked to the latest available close and counted as unresolved",
        "chosen_trades": exits[chosen_style],
    }


def summary_text(value: dict[str, Any]) -> str:
    return f"{value['trades']} 筆｜勝率 {value['win_rate_pct']:.2f}%｜平均 {value['avg_return_pct']:.2f}%｜中位 {value['median_return_pct']:.2f}%"


def render_html(payload: dict[str, Any]) -> str:
    rows = "".join(
        f"<tr><td>{html.escape(payload['exit_labels'][style])}</td><td>{html.escape(summary_text(result['train']))}</td><td>{html.escape(summary_text(result['validation']))}</td><td>{html.escape(summary_text(result['test']))}</td><td>{html.escape(summary_text(result['full']))}</td><td>{html.escape(summary_text(result['resolved_full']))}</td><td>{result['full']['unresolved']}</td></tr>"
        for style, result in payload["summaries"].items()
    )
    chosen_rows = "".join(
        f"<tr><td>{row['signal_date']}</td><td>{html.escape(str(row['stock_no'])+' '+str(row['stock_name']))}</td><td>{row['return_pct']:.2f}%</td><td>{row['benchmark_return_pct']:.2f}%</td><td>{row['excess_return_pct']:.2f}%</td><td>{html.escape(row['exit_reason'])}</td><td>{'是' if row['unresolved'] else '否'}</td></tr>"
        for row in sorted(payload["chosen_trades"], key=lambda item: item["signal_date"], reverse=True)
    )
    status = "留出樣本達標" if payload["target_met_on_test"] else "留出樣本未達標"
    tone = "pass" if payload["target_met_on_test"] else "fail"
    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PB-V9 核心倉研究</title><style>
:root{{--bg:#f4f6f5;--paper:#fff;--ink:#17201d;--muted:#68736e;--line:#dce2df;--good:#08735d;--bad:#a33d31}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 system-ui,"Microsoft JhengHei",sans-serif}}header,main{{max-width:1500px;margin:auto;padding:26px 20px}}header{{border-bottom:1px solid var(--line)}}h1{{font-size:28px;letter-spacing:0;margin:0 0 7px}}h2{{font-size:19px;letter-spacing:0;margin:28px 0 10px}}p{{color:var(--muted)}}.status{{display:inline-block;padding:6px 10px;border:1px solid currentColor;font-weight:700}}.pass{{color:var(--good)}}.fail{{color:var(--bad)}}.table{{overflow:auto;background:var(--paper);border:1px solid var(--line)}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:left}}th{{font-size:12px;color:var(--muted);background:#eef1ef}}.note{{border-left:4px solid var(--bad);background:#fff8f4;padding:12px 14px}}@media(max-width:760px){{header,main{{padding:18px 10px}}h1{{font-size:23px}}}}
</style></head><body><header><h1>PB-V9 戰術倉＋核心倉</h1><p>固定 ABC 快速回檔、月線多頭、貼近 MA20 的進場，只比較出場方式是否能保留主升波段。</p><span class="status {tone}">{status}</span></header><main><p><strong>訓練＋驗證選出：</strong>{html.escape(payload['exit_labels'][payload['chosen_exit']])}</p><div class="note">未觸發趨勢出場的部位以最新收盤估值，並另外標示未實現；不能把未實現部位當成已落袋績效。完整一年含未實現達標版本：{len(payload['full_target_hits'])}；僅已出場仍達標版本：{len(payload['realized_full_target_hits'])}。</div><h2>出場方式比較</h2><div class="table"><table><thead><tr><th>出場</th><th>訓練</th><th>驗證</th><th>留出測試</th><th>完整一年</th><th>僅已出場</th><th>未實現</th></tr></thead><tbody>{rows}</tbody></table></div><h2>選定方式逐筆交易</h2><div class="table"><table><thead><tr><th>訊號日</th><th>股票</th><th>策略</th><th>同期0050</th><th>超額</th><th>出場</th><th>未實現</th></tr></thead><tbody>{chosen_rows}</tbody></table></div></main></body></html>"""


def main() -> None:
    payload = research()
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    print(json.dumps({
        "chosen_exit": payload["chosen_exit"],
        "target_met_on_test": payload["target_met_on_test"],
        "full_target_hits": payload["full_target_hits"],
        "realized_full_target_hits": payload["realized_full_target_hits"],
        "summaries": payload["summaries"],
        "html": str(OUT_HTML),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
