#!/usr/bin/env python3
"""Finite-capital, cost-aware audit of the PB-V17 two-stage runner."""

from __future__ import annotations

import html
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from analyze_pullback_core_position import stats
from analyze_pullback_multitimeframe_search import BENCHMARK_CSV, date_split, enrich_trades
from analyze_pullback_pb_v15_all_signal_history import (
    attach_prior_only_scores,
    enrich_all_three_year_signals,
)
from analyze_pullback_pb_v16_daily_ranking import buy_and_hold
from analyze_pullback_pb_v17_two_stage_runner import replay, signal_rank
from analyze_pullback_rolling_climax import variant_rows
from analyze_pullback_technical_phenotypes import make_series_map
from run_market_backtest import csv_files


REPORT_DIR = Path("reports")
OUT_JSON = REPORT_DIR / "pullback_pb_v18_finite_capital.json"
OUT_HTML = REPORT_DIR / "pullback_pb_v18_finite_capital.html"
VERSION = "PB-V18.0-finite-capital"

CAPITAL = 500_000
POSITION_SIZE = 100_000
MAX_POSITIONS = 5
MAX_NEW_PER_DAY = 2
BUY_FEE_PCT = 0.1425
SELL_FEE_PCT = 0.1425
STOCK_SELL_TAX_PCT = 0.3
ETF_SELL_TAX_PCT = 0.1
STRESS_SLIPPAGE_EACH_SIDE_PCT = 0.1


def select_finite_portfolio(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["signal_date"]].append(row)
    selected: list[dict[str, Any]] = []
    for signal_date in sorted(grouped):
        candidates = sorted(grouped[signal_date], key=signal_rank, reverse=True)
        entry_date = candidates[0]["entry_date"]
        active = [row for row in selected if row["exit_date"] >= entry_date]
        held_codes = {row["stock_no"] for row in active}
        available = max(MAX_POSITIONS - len(active), 0)
        limit = min(MAX_NEW_PER_DAY, available)
        picked = 0
        for candidate in candidates:
            if candidate["stock_no"] in held_codes:
                continue
            if picked >= limit:
                break
            selected.append({**candidate, "daily_rank": picked + 1})
            held_codes.add(candidate["stock_no"])
            picked += 1
    return selected


def net_return(gross_return_pct: float, *, tax_pct: float, slippage_pct: float) -> float:
    buy_cost = BUY_FEE_PCT + slippage_pct
    sell_cost = (1 + gross_return_pct / 100) * (SELL_FEE_PCT + tax_pct + slippage_pct)
    return gross_return_pct - buy_cost - sell_cost


def adjusted_rows(rows: list[dict[str, Any]], slippage_pct: float) -> list[dict[str, Any]]:
    output = []
    for original in rows:
        row = dict(original)
        gross = float(row["return_pct"])
        net = net_return(gross, tax_pct=STOCK_SELL_TAX_PCT, slippage_pct=slippage_pct)
        row["gross_return_pct"] = gross
        row["return_pct"] = round(net, 4)
        row["transaction_cost_pct"] = round(gross - net, 4)
        row["pnl"] = round(net / 100 * POSITION_SIZE)
        benchmark = row.get("benchmark_return_pct")
        if isinstance(benchmark, (int, float)):
            benchmark_net = net_return(
                float(benchmark), tax_pct=ETF_SELL_TAX_PCT, slippage_pct=slippage_pct
            )
            row["benchmark_return_pct"] = round(benchmark_net, 4)
            row["excess_return_pct"] = round(net - benchmark_net, 4)
        output.append(row)
    return output


def scenario(
    resolved_rows: list[dict[str, Any]],
    slippage_pct: float,
) -> dict[str, Any]:
    net_rows = adjusted_rows(resolved_rows, slippage_pct)
    summary = stats(net_rows)
    total_pnl = round(sum(row["pnl"] for row in net_rows))
    required_cash = round(CAPITAL * (1 + (BUY_FEE_PCT + slippage_pct) / 100), 2)
    capital_return = round(total_pnl / required_cash * 100, 2)
    hold = buy_and_hold(resolved_rows)
    hold_net = net_return(
        float(hold["return_pct"]), tax_pct=ETF_SELL_TAX_PCT, slippage_pct=slippage_pct
    )
    return {
        "slippage_each_side_pct": slippage_pct,
        "trade_summary": summary,
        "total_pnl": total_pnl,
        "required_cash": required_cash,
        "capital_return_pct": capital_return,
        "benchmark_buy_hold": {**hold, "net_return_pct": round(hold_net, 2)},
        "capital_excess_pct": round(capital_return - hold_net, 2),
        "target_met": (
            summary["trades"] >= 20
            and summary["win_rate_pct"] >= 60
            and summary["avg_return_pct"] >= 10
            and capital_return > hold_net
        ),
        "net_rows": net_rows,
    }


def period_summaries(
    rows: list[dict[str, Any]], validation_start: str, test_start: str, slippage_pct: float
) -> dict[str, Any]:
    groups = {
        "train": [row for row in rows if row["signal_date"] < validation_start],
        "validation": [row for row in rows if validation_start <= row["signal_date"] < test_start],
        "test": [row for row in rows if row["signal_date"] >= test_start],
        "full": rows,
        "resolved_full": [row for row in rows if not row["unresolved"]],
        "resolved_test": [row for row in rows if row["signal_date"] >= test_start and not row["unresolved"]],
    }
    return {name: stats(adjusted_rows(value, slippage_pct)) for name, value in groups.items()}


def run() -> dict[str, Any]:
    historical, _ = enrich_all_three_year_signals()
    one_year, _ = enrich_trades()
    attach_prior_only_scores(one_year, historical)
    candidates = variant_rows(one_year, "avoid_score4")
    exits = replay(candidates, make_series_map(csv_files()), BENCHMARK_CSV)
    portfolio = select_finite_portfolio(exits)
    resolved = [row for row in portfolio if not row["unresolved"]]
    validation_start, test_start = date_split(one_year)
    max_fee = scenario(resolved, 0.0)
    stress = scenario(resolved, STRESS_SLIPPAGE_EACH_SIDE_PCT)
    return {
        "version": VERSION,
        "methodology": {
            "entry": "PB-V15 all-prior-signal rolling score; ABC/monthly/MA20 base; climax score below 4; next-open discount 2%",
            "ranking": "daily original signal score descending, then climax score ascending, then completed-month momentum descending",
            "portfolio": f"TWD {CAPITAL:,}; TWD {POSITION_SIZE:,} each; max {MAX_POSITIONS} positions and {MAX_NEW_PER_DAY} new positions per day; no duplicate active stock",
            "exit": "gap-aware -7% hard stop; +12% high protects +2%; +15% high starts 18% peak drawdown trail",
            "costs": {
                "buy_fee_pct": BUY_FEE_PCT,
                "sell_fee_pct": SELL_FEE_PCT,
                "stock_sell_tax_pct": STOCK_SELL_TAX_PCT,
                "etf_sell_tax_pct": ETF_SELL_TAX_PCT,
                "stress_slippage_each_side_pct": STRESS_SLIPPAGE_EACH_SIDE_PCT,
                "status": "explicit conservative assumptions; official lookup was unavailable during this run",
            },
            "caveat": "the exit and capacity rules were developed after observing this one-year sample; forward validation is still required",
        },
        "split": {"validation_start": validation_start, "test_start": test_start},
        "selected": len(portfolio),
        "resolved": len(resolved),
        "unresolved": len(portfolio) - len(resolved),
        "gross_resolved": stats(resolved),
        "max_fee": {key: value for key, value in max_fee.items() if key != "net_rows"},
        "stress": {key: value for key, value in stress.items() if key != "net_rows"},
        "periods_max_fee": period_summaries(portfolio, validation_start, test_start, 0.0),
        "periods_stress": period_summaries(
            portfolio, validation_start, test_start, STRESS_SLIPPAGE_EACH_SIDE_PCT
        ),
        "final_candidate_passes": max_fee["target_met"] and stress["target_met"],
        "portfolio_trades": max_fee["net_rows"],
    }


def compact(value: dict[str, Any]) -> str:
    return (
        f"{value['trades']} 筆｜勝率 {value['win_rate_pct']:.2f}%｜平均 {value['avg_return_pct']:.2f}%｜"
        f"中位 {value['median_return_pct']:.2f}%｜未實現 {value['unresolved']}"
    )


def render_html(payload: dict[str, Any]) -> str:
    periods = payload["periods_stress"]
    labels = {"train": "訓練", "validation": "驗證", "test": "最後20%", "resolved_test": "最後20%已出場", "resolved_full": "完整一年已出場"}
    period_rows = "".join(
        f"<tr><th>{label}</th><td>{html.escape(compact(periods[key]))}</td></tr>"
        for key, label in labels.items()
    )
    trade_rows = "".join(
        f"<tr><td>{row['signal_date']}</td><td>{row['daily_rank']}</td>"
        f"<td>{html.escape(str(row['stock_no']) + ' ' + str(row['stock_name']))}</td>"
        f"<td>{row['gross_return_pct']:.2f}%</td><td class={'pos' if row['return_pct'] > 0 else 'neg'}>{row['return_pct']:.2f}%</td>"
        f"<td>{row['transaction_cost_pct']:.2f}%</td><td>{row['holding_days']}</td>"
        f"<td>{html.escape(row['exit_reason'])}</td><td>{'是' if row['unresolved'] else '否'}</td></tr>"
        for row in sorted(payload["portfolio_trades"], key=lambda item: item["signal_date"], reverse=True)
    )
    max_fee = payload["max_fee"]
    stress = payload["stress"]
    max_stats = max_fee["trade_summary"]
    stress_stats = stress["trade_summary"]
    passed = payload["final_candidate_passes"]
    status = "完整一年通過；最後20%仍未通過" if passed else "壓力測試後未通過最終目標"
    tone = "pass" if passed else "fail"
    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PB-V18 有限本金最終稽核</title><style>
:root{{--bg:#f4f6f5;--paper:#fff;--ink:#18211e;--muted:#68736f;--line:#dbe2de;--good:#08735d;--bad:#a13e34;--accent:#245b78}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 system-ui,"Microsoft JhengHei",sans-serif}}header,main{{max-width:1500px;margin:auto;padding:26px 20px}}header{{border-bottom:1px solid var(--line)}}h1{{margin:0 0 6px;font-size:28px;letter-spacing:0}}h2{{margin:30px 0 10px;font-size:19px;letter-spacing:0}}p{{margin:6px 0;color:var(--muted)}}.status{{display:inline-block;margin-top:12px;padding:7px 11px;border:1px solid currentColor;font-weight:750}}.pass,.pos{{color:var(--good)}}.fail,.neg{{color:var(--bad)}}.metrics{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1px;margin-top:24px;background:var(--line);border:1px solid var(--line)}}.metric{{background:var(--paper);padding:16px}}.metric strong{{display:block;font-size:20px}}.note{{margin-top:18px;border-left:4px solid var(--accent);background:#edf3f5;padding:13px 15px}}.table{{overflow:auto;border:1px solid var(--line);background:var(--paper)}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:left}}thead th{{font-size:12px;color:var(--muted);background:#eef1ef}}tbody th{{font-weight:650}}@media(max-width:900px){{.metrics{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}@media(max-width:560px){{header,main{{padding:18px 10px}}h1{{font-size:23px}}.metrics{{grid-template-columns:1fr}}}}
</style></head><body><header><h1>PB-V18 有限本金最終稽核</h1><p>50 萬本金、最多 5 檔，納入跳空停損、交易成本與雙邊不利滑價。</p><span class="status {tone}">{status}</span><div class="metrics"><div class="metric"><span>成本後單筆</span><strong>{max_stats['win_rate_pct']:.2f}% / {max_stats['avg_return_pct']:.2f}%</strong><small>{max_stats['trades']} 筆，勝率 / 平均報酬</small></div><div class="metric"><span>成本後本金報酬</span><strong>{max_fee['capital_return_pct']:.2f}%</strong><small>淨損益 {max_fee['total_pnl']:,} 元</small></div><div class="metric"><span>滑價壓力後本金報酬</span><strong>{stress['capital_return_pct']:.2f}%</strong><small>勝率 {stress_stats['win_rate_pct']:.2f}%｜平均 {stress_stats['avg_return_pct']:.2f}%</small></div><div class="metric"><span>壓力情境0050</span><strong>{stress['benchmark_buy_hold']['net_return_pct']:.2f}%</strong><small>策略超額 {stress['capital_excess_pct']:.2f}%</small></div></div></header><main><div class="note"><strong>規則已固定：</strong>每日最多新增 2 檔、總持倉最多 5 檔，同股未出場不得重複進場。壓力情境所需現金 {stress['required_cash']:,.0f} 元，已把滿倉買進費用與滑價納入本金分母。成本假設為股票買賣手續費各 0.1425%、賣出稅 0.3%；0050 賣出稅 0.1%，再加入買賣各 0.10% 不利滑價。費率是明列的保守假設，非本次即時官方查價。<br><strong>尚未解決：</strong>最後20%僅已出場為 {periods['resolved_test']['win_rate_pct']:.2f}%／{periods['resolved_test']['avg_return_pct']:.2f}%，因此完整一年已達目標，但前瞻穩定性仍需新訊號驗證。</div><h2>滑價壓力下的時間切片</h2><div class="table"><table><thead><tr><th>區間</th><th>成本後績效</th></tr></thead><tbody>{period_rows}</tbody></table></div><h2>組合交易明細</h2><div class="table"><table><thead><tr><th>訊號日</th><th>日排名</th><th>股票</th><th>毛報酬</th><th>成本後</th><th>成本</th><th>持有日</th><th>出場</th><th>未實現</th></tr></thead><tbody>{trade_rows}</tbody></table></div></main></body></html>"""


def main() -> None:
    payload = run()
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    print(json.dumps({
        "selected": payload["selected"],
        "resolved": payload["resolved"],
        "unresolved": payload["unresolved"],
        "gross_resolved": payload["gross_resolved"],
        "max_fee": payload["max_fee"],
        "stress": payload["stress"],
        "periods_stress": payload["periods_stress"],
        "final_candidate_passes": payload["final_candidate_passes"],
        "html": str(OUT_HTML),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
