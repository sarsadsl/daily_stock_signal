#!/usr/bin/env python3
"""Daily qualitative ranking on the corrected PB-V15 candidate set."""

from __future__ import annotations

import html
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

from analyze_pullback_core_position import stats
from analyze_pullback_multitimeframe_search import BENCHMARK_CSV
from run_market_backtest import read_rows


REPORT_DIR = Path("reports")
SOURCE_JSON = REPORT_DIR / "pullback_pb_v15_all_signal_history.json"
OUT_JSON = REPORT_DIR / "pullback_pb_v16_daily_ranking.json"
OUT_HTML = REPORT_DIR / "pullback_pb_v16_daily_ranking.html"
VERSION = "PB-V16.0-daily-ranking"

RANKERS: dict[str, Callable[[dict[str, Any]], tuple[Any, ...]]] = {
    "signal_score": lambda row: (row["score"], -row["climax_score"], row["monthly_momentum3_pct"] or -999),
    "low_climax": lambda row: (-row["climax_score"], row["score"], row["monthly_momentum3_pct"] or -999),
    "monthly_strength": lambda row: (row["monthly_momentum3_pct"] or -999, row["score"]),
    "fresh_peak": lambda row: (-row["peak_age_days"], row["close_location"], row["score"]),
    "fib382": lambda row: (-abs(row["bc_retrace_pct"] - 38.2), row["score"]),
    "controlled_rs": lambda row: (-row["close_vs_ma60_pct"], row["monthly_momentum3_pct"] or -999, row["score"]),
    "active_volume": lambda row: (row["last5_volume_ratio"], row["c_vs_ab_volume"], row["score"]),
}
TOP_NS = (1, 2, 3, 5)
QUALITATIVE_CANDIDATE = "controlled_rs_top5"


def rank_daily(
    rows: list[dict[str, Any]],
    ranker: Callable[[dict[str, Any]], tuple[Any, ...]],
    top_n: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["signal_date"]].append(row)
    output: list[dict[str, Any]] = []
    for signal_date in sorted(grouped):
        ranked = sorted(grouped[signal_date], key=ranker, reverse=True)
        for position, row in enumerate(ranked[:top_n], start=1):
            output.append({**row, "daily_rank": position})
    return output


def enriched_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result = stats(rows)
    benchmark_pnl = round(sum(float(row.get("benchmark_return_pct") or 0) / 100 * 100_000 for row in rows))
    result["benchmark_total_pnl"] = benchmark_pnl
    result["strategy_minus_benchmark_pnl"] = result["total_pnl"] - benchmark_pnl
    return result


def segments(
    rows: list[dict[str, Any]], validation_start: str, test_start: str
) -> dict[str, Any]:
    slices = {
        "train": [row for row in rows if row["signal_date"] < validation_start],
        "validation": [row for row in rows if validation_start <= row["signal_date"] < test_start],
        "train_validation": [row for row in rows if row["signal_date"] < test_start],
        "test": [row for row in rows if row["signal_date"] >= test_start],
        "full": rows,
        "resolved_full": [row for row in rows if not row["unresolved"]],
        "resolved_test": [row for row in rows if row["signal_date"] >= test_start and not row["unresolved"]],
    }
    return {name: enriched_stats(value) for name, value in slices.items()}


def selection_score(result: dict[str, Any]) -> float:
    train = result["train"]
    validation = result["validation"]
    train_validation = result["train_validation"]
    if train_validation["trades"] < 25 or validation["trades"] < 5:
        return -1_000_000.0
    worst_win = min(train["win_rate_pct"], validation["win_rate_pct"])
    worst_avg = min(train["avg_return_pct"], validation["avg_return_pct"])
    return worst_win + worst_avg * 0.8 + train_validation["trades"] * 0.1


def buy_and_hold(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"entry_date": None, "exit_date": None, "return_pct": 0.0}
    benchmark = read_rows(BENCHMARK_CSV)
    dates = {row.date: row for row in benchmark}
    entry_date = min(row["entry_date"] for row in rows)
    exit_date = max(row["exit_date"] for row in rows)
    entry = dates.get(entry_date)
    exit_row = dates.get(exit_date)
    return {
        "entry_date": entry_date,
        "exit_date": exit_date,
        "return_pct": round((exit_row.close / entry.open - 1) * 100, 2) if entry and exit_row else 0.0,
    }


def run() -> dict[str, Any]:
    source = json.loads(SOURCE_JSON.read_text(encoding="utf-8"))
    rows = source["one_year_trades"]
    validation_start = source["one_year_split"]["validation_start"]
    test_start = source["one_year_split"]["test_start"]
    candidates: dict[str, Any] = {}
    ranked_rows: dict[str, list[dict[str, Any]]] = {}
    for name, ranker in RANKERS.items():
        for top_n in TOP_NS:
            key = f"{name}_top{top_n}"
            selected = rank_daily(rows, ranker, top_n)
            ranked_rows[key] = selected
            candidates[key] = segments(selected, validation_start, test_start)
            candidates[key]["selection_score"] = round(selection_score(candidates[key]), 4)
    chosen_pretest = max(candidates, key=lambda key: candidates[key]["selection_score"])
    qualitative = candidates[QUALITATIVE_CANDIDATE]
    qualitative_resolved = qualitative["resolved_full"]
    pretest_resolved = candidates[chosen_pretest]["resolved_full"]
    target_hits = [
        key
        for key, value in candidates.items()
        if value["resolved_full"]["trades"] >= 30
        and value["resolved_full"]["win_rate_pct"] >= 60
        and value["resolved_full"]["avg_return_pct"] >= 10
    ]
    return {
        "version": VERSION,
        "methodology": {
            "source": "PB-V15 corrected all-signal-history entries and frozen +15%/18% wide exit",
            "daily_capacity": "at most N entries per signal date; each trade uses TWD 100,000",
            "pretest_selection": "ranker and N selected from train and validation only using worst-segment win/average plus sample size",
            "qualitative_candidate": "daily top 5 by lower MA60 extension, then higher completed-month momentum, then higher original signal score",
            "caveat": "the qualitative candidate was identified after prior analyses and its final slice has already been observed",
        },
        "split": {"validation_start": validation_start, "test_start": test_start},
        "chosen_pretest": chosen_pretest,
        "qualitative_candidate": QUALITATIVE_CANDIDATE,
        "candidates": candidates,
        "target_hits_on_resolved_full": target_hits,
        "pretest_target_met": pretest_resolved["win_rate_pct"] >= 60 and pretest_resolved["avg_return_pct"] >= 10,
        "qualitative_target_met": qualitative_resolved["win_rate_pct"] >= 60 and qualitative_resolved["avg_return_pct"] >= 10,
        "qualitative_trades": ranked_rows[QUALITATIVE_CANDIDATE],
        "qualitative_0050_buy_hold": buy_and_hold(ranked_rows[QUALITATIVE_CANDIDATE]),
    }


def compact(value: dict[str, Any]) -> str:
    return (
        f"{value['trades']} 筆｜勝率 {value['win_rate_pct']:.2f}%｜平均 {value['avg_return_pct']:.2f}%｜"
        f"0050同期 {value['benchmark_avg_return_pct']:.2f}%｜超額 {value['avg_excess_return_pct']:.2f}%｜"
        f"未實現 {value['unresolved']}"
    )


def render_html(payload: dict[str, Any]) -> str:
    selected_keys = sorted(
        payload["candidates"],
        key=lambda key: payload["candidates"][key]["selection_score"],
        reverse=True,
    )
    candidate_rows = "".join(
        f"<tr class={'focus' if key == payload['qualitative_candidate'] else ''}><th>{key}</th>"
        f"<td>{html.escape(compact(payload['candidates'][key]['train']))}</td>"
        f"<td>{html.escape(compact(payload['candidates'][key]['validation']))}</td>"
        f"<td>{html.escape(compact(payload['candidates'][key]['test']))}</td>"
        f"<td>{html.escape(compact(payload['candidates'][key]['resolved_full']))}</td></tr>"
        for key in selected_keys
    )
    qualitative = payload["candidates"][payload["qualitative_candidate"]]
    pretest = payload["candidates"][payload["chosen_pretest"]]
    trade_rows = "".join(
        f"<tr><td>{row['signal_date']}</td><td>{row['daily_rank']}</td>"
        f"<td>{html.escape(str(row['stock_no']) + ' ' + str(row['stock_name']))}</td>"
        f"<td>{row['close_vs_ma60_pct']:.2f}%</td><td>{row['monthly_momentum3_pct']:.2f}%</td>"
        f"<td>{row['score']}</td><td class={'pos' if row['return_pct'] > 0 else 'neg'}>{row['return_pct']:.2f}%</td>"
        f"<td>{row['benchmark_return_pct'] if row['benchmark_return_pct'] is not None else '-'}%</td>"
        f"<td>{html.escape(row['exit_reason'])}</td><td>{'是' if row['unresolved'] else '否'}</td></tr>"
        for row in sorted(payload["qualitative_trades"], key=lambda item: item["signal_date"], reverse=True)
    )
    resolved = qualitative["resolved_full"]
    test = qualitative["test"]
    status = "完整一年數字達標，但尚未通過獨立留出" if payload["qualitative_target_met"] else "完整一年仍未達標"
    tone = "pass" if payload["qualitative_target_met"] else "fail"
    hold = payload["qualitative_0050_buy_hold"]
    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PB-V16 每日質化排序</title><style>
:root{{--bg:#f4f6f5;--paper:#fff;--ink:#18211e;--muted:#68736f;--line:#dbe2de;--good:#08735d;--bad:#a13e34;--accent:#245b78;--focus:#eef4f1}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 system-ui,"Microsoft JhengHei",sans-serif}}header,main{{max-width:1540px;margin:auto;padding:26px 20px}}header{{border-bottom:1px solid var(--line)}}h1{{margin:0 0 6px;font-size:28px;letter-spacing:0}}h2{{margin:30px 0 10px;font-size:19px;letter-spacing:0}}p{{margin:6px 0;color:var(--muted)}}.status{{display:inline-block;margin-top:12px;padding:7px 11px;border:1px solid currentColor;font-weight:750}}.pass,.pos{{color:var(--good)}}.fail,.neg{{color:var(--bad)}}.metrics{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1px;margin-top:24px;background:var(--line);border:1px solid var(--line)}}.metric{{background:var(--paper);padding:16px}}.metric strong{{display:block;font-size:20px}}.note{{margin-top:18px;border-left:4px solid var(--accent);background:#edf3f5;padding:13px 15px}}.table{{overflow:auto;border:1px solid var(--line);background:var(--paper)}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:left}}thead th{{font-size:12px;color:var(--muted);background:#eef1ef}}tbody th{{font-weight:650}}tr.focus th,tr.focus td{{background:var(--focus)}}@media(max-width:760px){{header,main{{padding:18px 10px}}h1{{font-size:23px}}.metrics{{grid-template-columns:1fr}}}}
</style></head><body><header><h1>PB-V16 每日質化排序</h1><p>同一天最多買 5 檔：先選乖離可控，再選月線較強，最後看原訊號分數。</p><span class="status {tone}">{status}</span><div class="metrics"><div class="metric"><span>質化候選，完整一年已出場</span><strong>{resolved['win_rate_pct']:.2f}% / {resolved['avg_return_pct']:.2f}%</strong><small>{resolved['trades']} 筆，勝率 / 平均報酬</small></div><div class="metric"><span>質化候選，最後20%</span><strong>{test['win_rate_pct']:.2f}% / {test['avg_return_pct']:.2f}%</strong><small>{test['trades']} 筆，含 {test['unresolved']} 筆未出場</small></div><div class="metric"><span>同期0050買進持有</span><strong>{hold['return_pct']:.2f}%</strong><small>{hold['entry_date']} 至 {hold['exit_date']}</small></div></div></header><main><div class="note"><strong>誠實邊界：</strong>完整一年已達 60%／10%，且同持有期間平均超額為 {resolved['avg_excess_return_pct']:.2f}%；但最後區間平均仍低於 10%，而且這個質化排序是在先前分析後形成，尚不能視為獨立驗證。訓練＋驗證客觀選出的版本是 <strong>{payload['chosen_pretest']}</strong>，其完整一年已出場為 {html.escape(compact(pretest['resolved_full']))}。</div><h2>候選排序比較</h2><div class="table"><table><thead><tr><th>排名規則</th><th>訓練</th><th>驗證</th><th>最後20%</th><th>完整一年已出場</th></tr></thead><tbody>{candidate_rows}</tbody></table></div><h2>質化候選交易明細</h2><div class="table"><table><thead><tr><th>訊號日</th><th>日排名</th><th>股票</th><th>MA60乖離</th><th>月動能</th><th>原分數</th><th>策略</th><th>同期0050</th><th>出場</th><th>未實現</th></tr></thead><tbody>{trade_rows}</tbody></table></div></main></body></html>"""


def main() -> None:
    payload = run()
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    print(json.dumps({
        "chosen_pretest": payload["chosen_pretest"],
        "pretest_resolved_full": payload["candidates"][payload["chosen_pretest"]]["resolved_full"],
        "qualitative_candidate": payload["qualitative_candidate"],
        "qualitative_train": payload["candidates"][payload["qualitative_candidate"]]["train"],
        "qualitative_validation": payload["candidates"][payload["qualitative_candidate"]]["validation"],
        "qualitative_test": payload["candidates"][payload["qualitative_candidate"]]["test"],
        "qualitative_resolved_full": payload["candidates"][payload["qualitative_candidate"]]["resolved_full"],
        "qualitative_0050_buy_hold": payload["qualitative_0050_buy_hold"],
        "target_hits": payload["target_hits_on_resolved_full"],
        "html": str(OUT_HTML),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
