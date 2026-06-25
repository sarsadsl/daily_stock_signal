#!/usr/bin/env python3
"""Small predeclared wide-trailing grid on the frozen rolling climax entry."""

from __future__ import annotations

import html
import itertools
import json
from pathlib import Path
from typing import Any

from analyze_pullback_core_position import exit_result, stats
from analyze_pullback_multitimeframe_search import BENCHMARK_CSV, add_benchmark_return, enrich_trades, find_series, make_series_map
from analyze_pullback_rolling_climax import add_rolling_climax_scores, variant_rows
from run_market_backtest import Row, csv_files, read_rows


REPORT_DIR = Path("reports")
VERSION = "PB-V12.0-wide-exit-grid"
OUT_JSON = REPORT_DIR / "pullback_pb_v12_wide_exit_grid.json"
OUT_HTML = REPORT_DIR / "pullback_pb_v12_wide_exit_grid.html"
ACTIVATIONS = (0.15, 0.20, 0.25)
DRAWDOWNS = (0.12, 0.15, 0.18)


def simulate(entry: Row, rows: list[Row], entry_index: int, activation_pct: float, drawdown_pct: float) -> dict[str, Any]:
    hard_stop = entry.open * 0.93
    activation = entry.open * (1 + activation_pct)
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
            trailing = max(trailing or 0, highest * (1 - drawdown_pct), entry.open * 1.02)
    return exit_result(entry, observed, observed[-1].close, "latest_close", unresolved=True)


def rebuild(filtered: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    series = make_series_map(csv_files())
    benchmark_rows = read_rows(BENCHMARK_CSV)
    benchmark_dates = {row.date: index for index, row in enumerate(benchmark_rows)}
    output = {f"a{int(a*100)}_d{int(d*100)}": [] for a, d in itertools.product(ACTIVATIONS, DRAWDOWNS)}
    for trade in filtered:
        bundle = find_series(series, str(trade["market"]), str(trade["stock_no"]))
        if not bundle:
            continue
        rows, _, dates = bundle
        signal_index = dates.get(trade["signal_date"])
        if signal_index is None or signal_index + 1 >= len(rows):
            continue
        entry_index = signal_index + 1
        entry = rows[entry_index]
        for activation, drawdown in itertools.product(ACTIVATIONS, DRAWDOWNS):
            key = f"a{int(activation*100)}_d{int(drawdown*100)}"
            result = simulate(entry, rows, entry_index, activation, drawdown)
            row = {**trade, **result, "activation_pct": activation * 100, "drawdown_pct": drawdown * 100}
            row["pnl"] = round(row["return_pct"] / 100 * 100_000)
            add_benchmark_return(row, benchmark_rows, benchmark_dates)
            output[key].append(row)
    return output


def objective(train: dict[str, Any], validation: dict[str, Any]) -> float:
    worst_win = min(train["win_rate_pct"], validation["win_rate_pct"])
    worst_avg = min(train["avg_return_pct"], validation["avg_return_pct"])
    shortfall = max(60 - worst_win, 0) + max(10 - worst_avg, 0) * 2
    instability = abs(train["avg_return_pct"] - validation["avg_return_pct"]) * 0.7
    unresolved = (train["unresolved"] + validation["unresolved"]) * 0.5
    return worst_win * 0.4 + worst_avg * 2.4 + min(train["median_return_pct"], validation["median_return_pct"]) * 0.5 - shortfall - instability - unresolved


def run() -> dict[str, Any]:
    enriched, _ = enrich_trades()
    add_rolling_climax_scores(enriched)
    filtered = variant_rows(enriched, "avoid_score4")
    exits = rebuild(filtered)
    v8 = json.loads((REPORT_DIR / "pullback_pb_v8_multitimeframe_search.json").read_text(encoding="utf-8"))
    validation_start = v8["split"]["validation_start"]
    test_start = v8["split"]["test_start"]
    results = {}
    for key, rows in exits.items():
        segments = {
            "train": [row for row in rows if row["signal_date"] < validation_start],
            "validation": [row for row in rows if validation_start <= row["signal_date"] < test_start],
            "test": [row for row in rows if row["signal_date"] >= test_start],
            "full": rows,
            "resolved_full": [row for row in rows if not row["unresolved"]],
        }
        results[key] = {name: stats(segment) for name, segment in segments.items()}
        results[key]["score"] = objective(results[key]["train"], results[key]["validation"])
    chosen = max(results, key=lambda key: results[key]["score"])
    test = results[chosen]["test"]
    resolved = results[chosen]["resolved_full"]
    target_test = test["trades"] >= 10 and test["win_rate_pct"] >= 60 and test["avg_return_pct"] >= 10 and test["unresolved"] <= 2
    target_resolved = resolved["trades"] >= 30 and resolved["win_rate_pct"] >= 60 and resolved["avg_return_pct"] >= 10
    return {
        "version": VERSION,
        "entry": "PB-V11 avoid_score4 chosen on pre-2026 expanded data",
        "grid": {"activations_pct": [value * 100 for value in ACTIVATIONS], "drawdowns_pct": [value * 100 for value in DRAWDOWNS]},
        "split": {"validation_start": validation_start, "test_start": test_start},
        "chosen": chosen,
        "results": results,
        "target_met_on_test": target_test,
        "target_met_on_resolved_full": target_resolved,
        "chosen_trades": exits[chosen],
    }


def summary_text(value: dict[str, Any]) -> str:
    return f"{value['trades']} 筆｜勝率 {value['win_rate_pct']:.2f}%｜平均 {value['avg_return_pct']:.2f}%｜中位 {value['median_return_pct']:.2f}%｜未實現 {value['unresolved']}"


def render_html(payload: dict[str, Any]) -> str:
    rows = "".join(
        f"<tr><td>{key}</td><td>{html.escape(summary_text(value['train']))}</td><td>{html.escape(summary_text(value['validation']))}</td><td>{html.escape(summary_text(value['test']))}</td><td>{html.escape(summary_text(value['full']))}</td><td>{html.escape(summary_text(value['resolved_full']))}</td></tr>"
        for key, value in sorted(payload["results"].items())
    )
    chosen_rows = "".join(
        f"<tr><td>{row['signal_date']}</td><td>{html.escape(str(row['stock_no'])+' '+str(row['stock_name']))}</td><td>{row['return_pct']:.2f}%</td><td>{row['benchmark_return_pct']:.2f}%</td><td>{row['excess_return_pct']:.2f}%</td><td>{row['exit_reason']}</td><td>{'是' if row['unresolved'] else '否'}</td></tr>"
        for row in sorted(payload["chosen_trades"], key=lambda item: item["signal_date"], reverse=True)
    )
    status = "已出場完整一年達標" if payload["target_met_on_resolved_full"] else "已出場完整一年未達標"
    tone = "pass" if payload["target_met_on_resolved_full"] else "fail"
    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PB-V12 寬幅移動停利</title><style>
:root{{--bg:#f4f6f5;--paper:#fff;--ink:#17201d;--muted:#68736e;--line:#dce2df;--good:#08735d;--bad:#a33d31}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 system-ui,"Microsoft JhengHei",sans-serif}}header,main{{max-width:1500px;margin:auto;padding:26px 20px}}header{{border-bottom:1px solid var(--line)}}h1{{font-size:28px;letter-spacing:0;margin:0 0 7px}}h2{{font-size:19px;letter-spacing:0;margin:28px 0 10px}}p{{color:var(--muted)}}.status{{display:inline-block;padding:6px 10px;border:1px solid currentColor;font-weight:700}}.pass{{color:var(--good)}}.fail{{color:var(--bad)}}.note{{border-left:4px solid var(--good);background:#eef4f1;padding:12px 14px}}.table{{overflow:auto;background:var(--paper);border:1px solid var(--line)}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:left}}th{{font-size:12px;color:var(--muted);background:#eef1ef}}@media(max-width:760px){{header,main{{padding:18px 10px}}h1{{font-size:23px}}}}
</style></head><body><header><h1>PB-V12 寬幅移動停利</h1><p>固定 PB-V11 滾動過熱濾網，只比較 +15/+20/+25% 啟動與 12/15/18% 回撤。</p><span class="status {tone}">{status}</span></header><main><div class="note"><strong>訓練＋驗證選出：</strong>{payload['chosen']}。留出測試：{'達標' if payload['target_met_on_test'] else '未達標'}。</div><h2>九組出場比較</h2><div class="table"><table><thead><tr><th>參數</th><th>訓練</th><th>驗證</th><th>留出測試</th><th>完整一年</th><th>僅已出場</th></tr></thead><tbody>{rows}</tbody></table></div><h2>選定參數明細</h2><div class="table"><table><thead><tr><th>訊號日</th><th>股票</th><th>策略</th><th>同期0050</th><th>超額</th><th>出場</th><th>未實現</th></tr></thead><tbody>{chosen_rows}</tbody></table></div></main></body></html>"""


def main() -> None:
    payload = run()
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    print(json.dumps({
        "chosen": payload["chosen"],
        "chosen_results": payload["results"][payload["chosen"]],
        "target_met_on_test": payload["target_met_on_test"],
        "target_met_on_resolved_full": payload["target_met_on_resolved_full"],
        "html": str(OUT_HTML),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
