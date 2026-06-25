#!/usr/bin/env python3
"""Frozen three-year pullback replay with one predeclared 0050 trend gate."""

from __future__ import annotations

import bisect
import html
import json
import statistics
from pathlib import Path
from typing import Any, Callable

from analyze_pullback_pb_v13_frozen_3y import (
    DISCOVERY_START,
    build_trade_sets,
    paired_summary,
)
from run_market_backtest import read_rows


REPORT_DIR = Path("reports")
BENCHMARK_CSV = Path("data/benchmark_0050_2023-06-01_2026-06-18.csv")
OUT_JSON = REPORT_DIR / "pullback_pb_v14_market_gate.json"
OUT_HTML = REPORT_DIR / "pullback_pb_v14_market_gate.html"
VERSION = "PB-V14.0-market-gate"
PROFILE_FEATURES = {
    "ab_gain_pct": "A→B 漲幅",
    "bc_retrace_pct": "B→C 回撤",
    "peak_age_days": "距 B 高點天數",
    "return20_pct": "訊號前20日漲幅",
    "monthly_momentum3_pct": "前三個完整月動能",
    "close_vs_ma60_pct": "MA60 乖離",
    "atr20_pct": "ATR20",
    "c_vs_ab_volume": "C段 / AB段量比",
    "last5_volume_ratio": "末五日 / 20日量比",
    "close_location": "訊號K收盤位置",
}


def continuous_closes() -> tuple[list[str], list[float], list[dict[str, Any]]]:
    rows = read_rows(BENCHMARK_CSV)
    dates = [row.date for row in rows]
    closes: list[float] = []
    adjustments: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if index == 0:
            closes.append(row.close)
            continue
        raw_ratio = row.close / rows[index - 1].close
        normalized_ratio = raw_ratio
        if raw_ratio < 0.5:
            split_multiple = max(2, round(1 / raw_ratio))
            normalized_ratio = raw_ratio * split_multiple
            adjustments.append({
                "date": row.date,
                "raw_ratio": round(raw_ratio, 6),
                "split_multiple": split_multiple,
            })
        elif raw_ratio > 2:
            split_multiple = max(2, round(raw_ratio))
            normalized_ratio = raw_ratio / split_multiple
            adjustments.append({
                "date": row.date,
                "raw_ratio": round(raw_ratio, 6),
                "split_multiple": split_multiple,
            })
        closes.append(closes[-1] * normalized_ratio)
    return dates, closes, adjustments


def moving_average(values: list[float], window: int) -> list[float | None]:
    output: list[float | None] = [None] * len(values)
    running = 0.0
    for index, value in enumerate(values):
        running += value
        if index >= window:
            running -= values[index - window]
        if index >= window - 1:
            output[index] = running / window
    return output


def add_market_gate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dates, closes, _ = continuous_closes()
    ma20 = moving_average(closes, 20)
    ma60 = moving_average(closes, 60)
    for row in rows:
        cursor = bisect.bisect_right(dates, row["signal_date"]) - 1
        valid = cursor >= 0 and ma20[cursor] is not None and ma60[cursor] is not None
        row["benchmark_date"] = dates[cursor] if cursor >= 0 else None
        row["benchmark_close_continuous"] = round(closes[cursor], 4) if cursor >= 0 else None
        row["benchmark_ma20"] = round(float(ma20[cursor]), 4) if valid else None
        row["benchmark_ma60"] = round(float(ma60[cursor]), 4) if valid else None
        row["primary_uptrend"] = bool(
            valid and closes[cursor] > float(ma60[cursor]) and float(ma20[cursor]) > float(ma60[cursor])
        )
    return rows


def regime_periods(
    pbv4_rows: list[dict[str, Any]],
    wide_rows: list[dict[str, Any]],
    gate: Callable[[dict[str, Any]], bool],
) -> dict[str, Any]:
    def both(predicate: Callable[[dict[str, Any]], bool]) -> Callable[[dict[str, Any]], bool]:
        return lambda row: gate(row) and predicate(row)

    return {
        "full": paired_summary(pbv4_rows, wide_rows, gate),
        "pre_discovery": paired_summary(
            pbv4_rows, wide_rows, both(lambda row: row["signal_date"] < DISCOVERY_START)
        ),
        "discovery_overlap": paired_summary(
            pbv4_rows, wide_rows, both(lambda row: row["signal_date"] >= DISCOVERY_START)
        ),
        "pre2026": paired_summary(
            pbv4_rows, wide_rows, both(lambda row: row["signal_date"] < "2026-01-01")
        ),
        "post2026": paired_summary(
            pbv4_rows, wide_rows, both(lambda row: row["signal_date"] >= "2026-01-01")
        ),
    }


def phenotype_profile(rows: list[dict[str, Any]]) -> dict[str, Any]:
    resolved = [row for row in rows if not row["unresolved"]]
    groups = {
        "2024": [row for row in resolved if row["signal_date"].startswith("2024")],
        "2025_2026": [row for row in resolved if row["signal_date"] >= "2025-01-01"],
        "winners": [row for row in resolved if row["return_pct"] > 0],
        "losers": [row for row in resolved if row["return_pct"] <= 0],
    }
    values: dict[str, Any] = {}
    for feature in PROFILE_FEATURES:
        values[feature] = {}
        for name, group in groups.items():
            numeric = [float(row[feature]) for row in group if isinstance(row.get(feature), (int, float))]
            values[feature][name] = round(statistics.median(numeric), 2) if numeric else None
    return {"counts": {name: len(group) for name, group in groups.items()}, "medians": values}


def run() -> dict[str, Any]:
    pbv4_rows, wide_rows = build_trade_sets()
    add_market_gate(pbv4_rows)
    add_market_gate(wide_rows)
    dates, _, adjustments = continuous_closes()
    regimes = {
        "all_market": regime_periods(pbv4_rows, wide_rows, lambda row: True),
        "primary_uptrend": regime_periods(
            pbv4_rows, wide_rows, lambda row: bool(row["primary_uptrend"])
        ),
    }
    years = sorted({row["signal_date"][:4] for row in wide_rows})
    by_year = {
        year: {
            regime: paired_summary(
                pbv4_rows,
                wide_rows,
                lambda row, y=year, r=regime: row["signal_date"].startswith(y)
                and (r == "all_market" or bool(row["primary_uptrend"])),
            )
            for regime in regimes
        }
        for year in years
    }
    selected = [row for row in wide_rows if row["primary_uptrend"]]
    resolved = [row for row in selected if not row["unresolved"]]
    resolved_stats = regimes["primary_uptrend"]["full"]["wide_resolved"]
    target_met = (
        resolved_stats["trades"] >= 30
        and resolved_stats["win_rate_pct"] >= 60
        and resolved_stats["avg_return_pct"] >= 10
    )
    return {
        "version": VERSION,
        "benchmark": {
            "file": str(BENCHMARK_CSV),
            "rows": len(dates),
            "corporate_action_adjustments": adjustments,
        },
        "methodology": {
            "frozen_strategy": "PB-V11 avoid_score4 plus PB-V12 +15% activation / 18% drawdown",
            "market_gate": "0050 signal-day continuous close > MA60 and MA20 > MA60",
            "lookahead": "uses the last 0050 close on or before the signal date only",
            "search": "no alternate benchmark, moving average, or threshold was tested",
        },
        "regimes": regimes,
        "by_year": by_year,
        "retention_pct": round(len(selected) / len(wide_rows) * 100, 2) if wide_rows else 0.0,
        "target_met_on_primary_uptrend_resolved": target_met,
        "phenotype_profile": phenotype_profile(selected),
        "selected_trades": selected,
        "resolved_selected_count": len(resolved),
    }


def compact(value: dict[str, Any]) -> str:
    return (
        f"{value['trades']} 筆｜勝率 {value['win_rate_pct']:.2f}%｜"
        f"平均 {value['avg_return_pct']:.2f}%｜中位 {value['median_return_pct']:.2f}%｜"
        f"未實現 {value['unresolved']}"
    )


def render_html(payload: dict[str, Any]) -> str:
    labels = {
        "full": "完整三年",
        "pre_discovery": "2025-09-22 前",
        "discovery_overlap": "一年發現區間",
        "pre2026": "2026 前",
        "post2026": "2026 起",
    }
    comparison_rows = "".join(
        f"<tr><th>{labels[period]}</th>"
        f"<td>{html.escape(compact(payload['regimes']['all_market'][period]['wide_resolved']))}</td>"
        f"<td>{html.escape(compact(payload['regimes']['primary_uptrend'][period]['pbv4']))}</td>"
        f"<td>{html.escape(compact(payload['regimes']['primary_uptrend'][period]['wide_resolved']))}</td></tr>"
        for period in labels
    )
    year_rows = "".join(
        f"<tr><th>{year}</th>"
        f"<td>{html.escape(compact(values['all_market']['wide_resolved']))}</td>"
        f"<td>{html.escape(compact(values['primary_uptrend']['wide_resolved']))}</td></tr>"
        for year, values in payload["by_year"].items()
    )
    profile = payload["phenotype_profile"]
    profile_rows = "".join(
        f"<tr><th>{html.escape(label)}</th>"
        f"<td>{profile['medians'][feature]['2024'] if profile['medians'][feature]['2024'] is not None else '-'}</td>"
        f"<td>{profile['medians'][feature]['2025_2026'] if profile['medians'][feature]['2025_2026'] is not None else '-'}</td>"
        f"<td>{profile['medians'][feature]['winners'] if profile['medians'][feature]['winners'] is not None else '-'}</td>"
        f"<td>{profile['medians'][feature]['losers'] if profile['medians'][feature]['losers'] is not None else '-'}</td></tr>"
        for feature, label in PROFILE_FEATURES.items()
    )
    trade_rows = "".join(
        f"<tr><td>{row['signal_date']}</td><td>{html.escape(str(row['stock_no']) + ' ' + str(row['stock_name']))}</td>"
        f"<td>{row['climax_score']}</td><td>{row['benchmark_close_continuous']:.2f}</td>"
        f"<td>{row['benchmark_ma20']:.2f}</td><td>{row['benchmark_ma60']:.2f}</td>"
        f"<td class={'pos' if row['return_pct'] > 0 else 'neg'}>{row['return_pct']:.2f}%</td>"
        f"<td>{row['holding_days']}</td><td>{html.escape(row['exit_reason'])}</td>"
        f"<td>{'是' if row['unresolved'] else '否'}</td></tr>"
        for row in sorted(payload["selected_trades"], key=lambda item: item["signal_date"], reverse=True)
    )
    gated = payload["regimes"]["primary_uptrend"]["full"]["wide_resolved"]
    baseline = payload["regimes"]["all_market"]["full"]["wide_resolved"]
    passed = payload["target_met_on_primary_uptrend_resolved"]
    status = "主升段版本達到三年彙總門檻" if passed else "主升段閘門仍未達到三年彙總門檻"
    tone = "pass" if passed else "fail"
    adjustments = "、".join(
        f"{item['date']} 偵測 {item['split_multiple']}:1 跳點" for item in payload["benchmark"]["corporate_action_adjustments"]
    ) or "無"
    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PB-V14 大盤主升段閘門</title><style>
:root{{--bg:#f4f6f5;--paper:#fff;--ink:#18211e;--muted:#68736f;--line:#dbe2de;--good:#08735d;--bad:#a13e34;--accent:#245b78}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 system-ui,"Microsoft JhengHei",sans-serif}}header,main{{max-width:1500px;margin:auto;padding:26px 20px}}header{{border-bottom:1px solid var(--line)}}h1{{margin:0 0 6px;font-size:28px;letter-spacing:0}}h2{{margin:30px 0 10px;font-size:19px;letter-spacing:0}}p{{margin:6px 0;color:var(--muted)}}.status{{display:inline-block;margin-top:12px;padding:7px 11px;border:1px solid currentColor;font-weight:750}}.pass,.pos{{color:var(--good)}}.fail,.neg{{color:var(--bad)}}.metrics{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1px;margin-top:24px;background:var(--line);border:1px solid var(--line)}}.metric{{background:var(--paper);padding:16px}}.metric strong{{display:block;font-size:20px}}.note{{margin-top:18px;border-left:4px solid var(--accent);background:#edf3f5;padding:13px 15px}}.table{{overflow:auto;border:1px solid var(--line);background:var(--paper)}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:left}}thead th{{font-size:12px;color:var(--muted);background:#eef1ef}}tbody th{{font-weight:650}}@media(max-width:760px){{header,main{{padding:18px 10px}}h1{{font-size:23px}}.metrics{{grid-template-columns:1fr}}}}
</style></head><body><header><h1>PB-V14 大盤主升段閘門</h1><p>只在訊號日 0050 收盤高於 MA60，且 MA20 高於 MA60 時交易。</p><span class="status {tone}">{status}</span><div class="metrics"><div class="metric"><span>未分盤勢，僅已出場</span><strong>{baseline['win_rate_pct']:.2f}% / {baseline['avg_return_pct']:.2f}%</strong><small>{baseline['trades']} 筆，勝率 / 平均報酬</small></div><div class="metric"><span>主升段，僅已出場</span><strong>{gated['win_rate_pct']:.2f}% / {gated['avg_return_pct']:.2f}%</strong><small>{gated['trades']} 筆，勝率 / 平均報酬</small></div><div class="metric"><span>訊號保留率</span><strong>{payload['retention_pct']:.2f}%</strong><small>未以績效反向選門檻</small></div></div></header><main><div class="note"><strong>資料處理：</strong>0050 共 {payload['benchmark']['rows']} 日；{html.escape(adjustments)}，以連續價格計算均線。閘門只看訊號日或更早資料。這仍不是純粹的全策略留出測試，因為 PB-V11 進場濾網曾使用歷史資料選強度。</div><h2>盤勢閘門前後</h2><div class="table"><table><thead><tr><th>區間</th><th>未分盤勢寬停利</th><th>主升段 PB-V4</th><th>主升段寬停利</th></tr></thead><tbody>{comparison_rows}</tbody></table></div><h2>逐年穩定性</h2><div class="table"><table><thead><tr><th>年度</th><th>未分盤勢寬停利</th><th>主升段寬停利</th></tr></thead><tbody>{year_rows}</tbody></table></div><h2>技術型態剖面</h2><p>僅為事後描述，不把中位數直接改寫成新門檻。2024 的主要問題是回撤較淺、離 B 高點較久且 MA60 乖離較大；成功組也沒有呈現「越縮量越好」。</p><div class="table"><table><thead><tr><th>特徵中位數</th><th>2024（{profile['counts']['2024']}筆）</th><th>2025–2026（{profile['counts']['2025_2026']}筆）</th><th>贏家（{profile['counts']['winners']}筆）</th><th>輸家（{profile['counts']['losers']}筆）</th></tr></thead><tbody>{profile_rows}</tbody></table></div><h2>主升段交易明細</h2><div class="table"><table><thead><tr><th>訊號日</th><th>股票</th><th>過熱分</th><th>0050連續價</th><th>MA20</th><th>MA60</th><th>報酬</th><th>持有日</th><th>原因</th><th>未實現</th></tr></thead><tbody>{trade_rows}</tbody></table></div></main></body></html>"""


def main() -> None:
    payload = run()
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    print(json.dumps({
        "benchmark": payload["benchmark"],
        "retention_pct": payload["retention_pct"],
        "all_market_resolved": payload["regimes"]["all_market"]["full"]["wide_resolved"],
        "primary_uptrend_resolved": payload["regimes"]["primary_uptrend"]["full"]["wide_resolved"],
        "primary_uptrend_by_year": {
            year: values["primary_uptrend"]["wide_resolved"]
            for year, values in payload["by_year"].items()
        },
        "target_met_on_primary_uptrend_resolved": payload["target_met_on_primary_uptrend_resolved"],
        "html": str(OUT_HTML),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
