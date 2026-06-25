#!/usr/bin/env python3
"""Rerun prior pullback reports under a standard TWD 100k unit per trade."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from analyze_pullback_core_position import stats
from analyze_pullback_multitimeframe_search import BENCHMARK_CSV, date_split, enrich_trades
from analyze_pullback_pb_v15_all_signal_history import (
    attach_prior_only_scores,
    enrich_all_three_year_signals,
)
from analyze_pullback_pb_v17_two_stage_runner import replay
from analyze_pullback_pb_v18_finite_capital import (
    STRESS_SLIPPAGE_EACH_SIDE_PCT,
    adjusted_rows,
)
from analyze_pullback_rolling_climax import variant_rows
from analyze_pullback_technical_phenotypes import make_series_map
from run_market_backtest import csv_files


REPORT_DIR = Path("reports")
OUT_JSON = REPORT_DIR / "pullback_standard_unit_rerun.json"
OUT_HTML = REPORT_DIR / "pullback_standard_unit_rerun.html"
POSITION_SIZE = 100_000


def load_report(name: str) -> dict[str, Any]:
    return json.loads((REPORT_DIR / name).read_text(encoding="utf-8"))


def money_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary = stats(rows)
    summary["standard_position_size"] = POSITION_SIZE
    summary["total_standard_notional"] = summary["trades"] * POSITION_SIZE
    summary["total_pnl"] = round(sum(float(row.get("pnl", 0)) for row in rows))
    return summary


def stat_with_money(summary: dict[str, Any]) -> dict[str, Any]:
    out = dict(summary)
    out["standard_position_size"] = POSITION_SIZE
    out["total_standard_notional"] = int(out.get("trades", 0)) * POSITION_SIZE
    if "total_pnl" not in out:
        out["total_pnl"] = round(float(out.get("avg_return_pct", 0)) / 100 * out["total_standard_notional"])
    return out


def compact(summary: dict[str, Any]) -> str:
    return (
        f"{summary.get('trades', 0)} 筆｜勝率 {summary.get('win_rate_pct', 0):.2f}%｜"
        f"平均 {summary.get('avg_return_pct', 0):.2f}%｜中位 {summary.get('median_return_pct', 0):.2f}%｜"
        f"損益 {summary.get('total_pnl', 0):,.0f}"
    )


def rebuild_v17_all_entries() -> dict[str, Any]:
    historical, _ = enrich_all_three_year_signals()
    one_year, _ = enrich_trades()
    attach_prior_only_scores(one_year, historical)
    candidates = variant_rows(one_year, "avoid_score4")
    exits = replay(candidates, make_series_map(csv_files()), BENCHMARK_CSV)
    validation_start, test_start = date_split(one_year)
    groups = {
        "train": [row for row in exits if row["signal_date"] < validation_start],
        "validation": [
            row for row in exits if validation_start <= row["signal_date"] < test_start
        ],
        "test": [row for row in exits if row["signal_date"] >= test_start],
        "full": exits,
        "resolved_full": [row for row in exits if not row["unresolved"]],
        "resolved_test": [
            row for row in exits if row["signal_date"] >= test_start and not row["unresolved"]
        ],
    }
    return {
        "split": {"validation_start": validation_start, "test_start": test_start},
        "gross_periods": {name: money_summary(rows) for name, rows in groups.items()},
        "cost_periods": {
            name: money_summary(adjusted_rows(rows, 0.0)) for name, rows in groups.items()
        },
        "stress_periods": {
            name: money_summary(adjusted_rows(rows, STRESS_SLIPPAGE_EACH_SIDE_PCT))
            for name, rows in groups.items()
        },
        "trades": exits,
        "cost_trades": adjusted_rows(exits, 0.0),
        "stress_trades": adjusted_rows(exits, STRESS_SLIPPAGE_EACH_SIDE_PCT),
    }


def collect_rows() -> dict[str, Any]:
    v4 = load_report("pullback_pb_v4_0_1y_discount2_swing.json")
    v5 = load_report("pullback_pb_v5_0_strong_filter_holdout.json")
    v8 = load_report("pullback_pb_v8_multitimeframe_search.json")
    v9 = load_report("pullback_pb_v9_core_position.json")
    v10 = load_report("pullback_pb_v10_joint_search.json")
    v14 = load_report("pullback_pb_v14_market_gate.json")
    v15 = load_report("pullback_pb_v15_all_signal_history.json")
    v17 = load_report("pullback_pb_v17_two_stage_runner.json")
    rebuilt = rebuild_v17_all_entries()

    rows = [
        {
            "version": "PB-V4",
            "name": "隔天開低 2% + swing 出場",
            "basis": "既有報表 swing_summary",
            "sample": "一年全訊號",
            "summary": stat_with_money(v4["swing_summary"]),
            "note": "這是目前你認為最有參考性的基準。",
        },
        {
            "version": "PB-V5 control",
            "name": "強勢濾網測試的未加濾網對照",
            "basis": "既有報表 control/full",
            "sample": "一年全訊號",
            "summary": stat_with_money(v5["results"]["control"]["all"]),
            "note": "濾網版本交易數太少，主比較保留對照組。",
        },
        {
            "version": "PB-V8",
            "name": "多週期搜尋選定版本",
            "basis": "既有報表 chosen/full",
            "sample": "一年全訊號",
            "summary": stat_with_money(v8["chosen"]["summaries"]["full"]),
            "note": "用當時選定規則，不加入本金限制。",
        },
        {
            "version": "PB-V9",
            "name": "核心倉位出場選定版本",
            "basis": "既有報表 chosen_exit/full",
            "sample": "一年全訊號",
            "summary": stat_with_money(v9["summaries"][v9["chosen_exit"]]["full"]),
            "note": f"選定出場：{v9['chosen_exit']}。",
        },
        {
            "version": "PB-V10",
            "name": "進出場聯合搜尋選定版本",
            "basis": "既有報表 chosen/full",
            "sample": "一年全訊號",
            "summary": stat_with_money(v10["chosen"]["summaries"]["full"]),
            "note": "屬於搜尋後版本，需留意過度擬合。",
        },
        {
            "version": "PB-V14",
            "name": "V14 大盤閘門：全部市場",
            "basis": "既有報表 all_market/full/wide_resolved",
            "sample": "三年全訊號已出場",
            "summary": stat_with_money(
                v14["regimes"]["all_market"]["full"]["wide_resolved"]
            ),
            "note": "不加 0050 閘門。",
        },
        {
            "version": "PB-V14 gate",
            "name": "V14 大盤閘門：0050 多頭",
            "basis": "既有報表 primary_uptrend/full/wide_resolved",
            "sample": "三年全訊號已出場",
            "summary": stat_with_money(
                v14["regimes"]["primary_uptrend"]["full"]["wide_resolved"]
            ),
            "note": f"保留 {v14['retention_pct']:.2f}% 訊號。",
        },
        {
            "version": "PB-V15",
            "name": "全歷史訊號修正後的一年版本",
            "basis": "既有報表 one_year/full/wide_resolved",
            "sample": "一年全訊號已出場",
            "summary": stat_with_money(
                v15["one_year_periods"]["full"]["wide_resolved"]
            ),
            "note": "修正 rolling score 只看過去已出現訊號。",
        },
        {
            "version": "PB-V15 3Y",
            "name": "全歷史訊號修正後的三年版本",
            "basis": "既有報表 three_year/full/wide_resolved",
            "sample": "三年全訊號已出場",
            "summary": stat_with_money(
                v15["three_year_periods"]["full"]["wide_resolved"]
            ),
            "note": "三年壓力測試口徑。",
        },
        {
            "version": "PB-V17",
            "name": "兩段式出場，全部合格訊號",
            "basis": "既有報表 all_entries/resolved_full",
            "sample": "一年全訊號已出場",
            "summary": stat_with_money(v17["all_entries"]["resolved_full"]),
            "note": "不用每日前 2、不跳過重複持股、不限本金。",
        },
        {
            "version": "PB-V17 rerun",
            "name": "兩段式出場，重新計算全部訊號",
            "basis": "本次由原始訊號重跑",
            "sample": "一年全訊號已出場",
            "summary": rebuilt["gross_periods"]["resolved_full"],
            "note": "用來確認既有 JSON 沒有被有限本金邏輯污染。",
        },
        {
            "version": "PB-V18 cost",
            "name": "V17 全訊號 + 成本",
            "basis": "本次重跑，套 V18 手續費/稅",
            "sample": "一年全訊號已出場",
            "summary": rebuilt["cost_periods"]["resolved_full"],
            "note": "不是 V18 有限本金版，是把 V18 成本邏輯套到全訊號。",
        },
        {
            "version": "PB-V18 stress",
            "name": "V17 全訊號 + 成本 + 雙邊滑價",
            "basis": "本次重跑，套 V18 壓力成本",
            "sample": "一年全訊號已出場",
            "summary": rebuilt["stress_periods"]["resolved_full"],
            "note": f"買賣各加 {STRESS_SLIPPAGE_EACH_SIDE_PCT:.2f}% 不利滑價。",
        },
    ]
    return {
        "position_size": POSITION_SIZE,
        "rules": {
            "capital_limit": None,
            "daily_position_limit": None,
            "duplicate_active_stock_filter": False,
            "ranking_queue": False,
            "entry_unit": "Every qualifying trade is counted as one TWD 100,000 unit.",
        },
        "split": rebuilt["split"],
        "comparison": rows,
        "rebuilt_v17_periods": rebuilt["gross_periods"],
        "rebuilt_v18_cost_periods": rebuilt["cost_periods"],
        "rebuilt_v18_stress_periods": rebuilt["stress_periods"],
    }


def row_html(row: dict[str, Any]) -> str:
    summary = row["summary"]
    return (
        "<tr>"
        f"<th>{html.escape(row['version'])}</th>"
        f"<td>{html.escape(row['name'])}</td>"
        f"<td>{html.escape(row['sample'])}</td>"
        f"<td class=\"num\">{summary.get('trades', 0)}</td>"
        f"<td class=\"num\">{summary.get('win_rate_pct', 0):.2f}%</td>"
        f"<td class=\"num strong\">{summary.get('avg_return_pct', 0):.2f}%</td>"
        f"<td class=\"num\">{summary.get('median_return_pct', 0):.2f}%</td>"
        f"<td class=\"num\">{summary.get('total_pnl', 0):,.0f}</td>"
        f"<td>{html.escape(row['basis'])}</td>"
        f"<td>{html.escape(row['note'])}</td>"
        "</tr>"
    )


def render_html(payload: dict[str, Any]) -> str:
    ranked = sorted(
        payload["comparison"],
        key=lambda row: (
            float(row["summary"].get("avg_return_pct", 0)),
            int(row["summary"].get("trades", 0)),
        ),
        reverse=True,
    )
    rows = "".join(row_html(row) for row in ranked)
    top = ranked[0]
    v4 = next(row for row in ranked if row["version"] == "PB-V4")
    v18_stress = next(row for row in ranked if row["version"] == "PB-V18 stress")
    period_rows = "".join(
        f"<tr><th>{html.escape(name)}</th>"
        f"<td>{html.escape(compact(payload['rebuilt_v17_periods'][name]))}</td>"
        f"<td>{html.escape(compact(payload['rebuilt_v18_cost_periods'][name]))}</td>"
        f"<td>{html.escape(compact(payload['rebuilt_v18_stress_periods'][name]))}</td></tr>"
        for name in ["train", "validation", "test", "full", "resolved_full", "resolved_test"]
    )
    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Pullback 標準 10 萬單位重跑</title><style>
:root{{--bg:#f6f7f4;--paper:#fff;--ink:#18211e;--muted:#65716b;--line:#dfe5df;--accent:#1f6a73;--good:#08735d;--bad:#a13e34}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 system-ui,"Microsoft JhengHei",sans-serif}}header,main{{max-width:1500px;margin:auto;padding:24px 16px}}header{{border-bottom:1px solid var(--line)}}h1{{margin:0 0 8px;font-size:28px;letter-spacing:0}}h2{{font-size:19px;margin:28px 0 10px}}p{{margin:6px 0;color:var(--muted)}}.cards{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1px;background:var(--line);border:1px solid var(--line);margin-top:20px}}.card{{background:var(--paper);padding:16px}}.card b{{display:block;font-size:20px}}.note{{margin-top:16px;background:#ecf3f2;border-left:4px solid var(--accent);padding:12px 14px}}.table{{overflow:auto;border:1px solid var(--line);background:var(--paper)}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}thead th{{background:#eef1ee;color:var(--muted);font-size:12px}}tbody th{{font-weight:750}}.num{{text-align:right}}.strong{{color:var(--good);font-weight:800}}code{{background:#eef1ee;padding:1px 4px;border-radius:4px}}@media(max-width:800px){{.cards{{grid-template-columns:1fr}}header,main{{padding:18px 10px}}h1{{font-size:23px}}}}
</style></head><body><header><h1>Pullback 標準 10 萬單位重跑</h1><p>每一筆符合條件的訊號都視為一份 100,000 元交易單位；不設總本金上限、不限制同日交易檔數、不用排名隊列、不排除同股舊部位未出場的重複訊號。</p><div class="cards"><div class="card"><span>平均報酬最高</span><b>{html.escape(top['version'])} {top['summary']['avg_return_pct']:.2f}%</b><small>{top['summary']['trades']} 筆，{html.escape(top['name'])}</small></div><div class="card"><span>V4 基準</span><b>{v4['summary']['win_rate_pct']:.2f}% / {v4['summary']['avg_return_pct']:.2f}%</b><small>{v4['summary']['trades']} 筆，勝率 / 平均報酬</small></div><div class="card"><span>成本壓力後</span><b>{v18_stress['summary']['win_rate_pct']:.2f}% / {v18_stress['summary']['avg_return_pct']:.2f}%</b><small>{v18_stress['summary']['trades']} 筆，V17 全訊號套 V18 成本</small></div></div><div class="note"><strong>口徑修正：</strong>這份報告刻意不使用 V18 有限本金的 50 萬、最多 5 檔、每日最多 2 檔限制。V18 在這裡只代表交易成本與滑價假設，套用在 V17 全部合格訊號上。</div></header><main><h2>版本比較</h2><div class="table"><table><thead><tr><th>版本</th><th>目標</th><th>樣本</th><th class="num">筆數</th><th class="num">勝率</th><th class="num">平均</th><th class="num">中位</th><th class="num">總損益</th><th>資料口徑</th><th>備註</th></tr></thead><tbody>{rows}</tbody></table></div><h2>V17 / V18 成本重跑切片</h2><div class="table"><table><thead><tr><th>區間</th><th>V17 毛報酬</th><th>V18 成本後</th><th>V18 成本+滑價</th></tr></thead><tbody>{period_rows}</tbody></table></div><p>輸出檔：<code>{html.escape(str(OUT_JSON))}</code>、<code>{html.escape(str(OUT_HTML))}</code></p></main></body></html>"""


def main() -> None:
    payload = collect_rows()
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    print(json.dumps({
        "html": str(OUT_HTML),
        "json": str(OUT_JSON),
        "top": payload["comparison"][0],
        "comparison_count": len(payload["comparison"]),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
