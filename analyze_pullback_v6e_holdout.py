#!/usr/bin/env python3
"""Chronological holdout / walk-forward check for the best PB-V6E trend-review variant."""

from __future__ import annotations

import html
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import analyze_pullback_discount2_swing as base
import analyze_pullback_trend_review_variants as variants

REPORT_DIR = Path("reports")
OUT_JSON = REPORT_DIR / "pullback_pb_v6e_holdout.json"
OUT_HTML = REPORT_DIR / "pullback_pb_v6e_holdout.html"
OUT_MD = REPORT_DIR / "pullback_pb_v6e_holdout.md"

VERSION = "PB-V6E-holdout"
VARIANT_ID = "V6E_ma20_review_no_trailing_after20"
VARIANT_NAME = "第20日站上MA20續抱；第20日後改用跌破MA20出場，不再用移動停利"


def paired_trades() -> list[tuple[dict[str, Any], dict[str, Any]]]:
    baseline, variant_map, _ = variants.build_all_trades()
    v6e = variant_map[VARIANT_ID]
    return sorted(
        zip(baseline, v6e),
        key=lambda pair: (pair[0]["signal_date"], pair[0]["market"], pair[0]["stock_no"]),
    )


def summarize_side(items: list[tuple[dict[str, Any], dict[str, Any]]], side: int) -> dict[str, Any]:
    return base.summarize([row[side] for row in items])


def summarize_pair(items: list[tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, Any]:
    baseline = summarize_side(items, 0)
    v6e = summarize_side(items, 1)
    return {
        "trades": len(items),
        "pb_v4": baseline,
        "v6e": v6e,
        "delta_avg_return_pct": round(v6e["avg_return_pct"] - baseline["avg_return_pct"], 2),
        "delta_median_return_pct": round(v6e["median_return_pct"] - baseline["median_return_pct"], 2),
        "delta_win_rate_pct": round(v6e["win_rate_pct"] - baseline["win_rate_pct"], 2),
        "delta_total_pnl": int(v6e["total_pnl"] - baseline["total_pnl"]),
        "v6e_exit_reasons": dict(Counter(row[1]["exit_reason"] for row in items)),
        "v6e_latest_close_unresolved": sum(1 for row in items if row[1]["exit_reason"] == "latest_close_after_review"),
    }


def split_60_20_20(rows: list[tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, Any]:
    total = len(rows)
    cut1 = int(total * 0.6)
    cut2 = int(total * 0.8)
    buckets = {
        "train": rows[:cut1],
        "validation": rows[cut1:cut2],
        "test": rows[cut2:],
    }
    split_dates = {
        "validation_start": rows[cut1][0]["signal_date"] if cut1 < total else None,
        "test_start": rows[cut2][0]["signal_date"] if cut2 < total else None,
    }
    return {
        "split_dates": split_dates,
        "splits": {name: summarize_pair(items) for name, items in buckets.items()},
    }


def month_walk_forward(rows: list[tuple[dict[str, Any], dict[str, Any]]]) -> list[dict[str, Any]]:
    buckets: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for pair in rows:
        buckets[pair[0]["signal_date"][:7]].append(pair)
    output = []
    for month in sorted(buckets):
        items = buckets[month]
        summary = summarize_pair(items)
        output.append({"month": month, **summary})
    return output


def robustness(payload: dict[str, Any]) -> dict[str, Any]:
    splits = payload["chronological_60_20_20"]["splits"]
    validation = splits["validation"]
    test = splits["test"]
    pass_gate = (
        validation["delta_avg_return_pct"] > 0
        and validation["delta_median_return_pct"] >= 0
        and test["delta_avg_return_pct"] > 0
        and test["delta_median_return_pct"] >= 0
        and test["v6e_latest_close_unresolved"] == 0
    )
    reasons = []
    if validation["delta_avg_return_pct"] <= 0:
        reasons.append("validation average did not improve")
    if validation["delta_median_return_pct"] < 0:
        reasons.append("validation median worsened")
    if test["delta_avg_return_pct"] <= 0:
        reasons.append("test average worsened")
    if test["delta_median_return_pct"] < 0:
        reasons.append("test median worsened")
    if test["v6e_latest_close_unresolved"] > 0:
        reasons.append("test still has latest-close unresolved exits")
    return {"pass": pass_gate, "reasons": reasons}


def fmt_pct(value: Any) -> str:
    return f"{float(value):.2f}%"


def fmt_money(value: Any) -> str:
    return f"{int(value):,}"


def render_html(payload: dict[str, Any]) -> str:
    split_rows = "".join(
        f"<tr>"
        f"<td class='left'>{name}</td>"
        f"<td>{summary['trades']}</td>"
        f"<td>{fmt_pct(summary['pb_v4']['avg_return_pct'])}</td>"
        f"<td>{fmt_pct(summary['v6e']['avg_return_pct'])}</td>"
        f"<td class='{ 'pos' if summary['delta_avg_return_pct'] > 0 else 'neg' }'>{fmt_pct(summary['delta_avg_return_pct'])}</td>"
        f"<td>{fmt_pct(summary['pb_v4']['median_return_pct'])}</td>"
        f"<td>{fmt_pct(summary['v6e']['median_return_pct'])}</td>"
        f"<td class='{ 'pos' if summary['delta_median_return_pct'] >= 0 else 'neg' }'>{fmt_pct(summary['delta_median_return_pct'])}</td>"
        f"<td>{fmt_money(summary['delta_total_pnl'])}</td>"
        f"<td>{summary['v6e_latest_close_unresolved']}</td>"
        f"</tr>"
        for name, summary in payload["chronological_60_20_20"]["splits"].items()
    )
    month_rows = "".join(
        f"<tr>"
        f"<td class='left'>{row['month']}</td>"
        f"<td>{row['trades']}</td>"
        f"<td>{fmt_pct(row['pb_v4']['avg_return_pct'])}</td>"
        f"<td>{fmt_pct(row['v6e']['avg_return_pct'])}</td>"
        f"<td class='{ 'pos' if row['delta_avg_return_pct'] > 0 else 'neg' if row['delta_avg_return_pct'] < 0 else '' }'>{fmt_pct(row['delta_avg_return_pct'])}</td>"
        f"<td>{fmt_pct(row['pb_v4']['median_return_pct'])}</td>"
        f"<td>{fmt_pct(row['v6e']['median_return_pct'])}</td>"
        f"<td>{fmt_pct(row['delta_median_return_pct'])}</td>"
        f"</tr>"
        for row in payload["monthly_walk_forward"]
        if row["trades"] >= 3
    )
    gate = payload["robust_gate"]
    gate_text = "通過" if gate["pass"] else "未通過"
    reasons = "；".join(gate["reasons"]) if gate["reasons"] else "無"
    return f"""<!doctype html>
<html lang='zh-Hant'>
<head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<title>{VERSION}</title>
<style>
body {{ margin: 0; background: #f6f7fb; color: #172033; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans TC', sans-serif; line-height: 1.65; }}
main {{ max-width: 1180px; margin: auto; padding: 32px 24px 64px; }}
.card {{ background: white; border: 1px solid #e4e7ec; border-radius: 18px; padding: 20px; margin: 18px 0; box-shadow: 0 12px 34px rgba(15,23,42,.06); }}
table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
th, td {{ padding: 10px; border-bottom: 1px solid #e4e7ec; text-align: right; vertical-align: top; }}
th {{ background: #f8fafc; }}
.left {{ text-align: left; }}
.pos {{ color: #16803c; font-weight: 800; }}
.neg {{ color: #b42318; font-weight: 800; }}
.bad {{ border-left: 4px solid #b42318; background: #fef3f2; color: #7a271a; padding: 12px 14px; border-radius: 12px; }}
.note {{ border-left: 4px solid #2563eb; background: #eff6ff; color: #1e3a8a; padding: 12px 14px; border-radius: 12px; }}
code {{ background: #f2f4f7; padding: 2px 6px; border-radius: 6px; }}
</style>
</head><body><main>
<h1>{VERSION}</h1>
<p class='note'>測試版本：{html.escape(VARIANT_NAME)}。資料仍是 PB-V4 的 223 筆 discount-2 交易，只改第 20 日後的續抱/出場規則。</p>
<div class='card'>
<h2>結論：{gate_text}</h2>
<p class='bad'>Robust gate：{html.escape(reasons)}。V6E 雖然全樣本平均較高，但最後 test 平均與中位數都輸給 PB-V4，因此不可部署。</p>
<p>切分日期：validation 從 <code>{payload['chronological_60_20_20']['split_dates']['validation_start']}</code> 開始，test 從 <code>{payload['chronological_60_20_20']['split_dates']['test_start']}</code> 開始。</p>
</div>
<div class='card'>
<h2>60/20/20 chronological holdout</h2>
<table><thead><tr><th class='left'>區間</th><th>交易</th><th>PB-V4平均</th><th>V6E平均</th><th>平均差</th><th>PB-V4中位</th><th>V6E中位</th><th>中位差</th><th>總損益差</th><th>未實現估值</th></tr></thead><tbody>{split_rows}</tbody></table>
</div>
<div class='card'>
<h2>逐月 walk-forward</h2>
<table><thead><tr><th class='left'>月份</th><th>交易</th><th>PB-V4平均</th><th>V6E平均</th><th>平均差</th><th>PB-V4中位</th><th>V6E中位</th><th>中位差</th></tr></thead><tbody>{month_rows}</tbody></table>
</div>
</main></body></html>"""


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# {VERSION}",
        "",
        f"Variant: {VARIANT_NAME}",
        "",
        f"Robust gate: {'PASS' if payload['robust_gate']['pass'] else 'FAIL'}",
        f"Reasons: {', '.join(payload['robust_gate']['reasons'])}",
        "",
        "| Split | Trades | PB-V4 avg | V6E avg | Delta avg | PB-V4 median | V6E median | Delta median | Latest close unresolved |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, summary in payload["chronological_60_20_20"]["splits"].items():
        lines.append(
            f"| {name} | {summary['trades']} | {summary['pb_v4']['avg_return_pct']:.2f}% | {summary['v6e']['avg_return_pct']:.2f}% | {summary['delta_avg_return_pct']:.2f}% | {summary['pb_v4']['median_return_pct']:.2f}% | {summary['v6e']['median_return_pct']:.2f}% | {summary['delta_median_return_pct']:.2f}% | {summary['v6e_latest_close_unresolved']} |"
        )
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    rows = paired_trades()
    payload = {
        "version": VERSION,
        "variant_id": VARIANT_ID,
        "variant_name": VARIANT_NAME,
        "methodology": {
            "baseline": "PB-V4 max-20 swing exit",
            "variant": VARIANT_NAME,
            "split": "chronological 60/20/20 by sorted trade signal_date",
        },
        "overall": summarize_pair(rows),
        "chronological_60_20_20": split_60_20_20(rows),
        "monthly_walk_forward": month_walk_forward(rows),
    }
    payload["robust_gate"] = robustness(payload)
    REPORT_DIR.mkdir(exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    OUT_MD.write_text(render_markdown(payload), encoding="utf-8")
    return payload


if __name__ == "__main__":
    result = run()
    print(json.dumps({
        "overall": result["overall"],
        "chronological_60_20_20": result["chronological_60_20_20"],
        "robust_gate": result["robust_gate"],
    }, ensure_ascii=False, indent=2))
