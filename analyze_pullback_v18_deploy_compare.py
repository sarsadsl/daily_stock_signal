#!/usr/bin/env python3
"""Deployment-oriented comparison: V18 all-score no-limit with and without V23 add-ons."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

REPORT_DIR = Path("reports")
NO_ADDON_JSON = REPORT_DIR / "pullback_v18_all_scores_no_limit.json"
ADDON_JSON = REPORT_DIR / "pullback_v18_all_scores_addon.json"
OUT_JSON = REPORT_DIR / "pullback_v18_deploy_compare.json"
OUT_HTML = REPORT_DIR / "pullback_v18_deploy_compare.html"
OUT_MD = REPORT_DIR / "pullback_v18_deploy_compare.md"
VERSION = "PB-V18-deploy-compare"


def load_payloads() -> tuple[dict[str, Any], dict[str, Any]]:
    return (
        json.loads(NO_ADDON_JSON.read_text(encoding="utf-8")),
        json.loads(ADDON_JSON.read_text(encoding="utf-8")),
    )


def unresolved_rate(summary: dict[str, Any]) -> float:
    total = summary.get("units") or summary.get("trades") or summary.get("signals") or 0
    unresolved = summary.get("unresolved", 0)
    return round(unresolved / total * 100, 2) if total else 0.0


def summarize_no_addon(no_addon: dict[str, Any]) -> dict[str, Any]:
    full = no_addon["full"]
    random_test = no_addon["random_statistics"]["stock_test"]
    return {
        "id": "v18_all_score_no_limit_no_addon",
        "label": "V18 all-score no-limit：不加碼",
        "purpose": "Baseline mother trades only. All original score buckets are included; avoid_score4 is removed.",
        "full": {
            "units": full["trades"],
            "win_rate_pct": full["win_rate_pct"],
            "avg_return_pct": full["avg_return_pct"],
            "median_return_pct": full["median_return_pct"],
            "capital_return_pct": full["capital_return_pct"],
            "best_return_pct": full["best_return_pct"],
            "worst_return_pct": full["worst_return_pct"],
            "unresolved": full["unresolved"],
            "unresolved_rate_pct": unresolved_rate({"units": full["trades"], "unresolved": full["unresolved"]}),
        },
        "deterministic_stock_test": None,
        "package_stock_test": None,
        "addon_units": None,
        "random_stock_test": random_test,
    }


def summarize_addon(addon: dict[str, Any]) -> dict[str, Any]:
    summaries = addon["result"]["summaries"]
    full = summaries["chronological_unit"]["full"]
    stock_test = summaries["stock_unit"]["stock_test"]
    addon_units = summaries["addon_units"]
    package_stock_test = summaries["stock_package"]["stock_test"]
    package_full = summaries["chronological_package"]["full"]
    random_test = addon["random_stock_unit_statistics"]["stock_test"]
    return {
        "id": "v18_all_score_no_limit_v23_addon",
        "label": "V18 all-score no-limit：V23 加碼",
        "purpose": "Mother trades plus PB-V23 add-on lifecycle for capturing large waves.",
        "full": {
            **full,
            "unresolved_rate_pct": unresolved_rate(full),
        },
        "deterministic_stock_test": {
            **stock_test,
            "unresolved_rate_pct": unresolved_rate(stock_test),
        },
        "package_full": package_full,
        "package_stock_test": package_stock_test,
        "addon_units": {
            **addon_units,
            "unresolved_rate_pct": unresolved_rate(addon_units),
        },
        "random_stock_test": random_test,
    }


def deployment_assessment(no_addon_summary: dict[str, Any], addon_summary: dict[str, Any]) -> dict[str, Any]:
    add_full = addon_summary["full"]
    add_stock = addon_summary["deterministic_stock_test"]
    add_random = addon_summary["random_stock_test"]
    add_package = addon_summary["package_stock_test"]
    blockers = []
    positives = []

    if add_full["avg_return_pct"] >= 10:
        positives.append("Full average return clears 10% after V23 add-ons.")
    if addon_summary["addon_units"]["avg_return_pct"] >= 20:
        positives.append("Add-on units capture large-wave upside and show high average return.")
    if add_random["avg_return_pct"]["mean"] >= 10:
        positives.append("Random stock-test average return clears 10% in mean and all 10 seeds clear avg>=10.")

    if add_stock["win_rate_pct"] < 60 or add_stock["avg_return_pct"] < 10:
        blockers.append("Deterministic stock-test does not clear 60% win / 10% average return.")
    if add_random["pass_60win_10avg_count"] < 7:
        blockers.append("Random stock-test pass count is only 5/10, not stable enough.")
    if add_full["unresolved_rate_pct"] >= 30:
        blockers.append("Unresolved exposure is very high; many gains are latest-close estimates, not realized exits.")
    if add_package["win_rate_pct"] < 50 or add_package["avg_return_pct"] < 10:
        blockers.append("Package stock-test is weak, meaning original signal quality is not strong enough even if add-ons lift unit returns.")
    if no_addon_summary["full"]["win_rate_pct"] < 50 or no_addon_summary["full"]["avg_return_pct"] < 10:
        blockers.append("Mother pool without add-ons is weak; deployment depends heavily on add-on winners.")

    verdict = "not_deployable"
    if not blockers:
        verdict = "deployable_candidate"
    elif len(blockers) <= 2:
        verdict = "paper_trade_candidate"

    return {
        "verdict": verdict,
        "label": "不可部署；可列為 forward paper-trading 觀察候選" if verdict == "not_deployable" else verdict,
        "positives": positives,
        "blockers": blockers,
        "recommended_next_step": "Track live signals with real-time unresolved/add-on exposure; do not use production capital until an untouched forward cohort resolves with >=60% win rate, >=10% average return, and acceptable drawdown/unresolved exposure.",
    }


def run() -> dict[str, Any]:
    no_addon, addon = load_payloads()
    no_addon_summary = summarize_no_addon(no_addon)
    addon_summary = summarize_addon(addon)
    assessment = deployment_assessment(no_addon_summary, addon_summary)
    return {
        "version": VERSION,
        "methodology": {
            "question": "Can the V18 all-score no-limit strategy be deployed, comparing mother-only vs V23 add-on version?",
            "shared_conditions": [
                "All one-year enriched pullback score buckets are included: score 5/4/3/2; score 1 has no trades.",
                "avoid_score4 is removed; no stock is excluded by climax filter.",
                "V17 runner is used for mother exits.",
                "V18 fee/tax model and +0.10% adverse slippage each side are included.",
                "No finite capital, max position, max-new-per-day, or duplicate-stock capacity limits.",
                "TWD 100,000 standard unit per entry/add-on unit.",
            ],
            "addon_version": "PB-V23 add-on lifecycle: MA20 retest, max5/spacing5, scan to data end, structural stop and 15% close-based catastrophic line.",
        },
        "comparison": [no_addon_summary, addon_summary],
        "deployment_assessment": assessment,
    }


def fmt(value: Any, suffix: str = "") -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.2f}{suffix}"
    return f"{value}{suffix}"


def summary_cell(summary: dict[str, Any] | None, *, random: bool = False, package: bool = False) -> str:
    if not summary:
        return "-"
    if random:
        return (
            f"mean {summary['trades']['mean']:.1f} 份｜"
            f"{summary['win_rate_pct']['mean']:.2f}%｜"
            f"{summary['avg_return_pct']['mean']:.2f}%｜"
            f"pass {summary['pass_60win_10avg_count']}/10"
        )
    if package:
        return (
            f"{summary['signals']} 組｜"
            f"{summary['win_rate_pct']:.2f}%｜"
            f"{summary['avg_return_pct']:.2f}%｜"
            f"中位 {summary['median_return_pct']:.2f}%"
        )
    total = summary.get("units") or summary.get("trades")
    return (
        f"{total} 份｜"
        f"{summary['win_rate_pct']:.2f}%｜"
        f"{summary['avg_return_pct']:.2f}%｜"
        f"中位 {summary['median_return_pct']:.2f}%｜"
        f"未實現 {summary.get('unresolved', 0)}"
    )


def render_html(payload: dict[str, Any]) -> str:
    rows = "".join(
        f"<tr><th>{html.escape(item['label'])}</th>"
        f"<td>{html.escape(summary_cell(item['full']))}</td>"
        f"<td>{html.escape(summary_cell(item.get('deterministic_stock_test')))}</td>"
        f"<td>{html.escape(summary_cell(item.get('random_stock_test'), random=True))}</td>"
        f"<td>{html.escape(summary_cell(item.get('addon_units')))}</td>"
        f"<td>{html.escape(summary_cell(item.get('package_stock_test'), package=True))}</td></tr>"
        for item in payload["comparison"]
    )
    assessment = payload["deployment_assessment"]
    blockers = "".join(f"<li>{html.escape(item)}</li>" for item in assessment["blockers"])
    positives = "".join(f"<li>{html.escape(item)}</li>" for item in assessment["positives"])
    addon = payload["comparison"][1]
    no_addon = payload["comparison"][0]
    return f"""<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{VERSION}</title><style>
:root{{--bg:#f6f7fb;--paper:#fff;--ink:#172033;--muted:#667085;--line:#e4e7ec;--good:#08735d;--bad:#b42318;--blue:#2563eb}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 system-ui,'Microsoft JhengHei',sans-serif}}header,main{{max-width:1400px;margin:auto;padding:28px 20px}}header{{border-bottom:1px solid var(--line)}}h1{{margin:0 0 8px;font-size:30px}}h2{{margin:28px 0 10px;font-size:20px}}p{{color:var(--muted)}}.metrics{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1px;background:var(--line);border:1px solid var(--line);margin-top:22px}}.metric{{background:#fff;padding:16px}}.metric span,.metric small{{display:block;color:var(--muted)}}.metric b{{font-size:22px}}.warn{{border-left:4px solid var(--bad);background:#fef3f2;padding:12px 14px;margin:18px 0;border-radius:12px}}.note{{border-left:4px solid var(--blue);background:#eff6ff;padding:12px 14px;margin:18px 0;border-radius:12px}}.table{{overflow:auto;border:1px solid var(--line);background:#fff}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:right;vertical-align:top}}th:first-child,td:first-child{{text-align:left}}thead th{{background:#f8fafc;color:var(--muted);font-size:12px}}li{{margin:6px 0}}@media(max-width:900px){{.metrics{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}@media(max-width:560px){{header,main{{padding:18px 10px}}.metrics{{grid-template-columns:1fr}}}}
</style></head><body><header><h1>{VERSION}</h1><p>比較 V18 all-score no-limit 在「不加碼」與「套 PB-V23 加碼」兩種版本下，是否已達可部署水準。</p><div class='metrics'><div class='metric'><span>部署判斷</span><b>{html.escape(assessment['label'])}</b><small>不是 production-ready</small></div><div class='metric'><span>不加碼 full</span><b>{no_addon['full']['win_rate_pct']:.2f}% / {no_addon['full']['avg_return_pct']:.2f}%</b><small>{no_addon['full']['units']} 份｜中位 {no_addon['full']['median_return_pct']:.2f}%</small></div><div class='metric'><span>加碼 full</span><b>{addon['full']['win_rate_pct']:.2f}% / {addon['full']['avg_return_pct']:.2f}%</b><small>{addon['full']['units']} 份｜未實現 {addon['full']['unresolved_rate_pct']:.2f}%</small></div><div class='metric'><span>加碼 random test</span><b>{addon['random_stock_test']['win_rate_pct']['mean']:.2f}% / {addon['random_stock_test']['avg_return_pct']['mean']:.2f}%</b><small>pass {addon['random_stock_test']['pass_60win_10avg_count']}/10</small></div></div><div class='warn'><strong>結論：</strong>加碼確實放大大波段報酬，但 deterministic stock-test 沒過 60% / 10%，random stock-test 只有 5/10 達標，且未實現部位太高。因此不可部署，只能 forward paper trade。</div></header><main><h2>比較表</h2><div class='table'><table><thead><tr><th>版本</th><th>Full</th><th>Deterministic stock-test</th><th>Random stock-test</th><th>加碼單</th><th>Package stock-test</th></tr></thead><tbody>{rows}</tbody></table></div><h2>有利證據</h2><ul>{positives}</ul><h2>部署阻礙</h2><ul>{blockers}</ul><div class='note'><strong>下一步：</strong>{html.escape(assessment['recommended_next_step'])}</div></main></body></html>"""


def render_md(payload: dict[str, Any]) -> str:
    assessment = payload["deployment_assessment"]
    lines = [
        f"# {VERSION}",
        "",
        f"Verdict: {assessment['label']}",
        "",
        "| Version | Full | Deterministic stock-test | Random stock-test | Add-on units | Package stock-test |",
        "|---|---|---|---|---|---|",
    ]
    for item in payload["comparison"]:
        lines.append(
            f"| {item['label']} | {summary_cell(item['full'])} | {summary_cell(item.get('deterministic_stock_test'))} | {summary_cell(item.get('random_stock_test'), random=True)} | {summary_cell(item.get('addon_units'))} | {summary_cell(item.get('package_stock_test'), package=True)} |"
        )
    lines += ["", "## Blockers"]
    lines += [f"- {item}" for item in assessment["blockers"]]
    lines += ["", "## Positives"]
    lines += [f"- {item}" for item in assessment["positives"]]
    return "\n".join(lines) + "\n"


def main() -> None:
    payload = run()
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    OUT_MD.write_text(render_md(payload), encoding="utf-8")
    print(json.dumps({
        "version": VERSION,
        "verdict": payload["deployment_assessment"],
        "comparison": payload["comparison"],
        "html": str(OUT_HTML),
        "json": str(OUT_JSON),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
