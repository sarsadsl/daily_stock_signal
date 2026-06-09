#!/usr/bin/env python3
"""Scan latest market data for strategy signals and send an alert message."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from plot_kline import plot_chart
from run_market_backtest import STRATEGIES, csv_files, prepare, read_rows, value_at
from signal_scoring import signal_score


REPORT_DIR = Path("reports")
DEFAULT_REPORT_PATH = REPORT_DIR / "daily_signal_alert.txt"
DEFAULT_JSON_PATH = REPORT_DIR / "daily_signal_alert.json"
DEFAULT_CHART_DIR = Path("charts/daily_alert")
MIN_SIGNAL_VOLUME_SHARES = 1_000_000
PULLBACK_PATTERN = re.compile(r"回檔|回測|拉回|支撐", re.IGNORECASE)
BREAKOUT_PATTERN = re.compile(r"突破|帶量|紅K|跳空|站回|站上|創高|攻擊", re.IGNORECASE)


def parse_multi_values(values: list[str] | None) -> set[str]:
    if not values:
        return set()
    parsed: set[str] = set()
    for value in values:
        parsed.update(item.strip() for item in value.split(",") if item.strip())
    return parsed


def latest_signals(latest_only: bool = True) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    files = csv_files()
    global_latest_date = ""

    for path in files:
        rows = read_rows(path)
        if len(rows) < 60:
            continue
        latest = rows[-1].date
        if latest > global_latest_date:
            global_latest_date = latest

    for path in files:
        rows = read_rows(path)
        if len(rows) < 60:
            continue
        if latest_only and rows[-1].date != global_latest_date:
            continue

        indicators = prepare(rows)
        index = len(rows) - 1
        row = rows[index]
        if row.volume < MIN_SIGNAL_VOLUME_SHARES:
            continue
        for strategy_name, signal in STRATEGIES.items():
            reason = signal(rows, indicators, index)
            if not reason:
                continue
            score_data = signal_score(rows, indicators, index, reason)
            matches.append(
                {
                    "market": row.market.upper(),
                    "stock_no": row.stock_no,
                    "stock_name": row.stock_name,
                    "date": row.date,
                    "strategy": strategy_name,
                    "reason": reason,
                    **score_data,
                    "close": row.close,
                    "volume": row.volume,
                    "ma5": value_at(indicators["ma5"], index),
                    "ma10": value_at(indicators["ma10"], index),
                    "ma20": value_at(indicators["ma20"], index),
                    "ma60": value_at(indicators["ma60"], index),
                    "source": str(path),
                }
            )

    matches.sort(key=lambda item: (item["market"], item["stock_no"], item["strategy"]))
    return matches


def filter_signals(
    matches: list[dict[str, Any]],
    strategies: set[str] | None = None,
    stocks: set[str] | None = None,
    markets: set[str] | None = None,
    reason_contains: str | None = None,
) -> list[dict[str, Any]]:
    strategy_filter = {value.casefold() for value in strategies or set()}
    stock_filter = {value.casefold() for value in stocks or set()}
    market_filter = {value.upper() for value in markets or set()}
    reason_filter = reason_contains.casefold() if reason_contains else ""

    filtered: list[dict[str, Any]] = []
    for item in matches:
        if strategy_filter and str(item["strategy"]).casefold() not in strategy_filter:
            continue
        if stock_filter and str(item["stock_no"]).casefold() not in stock_filter:
            continue
        if market_filter and str(item["market"]).upper() not in market_filter:
            continue
        if reason_filter and reason_filter not in str(item["reason"]).casefold():
            continue
        filtered.append(item)
    return filtered


def format_volume_lots(value: int) -> str:
    lots = value / 1000
    if lots >= 1:
        return f"{lots:,.0f}張"
    return f"{lots:.1f}張"


def format_price(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def group_matches_for_display(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in matches:
        key = (str(item["market"]), str(item["stock_no"]), str(item["date"]))
        current = grouped.get(key)
        if current is None:
            current = dict(item)
            current["reasons"] = []
            current["reason_details"] = []
            current["score_reasons"] = []
            grouped[key] = current
        reason = str(item["reason"])
        if reason not in current["reasons"]:
            current["reasons"].append(reason)
            current["reason_details"].append(
                {
                    "reason": reason,
                    "score": item.get("score"),
                    "score_reasons": item.get("score_reasons") or [],
                }
            )
        if int(item.get("score") or 0) > int(current.get("score") or 0):
            current["score"] = item.get("score")
            current["score_label"] = item.get("score_label")
        for score_reason in item.get("score_reasons") or []:
            if score_reason not in current["score_reasons"]:
                current["score_reasons"].append(score_reason)
    return sorted(grouped.values(), key=lambda item: (item["market"], item["stock_no"]))


def normalize_score(value: Any) -> int:
    try:
        score = int(float(value))
    except (TypeError, ValueError):
        score = 1
    return max(1, min(5, score))


def matching_reason_details(item: dict[str, Any], pattern: re.Pattern[str]) -> list[dict[str, Any]]:
    details = item.get("reason_details") or [
        {"reason": reason, "score": item.get("score"), "score_reasons": item.get("score_reasons") or []}
        for reason in item.get("reasons", [])
    ]
    return [detail for detail in details if pattern.search(str(detail.get("reason") or ""))]


def weighted_focus_score(item: dict[str, Any], pattern: re.Pattern[str]) -> float:
    matched_details = matching_reason_details(item, pattern)
    detail_scores = [normalize_score(detail.get("score") or item.get("score")) for detail in matched_details]
    category_score = max([*detail_scores, normalize_score(item.get("score"))])
    score_part = category_score * 20
    volume_lots = max(1.0, float(item.get("volume") or 0) / 1000)
    volume_part = min(20.0, math.log10(volume_lots) * 5)
    signal_part = min(12, max(0, (len(matched_details) or 1) - 1) * 4)
    category_part = min(12, max(1, len(matched_details)) * 4)
    return round(score_part + volume_part + signal_part + category_part, 6)


def stock_sort_key(value: Any) -> tuple[int, str]:
    text = str(value)
    return (int(text), text) if text.isdigit() else (10**9, text)


def strongest_signal_lists(matches: list[dict[str, Any]], count: int = 5) -> dict[str, list[dict[str, Any]]]:
    grouped = group_matches_for_display(matches)
    pullbacks = [item for item in grouped if matching_reason_details(item, PULLBACK_PATTERN)]
    breakouts = [item for item in grouped if matching_reason_details(item, BREAKOUT_PATTERN)]

    for item in pullbacks:
        item["weighted_score"] = weighted_focus_score(item, PULLBACK_PATTERN)
    for item in breakouts:
        item["weighted_score"] = weighted_focus_score(item, BREAKOUT_PATTERN)

    def rank_key(item: dict[str, Any]) -> tuple[float, int, int, tuple[int, str]]:
        return (
            float(item.get("weighted_score") or 0),
            normalize_score(item.get("score")),
            int(item.get("volume") or 0),
            tuple(-part if isinstance(part, int) else part for part in stock_sort_key(item.get("stock_no"))),
        )

    pullbacks.sort(key=rank_key, reverse=True)
    breakouts.sort(key=rank_key, reverse=True)
    return {
        "pullback": pullbacks[:count],
        "breakout": breakouts[:count],
    }


def chart_sources_for_top_lists(top_lists: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for list_items in top_lists.values():
        for item in list_items:
            selected.append(item)
    return selected


def build_ranked_signal_text(title: str, rank: int, item: dict[str, Any]) -> str:
    lines = [
        f"{title} 第{rank}名",
        f"{item['stock_no']} {item['stock_name']} ({item['market']})",
        f"訊號: {'、'.join(item['reasons'])}",
        f"評分: {item.get('score_label', '-')}",
    ]
    if item.get("score_reasons"):
        lines.append(f"依據: {'、'.join(item['score_reasons'][:3])}")
    lines.extend(
        [
            f"收盤: {format_price(item['close'])} 量: {format_volume_lots(int(item['volume']))}",
            (
                "均線: "
                f"5MA {format_price(item['ma5'])}, "
                f"10MA {format_price(item['ma10'])}, "
                f"20MA {format_price(item['ma20'])}, "
                f"60MA {format_price(item['ma60'])}"
            ),
        ]
    )
    if item.get("volume_ratio"):
        lines.append(f"量能: 20日均量 {float(item['volume_ratio']):.2f}x")
    if item.get("weighted_score"):
        lines.append(f"看板加權分: {float(item['weighted_score']):.2f}")
    if item.get("chart_path"):
        lines.append(f"K線圖: {item['chart_path']}")
    return "\n".join(lines)


def build_top_lists_message(top_lists: dict[str, list[dict[str, Any]]], signal_date: str) -> str:
    now_text = datetime.now().strftime("%Y-%m-%d %H:%M")
    pullback_count = len(top_lists["pullback"])
    breakout_count = len(top_lists["breakout"])
    return "\n".join(
        [
            f"每日策略警示 {now_text}",
            f"訊號日期: {signal_date}",
            f"本次只推送回檔最強前{pullback_count}名、突破最強前{breakout_count}名。",
            "每一名會各自附上一張 K 線圖。",
            "提醒: 這是策略篩選結果，進場前仍請搭配風險控管與部位規劃。",
        ]
    )


def build_message(matches: list[dict[str, Any]], max_items: int = 30) -> str:
    now_text = datetime.now().strftime("%Y-%m-%d %H:%M")
    if not matches:
        return f"每日策略警示 {now_text}\n今日沒有股票符合策略進場條件。"

    display_matches = group_matches_for_display(matches)
    signal_date = matches[0]["date"]
    lines = [
        f"每日策略警示 {now_text}",
        f"訊號日期: {signal_date}",
        f"符合股票: {len(display_matches)} 檔",
        "",
    ]
    visible_matches = display_matches[:max_items] if max_items > 0 else display_matches
    for index, item in enumerate(visible_matches, start=1):
        lines.extend(
            [
                f"{index}. {item['stock_no']} {item['stock_name']} ({item['market']})",
                f"   訊號: {'、'.join(item['reasons'])}",
                f"   評分: {item.get('score_label', '-')}",
                *([f"   依據: {'、'.join(item['score_reasons'][:3])}"] if item.get("score_reasons") else []),
                f"   收盤: {format_price(item['close'])} 量: {format_volume_lots(int(item['volume']))}",
                (
                    "   均線: "
                    f"5MA {format_price(item['ma5'])}, "
                    f"10MA {format_price(item['ma10'])}, "
                    f"20MA {format_price(item['ma20'])}, "
                    f"60MA {format_price(item['ma60'])}"
                ),
                *([f"   K線圖: {item['chart_path']}"] if item.get("chart_path") else []),
                "",
            ]
        )
    if len(display_matches) > len(visible_matches):
        lines.append(f"還有 {len(display_matches) - len(visible_matches)} 檔，完整清單請看 reports/daily_signal_alert.csv")
        lines.append("")
    lines.append("提醒: 這是策略篩選結果，進場前仍請搭配風險控管與部位規劃。")
    return "\n".join(lines)


def post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        response.read()


def post_multipart(url: str, fields: dict[str, str], files: dict[str, Path]) -> None:
    boundary = f"----stock-alert-{uuid4().hex}"
    body_parts: list[bytes] = []

    for name, value in fields.items():
        body_parts.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )

    for name, path in files.items():
        filename = path.name
        body_parts.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                (
                    f'Content-Disposition: form-data; name="{name}"; '
                    f'filename="{filename}"\r\n'
                ).encode("utf-8"),
                b"Content-Type: image/png\r\n\r\n",
                path.read_bytes(),
                b"\r\n",
            ]
        )

    body_parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(body_parts)
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        response.read()


def line_image_url(path: Path, base_url: str) -> str:
    return f"{base_url.rstrip('/')}/{path.name}"


def send_line_message(message: str, image_urls: list[str] | None = None) -> bool:
    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    user_id = os.getenv("LINE_USER_ID")
    if not token or not user_id:
        return False
    messages: list[dict[str, str]] = [{"type": "text", "text": message[:5000]}]
    for image_url in (image_urls or [])[:4]:
        messages.append(
            {
                "type": "image",
                "originalContentUrl": image_url,
                "previewImageUrl": image_url,
            }
        )
    post_json(
        "https://api.line.me/v2/bot/message/push",
        {"to": user_id, "messages": messages},
        {"Authorization": f"Bearer {token}"},
    )
    return True


def send_telegram_message(message: str, image_paths: list[Path] | None = None) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False
    post_json(
        f"https://api.telegram.org/bot{token}/sendMessage",
        {"chat_id": chat_id, "text": message},
    )
    for image_path in image_paths or []:
        if not image_path.exists():
            continue
        post_multipart(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            {
                "chat_id": chat_id,
                "caption": image_path.stem,
            },
            {"photo": image_path},
        )
    return True


def send_telegram_ranked_messages(top_lists: dict[str, list[dict[str, Any]]]) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False

    for title, key in (("回檔最強", "pullback"), ("突破最強", "breakout")):
        for rank, item in enumerate(top_lists[key], start=1):
            text = build_ranked_signal_text(title, rank, item)
            chart_path = Path(str(item["chart_path"])) if item.get("chart_path") else None
            if chart_path and chart_path.exists():
                post_multipart(
                    f"https://api.telegram.org/bot{token}/sendPhoto",
                    {
                        "chat_id": chat_id,
                        "caption": text[:1024],
                    },
                    {"photo": chart_path},
                )
            else:
                post_json(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    {"chat_id": chat_id, "text": text},
                )
    return True


def send_webhook_message(message: str) -> bool:
    url = os.getenv("ALERT_WEBHOOK_URL")
    if not url:
        return False
    post_json(url, {"content": message, "text": message})
    return True


def send_message(
    message: str,
    channels: set[str] | None = None,
    image_urls: list[str] | None = None,
    image_paths: list[Path] | None = None,
) -> list[str]:
    enabled_channels = {channel.casefold() for channel in channels or set()}

    def channel_enabled(name: str) -> bool:
        return not enabled_channels or name in enabled_channels

    sent: list[str] = []
    if channel_enabled("line") and send_line_message(message, image_urls=image_urls):
        sent.append("line")
    if channel_enabled("telegram") and send_telegram_message(message, image_paths=image_paths):
        sent.append("telegram")
    if channel_enabled("webhook") and send_webhook_message(message):
        sent.append("webhook")
    return sent


def generate_signal_charts(matches: list[dict[str, Any]], limit: int, output_dir: Path) -> list[Path]:
    if limit <= 0:
        return []

    chart_paths: list[Path] = []
    chart_by_source: dict[str, Path] = {}
    for item in matches:
        if len(chart_paths) >= limit:
            break

        source = str(item["source"])
        if source in chart_by_source:
            item["chart_path"] = str(chart_by_source[source])
            continue

        chart_path = plot_chart(Path(source), output_dir)
        chart_by_source[source] = chart_path
        item["chart_path"] = str(chart_path)
        chart_paths.append(chart_path)
    return chart_paths


def write_reports(matches: list[dict[str, Any]], message: str) -> None:
    REPORT_DIR.mkdir(exist_ok=True)
    DEFAULT_REPORT_PATH.write_text(message, encoding="utf-8")
    DEFAULT_JSON_PATH.write_text(json.dumps(matches, ensure_ascii=False, indent=2), encoding="utf-8")

    csv_path = REPORT_DIR / "daily_signal_alert.csv"
    fieldnames = [
        "market",
        "stock_no",
        "stock_name",
        "date",
        "strategy",
        "reason",
        "score",
        "score_label",
        "score_reasons",
        "volume_ratio",
        "ma20_slope_pct",
        "ma60_slope_pct",
        "close",
        "volume",
        "ma5",
        "ma10",
        "ma20",
        "ma60",
        "source",
        "chart_path",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for item in matches:
            row = dict(item)
            if isinstance(row.get("score_reasons"), list):
                row["score_reasons"] = "、".join(str(reason) for reason in row["score_reasons"])
            writer.writerow(row)


def write_top_list_reports(top_lists: dict[str, list[dict[str, Any]]]) -> None:
    REPORT_DIR.mkdir(exist_ok=True)
    output = {
        "pullback": top_lists["pullback"],
        "breakout": top_lists["breakout"],
    }
    (REPORT_DIR / "daily_signal_top_lists.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan latest TWSE/TPEx CSV data and send strategy alerts.")
    parser.add_argument("--all-dates", action="store_true", help="Scan each file's own latest date instead of one global latest date.")
    parser.add_argument("--dry-run", action="store_true", help="Write reports and print the message without sending notifications.")
    parser.add_argument("--max-items", type=int, default=int(os.getenv("ALERT_MAX_ITEMS", "30")), help="Maximum matching rows to include in the pushed text message.")
    parser.add_argument("--send-empty", action="store_true", help="Send a notification even when no stocks match.")
    parser.add_argument("--top-lists", action="store_true", help="Send only strongest pullback and breakout lists.")
    parser.add_argument("--top-count", type=int, default=int(os.getenv("ALERT_TOP_COUNT", "5")), help="Number of ranked items per top list.")
    parser.add_argument(
        "--chart-items",
        type=int,
        default=int(os.getenv("ALERT_CHART_ITEMS", "0")),
        help="Generate K-line PNG charts for the first N matching stocks.",
    )
    parser.add_argument(
        "--chart-output-dir",
        type=Path,
        default=DEFAULT_CHART_DIR,
        help="Directory for generated alert K-line charts.",
    )
    parser.add_argument("--strategy", action="append", help="Only include this strategy name. Can be repeated or comma-separated.")
    parser.add_argument("--stock", action="append", help="Only include this stock number. Can be repeated or comma-separated.")
    parser.add_argument("--market", action="append", help="Only include this market: twse or tpex. Can be repeated or comma-separated.")
    parser.add_argument("--reason-contains", help="Only include signals whose reason text contains this value.")
    parser.add_argument(
        "--channel",
        action="append",
        help="Only send through this notification channel. Can be repeated or comma-separated.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    markets = parse_multi_values(args.market)
    unknown_markets = {market for market in markets if market.upper() not in {"TWSE", "TPEX"}}
    if unknown_markets:
        print(f"Unknown market: {', '.join(sorted(unknown_markets))}. Use twse or tpex.", file=sys.stderr)
        return 2

    channels = parse_multi_values(args.channel)
    unknown_channels = {channel for channel in channels if channel.casefold() not in {"line", "telegram", "webhook"}}
    if unknown_channels:
        print(f"Unknown channel: {', '.join(sorted(unknown_channels))}. Use line, telegram, or webhook.", file=sys.stderr)
        return 2

    matches = latest_signals(latest_only=not args.all_dates)
    matches = filter_signals(
        matches,
        strategies=parse_multi_values(args.strategy),
        stocks=parse_multi_values(args.stock),
        markets=markets,
        reason_contains=args.reason_contains,
    )
    chart_paths = generate_signal_charts(matches, limit=args.chart_items, output_dir=args.chart_output_dir)
    top_lists: dict[str, list[dict[str, Any]]] | None = None
    if args.top_lists:
        top_lists = strongest_signal_lists(matches, count=args.top_count)
        chart_targets = chart_sources_for_top_lists(top_lists)
        chart_paths = generate_signal_charts(chart_targets, limit=len(chart_targets), output_dir=args.chart_output_dir)
        signal_date = matches[0]["date"] if matches else "-"
        message = build_top_lists_message(top_lists, signal_date)
        write_top_list_reports(top_lists)
    else:
        message = build_message(matches, max_items=args.max_items)
    write_reports(matches, message)
    print(message)

    if args.dry_run:
        return 0
    if not matches and not args.send_empty:
        print("No matches found. Reports were written; notification was skipped.")
        return 0

    try:
        image_base_url = os.getenv("ALERT_IMAGE_BASE_URL", "").strip()
        image_urls = [line_image_url(path, image_base_url) for path in chart_paths] if image_base_url else []
        sent = send_message(message, channels=channels, image_urls=image_urls, image_paths=[] if args.top_lists else chart_paths)
        if top_lists and ("telegram" in {channel.casefold() for channel in channels} or not channels):
            if send_telegram_ranked_messages(top_lists):
                if "telegram" not in sent:
                    sent.append("telegram")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"Notification failed: {exc}", file=sys.stderr)
        return 2

    if not sent:
        print(
            "No notification channel configured. Set LINE_CHANNEL_ACCESS_TOKEN/LINE_USER_ID, "
            "TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID, or ALERT_WEBHOOK_URL.",
            file=sys.stderr,
        )
        return 1
    print(f"Notification sent via: {', '.join(sent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
