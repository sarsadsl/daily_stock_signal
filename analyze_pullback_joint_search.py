#!/usr/bin/env python3
"""Jointly search constrained PB-V8 entries and PB-V9 exits with holdout."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from analyze_pullback_core_position import EXIT_LABELS, EXIT_STYLES, rebuild_exits, stats
from analyze_pullback_multitimeframe_search import enrich_trades, rule_label, rules, select


REPORT_DIR = Path("reports")
VERSION = "PB-V10.0-joint-search"
OUT_JSON = REPORT_DIR / "pullback_pb_v10_joint_search.json"
OUT_HTML = REPORT_DIR / "pullback_pb_v10_joint_search.html"


def selection_score(train: dict[str, Any], validation: dict[str, Any]) -> float:
    worst_win = min(train["win_rate_pct"], validation["win_rate_pct"])
    worst_avg = min(train["avg_return_pct"], validation["avg_return_pct"])
    worst_median = min(train["median_return_pct"], validation["median_return_pct"])
    shortfall = max(60 - worst_win, 0) * 1.0 + max(10 - worst_avg, 0) * 2.2
    instability = abs(train["win_rate_pct"] - validation["win_rate_pct"]) * 0.12 + abs(train["avg_return_pct"] - validation["avg_return_pct"]) * 0.7
    unresolved = (train["unresolved"] + validation["unresolved"]) * 0.4
    sample_bonus = min(train["trades"] + validation["trades"], 100) * 0.04
    return worst_win * 0.38 + worst_avg * 2.3 + worst_median * 0.5 + sample_bonus - shortfall - instability - unresolved


def research() -> dict[str, Any]:
    enriched, _ = enrich_trades()
    exits = rebuild_exits(enriched)
    v8 = json.loads((REPORT_DIR / "pullback_pb_v8_multitimeframe_search.json").read_text(encoding="utf-8"))
    validation_start = v8["split"]["validation_start"]
    test_start = v8["split"]["test_start"]
    candidates: list[dict[str, Any]] = []
    full_hits: list[dict[str, Any]] = []
    for exit_style in EXIT_STYLES:
        rows = exits[exit_style]
        source_segments = {
            "train": [row for row in rows if row["signal_date"] < validation_start],
            "validation": [row for row in rows if validation_start <= row["signal_date"] < test_start],
            "test": [row for row in rows if row["signal_date"] >= test_start],
            "full": rows,
        }
        for rule in rules():
            selected = {name: select(segment, rule) for name, segment in source_segments.items()}
            summaries = {name: stats(segment) for name, segment in selected.items()}
            record = {
                "entry_rule": rule,
                "entry_label": rule_label(rule),
                "exit_style": exit_style,
                "exit_label": EXIT_LABELS[exit_style],
                "summaries": summaries,
            }
            full = summaries["full"]
            if full["trades"] >= 30 and full["win_rate_pct"] >= 60 and full["avg_return_pct"] >= 10 and full["unresolved"] <= 2:
                full_hits.append(record)
            if summaries["train"]["trades"] < 20 or summaries["validation"]["trades"] < 8:
                continue
            if min(summaries["train"]["win_rate_pct"], summaries["validation"]["win_rate_pct"]) < 55:
                continue
            if min(summaries["train"]["median_return_pct"], summaries["validation"]["median_return_pct"]) < 0:
                continue
            record["score"] = selection_score(summaries["train"], summaries["validation"])
            candidates.append(record)
    candidates.sort(key=lambda item: item["score"], reverse=True)
    if not candidates:
        raise RuntimeError("No joint candidate had enough chronological samples.")
    chosen = candidates[0]
    test = chosen["summaries"]["test"]
    target_met = test["trades"] >= 10 and test["win_rate_pct"] >= 60 and test["avg_return_pct"] >= 10 and test["unresolved"] <= 2
    full_hits.sort(key=lambda item: (item["summaries"]["full"]["trades"], item["summaries"]["full"]["avg_return_pct"]), reverse=True)
    return {
        "version": VERSION,
        "candidate_count": len(rules()) * len(EXIT_STYLES),
        "eligible_candidate_count": len(candidates),
        "split": {"validation_start": validation_start, "test_start": test_start},
        "chosen": chosen,
        "target_met_on_test": target_met,
        "full_realized_target_hit_count": len(full_hits),
        "top_full_realized_target_hits": full_hits[:20],
        "top_train_validation_candidates": candidates[:20],
        "guardrails": {
            "selection": "entry and exit selected only from train+validation objective",
            "test_target": ">=10 trades, >=60% win rate, >=10% average return, <=2 unresolved",
            "full_hit_target": ">=30 trades, >=60% win rate, >=10% average return, <=2 unresolved",
        },
    }


def summary_text(value: dict[str, Any]) -> str:
    return f"{value['trades']} 筆｜勝率 {value['win_rate_pct']:.2f}%｜平均 {value['avg_return_pct']:.2f}%｜中位 {value['median_return_pct']:.2f}%｜未實現 {value['unresolved']}"


def render_html(payload: dict[str, Any]) -> str:
    chosen = payload["chosen"]
    cards = "".join(
        f"<article><span>{name}</span><strong>{html.escape(summary_text(chosen['summaries'][name]))}</strong><small>平均超額 {chosen['summaries'][name]['avg_excess_return_pct']:.2f}%</small></article>"
        for name in ("train", "validation", "test", "full")
    )
    hit_rows = "".join(
        f"<tr><td>{html.escape(item['entry_label'])}</td><td>{html.escape(item['exit_label'])}</td><td>{html.escape(summary_text(item['summaries']['full']))}</td><td>{html.escape(summary_text(item['summaries']['test']))}</td></tr>"
        for item in payload["top_full_realized_target_hits"]
    ) or "<tr><td colspan='4'>沒有低未實現部位的完整一年達標組合。</td></tr>"
    status = "留出測試達標" if payload["target_met_on_test"] else "留出測試未達標"
    tone = "pass" if payload["target_met_on_test"] else "fail"
    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PB-V10 聯合搜尋</title><style>
:root{{--bg:#f4f6f5;--paper:#fff;--ink:#17201d;--muted:#68736e;--line:#dce2df;--good:#08735d;--bad:#a33d31}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 system-ui,"Microsoft JhengHei",sans-serif}}header,main{{max-width:1480px;margin:auto;padding:26px 20px}}header{{border-bottom:1px solid var(--line)}}h1{{font-size:28px;letter-spacing:0;margin:0 0 7px}}h2{{font-size:19px;letter-spacing:0;margin:28px 0 10px}}p,small{{color:var(--muted)}}.status{{display:inline-block;padding:6px 10px;border:1px solid currentColor;font-weight:700}}.pass{{color:var(--good)}}.fail{{color:var(--bad)}}.cards{{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin:18px 0}}article{{background:var(--paper);border:1px solid var(--line);padding:14px;border-radius:6px}}article span,article strong,article small{{display:block}}.rule{{border-left:4px solid var(--good);background:#eef4f1;padding:12px 14px}}.table{{overflow:auto;background:var(--paper);border:1px solid var(--line)}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:left}}th{{font-size:12px;color:var(--muted);background:#eef1ef}}@media(max-width:760px){{.cards{{grid-template-columns:1fr}}header,main{{padding:18px 10px}}h1{{font-size:23px}}}}
</style></head><body><header><h1>PB-V10 入口＋出場聯合搜尋</h1><p>2,304 組多週期入口 × 9 種出場；只用訓練與驗證選規則，最後 20% 封存。</p><span class="status {tone}">{status}</span></header><main><div class="rule"><strong>選定入口：</strong>{html.escape(chosen['entry_label'])}<br><strong>選定出場：</strong>{html.escape(chosen['exit_label'])}</div><div class="cards">{cards}</div><h2>完整一年達標且未實現不超過 2 筆</h2><p>共 {payload['full_realized_target_hit_count']} 組；因使用完整期間，只能作探索，不能取代留出測試。</p><div class="table"><table><thead><tr><th>入口</th><th>出場</th><th>完整一年</th><th>留出測試</th></tr></thead><tbody>{hit_rows}</tbody></table></div></main></body></html>"""


def main() -> None:
    payload = research()
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    print(json.dumps({
        "candidate_count": payload["candidate_count"],
        "chosen": payload["chosen"],
        "target_met_on_test": payload["target_met_on_test"],
        "full_realized_target_hit_count": payload["full_realized_target_hit_count"],
        "html": str(OUT_HTML),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
