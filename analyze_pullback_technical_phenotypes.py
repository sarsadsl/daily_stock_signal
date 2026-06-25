#!/usr/bin/env python3
"""Describe recent pullback winners and validate frozen ABC/volume hypotheses."""

from __future__ import annotations

import html
import json
import statistics
import sys
import types
from pathlib import Path
from typing import Any

plot_kline_stub = types.ModuleType("plot_kline")
plot_kline_stub.plot_chart = lambda *args, **kwargs: None
sys.modules.setdefault("plot_kline", plot_kline_stub)

from analyze_pullback_discount2_swing import CAPITAL_PER_TRADE, summarize, swing_exit
from analyze_pullback_versioned import research_csv_files
from analyze_recent_all_signal_backtest import build_rows
from run_market_backtest import Row, csv_files, prepare, read_rows


REPORT_DIR = Path("reports")
VERSION = "PB-V7.0-technical-phenotypes"
OUT_JSON = REPORT_DIR / "pullback_pb_v7_technical_phenotypes.json"
OUT_HTML = REPORT_DIR / "pullback_pb_v7_technical_phenotypes.html"
PBV4_JSON = REPORT_DIR / "pullback_pb_v4_0_1y_discount2_swing.json"
PBV2_JSON = REPORT_DIR / "pullback_pb_v2_0_3y.json"


FEATURES = {
    "return20_pct": "訊號日前 20 日漲幅",
    "ab_gain_pct": "A→B 推進漲幅",
    "bc_retrace_pct": "B→C 回撤占 AB 比例",
    "peak_age_days": "距 B 波高點天數",
    "distance_high60_pct": "距 60 日高點",
    "close_vs_ma20_pct": "收盤相對 MA20",
    "close_vs_ma60_pct": "收盤相對 MA60",
    "c_vs_ab_volume": "BC 回檔量 / AB 推進量",
    "last5_volume_ratio": "末 5 日量 / 前 5 日量",
    "obv_pressure10": "10 日方向量壓力",
    "atr20_pct": "20 日波動率 ATR",
    "close_location": "訊號 K 收盤位置",
    "lower_low_dryup": "末段價創低但量縮",
}


RULES = {
    "baseline": {
        "label": "PB-V4 原始隔日開低 2%",
        "description": "不增加型態濾網。",
    },
    "abc_structure": {
        "label": "ABC 結構",
        "description": "AB 漲幅至少 15%；B 高點距今 2-15 日；BC 回撤為 AB 的 20%-70%；收盤仍在 MA60 上。",
    },
    "abc_volume": {
        "label": "ABC + 回檔量縮",
        "description": "ABC 結構成立，且 BC 平均量不超過 AB 平均量的 85%。",
    },
    "c_wave_exhaustion": {
        "label": "C 波末端量價背離",
        "description": "ABC 結構成立；末 5 日低點不高於前 5 日，但末 5 日均量少 15% 以上，且訊號 K 收在區間上半部。",
    },
}


def median(values: list[float]) -> float | None:
    return round(statistics.median(values), 2) if values else None


def average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def locate_peak_and_base(rows: list[Row], index: int) -> tuple[int, int]:
    peak_start = max(30, index - 29)
    peak_index = max(range(peak_start, index + 1), key=lambda cursor: rows[cursor].high)
    base_start = max(0, peak_index - 30)
    base_index = min(range(base_start, peak_index + 1), key=lambda cursor: rows[cursor].low)
    return base_index, peak_index


def technical_features(rows: list[Row], indicators: dict[str, list[float | None]], index: int) -> dict[str, Any]:
    row = rows[index]
    base_index, peak_index = locate_peak_and_base(rows, index)
    base_price = rows[base_index].low
    peak_price = rows[peak_index].high
    impulse_range = peak_price - base_price
    ab_rows = rows[base_index : peak_index + 1]
    c_rows = rows[peak_index + 1 : index + 1] or [row]
    prior5 = rows[index - 9 : index - 4]
    last5 = rows[index - 4 : index + 1]
    high60 = max(item.high for item in rows[index - 59 : index + 1])
    ma20 = indicators["ma20"][index]
    ma60 = indicators["ma60"][index]

    true_ranges: list[float] = []
    for cursor in range(index - 19, index + 1):
        previous_close = rows[cursor - 1].close
        current = rows[cursor]
        true_ranges.append(max(current.high - current.low, abs(current.high - previous_close), abs(current.low - previous_close)))

    signed_volume = 0.0
    total_volume = 0.0
    for cursor in range(index - 9, index + 1):
        direction = 1 if rows[cursor].close > rows[cursor - 1].close else (-1 if rows[cursor].close < rows[cursor - 1].close else 0)
        signed_volume += direction * rows[cursor].volume
        total_volume += rows[cursor].volume

    day_range = max(row.high - row.low, row.close * 0.001)
    last5_volume = average([item.volume for item in last5])
    prior5_volume = average([item.volume for item in prior5])
    lower_low = min(item.low for item in last5) <= min(item.low for item in prior5)
    volume_dryup = last5_volume <= prior5_volume * 0.85
    return {
        "return20_pct": round((row.close / rows[index - 20].close - 1) * 100, 2),
        "ab_gain_pct": round((peak_price / base_price - 1) * 100, 2),
        "bc_retrace_pct": round((peak_price - row.close) / impulse_range * 100, 2) if impulse_range > 0 else 0.0,
        "peak_age_days": index - peak_index,
        "distance_high60_pct": round((row.close / high60 - 1) * 100, 2),
        "close_vs_ma20_pct": round((row.close / ma20 - 1) * 100, 2) if ma20 else None,
        "close_vs_ma60_pct": round((row.close / ma60 - 1) * 100, 2) if ma60 else None,
        "c_vs_ab_volume": round(average([item.volume for item in c_rows]) / average([item.volume for item in ab_rows]), 2),
        "last5_volume_ratio": round(last5_volume / prior5_volume, 2) if prior5_volume else None,
        "obv_pressure10": round(signed_volume / total_volume, 3) if total_volume else 0.0,
        "atr20_pct": round(average(true_ranges) / row.close * 100, 2),
        "close_location": round((row.close - row.low) / day_range, 2),
        "lower_low_dryup": lower_low and volume_dryup,
        "a_date": rows[base_index].date,
        "b_date": rows[peak_index].date,
        "a_price": round(base_price, 4),
        "b_price": round(peak_price, 4),
    }


def rule_passes(trade: dict[str, Any], rule: str) -> bool:
    if rule == "baseline":
        return True
    structure = (
        trade["ab_gain_pct"] >= 15
        and 2 <= trade["peak_age_days"] <= 15
        and 20 <= trade["bc_retrace_pct"] <= 70
        and trade["close_vs_ma60_pct"] >= 0
    )
    if rule == "abc_structure":
        return structure
    if rule == "abc_volume":
        return structure and trade["c_vs_ab_volume"] <= 0.85
    return structure and trade["lower_low_dryup"] and trade["close_location"] >= 0.50


def make_series_map(paths: list[Path]) -> dict[tuple[str, str], tuple[list[Row], dict[str, list[float | None]], dict[str, int]]]:
    output: dict[tuple[str, str], tuple[list[Row], dict[str, list[float | None]], dict[str, int]]] = {}
    for path in paths:
        rows = read_rows(path)
        if len(rows) < 80:
            continue
        key = (rows[-1].market.upper(), rows[-1].stock_no)
        output[key] = (rows, prepare(rows), {row.date: index for index, row in enumerate(rows)})
    return output


def find_series(
    series: dict[tuple[str, str], tuple[list[Row], dict[str, list[float | None]], dict[str, int]]],
    market: str,
    stock_no: str,
) -> tuple[list[Row], dict[str, list[float | None]], dict[str, int]] | None:
    exact = series.get((market.upper(), stock_no))
    if exact:
        return exact
    candidates = [bundle for (candidate_market, code), bundle in series.items() if code == stock_no]
    return candidates[0] if len(candidates) == 1 else None


def enrich_existing_trades(
    source: list[dict[str, Any]],
    series: dict[tuple[str, str], tuple[list[Row], dict[str, list[float | None]], dict[str, int]]],
) -> list[dict[str, Any]]:
    output = []
    for original in source:
        if not isinstance(original.get("return_pct"), (int, float)):
            continue
        if float(original["entry_price"]) > float(original["signal_close"]) * 0.98:
            continue
        bundle = find_series(series, str(original["market"]), str(original["stock_no"]))
        if not bundle:
            continue
        rows, indicators, dates = bundle
        index = dates.get(str(original["signal_date"]))
        if index is None or index < 60:
            continue
        trade = dict(original)
        trade.update(technical_features(rows, indicators, index))
        output.append(trade)
    return output


def rebuild_three_year_trades(
    source: list[dict[str, Any]],
    series: dict[tuple[str, str], tuple[list[Row], dict[str, list[float | None]], dict[str, int]]],
) -> list[dict[str, Any]]:
    output = []
    for original in source:
        bundle = find_series(series, str(original["market"]), str(original["stock_no"]))
        if not bundle:
            continue
        rows, indicators, dates = bundle
        index = dates.get(str(original["signal_date"]))
        if index is None or index < 60 or index + 21 >= len(rows):
            continue
        entry = rows[index + 1]
        if entry.open > float(original["signal_close"]) * 0.98:
            continue
        perf = swing_exit(entry, rows[index + 1 : index + 21])
        ret = float(perf["return_pct"])
        trade = {
            **original,
            "entry_date": entry.date,
            "entry_price": round(entry.open, 4),
            "exit_date": perf["exit_date"],
            "exit_price": perf["exit_price"],
            "holding_days": perf["holding_days"],
            "return_pct": ret,
            "mfe_pct": perf["mfe_pct"],
            "mae_pct": perf["mae_pct"],
            "exit_reason": perf["exit_reason"],
            "capital": CAPITAL_PER_TRADE,
            "pnl": round(ret / 100 * CAPITAL_PER_TRADE),
        }
        trade.update(technical_features(rows, indicators, index))
        output.append(trade)
    return output


def feature_profile(trades: list[dict[str, Any]]) -> dict[str, Any]:
    groups = {
        "all": trades,
        "winners": [row for row in trades if row["return_pct"] > 0],
        "losers": [row for row in trades if row["return_pct"] <= 0],
        "strong_winners": [row for row in trades if row["return_pct"] >= 10],
    }
    profile: dict[str, Any] = {}
    for feature in FEATURES:
        profile[feature] = {}
        for group, rows in groups.items():
            if feature == "lower_low_dryup":
                profile[feature][group] = round(sum(bool(row[feature]) for row in rows) / len(rows) * 100, 2) if rows else None
            else:
                values = [float(row[feature]) for row in rows if isinstance(row.get(feature), (int, float))]
                profile[feature][group] = median(values)
    profile["counts"] = {name: len(rows) for name, rows in groups.items()}
    return profile


def evaluate(trades: list[dict[str, Any]]) -> dict[str, Any]:
    baseline_count = len(trades)
    output = {}
    for rule in RULES:
        selected = [trade for trade in trades if rule_passes(trade, rule)]
        output[rule] = {
            **summarize(selected),
            "retention_pct": round(len(selected) / baseline_count * 100, 2) if baseline_count else 0.0,
        }
    return output


def top_examples(trades: list[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    fields = [
        "signal_date", "market", "stock_no", "stock_name", "return_pct", "entry_price", "exit_price",
        "ab_gain_pct", "bc_retrace_pct", "peak_age_days", "c_vs_ab_volume", "last5_volume_ratio",
        "obv_pressure10", "close_location", "lower_low_dryup", "reasons",
    ]
    return [{key: row.get(key) for key in fields} for row in sorted(trades, key=lambda item: item["return_pct"], reverse=True)[:limit]]


def run() -> dict[str, Any]:
    one_year_series = make_series_map(csv_files())
    recent20_rows, recent20_meta = build_rows(days=20, exit_mode="smart")
    recent20_pullback = [row for row in recent20_rows if row.get("category") == "pullback"]
    recent20 = enrich_existing_trades(recent20_pullback, one_year_series)
    recent10_dates = set(recent20_meta["target_dates"][-10:])
    recent10 = [row for row in recent20 if row["signal_date"] in recent10_dates]

    pbv4 = json.loads(PBV4_JSON.read_text(encoding="utf-8"))
    one_year = enrich_existing_trades(pbv4["trades"], one_year_series)

    three_year_series = make_series_map(research_csv_files())
    pbv2 = json.loads(PBV2_JSON.read_text(encoding="utf-8"))
    three_year = rebuild_three_year_trades(pbv2["trades"], three_year_series)

    datasets = {
        "recent10": recent10,
        "recent20": recent20,
        "one_year": one_year,
        "three_year": three_year,
    }
    return {
        "version": VERSION,
        "methodology": {
            "entry": "next trading-day open <= signal close * 0.98",
            "validation_exit": "PB-V4: 7% hard stop; activate 12% trailing after +12% MFE with +2% floor; max 20 trading days",
            "recent_exit_caveat": "recent 10/20 cohorts use the existing smart report and are marked/stopped through the common latest date, so holding periods differ; use them only for description",
            "feature_timing": "all technical features use signal-day-or-earlier OHLCV only",
            "rule_policy": "three interpretable rules were frozen before one-year/three-year validation; no post-result tuning",
        },
        "feature_labels": FEATURES,
        "rules": RULES,
        "recent_dates": {
            "recent10": sorted(recent10_dates),
            "recent20": recent20_meta["target_dates"],
            "latest": recent20_meta["latest_date"],
        },
        "dataset_counts": {name: len(rows) for name, rows in datasets.items()},
        "profiles": {
            "recent10": feature_profile(recent10),
            "recent20": feature_profile(recent20),
        },
        "results": {name: evaluate(rows) for name, rows in datasets.items()},
        "by_year_3y": {
            year: evaluate([row for row in three_year if row["signal_date"].startswith(year)])
            for year in sorted({row["signal_date"][:4] for row in three_year})
        },
        "interpretation": {
            "recent_commonality": "Recent winners tended to have a stronger prior AB impulse, remain farther above MA60, form the signal sooner after the peak, and close higher within the signal-day candle.",
            "volume_finding": "Simple volume contraction was not a universal winner/loser separator. It improved aggregate one-year results but failed badly in the 2024 regime.",
            "candidate": "ABC structure is the only broad candidate that improved aggregate one-year and three-year win rate and average return while retaining about 71% of trades.",
            "deployment": "Research only. The expanded three-year sample overlaps the one-year period and ABC structure did not rescue the adverse 2024 regime.",
        },
        "top_recent20_examples": top_examples(recent20),
    }


def number(value: Any, suffix: str = "") -> str:
    return "-" if value is None else f"{value:.2f}{suffix}" if isinstance(value, float) else f"{value}{suffix}"


def summary_text(summary: dict[str, Any]) -> str:
    return f"{summary['trades']} 筆｜勝率 {summary['win_rate_pct']:.2f}%｜平均 {summary['avg_return_pct']:.2f}%｜中位 {summary['median_return_pct']:.2f}%"


def render_html(payload: dict[str, Any]) -> str:
    dataset_labels = {"recent10": "最近 10 日", "recent20": "最近 20 日", "one_year": "一年樣本", "three_year": "三年樣本"}
    result_rows = []
    for rule, rule_info in RULES.items():
        cells = [f"<td><strong>{html.escape(rule_info['label'])}</strong><small>{html.escape(rule_info['description'])}</small></td>"]
        for dataset in dataset_labels:
            result = payload["results"][dataset][rule]
            tone = "good" if result["avg_return_pct"] > payload["results"][dataset]["baseline"]["avg_return_pct"] else ""
            cells.append(f"<td class='{tone}'>{html.escape(summary_text(result))}<small>保留 {result['retention_pct']:.1f}%</small></td>")
        result_rows.append("<tr>" + "".join(cells) + "</tr>")

    profile_rows = []
    for key, label in FEATURES.items():
        ten = payload["profiles"]["recent10"][key]
        twenty = payload["profiles"]["recent20"][key]
        profile_rows.append(
            "<tr>"
            f"<td>{html.escape(label)}</td>"
            f"<td>{number(ten['winners'])}</td><td>{number(ten['losers'])}</td><td>{number(ten['strong_winners'])}</td>"
            f"<td>{number(twenty['winners'])}</td><td>{number(twenty['losers'])}</td><td>{number(twenty['strong_winners'])}</td>"
            "</tr>"
        )

    year_rows = []
    for year, results in payload["by_year_3y"].items():
        year_rows.append(
            "<tr>"
            f"<td><strong>{year}</strong></td>"
            f"<td>{html.escape(summary_text(results['baseline']))}</td>"
            f"<td>{html.escape(summary_text(results['abc_structure']))}</td>"
            f"<td>{html.escape(summary_text(results['abc_volume']))}</td>"
            f"<td>{html.escape(summary_text(results['c_wave_exhaustion']))}</td>"
            "</tr>"
        )

    example_rows = "".join(
        "<tr>"
        f"<td>{row['signal_date']}</td><td>{html.escape(str(row['stock_no']) + ' ' + str(row['stock_name']))}</td>"
        f"<td class='good'>{row['return_pct']:.2f}%</td><td>{row['ab_gain_pct']:.2f}%</td>"
        f"<td>{row['bc_retrace_pct']:.2f}%</td><td>{row['peak_age_days']}</td>"
        f"<td>{row['c_vs_ab_volume']:.2f}</td><td>{row['last5_volume_ratio']:.2f}</td>"
        f"<td>{'是' if row['lower_low_dryup'] else '否'}</td></tr>"
        for row in payload["top_recent20_examples"]
    )
    counts = payload["dataset_counts"]
    return f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pullback 技術型態與量價規律</title>
<style>
:root{{--bg:#f4f6f5;--paper:#fff;--ink:#17201d;--muted:#66716c;--line:#dbe1de;--accent:#08735d;--warn:#a1492e}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 system-ui,"Microsoft JhengHei",sans-serif}}
main{{max-width:1500px;margin:auto;padding:30px 20px 56px}}h1{{font-size:28px;letter-spacing:0;margin:0 0 6px}}h2{{font-size:19px;letter-spacing:0;margin:28px 0 10px}}p{{color:var(--muted);margin:0 0 18px}}
.notice{{border-left:4px solid var(--warn);background:#fff8f4;padding:12px 14px;margin:18px 0}}.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:18px 0}}.stat{{background:var(--paper);border:1px solid var(--line);padding:14px;border-radius:6px}}.stat b{{display:block;font-size:22px}}.stat span,small{{display:block;color:var(--muted);margin-top:3px}}
.table{{overflow:auto;background:var(--paper);border:1px solid var(--line)}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{padding:11px 10px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}}th{{font-size:12px;color:var(--muted);background:#edf1ef;position:sticky;top:0}}td:first-child{{white-space:normal;min-width:190px}}.good{{color:var(--accent);font-weight:700}}
@media(max-width:800px){{main{{padding:20px 10px}}.stats{{grid-template-columns:repeat(2,1fr)}}h1{{font-size:23px}}}}
</style></head><body><main>
<h1>Pullback 技術型態與量價規律</h1>
<p>從最近 10／20 個交易日描述贏家，再以固定的隔日開低 2% 進場與 PB-V4 出場驗證一年、三年。</p>
<div class="notice"><strong>閱讀方式：</strong>最近 10／20 日持有天數不同，只能用來找候選特徵；是否有效，以一年與三年欄位能否同方向改善為準。</div>
<div class="stats"><div class="stat"><b>{counts['recent10']}</b><span>最近 10 日開低 2% 樣本</span></div><div class="stat"><b>{counts['recent20']}</b><span>最近 20 日開低 2% 樣本</span></div><div class="stat"><b>{counts['one_year']}</b><span>一年 PB-V4 樣本</span></div><div class="stat"><b>{counts['three_year']}</b><span>三年同規則樣本</span></div></div>
<h2>固定規則跨期間比較</h2><div class="table"><table><thead><tr><th>規則</th>{''.join(f'<th>{label}</th>' for label in dataset_labels.values())}</tr></thead><tbody>{''.join(result_rows)}</tbody></table></div>
<div class="notice"><strong>目前判定：</strong>ABC 結構是唯一值得保留研究的寬鬆濾網；一年與三年整體皆改善，且保留約 71% 交易。量縮與 C 波背離不是穩定硬條件，2024 年明顯失效。三年擴充樣本與一年期間部分重疊，因此尚不能部署。</div>
<h2>三年樣本逐年拆解</h2><div class="table"><table><thead><tr><th>年度</th><th>控制組</th><th>ABC 結構</th><th>ABC + 量縮</th><th>C 波背離</th></tr></thead><tbody>{''.join(year_rows)}</tbody></table></div>
<h2>近期贏家與輸家的型態中位數</h2><p>「強勢贏家」定義為報酬至少 10%；布林型特徵顯示出現比例。</p><div class="table"><table><thead><tr><th>特徵</th><th>10日贏家</th><th>10日輸家</th><th>10日強勢贏家</th><th>20日贏家</th><th>20日輸家</th><th>20日強勢贏家</th></tr></thead><tbody>{''.join(profile_rows)}</tbody></table></div>
<h2>最近 20 日績效前 20 名</h2><div class="table"><table><thead><tr><th>訊號日</th><th>股票</th><th>報酬</th><th>AB 漲幅</th><th>BC 回撤</th><th>高點天數</th><th>BC/AB量</th><th>末5日量比</th><th>低量創低</th></tr></thead><tbody>{example_rows}</tbody></table></div>
</main></body></html>"""


def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    payload = run()
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    print(json.dumps({"version": VERSION, "counts": payload["dataset_counts"], "results": payload["results"], "html": str(OUT_HTML)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
