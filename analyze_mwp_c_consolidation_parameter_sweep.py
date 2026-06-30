#!/usr/bin/env python3
"""Sweep consolidation-floor parameters for MWP-C."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

import analyze_pullback_pb_v23_independent_lifecycle as pbv23
from analyze_mwp_addon_strategy_comparison import strip_heavy
from analyze_mwp_c_consolidation_structure_compare import (
    OUT_JSON as _UNUSED,
)  # keep import grouping stable
from analyze_mwp_c_dynamic_structure_compare import (
    addon_exit_fixed,
    base_exit_fixed,
    build_record,
    changed_units,
    fmt_count,
    fmt_money,
    pct,
    random_cell,
    summary_delta,
    unit_cell,
    with_structure_meta,
)

REPORT_DIR = Path("reports")
OUT_JSON = REPORT_DIR / "mwp_c_consolidation_parameter_sweep.json"
OUT_HTML = REPORT_DIR / "mwp_c_consolidation_parameter_sweep.html"
OUT_MD = REPORT_DIR / "mwp_c_consolidation_parameter_sweep.md"
VERSION = "MWP-C-consolidation-parameter-sweep"

WINDOWS = [15, 20, 30]
BREAKOUT_MODES = ["close", "high"]
SCOPES = ["base_only", "base_and_addon"]


def consolidation_floor_exit(
    entry: pbv23.Row,
    rows: list[pbv23.Row],
    indicators: dict[str, list[float | None]],
    signal_index: int,
    entry_index: int,
    confirm_index: int | None,
    *,
    unit_prefix: str,
    catastrophic_close_pct: float,
    allow_hard_stop: bool,
    policy_name: str,
    consolidation_window: int,
    breakout_mode: str,
) -> dict[str, Any]:
    levels = pbv23.structural_levels(rows, signal_index, confirm_index) if confirm_index is not None else None
    initial_structure_low = float(levels["structure_low"]) if levels else None
    current_structure_low = initial_structure_low
    hard_stop = entry.open * (1 - pbv23.BASE_HARD_STOP_PCT) if allow_hard_stop else None
    updates: list[dict[str, Any]] = []
    observed: list[pbv23.Row] = []
    for cursor in range(entry_index, len(rows)):
        row = rows[cursor]
        observed.append(row)
        if allow_hard_stop and hard_stop is not None:
            if row.open <= hard_stop:
                return with_structure_meta(
                    pbv23.return_result(entry, observed, row.open, f"{unit_prefix}_gap_hard_stop7"),
                    initial_structure_low,
                    current_structure_low,
                    updates,
                    policy_name,
                )
            if row.low <= hard_stop:
                return with_structure_meta(
                    pbv23.return_result(entry, observed, hard_stop, f"{unit_prefix}_hard_stop7"),
                    initial_structure_low,
                    current_structure_low,
                    updates,
                    policy_name,
                )

        if current_structure_low is not None and confirm_index is not None and cursor > confirm_index and cursor >= entry_index + consolidation_window:
            window_rows = rows[cursor - consolidation_window : cursor]
            if len(window_rows) == consolidation_window:
                prior_high = max(item.high for item in window_rows)
                box_low = min(item.low for item in window_rows)
                breakout_passed = row.close > prior_high if breakout_mode == "close" else row.high > prior_high
                if breakout_passed and box_low > current_structure_low:
                    current_structure_low = box_low
                    updates.append({
                        "update_date": row.date,
                        "source": f"consolidation{consolidation_window}_{breakout_mode}",
                        "structure_low_after_update": round(current_structure_low, 4),
                    })

        if current_structure_low is None or confirm_index is None or cursor <= confirm_index:
            continue
        ma20 = indicators["ma20"][cursor]
        if ma20 is None:
            continue
        if row.close <= entry.open * (1 - catastrophic_close_pct):
            return with_structure_meta(
                pbv23.close_execution_result(entry, observed, rows, cursor, "next_open", f"{unit_prefix}_catastrophic_close_stop"),
                initial_structure_low,
                current_structure_low,
                updates,
                policy_name,
            )
        if row.close < ma20 and row.close < current_structure_low:
            return with_structure_meta(
                pbv23.close_execution_result(entry, observed, rows, cursor, "next_open", f"{unit_prefix}_consolidation_structure_close_break"),
                initial_structure_low,
                current_structure_low,
                updates,
                policy_name,
            )
    return with_structure_meta(
        pbv23.return_result(entry, observed, observed[-1].close, "latest_close", unresolved=True),
        initial_structure_low,
        current_structure_low,
        updates,
        policy_name,
    )


def make_base_exit(consolidation_window: int, breakout_mode: str):
    def _exit(
        entry: pbv23.Row,
        rows: list[pbv23.Row],
        indicators: dict[str, list[float | None]],
        signal_index: int,
        entry_index: int,
        confirm_index: int | None,
    ) -> dict[str, Any]:
        return consolidation_floor_exit(
            entry,
            rows,
            indicators,
            signal_index,
            entry_index,
            confirm_index,
            unit_prefix="base",
            catastrophic_close_pct=pbv23.STRUCTURAL_STOP["catastrophic_close_pct"],
            allow_hard_stop=True,
            policy_name=f"consolidation{consolidation_window}_{breakout_mode}_base",
            consolidation_window=consolidation_window,
            breakout_mode=breakout_mode,
        )
    return _exit


def make_addon_exit(consolidation_window: int, breakout_mode: str):
    def _exit(
        entry: pbv23.Row,
        rows: list[pbv23.Row],
        indicators: dict[str, list[float | None]],
        signal_index: int,
        entry_index: int,
        confirm_index: int | None,
    ) -> dict[str, Any]:
        return consolidation_floor_exit(
            entry,
            rows,
            indicators,
            signal_index,
            entry_index,
            confirm_index,
            unit_prefix="addon",
            catastrophic_close_pct=pbv23.STRUCTURAL_STOP["catastrophic_close_pct"],
            allow_hard_stop=False,
            policy_name=f"consolidation{consolidation_window}_{breakout_mode}_addon",
            consolidation_window=consolidation_window,
            breakout_mode=breakout_mode,
        )
    return _exit


def score_row(row: dict[str, Any]) -> float:
    full = row["summary"]["full_units"]
    random_stats = row["random_unit_stock_test"]
    return round(
        float(random_stats["avg_return_pct"]["mean"])
        + 0.30 * float(random_stats["avg_return_pct"]["p25"])
        + 0.08 * float(full["win_rate_pct"])
        - 0.03 * float(full["unresolved"]),
        4,
    )


def variant_label(window: int, breakout_mode: str, scope: str) -> str:
    trigger = "收盤突破" if breakout_mode == "close" else "盤中高點突破"
    apply_scope = "只套母單" if scope == "base_only" else "母單+加碼都套"
    return f"{window}日整理低點｜{trigger}｜{apply_scope}"


def variant_description(window: int, breakout_mode: str, scope: str) -> str:
    trigger = "當日收盤 > 前區間高點" if breakout_mode == "close" else "當日最高價 > 前區間高點"
    scope_text = "只有母單採用動態整理低點；加碼維持固定 structure_low。" if scope == "base_only" else "母單與加碼都採用動態整理低點。"
    return f"回看前 {window} 個交易日，若 {trigger}，就把前 {window} 日區間最低 low 鎖成新的 structure_low。{scope_text}"


def render_html(payload: dict[str, Any]) -> str:
    baseline = payload["baseline"]
    rows = ""
    for row in payload["variants"]:
        rows += (
            f"<tr><th>{html.escape(row['label'])}</th>"
            f"<td>{html.escape(unit_cell(row['summary']['full_units']))}</td>"
            f"<td>{html.escape(random_cell(row['random_unit_stock_test']))}</td>"
            f"<td>{fmt_count(row['structure_update_stats']['updated_units'])}</td>"
            f"<td>{fmt_count(row['summary']['full_units']['unresolved'])}</td>"
            f"<td>{pct(row['delta_vs_fixed']['full_avg_return_pct'])}</td>"
            f"<td>{fmt_money(row['delta_vs_fixed']['full_total_pnl'])}</td>"
            f"<td>{pct(row['delta_vs_fixed']['random_avg_return_pct'])}</td>"
            f"<td>{pct(row['delta_vs_fixed']['random_p25_return_pct'])}</td>"
            f"<td>{row['score_return_balance']:.2f}</td></tr>"
        )
    best = payload["best_by_score"]
    return f"""<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{VERSION}</title><style>
:root{{--bg:#f6f7fb;--paper:#fff;--ink:#172033;--muted:#667085;--line:#e4e7ec;--blue:#2563eb}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 system-ui,'Microsoft JhengHei',sans-serif}}header,main{{max-width:1700px;margin:auto;padding:28px 20px}}header{{border-bottom:1px solid var(--line)}}h1{{margin:0 0 8px;font-size:30px}}h2{{margin:28px 0 10px}}p{{color:var(--muted)}}.note{{border-left:4px solid var(--blue);background:#eff6ff;padding:12px 14px;margin:18px 0;border-radius:12px}}.card{{background:#fff;border:1px solid var(--line);border-radius:14px;padding:14px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px}}.table{{overflow:auto;border:1px solid var(--line);background:#fff;border-radius:12px}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}thead th{{background:#f8fafc;color:var(--muted);font-size:12px}}code{{background:#eef2ff;padding:2px 6px;border-radius:6px}}</style></head><body><header><h1>MWP-C 整理低點參數掃描</h1><p>比較整理視窗 15 / 20 / 30、突破方式 high / close、以及套用範圍 base only / base+addon。</p><div class='note'><strong>Baseline：</strong>{html.escape(unit_cell(baseline['summary']['full_units']))}｜Random {html.escape(random_cell(baseline['random_unit_stock_test']))}<br><strong>目前平衡分數最佳：</strong>{html.escape(best['label'])}。這個分數偏重 Random 平均、Random p25、Full 勝率，並對未實現數量做輕度扣分，只用來幫助排序，不代表正式策略已決定。</div></header><main><div class='table'><table><thead><tr><th>版本</th><th>Full units</th><th>Random unit stock-test</th><th>有動態更新的單位</th><th>未實現</th><th>Full 平均差</th><th>總損益差</th><th>Random 平均差</th><th>Random p25 差</th><th>平衡分數</th></tr></thead><tbody>{rows}</tbody></table></div><p>JSON: <code>{OUT_JSON}</code>｜MD: <code>{OUT_MD}</code></p></main></body></html>"""


def render_md(payload: dict[str, Any]) -> str:
    lines = [
        "# MWP-C 整理低點參數掃描",
        "",
        f"- Baseline：{unit_cell(payload['baseline']['summary']['full_units'])}",
        f"- Baseline Random：{random_cell(payload['baseline']['random_unit_stock_test'])}",
        "",
        "## 版本比較",
    ]
    for row in payload["variants"]:
        lines.extend([
            f"### {row['label']}",
            f"- 說明：{row['description']}",
            f"- Full：{unit_cell(row['summary']['full_units'])}",
            f"- Random：{random_cell(row['random_unit_stock_test'])}",
            f"- 更新單位：{row['structure_update_stats']['updated_units']}",
            f"- Full 平均差：{pct(row['delta_vs_fixed']['full_avg_return_pct'])}",
            f"- 總損益差：{fmt_money(row['delta_vs_fixed']['full_total_pnl'])}",
            f"- Random 平均差：{pct(row['delta_vs_fixed']['random_avg_return_pct'])}",
            f"- Random p25 差：{pct(row['delta_vs_fixed']['random_p25_return_pct'])}",
            f"- 平衡分數：{row['score_return_balance']:.2f}",
            "",
        ])
    return "\n".join(lines) + "\n"


def main() -> None:
    baseline = build_record(
        "固定 structure_low（現行版）",
        "結構低點固定鎖在訊號日至確認K區間最低 low，不會隨後續上漲而上移。",
        base_exit_fixed,
        addon_exit_fixed,
    )
    variants: list[dict[str, Any]] = []
    for window in WINDOWS:
        for breakout_mode in BREAKOUT_MODES:
            for scope in SCOPES:
                base_exit = make_base_exit(window, breakout_mode)
                addon_exit = addon_exit_fixed if scope == "base_only" else make_addon_exit(window, breakout_mode)
                row = build_record(
                    variant_label(window, breakout_mode, scope),
                    variant_description(window, breakout_mode, scope),
                    base_exit,
                    addon_exit,
                )
                row["parameters"] = {
                    "window": window,
                    "breakout_mode": breakout_mode,
                    "scope": scope,
                }
                row["delta_vs_fixed"] = summary_delta(row, baseline)
                row["changed_vs_fixed"] = changed_units(baseline, row)
                row["score_return_balance"] = score_row(row)
                variants.append(row)
    variants.sort(key=lambda row: row["score_return_balance"], reverse=True)
    payload = {
        "version": VERSION,
        "baseline": strip_heavy(baseline),
        "variants": [strip_heavy(row) for row in variants],
        "best_by_score": strip_heavy(variants[0]),
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    OUT_MD.write_text(render_md(payload), encoding="utf-8")
    print(json.dumps({
        "output": str(OUT_JSON),
        "html": str(OUT_HTML),
        "best_by_score": {
            "label": variants[0]["label"],
            "score_return_balance": variants[0]["score_return_balance"],
            "full_units": variants[0]["summary"]["full_units"],
            "random_unit_stock_test": variants[0]["random_unit_stock_test"],
            "delta_vs_fixed": variants[0]["delta_vs_fixed"],
        },
        "top5": [
            {
                "label": row["label"],
                "score": row["score_return_balance"],
                "delta_vs_fixed": row["delta_vs_fixed"],
                "full_units": row["summary"]["full_units"],
            }
            for row in variants[:5]
        ],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
