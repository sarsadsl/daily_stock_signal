#!/usr/bin/env python3
"""Test a small, predeclared strong-stock filter without tuning on outcomes."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from analyze_pullback_discount2_swing import (
    ENTRY_DISCOUNT_PCT,
    SWING_MAX_HOLD_DAYS,
    build_trade,
    load_pullback_candidates,
    summarize,
    swing_exit,
)
from run_market_backtest import Row, prepare


REPORT_DIR = Path("reports")
VERSION = "PB-V5.0-strong-filter-holdout"
OUT_JSON = REPORT_DIR / "pullback_pb_v5_0_strong_filter_holdout.json"
OUT_HTML = REPORT_DIR / "pullback_pb_v5_0_strong_filter_holdout.html"

VARIANTS = {
    "control": "PB-V4 原規則，不加強勢濾網",
    "price_strength": "20 日漲幅 >= 8%，且收盤距 60 日高點不超過 15%",
    "orderly_pullback": "價格強勢 + 收盤仍在 MA60 上 + 訊號日量 <= 20 日均量 1.2 倍",
    "confirmed_leader": "回檔秩序 + 過去 40 日至少一次帶量推進日",
}


def features(rows: list[Row], index: int) -> dict[str, Any]:
    indicators = prepare(rows)
    row = rows[index]
    ret20 = row.close / rows[index - 20].close - 1
    high60 = max(item.high for item in rows[index - 59 : index + 1])
    ma60 = indicators["ma60"][index]
    vol20 = indicators["vol20"][index]
    surge_days = 0
    for cursor in range(index - 39, index + 1):
        prior = rows[cursor - 1]
        current = rows[cursor]
        avg_volume = indicators["vol20"][cursor]
        if avg_volume and current.close / prior.close - 1 >= 0.03 and current.volume >= avg_volume * 1.5:
            surge_days += 1
    price_strength = ret20 >= 0.08 and row.close >= high60 * 0.85
    orderly_pullback = bool(price_strength and ma60 and vol20 and row.close >= ma60 and row.volume <= vol20 * 1.2)
    return {
        "ret20_pct": round(ret20 * 100, 2),
        "distance_from_high60_pct": round((row.close / high60 - 1) * 100, 2),
        "signal_volume_ratio": round(row.volume / vol20, 2) if vol20 else None,
        "surge_days_40": surge_days,
        "price_strength": price_strength,
        "orderly_pullback": orderly_pullback,
        "confirmed_leader": orderly_pullback and surge_days >= 1,
    }


def split_dates(trades: list[dict[str, Any]]) -> tuple[str, str]:
    dates = sorted({row["signal_date"] for row in trades})
    return dates[int(len(dates) * 0.60)], dates[int(len(dates) * 0.80)]


def segment(trades: list[dict[str, Any]], validation_start: str, test_start: str, name: str) -> list[dict[str, Any]]:
    if name == "train":
        return [row for row in trades if row["signal_date"] < validation_start]
    if name == "validation":
        return [row for row in trades if validation_start <= row["signal_date"] < test_start]
    return [row for row in trades if row["signal_date"] >= test_start]


def run_backtest() -> dict[str, Any]:
    candidates, rows_by_source, funnel = load_pullback_candidates()
    trades: list[dict[str, Any]] = []
    for item in candidates:
        rows = rows_by_source[str(item["source"])]
        index = int(item["row_index"])
        entry_index = index + 1
        if index < 60 or entry_index + SWING_MAX_HOLD_DAYS > len(rows):
            continue
        entry = rows[entry_index]
        if entry.open > float(item["close"]) * (1 - ENTRY_DISCOUNT_PCT):
            continue
        perf = swing_exit(entry, rows[entry_index : entry_index + SWING_MAX_HOLD_DAYS])
        trade = build_trade(item, entry, perf, version=VERSION, exit_style="swing_d2")
        trade.update(features(rows, index))
        trades.append(trade)

    validation_start, test_start = split_dates(trades)
    results: dict[str, Any] = {}
    for variant in VARIANTS:
        selected = trades if variant == "control" else [row for row in trades if row[variant]]
        results[variant] = {
            "description": VARIANTS[variant],
            "all": summarize(selected),
            "retention_pct": round(len(selected) / len(trades) * 100, 2),
            "train": summarize(segment(selected, validation_start, test_start, "train")),
            "validation": summarize(segment(selected, validation_start, test_start, "validation")),
            "test": summarize(segment(selected, validation_start, test_start, "test")),
        }

    control = results["control"]
    for result in results.values():
        result["validation_avg_delta"] = round(result["validation"]["avg_return_pct"] - control["validation"]["avg_return_pct"], 2)
        result["test_avg_delta"] = round(result["test"]["avg_return_pct"] - control["test"]["avg_return_pct"], 2)
        result["robust"] = (
            result["validation"]["trades"] >= 20
            and result["test"]["trades"] >= 20
            and result["validation_avg_delta"] > 0
            and result["test_avg_delta"] > 0
        )

    return {
        "version": VERSION,
        "methodology": {
            "entry": "next open <= signal close * 0.98",
            "exit": "PB-V4 swing exit",
            "split": "chronological 60% train / 20% validation / 20% test by signal date",
            "selection": "thresholds declared before this run; no outcome-based parameter search",
            "robust_gate": "both validation and test improve average return, with >=20 trades in each",
        },
        "split_dates": {"validation_start": validation_start, "test_start": test_start},
        "funnel": funnel,
        "results": results,
        "trades": trades,
    }


def metric(summary: dict[str, Any]) -> str:
    return f"{summary['trades']} 筆 / 勝率 {summary['win_rate_pct']:.2f}% / 平均 {summary['avg_return_pct']:.2f}% / 中位 {summary['median_return_pct']:.2f}%"


def render_html(payload: dict[str, Any]) -> str:
    rows = []
    for name, result in payload["results"].items():
        status = "通過" if result["robust"] else ("控制組" if name == "control" else "未通過")
        rows.append(
            "<tr>"
            f"<td><strong>{html.escape(name)}</strong><small>{html.escape(result['description'])}</small></td>"
            f"<td>{result['retention_pct']:.1f}%</td>"
            f"<td>{html.escape(metric(result['train']))}</td>"
            f"<td>{html.escape(metric(result['validation']))}<small>相對控制 {result['validation_avg_delta']:+.2f} pt</small></td>"
            f"<td>{html.escape(metric(result['test']))}<small>相對控制 {result['test_avg_delta']:+.2f} pt</small></td>"
            f"<td><span class={'pass' if result['robust'] else 'fail'}>{status}</span></td>"
            "</tr>"
        )
    return f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PB-V5 強勢股濾網防過度擬合測試</title>
<style>
:root{{--ink:#17202a;--muted:#67727e;--line:#dfe4e8;--paper:#f7f8f6;--accent:#0c6b58;--bad:#9d3b32}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,"Noto Sans TC",sans-serif}}
main{{max-width:1440px;margin:auto;padding:32px 24px}} h1{{font-size:28px;margin:0 0 6px;letter-spacing:0}} p{{color:var(--muted);margin:0 0 24px}}
.summary{{display:flex;gap:32px;padding:16px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line);margin-bottom:24px}}
.summary b{{display:block;font-size:18px}} table{{width:100%;border-collapse:collapse;background:white}} th,td{{padding:13px 12px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}} th{{font-size:12px;color:var(--muted);background:#eef1ef}} small{{display:block;color:var(--muted);margin-top:4px}} .pass{{color:var(--accent);font-weight:700}} .fail{{color:var(--bad);font-weight:700}}
@media(max-width:900px){{main{{padding:20px 12px}}.summary{{display:block}}.summary div{{margin:8px 0}}.table{{overflow:auto}}table{{min-width:1050px}}}}
</style></head><body><main>
<h1>強勢股濾網：先防過度擬合</h1>
<p>固定 PB-V4 的隔日開低 2% 進場與波段出場，只增加三層事前濾網。門檻在回測前固定，不依報酬調參。</p>
<section class="summary"><div>驗證期開始<b>{payload['split_dates']['validation_start']}</b></div><div>測試期開始<b>{payload['split_dates']['test_start']}</b></div><div>穩健門檻<b>驗證與測試均改善，且各至少 20 筆</b></div></section>
<div class="table"><table><thead><tr><th>版本</th><th>保留率</th><th>前 60%</th><th>中間 20%</th><th>最後 20%</th><th>判定</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
</main></body></html>"""


def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    payload = run_backtest()
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    print(json.dumps({"version": VERSION, "results": payload["results"], "html": str(OUT_HTML)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
