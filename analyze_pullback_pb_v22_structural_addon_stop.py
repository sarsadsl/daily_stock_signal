#!/usr/bin/env python3
"""PB-V22: close-based structural stops for pullback add-on units."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from analyze_pullback_multitimeframe_search import BENCHMARK_CSV, PBV4_JSON, add_benchmark_return
from analyze_pullback_pb_v19_main_wave_addon import POSITION_SIZE, source_base_exit, summarize_packages, summarize_units
from analyze_pullback_pb_v20_fuzzy_addon import find_next_addon, split_chronological, split_stocks
from analyze_pullback_pb_v21_addon_stop_variants import intraday_exit, return_result
from analyze_pullback_technical_phenotypes import find_series, make_series_map
from run_market_backtest import Row, csv_files, read_rows


REPORT_DIR = Path("reports")
OUT_JSON = REPORT_DIR / "pullback_pb_v22_structural_addon_stop.json"
OUT_HTML = REPORT_DIR / "pullback_pb_v22_structural_addon_stop.html"
VERSION = "PB-V22.0-structural-addon-stop"
FOCUS_VARIANT_ID = "confluence_struct_close_next_open"

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
        "label": "V20 對照：MA20回測加碼 + 4%盤中停損",
        "stop_type": "intraday",
        "stop_pct": 0.04,
    },
    {
        "id": "exact_struct_close_exit_close",
        "label": "精準版：收盤跌破 MA20 / 確認K低點 / 回測低點，同日收盤出",
        "stop_type": "structure_close",
        "execute": "close",
        "catastrophic_close_pct": 0.15,
        "require_confluence": False,
    },
    {
        "id": "exact_struct_close_next_open",
        "label": "精準版：收盤跌破結構，隔天開盤出",
        "stop_type": "structure_close",
        "execute": "next_open",
        "catastrophic_close_pct": 0.15,
        "require_confluence": False,
    },
    {
        "id": FOCUS_VARIANT_ID,
        "label": "寬鬆版：收盤同時跌破 MA20 與結構低點，隔天開盤出",
        "stop_type": "structure_close",
        "execute": "next_open",
        "catastrophic_close_pct": 0.15,
        "require_confluence": True,
    },
]


def structural_levels(rows: list[Row], signal_index: int, confirm_index: int) -> dict[str, float]:
    pullback_low = min(row.low for row in rows[signal_index : confirm_index + 1])
    confirm_low = rows[confirm_index].low
    return {
        "confirm_low": confirm_low,
        "pullback_low": pullback_low,
        "structure_low": min(confirm_low, pullback_low),
    }


def close_execution_result(
    entry: Row,
    observed: list[Row],
    rows: list[Row],
    cursor: int,
    execute: str,
    reason: str,
) -> dict[str, Any]:
    if execute == "next_open" and cursor + 1 < len(rows):
        next_row = rows[cursor + 1]
        observed = observed + [next_row]
        return return_result(entry, observed, next_row.open, reason + "_next_open")
    return return_result(entry, observed, rows[cursor].close, reason)


def structure_close_exit(
    entry: Row,
    rows: list[Row],
    indicators: dict[str, list[float | None]],
    signal_index: int,
    entry_index: int,
    confirm_index: int,
    variant: dict[str, Any],
) -> dict[str, Any]:
    levels = structural_levels(rows, signal_index, confirm_index)
    catastrophic_close = entry.open * (1 - float(variant["catastrophic_close_pct"]))
    execute = str(variant["execute"])
    require_confluence = bool(variant["require_confluence"])
    observed: list[Row] = []

    for cursor in range(entry_index, len(rows)):
        row = rows[cursor]
        observed.append(row)
        ma20 = indicators["ma20"][cursor]
        if ma20 is None:
            continue

        below_ma20 = row.close < ma20
        below_confirm_low = row.close < levels["confirm_low"]
        below_pullback_low = row.close < levels["pullback_low"]
        below_structure_low = row.close < levels["structure_low"]
        below_catastrophic = row.close <= catastrophic_close

        if below_catastrophic:
            return close_execution_result(entry, observed, rows, cursor, execute, "catastrophic_close_stop")
        if require_confluence:
            if below_ma20 and below_structure_low:
                return close_execution_result(entry, observed, rows, cursor, execute, "confluence_structure_close_break")
            continue
        if below_ma20 or below_confirm_low or below_pullback_low:
            return close_execution_result(entry, observed, rows, cursor, execute, "structure_close_break")

    return return_result(entry, observed, observed[-1].close, "latest_close", unresolved=True)


def addon_exit(
    entry: Row,
    rows: list[Row],
    indicators: dict[str, list[float | None]],
    signal_index: int,
    entry_index: int,
    confirm_index: int,
    variant: dict[str, Any],
) -> dict[str, Any]:
    if variant["stop_type"] == "intraday":
        return intraday_exit(entry, rows, indicators, entry_index, float(variant["stop_pct"]))
    if variant["stop_type"] == "structure_close":
        return structure_close_exit(entry, rows, indicators, signal_index, entry_index, confirm_index, variant)
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
            exit_data = addon_exit(entry, rows, indicators, signal_index, entry_index, confirm_index, stop_variant)
            levels = structural_levels(rows, signal_index, confirm_index)
            unit = {
                **source,
                "variant": stop_variant["id"],
                "unit_type": "addon",
                "addon_number": addon_number,
                "entry_date": entry.date,
                "entry_price": round(entry.open, 4),
                "confirm_low": round(levels["confirm_low"], 4),
                "pullback_low": round(levels["pullback_low"], 4),
                "structure_low": round(levels["structure_low"], 4),
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
    washed = [row for row in addons if row["holding_days"] <= 10 and row["exit_reason"] != "latest_close"]
    recovered = [
        row for row in addons
        if row["holding_days"] <= 10
        and row["exit_reason"] == "latest_close"
        and row["return_pct"] > 20
    ]
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
            "recovered_unresolved_fast_winners": summarize_units(recovered),
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
            "base": "PB-V4 base unit keeps its original hard-stop/swing exit",
            "addon_entry": "PB-V20 MA20-retest add-on timing, max three equal TWD 100,000 add-on units",
            "exact_structure_stop": "add-on units ignore intraday structure breaks; failure is based on close below MA20, confirmation candle low, prior pullback low, or a close-based 15% catastrophic line",
            "execution": "both same-close theoretical exit and next-open realistic exit are reported",
            "validation": "chronological slices and stock-level 60/20/20 holdout are reported",
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


def unit_payload(row: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "id": f"{row['variant']}-{row['unit_type']}-{index}",
        "variant": row["variant"],
        "unitType": row["unit_type"],
        "unitLabel": "加碼單" if row["unit_type"] == "addon" else "母單",
        "addonNumber": row.get("addon_number"),
        "market": row["market"],
        "stockNo": str(row["stock_no"]),
        "stockName": row.get("stock_name", ""),
        "signalDate": row["signal_date"],
        "confirmDate": row.get("confirm_date"),
        "entryTriggerDate": row.get("entry_trigger_date"),
        "entryTriggerType": row.get("entry_trigger_type"),
        "entryDate": row["entry_date"],
        "entryPrice": row["entry_price"],
        "exitDate": row["exit_date"],
        "exitPrice": row["exit_price"],
        "holdingDays": row["holding_days"],
        "returnPct": row["return_pct"],
        "pnl": row["pnl"],
        "exitReason": row["exit_reason"],
        "unresolved": bool(row.get("unresolved")),
        "signalClose": row.get("signal_close"),
        "confirmClose": row.get("confirm_close"),
        "confirmLow": row.get("confirm_low"),
        "pullbackLow": row.get("pullback_low"),
        "structureLow": row.get("structure_low"),
        "reasons": row.get("reasons") or row.get("confirm_reason") or "",
    }


def chart_payload(units: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    series = make_series_map(csv_files())
    output: dict[str, list[dict[str, Any]]] = {}
    for unit in units:
        key = f"{unit['market']}:{unit['stockNo']}"
        if key in output:
            continue
        bundle = find_series(series, unit["market"], unit["stockNo"])
        if not bundle:
            output[key] = []
            continue
        rows, _, _ = bundle
        output[key] = [
            {
                "date": row.date,
                "open": row.open,
                "high": row.high,
                "low": row.low,
                "close": row.close,
                "volume": row.volume,
            }
            for row in rows
        ]
    return output


def render_html(payload: dict[str, Any]) -> str:
    ranked = sorted(
        payload["variants"],
        key=lambda item: (
            item["summaries"]["stock_unit"]["stock_test"]["avg_return_pct"],
            item["summaries"]["stock_unit"]["stock_test"]["win_rate_pct"],
        ),
        reverse=True,
    )
    comparison_rows = "".join(
        f"<tr><th>{html.escape(item['variant']['label'])}</th>"
        f"<td>{html.escape(compact(item['summaries']['chronological_unit']['full']))}</td>"
        f"<td>{html.escape(compact(item['summaries']['stock_unit']['stock_test']))}</td>"
        f"<td>{html.escape(compact(item['summaries']['addon_units']))}</td>"
        f"<td>{html.escape(compact(item['summaries']['washed_addons_le_10d']))}</td></tr>"
        for item in ranked
    )
    focus = next(item for item in payload["variants"] if item["variant"]["id"] == FOCUS_VARIANT_ID)
    focus_units = [unit_payload(row, index) for index, row in enumerate(focus["units"])]
    focus_units.sort(key=lambda row: (row["signalDate"], row["stockNo"], 0 if row["unitType"] == "base" else 1, row.get("addonNumber") or 0))
    series_json = json.dumps(chart_payload(focus_units), ensure_ascii=False, separators=(",", ":"))
    units_json = json.dumps(focus_units, ensure_ascii=False, separators=(",", ":"))
    labels_json = json.dumps({item["variant"]["id"]: item["variant"]["label"] for item in payload["variants"]}, ensure_ascii=False)
    focus_summary = focus["summaries"]
    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PB-V22 結構式加碼停損</title><style>
:root{{--bg:#f7f7f2;--paper:#fff;--ink:#17211d;--muted:#65716b;--line:#dfe5df;--good:#08735d;--bad:#a13e34;--accent:#1f6a73;--blue:#2563eb;--orange:#d97706;--purple:#7c3aed}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 system-ui,"Microsoft JhengHei",sans-serif}}header,main{{max-width:1500px;margin:auto;padding:24px 16px}}header{{border-bottom:1px solid var(--line)}}h1{{margin:0 0 8px;font-size:28px}}h2{{font-size:19px;margin:28px 0 10px}}p{{margin:6px 0;color:var(--muted)}}.cards{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1px;background:var(--line);border:1px solid var(--line);margin-top:20px}}.card{{background:var(--paper);padding:16px}}.card b{{display:block;font-size:20px}}.note{{margin-top:16px;background:#ecf3f2;border-left:4px solid var(--accent);padding:12px 14px}}.tools{{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:12px 0}}input,select{{height:38px;border:1px solid var(--line);border-radius:8px;background:#fff;padding:0 10px;color:var(--ink)}}.table{{overflow:auto;border:1px solid var(--line);background:var(--paper)}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}thead th{{background:#eef1ee;color:var(--muted);font-size:12px;position:sticky;top:0;z-index:1}}.num{{text-align:right}}.pos{{color:var(--good);font-weight:800}}.neg{{color:var(--bad);font-weight:800}}code{{background:#eef1ee;padding:1px 4px;border-radius:4px}}button{{border:1px solid #b9d6d4;background:#eef8f7;color:#155e63;border-radius:999px;padding:6px 10px;font-weight:700;cursor:pointer}}button:hover{{background:#d9efed}}.chip{{display:inline-flex;padding:2px 7px;border-radius:999px;background:#eef1ee;color:#46524b;font-size:12px;font-weight:700}}.chip.addon{{background:#fff7ed;color:#b45309}}.chip.open{{background:#fff7ed;color:#b45309}}.chart-row td{{background:#fbfcfb}}.chart-panel{{min-width:960px;padding:14px}}.chart-head{{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:8px}}.chart-canvas{{width:100%;height:560px;border:1px solid var(--line);background:#fff;border-radius:8px}}.legend{{display:flex;gap:12px;flex-wrap:wrap;margin-top:8px;color:var(--muted);font-size:12px}}.dot{{width:10px;height:10px;border-radius:50%;display:inline-block;margin-right:4px}}@media(max-width:900px){{.cards{{grid-template-columns:1fr 1fr}}header,main{{padding:18px 10px}}.chart-panel{{min-width:900px}}}}
</style></head><body><header><h1>PB-V22 結構式加碼停損</h1><p>這版補測你指定的方法：底倉照 PB-V4；加碼單不再用盤中低點機械停損，而是以收盤同時跌破 MA20 與結構低點才視為寬鬆版加碼失敗，隔天開盤出。</p><div class="cards"><div class="card"><span>焦點版本</span><b>寬鬆版</b><small>{html.escape(focus['variant']['label'])}</small></div><div class="card"><span>全期</span><b>{focus_summary['chronological_unit']['full']['avg_return_pct']:.2f}%</b><small>{focus_summary['chronological_unit']['full']['units']} 份，勝率 {focus_summary['chronological_unit']['full']['win_rate_pct']:.2f}%</small></div><div class="card"><span>母單</span><b>{focus_summary['base_units']['units']} 份</b><small>平均 {focus_summary['base_units']['avg_return_pct']:.2f}%</small></div><div class="card"><span>加碼單</span><b>{focus_summary['addon_units']['win_rate_pct']:.2f}% / {focus_summary['addon_units']['avg_return_pct']:.2f}%</b><small>{focus_summary['addon_units']['units']} 份，勝率 / 平均</small></div></div><div class="note"><strong>這頁已把寬鬆版全部列出：</strong>母單 223 筆、加碼單 40 筆。按「展開K線」可以看訊號日、確認日、買進日、賣出/估值日，以及加碼單的確認K低點、回測低點、結構低點。</div></header><main><h2>變體比較</h2><div class="table"><table><thead><tr><th>版本</th><th>全期單位</th><th>股票測試單位</th><th>加碼單</th><th>10日內結構失敗</th></tr></thead><tbody>{comparison_rows}</tbody></table></div><h2>寬鬆版逐筆檢視</h2><div class="tools"><input id="search" placeholder="搜尋代號、名稱、日期、原因"><select id="typeFilter"><option value="all">全部單位</option><option value="base">只看母單</option><option value="addon">只看加碼單</option></select><select id="statusFilter"><option value="all">全部狀態</option><option value="closed">已出場</option><option value="open">未實現</option></select><select id="sortBy"><option value="signalDate">依訊號日</option><option value="returnPct">依報酬率</option><option value="holdingDays">依持有日</option><option value="stockNo">依代號</option></select><span id="rowCount" class="chip"></span></div><div class="table"><table id="unitTable"><thead><tr><th>股票 / K線</th><th>單位</th><th>訊號日</th><th>確認日</th><th>進場日</th><th>出場/估值</th><th class="num">進場</th><th class="num">出場</th><th class="num">持有</th><th class="num">報酬</th><th class="num">損益</th><th class="num">結構低</th><th>出場原因</th></tr></thead><tbody></tbody></table></div><p>輸出檔：<code>{OUT_JSON}</code>、<code>{OUT_HTML}</code></p></main><script id="unit-data" type="application/json">{units_json}</script><script id="series-data" type="application/json">{series_json}</script><script id="variant-labels" type="application/json">{labels_json}</script><script>
const trades = JSON.parse(document.getElementById('unit-data').textContent);
const seriesByStock = JSON.parse(document.getElementById('series-data').textContent);
let expandedId = null;
const fmt = new Intl.NumberFormat('zh-TW');
function esc(value) {{ return String(value ?? '').replace(/[&<>"']/g, char => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[char])); }}
function pct(value) {{ const number = Number(value); return Number.isFinite(number) ? `${{number.toFixed(2)}}%` : '-'; }}
function price(value) {{ const number = Number(value); return Number.isFinite(number) ? number.toFixed(2) : '-'; }}
function money(value) {{ const number = Number(value); return Number.isFinite(number) ? fmt.format(Math.round(number)) : '-'; }}
function keyOf(row) {{ return `${{row.market}}:${{row.stockNo}}`; }}
function statusOf(row) {{ return row.unresolved ? '未實現' : '已出場'; }}
function markerIndex(rows, date) {{ if (!date) return -1; const exact = rows.findIndex(row => row.date === date); if (exact >= 0) return exact; return rows.findIndex(row => row.date > date); }}
function chartWindow(rows, trade) {{
  const anchors = [trade.signalDate, trade.confirmDate, trade.entryDate, trade.exitDate].map(date => markerIndex(rows, date)).filter(index => index >= 0);
  if (!anchors.length) return rows.slice(-110);
  const start = Math.max(0, Math.min(...anchors) - 45);
  const end = Math.min(rows.length, Math.max(...anchors) + 60);
  return rows.slice(start, end);
}}
function movingAverage(rows, index, window) {{ if (index < window - 1) return null; let total = 0; for (let i = index - window + 1; i <= index; i += 1) total += rows[i].close; return total / window; }}
function renderRows() {{
  const query = document.getElementById('search').value.trim().toLowerCase();
  const type = document.getElementById('typeFilter').value;
  const status = document.getElementById('statusFilter').value;
  const sortBy = document.getElementById('sortBy').value;
  let rows = trades.filter(row => {{
    if (type !== 'all' && row.unitType !== type) return false;
    if (status === 'closed' && row.unresolved) return false;
    if (status === 'open' && !row.unresolved) return false;
    if (!query) return true;
    return [row.stockNo,row.stockName,row.signalDate,row.confirmDate,row.entryDate,row.exitDate,row.exitReason,row.reasons,row.unitLabel].some(value => String(value || '').toLowerCase().includes(query));
  }});
  rows.sort((a, b) => {{
    if (sortBy === 'returnPct' || sortBy === 'holdingDays') return Number(b[sortBy] || 0) - Number(a[sortBy] || 0);
    return String(a[sortBy] || '').localeCompare(String(b[sortBy] || ''), 'zh-Hant');
  }});
  document.getElementById('rowCount').textContent = `顯示 ${{rows.length}} / ${{trades.length}} 筆`;
  const tbody = document.querySelector('#unitTable tbody');
  tbody.innerHTML = rows.map(row => {{
    const isAddon = row.unitType === 'addon';
    const main = `<tr><td><strong>${{esc(row.stockNo)}} ${{esc(row.stockName)}}</strong> <span class="chip">${{esc(row.market)}}</span><br><button type="button" data-chart="${{esc(row.id)}}">${{expandedId === row.id ? '收合K線' : '展開K線'}}</button></td><td><span class="chip ${{isAddon ? 'addon' : ''}}">${{esc(row.unitLabel)}}${{row.addonNumber ? ' #' + row.addonNumber : ''}}</span> <span class="chip ${{row.unresolved ? 'open' : ''}}">${{statusOf(row)}}</span></td><td>${{esc(row.signalDate)}}</td><td>${{esc(row.confirmDate || '-')}}</td><td>${{esc(row.entryDate)}}</td><td>${{esc(row.exitDate)}}</td><td class="num">${{price(row.entryPrice)}}</td><td class="num">${{price(row.exitPrice)}}</td><td class="num">${{esc(row.holdingDays)}}</td><td class="num ${{Number(row.returnPct) >= 0 ? 'pos' : 'neg'}}">${{pct(row.returnPct)}}</td><td class="num ${{Number(row.pnl) >= 0 ? 'pos' : 'neg'}}">${{money(row.pnl)}}</td><td class="num">${{price(row.structureLow)}}</td><td>${{esc(row.exitReason)}}</td></tr>`;
    const chart = expandedId === row.id ? `<tr class="chart-row"><td colspan="13"><div class="chart-panel"><div class="chart-head"><strong>${{esc(row.stockNo)}} ${{esc(row.stockName)}}｜${{esc(row.unitLabel)}} K線</strong><span>訊號 ${{esc(row.signalDate)}}｜確認 ${{esc(row.confirmDate || '-')}}｜進場 ${{esc(row.entryDate)}}｜出場/估值 ${{esc(row.exitDate)}}</span></div><canvas id="canvas-${{esc(row.id)}}" class="chart-canvas" width="1200" height="560"></canvas><div class="legend"><span><i class="dot" style="background:#f59e0b"></i>MA5</span><span><i class="dot" style="background:#64748b"></i>MA20</span><span><i class="dot" style="background:#94a3b8"></i>MA60</span><span><i class="dot" style="background:#2563eb"></i>訊號</span><span><i class="dot" style="background:#d97706"></i>確認</span><span><i class="dot" style="background:#16a34a"></i>進場</span><span><i class="dot" style="background:#dc2626"></i>出場/估值</span><span><i class="dot" style="background:#7c3aed"></i>結構線</span></div></div></td></tr>` : '';
    return main + chart;
  }}).join('') || '<tr><td colspan="13">沒有符合條件的資料</td></tr>';
  if (expandedId) drawExpanded();
}}
function drawMarker(ctx, x, top, bottom, color, label) {{ ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, bottom); ctx.stroke(); ctx.fillStyle = color; ctx.font = '12px sans-serif'; ctx.textAlign = 'center'; ctx.fillText(label, x, top - 6); }}
function drawExpanded() {{
  const trade = trades.find(row => row.id === expandedId);
  if (!trade) return;
  const canvas = document.getElementById(`canvas-${{trade.id}}`);
  const allRows = seriesByStock[keyOf(trade)] || [];
  if (!canvas || !allRows.length) return;
  const rows = chartWindow(allRows, trade);
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const cssWidth = Math.max(960, canvas.clientWidth || 1200);
  const cssHeight = 560;
  canvas.width = Math.round(cssWidth * dpr); canvas.height = Math.round(cssHeight * dpr); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssWidth, cssHeight); ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, cssWidth, cssHeight);
  const margin = {{left:58,right:26,top:34,bottom:70}}; const priceHeight = 350; const volumeTop = margin.top + priceHeight + 30; const volumeHeight = 90; const plotWidth = cssWidth - margin.left - margin.right;
  const maxPrice = Math.max(...rows.map(row => row.high), Number(trade.confirmLow || 0), Number(trade.pullbackLow || 0), Number(trade.structureLow || 0)) * 1.04;
  const minPrice = Math.min(...rows.map(row => row.low), ...[trade.confirmLow, trade.pullbackLow, trade.structureLow].filter(Number.isFinite).map(Number)) * 0.96;
  const priceScale = value => margin.top + (maxPrice - value) / (maxPrice - minPrice) * priceHeight;
  const maxVolume = Math.max(...rows.map(row => row.volume || 0), 1); const xStep = plotWidth / Math.max(rows.length, 1); const candleWidth = Math.max(3, Math.min(10, xStep * .58)); const xAt = index => margin.left + index * xStep + xStep / 2;
  ctx.strokeStyle = '#e4e7ec'; ctx.lineWidth = 1; ctx.fillStyle = '#667085'; ctx.font = '12px sans-serif'; ctx.textAlign = 'right';
  for (let i = 0; i <= 4; i += 1) {{ const y = margin.top + priceHeight * i / 4; const value = maxPrice - (maxPrice - minPrice) * i / 4; ctx.beginPath(); ctx.moveTo(margin.left, y); ctx.lineTo(cssWidth - margin.right, y); ctx.stroke(); ctx.fillText(value.toFixed(2), margin.left - 8, y + 4); }}
  rows.forEach((row, index) => {{ const x = xAt(index); const up = row.close >= row.open; ctx.strokeStyle = up ? '#d92d20' : '#039855'; ctx.fillStyle = ctx.strokeStyle; ctx.beginPath(); ctx.moveTo(x, priceScale(row.high)); ctx.lineTo(x, priceScale(row.low)); ctx.stroke(); const bodyTop = priceScale(Math.max(row.open, row.close)); const bodyBottom = priceScale(Math.min(row.open, row.close)); ctx.fillRect(x - candleWidth / 2, bodyTop, candleWidth, Math.max(1, bodyBottom - bodyTop)); const vh = (row.volume || 0) / maxVolume * volumeHeight; ctx.globalAlpha = .28; ctx.fillRect(x - candleWidth / 2, volumeTop + volumeHeight - vh, candleWidth, vh); ctx.globalAlpha = 1; }});
  function drawMa(window, color) {{ ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.beginPath(); let started = false; rows.forEach((_, index) => {{ const globalIndex = allRows.findIndex(row => row.date === rows[index].date); const ma = movingAverage(allRows, globalIndex, window); if (!ma) return; const x = xAt(index); const y = priceScale(ma); if (!started) {{ ctx.moveTo(x, y); started = true; }} else ctx.lineTo(x, y); }}); ctx.stroke(); }}
  drawMa(5, '#f59e0b'); drawMa(20, '#64748b'); drawMa(60, '#94a3b8');
  function idx(date) {{ return rows.findIndex(row => row.date === date); }}
  [[trade.signalDate,'#2563eb','訊號'],[trade.confirmDate,'#d97706','確認'],[trade.entryDate,'#16a34a','進場'],[trade.exitDate,'#dc2626','出場']].forEach(([date,color,label]) => {{ const index = idx(date); if (index >= 0) drawMarker(ctx, xAt(index), margin.top, margin.top + priceHeight, color, label); }});
  [[trade.confirmLow,'確認K低'],[trade.pullbackLow,'回測低'],[trade.structureLow,'結構低']].forEach(([value,label], i) => {{ const number = Number(value); if (!Number.isFinite(number)) return; const y = priceScale(number); ctx.setLineDash([6,4]); ctx.strokeStyle = ['#7c3aed','#a16207','#111827'][i]; ctx.beginPath(); ctx.moveTo(margin.left, y); ctx.lineTo(cssWidth - margin.right, y); ctx.stroke(); ctx.setLineDash([]); ctx.fillStyle = ['#7c3aed','#a16207','#111827'][i]; ctx.textAlign = 'left'; ctx.fillText(`${{label}} ${{number.toFixed(2)}}`, margin.left + 8, y - 5); }});
  ctx.fillStyle = '#667085'; ctx.textAlign = 'center'; ctx.font = '12px sans-serif'; for (let i = 0; i < rows.length; i += Math.ceil(rows.length / 6)) ctx.fillText(rows[i].date.slice(5), xAt(i), cssHeight - 28);
}}
document.addEventListener('input', event => {{ if (['search','typeFilter','statusFilter','sortBy'].includes(event.target.id)) {{ expandedId = null; renderRows(); }} }});
document.addEventListener('change', event => {{ if (['typeFilter','statusFilter','sortBy'].includes(event.target.id)) {{ expandedId = null; renderRows(); }} }});
document.addEventListener('click', event => {{ const button = event.target.closest('[data-chart]'); if (!button) return; expandedId = expandedId === button.dataset.chart ? null : button.dataset.chart; renderRows(); }});
renderRows();
</script></body></html>"""


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
