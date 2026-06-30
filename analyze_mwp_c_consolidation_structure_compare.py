#!/usr/bin/env python3
"""Compare slower trailing structure floors for MWP-C."""

from __future__ import annotations

import html
import json
import statistics
from pathlib import Path
from typing import Any

import analyze_pullback_pb_v23_independent_lifecycle as pbv23
from analyze_mwp_addon_strategy_comparison import strip_heavy
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
OUT_JSON = REPORT_DIR / "mwp_c_consolidation_structure_compare.json"
OUT_HTML = REPORT_DIR / "mwp_c_consolidation_structure_compare.html"
OUT_MD = REPORT_DIR / "mwp_c_consolidation_structure_compare.md"
VERSION = "MWP-C-consolidation-structure-compare"

CONSOLIDATION_WINDOW = 20
BBAND_WINDOW = 20
BBAND_STD_MULTIPLIER = 2.0


def rolling_lower_band(rows: list[pbv23.Row], cursor: int, window: int = BBAND_WINDOW, multiplier: float = BBAND_STD_MULTIPLIER) -> float | None:
    if cursor - window + 1 < 0:
        return None
    closes = [row.close for row in rows[cursor - window + 1 : cursor + 1]]
    if len(closes) < window:
        return None
    mean = statistics.mean(closes)
    stdev = statistics.pstdev(closes)
    return mean - multiplier * stdev


def generic_trailing_floor_exit(
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
    use_consolidation_floor: bool,
    use_bband_floor: bool,
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

        if current_structure_low is not None and confirm_index is not None and cursor > confirm_index:
            floor_candidates: list[tuple[str, float]] = []
            if use_consolidation_floor and cursor >= entry_index + CONSOLIDATION_WINDOW:
                window_rows = rows[cursor - CONSOLIDATION_WINDOW : cursor]
                if len(window_rows) == CONSOLIDATION_WINDOW:
                    prior_high = max(item.high for item in window_rows)
                    box_low = min(item.low for item in window_rows)
                    if row.close > prior_high and box_low > current_structure_low:
                        floor_candidates.append(("consolidation20_breakout", box_low))
            if use_bband_floor:
                lower_band = rolling_lower_band(rows, cursor)
                if lower_band is not None and lower_band > current_structure_low:
                    floor_candidates.append(("bband_lower20", lower_band))
            if floor_candidates:
                source, new_floor = max(floor_candidates, key=lambda item: item[1])
                if new_floor > current_structure_low:
                    current_structure_low = new_floor
                    updates.append({
                        "update_date": row.date,
                        "source": source,
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


def base_exit_consolidation20(
    entry: pbv23.Row,
    rows: list[pbv23.Row],
    indicators: dict[str, list[float | None]],
    signal_index: int,
    entry_index: int,
    confirm_index: int | None,
) -> dict[str, Any]:
    return generic_trailing_floor_exit(
        entry,
        rows,
        indicators,
        signal_index,
        entry_index,
        confirm_index,
        unit_prefix="base",
        catastrophic_close_pct=pbv23.STRUCTURAL_STOP["catastrophic_close_pct"],
        allow_hard_stop=True,
        policy_name="consolidation20_low",
        use_consolidation_floor=True,
        use_bband_floor=False,
    )


def addon_exit_consolidation20(
    entry: pbv23.Row,
    rows: list[pbv23.Row],
    indicators: dict[str, list[float | None]],
    signal_index: int,
    entry_index: int,
    confirm_index: int | None,
) -> dict[str, Any]:
    return generic_trailing_floor_exit(
        entry,
        rows,
        indicators,
        signal_index,
        entry_index,
        confirm_index,
        unit_prefix="addon",
        catastrophic_close_pct=pbv23.STRUCTURAL_STOP["catastrophic_close_pct"],
        allow_hard_stop=False,
        policy_name="consolidation20_low",
        use_consolidation_floor=True,
        use_bband_floor=False,
    )


def base_exit_bband_lower(
    entry: pbv23.Row,
    rows: list[pbv23.Row],
    indicators: dict[str, list[float | None]],
    signal_index: int,
    entry_index: int,
    confirm_index: int | None,
) -> dict[str, Any]:
    return generic_trailing_floor_exit(
        entry,
        rows,
        indicators,
        signal_index,
        entry_index,
        confirm_index,
        unit_prefix="base",
        catastrophic_close_pct=pbv23.STRUCTURAL_STOP["catastrophic_close_pct"],
        allow_hard_stop=True,
        policy_name="bband_lower20_only",
        use_consolidation_floor=False,
        use_bband_floor=True,
    )


def addon_exit_bband_lower(
    entry: pbv23.Row,
    rows: list[pbv23.Row],
    indicators: dict[str, list[float | None]],
    signal_index: int,
    entry_index: int,
    confirm_index: int | None,
) -> dict[str, Any]:
    return generic_trailing_floor_exit(
        entry,
        rows,
        indicators,
        signal_index,
        entry_index,
        confirm_index,
        unit_prefix="addon",
        catastrophic_close_pct=pbv23.STRUCTURAL_STOP["catastrophic_close_pct"],
        allow_hard_stop=False,
        policy_name="bband_lower20_only",
        use_consolidation_floor=False,
        use_bband_floor=True,
    )


def base_exit_consolidation20_bband(
    entry: pbv23.Row,
    rows: list[pbv23.Row],
    indicators: dict[str, list[float | None]],
    signal_index: int,
    entry_index: int,
    confirm_index: int | None,
) -> dict[str, Any]:
    return generic_trailing_floor_exit(
        entry,
        rows,
        indicators,
        signal_index,
        entry_index,
        confirm_index,
        unit_prefix="base",
        catastrophic_close_pct=pbv23.STRUCTURAL_STOP["catastrophic_close_pct"],
        allow_hard_stop=True,
        policy_name="consolidation20_plus_bband_lower20",
        use_consolidation_floor=True,
        use_bband_floor=True,
    )


def addon_exit_consolidation20_bband(
    entry: pbv23.Row,
    rows: list[pbv23.Row],
    indicators: dict[str, list[float | None]],
    signal_index: int,
    entry_index: int,
    confirm_index: int | None,
) -> dict[str, Any]:
    return generic_trailing_floor_exit(
        entry,
        rows,
        indicators,
        signal_index,
        entry_index,
        confirm_index,
        unit_prefix="addon",
        catastrophic_close_pct=pbv23.STRUCTURAL_STOP["catastrophic_close_pct"],
        allow_hard_stop=False,
        policy_name="consolidation20_plus_bband_lower20",
        use_consolidation_floor=True,
        use_bband_floor=True,
    )


def render_html(payload: dict[str, Any]) -> str:
    baseline = payload["strategies"][0]
    comparison_rows = "".join(
        f"<tr><th>{html.escape(row['label'])}</th>"
        f"<td>{html.escape(unit_cell(row['summary']['full_units']))}</td>"
        f"<td>{html.escape(unit_cell(row['summary']['base_units']))}</td>"
        f"<td>{html.escape(unit_cell(row['summary']['addon_units']))}</td>"
        f"<td>{html.escape(random_cell(row['random_unit_stock_test']))}</td>"
        f"<td>{fmt_count(row['structure_update_stats']['updated_units'])}</td>"
        f"<td>{fmt_count(row['structure_update_stats']['raised_structure_units'])}</td>"
        f"<td>{fmt_count(row['exit_family_counts'].get('structure_break', 0))}</td>"
        f"<td>{fmt_count(row['exit_family_counts'].get('hard_stop', 0))}</td></tr>"
        for row in payload["strategies"]
    )
    delta_rows = "".join(
        f"<tr><th>{html.escape(row['label'])}</th>"
        f"<td>{fmt_count(row['delta_vs_fixed']['full_units'])}</td>"
        f"<td>{pct(row['delta_vs_fixed']['full_avg_return_pct'])}</td>"
        f"<td>{pct(row['delta_vs_fixed']['full_win_rate_pct'])}</td>"
        f"<td>{fmt_money(row['delta_vs_fixed']['full_total_pnl'])}</td>"
        f"<td>{pct(row['delta_vs_fixed']['random_avg_return_pct'])}</td>"
        f"<td>{pct(row['delta_vs_fixed']['random_p25_return_pct'])}</td>"
        f"<td>{fmt_count(row['changed_vs_fixed']['count'])}</td></tr>"
        for row in payload["strategies"][1:]
    )
    return f"""<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{VERSION}</title><style>
:root{{--bg:#f6f7fb;--paper:#fff;--ink:#172033;--muted:#667085;--line:#e4e7ec;--blue:#2563eb}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 system-ui,'Microsoft JhengHei',sans-serif}}header,main{{max-width:1650px;margin:auto;padding:28px 20px}}header{{border-bottom:1px solid var(--line)}}h1{{margin:0 0 8px;font-size:30px}}h2{{margin:28px 0 10px}}p{{color:var(--muted)}}.note{{border-left:4px solid var(--blue);background:#eff6ff;padding:12px 14px;margin:18px 0;border-radius:12px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px}}.card{{background:#fff;border:1px solid var(--line);border-radius:14px;padding:14px}}.table{{overflow:auto;border:1px solid var(--line);background:#fff;border-radius:12px}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}thead th{{background:#f8fafc;color:var(--muted);font-size:12px}}code{{background:#eef2ff;padding:2px 6px;border-radius:6px}}</style></head><body><header><h1>MWP-C 20日整理低點 / BBand 比較</h1><p>比較較慢的波段級 trailing floor，檢查是否能比小 pivot 更接近你想要的波段防守線。</p><div class='note'><strong>20日整理低點版本：</strong>若當日收盤突破前一段 20 個交易日區間高點，就把那段 20 日區間的最低 low 往上鎖成新的 structure_low。<strong>BBand 版本：</strong>使用 20 日布林通道下軌 <code>MA20 - 2σ</code> 作為可上移的防守線，只允許往上抬，不往下降。三版都固定使用相同的 corrected-lifecycle formal MWP-C 框架。</div><div class='grid'><div class='card'><h3>{html.escape(baseline['label'])}</h3><p>{html.escape(unit_cell(baseline['summary']['full_units']))}</p><p>{html.escape(random_cell(baseline['random_unit_stock_test']))}</p></div>{''.join(f"<div class='card'><h3>{html.escape(row['label'])}</h3><p>{html.escape(unit_cell(row['summary']['full_units']))}</p><p>{html.escape(random_cell(row['random_unit_stock_test']))}</p></div>" for row in payload['strategies'][1:])}</div></header><main><h2>整體比較</h2><div class='table'><table><thead><tr><th>版本</th><th>Full units</th><th>Base units</th><th>Add-on units</th><th>Random unit stock-test</th><th>有動態更新的單位</th><th>真的抬高結構低點的單位</th><th>結構轉弱出場</th><th>硬停損</th></tr></thead><tbody>{comparison_rows}</tbody></table></div><h2>相對固定版差異</h2><div class='table'><table><thead><tr><th>版本</th><th>Units 差</th><th>Full 平均差</th><th>Full 勝率差</th><th>總損益差</th><th>Random 平均差</th><th>Random p25 差</th><th>結果被改寫的單位</th></tr></thead><tbody>{delta_rows}</tbody></table></div><p>JSON: <code>{OUT_JSON}</code>｜MD: <code>{OUT_MD}</code></p></main></body></html>"""


def render_md(payload: dict[str, Any]) -> str:
    lines = [
        "# MWP-C 20日整理低點 / BBand 比較",
        "",
        f"- 20日整理低點：收盤突破前 20 日區間高點後，把前 20 日區間最低 low 上移成新的 structure_low。",
        f"- BBand 下軌：20 日布林下軌 = MA20 - {BBAND_STD_MULTIPLIER:.1f} * 標準差。",
        "",
        "## 整體結果",
    ]
    for row in payload["strategies"]:
        lines.extend([
            f"### {row['label']}",
            f"- 說明：{row['description']}",
            f"- Full units：{unit_cell(row['summary']['full_units'])}",
            f"- Base units：{unit_cell(row['summary']['base_units'])}",
            f"- Add-on units：{unit_cell(row['summary']['addon_units'])}",
            f"- Random unit stock-test：{random_cell(row['random_unit_stock_test'])}",
            f"- 動態更新單位：{row['structure_update_stats']['updated_units']}，抬高結構低點單位：{row['structure_update_stats']['raised_structure_units']}",
            f"- 出場組成：{json.dumps(row['exit_family_counts'], ensure_ascii=False)}",
            "",
        ])
    lines.append("## 相對固定版差異")
    for row in payload["strategies"][1:]:
        delta = row["delta_vs_fixed"]
        changed = row["changed_vs_fixed"]
        lines.extend([
            f"### {row['label']}",
            f"- Units 差：{delta['full_units']}",
            f"- Full 平均差：{pct(delta['full_avg_return_pct'])}",
            f"- Full 勝率差：{pct(delta['full_win_rate_pct'])}",
            f"- 總損益差：{fmt_money(delta['full_total_pnl'])}",
            f"- Random 平均差：{pct(delta['random_avg_return_pct'])}",
            f"- Random p25 差：{pct(delta['random_p25_return_pct'])}",
            f"- 被改寫單位：{changed['count']}，改善 {changed['improved_count']}，惡化 {changed['worsened_count']}，合計損益差 {fmt_money(changed['total_pnl_delta'])}",
            "",
        ])
    return "\n".join(lines) + "\n"


def main() -> None:
    strategies = [
        build_record(
            "固定 structure_low（現行版）",
            "結構低點固定鎖在訊號日至確認K區間最低 low，不會隨後續上漲而上移。",
            base_exit_fixed,
            addon_exit_fixed,
        ),
        build_record(
            "20日整理低點上移",
            "若收盤突破前 20 日區間高點，就把前 20 日區間最低 low 鎖成新的 structure_low，模擬較大一級的橫盤整理低點。",
            base_exit_consolidation20,
            addon_exit_consolidation20,
        ),
        build_record(
            "BBand 20日下軌上移",
            "用 20 日布林通道下軌當成可上移的防守線，只允許往上抬，不往下降。",
            base_exit_bband_lower,
            addon_exit_bband_lower,
        ),
        build_record(
            "20日整理低點 + BBand 下軌",
            "同時觀察 20 日整理區低點與 BBand 20 日下軌，取較高者作為新的 trailing floor。",
            base_exit_consolidation20_bband,
            addon_exit_consolidation20_bband,
        ),
    ]
    baseline = strategies[0]
    for row in strategies[1:]:
        row["delta_vs_fixed"] = summary_delta(row, baseline)
        row["changed_vs_fixed"] = changed_units(baseline, row)
    payload = {
        "version": VERSION,
        "parameters": {
            "consolidation_window": CONSOLIDATION_WINDOW,
            "bband_window": BBAND_WINDOW,
            "bband_std_multiplier": BBAND_STD_MULTIPLIER,
        },
        "shared_rules": "Formal MWP-C framework held fixed: PB-V4 discount-2 mother pool, MA20 5-day slope > 0, max 1 add-on, MA20 retest band 1.9%, same-stock lifecycle filter, mother exit synchronizes remaining add-ons.",
        "strategies": [strip_heavy(row) for row in strategies],
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    OUT_MD.write_text(render_md(payload), encoding="utf-8")
    print(json.dumps({
        "output": str(OUT_JSON),
        "html": str(OUT_HTML),
        "strategies": [
            {
                "label": row["label"],
                "full_units": row["summary"]["full_units"],
                "random_unit_stock_test": row["random_unit_stock_test"],
                "structure_update_stats": row["structure_update_stats"],
                "delta_vs_fixed": row.get("delta_vs_fixed"),
            }
            for row in payload["strategies"]
        ],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
