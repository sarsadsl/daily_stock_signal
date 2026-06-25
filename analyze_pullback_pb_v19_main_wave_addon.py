#!/usr/bin/env python3
"""PB-V19: broad pullback base entry plus one equal-sized main-wave add-on."""

from __future__ import annotations

import html
import hashlib
import json
import statistics
from pathlib import Path
from typing import Any

from analyze_pullback_multitimeframe_search import BENCHMARK_CSV, PBV4_JSON, add_benchmark_return
from analyze_pullback_technical_phenotypes import find_series, make_series_map
from run_market_backtest import Row, csv_files, prepare, read_rows


REPORT_DIR = Path("reports")
OUT_JSON = REPORT_DIR / "pullback_pb_v19_main_wave_addon.json"
OUT_HTML = REPORT_DIR / "pullback_pb_v19_main_wave_addon.html"
VERSION = "PB-V19.0-main-wave-addon"
POSITION_SIZE = 100_000
HARD_STOP_PCT = 0.07
MIN_CORE_HOLD_DAYS = 10


def pct_return(exit_price: float, entry_price: float) -> float:
    return round((exit_price / entry_price - 1) * 100, 2)


def unit_pnl(return_pct: float) -> int:
    return round(return_pct / 100 * POSITION_SIZE)


def exit_result(
    entry: Row,
    observed: list[Row],
    price: float,
    reason: str,
    unresolved: bool = False,
) -> dict[str, Any]:
    ret = pct_return(price, entry.open)
    return {
        "exit_date": observed[-1].date,
        "exit_price": round(price, 4),
        "holding_days": len(observed),
        "return_pct": ret,
        "pnl": unit_pnl(ret),
        "exit_reason": reason,
        "unresolved": unresolved,
    }


def gap_aware_ma20_core_exit(
    entry: Row,
    rows: list[Row],
    indicators: dict[str, list[float | None]],
    entry_index: int,
) -> dict[str, Any]:
    hard_stop = entry.open * (1 - HARD_STOP_PCT)
    observed: list[Row] = []
    for cursor in range(entry_index, len(rows)):
        row = rows[cursor]
        observed.append(row)
        if row.open <= hard_stop:
            return exit_result(entry, observed, row.open, "gap_hard_stop")
        if row.low <= hard_stop:
            return exit_result(entry, observed, hard_stop, "hard_stop")
        ma20 = indicators["ma20"][cursor]
        prior_ma20 = indicators["ma20"][cursor - 3] if cursor >= 3 else None
        if len(observed) >= MIN_CORE_HOLD_DAYS and ma20 and prior_ma20:
            if row.close < ma20 and ma20 <= prior_ma20:
                return exit_result(entry, observed, row.close, "ma20_trend_break")
    return exit_result(entry, observed, observed[-1].close, "latest_close", unresolved=True)


def moving_average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def benchmark_return(
    benchmark_rows: list[Row],
    benchmark_dates: dict[str, int],
    entry_date: str,
    confirm_date: str,
) -> float | None:
    entry_index = benchmark_dates.get(entry_date)
    confirm_index = benchmark_dates.get(confirm_date)
    if entry_index is None or confirm_index is None:
        return None
    return (benchmark_rows[confirm_index].close / benchmark_rows[entry_index].open - 1) * 100


def confirmation_reason(
    rows: list[Row],
    indicators: dict[str, list[float | None]],
    signal_index: int,
    entry_index: int,
    cursor: int,
    benchmark_rows: list[Row],
    benchmark_dates: dict[str, int],
) -> str | None:
    row = rows[cursor]
    ma20 = indicators["ma20"][cursor]
    if ma20 is None or row.close <= ma20:
        return None
    prior_high20 = max(item.high for item in rows[max(0, signal_index - 19) : signal_index + 1])
    broke_signal_high = row.close > rows[signal_index].high
    broke_prior20_high = row.close > prior_high20
    if not (broke_signal_high or broke_prior20_high):
        return None
    vol20 = moving_average([item.volume for item in rows[max(0, cursor - 20) : cursor]])
    vol5 = moving_average([item.volume for item in rows[max(0, cursor - 5) : cursor]])
    if not ((vol20 and row.volume > vol20) or (vol5 and row.volume > vol5)):
        return None
    stock_return = (row.close / rows[entry_index].open - 1) * 100
    bench_return = benchmark_return(benchmark_rows, benchmark_dates, rows[entry_index].date, row.date)
    if bench_return is None or stock_return <= bench_return:
        return None
    reasons = ["close>MA20"]
    reasons.append("break_signal_high" if broke_signal_high else "break_prior20_high")
    reasons.append("volume_expand")
    reasons.append("stronger_than_0050")
    return "+".join(reasons)


def find_addon_entry(
    rows: list[Row],
    indicators: dict[str, list[float | None]],
    signal_index: int,
    entry_index: int,
    base_exit_index: int,
    benchmark_rows: list[Row],
    benchmark_dates: dict[str, int],
) -> dict[str, Any] | None:
    last_confirm_index = min(base_exit_index - 1, len(rows) - 2)
    for cursor in range(entry_index, last_confirm_index + 1):
        reason = confirmation_reason(
            rows, indicators, signal_index, entry_index, cursor, benchmark_rows, benchmark_dates
        )
        if not reason:
            continue
        addon_index = cursor + 1
        return {
            "confirm_date": rows[cursor].date,
            "confirm_close": round(rows[cursor].close, 4),
            "confirm_reason": reason,
            "addon_entry_index": addon_index,
            "addon_entry_date": rows[addon_index].date,
            "addon_entry_price": round(rows[addon_index].open, 4),
        }
    return None


def summarize_units(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(row["return_pct"]) for row in rows]
    if not values:
        return {
            "units": 0,
            "win_rate_pct": 0.0,
            "avg_return_pct": 0.0,
            "median_return_pct": 0.0,
            "total_pnl": 0,
            "capital_used": 0,
            "capital_return_pct": 0.0,
            "best_return_pct": 0.0,
            "worst_return_pct": 0.0,
            "unresolved": 0,
        }
    total_pnl = round(sum(row["pnl"] for row in rows))
    capital_used = len(rows) * POSITION_SIZE
    return {
        "units": len(rows),
        "win_rate_pct": round(sum(value > 0 for value in values) / len(values) * 100, 2),
        "avg_return_pct": round(sum(values) / len(values), 2),
        "median_return_pct": round(statistics.median(values), 2),
        "total_pnl": total_pnl,
        "capital_used": capital_used,
        "capital_return_pct": round(total_pnl / capital_used * 100, 2),
        "best_return_pct": round(max(values), 2),
        "worst_return_pct": round(min(values), 2),
        "unresolved": sum(bool(row.get("unresolved")) for row in rows),
    }


def summarize_packages(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(row["package_return_pct"]) for row in rows]
    if not values:
        return {
            "signals": 0,
            "addon_signals": 0,
            "addon_rate_pct": 0.0,
            "avg_return_pct": 0.0,
            "median_return_pct": 0.0,
            "win_rate_pct": 0.0,
            "total_pnl": 0,
            "capital_used": 0,
            "capital_return_pct": 0.0,
        }
    total_pnl = round(sum(row["total_pnl"] for row in rows))
    capital_used = round(sum(row["total_capital"] for row in rows))
    addon_count = sum(bool(row["addon_added"]) for row in rows)
    return {
        "signals": len(rows),
        "addon_signals": addon_count,
        "addon_rate_pct": round(addon_count / len(rows) * 100, 2),
        "avg_return_pct": round(sum(values) / len(values), 2),
        "median_return_pct": round(statistics.median(values), 2),
        "win_rate_pct": round(sum(value > 0 for value in values) / len(values) * 100, 2),
        "total_pnl": total_pnl,
        "capital_used": capital_used,
        "capital_return_pct": round(total_pnl / capital_used * 100, 2) if capital_used else 0.0,
    }


def split_rows(rows: list[dict[str, Any]], validation_start: str, test_start: str) -> dict[str, list[dict[str, Any]]]:
    return {
        "train": [row for row in rows if row["signal_date"] < validation_start],
        "validation": [row for row in rows if validation_start <= row["signal_date"] < test_start],
        "test": [row for row in rows if row["signal_date"] >= test_start],
        "full": rows,
        "resolved_full": [row for row in rows if not row.get("unresolved")],
    }


def stock_key(row: dict[str, Any]) -> str:
    return f"{row['market']}:{row['stock_no']}"


def stock_holdout_groups(rows: list[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
    stocks = sorted({stock_key(row) for row in rows})
    ranked = sorted(
        stocks,
        key=lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest(),
    )
    train_end = round(len(ranked) * 0.60)
    validation_end = round(len(ranked) * 0.80)
    buckets = {
        "stock_train": set(ranked[:train_end]),
        "stock_validation": set(ranked[train_end:validation_end]),
        "stock_test": set(ranked[validation_end:]),
    }
    grouped = {
        name: [row for row in rows if stock_key(row) in symbols]
        for name, symbols in buckets.items()
    }
    return grouped, {name: len(symbols) for name, symbols in buckets.items()}


def source_base_exit(source: dict[str, Any]) -> dict[str, Any]:
    ret = float(source["return_pct"])
    return {
        "exit_date": source["exit_date"],
        "exit_price": source["exit_price"],
        "holding_days": source["holding_days"],
        "return_pct": ret,
        "pnl": unit_pnl(ret),
        "exit_reason": source["exit_reason"],
        "unresolved": False,
    }


def simulate_mode(
    source_trades: list[dict[str, Any]],
    series: dict[tuple[str, str], tuple[list[Row], dict[str, list[float | None]], dict[str, int]]],
    benchmark_rows: list[Row],
    benchmark_dates: dict[str, int],
    validation_start: str,
    test_start: str,
    mode: str,
) -> dict[str, Any]:
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
        entry_index = signal_index + 1
        entry = rows[entry_index]
        base = source_base_exit(source) if mode == "v4_swing_base" else gap_aware_ma20_core_exit(entry, rows, indicators, entry_index)
        base_exit_index = dates.get(base["exit_date"], len(rows) - 1)
        base_unit = {
            **source,
            "mode": mode,
            "unit_type": "base",
            "entry_date": entry.date,
            "entry_price": round(entry.open, 4),
            **base,
        }
        base_unit["pnl"] = unit_pnl(base_unit["return_pct"])
        add_benchmark_return(base_unit, benchmark_rows, benchmark_dates)
        units.append(base_unit)
        addon = find_addon_entry(
            rows,
            indicators,
            signal_index,
            entry_index,
            base_exit_index,
            benchmark_rows,
            benchmark_dates,
        )
        addon_unit = None
        if addon:
            addon_entry = rows[addon["addon_entry_index"]]
            addon_exit = gap_aware_ma20_core_exit(
                addon_entry, rows, indicators, addon["addon_entry_index"]
            )
            addon_unit = {
                **source,
                "mode": mode,
                "unit_type": "addon",
                "entry_date": addon_entry.date,
                "entry_price": round(addon_entry.open, 4),
                **addon,
                **addon_exit,
            }
            addon_unit["pnl"] = unit_pnl(addon_unit["return_pct"])
            add_benchmark_return(addon_unit, benchmark_rows, benchmark_dates)
            units.append(addon_unit)
        total_pnl = base_unit["pnl"] + (addon_unit["pnl"] if addon_unit else 0)
        total_units = 1 + int(addon_unit is not None)
        packages.append({
            **source,
            "mode": mode,
            "base_return_pct": base_unit["return_pct"],
            "base_exit_date": base_unit["exit_date"],
            "base_exit_reason": base_unit["exit_reason"],
            "addon_added": bool(addon_unit),
            "addon_return_pct": addon_unit["return_pct"] if addon_unit else None,
            "addon_entry_date": addon_unit["entry_date"] if addon_unit else None,
            "addon_exit_date": addon_unit["exit_date"] if addon_unit else None,
            "addon_exit_reason": addon_unit["exit_reason"] if addon_unit else None,
            "confirm_date": addon["confirm_date"] if addon else None,
            "confirm_reason": addon["confirm_reason"] if addon else None,
            "total_units": total_units,
            "total_capital": total_units * POSITION_SIZE,
            "total_pnl": total_pnl,
            "package_return_pct": round(total_pnl / (total_units * POSITION_SIZE) * 100, 2),
            "unresolved": bool(base_unit.get("unresolved")) or bool(addon_unit and addon_unit.get("unresolved")),
        })

    unit_groups = split_rows(units, validation_start, test_start)
    package_groups = split_rows(packages, validation_start, test_start)
    stock_unit_groups, stock_counts = stock_holdout_groups(units)
    stock_package_groups, package_stock_counts = stock_holdout_groups(packages)
    base_units = [row for row in units if row["unit_type"] == "base"]
    addon_units = [row for row in units if row["unit_type"] == "addon"]
    return {
        "mode": mode,
        "summaries": {
            "chronological_unit": {name: summarize_units(rows) for name, rows in unit_groups.items()},
            "chronological_package": {name: summarize_packages(rows) for name, rows in package_groups.items()},
            "stock_unit": {name: summarize_units(rows) for name, rows in stock_unit_groups.items()},
            "stock_package": {name: summarize_packages(rows) for name, rows in stock_package_groups.items()},
            "base_units": summarize_units(base_units),
            "addon_units": summarize_units(addon_units),
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
    modes = {
        "v4_swing_base": simulate_mode(
            source_trades, series, benchmark_rows, benchmark_dates, validation_start, test_start, "v4_swing_base"
        ),
        "ma20_core_base": simulate_mode(
            source_trades, series, benchmark_rows, benchmark_dates, validation_start, test_start, "ma20_core_base"
        ),
    }
    return {
        "version": VERSION,
        "methodology": {
            "base_universe": "PB-V4 all next-open discount-2 pullback signals; one TWD 100,000 base unit each",
            "v4_swing_base": "keeps the original PB-V4 swing exit for the base unit, then tests add-on separately",
            "ma20_core_base": "lets the base unit become a MA20 core position, then tests add-on",
            "addon_entry": "one additional TWD 100,000 unit at next open after main-wave confirmation",
            "addon_confirmation": "confirmation close above MA20, breaks signal-day high or prior-20-day high, volume expands versus prior 20 or 5 days, and stock return since base entry beats 0050 over the same dates",
            "addon_exit": "gap-aware -7% hard stop, then MA20 core trend break after at least 10 trading days; latest close if still active",
            "capital": "standard-unit simulation only; no finite capital cap, no daily limit, no ranking queue",
        },
        "split": {"validation_start": validation_start, "test_start": test_start},
        "modes": modes,
    }


def compact(summary: dict[str, Any], key: str = "units") -> str:
    count = summary.get(key, 0)
    return (
        f"{count}｜勝率 {summary['win_rate_pct']:.2f}%｜平均 {summary['avg_return_pct']:.2f}%｜"
        f"中位 {summary['median_return_pct']:.2f}%｜損益 {summary['total_pnl']:,.0f}"
    )


def render_html(payload: dict[str, Any]) -> str:
    v4_mode = payload["modes"]["v4_swing_base"]
    core_mode = payload["modes"]["ma20_core_base"]
    v4_unit = v4_mode["summaries"]["chronological_unit"]
    core_unit = core_mode["summaries"]["chronological_unit"]
    v4_package = v4_mode["summaries"]["chronological_package"]
    core_package = core_mode["summaries"]["chronological_package"]
    v4_stock_unit = v4_mode["summaries"]["stock_unit"]
    core_stock_unit = core_mode["summaries"]["stock_unit"]
    v4_stock_package = v4_mode["summaries"]["stock_package"]
    core_stock_package = core_mode["summaries"]["stock_package"]
    v4_addon = v4_mode["summaries"]["addon_units"]
    core_addon = core_mode["summaries"]["addon_units"]
    chronological_rows = "".join(
        f"<tr><th>{name}</th><td>{html.escape(compact(v4_unit[name]))}</td>"
        f"<td>{html.escape(compact(core_unit[name]))}</td>"
        f"<td>{html.escape(compact(v4_package[name], 'signals'))}</td>"
        f"<td>{html.escape(compact(core_package[name], 'signals'))}</td></tr>"
        for name in ["train", "validation", "test", "full", "resolved_full"]
    )
    stock_labels = {
        "stock_train": "stock_train 60%",
        "stock_validation": "stock_validation 20%",
        "stock_test": "stock_test 20%",
    }
    stock_rows = "".join(
        f"<tr><th>{label}</th><td>{html.escape(compact(v4_stock_unit[name]))}</td>"
        f"<td>{html.escape(compact(core_stock_unit[name]))}</td>"
        f"<td>{html.escape(compact(v4_stock_package[name], 'signals'))}</td>"
        f"<td>{html.escape(compact(core_stock_package[name], 'signals'))}</td></tr>"
        for name, label in stock_labels.items()
    )
    top_addons = sorted(
        [row for row in v4_mode["units"] if row["unit_type"] == "addon"],
        key=lambda row: row["return_pct"],
        reverse=True,
    )[:30]
    addon_rows = "".join(
        f"<tr><td>{row['signal_date']}</td><td>{html.escape(str(row['stock_no']) + ' ' + str(row['stock_name']))}</td>"
        f"<td>{row['confirm_date']}</td><td>{row['entry_date']}</td>"
        f"<td class=\"num {'pos' if row['return_pct'] > 0 else 'neg'}\">{row['return_pct']:.2f}%</td>"
        f"<td>{row['exit_date']}</td><td>{html.escape(row['exit_reason'])}</td>"
        f"<td>{html.escape(row.get('confirm_reason') or '')}</td></tr>"
        for row in top_addons
    )
    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PB-V19 主升段加碼測試</title><style>
:root{{--bg:#f6f7f4;--paper:#fff;--ink:#17211d;--muted:#65716b;--line:#dfe5df;--good:#08735d;--bad:#a13e34;--accent:#1f6a73}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 system-ui,"Microsoft JhengHei",sans-serif}}header,main{{max-width:1500px;margin:auto;padding:24px 16px}}header{{border-bottom:1px solid var(--line)}}h1{{margin:0 0 8px;font-size:28px}}h2{{font-size:19px;margin:28px 0 10px}}p{{margin:6px 0;color:var(--muted)}}.cards{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1px;background:var(--line);border:1px solid var(--line);margin-top:20px}}.card{{background:var(--paper);padding:16px}}.card b{{display:block;font-size:20px}}.note{{margin-top:16px;background:#ecf3f2;border-left:4px solid var(--accent);padding:12px 14px}}.table{{overflow:auto;border:1px solid var(--line);background:var(--paper)}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}thead th{{background:#eef1ee;color:var(--muted);font-size:12px}}.num{{text-align:right}}.pos{{color:var(--good);font-weight:800}}.neg{{color:var(--bad);font-weight:800}}code{{background:#eef1ee;padding:1px 4px;border-radius:4px}}@media(max-width:900px){{.cards{{grid-template-columns:1fr 1fr}}}}@media(max-width:560px){{header,main{{padding:18px 10px}}.cards{{grid-template-columns:1fr}}}}
</style></head><body><header><h1>PB-V19 主升段加碼測試</h1><p>底倉不縮窄，PB-V4 全部折價 pullback 訊號都進一份 100,000；只有確認主升段後，隔天開盤再加碼一份 100,000。</p><div class="cards"><div class="card"><span>V4底倉+加碼</span><b>{v4_unit['full']['win_rate_pct']:.2f}% / {v4_unit['full']['avg_return_pct']:.2f}%</b><small>{v4_unit['full']['units']} 份，勝率 / 平均</small></div><div class="card"><span>核心底倉+加碼</span><b>{core_unit['full']['win_rate_pct']:.2f}% / {core_unit['full']['avg_return_pct']:.2f}%</b><small>{core_unit['full']['units']} 份</small></div><div class="card"><span>V4版加碼單</span><b>{v4_addon['win_rate_pct']:.2f}% / {v4_addon['avg_return_pct']:.2f}%</b><small>{v4_addon['units']} 份</small></div><div class="card"><span>核心版加碼單</span><b>{core_addon['win_rate_pct']:.2f}% / {core_addon['avg_return_pct']:.2f}%</b><small>{core_addon['units']} 份</small></div></div><div class="note"><strong>規則：</strong>確認日收盤站上 MA20，突破訊號日高點或前 20 日高點，量能高於前 20 日或前 5 日均量，且自底倉進場起漲幅勝過 0050；隔天開盤才加碼，不使用確認日收盤價。報表同時列出「V4 底倉不變」和「底倉也轉核心倉」兩種口徑。時間切片是前推驗證；股票切片才是 60% 股票訓練、20% 股票驗證、20% 股票測試。</div></header><main><h2>時間前推切片</h2><p>依照訊號日期排序切分，用來看策略在較新的市場期間是否衰退，不代表股票樣本切分。</p><div class="table"><table><thead><tr><th>區間</th><th>V4底倉+加碼 單位</th><th>核心底倉+加碼 單位</th><th>V4底倉 訊號包裹</th><th>核心底倉 訊號包裹</th></tr></thead><tbody>{chronological_rows}</tbody></table></div><h2>股票 60 / 20 / 20 切片</h2><p>以股票代號做固定雜湊分組，同一檔股票只會出現在同一組，用來檢查規則對未看過股票是否泛化。</p><div class="table"><table><thead><tr><th>區間</th><th>V4底倉+加碼 單位</th><th>核心底倉+加碼 單位</th><th>V4底倉 訊號包裹</th><th>核心底倉 訊號包裹</th></tr></thead><tbody>{stock_rows}</tbody></table></div><h2>V4底倉版：加碼單前 30 名</h2><div class="table"><table><thead><tr><th>訊號日</th><th>股票</th><th>確認日</th><th>加碼日</th><th class="num">加碼報酬</th><th>出場日</th><th>出場</th><th>確認條件</th></tr></thead><tbody>{addon_rows}</tbody></table></div><p>輸出檔：<code>{OUT_JSON}</code>、<code>{OUT_HTML}</code></p></main></body></html>"""


def main() -> None:
    payload = run()
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    v4_mode = payload["modes"]["v4_swing_base"]
    core_mode = payload["modes"]["ma20_core_base"]
    print(json.dumps({
        "html": str(OUT_HTML),
        "json": str(OUT_JSON),
        "v4_swing_base_unit_full": v4_mode["summaries"]["chronological_unit"]["full"],
        "v4_swing_base_addon_units": v4_mode["summaries"]["addon_units"],
        "v4_swing_stock_test": v4_mode["summaries"]["stock_unit"]["stock_test"],
        "ma20_core_base_unit_full": core_mode["summaries"]["chronological_unit"]["full"],
        "ma20_core_base_addon_units": core_mode["summaries"]["addon_units"],
        "ma20_core_stock_test": core_mode["summaries"]["stock_unit"]["stock_test"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
