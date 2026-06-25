#!/usr/bin/env python3
"""Two-stage pullback exit: protect a rebound, then let confirmed runners breathe."""

from __future__ import annotations

import html
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from analyze_pullback_core_position import exit_result, stats
from analyze_pullback_multitimeframe_search import BENCHMARK_CSV, add_benchmark_return, date_split, enrich_trades
from analyze_pullback_pb_v15_all_signal_history import (
    attach_prior_only_scores,
    enrich_all_three_year_signals,
    trade_key,
)
from analyze_pullback_pb_v16_daily_ranking import buy_and_hold, enriched_stats
from analyze_pullback_rolling_climax import variant_rows
from analyze_pullback_technical_phenotypes import find_series, make_series_map
from run_market_backtest import Row, csv_files, read_rows


REPORT_DIR = Path("reports")
OUT_JSON = REPORT_DIR / "pullback_pb_v17_two_stage_runner.json"
OUT_HTML = REPORT_DIR / "pullback_pb_v17_two_stage_runner.html"
VERSION = "PB-V17.0-two-stage-runner"
PROTECT_TRIGGER_PCT = 0.12
RUNNER_TRIGGER_PCT = 0.15
RUNNER_DRAWDOWN_PCT = 0.18
PROFIT_FLOOR_PCT = 0.02
HARD_STOP_PCT = 0.07


def simulate_two_stage(entry: Row, rows: list[Row], entry_index: int) -> dict[str, Any]:
    hard_stop = entry.open * (1 - HARD_STOP_PCT)
    protect_trigger = entry.open * (1 + PROTECT_TRIGGER_PCT)
    runner_trigger = entry.open * (1 + RUNNER_TRIGGER_PCT)
    profit_floor = entry.open * (1 + PROFIT_FLOOR_PCT)
    highest = entry.open
    active_stop = hard_stop
    runner_active = False
    observed: list[Row] = []
    for row in rows[entry_index:]:
        observed.append(row)
        if row.open <= active_stop:
            reason = "gap_runner_stop" if runner_active else (
                "gap_rebound_floor" if active_stop > hard_stop else "gap_hard_stop"
            )
            return exit_result(entry, observed, row.open, reason)
        if row.low <= active_stop:
            reason = "runner_trailing_stop" if runner_active else (
                "rebound_profit_floor" if active_stop > hard_stop else "hard_stop"
            )
            return exit_result(entry, observed, active_stop, reason)
        highest = max(highest, row.high)
        if highest >= protect_trigger:
            active_stop = max(active_stop, profit_floor)
        if highest >= runner_trigger:
            runner_active = True
            active_stop = max(active_stop, highest * (1 - RUNNER_DRAWDOWN_PCT), profit_floor)
    return exit_result(entry, observed, observed[-1].close, "latest_close", unresolved=True)


def replay(
    selected: list[dict[str, Any]],
    series: dict[tuple[str, str], tuple[Any, Any, Any]],
    benchmark_path: Path | None = None,
) -> list[dict[str, Any]]:
    benchmark_rows = read_rows(benchmark_path) if benchmark_path and benchmark_path.exists() else []
    benchmark_dates = {row.date: index for index, row in enumerate(benchmark_rows)}
    output: list[dict[str, Any]] = []
    for signal in selected:
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
        result = {
            **signal,
            **simulate_two_stage(entry, rows, entry_index),
            "entry_date": entry.date,
            "entry_price": round(entry.open, 4),
        }
        result["pnl"] = round(result["return_pct"] / 100 * 100_000)
        if benchmark_rows:
            add_benchmark_return(result, benchmark_rows, benchmark_dates)
        output.append(result)
    return output


def signal_rank(row: dict[str, Any]) -> tuple[Any, ...]:
    return (row["score"], -row["climax_score"], row["monthly_momentum3_pct"] or -999)


def select_daily_top2_no_duplicate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["signal_date"]].append(row)
    selected: list[dict[str, Any]] = []
    for signal_date in sorted(grouped):
        candidates = sorted(grouped[signal_date], key=signal_rank, reverse=True)
        picked = 0
        for candidate in candidates:
            already_active = any(
                prior["stock_no"] == candidate["stock_no"]
                and prior["entry_date"] <= candidate["entry_date"] <= prior["exit_date"]
                for prior in selected
            )
            if already_active:
                continue
            selected.append({**candidate, "daily_rank": picked + 1})
            picked += 1
            if picked == 2:
                break
    return selected


def portfolio_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "max_concurrent_positions": 0,
            "required_capital": 0,
            "total_pnl": 0,
            "capital_return_pct": 0.0,
            "benchmark_buy_hold": buy_and_hold([]),
            "beats_buy_hold": False,
        }
    dates = sorted({row["entry_date"] for row in rows} | {row["exit_date"] for row in rows})
    max_concurrent = max(
        sum(row["entry_date"] <= date <= row["exit_date"] for row in rows)
        for date in dates
    )
    required_capital = max_concurrent * 100_000
    total_pnl = round(sum(float(row["return_pct"]) / 100 * 100_000 for row in rows))
    capital_return = round(total_pnl / required_capital * 100, 2) if required_capital else 0.0
    hold = buy_and_hold(rows)
    return {
        "max_concurrent_positions": max_concurrent,
        "required_capital": required_capital,
        "total_pnl": total_pnl,
        "capital_return_pct": capital_return,
        "benchmark_buy_hold": hold,
        "beats_buy_hold": capital_return > hold["return_pct"],
    }


def sliced(rows: list[dict[str, Any]], validation_start: str, test_start: str) -> dict[str, Any]:
    groups = {
        "train": [row for row in rows if row["signal_date"] < validation_start],
        "validation": [row for row in rows if validation_start <= row["signal_date"] < test_start],
        "test": [row for row in rows if row["signal_date"] >= test_start],
        "full": rows,
        "resolved_full": [row for row in rows if not row["unresolved"]],
        "resolved_test": [row for row in rows if row["signal_date"] >= test_start and not row["unresolved"]],
    }
    return {name: enriched_stats(value) for name, value in groups.items()}


def run() -> dict[str, Any]:
    historical, research_series = enrich_all_three_year_signals()
    one_year, _ = enrich_trades()
    attach_prior_only_scores(one_year, historical)
    selected_one_year = variant_rows(one_year, "avoid_score4")
    one_year_rows = replay(selected_one_year, make_series_map(csv_files()), BENCHMARK_CSV)
    portfolio_rows = select_daily_top2_no_duplicate(one_year_rows)
    validation_start, test_start = date_split(one_year)

    selected_three_year = variant_rows(historical, "avoid_score4")
    three_year_rows = replay(selected_three_year, research_series)
    years = sorted({row["signal_date"][:4] for row in three_year_rows})
    by_year = {
        year: stats([row for row in three_year_rows if row["signal_date"].startswith(year) and not row["unresolved"]])
        for year in years
    }
    portfolio_resolved = [row for row in portfolio_rows if not row["unresolved"]]
    portfolio_stats = enriched_stats(portfolio_resolved)
    portfolio = portfolio_metrics(portfolio_resolved)
    return {
        "version": VERSION,
        "methodology": {
            "entry": "PB-V15 corrected all-signal rolling history, ABC/monthly/MA20 base, climax score below 4, next-open discount 2%",
            "exit": "-7% hard stop; after +12% high protect +2%; after +15% high trail 18% from peak with +2% floor",
            "intraday": "existing stop is checked before the current daily high updates it",
            "portfolio": "daily top 2 by original signal score, then lower climax score and higher monthly momentum; skip a stock while its prior position is active",
            "capital": "TWD 100,000 per position; required capital equals maximum concurrent positions",
            "caveat": "the two-stage rule was formed after inspecting PB-V15 exit disagreements",
        },
        "split": {"validation_start": validation_start, "test_start": test_start},
        "all_entries": sliced(one_year_rows, validation_start, test_start),
        "portfolio": sliced(portfolio_rows, validation_start, test_start),
        "portfolio_metrics_resolved": portfolio,
        "portfolio_target_met": (
            portfolio_stats["trades"] >= 20
            and portfolio_stats["win_rate_pct"] >= 60
            and portfolio_stats["avg_return_pct"] >= 10
            and portfolio["beats_buy_hold"]
        ),
        "three_year_by_year": by_year,
        "exit_reasons": dict(Counter(row["exit_reason"] for row in one_year_rows)),
        "portfolio_trades": portfolio_rows,
    }


def compact(value: dict[str, Any]) -> str:
    return (
        f"{value['trades']} 筆｜勝率 {value['win_rate_pct']:.2f}%｜平均 {value['avg_return_pct']:.2f}%｜"
        f"0050同期 {value['benchmark_avg_return_pct']:.2f}%｜超額 {value['avg_excess_return_pct']:.2f}%｜"
        f"未實現 {value['unresolved']}"
    )


def render_html(payload: dict[str, Any]) -> str:
    portfolio = payload["portfolio"]
    metrics = payload["portfolio_metrics_resolved"]
    period_labels = {"train": "訓練", "validation": "驗證", "test": "最後20%", "full": "完整一年", "resolved_full": "完整一年已出場"}
    period_rows = "".join(
        f"<tr><th>{label}</th><td>{html.escape(compact(payload['all_entries'][key]))}</td>"
        f"<td>{html.escape(compact(portfolio[key]))}</td></tr>"
        for key, label in period_labels.items()
    )
    year_rows = "".join(
        f"<tr><th>{year}</th><td>{html.escape(compact(value))}</td></tr>"
        for year, value in payload["three_year_by_year"].items()
    )
    trade_rows = "".join(
        f"<tr><td>{row['signal_date']}</td><td>{row['daily_rank']}</td>"
        f"<td>{html.escape(str(row['stock_no']) + ' ' + str(row['stock_name']))}</td>"
        f"<td>{row['score']}</td><td>{row['climax_score']}</td>"
        f"<td class={'pos' if row['return_pct'] > 0 else 'neg'}>{row['return_pct']:.2f}%</td>"
        f"<td>{row['benchmark_return_pct'] if row['benchmark_return_pct'] is not None else '-'}%</td>"
        f"<td>{row['holding_days']}</td><td>{html.escape(row['exit_reason'])}</td>"
        f"<td>{'是' if row['unresolved'] else '否'}</td></tr>"
        for row in sorted(payload["portfolio_trades"], key=lambda item: item["signal_date"], reverse=True)
    )
    resolved = portfolio["resolved_full"]
    test = portfolio["test"]
    hold = metrics["benchmark_buy_hold"]
    passed = payload["portfolio_target_met"]
    status = "一年數字與有限本金報酬均超過0050" if passed else "尚未同時通過交易與指數門檻"
    tone = "pass" if passed else "fail"
    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PB-V17 兩段式波段出場</title><style>
:root{{--bg:#f4f6f5;--paper:#fff;--ink:#18211e;--muted:#68736f;--line:#dbe2de;--good:#08735d;--bad:#a13e34;--accent:#245b78}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 system-ui,"Microsoft JhengHei",sans-serif}}header,main{{max-width:1500px;margin:auto;padding:26px 20px}}header{{border-bottom:1px solid var(--line)}}h1{{margin:0 0 6px;font-size:28px;letter-spacing:0}}h2{{margin:30px 0 10px;font-size:19px;letter-spacing:0}}p{{margin:6px 0;color:var(--muted)}}.status{{display:inline-block;margin-top:12px;padding:7px 11px;border:1px solid currentColor;font-weight:750}}.pass,.pos{{color:var(--good)}}.fail,.neg{{color:var(--bad)}}.metrics{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1px;margin-top:24px;background:var(--line);border:1px solid var(--line)}}.metric{{background:var(--paper);padding:16px}}.metric strong{{display:block;font-size:20px}}.note{{margin-top:18px;border-left:4px solid var(--accent);background:#edf3f5;padding:13px 15px}}.table{{overflow:auto;border:1px solid var(--line);background:var(--paper)}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:left}}thead th{{font-size:12px;color:var(--muted);background:#eef1ef}}tbody th{{font-weight:650}}@media(max-width:900px){{.metrics{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}@media(max-width:560px){{header,main{{padding:18px 10px}}h1{{font-size:23px}}.metrics{{grid-template-columns:1fr}}}}
</style></head><body><header><h1>PB-V17 兩段式波段出場</h1><p>反彈到 +12% 先保住 +2%；確認 +15% 後，才進入 18% 寬幅移動停利。</p><span class="status {tone}">{status}</span><div class="metrics"><div class="metric"><span>每日前2，完整一年已出場</span><strong>{resolved['win_rate_pct']:.2f}% / {resolved['avg_return_pct']:.2f}%</strong><small>{resolved['trades']} 筆，勝率 / 平均報酬</small></div><div class="metric"><span>最後20%</span><strong>{test['win_rate_pct']:.2f}% / {test['avg_return_pct']:.2f}%</strong><small>{test['trades']} 筆，未實現 {test['unresolved']}</small></div><div class="metric"><span>所需本金報酬</span><strong>{metrics['capital_return_pct']:.2f}%</strong><small>最多 {metrics['max_concurrent_positions']} 檔，約 {metrics['required_capital']:,} 元</small></div><div class="metric"><span>同期0050買進持有</span><strong>{hold['return_pct']:.2f}%</strong><small>{hold['entry_date']} 至 {hold['exit_date']}</small></div></div></header><main><div class="note"><strong>判讀：</strong>本金報酬以每檔 10 萬、最大同時持倉所需資金計算，並禁止同一股票在舊部位未結束前重複進場。這是目前最接近真實執行的比較；但兩段式規則來自已觀察過的失敗案例，最後20%只能當稽核，不能再稱為純留出。</div><h2>全部訊號與有限持倉</h2><div class="table"><table><thead><tr><th>區間</th><th>全部合格訊號</th><th>每日前2且不重複持股</th></tr></thead><tbody>{period_rows}</tbody></table></div><h2>三年逐年壓力測試</h2><div class="table"><table><thead><tr><th>年度</th><th>兩段式全部合格訊號</th></tr></thead><tbody>{year_rows}</tbody></table></div><h2>組合交易明細</h2><div class="table"><table><thead><tr><th>訊號日</th><th>日排名</th><th>股票</th><th>原分數</th><th>過熱分</th><th>策略</th><th>同期0050</th><th>持有日</th><th>出場</th><th>未實現</th></tr></thead><tbody>{trade_rows}</tbody></table></div></main></body></html>"""


def main() -> None:
    payload = run()
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    print(json.dumps({
        "all_entries_resolved": payload["all_entries"]["resolved_full"],
        "portfolio_train": payload["portfolio"]["train"],
        "portfolio_validation": payload["portfolio"]["validation"],
        "portfolio_test": payload["portfolio"]["test"],
        "portfolio_resolved": payload["portfolio"]["resolved_full"],
        "portfolio_metrics_resolved": payload["portfolio_metrics_resolved"],
        "portfolio_target_met": payload["portfolio_target_met"],
        "three_year_by_year": payload["three_year_by_year"],
        "exit_reasons": payload["exit_reasons"],
        "html": str(OUT_HTML),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
