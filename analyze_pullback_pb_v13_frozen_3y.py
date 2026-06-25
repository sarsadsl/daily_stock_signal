#!/usr/bin/env python3
"""Three-year validation of the frozen PB-V11 entry and PB-V12 wide exit."""

from __future__ import annotations

import html
import json
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from analyze_pullback_core_position import exit_result, stats
from analyze_pullback_multitimeframe_search import multitimeframe_features
from analyze_pullback_rolling_climax import add_rolling_climax_scores, variant_rows
from analyze_pullback_technical_phenotypes import (
    find_series,
    make_series_map,
    rebuild_three_year_trades,
)
from analyze_pullback_versioned import research_csv_files
from run_market_backtest import Row


REPORT_DIR = Path("reports")
PBV2_JSON = REPORT_DIR / "pullback_pb_v2_0_3y.json"
OUT_JSON = REPORT_DIR / "pullback_pb_v13_frozen_3y.json"
OUT_HTML = REPORT_DIR / "pullback_pb_v13_frozen_3y.html"
VERSION = "PB-V13.0-frozen-3y"
DISCOVERY_START = "2025-09-22"
ACTIVATION_PCT = 0.15
DRAWDOWN_PCT = 0.18


def simulate_frozen_wide_exit(entry: Row, rows: list[Row], entry_index: int) -> dict[str, Any]:
    hard_stop = entry.open * 0.93
    activation = entry.open * (1 + ACTIVATION_PCT)
    highest = entry.open
    trailing: float | None = None
    observed: list[Row] = []
    for row in rows[entry_index:]:
        observed.append(row)
        # Daily OHLC cannot reveal intraday order, so same-day stop ambiguity is
        # resolved conservatively by checking the hard/trailing stop first.
        if row.low <= hard_stop:
            return exit_result(entry, observed, hard_stop, "hard_stop")
        if trailing is not None and row.low <= trailing:
            return exit_result(entry, observed, trailing, "wide_trailing_stop")
        highest = max(highest, row.high)
        if highest >= activation:
            trailing = max(trailing or 0, highest * (1 - DRAWDOWN_PCT), entry.open * 1.02)
    return exit_result(entry, observed, observed[-1].close, "latest_close", unresolved=True)


def build_trade_sets() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    series = make_series_map(research_csv_files())
    source = json.loads(PBV2_JSON.read_text(encoding="utf-8"))["trades"]
    rebuilt = rebuild_three_year_trades(source, series)
    enriched: list[dict[str, Any]] = []
    for trade in rebuilt:
        bundle = find_series(series, str(trade["market"]), str(trade["stock_no"]))
        if not bundle:
            continue
        rows, _, dates = bundle
        signal_index = dates.get(str(trade["signal_date"]))
        if signal_index is None or signal_index < 65:
            continue
        trade.update(multitimeframe_features(rows, signal_index))
        enriched.append(trade)

    add_rolling_climax_scores(enriched)
    selected = variant_rows(enriched, "avoid_score4")
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
        frozen = simulate_frozen_wide_exit(entry, rows, entry_index)
        wide = {
            **trade,
            **frozen,
            "entry_date": entry.date,
            "entry_price": round(entry.open, 4),
            "activation_pct": ACTIVATION_PCT * 100,
            "drawdown_pct": DRAWDOWN_PCT * 100,
        }
        wide["pnl"] = round(wide["return_pct"] / 100 * 100_000)
        pbv4_rows.append({**trade, "unresolved": False})
        wide_rows.append(wide)
    return pbv4_rows, wide_rows


def paired_summary(
    pbv4_rows: list[dict[str, Any]],
    wide_rows: list[dict[str, Any]],
    predicate: Callable[[dict[str, Any]], bool],
) -> dict[str, Any]:
    pbv4 = [row for row in pbv4_rows if predicate(row)]
    wide = [row for row in wide_rows if predicate(row)]
    resolved = [row for row in wide if not row["unresolved"]]
    return {
        "pbv4": stats(pbv4),
        "wide_mark_to_market": stats(wide),
        "wide_resolved": stats(resolved),
        "wide_unresolved": stats([row for row in wide if row["unresolved"]]),
        "resolved_rate_pct": round(len(resolved) / len(wide) * 100, 2) if wide else 0.0,
    }


def meets_target(summary: dict[str, Any], minimum_trades: int = 30) -> bool:
    return (
        summary["trades"] >= minimum_trades
        and summary["win_rate_pct"] >= 60
        and summary["avg_return_pct"] >= 10
    )


def run() -> dict[str, Any]:
    pbv4_rows, wide_rows = build_trade_sets()
    periods = {
        "full": paired_summary(pbv4_rows, wide_rows, lambda row: True),
        "pre_discovery": paired_summary(
            pbv4_rows, wide_rows, lambda row: row["signal_date"] < DISCOVERY_START
        ),
        "discovery_overlap": paired_summary(
            pbv4_rows, wide_rows, lambda row: row["signal_date"] >= DISCOVERY_START
        ),
        "pre2026": paired_summary(
            pbv4_rows, wide_rows, lambda row: row["signal_date"] < "2026-01-01"
        ),
        "post2026": paired_summary(
            pbv4_rows, wide_rows, lambda row: row["signal_date"] >= "2026-01-01"
        ),
    }
    years = sorted({row["signal_date"][:4] for row in wide_rows})
    by_year = {
        year: paired_summary(
            pbv4_rows, wide_rows, lambda row, y=year: row["signal_date"].startswith(y)
        )
        for year in years
    }
    full_resolved = periods["full"]["wide_resolved"]
    pre_discovery_resolved = periods["pre_discovery"]["wide_resolved"]
    exit_reasons = Counter(row["exit_reason"] for row in wide_rows)
    return {
        "version": VERSION,
        "methodology": {
            "entry": "PB-V11 base entry plus rolling prior-60-signal climax score below 4",
            "execution": "signal next open only when open is at least 2% below signal close",
            "risk": "7% hard stop",
            "wide_exit": "activate at +15%, then exit after an 18% drawdown from the running high with a +2% floor",
            "parameter_policy": "all parameters frozen before this three-year replay; no grid search in PB-V13",
            "caveat": "the exit is new to pre-2025-09-22 data, but the entry filter was developed with pre-2026 history",
        },
        "discovery_start": DISCOVERY_START,
        "periods": periods,
        "by_year": by_year,
        "exit_reasons": dict(exit_reasons),
        "full_resolved_target_met": meets_target(full_resolved),
        "pre_discovery_resolved_target_met": meets_target(pre_discovery_resolved, minimum_trades=20),
        "wide_trades": wide_rows,
    }


def compact(value: dict[str, Any]) -> str:
    return (
        f"{value['trades']} 筆｜勝率 {value['win_rate_pct']:.2f}%｜"
        f"平均 {value['avg_return_pct']:.2f}%｜中位 {value['median_return_pct']:.2f}%｜"
        f"未實現 {value['unresolved']}"
    )


def render_html(payload: dict[str, Any]) -> str:
    period_labels = {
        "full": "完整三年資料",
        "pre_discovery": "2025-09-22 前",
        "discovery_overlap": "一年發現區間",
        "pre2026": "2026 前",
        "post2026": "2026 起",
    }
    period_rows = "".join(
        f"<tr><th>{period_labels[key]}</th><td>{html.escape(compact(value['pbv4']))}</td>"
        f"<td>{html.escape(compact(value['wide_mark_to_market']))}</td>"
        f"<td>{html.escape(compact(value['wide_resolved']))}</td>"
        f"<td>{value['resolved_rate_pct']:.2f}%</td></tr>"
        for key, value in payload["periods"].items()
    )
    year_rows = "".join(
        f"<tr><th>{year}</th><td>{html.escape(compact(value['pbv4']))}</td>"
        f"<td>{html.escape(compact(value['wide_resolved']))}</td>"
        f"<td>{value['resolved_rate_pct']:.2f}%</td></tr>"
        for year, value in payload["by_year"].items()
    )
    trade_rows = "".join(
        f"<tr><td>{row['signal_date']}</td><td>{html.escape(str(row['stock_no']) + ' ' + str(row['stock_name']))}</td>"
        f"<td>{row['climax_score']}</td><td>{row['entry_price']:.2f}</td><td>{row['exit_date']}</td>"
        f"<td class={'pos' if row['return_pct'] > 0 else 'neg'}>{row['return_pct']:.2f}%</td>"
        f"<td>{row['holding_days']}</td><td>{html.escape(row['exit_reason'])}</td>"
        f"<td>{'是' if row['unresolved'] else '否'}</td></tr>"
        for row in sorted(payload["wide_trades"], key=lambda item: item["signal_date"], reverse=True)
    )
    pre = payload["periods"]["pre_discovery"]["wide_resolved"]
    full = payload["periods"]["full"]["wide_resolved"]
    passed = payload["pre_discovery_resolved_target_met"]
    status = "跨期數字達標，但仍需未來樣本確認" if passed else "跨期未達標，不能把一年結果視為穩定規律"
    tone = "pass" if passed else "fail"
    reasons = "、".join(f"{key} {value}" for key, value in payload["exit_reasons"].items())
    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PB-V13 三年凍結驗證</title><style>
:root{{--bg:#f5f6f4;--paper:#fff;--ink:#19211e;--muted:#69736f;--line:#dce1de;--good:#08735d;--bad:#a13e34;--accent:#245b78}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 system-ui,"Microsoft JhengHei",sans-serif}}header,main{{max-width:1500px;margin:auto;padding:26px 20px}}header{{border-bottom:1px solid var(--line)}}h1{{margin:0 0 6px;font-size:28px;letter-spacing:0}}h2{{margin:30px 0 10px;font-size:19px;letter-spacing:0}}p{{margin:6px 0;color:var(--muted)}}.status{{display:inline-block;margin-top:12px;padding:7px 11px;border:1px solid currentColor;font-weight:750}}.pass,.pos{{color:var(--good)}}.fail,.neg{{color:var(--bad)}}.metrics{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1px;margin-top:24px;background:var(--line);border:1px solid var(--line)}}.metric{{background:var(--paper);padding:16px}}.metric strong{{display:block;font-size:20px}}.note{{margin-top:18px;border-left:4px solid var(--accent);background:#edf3f5;padding:13px 15px}}.table{{overflow:auto;border:1px solid var(--line);background:var(--paper)}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:left}}thead th{{font-size:12px;color:var(--muted);background:#eef1ef}}tbody th{{font-weight:650}}@media(max-width:760px){{header,main{{padding:18px 10px}}h1{{font-size:23px}}.metrics{{grid-template-columns:1fr}}}}
</style></head><body><header><h1>PB-V13 三年凍結驗證</h1><p>固定 PB-V11 過熱濾網與 +15% 啟動／18% 回撤，三年資料不再調參數。</p><span class="status {tone}">{status}</span><div class="metrics"><div class="metric"><span>發現區間前，僅已出場</span><strong>{pre['win_rate_pct']:.2f}% / {pre['avg_return_pct']:.2f}%</strong><small>{pre['trades']} 筆，勝率 / 平均報酬</small></div><div class="metric"><span>完整三年，僅已出場</span><strong>{full['win_rate_pct']:.2f}% / {full['avg_return_pct']:.2f}%</strong><small>{full['trades']} 筆，勝率 / 平均報酬</small></div></div></header><main><div class="note"><strong>判讀邊界：</strong>2025-09-22 前沒有參與這次寬幅停利的發現，但 PB-V11 進場濾網曾用 2026 前資料選強度，因此這是較強的歷史壓力測試，不是完全純淨的全策略留出測試。出場原因：{html.escape(reasons)}。</div><h2>期間配對比較</h2><div class="table"><table><thead><tr><th>區間</th><th>PB-V4 20日</th><th>寬停利含未實現</th><th>寬停利僅已出場</th><th>已出場率</th></tr></thead><tbody>{period_rows}</tbody></table></div><h2>逐年穩定性</h2><div class="table"><table><thead><tr><th>年度</th><th>PB-V4 20日</th><th>寬停利僅已出場</th><th>已出場率</th></tr></thead><tbody>{year_rows}</tbody></table></div><h2>固定規則交易明細</h2><div class="table"><table><thead><tr><th>訊號日</th><th>股票</th><th>過熱分</th><th>成本</th><th>出場日</th><th>報酬</th><th>持有日</th><th>原因</th><th>未實現</th></tr></thead><tbody>{trade_rows}</tbody></table></div></main></body></html>"""


def main() -> None:
    payload = run()
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    print(json.dumps({
        "pre_discovery": payload["periods"]["pre_discovery"],
        "full": payload["periods"]["full"],
        "by_year": payload["by_year"],
        "full_resolved_target_met": payload["full_resolved_target_met"],
        "pre_discovery_resolved_target_met": payload["pre_discovery_resolved_target_met"],
        "html": str(OUT_HTML),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
