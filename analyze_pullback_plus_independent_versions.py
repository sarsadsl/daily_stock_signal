#!/usr/bin/env python3
"""Rerun V8/V9/V10/V14/V18 as independent plus versions with stock holdout splits."""

from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
from typing import Any

from analyze_pullback_core_position import (
    EXIT_LABELS,
    ma20_core_exit,
    stats,
    weekly_core_exit,
    wide_trail_exit,
)
from analyze_pullback_multitimeframe_search import (
    BENCHMARK_CSV,
    add_benchmark_return,
    enrich_trades,
    extended_summary,
    rule_label,
    rules,
    select,
)
from analyze_pullback_pb_v13_frozen_3y import build_trade_sets
from analyze_pullback_pb_v14_market_gate import add_market_gate as add_v14_market_gate
from analyze_pullback_pb_v15_all_signal_history import attach_prior_only_scores, enrich_all_three_year_signals
from analyze_pullback_pb_v17_two_stage_runner import replay, signal_rank, simulate_two_stage
from analyze_pullback_pb_v18_finite_capital import (
    STRESS_SLIPPAGE_EACH_SIDE_PCT,
    adjusted_rows,
    select_finite_portfolio,
)
from analyze_pullback_rolling_climax import variant_rows
from analyze_pullback_technical_phenotypes import find_series, make_series_map
from run_market_backtest import Row, csv_files, read_rows


REPORT_DIR = Path("reports")
OUT_JSON = REPORT_DIR / "pullback_plus_independent_versions.json"
OUT_HTML = REPORT_DIR / "pullback_plus_independent_versions.html"
VERSION = "PB-plus-independent-stock-holdout"
POSITION_SIZE = 100_000

V9_ENTRY_RULE = {
    "structure": "abc_fast",
    "market": "all",
    "weekly": "all",
    "monthly": "trend",
    "signal": "controlled",
    "top_n": 0,
}

INDEPENDENT_EXIT_STYLES = ("v17_runner", "ma20_core", "weekly_core", "wide_trail")
INDEPENDENT_EXIT_LABELS = {
    "v17_runner": "V17 兩段式 runner",
    "ma20_core": EXIT_LABELS["ma20_core"],
    "weekly_core": EXIT_LABELS["weekly_core"],
    "wide_trail": EXIT_LABELS["wide_trail"],
}


def stock_key(row: dict[str, Any]) -> str:
    return f"{row.get('market')}:{row.get('stock_no')}"


def stock_groups(rows: list[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
    stocks = sorted({stock_key(row) for row in rows})
    ranked = sorted(stocks, key=lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest())
    train_end = round(len(ranked) * 0.60)
    validation_end = round(len(ranked) * 0.80)
    groups = {
        "stock_train": set(ranked[:train_end]),
        "stock_validation": set(ranked[train_end:validation_end]),
        "stock_test": set(ranked[validation_end:]),
    }
    return (
        {name: [row for row in rows if stock_key(row) in keys] for name, keys in groups.items()} | {"full": rows},
        {name: len(keys) for name, keys in groups.items()} | {"full": len(stocks)},
    )


def target_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary = extended_summary(rows)
    summary["unresolved"] = sum(bool(row.get("unresolved")) for row in rows)
    return summary


def unit_pnl(row: dict[str, Any]) -> int:
    return round(float(row["return_pct"]) / 100 * POSITION_SIZE)


def compute_independent_exits(base_trades: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    series = make_series_map(csv_files())
    benchmark_rows = read_rows(BENCHMARK_CSV)
    benchmark_dates = {row.date: index for index, row in enumerate(benchmark_rows)}
    output = {style: [] for style in INDEPENDENT_EXIT_STYLES}
    for trade in base_trades:
        bundle = find_series(series, str(trade["market"]), str(trade["stock_no"]))
        if not bundle:
            continue
        rows, indicators, dates = bundle
        signal_index = dates.get(str(trade["signal_date"]))
        if signal_index is None or signal_index + 1 >= len(rows):
            continue
        entry_index = signal_index + 1
        entry = rows[entry_index]
        exits = {
            "v17_runner": simulate_two_stage(entry, rows, entry_index),
            "ma20_core": ma20_core_exit(entry, rows, indicators, entry_index),
            "weekly_core": weekly_core_exit(entry, rows, entry_index),
            "wide_trail": wide_trail_exit(entry, rows, entry_index),
        }
        for style, result in exits.items():
            row = {
                **trade,
                **result,
                "entry_date": entry.date,
                "entry_price": round(entry.open, 4),
                "exit_style": style,
                "exit_label": INDEPENDENT_EXIT_LABELS[style],
            }
            row["pnl"] = unit_pnl(row)
            add_benchmark_return(row, benchmark_rows, benchmark_dates)
            output[style].append(row)
    return output


def selection_score(train: dict[str, Any], validation: dict[str, Any]) -> float:
    worst_win = min(train["win_rate_pct"], validation["win_rate_pct"])
    worst_avg = min(train["avg_return_pct"], validation["avg_return_pct"])
    worst_median = min(train["median_return_pct"], validation["median_return_pct"])
    shortfall = max(60 - worst_win, 0) * 0.9 + max(10 - worst_avg, 0) * 2.0
    instability = abs(train["win_rate_pct"] - validation["win_rate_pct"]) * 0.12 + abs(train["avg_return_pct"] - validation["avg_return_pct"]) * 0.6
    unresolved_penalty = (train.get("unresolved", 0) + validation.get("unresolved", 0)) * 0.25
    sample_bonus = min(train["trades"] + validation["trades"], 90) * 0.05
    return worst_win * 0.35 + worst_avg * 2.2 + worst_median * 0.5 + sample_bonus - shortfall - instability - unresolved_penalty


def summarize_rule_by_stock(rows: list[dict[str, Any]], rule: dict[str, Any]) -> dict[str, Any]:
    groups, counts = stock_groups(rows)
    selected = {name: select(group_rows, rule) for name, group_rows in groups.items()}
    summaries = {name: target_summary(group_rows) for name, group_rows in selected.items()}
    return {"stock_counts": counts, "selected": selected, "summaries": summaries}


def run_v8_plus(enriched: list[dict[str, Any]], independent_exits: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    runner_rows = independent_exits["v17_runner"]
    groups, counts = stock_groups(runner_rows)
    candidates = []
    full_hits = []
    for rule in rules():
        selected = {name: select(group_rows, rule) for name, group_rows in groups.items()}
        summaries = {name: target_summary(group_rows) for name, group_rows in selected.items()}
        if summaries["full"]["trades"] >= 30 and summaries["full"]["win_rate_pct"] >= 60 and summaries["full"]["avg_return_pct"] >= 10:
            full_hits.append({"rule": rule, "label": rule_label(rule), "summaries": summaries})
        if summaries["stock_train"]["trades"] < 20 or summaries["stock_validation"]["trades"] < 8:
            continue
        candidates.append({
            "score": selection_score(summaries["stock_train"], summaries["stock_validation"]),
            "rule": rule,
            "label": rule_label(rule),
            "summaries": summaries,
        })
    candidates.sort(key=lambda item: item["score"], reverse=True)
    chosen = candidates[0]
    return {
        "version": "PB-V8+",
        "definition": "V8 entry-search modules rerun with stock 60/20/20 split and V17 independent runner exit instead of PB-V4 exit dates.",
        "old_contamination": "Original V8 enriched PB-V4 trades and evaluated candidate entries using PB-V4 exit dates.",
        "exit_style": "v17_runner",
        "stock_counts": counts,
        "candidate_count": len(rules()),
        "eligible_candidate_count": len(candidates),
        "chosen": chosen,
        "top_full_hits": sorted(full_hits, key=lambda item: item["summaries"]["full"]["avg_return_pct"], reverse=True)[:20],
    }


def run_v9_plus(enriched: list[dict[str, Any]], independent_exits: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    selected_features = select(enriched, V9_ENTRY_RULE)
    selected_keys = {(row["signal_date"], row["market"], row["stock_no"]) for row in selected_features}
    styles = {}
    for style, rows in independent_exits.items():
        style_rows = [row for row in rows if (row["signal_date"], row["market"], row["stock_no"]) in selected_keys]
        groups, counts = stock_groups(style_rows)
        summaries = {name: target_summary(group_rows) for name, group_rows in groups.items()}
        styles[style] = {
            "exit_label": INDEPENDENT_EXIT_LABELS[style],
            "stock_counts": counts,
            "summaries": summaries,
            "score": selection_score(summaries["stock_train"], summaries["stock_validation"]),
            "rows": style_rows,
        }
    chosen_style = max(styles, key=lambda key: styles[key]["score"])
    return {
        "version": "PB-V9+",
        "definition": "V9 fixed entry rule rerun with only independent exits; PB-V4 tactical and PB-V4 hybrid exits are removed.",
        "old_contamination": "Original V9 included PB-V4 tactical exit and hybrids that blended PB-V4 exit dates with core exits; splits were chronological.",
        "entry_rule": V9_ENTRY_RULE,
        "entry_label": rule_label(V9_ENTRY_RULE),
        "chosen_exit_style": chosen_style,
        "styles": {key: {k: v for k, v in value.items() if k != "rows"} for key, value in styles.items()},
    }


def run_v10_plus(independent_exits: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    candidates = []
    full_hits = []
    for style, rows in independent_exits.items():
        groups, counts = stock_groups(rows)
        for rule in rules():
            selected = {name: select(group_rows, rule) for name, group_rows in groups.items()}
            summaries = {name: target_summary(group_rows) for name, group_rows in selected.items()}
            record = {
                "entry_rule": rule,
                "entry_label": rule_label(rule),
                "exit_style": style,
                "exit_label": INDEPENDENT_EXIT_LABELS[style],
                "stock_counts": counts,
                "summaries": summaries,
            }
            full = summaries["full"]
            if full["trades"] >= 30 and full["win_rate_pct"] >= 60 and full["avg_return_pct"] >= 10 and full["unresolved"] <= 2:
                full_hits.append(record)
            if summaries["stock_train"]["trades"] < 20 or summaries["stock_validation"]["trades"] < 8:
                continue
            if min(summaries["stock_train"]["win_rate_pct"], summaries["stock_validation"]["win_rate_pct"]) < 55:
                continue
            record["score"] = selection_score(summaries["stock_train"], summaries["stock_validation"])
            candidates.append(record)
    candidates.sort(key=lambda item: item["score"], reverse=True)
    chosen = candidates[0]
    return {
        "version": "PB-V10+",
        "definition": "Joint entry/exit search rerun on stock 60/20/20 splits with only independent exits.",
        "old_contamination": "Original V10 inherited V8 PB-V4 exit evaluation and V9 PB-V4 tactical/hybrid exits, and used chronological splits.",
        "candidate_count": len(rules()) * len(INDEPENDENT_EXIT_STYLES),
        "eligible_candidate_count": len(candidates),
        "chosen": chosen,
        "top_full_hits_low_unresolved": sorted(
            full_hits,
            key=lambda item: (item["summaries"]["full"]["trades"], item["summaries"]["full"]["avg_return_pct"]),
            reverse=True,
        )[:20],
    }


def run_v14_plus() -> dict[str, Any]:
    _, wide_rows = build_trade_sets()
    add_v14_market_gate(wide_rows)
    selected = [row for row in wide_rows if row.get("primary_uptrend")]
    groups, counts = stock_groups(selected)
    summaries = {name: target_summary(group_rows) for name, group_rows in groups.items()}
    return {
        "version": "PB-V14+",
        "definition": "Original V14 three-year 0050 primary-uptrend gate retained, with the independent PB-V13 frozen wide exit and stock 60/20/20 validation.",
        "old_contamination": "V14 wide exit did not inherit PB-V4 exit dates, but its report still relied on chronological/regime periods rather than the requested stock holdout.",
        "stock_counts": counts,
        "selected_trades": len(selected),
        "summaries": summaries,
    }


def run_v18_plus(enriched: list[dict[str, Any]]) -> dict[str, Any]:
    historical, _ = enrich_all_three_year_signals()
    one_year = [dict(row) for row in enriched]
    attach_prior_only_scores(one_year, historical)
    candidates = variant_rows(one_year, "avoid_score4")
    exits = replay(candidates, make_series_map(csv_files()), BENCHMARK_CSV)
    groups, counts = stock_groups(exits)
    portfolios = {name: select_finite_portfolio(group_rows) for name, group_rows in groups.items()}
    stress_summaries = {name: stats(adjusted_rows(rows, STRESS_SLIPPAGE_EACH_SIDE_PCT)) for name, rows in portfolios.items()}
    gross_summaries = {name: stats(rows) for name, rows in portfolios.items()}
    return {
        "version": "PB-V18+",
        "definition": "Original V18 entry, ranking, finite-position selection, and V17 runner exit retained; validation is rerun as stock 60/20/20 groups instead of chronological dates.",
        "old_contamination": "V18 exit itself was independent via V17 runner, but train/validation/test reporting was chronological and therefore not the requested stock holdout.",
        "stock_counts": counts,
        "eligible_exits": len(exits),
        "portfolio_counts": {name: len(rows) for name, rows in portfolios.items()},
        "gross_summaries": gross_summaries,
        "stress_summaries": stress_summaries,
        "portfolio_trades": portfolios["full"],
    }


def compact(summary: dict[str, Any], label: str = "trades") -> str:
    count = summary.get(label, summary.get("trades", 0))
    return (
        f"{count} | 勝率 {summary['win_rate_pct']:.2f}% | 平均 {summary['avg_return_pct']:.2f}% | "
        f"中位 {summary['median_return_pct']:.2f}% | 未實現 {summary.get('unresolved', 0)}"
    )


def run() -> dict[str, Any]:
    enriched, _ = enrich_trades()
    independent_exits = compute_independent_exits(enriched)
    return {
        "version": VERSION,
        "methodology": {
            "stock_split": "All plus versions use deterministic stock-identity 60/20/20 groups. The same stock cannot appear in more than one split.",
            "entry_source": "V8/V9/V10/V18+ use the original one-year PB-V4 discount-2 signal universe as their signal source; V14+ keeps V14's original three-year PB-V11/PB-V12 universe.",
            "independent_exits": INDEPENDENT_EXIT_LABELS,
            "v8_plus_exit_note": "V8 did not define its own exit; V8+ therefore pairs the V8 entry-search modules with the independent V17 runner as an executable baseline.",
        },
        "audit": {
            "V8": "contaminated: PB-V4 exits were used for entry-filter scoring and chronological splits were used.",
            "V9": "partly contaminated: independent MA20/weekly/wide exits existed, but PB-V4 tactical and PB-V4 hybrids were part of the comparison and chronological splits were used.",
            "V10": "contaminated by inheritance: joint search used V8/V9 data including PB-V4 tactical/hybrid exits and chronological splits.",
            "V14": "exit independent, split not compliant: V14's wide exit was independent, but evaluation was chronological/regime-based rather than stock-holdout based.",
            "V18": "exit independent, split not compliant: V18 used V17 runner exits but reported chronological train/validation/test.",
        },
        "universe": {
            "enriched_signals": len(enriched),
            "independent_exit_rows": {style: len(rows) for style, rows in independent_exits.items()},
        },
        "v8_plus": run_v8_plus(enriched, independent_exits),
        "v9_plus": run_v9_plus(enriched, independent_exits),
        "v10_plus": run_v10_plus(independent_exits),
        "v14_plus": run_v14_plus(),
        "v18_plus": run_v18_plus(enriched),
    }


def render_html(payload: dict[str, Any]) -> str:
    v8 = payload["v8_plus"]
    v9 = payload["v9_plus"]
    v10 = payload["v10_plus"]
    v14 = payload["v14_plus"]
    v18 = payload["v18_plus"]
    rows = []
    rows.append((
        "V8+",
        v8["definition"],
        v8["chosen"]["label"] + " / " + INDEPENDENT_EXIT_LABELS[v8["exit_style"]],
        v8["chosen"]["summaries"],
    ))
    rows.append((
        "V9+",
        v9["definition"],
        v9["entry_label"] + " / " + v9["styles"][v9["chosen_exit_style"]]["exit_label"],
        v9["styles"][v9["chosen_exit_style"]]["summaries"],
    ))
    rows.append((
        "V10+",
        v10["definition"],
        v10["chosen"]["entry_label"] + " / " + v10["chosen"]["exit_label"],
        v10["chosen"]["summaries"],
    ))
    rows.append((
        "V14+",
        v14["definition"],
        "0050 主升段閘門 / PB-V13 frozen wide exit",
        v14["summaries"],
    ))
    comparison_rows = "".join(
        f"<tr><th>{html.escape(version)}</th><td>{html.escape(definition)}</td><td>{html.escape(rule)}</td>"
        f"<td>{html.escape(compact(summaries['stock_train']))}</td>"
        f"<td>{html.escape(compact(summaries['stock_validation']))}</td>"
        f"<td>{html.escape(compact(summaries['stock_test']))}</td>"
        f"<td>{html.escape(compact(summaries['full']))}</td></tr>"
        for version, definition, rule, summaries in rows
    )
    v18_rows = "".join(
        f"<tr><th>{html.escape(name)}</th><td>{v18['stock_counts'].get(name, '-')}</td><td>{v18['portfolio_counts'].get(name, '-')}</td>"
        f"<td>{html.escape(compact(v18['gross_summaries'][name]))}</td>"
        f"<td>{html.escape(compact(v18['stress_summaries'][name]))}</td></tr>"
        for name in ("stock_train", "stock_validation", "stock_test", "full")
    )
    audit_rows = "".join(
        f"<tr><th>{html.escape(version)}</th><td>{html.escape(text)}</td></tr>"
        for version, text in payload["audit"].items()
    )
    return f"""<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Pullback Plus 獨立版本重算</title><style>
:root{{--bg:#f7f7f2;--paper:#fff;--ink:#17211d;--muted:#65716b;--line:#dfe5df;--good:#08735d;--bad:#a13e34;--accent:#1f6a73}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 system-ui,'Microsoft JhengHei',sans-serif}}header,main{{max-width:1500px;margin:auto;padding:24px 16px}}header{{border-bottom:1px solid var(--line)}}h1{{margin:0 0 8px;font-size:28px}}h2{{font-size:19px;margin:28px 0 10px}}p{{margin:6px 0;color:var(--muted)}}.note{{margin-top:16px;background:#ecf3f2;border-left:4px solid var(--accent);padding:12px 14px}}.table{{overflow:auto;border:1px solid var(--line);background:var(--paper)}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}thead th{{background:#eef1ee;color:var(--muted);font-size:12px}}code{{background:#eef1ee;padding:1px 4px;border-radius:4px}}@media(max-width:900px){{header,main{{padding:18px 10px}}}}
</style></head><body><header><h1>Pullback Plus 獨立版本重算</h1><p>確認 V8/V9/V10/V14/V18 是否受 PB-V4 出場日或日期切分影響，並重算成 V8+ / V9+ / V10+ / V14+ / V18+。</p><div class='note'><strong>統一規則：</strong>所有 plus 版都用股票身份做 60/20/20 切分；同一檔股票只會出現在訓練、驗證、測試其中一組。所有 plus 報酬都覆寫 PB-V4 出場日，由該版本指定的獨立出場或 runner 重新走 K 線。</div></header><main><h2>污染稽核</h2><div class='table'><table><thead><tr><th>版本</th><th>稽核結論</th></tr></thead><tbody>{audit_rows}</tbody></table></div><h2>V8+ / V9+ / V10+ / V14+ 股票切分結果</h2><div class='table'><table><thead><tr><th>版本</th><th>Plus 定義</th><th>選定規則</th><th>股票訓練</th><th>股票驗證</th><th>股票測試</th><th>全體</th></tr></thead><tbody>{comparison_rows}</tbody></table></div><h2>V18+ 股票切分結果</h2><p>V18+ 保留原本 V18 的有限持倉與 V17 runner 出場，但把評估切成股票 60/20/20；每個切片各自執行有限持倉挑選。</p><div class='table'><table><thead><tr><th>區間</th><th>股票數</th><th>組合交易數</th><th>毛報酬</th><th>成本滑價後</th></tr></thead><tbody>{v18_rows}</tbody></table></div><p>輸出檔：<code>{OUT_JSON}</code>、<code>{OUT_HTML}</code></p></main></body></html>"""


def main() -> None:
    payload = run()
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    concise = {
        "html": str(OUT_HTML),
        "json": str(OUT_JSON),
        "audit": payload["audit"],
        "v8_plus": payload["v8_plus"]["chosen"]["summaries"],
        "v9_plus_chosen": payload["v9_plus"]["chosen_exit_style"],
        "v9_plus": payload["v9_plus"]["styles"][payload["v9_plus"]["chosen_exit_style"]]["summaries"],
        "v10_plus": payload["v10_plus"]["chosen"]["summaries"],
        "v14_plus": payload["v14_plus"]["summaries"],
        "v18_plus_stress": payload["v18_plus"]["stress_summaries"],
    }
    print(json.dumps(concise, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
