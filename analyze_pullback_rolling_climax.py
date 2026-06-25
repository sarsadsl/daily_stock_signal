#!/usr/bin/env python3
"""Rolling, prior-only climax filter for pullback entries."""

from __future__ import annotations

import html
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from analyze_pullback_discount2_swing import summarize
from analyze_pullback_multitimeframe_search import (
    date_split,
    enrich_trades,
    multitimeframe_features,
)
from analyze_pullback_technical_phenotypes import (
    find_series,
    make_series_map,
    rebuild_three_year_trades,
)
from analyze_pullback_versioned import research_csv_files


REPORT_DIR = Path("reports")
VERSION = "PB-V11.0-rolling-climax"
PBV2_JSON = REPORT_DIR / "pullback_pb_v2_0_3y.json"
OUT_JSON = REPORT_DIR / "pullback_pb_v11_rolling_climax.json"
OUT_HTML = REPORT_DIR / "pullback_pb_v11_rolling_climax.html"

FEATURE_DIRECTIONS = {
    "return20_pct": "high",
    "weekly_momentum4_pct": "high",
    "monthly_momentum3_pct": "high",
    "close_vs_ma60_pct": "high",
    "atr20_pct": "high",
    "last5_volume_ratio": "high",
    "bc_retrace_pct": "low",
}

VARIANTS = {
    "baseline": 8,
    "avoid_score4": 4,
    "avoid_score3": 3,
    "avoid_score2": 2,
}


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def add_rolling_climax_scores(trades: list[dict[str, Any]], history_size: int = 60, min_history: int = 30) -> None:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        grouped[trade["signal_date"]].append(trade)
    history: list[dict[str, Any]] = []
    for signal_date in sorted(grouped):
        current = grouped[signal_date]
        prior = history[-history_size:]
        for trade in current:
            score = 0
            details: dict[str, bool] = {}
            if len(prior) >= min_history:
                for feature, direction in FEATURE_DIRECTIONS.items():
                    values = [float(row[feature]) for row in prior if isinstance(row.get(feature), (int, float))]
                    if len(values) < min_history // 2 or not isinstance(trade.get(feature), (int, float)):
                        details[feature] = False
                        continue
                    threshold = percentile(values, 0.75 if direction == "high" else 0.25)
                    hot = float(trade[feature]) > threshold if direction == "high" else float(trade[feature]) < threshold
                    details[feature] = hot
                    score += int(hot)
            trade["climax_score"] = score
            trade["climax_history_count"] = len(prior)
            trade["climax_flags"] = details
        history.extend(current)


def base_entry(trade: dict[str, Any]) -> bool:
    return (
        trade["ab_gain_pct"] >= 15
        and 2 <= trade["peak_age_days"] <= 8
        and 20 <= trade["bc_retrace_pct"] <= 55
        and trade["close_vs_ma60_pct"] >= 0
        and trade.get("monthly_trend", False)
        and 0 <= trade["close_vs_ma20_pct"] <= 8
    )


def variant_rows(trades: list[dict[str, Any]], variant: str) -> list[dict[str, Any]]:
    limit = VARIANTS[variant]
    return [row for row in trades if base_entry(row) and row["climax_score"] < limit]


def rebuild_three_year() -> list[dict[str, Any]]:
    series = make_series_map(research_csv_files())
    source = json.loads(PBV2_JSON.read_text(encoding="utf-8"))["trades"]
    trades = rebuild_three_year_trades(source, series)
    output = []
    for trade in trades:
        bundle = find_series(series, str(trade["market"]), str(trade["stock_no"]))
        if not bundle:
            continue
        rows, _, dates = bundle
        index = dates.get(trade["signal_date"])
        if index is None or index < 65:
            continue
        trade.update(multitimeframe_features(rows, index))
        output.append(trade)
    return output


def summarize_variants(trades: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {variant: summarize(variant_rows(trades, variant)) for variant in VARIANTS}


def year_summaries(trades: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        year: summarize_variants([row for row in trades if row["signal_date"].startswith(year)])
        for year in sorted({row["signal_date"][:4] for row in trades})
    }


def choose_on_pre2026(trades: list[dict[str, Any]]) -> str:
    historical = [row for row in trades if row["signal_date"] < "2026-01-01"]
    candidates = []
    for variant in VARIANTS:
        rows = variant_rows(historical, variant)
        stats = summarize(rows)
        if stats["trades"] < 20:
            continue
        shortfall = max(60 - stats["win_rate_pct"], 0) + max(10 - stats["avg_return_pct"], 0) * 2
        score = stats["win_rate_pct"] * 0.4 + stats["avg_return_pct"] * 2 + stats["median_return_pct"] * 0.5 + min(stats["trades"], 60) * 0.05 - shortfall
        candidates.append((score, variant, stats))
    if not candidates:
        return "baseline"
    candidates.sort(reverse=True)
    return candidates[0][1]


def run() -> dict[str, Any]:
    one_year, _ = enrich_trades()
    three_year = rebuild_three_year()
    add_rolling_climax_scores(one_year)
    add_rolling_climax_scores(three_year)
    chosen = choose_on_pre2026(three_year)

    validation_start, test_start = date_split(one_year)
    one_year_segments = {
        "train": [row for row in one_year if row["signal_date"] < validation_start],
        "validation": [row for row in one_year if validation_start <= row["signal_date"] < test_start],
        "test": [row for row in one_year if row["signal_date"] >= test_start],
        "full": one_year,
    }
    segment_results = {name: summarize_variants(rows) for name, rows in one_year_segments.items()}
    chosen_test = segment_results["test"][chosen]
    target_met = chosen_test["trades"] >= 10 and chosen_test["win_rate_pct"] >= 60 and chosen_test["avg_return_pct"] >= 10
    return {
        "version": VERSION,
        "methodology": {
            "base_entry": "ABC fast pullback + completed-month uptrend + signal close within 0%-8% above MA20 + next-open discount 2%",
            "climax_score": "one point for each feature beyond its rolling prior-60-signal 75th percentile; BC retracement uses the lower 25th percentile",
            "features": FEATURE_DIRECTIONS,
            "history": "same-date signals never enter one another's history; minimum 30 prior signals",
            "selection": "filter strength selected only on expanded three-year signals before 2026",
            "exit": "PB-V4 fully realized 20-day policy",
        },
        "chosen_variant": chosen,
        "variant_score_limits": VARIANTS,
        "one_year_count": len(one_year),
        "three_year_count": len(three_year),
        "one_year_split": {"validation_start": validation_start, "test_start": test_start},
        "one_year_segments": segment_results,
        "three_year_full": summarize_variants(three_year),
        "three_year_by_year": year_summaries(three_year),
        "pre2026_selection": summarize_variants([row for row in three_year if row["signal_date"] < "2026-01-01"]),
        "post2026_test": summarize_variants([row for row in three_year if row["signal_date"] >= "2026-01-01"]),
        "target_met_on_one_year_test": target_met,
        "chosen_one_year_trades": variant_rows(one_year, chosen),
    }


def summary_text(stats: dict[str, Any]) -> str:
    return f"{stats['trades']} 筆｜勝率 {stats['win_rate_pct']:.2f}%｜平均 {stats['avg_return_pct']:.2f}%｜中位 {stats['median_return_pct']:.2f}%"


def render_html(payload: dict[str, Any]) -> str:
    rows = "".join(
        f"<tr><td>{variant}</td><td>{html.escape(summary_text(payload['pre2026_selection'][variant]))}</td><td>{html.escape(summary_text(payload['post2026_test'][variant]))}</td><td>{html.escape(summary_text(payload['one_year_segments']['full'][variant]))}</td><td>{html.escape(summary_text(payload['one_year_segments']['test'][variant]))}</td></tr>"
        for variant in VARIANTS
    )
    year_rows = "".join(
        f"<tr><td>{year}</td>{''.join(f'<td>{html.escape(summary_text(results[variant]))}</td>' for variant in VARIANTS)}</tr>"
        for year, results in payload["three_year_by_year"].items()
    )
    trade_rows = "".join(
        f"<tr><td>{row['signal_date']}</td><td>{html.escape(str(row['stock_no'])+' '+str(row['stock_name']))}</td><td>{row['climax_score']}</td><td>{row['return_pct']:.2f}%</td><td>{row['return20_pct']:.2f}%</td><td>{row['weekly_momentum4_pct'] if row['weekly_momentum4_pct'] is not None else '-'}</td><td>{row['monthly_momentum3_pct'] if row['monthly_momentum3_pct'] is not None else '-'}</td></tr>"
        for row in sorted(payload["chosen_one_year_trades"], key=lambda item: item["signal_date"], reverse=True)
    )
    status = "留出測試達標" if payload["target_met_on_one_year_test"] else "留出測試未達標"
    tone = "pass" if payload["target_met_on_one_year_test"] else "fail"
    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PB-V11 滾動末升段濾網</title><style>
:root{{--bg:#f4f6f5;--paper:#fff;--ink:#17201d;--muted:#68736e;--line:#dce2df;--good:#08735d;--bad:#a33d31}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 system-ui,"Microsoft JhengHei",sans-serif}}header,main{{max-width:1480px;margin:auto;padding:26px 20px}}header{{border-bottom:1px solid var(--line)}}h1{{font-size:28px;letter-spacing:0;margin:0 0 7px}}h2{{font-size:19px;letter-spacing:0;margin:28px 0 10px}}p{{color:var(--muted)}}.status{{display:inline-block;padding:6px 10px;border:1px solid currentColor;font-weight:700}}.pass{{color:var(--good)}}.fail{{color:var(--bad)}}.note{{border-left:4px solid var(--good);background:#eef4f1;padding:12px 14px}}.table{{overflow:auto;background:var(--paper);border:1px solid var(--line)}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:left}}th{{font-size:12px;color:var(--muted);background:#eef1ef}}@media(max-width:760px){{header,main{{padding:18px 10px}}h1{{font-size:23px}}}}
</style></head><body><header><h1>PB-V11 滾動末升段濾網</h1><p>所有過熱門檻只來自該訊號之前最近 60 筆，不使用未來分布。</p><span class="status {tone}">{status}</span></header><main><div class="note"><strong>2024–2025 選出的強度：</strong>{payload['chosen_variant']}。分數包含日／週／月漲幅、MA60 乖離、ATR、末五日量比與回撤過淺。</div><h2>歷史選擇、2026 與一年留出比較</h2><div class="table"><table><thead><tr><th>版本</th><th>2026 前選擇區</th><th>2026 測試</th><th>完整一年</th><th>一年最後20%</th></tr></thead><tbody>{rows}</tbody></table></div><h2>擴充三年逐年</h2><div class="table"><table><thead><tr><th>年度</th>{''.join(f'<th>{variant}</th>' for variant in VARIANTS)}</tr></thead><tbody>{year_rows}</tbody></table></div><h2>選定版本一年交易</h2><div class="table"><table><thead><tr><th>訊號日</th><th>股票</th><th>過熱分</th><th>報酬</th><th>20日漲幅</th><th>4週漲幅</th><th>3月漲幅</th></tr></thead><tbody>{trade_rows}</tbody></table></div></main></body></html>"""


def main() -> None:
    payload = run()
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    print(json.dumps({
        "chosen_variant": payload["chosen_variant"],
        "pre2026_selection": payload["pre2026_selection"],
        "post2026_test": payload["post2026_test"],
        "one_year_full": payload["one_year_segments"]["full"],
        "one_year_test": payload["one_year_segments"]["test"],
        "target_met_on_one_year_test": payload["target_met_on_one_year_test"],
        "html": str(OUT_HTML),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
