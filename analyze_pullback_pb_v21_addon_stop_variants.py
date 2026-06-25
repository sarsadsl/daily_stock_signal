#!/usr/bin/env python3
"""PB-V21: add-on stop variants for main-wave pullback add-ons."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from analyze_pullback_multitimeframe_search import BENCHMARK_CSV, PBV4_JSON, add_benchmark_return
from analyze_pullback_pb_v19_main_wave_addon import POSITION_SIZE, source_base_exit, summarize_packages, summarize_units, unit_pnl
from analyze_pullback_pb_v20_fuzzy_addon import (
    find_next_addon,
    split_chronological,
    split_stocks,
)
from analyze_pullback_technical_phenotypes import find_series, make_series_map
from run_market_backtest import Row, csv_files, read_rows


REPORT_DIR = Path("reports")
OUT_JSON = REPORT_DIR / "pullback_pb_v21_addon_stop_variants.json"
OUT_HTML = REPORT_DIR / "pullback_pb_v21_addon_stop_variants.html"
VERSION = "PB-V21.0-addon-stop-variants"

ENTRY_VARIANT = {
    "entry_policy": "retest",
    "max_addons": 3,
    "delay_days": 0,
    "min_wait": 2,
    "max_wait": 8,
    "ma20_band_pct": 0.06,
    "min_spacing": 5,
}

STOP_VARIANTS = [
    {
        "id": "v20_retest_stop4",
        "label": "V20 對照：回測加碼 + 4% 盤中停損",
        "stop_type": "intraday",
        "stop_pct": 0.04,
    },
    {
        "id": "structure_close",
        "label": "結構停損：收盤跌破 MA20 或確認K低點",
        "stop_type": "structure_close",
        "catastrophic_stop_pct": 0.15,
        "grace_days": 0,
    },
    {
        "id": "structure_close_grace3",
        "label": "結構停損：前3天需同時跌破 MA20 與確認K低點",
        "stop_type": "structure_close",
        "catastrophic_stop_pct": 0.15,
        "grace_days": 3,
    },
    {
        "id": "hard_stop15",
        "label": "加碼 hard stop 放寬到 15%",
        "stop_type": "intraday",
        "stop_pct": 0.15,
    },
    {
        "id": "hard_stop15_ma20_close",
        "label": "15% hard stop + 收盤跌破 MA20 出場",
        "stop_type": "hard15_ma20_close",
        "stop_pct": 0.15,
    },
]


def return_result(entry: Row, observed: list[Row], price: float, reason: str, unresolved: bool = False) -> dict[str, Any]:
    ret = round((price / entry.open - 1) * 100, 2)
    return {
        "exit_date": observed[-1].date,
        "exit_price": round(price, 4),
        "holding_days": len(observed),
        "return_pct": ret,
        "pnl": unit_pnl(ret),
        "exit_reason": reason,
        "unresolved": unresolved,
    }


def intraday_exit(
    entry: Row,
    rows: list[Row],
    indicators: dict[str, list[float | None]],
    entry_index: int,
    stop_pct: float,
) -> dict[str, Any]:
    hard_stop = entry.open * (1 - stop_pct)
    observed: list[Row] = []
    for cursor in range(entry_index, len(rows)):
        row = rows[cursor]
        observed.append(row)
        if row.open <= hard_stop:
            return return_result(entry, observed, row.open, "gap_hard_stop")
        if row.low <= hard_stop:
            return return_result(entry, observed, hard_stop, "hard_stop")
        ma20 = indicators["ma20"][cursor]
        prior_ma20 = indicators["ma20"][cursor - 3] if cursor >= 3 else None
        if len(observed) >= 6 and ma20 and prior_ma20 and row.close < ma20 and ma20 <= prior_ma20:
            return return_result(entry, observed, row.close, "ma20_trend_break")
    return return_result(entry, observed, observed[-1].close, "latest_close", unresolved=True)


def structure_close_exit(
    entry: Row,
    rows: list[Row],
    indicators: dict[str, list[float | None]],
    entry_index: int,
    confirm_index: int,
    catastrophic_stop_pct: float,
    grace_days: int,
) -> dict[str, Any]:
    catastrophic = entry.open * (1 - catastrophic_stop_pct)
    confirm_low = rows[confirm_index].low
    observed: list[Row] = []
    for cursor in range(entry_index, len(rows)):
        row = rows[cursor]
        observed.append(row)
        if row.open <= catastrophic:
            return return_result(entry, observed, row.open, "gap_catastrophic_stop")
        if row.low <= catastrophic:
            return return_result(entry, observed, catastrophic, "catastrophic_stop")
        ma20 = indicators["ma20"][cursor]
        if ma20 is None:
            continue
        below_ma20 = row.close < ma20
        below_confirm = row.close < confirm_low
        in_grace = len(observed) <= grace_days
        if in_grace:
            if below_ma20 and below_confirm:
                return return_result(entry, observed, row.close, "grace_structure_break")
        elif below_ma20 or below_confirm:
            return return_result(entry, observed, row.close, "structure_close_break")
    return return_result(entry, observed, observed[-1].close, "latest_close", unresolved=True)


def hard15_ma20_close_exit(
    entry: Row,
    rows: list[Row],
    indicators: dict[str, list[float | None]],
    entry_index: int,
) -> dict[str, Any]:
    hard_stop = entry.open * 0.85
    observed: list[Row] = []
    for cursor in range(entry_index, len(rows)):
        row = rows[cursor]
        observed.append(row)
        if row.open <= hard_stop:
            return return_result(entry, observed, row.open, "gap_hard_stop15")
        if row.low <= hard_stop:
            return return_result(entry, observed, hard_stop, "hard_stop15")
        ma20 = indicators["ma20"][cursor]
        if len(observed) >= 3 and ma20 and row.close < ma20:
            return return_result(entry, observed, row.close, "ma20_close_break")
    return return_result(entry, observed, observed[-1].close, "latest_close", unresolved=True)


def addon_exit(
    entry: Row,
    rows: list[Row],
    indicators: dict[str, list[float | None]],
    entry_index: int,
    confirm_index: int,
    variant: dict[str, Any],
) -> dict[str, Any]:
    if variant["stop_type"] == "intraday":
        return intraday_exit(entry, rows, indicators, entry_index, float(variant["stop_pct"]))
    if variant["stop_type"] == "structure_close":
        return structure_close_exit(
            entry,
            rows,
            indicators,
            entry_index,
            confirm_index,
            float(variant["catastrophic_stop_pct"]),
            int(variant["grace_days"]),
        )
    if variant["stop_type"] == "hard15_ma20_close":
        return hard15_ma20_close_exit(entry, rows, indicators, entry_index)
    raise ValueError(f"unknown stop type {variant['stop_type']}")


def simulate_variant(
    source_trades: list[dict[str, Any]],
    series: dict[tuple[str, str], tuple[list[Row], dict[str, list[float | None]], dict[str, int]]],
    benchmark_rows: list[Row],
    benchmark_dates: dict[str, int],
    validation_start: str,
    test_start: str,
    stop_variant: dict[str, Any],
) -> dict[str, Any]:
    entry_variant = {**ENTRY_VARIANT, **stop_variant}
    units: list[dict[str, Any]] = []
    packages: list[dict[str, Any]] = []
    for source in source_trades:
        bundle = find_series(series, str(source["market"]), str(source["stock_no"]))
        if not bundle:
            continue
        rows, indicators, dates = bundle
        signal_index = dates.get(source["signal_date"])
        if signal_index is None or signal_index + 1 >= len(rows):
            continue
        base_entry_index = signal_index + 1
        base_entry = rows[base_entry_index]
        base_exit = source_base_exit(source)
        base_exit_index = dates.get(base_exit["exit_date"], len(rows) - 1)
        base_unit = {
            **source,
            "variant": stop_variant["id"],
            "unit_type": "base",
            "entry_date": base_entry.date,
            "entry_price": round(base_entry.open, 4),
            **base_exit,
        }
        add_benchmark_return(base_unit, benchmark_rows, benchmark_dates)
        units.append(base_unit)

        addon_units = []
        scan_start = base_entry_index
        for addon_number in range(1, int(entry_variant["max_addons"]) + 1):
            addon = find_next_addon(
                rows,
                indicators,
                signal_index,
                base_entry_index,
                scan_start,
                base_exit_index,
                benchmark_rows,
                benchmark_dates,
                entry_variant,
            )
            if not addon:
                break
            entry_index = addon["entry_index"]
            confirm_index = dates.get(addon["confirm_date"])
            if confirm_index is None:
                break
            entry = rows[entry_index]
            exit_data = addon_exit(entry, rows, indicators, entry_index, confirm_index, stop_variant)
            unit = {
                **source,
                "variant": stop_variant["id"],
                "unit_type": "addon",
                "addon_number": addon_number,
                "entry_date": entry.date,
                "entry_price": round(entry.open, 4),
                **addon,
                **exit_data,
            }
            add_benchmark_return(unit, benchmark_rows, benchmark_dates)
            units.append(unit)
            addon_units.append(unit)
            scan_start = entry_index + int(entry_variant["min_spacing"])

        total_pnl = base_unit["pnl"] + sum(row["pnl"] for row in addon_units)
        total_units = 1 + len(addon_units)
        packages.append({
            **source,
            "variant": stop_variant["id"],
            "base_return_pct": base_unit["return_pct"],
            "addon_count": len(addon_units),
            "addon_added": bool(addon_units),
            "total_units": total_units,
            "total_capital": total_units * POSITION_SIZE,
            "total_pnl": total_pnl,
            "package_return_pct": round(total_pnl / (total_units * POSITION_SIZE) * 100, 2),
            "unresolved": bool(base_unit.get("unresolved")) or any(row.get("unresolved") for row in addon_units),
        })

    chrono_units = split_chronological(units, validation_start, test_start)
    chrono_packages = split_chronological(packages, validation_start, test_start)
    stock_units, stock_counts = split_stocks(units)
    stock_packages, package_stock_counts = split_stocks(packages)
    addons = [row for row in units if row["unit_type"] == "addon"]
    washed = [row for row in addons if row["holding_days"] <= 10 and row["exit_reason"] not in {"latest_close", "ma20_trend_break"}]
    return {
        "variant": stop_variant,
        "summaries": {
            "chronological_unit": {name: summarize_units(rows) for name, rows in chrono_units.items()},
            "chronological_package": {name: summarize_packages(rows) for name, rows in chrono_packages.items()},
            "stock_unit": {name: summarize_units(rows) for name, rows in stock_units.items()},
            "stock_package": {name: summarize_packages(rows) for name, rows in stock_packages.items()},
            "base_units": summarize_units([row for row in units if row["unit_type"] == "base"]),
            "addon_units": summarize_units(addons),
            "washed_addons_le_10d": summarize_units(washed),
            "stock_counts": stock_counts,
            "package_stock_counts": package_stock_counts,
        },
        "units": units,
        "packages": packages,
    }


def run() -> dict[str, Any]:
    source_trades = json.loads(PBV4_JSON.read_text(encoding="utf-8"))["trades"]
    series = make_series_map(csv_files())
    benchmark_rows = read_rows(BENCHMARK_CSV)
    benchmark_dates = {row.date: index for index, row in enumerate(benchmark_rows)}
    v8 = json.loads((REPORT_DIR / "pullback_pb_v8_multitimeframe_search.json").read_text(encoding="utf-8"))
    validation_start = v8["split"]["validation_start"]
    test_start = v8["split"]["test_start"]
    variants = [
        simulate_variant(source_trades, series, benchmark_rows, benchmark_dates, validation_start, test_start, variant)
        for variant in STOP_VARIANTS
    ]
    return {
        "version": VERSION,
        "methodology": {
            "base": "PB-V4 broad discount-2 pullback base unit, one TWD 100,000 unit each",
            "addon_entry": "same as PB-V20 best direction: wait for MA20-near retest after main-wave confirmation; max three add-ons",
            "structure_stop": "structure variants do not exit on intraday MA20 breaks; they exit on close below MA20/confirm low, with an optional 3-day grace window",
            "hard_stop15": "separate variants test add-on hard stop widened to 15%",
            "validation": "both chronological forward slices and stock-level 60/20/20 holdout are reported",
        },
        "split": {"validation_start": validation_start, "test_start": test_start},
        "variants": variants,
    }


def compact(summary: dict[str, Any], key: str = "units") -> str:
    return (
        f"{summary.get(key, 0)}｜勝率 {summary['win_rate_pct']:.2f}%｜"
        f"平均 {summary['avg_return_pct']:.2f}%｜中位 {summary['median_return_pct']:.2f}%｜"
        f"損益 {summary['total_pnl']:,.0f}"
    )


def render_html(payload: dict[str, Any]) -> str:
    ranked = sorted(
        payload["variants"],
        key=lambda item: (
            item["summaries"]["stock_unit"]["stock_test"]["avg_return_pct"],
            item["summaries"]["stock_unit"]["stock_test"]["win_rate_pct"],
        ),
        reverse=True,
    )
    rows = "".join(
        f"<tr><th>{html.escape(item['variant']['label'])}</th>"
        f"<td>{html.escape(compact(item['summaries']['chronological_unit']['full']))}</td>"
        f"<td>{html.escape(compact(item['summaries']['stock_unit']['stock_test']))}</td>"
        f"<td>{html.escape(compact(item['summaries']['addon_units']))}</td>"
        f"<td>{html.escape(compact(item['summaries']['washed_addons_le_10d']))}</td></tr>"
        for item in ranked
    )
    best = ranked[0]
    top_addons = sorted(
        [row for row in best["units"] if row["unit_type"] == "addon"],
        key=lambda row: row["return_pct"],
        reverse=True,
    )[:30]
    addon_rows = "".join(
        f"<tr><td>{row['signal_date']}</td><td>{html.escape(str(row['stock_no']) + ' ' + str(row['stock_name']))}</td>"
        f"<td>{row['confirm_date']}</td><td>{row.get('entry_trigger_date')}</td><td>{row['entry_date']}</td>"
        f"<td>{html.escape(row.get('entry_trigger_type') or '')}</td>"
        f"<td class=\"num {'pos' if row['return_pct'] > 0 else 'neg'}\">{row['return_pct']:.2f}%</td>"
        f"<td>{row['exit_date']}</td><td>{html.escape(row['exit_reason'])}</td></tr>"
        for row in top_addons
    )
    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PB-V21 加碼停損變體</title><style>
:root{{--bg:#f6f7f4;--paper:#fff;--ink:#17211d;--muted:#65716b;--line:#dfe5df;--good:#08735d;--bad:#a13e34;--accent:#1f6a73}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 system-ui,"Microsoft JhengHei",sans-serif}}header,main{{max-width:1500px;margin:auto;padding:24px 16px}}header{{border-bottom:1px solid var(--line)}}h1{{margin:0 0 8px;font-size:28px}}h2{{font-size:19px;margin:28px 0 10px}}p{{margin:6px 0;color:var(--muted)}}.cards{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1px;background:var(--line);border:1px solid var(--line);margin-top:20px}}.card{{background:var(--paper);padding:16px}}.card b{{display:block;font-size:20px}}.note{{margin-top:16px;background:#ecf3f2;border-left:4px solid var(--accent);padding:12px 14px}}.table{{overflow:auto;border:1px solid var(--line);background:var(--paper)}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}thead th{{background:#eef1ee;color:var(--muted);font-size:12px}}.num{{text-align:right}}.pos{{color:var(--good);font-weight:800}}.neg{{color:var(--bad);font-weight:800}}code{{background:#eef1ee;padding:1px 4px;border-radius:4px}}@media(max-width:900px){{.cards{{grid-template-columns:1fr}}}}
</style></head><body><header><h1>PB-V21 加碼停損變體</h1><p>底倉維持 PB-V4，加碼進場沿用 PB-V20 的 MA20 回測方向；這次只測加碼單停損：結構停損、前3天寬限，以及 hard stop 放寬到 15%。</p><div class="cards"><div class="card"><span>股票測試最佳</span><b>{html.escape(best['variant']['label'])}</b><small>{html.escape(compact(best['summaries']['stock_unit']['stock_test']))}</small></div><div class="card"><span>全期</span><b>{best['summaries']['chronological_unit']['full']['avg_return_pct']:.2f}%</b><small>{best['summaries']['chronological_unit']['full']['units']} 份平均報酬</small></div><div class="card"><span>加碼單</span><b>{best['summaries']['addon_units']['win_rate_pct']:.2f}% / {best['summaries']['addon_units']['avg_return_pct']:.2f}%</b><small>{best['summaries']['addon_units']['units']} 份，勝率 / 平均</small></div></div><div class="note"><strong>判讀重點：</strong>結構停損用收盤確認，不因盤中跌破就出；15% hard stop 則測試是否能避免主升段早期震盪被洗掉。排序仍以股票 20% holdout 平均報酬為主。</div></header><main><h2>變體比較</h2><div class="table"><table><thead><tr><th>版本</th><th>全期單位</th><th>股票測試單位</th><th>加碼單</th><th>10日內洗出</th></tr></thead><tbody>{rows}</tbody></table></div><h2>股票測試最佳版本：加碼單前 30 名</h2><div class="table"><table><thead><tr><th>訊號日</th><th>股票</th><th>確認日</th><th>觸發日</th><th>加碼日</th><th>方式</th><th class="num">報酬</th><th>出場日</th><th>出場</th></tr></thead><tbody>{addon_rows}</tbody></table></div><p>輸出檔：<code>{OUT_JSON}</code>、<code>{OUT_HTML}</code></p></main></body></html>"""


def main() -> None:
    payload = run()
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    compact_output = []
    for item in payload["variants"]:
        compact_output.append({
            "id": item["variant"]["id"],
            "label": item["variant"]["label"],
            "full": item["summaries"]["chronological_unit"]["full"],
            "stock_test": item["summaries"]["stock_unit"]["stock_test"],
            "addons": item["summaries"]["addon_units"],
            "washed_le_10d": item["summaries"]["washed_addons_le_10d"],
        })
    print(json.dumps({"html": str(OUT_HTML), "json": str(OUT_JSON), "variants": compact_output}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
