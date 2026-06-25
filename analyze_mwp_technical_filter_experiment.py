#!/usr/bin/env python3
"""Technical filter experiment for return-first capped add-on strategy."""

from __future__ import annotations

import html
import json
import math
import statistics
from pathlib import Path
from typing import Any, Callable

FilterPredicate = Callable[[dict[str, Any], dict[tuple[str, str, str], dict[str, Any]], list[dict[str, Any]]], bool]

import analyze_pullback_pb_v23_independent_lifecycle as pbv23
from analyze_mwp_addon_strategy_comparison import randomized_stats, strategy_record, strip_heavy
from analyze_pullback_pb_v19_main_wave_addon import summarize_packages, summarize_units

REPORT_DIR = Path("reports")
OUT_JSON = REPORT_DIR / "mwp_technical_filter_experiment.json"
OUT_HTML = REPORT_DIR / "mwp_technical_filter_experiment.html"
OUT_MD = REPORT_DIR / "mwp_technical_filter_experiment.md"
VERSION = "MWP-technical-filter-experiment"

BASE_VARIANT = {
    "id": "pbv23_max1_band19",
    "label": "PB-V23 capped baseline：最多加碼1次，MA20 band 1.9%",
    "max_addons": 1,
    "min_spacing": 5,
    "ma20_band_pct": 0.019,
}


def sma(values: list[float], window: int) -> list[float | None]:
    out: list[float | None] = []
    total = 0.0
    for index, value in enumerate(values):
        total += value
        if index >= window:
            total -= values[index - window]
        out.append(total / window if index + 1 >= window else None)
    return out


def ema(values: list[float], span: int) -> list[float | None]:
    out: list[float | None] = []
    alpha = 2 / (span + 1)
    current: float | None = None
    for index, value in enumerate(values):
        if current is None:
            if index + 1 < span:
                out.append(None)
                continue
            current = sum(values[index + 1 - span : index + 1]) / span
        else:
            current = value * alpha + current * (1 - alpha)
        out.append(current)
    return out


def rsi(values: list[float], window: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) <= window:
        return out
    gains: list[float] = []
    losses: list[float] = []
    for index in range(1, window + 1):
        delta = values[index] - values[index - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = sum(gains) / window
    avg_loss = sum(losses) / window
    out[window] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    for index in range(window + 1, len(values)):
        delta = values[index] - values[index - 1]
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        avg_gain = (avg_gain * (window - 1) + gain) / window
        avg_loss = (avg_loss * (window - 1) + loss) / window
        out[index] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    return out


def indicator_pack(rows: list[pbv23.Row]) -> dict[str, list[float | None]]:
    closes = [row.close for row in rows]
    volumes = [float(row.volume) for row in rows]
    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)
    macd_line: list[float | None] = []
    macd_values_for_signal: list[float] = []
    macd_signal: list[float | None] = []
    for fast, slow in zip(ema12, ema26):
        value = fast - slow if fast is not None and slow is not None else None
        macd_line.append(value)
        if value is None:
            macd_signal.append(None)
            continue
        macd_values_for_signal.append(value)
        if len(macd_values_for_signal) < 9:
            macd_signal.append(None)
        elif len(macd_values_for_signal) == 9:
            macd_signal.append(sum(macd_values_for_signal[-9:]) / 9)
        else:
            previous = macd_signal[-1]
            assert previous is not None
            macd_signal.append(value * (2 / 10) + previous * (1 - 2 / 10))
    macd_hist = [line - signal if line is not None and signal is not None else None for line, signal in zip(macd_line, macd_signal)]
    ma20 = sma(closes, 20)
    ma60 = sma(closes, 60)
    vol20 = sma(volumes, 20)
    return {
        "rsi14": rsi(closes, 14),
        "ema12": ema12,
        "ema26": ema26,
        "macd": macd_line,
        "macd_signal": macd_signal,
        "macd_hist": macd_hist,
        "ma20": ma20,
        "ma60": ma60,
        "vol20": vol20,
    }


def value_at(values: list[float | None], index: int, default: float | None = None) -> float | None:
    if index < 0 or index >= len(values):
        return default
    value = values[index]
    return value if value is not None and math.isfinite(value) else default


def build_features(packages: list[dict[str, Any]], series: dict[Any, Any]) -> dict[tuple[str, str, str], dict[str, Any]]:
    cache: dict[tuple[str, str], dict[str, Any]] = {}
    features: dict[tuple[str, str, str], dict[str, Any]] = {}
    for package in packages:
        market = str(package.get("market") or "").upper()
        stock_no = str(package.get("stock_no") or "")
        signal_date = str(package.get("signal_date") or "")
        bundle = pbv23.find_series(series, market, stock_no)
        if not bundle:
            continue
        rows, base_indicators, dates = bundle
        signal_index = dates.get(signal_date)
        entry_index = dates.get(str(package.get("entry_date"))) or (signal_index + 1 if signal_index is not None else None)
        if signal_index is None or entry_index is None:
            continue
        key2 = (market, stock_no)
        if key2 not in cache:
            cache[key2] = indicator_pack(rows)
        ind = cache[key2]
        row = rows[signal_index]
        entry_row = rows[entry_index]
        ma20 = value_at(ind["ma20"], signal_index)
        ma60 = value_at(ind["ma60"], signal_index)
        ma20_5 = value_at(ind["ma20"], signal_index - 5)
        ma60_10 = value_at(ind["ma60"], signal_index - 10)
        macd_hist = value_at(ind["macd_hist"], signal_index)
        macd_hist_1 = value_at(ind["macd_hist"], signal_index - 1)
        macd_hist_3 = value_at(ind["macd_hist"], signal_index - 3)
        macd_line = value_at(ind["macd"], signal_index)
        macd_signal = value_at(ind["macd_signal"], signal_index)
        rsi14 = value_at(ind["rsi14"], signal_index)
        vol20 = value_at(ind["vol20"], signal_index)
        prior_high20 = max(item.high for item in rows[max(0, signal_index - 19) : signal_index + 1])
        return20 = (row.close / rows[signal_index - 20].close - 1) * 100 if signal_index >= 20 else None
        features[(market, stock_no, signal_date)] = {
            "market": market,
            "stock_no": stock_no,
            "signal_date": signal_date,
            "rsi14": round(rsi14, 4) if rsi14 is not None else None,
            "macd": round(macd_line, 4) if macd_line is not None else None,
            "macd_signal": round(macd_signal, 4) if macd_signal is not None else None,
            "macd_hist": round(macd_hist, 4) if macd_hist is not None else None,
            "macd_hist_delta1": round(macd_hist - macd_hist_1, 4) if macd_hist is not None and macd_hist_1 is not None else None,
            "macd_hist_delta3": round(macd_hist - macd_hist_3, 4) if macd_hist is not None and macd_hist_3 is not None else None,
            "macd_above_signal": macd_line is not None and macd_signal is not None and macd_line > macd_signal,
            "macd_hist_positive": macd_hist is not None and macd_hist > 0,
            "ma20_slope5_pct": round((ma20 / ma20_5 - 1) * 100, 4) if ma20 and ma20_5 else None,
            "ma60_slope10_pct": round((ma60 / ma60_10 - 1) * 100, 4) if ma60 and ma60_10 else None,
            "close_vs_ma20_pct": round((row.close / ma20 - 1) * 100, 4) if ma20 else None,
            "close_vs_ma60_pct": round((row.close / ma60 - 1) * 100, 4) if ma60 else None,
            "entry_vs_ma20_pct": round((entry_row.open / ma20 - 1) * 100, 4) if ma20 else None,
            "volume_vs_vol20": round(row.volume / vol20, 4) if vol20 else None,
            "return20_pct": round(return20, 4) if return20 is not None else None,
            "near_high20_pct": round((row.close / prior_high20 - 1) * 100, 4) if prior_high20 else None,
        }
    return features


def lifecycle_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (str(row.get("market") or "").upper(), str(row.get("stock_no") or ""), str(row.get("signal_date") or ""))


def getf(features: dict[tuple[str, str, str], dict[str, Any]], package: dict[str, Any], name: str) -> Any:
    return features.get(lifecycle_key(package), {}).get(name)


def ge(name: str, threshold: float) -> Callable[[dict[str, Any], dict[tuple[str, str, str], dict[str, Any]], list[dict[str, Any]]], bool]:
    return lambda package, features, units: getf(features, package, name) is not None and getf(features, package, name) >= threshold


def le(name: str, threshold: float) -> Callable[[dict[str, Any], dict[tuple[str, str, str], dict[str, Any]], list[dict[str, Any]]], bool]:
    return lambda package, features, units: getf(features, package, name) is not None and getf(features, package, name) <= threshold


def between(name: str, low: float, high: float) -> Callable[[dict[str, Any], dict[tuple[str, str, str], dict[str, Any]], list[dict[str, Any]]], bool]:
    return lambda package, features, units: getf(features, package, name) is not None and low <= getf(features, package, name) <= high


def flag(name: str) -> Callable[[dict[str, Any], dict[tuple[str, str, str], dict[str, Any]], list[dict[str, Any]]], bool]:
    return lambda package, features, units: bool(getf(features, package, name))


def not_stop_loss_package(package: dict[str, Any], features: dict[Any, Any], units: list[dict[str, Any]]) -> bool:
    related = [row for row in units if lifecycle_key(row) == lifecycle_key(package)]
    return not any("hard_stop" in str(row.get("exit_reason") or "") or "catastrophic" in str(row.get("exit_reason") or "") for row in related)


def filter_record(
    label: str,
    packages: list[dict[str, Any]],
    units: list[dict[str, Any]],
    features: dict[tuple[str, str, str], dict[str, Any]],
    predicate: Callable[[dict[str, Any], dict[tuple[str, str, str], dict[str, Any]], list[dict[str, Any]]], bool],
) -> dict[str, Any]:
    selected_packages = [package for package in packages if predicate(package, features, units)]
    keys = {lifecycle_key(package) for package in selected_packages}
    selected_units = [unit for unit in units if lifecycle_key(unit) in keys]
    record = strategy_record(label, selected_units, selected_packages, "simulated technical filter")
    record["selected_lifecycles"] = len(selected_packages)
    record["selected_units"] = len(selected_units)
    record["excluded_lifecycles"] = len(packages) - len(selected_packages)
    record["excluded_units"] = len(units) - len(selected_units)
    stop_packages = [package for package in selected_packages if not not_stop_loss_package(package, features, units)]
    record["stop_loss_lifecycles"] = len(stop_packages)
    record["stop_loss_lifecycle_rate_pct"] = round(len(stop_packages) / max(1, len(selected_packages)) * 100, 2)
    record["score_return_then_quality"] = round(
        record["random_unit_stock_test"]["avg_return_pct"]["mean"]
        + 0.25 * record["random_unit_stock_test"]["avg_return_pct"]["p25"]
        + 0.08 * record["summary"]["full_units"]["win_rate_pct"]
        - 0.03 * record["stop_loss_lifecycle_rate_pct"],
        4,
    )
    return record


def describe_feature_splits(packages: list[dict[str, Any]], units: list[dict[str, Any]], features: dict[tuple[str, str, str], dict[str, Any]]) -> dict[str, Any]:
    stop_keys = {
        lifecycle_key(package)
        for package in packages
        if not not_stop_loss_package(package, features, units)
    }
    rows = []
    for name in ["rsi14", "macd_hist", "macd_hist_delta1", "macd_hist_delta3", "ma20_slope5_pct", "ma60_slope10_pct", "close_vs_ma20_pct", "close_vs_ma60_pct", "volume_vs_vol20", "return20_pct"]:
        stop_values = []
        non_stop_values = []
        for package in packages:
            value = getf(features, package, name)
            if value is None:
                continue
            if lifecycle_key(package) in stop_keys:
                stop_values.append(float(value))
            else:
                non_stop_values.append(float(value))
        rows.append({
            "feature": name,
            "stop_count": len(stop_values),
            "non_stop_count": len(non_stop_values),
            "stop_mean": round(statistics.mean(stop_values), 4) if stop_values else None,
            "non_stop_mean": round(statistics.mean(non_stop_values), 4) if non_stop_values else None,
            "stop_median": round(statistics.median(stop_values), 4) if stop_values else None,
            "non_stop_median": round(statistics.median(non_stop_values), 4) if non_stop_values else None,
        })
    return {"rows": rows, "stop_lifecycles": len(stop_keys), "total_lifecycles": len(packages)}


def simulate_baseline() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[Any, Any]]:
    source_trades = json.loads(pbv23.PBV4_JSON.read_text(encoding="utf-8"))["trades"]
    series = pbv23.make_series_map(pbv23.csv_files())
    benchmark_rows = pbv23.read_rows(pbv23.BENCHMARK_CSV)
    benchmark_dates = {row.date: index for index, row in enumerate(benchmark_rows)}
    v8 = json.loads((REPORT_DIR / "pullback_pb_v8_multitimeframe_search.json").read_text(encoding="utf-8"))
    result = pbv23.simulate_variant(
        source_trades,
        series,
        benchmark_rows,
        benchmark_dates,
        v8["split"]["validation_start"],
        v8["split"]["test_start"],
        BASE_VARIANT,
    )
    return result["units"], result["packages"], series


def candidate_filters() -> list[tuple[str, FilterPredicate]]:
    filters: list[tuple[str, FilterPredicate]] = [
        ("baseline：不加技術濾網", lambda package, features, units: True),
        ("RSI14 >= 45", ge("rsi14", 45)),
        ("RSI14 >= 50", ge("rsi14", 50)),
        ("RSI14 >= 55", ge("rsi14", 55)),
        ("RSI14 45~75", between("rsi14", 45, 75)),
        ("MACD hist > 0", flag("macd_hist_positive")),
        ("MACD line > signal", flag("macd_above_signal")),
        ("MACD hist 改善1日", ge("macd_hist_delta1", 0)),
        ("MACD hist 改善3日", ge("macd_hist_delta3", 0)),
        ("MA20斜率5日 > 0", ge("ma20_slope5_pct", 0)),
        ("MA60斜率10日 > 0", ge("ma60_slope10_pct", 0)),
        ("收盤站上MA20", ge("close_vs_ma20_pct", 0)),
        ("收盤站上MA60", ge("close_vs_ma60_pct", 0)),
        ("量能 <= 2倍20日均量", le("volume_vs_vol20", 2.0)),
        ("20日漲幅 >= 0", ge("return20_pct", 0)),
        ("20日漲幅 >= 5", ge("return20_pct", 5)),
    ]
    def both(a, b):
        return lambda package, features, units: a(package, features, units) and b(package, features, units)
    combo_specs = [
        ("RSI>=50 + MACD hist>0", ge("rsi14", 50), flag("macd_hist_positive")),
        ("RSI>=50 + MACD改善1日", ge("rsi14", 50), ge("macd_hist_delta1", 0)),
        ("RSI>=50 + MA20斜率>0", ge("rsi14", 50), ge("ma20_slope5_pct", 0)),
        ("MACD hist>0 + MA20斜率>0", flag("macd_hist_positive"), ge("ma20_slope5_pct", 0)),
        ("MACD改善1日 + MA20斜率>0", ge("macd_hist_delta1", 0), ge("ma20_slope5_pct", 0)),
        ("RSI>=50 + MACD hist>0 + MA20斜率>0", both(ge("rsi14", 50), flag("macd_hist_positive")), ge("ma20_slope5_pct", 0)),
        ("RSI>=45 + MACD改善1日 + MA20斜率>0", both(ge("rsi14", 45), ge("macd_hist_delta1", 0)), ge("ma20_slope5_pct", 0)),
        ("RSI>=50 + 20日漲幅>=0", ge("rsi14", 50), ge("return20_pct", 0)),
    ]
    filters.extend((label, both(first, second)) for label, first, second in combo_specs)
    return filters


def fmt_pct(value: Any) -> str:
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return "-"


def row_html(record: dict[str, Any]) -> str:
    full = record["summary"]["full_units"]
    random_unit = record["random_unit_stock_test"]
    return (
        f"<tr><th>{html.escape(record['label'])}</th>"
        f"<td>{record['selected_units']}</td>"
        f"<td>{record['selected_lifecycles']}</td>"
        f"<td>{fmt_pct(full['win_rate_pct'])}</td>"
        f"<td>{fmt_pct(full['avg_return_pct'])}</td>"
        f"<td>{fmt_pct(random_unit['avg_return_pct']['mean'])}</td>"
        f"<td>{fmt_pct(random_unit['avg_return_pct']['p25'])}</td>"
        f"<td>{fmt_pct(random_unit['win_rate_pct']['mean'])}</td>"
        f"<td>{fmt_pct(record['stop_loss_lifecycle_rate_pct'])}</td>"
        f"<td>{record['summary']['lifecycle_violations']}</td></tr>"
    )


def render_html(payload: dict[str, Any]) -> str:
    rows = "".join(row_html(record) for record in payload["filters"])
    best = payload["best_return_then_quality"]
    feature_rows = "".join(
        f"<tr><th>{html.escape(row['feature'])}</th><td>{row['stop_count']}</td><td>{row['non_stop_count']}</td><td>{row['stop_median']}</td><td>{row['non_stop_median']}</td><td>{row['stop_mean']}</td><td>{row['non_stop_mean']}</td></tr>"
        for row in payload["feature_diagnostics"]["rows"]
    )
    return f"""<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{VERSION}</title><style>
:root{{--bg:#f6f7fb;--paper:#fff;--ink:#172033;--muted:#667085;--line:#e4e7ec;--blue:#2563eb}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 system-ui,'Microsoft JhengHei',sans-serif}}header,main{{max-width:1600px;margin:auto;padding:28px 20px}}header{{border-bottom:1px solid var(--line)}}h1{{margin:0 0 8px;font-size:30px}}p{{color:var(--muted)}}.note{{border-left:4px solid var(--blue);background:#eff6ff;padding:12px 14px;margin:18px 0;border-radius:12px}}.table{{overflow:auto;border:1px solid var(--line);background:#fff;border-radius:12px;margin:18px 0}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:right;vertical-align:top}}th:first-child,td:first-child{{text-align:left;min-width:300px}}thead th{{background:#f8fafc;color:var(--muted);font-size:12px}}code{{background:#eef2ff;padding:2px 6px;border-radius:6px}}
</style></head><body><header><h1>{VERSION}</h1><p>以 PB-V23 capped baseline（最多加碼1次，MA20 band 1.9%，299 units）測試 RSI / MACD / 均線斜率等技術濾網。</p><div class='note'><strong>目前最佳平衡濾網：</strong>{html.escape(best['label'])}。Random unit 平均報酬 {fmt_pct(best['random_unit_stock_test']['avg_return_pct']['mean'])}，p25 {fmt_pct(best['random_unit_stock_test']['avg_return_pct']['p25'])}，Full 勝率 {fmt_pct(best['summary']['full_units']['win_rate_pct'])}，停損生命週期率 {fmt_pct(best['stop_loss_lifecycle_rate_pct'])}。</div></header><main><h2>濾網結果</h2><div class='table'><table><thead><tr><th>濾網</th><th>units</th><th>生命週期</th><th>Full勝率</th><th>Full平均</th><th>Random平均</th><th>Random p25</th><th>Random勝率</th><th>停損生命週期率</th><th>違規</th></tr></thead><tbody>{rows}</tbody></table></div><h2>停損 vs 非停損特徵診斷</h2><div class='table'><table><thead><tr><th>特徵</th><th>停損數</th><th>非停損數</th><th>停損中位</th><th>非停損中位</th><th>停損均值</th><th>非停損均值</th></tr></thead><tbody>{feature_rows}</tbody></table></div><p>JSON: <code>{OUT_JSON}</code>｜MD: <code>{OUT_MD}</code></p></main></body></html>"""


def md_row(record: dict[str, Any]) -> str:
    full = record["summary"]["full_units"]
    random_unit = record["random_unit_stock_test"]
    return f"| {record['label']} | {record['selected_units']} | {record['selected_lifecycles']} | {fmt_pct(full['win_rate_pct'])} | {fmt_pct(full['avg_return_pct'])} | {fmt_pct(random_unit['avg_return_pct']['mean'])} | {fmt_pct(random_unit['avg_return_pct']['p25'])} | {fmt_pct(random_unit['win_rate_pct']['mean'])} | {fmt_pct(record['stop_loss_lifecycle_rate_pct'])} |"


def render_md(payload: dict[str, Any]) -> str:
    lines = [
        f"# {VERSION}",
        "",
        "以 PB-V23 capped baseline（最多加碼1次，MA20 band 1.9%，299 units）測試 RSI / MACD / 均線斜率等技術濾網。",
        "",
        "| 濾網 | units | 生命週期 | Full勝率 | Full平均 | Random平均 | Random p25 | Random勝率 | 停損生命週期率 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    lines.extend(md_row(record) for record in payload["filters"])
    best = payload["best_return_then_quality"]
    lines.extend([
        "",
        f"最佳平衡濾網：{best['label']}",
        f"Random unit 平均報酬：{fmt_pct(best['random_unit_stock_test']['avg_return_pct']['mean'])}",
        f"Random unit p25：{fmt_pct(best['random_unit_stock_test']['avg_return_pct']['p25'])}",
        f"Full 勝率：{fmt_pct(best['summary']['full_units']['win_rate_pct'])}",
        f"停損生命週期率：{fmt_pct(best['stop_loss_lifecycle_rate_pct'])}",
    ])
    return "\n".join(lines) + "\n"


def main() -> None:
    units, packages, series = simulate_baseline()
    features = build_features(packages, series)
    records = [filter_record(label, packages, units, features, predicate) for label, predicate in candidate_filters()]
    records.sort(
        key=lambda row: (
            -float(row["score_return_then_quality"]),
            -float(row["random_unit_stock_test"]["avg_return_pct"]["mean"]),
            -float(row["summary"]["full_units"]["win_rate_pct"]),
        )
    )
    public_records = [strip_heavy(record) for record in records]
    payload = {
        "version": VERSION,
        "base_variant": BASE_VARIANT,
        "methodology": {
            "filter_level": "Filter whole mother lifecycle/package, then include all base/add-on units belonging to selected lifecycles.",
            "random_stock_splits": "10 stock-code random 60/20/20 splits, same helper as other MWP comparison reports.",
            "technical_features": "RSI14, MACD line/signal/histogram, MACD histogram delta, MA20/MA60 slopes, price vs MA, volume vs 20-day volume, 20-day return, all measured on signal date.",
        },
        "feature_diagnostics": describe_feature_splits(packages, units, features),
        "filters": public_records,
    }
    payload["best_return_then_quality"] = max(
        [row for row in public_records if row["selected_units"] >= 120],
        key=lambda row: row["score_return_then_quality"],
    )
    payload["best_random_avg"] = max(
        [row for row in public_records if row["selected_units"] >= 120],
        key=lambda row: row["random_unit_stock_test"]["avg_return_pct"]["mean"],
    )
    payload["baseline"] = next(row for row in public_records if row["label"].startswith("baseline"))
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    OUT_MD.write_text(render_md(payload), encoding="utf-8")
    print(json.dumps({
        "version": VERSION,
        "baseline": {
            "units": payload["baseline"]["selected_units"],
            "full_win": payload["baseline"]["summary"]["full_units"]["win_rate_pct"],
            "random_avg": payload["baseline"]["random_unit_stock_test"]["avg_return_pct"]["mean"],
            "stop_rate": payload["baseline"]["stop_loss_lifecycle_rate_pct"],
        },
        "best_return_then_quality": {
            "label": payload["best_return_then_quality"]["label"],
            "units": payload["best_return_then_quality"]["selected_units"],
            "full_win": payload["best_return_then_quality"]["summary"]["full_units"]["win_rate_pct"],
            "full_avg": payload["best_return_then_quality"]["summary"]["full_units"]["avg_return_pct"],
            "random_avg": payload["best_return_then_quality"]["random_unit_stock_test"]["avg_return_pct"]["mean"],
            "random_p25": payload["best_return_then_quality"]["random_unit_stock_test"]["avg_return_pct"]["p25"],
            "random_win": payload["best_return_then_quality"]["random_unit_stock_test"]["win_rate_pct"]["mean"],
            "stop_rate": payload["best_return_then_quality"]["stop_loss_lifecycle_rate_pct"],
        },
        "top_filters": [
            {
                "label": row["label"],
                "units": row["selected_units"],
                "full_win": row["summary"]["full_units"]["win_rate_pct"],
                "full_avg": row["summary"]["full_units"]["avg_return_pct"],
                "random_avg": row["random_unit_stock_test"]["avg_return_pct"]["mean"],
                "random_p25": row["random_unit_stock_test"]["avg_return_pct"]["p25"],
                "random_win": row["random_unit_stock_test"]["win_rate_pct"]["mean"],
                "stop_rate": row["stop_loss_lifecycle_rate_pct"],
            }
            for row in public_records[:10]
        ],
        "html": str(OUT_HTML),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
